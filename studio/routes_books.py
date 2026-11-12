"""Books endpoints: the shelf, a book's details, its pieces and their history, search and replace, sources, images, export.

Thin wrappers over books.Books. A new Books(config.BOOKS) per request, because the library can change in Settings.
BooksError carries its status (400, 404, 409) and Handler._guard sends it with its details.
"""
import base64
import subprocess
import sys

from . import book_export, book_import, config, manuscript, routes
from .books import AUTO, FORMS, KINDS, PIECE_KINDS, Books, BooksError


def _books():
    return Books(config.BOOKS)


def _flag(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _body_flag(v):
    return v if isinstance(v, bool) else _flag(v)


def _file(v):
    if not isinstance(v, str) or not v:
        raise BooksError("Say which piece.", 404)
    return v


@routes.get("/api/books")
def books_list(h, q):
    h._send(200, _books().list())


@routes.get_prefix("/bookfiles/")
def book_file(h, rest, q):
    """A book's image, /bookfiles/<book>/images/<name> (the editor's `../images/<name>`): its own prefix, so a Poems
    series named "Books" keeps its /files/ URLs."""
    h._file(_books().file(rest))


@routes.get("/api/books/kinds")
def books_kinds(h, q):
    """The kinds of book, in order (the features each starts with, its first pieces and its closing auto pages), and
    the lists the writing window and the import screen offer: piece kinds, forms and auto pages."""
    h._send(200, {"kinds": KINDS, "pieces": PIECE_KINDS, "forms": FORMS, "autos": AUTO})


@routes.post("/api/books")
def books_create(h, body):
    h._send(200, _books().create(body.get("title"), body.get("author") or "", body.get("language") or "en",
                                 body.get("kind") or "memoir", body.get("look")))


@routes.get("/api/book")
def book_read(h, q):
    h._send(200, _books().read(q.get("b")))


@routes.post("/api/book/update")
def book_update(h, body):
    fields = body.get("fields")
    if not isinstance(fields, dict):
        raise BooksError("Send the fields to change.")
    h._send(200, _books().update(body.get("b"), fields))


@routes.post("/api/book/delete")
def book_delete(h, body):
    dest = _books().delete_book(body.get("b"))
    h._send(200, {"trash": str(dest)})


@routes.get("/api/book/piece")
def piece_read(h, q):
    h._send(200, _books().piece(q.get("b"), _file(q.get("f"))))


@routes.post("/api/book/piece")
def piece_save(h, body):
    piece = _books().save_piece(body.get("b"), _file(body.get("f")), doc=body.get("doc"), md=body.get("md"),
                                base_mtime=body.get("base_mtime"), leaving=_body_flag(body.get("leaving")),
                                force=_body_flag(body.get("force")))
    out = {"mtime": piece["mtime"], "counts": {k: piece[k] for k in ("words", "note_words", "notes")}}
    if piece["snapshot"]:
        out["snapshot"] = piece["snapshot"]
    h._send(200, out)


@routes.post("/api/book/piece/new")
def piece_new(h, body):
    h._send(200, _books().new_piece(body.get("b"), body.get("kind"), body.get("form") or "prose",
                                    body.get("title") or "", body.get("after")))


@routes.post("/api/book/piece/delete")
def piece_delete(h, body):
    dest = _books().delete_piece(body.get("b"), _file(body.get("f")))
    h._send(200, {"trash": str(dest)})


@routes.get("/api/book/history")
def history(h, q):
    h._send(200, _books().history(q.get("b"), _file(q.get("f"))))


@routes.get("/api/book/snapshot")
def snapshot(h, q):
    books, file = _books(), _file(q.get("f"))
    md = books.snapshot_text(q.get("b"), file, q.get("when"))
    form = books.piece(q.get("b"), file)["form"]
    h._send(200, {"md": md, "doc": manuscript.parse(md, form)})


@routes.post("/api/book/restore")
def restore(h, body):
    h._send(200, _books().restore(body.get("b"), _file(body.get("f")), body.get("when")))


@routes.post("/api/book/edition")
def edition(h, body):
    dest = _books().edition(body.get("b"), body.get("name") or "")
    h._send(200, {"name": dest.name, "path": str(dest)})


@routes.get("/api/book/poem")
def linked_poem(h, q):
    """A poem of the Poems library as a book shows it: {"title", "lines"}, or {"missing": true}."""
    h._send(200, _books().linked_poem(q.get("src", "")))


@routes.get("/api/book/editions")
def editions(h, q):
    h._send(200, _books().editions(q.get("b")))


@routes.post("/api/book/reveal")
def reveal(h, body):
    """Show one of the book's editions in the system's file manager (the edition is named as `<date> <name>`)."""
    books = _books()
    wanted = body.get("edition")
    found = next((e for e in books.editions(body.get("b")) if f"{e['date']} {e['name']}" == wanted), None)
    if not found:
        raise BooksError("There's no such edition.", 404)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", found["path"]])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", found["path"]])
    else:
        subprocess.Popen(["xdg-open", found["path"]])
    h._send(200, {"ok": True})


@routes.post("/api/book/export")
def export(h, body):
    """The book as a download; a dated copy is also written to its exports/ folder, so this is a POST."""
    fmt = body.get("format") or "docx"
    name, data, ctype = book_export.export(_books(), body.get("b"), fmt if isinstance(fmt, str) else "")
    h._send(200, data, ctype=ctype, headers={"Content-Disposition": book_export.disposition(name)})


@routes.get("/api/book/search")
def search(h, q):
    h._send(200, _books().search(q.get("b"), q.get("q", ""), _flag(q.get("whole")), _flag(q.get("case"))))


@routes.post("/api/book/replace")
def replace(h, body):
    index = body.get("index")
    if index is not None and (not isinstance(index, int) or isinstance(index, bool)):
        raise BooksError("index is the match's number.")
    file = body.get("f")
    h._send(200, _books().replace(body.get("b"), body.get("q"), body.get("repl") or "", _body_flag(body.get("whole")),
                                  _body_flag(body.get("case")), file if isinstance(file, str) else None, index))


@routes.get("/api/book/sources")
def sources(h, q):
    h._send(200, _books().sources(q.get("b")))


@routes.post("/api/book/sources")
def sources_save(h, body):
    h._send(200, _books().save_sources(body.get("b"), body.get("items")))


@routes.post("/api/book/image")
def image(h, body):
    data = body.get("data")
    if not isinstance(data, str) or not data:
        raise BooksError("There is no image.")
    try:
        raw = base64.b64decode(data, validate=True)
    except ValueError:
        raise BooksError(f"{body.get('name') or 'The image'} couldn't be read.") from None
    h._send(200, {"src": _books().save_image(body.get("b"), body.get("name") or "", raw)})


def _file_bytes(body):
    data = body.get("data")
    if not isinstance(data, str) or not data:
        raise BooksError("There is no file.")
    try:
        return base64.b64decode(data, validate=True)
    except ValueError:
        raise BooksError(f"{body.get('name') or 'The file'} couldn't be read.") from None


@routes.post("/api/book/import")
def import_propose(h, body):
    """What importing this .docx or Markdown file would make. Nothing is written until the commit."""
    signature = body.get("signature")
    h._send(200, book_import.propose(str(body.get("name") or ""), _file_bytes(body),
                                     signature if isinstance(signature, str) else config.SIGNATURE))


@routes.post("/api/book/import/commit")
def import_commit(h, body):
    h._send(200, book_import.commit(_books(), body))
