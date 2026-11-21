"""The composer: a book's pages, from its files to Typst's output.

Spec: docs/superpowers/specs/2026-11-13-books-part-2-design.md ("Preview", "PDF", "Server", "Hooks for part 4"). The
web routes, the print checks and Claude's tools all come here: nothing else compiles a book.

A compile, per book:
  1. The signature: book.json's bytes, each piece file's and each image's (name, mtime, size), sources.json's and the
     linked poems' poem.json times, and the resolved design. An unchanged signature means unchanged pages, so the last
     result is given without compiling. Every file is looked at before it is read, so a save made during a compile
     always gives the next call a fresh one.
  2. Staging, in STUDIO_CACHE/compose/<sha1 of the book folder>/: copies of the book's images (grey ones for a grey
     interior), refreshed by modification time, and main.typ, the source typeset_book writes. The compiler's root is
     this folder and its package folders an empty one, so a book reads nothing outside it but the cut fonts.
  3. Typst compiles main.typ to SVG pages, and one query reads the page facts the template leaves: `<page-info>` per
     page and the `<blk>`, `<blkend>`, `<piece-start>` and `<piece-end>` markers.

One job per book at a time: a lock per book in this process, and a lock file in the staging folder across processes
(Claude's MCP server is another process and compiles for itself). Each process keeps its own compilers and pages;
nothing depends on the web server's memory.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import os
import posixpath
import re
import shutil
import threading
import time
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import typst
from PIL import Image, ImageOps

from . import book_design, book_export, config, fonts, printers, typeset, typeset_book, typeset_fonts
from .books import BOOK_FILE, IMAGE_TYPES, NOTES, UNREADABLE, BooksError
from .store import write_text

LOCK_WAIT = 60.0            # seconds a compile waits for another process's compile of the same book
PAGE_CACHE = 4000           # SVG pages kept in this process, by hash
MAX_PPI = 300               # the finest PNG render_pages draws
_BOOKISH = {"serif": 0, "sans": 1}          # the categories books are set in, listed first

# The page facts, read in one query after a compile. Positions are Typst's: the physical page (1-based) and y in pt
# from the top of the page.
_FACTS = """(
  info: query(<page-info>).map(m => m.value),
  blk: query(<blk>).map(m => { let at = m.location().position(); (m.value.p, m.value.b, at.page, at.y.pt()) }),
  blkend: query(<blkend>).map(m => { let at = m.location().position(); (m.value.p, m.value.b, at.page, at.y.pt()) }),
  starts: query(<piece-start>).map(m => { let at = m.location().position(); (m.value, at.page, at.y.pt()) }),
  ends: query(<piece-end>).map(m => { let at = m.location().position(); (m.value, at.page, at.y.pt()) }),
)"""


@dataclass
class Compiled:
    """One compile of a book. `pages` are `{"hash", "folio", "side", "entry", "blank", "shown"}` per page, `entry`
    being the contents index of the last piece or generated page that started on or before it. `blocks` maps each
    piece's file to the page (0-based) of each of its top-level blocks. `markers` holds the raw marker positions for
    the print checks: `blk` and `blkend` as {"p", "b", "page", "y"}, `piece-start` and `piece-end` as {"i", "page",
    "y"}, `page` 1-based and `y` in pt. After a Typst error, `error` holds its message and everything else is the
    last good compile's."""
    signature: str
    svgs: list = field(default_factory=list)
    hashes: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    blocks: dict = field(default_factory=dict)
    markers: dict = field(default_factory=dict)
    ctx: typeset.Context | None = None
    fonts: dict | None = None
    seconds: float = 0.0
    warnings: list = field(default_factory=list)
    error: str | None = None
    pdf: bytes | None = None
    design: dict = field(default_factory=dict)      # the resolved design the pages were set with
    staging: Path | None = None                     # the folder Typst compiled from
    left_out: dict = field(default_factory=dict)    # contents index -> why its generated page isn't in the pages


# ---------------------------------------------------------------------------------------------------------
# The design

def _fonts_list() -> list[str]:
    families = sorted(fonts.registry().families(), key=lambda f: (_BOOKISH.get(f.category, 2), f.name.lower()))
    return [f.name for f in families]


