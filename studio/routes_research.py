"""Research board endpoints: boards, items, layout, moving, search, clipping pages, using an item in the text, and a
board's files.

Thin wrappers over research.Research. A new Research(config.ART) per request, because the library can change in
Settings. ResearchError carries its status (400, 404, 409) and details (a stale update's `current`); a 409 without
`current` is a board that stayed busy. Handler._guard sends them all as they are (a ClipError is a 400 with its
reason). `b` (query or body) is a book's id; missing, empty or null it is the shared board.
"""
import base64
import hashlib
import io
import os
import subprocess
import sys
import threading

from . import config, routes
from .research import SHARED_URL, Research, ResearchError

THUMBS = (160, 320, 480, 640, 960)
YEAR = "max-age=31536000, immutable"


def _research():
    return Research(config.ART)


def _board(v):
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise ResearchError("Say which board: a book's id, or nothing for the shared board.")
    return v


def _flag(v):
    return v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")


def _id(v):
    if not isinstance(v, str) or not v:
        raise ResearchError("Say which item.", 404)
    return v


def _fields(body):
    fields = body.get("fields")
    if not isinstance(fields, dict):
        raise ResearchError("Send the fields.")
    return fields


@routes.get("/api/research/boards")
def boards(h, q):
    h._send(200, _research().boards())


@routes.get("/api/research")
def board_read(h, q):
    h._send(200, _research().read(_board(q.get("b"))))


@routes.get("/api/research/stamp")
def board_stamp(h, q):
    h._send(200, {"stamp": _research().stamp(_board(q.get("b")), _flag(q.get("every")))})


@routes.get("/api/research/item")
def item_read(h, q):
    h._send(200, _research().item(_board(q.get("b")), _id(q.get("id"))))


@routes.post("/api/research/item")
def item_add(h, body):
    h._send(200, _research().add(_board(body.get("b")), _fields(body), body.get("at"), body.get("frame")))


@routes.post("/api/research/update")
def item_update(h, body):
    h._send(200, _research().update(_board(body.get("b")), _id(body.get("id")), _fields(body), body.get("base_mtime"),
                                    _flag(body.get("force"))))


@routes.post("/api/research/delete")
def item_delete(h, body):
    gone = _research().delete(_board(body.get("b")), body.get("ids"))
    h._send(200, {"trash": [os.path.basename(p) for p in gone]})


@routes.post("/api/research/restore")
def item_restore(h, body):
    h._send(200, {"items": _research().restore(_board(body.get("b")), body.get("names"))})


@routes.post("/api/research/layout")
def board_layout(h, body):
    h._send(200, _research().layout(_board(body.get("b")), body.get("items"), body.get("frames"), body.get("remove_frames")))


@routes.post("/api/research/move")
def items_move(h, body):
    """{"items": [...]}: the items as they are on the other board, each with `warnings` when a board stayed busy."""
    h._send(200, {"items": _research().move(_board(body.get("b")), body.get("ids"), body.get("to"), _flag(body.get("link")))})


@routes.post("/api/research/image")
def image_add(h, body):
    data = body.get("data")
    if not isinstance(data, str) or not data:
        raise ResearchError("There is no image.")
    try:
        raw = base64.b64decode(data, validate=True)
    except ValueError:
        raise ResearchError("The image couldn't be read.") from None
    fields = body.get("fields")
    h._send(200, _research().add_image(_board(body.get("b")), str(body.get("name") or ""), raw,
                                       fields if fields is not None else None, body.get("at"), body.get("frame")))


@routes.post("/api/research/clip")
def clip_add(h, body):
    """The page at `url` clipped (fetched, read and photographed in this request): the new item, a clip or an image,
    with `warning` when its picture couldn't be taken. With `id`, that clip is clipped again (from its own address
    when `url` is missing)."""
    url, again = body.get("url"), body.get("id")
    if url is not None and not isinstance(url, str):
        raise ResearchError("Say which page to clip.")
    h._send(200, _research().clip(_board(body.get("b")), url, body.get("at"), body.get("frame"),
                                  id=None if again in (None, "") else _id(again)))


@routes.post("/api/research/reveal")
def reveal(h, body):
    """Show an item's file (a clip's PDF, an image) in the system's file manager."""
    board, r = _board(body.get("b")), _research()
    item = r.item(board, _id(body.get("id")))
    name = item.get("file")
    if not isinstance(name, str) or not name:
        raise ResearchError("This item has no file to show.")
    home = item["link"]["board"] if item.get("link") else board        # a link's file is its original's
    target = r.file(f"{SHARED_URL if home is None else home}/{os.path.basename(name.replace(chr(92), '/'))}")
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(target)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target.parent)])
    h._send(200, {"ok": True})


@routes.get("/api/research/search")
def search(h, q):
    h._send(200, _research().search(q.get("q", ""), _board(q.get("b")), _flag(q.get("every"))))


@routes.get("/api/research/citable")
def citable(h, q):
    h._send(200, _research().citable(_board(q.get("b"))))


@routes.post("/api/research/use")
def use(h, body):
    book = body.get("book")
    if not isinstance(book, str):
        raise ResearchError("Say which book.")
    h._send(200, _research().use(book, _board(body.get("b")), _id(body.get("id"))))


def _thumbnail(path, w):
    """The JPEG of `path` at most w wide (first frame, turned as its EXIF says, transparency on white), from the cache
    folder, made there when missing. None when Pillow can't read the file or the cache folder can't be used (the file
    is then served as it is)."""
    st = path.stat()
    key = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}|{w}".encode("utf-8")).hexdigest()
    cached = config.CACHE / "research-thumbs" / f"{key}.jpg"
    try:
        if cached.is_file():
            return cached.read_bytes()
    except OSError:
        return None
    from PIL import Image, ImageOps
    try:
        with Image.open(path) as im:
            im.seek(0)
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
                im = im.convert("RGBA")
                paper = Image.new("RGB", im.size, (255, 255, 255))
                paper.paste(im, mask=im.getchannel("A"))
                im = paper
            else:
                im = im.convert("RGB")
            im.thumbnail((w, w * 10))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=82)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None
    data = out.getvalue()
    tmp = cached.with_name(f".{cached.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp.write_bytes(data)
            os.replace(tmp, cached)
        finally:
            tmp.unlink(missing_ok=True)
    except OSError:
        return None
    return data


@routes.get_prefix("/researchfiles/")
def research_file(h, rest, q):
    """A board's image, picture or PDF, /researchfiles/<_shared or a book id>/<name>; `w` (one of THUMBS) asks for a JPEG
    thumbnail. A PDF is sent as a download. `rest` comes decoded already (Handler._get decodes the path once)."""
    path = _research().file(rest)
    if path.suffix.lower() == ".pdf":
        return h._send(200, path.read_bytes(), "application/pdf",
                       headers={"Content-Disposition": "attachment"})
    w = q.get("w", "")
    if w.isdigit() and int(w) in THUMBS:
        data = _thumbnail(path, int(w))
        if data is not None:
            return h._send(200, data, "image/jpeg", cache=YEAR)
    h._file(path)
