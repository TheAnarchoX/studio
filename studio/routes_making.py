"""Making a carousel in the app: the kit's concepts, the slides, brief and posting notes, render and QA.

The same work Claude does through the MCP tools, over the same store and studio.making."""
import functools

from . import making, routes
from .kit import Kit, KitError
from .store import StoreError


def _plain(fn):
    """A kit's or a check's complaint reaches the browser as a 400 with its own sentence."""
    @functools.wraps(fn)
    def wrapper(h, arg):
        try:
            return fn(h, arg)
        except (KitError, ValueError) as e:
            raise StoreError(str(e)) from None
    return wrapper


def _scope(body):
    return {"slide": body.get("slide"), "format": body.get("format") or None}


@routes.get("/api/concepts")
@_plain
def concepts(h, q):
    h._send(200, Kit(h.store.series_dir(q.get("series", ""))).concepts())


@routes.post("/api/slides")
@_plain
def slides(h, body):
    h.store.set_slides(body.get("id"), body.get("slides"))
    h._send(200, h.store.read(body.get("id")))


def _text(body, what):
    text = body.get("text", "")
    if not isinstance(text, str):
        raise StoreError(f"send the {what} as text")
    return text


@routes.post("/api/brief")
def brief(h, body):
    h.store.write_brief(body.get("id"), _text(body, "brief"))
    h._send(200, h.store.read(body.get("id")))


@routes.post("/api/posting-notes")
def posting_notes(h, body):
    h._send(200, h.store.save_posting_notes(body.get("id"), _text(body, "posting notes")))


@routes.post("/api/render")
@_plain
def render(h, body):
    res = making.render(h.store, body.get("id"), signed=body.get("signed"), **_scope(body))
    h._send(200, {**res, "poem": h.store.read(res["id"])})


@routes.get("/api/render/progress")
@_plain
def render_progress(h, q):
    h._send(200, making.progress(h.store, q.get("id", "")))


@routes.post("/api/qa")
@_plain
def qa(h, body):
    res = making.run_qa(h.store, body.get("id"), **_scope(body))
    h._send(200, {**res, "poem": h.store.read(res["report"]["poem"])})