def get_design(books, book) -> dict:
    """The resolved design, what book.json stores of it, and the choices the design panel offers. Each printer comes
    with its smallest margins (`min`, and `inside` by page count as printers.py keeps them), so the panel can show
    them beside the margins."""
    meta = books.read(book)
    stored = meta.get("design") if isinstance(meta.get("design"), dict) else {}
    return {"design": book_design.resolve(meta, meta.get("style")), "stored": stored,
            "templates": [{"id": k, "name": t["name"]} for k, t in book_design.TEMPLATES.items()],
            "trims": [{"id": k, "name": book_design.TRIM_NAMES[k], "width": w, "height": h}
                      for k, (w, h) in book_design.TRIMS.items()]
            + [{"id": "custom", "name": "Custom size", "width": None, "height": None}],
            "printers": [{"id": k, "name": p["name"], "min": dict(p["min"]), "inside": [list(r) for r in p["inside"]]}
                         for k, p in printers.PRINTERS.items()],
            "fonts": _fonts_list()}


def set_design(books, book, changes: dict | None = None, template: str | None = None, reset=()) -> dict:
    """Changes the stored design (`reset` first, then `template` and `changes`) and gives it back as `get_design`
    does. Values are checked by book_design; a bad one is a BooksError with a plain sentence."""
    if changes is not None and not isinstance(changes, dict):
        raise BooksError("The design is an object.")
    design = dict(changes or {})
    if template is not None:
        design["template"] = template
    fields = {}
    if reset:
        fields["design_reset"] = reset
    if design:
        fields["design"] = design
    if fields:
        books.update(book, fields)
    return get_design(books, book)


# ---------------------------------------------------------------------------------------------------------
# Jobs and the lock across processes

class _Job:
    """One book's compiling in this process: its lock, its compiler and the last result."""

    def __init__(self, staging: Path):
        self.lock = threading.Lock()
        self.staging = staging
        self.compiler = None
        self.compiler_fonts = None      # the font folder the compiler was made with
        self.compiled = None            # the last result; after an error it carries the last good pages
        self.source = None              # main.typ as this process last set it
        self.linked = ()                # the linked poems at the last compile: their files go into the signature
        self.title = ""                 # the book's title, for the message when another process holds it


_JOBS = {}
_JOBS_LOCK = threading.Lock()


def staging_dir(d: Path) -> Path:
    """The folder a book is compiled from: STUDIO_CACHE/compose/<sha1 of the book folder's path>."""
    return config.CACHE / "compose" / hashlib.sha1(str(d).encode("utf-8")).hexdigest()


def _job(books, book):
    d = books.dir(book)
    with _JOBS_LOCK:
        job = _JOBS.get(str(d))
        if job is None:
            job = _JOBS[str(d)] = _Job(staging_dir(d))
    return d, job


def _busy(title) -> BooksError:
    return BooksError(f"{title} is being set in another window; try again in a moment.", 409)


@contextlib.contextmanager
def _book_lock(job, d: Path):
    """The book's lock in this process, waited for no longer than another process's lock file (LOCK_WAIT): the
    request holding it may itself be waiting that long for another process."""
    if not job.lock.acquire(timeout=LOCK_WAIT):
        raise _busy(job.title or d.name)
    try:
        yield
    finally:
        job.lock.release()


