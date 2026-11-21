"""Composer endpoints: a book's design, its set pages, one page's SVG and the print checks.

Thin wrappers over compose and preflight. A new Books(config.BOOKS) per request, because the library can change in
Settings; BooksError carries its status and Handler._guard sends it. The PDF goes through the existing
POST /api/book/export (format "pdf"), in routes_books.
"""
import re

from . import compose, config, preflight, routes
from .books import Books

_HASH = re.compile(r"[0-9a-f]{40}")
FOREVER = "public, max-age=31536000, immutable"       # a page's URL is its hash, so it never changes
# A page is Typst's SVG: glyphs as paths, images as data: URLs, no script and nothing fetched. Opened on its own (a
# page's address in a tab) it may still do no more than that.
PAGE_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"


def _books():
    return Books(config.BOOKS)


@routes.get("/api/book/design")
def design_read(h, q):
    h._send(200, compose.get_design(_books(), q.get("b")))


@routes.post("/api/book/design")
def design_save(h, body):
    reset = body.get("reset")
    h._send(200, compose.set_design(_books(), body.get("b"), changes=body.get("changes"),
                                    template=body.get("template"), reset=reset if isinstance(reset, list) else ()))


@routes.get("/api/book/pages")
def pages(h, q):
    """The set pages; compiles first when the book changed, which can take seconds on a big book."""
    h._send(200, compose.pages(_books(), q.get("b")))


@routes.get("/api/book/cutting")
def cutting(h, q):
    """The families being cut for print for the book while its pages wait (the viewer's words for a slow first
    compile); answered at once, never behind the compile."""
    h._send(200, {"families": compose.cutting(_books(), q.get("b"))})


@routes.get("/api/book/page")
def page(h, q):
    """One page's SVG by its hash. The hash is checked before anything looks it up; an unknown one (this process
    forgot it) is a 404, and the viewer asks for the pages again."""
    key = q.get("h") or ""
    svg = compose.page_svg(key) if _HASH.fullmatch(key) else None
    if svg is None:
        return h._send(404, {"error": "That page isn't available any more."})
    h._send(200, svg, ctype="image/svg+xml", cache=FOREVER, headers={"Content-Security-Policy": PAGE_CSP})


@routes.post("/api/book/preflight")
def preflight_run(h, body):
    h._send(200, preflight.run(_books(), body.get("b")))


@routes.get("/api/book/preflight")
def preflight_last(h, q):
    books, book = _books(), q.get("b")
    books.read(book)                    # an unknown book is a 404, not an empty report
    h._send(200, preflight.last(books, book) or {})