if os.name == "nt":
    import msvcrt

    def _try_lock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class _StagingLock:
    """The staging folder's lock file, held while one process stages and compiles. The OS lets go of it when that
    process ends, so a crash never leaves a book locked; a process that waits longer than LOCK_WAIT gives up."""

    def __init__(self, folder: Path, title: str):
        self.folder, self.title, self.f = folder, title, None

    def __enter__(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.f = open(self.folder / ".lock", "a+b")
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                _try_lock(self.f)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.f.close()
                    raise _busy(self.title) from None
                time.sleep(0.1)

    def __exit__(self, *exc):
        try:
            _unlock(self.f)
        finally:
            self.f.close()


# ---------------------------------------------------------------------------------------------------------
# The signature

def _stat(path: Path):
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _images(d: Path) -> dict:
    """The book's own images by name: files right in images/ of an image type, never a link that leaves the folder."""
    folder = d / "images"
    try:
        entries = list(os.scandir(folder))
        real = folder.resolve()
    except OSError:
        return {}
    out = {}
    for e in entries:
        p = Path(e.path)
        if e.name.startswith(".") or p.suffix.lower() not in IMAGE_TYPES:
            continue
        try:
            if e.is_file() and p.resolve().parent == real:
                out[e.name] = p
        except OSError:
            continue
    return out


def _poem_file(books, src):
    """A linked poem's poem.json, by the rule Books.linked_poem reads it by (Series/Poem, nothing else)."""
    parts = str(src).split("/")
    if len(parts) == 2 and all(p and p not in (".", "..") and "\\" not in p and ":" not in p for p in parts):
        return books.root.parent / "Poems" / parts[0] / parts[1] / "poem.json"
    return None


def _poems(books, srcs) -> list:
    return [(src, _stat(f) if (f := _poem_file(books, src)) else None) for src in sorted(srcs)]


def _families(design) -> list:
    """Whether the design's families are there: a family added to the library sets the book in it, not in Literata."""
    names = [(design.get("text") or {}).get("font"), (design.get("headings") or {}).get("font")]
    out = []
    for name in (n for n in names if n):
        fam = fonts.registry().get(name)
        out.append([name, fam.name, fam.embeddable, len(fam.files)] if fam else [name, None])
    return out


def _base(d: Path, raw: bytes, meta: dict, design: dict) -> list:
    """Everything of the signature but the linked poems, looked at before any of it is read."""
    parts = [hashlib.sha1(raw).hexdigest()]
    for e in meta["contents"]:
        if e.get("file"):
            parts.append(["piece", e["file"], _stat(d / "manuscript" / e["file"])])
    for name, p in sorted(_images(d).items()):
        parts.append(["image", name, _stat(p)])
    parts.append(["sources", _stat(d / "sources.json")])
    parts.append(["fonts", _families(design)])
    parts.append(["design", design])
    return parts


def _digest(base: list, poems: list) -> str:
    return hashlib.sha1(json.dumps([base, poems], sort_keys=True, default=str).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------------------
# Reading and staging

def _unreadable(file) -> str:
    return (f"{file} isn't readable text (Studio reads pieces as UTF-8), so the book can't be set. Save that file as "
            f"UTF-8 and try again.")


def _walk(n, images: set, poems: set):
    """The image and linked-poem sources anywhere in a document."""
    if not isinstance(n, dict):
        return
    attrs = n.get("attrs") if isinstance(n.get("attrs"), dict) else {}
    if attrs.get("src") and n.get("type") == "image":
        images.add(str(attrs["src"]))
    elif attrs.get("src") and n.get("type") == "poem":
        poems.add(str(attrs["src"]))
    for c in n.get("content") if isinstance(n.get("content"), list) else []:
        _walk(c, images, poems)


def _read(books, book, meta):
    """[(i, entry, doc | None)] for typeset_book, the documents by contents index, and the sources of their images
    and linked poems. Missing pieces are left out, as the other exports leave them out."""
    pieces, docs, images, poems = [], {}, set(), set()
    for i, e in enumerate(meta["contents"]):
        if e.get("auto") is not None:
            pieces.append((i, e, None))
            continue
        if not e.get("file") or e.get("missing"):
            continue
        try:
            doc = books.piece(book, e["file"])["doc"]
        except BooksError as err:
            if err.code == 404:
                continue                    # gone since the book was read
            if str(err) == UNREADABLE:      # it stopped being UTF-8 since the book was read: say which piece
                raise BooksError(_unreadable(e["file"])) from None
            raise
        pieces.append((i, e, doc))
        docs[i] = doc
        _walk(doc, images, poems)
    return pieces, docs, images, poems


def _image_name(src):
    """The file name in images/ an image's `src` points at (manuscript/../images/<name>), or None for anything else:
    a src that leaves images/ is never staged, so it is set as missing."""
    s = str(src or "")
    if not s or "\\" in s or ":" in s or s.startswith("/"):
        return None
    folder, _, name = posixpath.normpath(posixpath.join("manuscript", s)).partition("/")
    return name if folder == "images" and name and "/" not in name else None


_DEEP = ("I", "I;16", "I;16B", "I;16L", "I;16N")        # 16-bit grey (a 16-bit grey PNG opens as I;16)
_ALPHA = ("RGBA", "LA", "PA", "RGBa", "La")
_ORIENTATION = 0x0112                                    # the EXIF tag that says how a photo is turned


def _grey(im):
    """`im` as 8-bit grey: L, or LA when it has transparency. Pillow clips 16-bit and float pixels when it converts
    them to L (20000 of 65535 would become 255, white), so those are scaled to 8 bits first (20000 becomes 78)."""
    if im.mode in _DEEP:
        return im.convert("I").point(lambda v: v / 256).convert("L")
    if im.mode == "F":                      # float pixels: 0–1, 0–255 or 16-bit values, by their brightest
        top = im.getextrema()[1] or 0
        scale = 255 if top <= 1 else 1 if top <= 255 else 1 / 256
        return im.point(lambda v: v * scale).convert("L")
    if im.mode in _ALPHA or "transparency" in im.info:
        return im.convert("RGBA").convert("LA")
    return im.convert("L")


def _copy_image(src: Path, dest: Path, grey: bool, mtime: int):
    """The staged copy. For a grey interior: 8-bit grey (`_grey`), turned as the photo's EXIF says, as a PNG unless
    the image is a JPEG; an image that is already 8-bit grey, upright and of the same type is copied as it is, so a
    grey JPEG isn't encoded twice. For a colour interior: the file itself. Either way Pillow reads the image first,
    so a broken file is set as missing instead of stopping Typst.
    The copy is dated `mtime`, the source's time from before it was read: an image replaced during the copy then
    differs from its copy's date, and the next compile copies it again."""
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with Image.open(src) as im:
            same = src.suffix.lower() == dest.suffix.lower()
            if grey and not (same and im.mode in ("1", "L", "LA") and im.getexif().get(_ORIENTATION, 1) == 1):
                out = _grey(ImageOps.exif_transpose(im))
                if dest.suffix.lower() in (".jpg", ".jpeg"):
                    out.convert("L").save(tmp, "JPEG", quality=95)
                else:
                    out.save(tmp, "PNG")
            else:
                im.load()                   # the whole image decodes: Typst will be able to read it
                shutil.copyfile(src, tmp)
        os.utime(tmp, ns=(mtime, mtime))
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def _stage_images(d: Path, staging: Path, grey: bool) -> dict:
    """Copies the book's images into staging/images/ and returns {name in lower case: path from the staging root}.
    A copy is made again when its source's modification time differs; all of them when the interior changes."""
    folder, marker = staging / "images", staging / ".interior"
    mode = "grey" if grey else "colour"
    try:
        was = marker.read_text(encoding="utf-8")
    except OSError:
        was = None
    if was != mode:
        shutil.rmtree(folder, ignore_errors=True)
        marker.write_text(mode, encoding="utf-8")
    folder.mkdir(parents=True, exist_ok=True)
    out, keep = {}, set()
    for name, src in sorted(_images(d).items()):
        # GIF and WebP can't hold grey pixels as such (WebP decodes as RGB): their grey copies are PNGs
        target = name + ".png" if grey and src.suffix.lower() in (".gif", ".webp") else name
        dest = folder / target
        try:
            have, want = _stat(dest), _stat(src)       # the source's time before it is read (see _copy_image)
            if want is None:
                continue
            if have is None or have[0] != want[0]:
                _copy_image(src, dest, grey, want[0])
        except Exception:       # noqa: BLE001 — not an image Pillow can read: set as missing
            dest.unlink(missing_ok=True)
            continue
        out[name.lower()] = f"images/{target}"
        keep.add(target)
    for p in folder.iterdir():
        if p.name not in keep and p.is_file():
            p.unlink(missing_ok=True)
    return out


def _roles(design) -> dict:
    """The faces to cut: the text at its size's optical size, and the headings when they have a family of their own."""
    text, headings = design["text"], design["headings"]
    roles = {"text": {"family": text["font"], "weight": text["weight"], "opsz": text["size"]}}
    if headings.get("font"):
        roles["heading"] = {"family": headings["font"], "weight": text["weight"], "opsz": headings["size"]}
    return roles


# The families being cut for print, per book folder, while that book's compile waits for them. The first compile in
# a new family, weight or optical size cuts its four faces (some 18 s); the viewer asks (`cutting`) and says so
# instead of only "Setting the pages…".
_CUTTING = {}
_CUTTING_LOCK = threading.Lock()


def _prepare_fonts(d: Path, design) -> dict:
    key = str(d)

    def started(family):
        with _CUTTING_LOCK:
            names = _CUTTING.setdefault(key, [])
            if family not in names:
                names.append(family)
    try:
        return typeset_fonts.prepare(_roles(design), config.CACHE, on_cut=started)
    finally:
        with _CUTTING_LOCK:
            _CUTTING.pop(key, None)


def cutting(books, book) -> list:
    """The families this process is cutting for print for the book right now (none, mostly): its pages wait for
    them. Asked while a compile runs, so it never waits for the book's lock."""
    d = books.dir(book)
    with _CUTTING_LOCK:
        return list(_CUTTING.get(str(d)) or [])


def _write_source(job, source: str):
    main = job.staging / "main.typ"
    try:
        current = main.read_text(encoding="utf-8")
    except OSError:
        current = None
    if current != source:           # another process may have set the book since: main.typ is always ours here
        write_text(main, source)
    job.source = source


def _compiler(job, folder: Path):
    """The book's compiler, kept between compiles (Typst reuses what didn't change), made again for other fonts."""
    if job.compiler is None or job.compiler_fonts != str(folder):
        empty = job.staging / ".none"
        empty.mkdir(exist_ok=True)
        job.compiler = typst.Compiler(
            str(job.staging / "main.typ"), root=str(job.staging),
            font_paths=typst.Fonts(include_system_fonts=False, include_embedded_fonts=True, font_paths=[str(folder)]),
            ignore_system_fonts=True, package_path=str(empty), package_cache_path=str(empty))
        job.compiler_fonts = str(folder)
    return job.compiler


def _message(e) -> str:
    return str(getattr(e, "message", None) or e)


# ---------------------------------------------------------------------------------------------------------
# Compiling

def _result(signature, svgs, facts, warnings, meta, docs, ctx, cut, design, staging, seconds, left=None) -> Compiled:
    hashes = [hashlib.sha1(s).hexdigest() for s in svgs]
    info = {x["page"]: x for x in facts.get("info") or [] if isinstance(x, dict) and "page" in x}
    starts = facts.get("starts") or []
    pages, entry, k = [], None, 0
    for n, h in enumerate(hashes):
        page = n + 1
        while k < len(starts) and starts[k][1] <= page:
            entry, k = starts[k][0], k + 1
        f = info.get(page) or {}
        pages.append({"hash": h, "folio": str(f.get("folio") or ""), "side": "recto" if page % 2 else "verso",
                      "entry": entry, "blank": bool(f.get("blank")), "shown": bool(f.get("shown"))})

    def marks(rows, keys):
        return [dict(zip(keys, row)) for row in rows or []]

    markers = {"blk": marks(facts.get("blk"), ("p", "b", "page", "y")),
               "blkend": marks(facts.get("blkend"), ("p", "b", "page", "y")),
               "piece-start": marks(starts, ("i", "page", "y")),
               "piece-end": marks(facts.get("ends"), ("i", "page", "y"))}
    at, first = {}, {}
    for m in markers["blk"]:
        at.setdefault((m["p"], m["b"]), m["page"] - 1)
    for m in markers["piece-start"]:
        first.setdefault(m["i"], m["page"] - 1)
    blocks = {}
    for i, doc in docs.items():
        last, filled = first.get(i, 0), []
        for b in range(len(doc.get("content") or [])):
            last = at.get((i, b), last)         # a block without a marker is where the one before it is
            filled.append(last)
        blocks[meta["contents"][i]["file"]] = filled
    said = list(dict.fromkeys(_message(w) for w in warnings or []))
    return Compiled(signature=signature, svgs=svgs, hashes=hashes, pages=pages, blocks=blocks, markers=markers,
                    ctx=ctx, fonts=cut, seconds=seconds, warnings=said, design=design, staging=staging,
                    left_out=dict(left or {}))


def _failed(last, signature, message, seconds, design, staging) -> Compiled:
    """A Typst error: its message, with the last good pages kept (and their page map, context and fonts)."""
    if last is not None:
        return dataclasses.replace(last, signature=signature, error=message, seconds=seconds, pdf=None)
    return Compiled(signature=signature, error=message, seconds=seconds, design=design, staging=staging)


def _compile(books, book, d: Path, job) -> Compiled:
    """compile_book's work, with the book's lock held."""
    started = time.monotonic()
    try:
        raw = (d / BOOK_FILE).read_bytes()      # before it is read as the book: a change after this is seen next time
    except OSError:
        raw = b""
    meta = books.read(book)
    for e in meta["contents"]:
        if e.get("unreadable"):
            raise BooksError(_unreadable(e["file"]))
    job.title = str(meta.get("title") or d.name)
    design = book_design.resolve(meta, meta.get("style"))
    base = _base(d, raw, meta, design)
    signature = _digest(base, _poems(books, job.linked))
    if job.compiled is not None and job.compiled.signature == signature:
        return job.compiled
    with _StagingLock(job.staging, job.title):
        pieces, docs, image_srcs, poem_srcs = _read(books, book, meta)
        poems = _poems(books, poem_srcs)            # looked at before typeset reads them
        staged = _stage_images(d, job.staging, design.get("interior") != "colour")
        features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
        ctx = typeset.Context(
            design=design, lang=str(meta.get("language") or "en"), sources=books.sources(book),
            notes=features.get("notes") if features.get("notes") in NOTES else "footnotes",
            numbering="book" if features.get("noteNumbering") == "book" else "chapter",
            images={src: staged[name.lower()] for src in image_srcs
                    if (name := _image_name(src)) and name.lower() in staged},
            linked=books.linked_poem)
        cut = _prepare_fonts(d, design)
        _write_source(job, typeset_book.book(meta, pieces, design, cut["names"], ctx))
        left = typeset_book.left_out(meta, design, ctx)        # the pieces are set: the collectors are full
        signature = _digest(base, poems)
        job.linked = tuple(sorted(poem_srcs))
        try:
            compiler = _compiler(job, cut["folder"])
            out, warnings = compiler.compile_with_warnings(format="svg")
            facts = json.loads(compiler.eval(_FACTS, format="json"))
        except typst.TypstError as e:
            job.compiled = _failed(job.compiled, signature, _message(e), time.monotonic() - started, design,
                                   job.staging)
            return job.compiled
    svgs = [out] if isinstance(out, bytes) else list(out or [])
    job.compiled = _result(signature, svgs, facts, warnings, meta, docs, ctx, cut, design, job.staging,
                           time.monotonic() - started, left)
    return job.compiled


def compile_book(books, book, purpose: str = "preview") -> Compiled:
    """The book compiled, or the last result when nothing changed since. One job per book: a second caller waits
    and gets the same result. `purpose` names the caller (preview, check, pdf, render); they all share one compile.
    An unreadable piece raises a BooksError naming it; a Typst error comes back in `error`, with the last good
    pages kept."""
    d, job = _job(books, book)
    with _book_lock(job, d):
        return _compile(books, book, d, job)


def _output(job, c: Compiled, what: str, **kwargs):
    """Another output of the compiled book (PNG, PDF) from its compiler, with main.typ as this process set it."""
    if c.error:
        raise BooksError(f"The {what} can't be made: {c.error}")
    with _StagingLock(job.staging, job.title):
        _write_source(job, job.source)
        try:
            return job.compiler.compile(**kwargs)
        except typst.TypstError as e:
            raise BooksError(f"The {what} can't be made: {_message(e)}") from None


# ---------------------------------------------------------------------------------------------------------
# Pages, PNGs and the PDF

# The page cache holds each SVG compressed: Typst writes every page's glyph outlines into it, about 160 KB a page of
# text, which zlib brings to about 15 % (4,000 pages: some 100 MB instead of 640). Only pages new to the cache are
# compressed, so a recompile after an edit compresses the two or three pages that changed.
_SVGS = OrderedDict()
_SVGS_LOCK = threading.Lock()
_HASH = re.compile(r"[0-9a-f]{40}")


def _remember(c: Compiled):
    with _SVGS_LOCK:
        for h, svg in zip(c.hashes, c.svgs):
            if h in _SVGS:
                _SVGS.move_to_end(h)
            else:
                _SVGS[h] = zlib.compress(svg, 1)
        while len(_SVGS) > PAGE_CACHE:
            _SVGS.popitem(last=False)


def pages(books, book) -> dict:
    """The book's pages for the viewer (compiled when the book changed); their SVGs stay in this process's page
    cache for `page_svg`. `width`, `height` (mm) and `paper` are those the pages were set with, so the viewer sizes
    and colours the pages from the same compile it shows, even while a newer design is still being set. `left` lists
    the generated pages left out ({"entry": contents index, "why"}), which Compose's contents shows as not in the
    pages."""
    c = compile_book(books, book)
    _remember(c)
    design = c.design or {}
    return {"signature": c.signature, "pages": c.pages, "blocks": c.blocks, "seconds": round(c.seconds, 2),
            "warnings": c.warnings, "error": c.error, "count": len(c.pages),
            "width": design.get("width"), "height": design.get("height"), "paper": design.get("paper"),
            "left": [{"entry": i, "why": why} for i, why in sorted(c.left_out.items())]}


def page_svg(hash: str) -> bytes | None:
    """One page by its hash, or None when this process doesn't have it (any more): the viewer then asks for the pages
    again."""
    if not isinstance(hash, str) or not _HASH.fullmatch(hash):
        return None
    with _SVGS_LOCK:
        packed = _SVGS.get(hash)
        if packed is not None:
            _SVGS.move_to_end(hash)
    return zlib.decompress(packed) if packed is not None else None


def _wanted(numbers, count) -> list[int]:
    if numbers is None:
        return list(range(1, count + 1))
    if not isinstance(numbers, (list, tuple)) or not all(type(n) is int and 1 <= n <= count for n in numbers):
        raise BooksError(f"Pages are numbered 1 to {count}." if count else "This book has no pages yet.")
    return list(numbers)


def render_pages(books, book, pages: list[int] | None = None, fmt: str = "png", ppi: float = 96) -> list[bytes]:
    """The requested pages (1-based; all when None) as PNG at `ppi`, or as the SVGs the viewer shows.

    Typst draws every page of the book for a PNG (typst-py has no page selection), holding the book's locks while it
    does: up to MAX_PPI that stays well inside another caller's LOCK_WAIT (about 8 s for 210 pages at 300 ppi). A
    higher resolution is refused with a plain message, not lowered: the caller asked for a size it wouldn't get."""
    if fmt not in ("png", "svg"):
        raise BooksError("Pages are drawn as png or svg.")
    if isinstance(ppi, bool) or not isinstance(ppi, (int, float)) or not 1 <= ppi <= MAX_PPI:
        raise BooksError(f"The resolution is 1 to {MAX_PPI} pixels per inch.")
    if isinstance(pages, (list, tuple)) and not pages:
        return []                           # nothing asked: nothing compiled or drawn
    d, job = _job(books, book)
    with _book_lock(job, d):
        c = _compile(books, book, d, job)
        wanted = _wanted(pages, len(c.pages))
        if fmt == "svg":
            out = c.svgs
        else:
            out = _output(job, c, "pages", format="png", ppi=float(ppi))
            out = [out] if isinstance(out, bytes) else out          # one page comes as bytes, more as a list
    return [out[n - 1] for n in wanted]


def pdf(books, book, now: datetime | None = None) -> bytes:
    """The print PDF: fonts embedded (subset), black as one-channel grey, grey images for a grey interior, document
    title, author and language from the template, bookmarks for the pieces. `now` dates it (default: now)."""
    d, job = _job(books, book)
    with _book_lock(job, d):
        c = _compile(books, book, d, job)
        when = now if isinstance(now, datetime) else datetime.now()
        c.pdf = _output(job, c, "PDF", format="pdf", pdf_tags=True, timestamp=int(when.timestamp()))
        return c.pdf


def export_pdf(books, book, now: datetime | None = None) -> dict:
    """The PDF written as an export: a dated copy in the book's exports/ folder, as `book_export.export` keeps one.
    `path` is that copy (None when the folder can't be written)."""
    name, data, _, path = book_export.save(books, book, "pdf", now)
    return {"name": name, "path": str(path) if path else None, "pages": len(re.findall(rb"/Type\s*/Page\b", data)),
            "size": len(data)}
