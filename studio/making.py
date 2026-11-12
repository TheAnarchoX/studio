"""Making a carousel with the series' kit: render the slides and measure them.

One place for both ways of working: the Art tab calls it through the web API, the MCP tools render and qa
build their text and pictures from its results. One job per poem at a time (in this process).
"""
import contextlib
import threading
import time

from . import qa as qa_mod
from .kit import format_key

_jobs = {}                  # poem id -> {"kind": "render" | "qa", "done", "total", "started"}
_lock = threading.Lock()


@contextlib.contextmanager
def _job(pid, kind):
    with _lock:
        if pid in _jobs:
            busy = "rendering" if _jobs[pid]["kind"] == "render" else "running QA"
            raise ValueError(f"{pid} is {busy} already; wait until it has finished")
        job = _jobs[pid] = {"kind": kind, "done": 0, "total": 0, "started": time.time()}
    try:
        yield job
    finally:
        with _lock:
            _jobs.pop(pid, None)


def progress(store, ref):
    """What the poem's running job has done: {"running": False}, or kind, done and total images, seconds so far."""
    pid = store.pid(store.resolve(ref))
    with _lock:
        job = dict(_jobs[pid]) if pid in _jobs else None
    if not job:
        return {"running": False}
    return {"running": True, "kind": job["kind"], "done": job["done"], "total": job["total"],
            "seconds": round(time.time() - job["started"], 1)}


def _slide(slide):
    if slide is not None and (isinstance(slide, bool) or not isinstance(slide, int)):
        raise ValueError("slide must be a slide number (1, 2, …)")
    return [slide] if slide is not None else None


def render(store, ref, slide: int | None = None, format: str | None = None, signed: bool | None = None) -> dict:
    """Render the poem's carousel (or one slide, one format, one name variant) with the series' kit.

    A ready poem moves to in review. Returns the images and the contact sheet (paths relative to Poems/), the
    preview page, the poem's status and the seconds it took; partial says whether only part was rendered, and
    rest_stale whether the images left alone now show an older text or older slides."""
    folder = store.resolve(ref)
    pid, poem, kit = store.pid(folder), store.load(folder), store.kit(folder)
    slides, r = _slide(slide), format_key(format)
    if signed not in (None, True, False):
        raise ValueError("signed must be true, false or left out")
    partial = bool(slides or r or signed is not None)
    try:
        stale = partial and store.art(folder, poem)["stale"]
    except (KeyError, IndexError):     # a kit that can't describe the old renders: kit.render says what is wrong
        stale = False
    with _job(pid, "render") as job:
        def tick(done, total):
            with _lock:
                job["done"], job["total"] = done, total
        t = time.time()
        res = kit.render(folder, poem, slides=slides, formats=[r] if r else None, signed=signed, progress=tick)
        secs = time.time() - t
    status = store.status(folder, poem)
    if status == "ready":
        store.set_status(folder, "in review")
        status = "in review"
    return {"id": pid, "images": [store.rel(x) for x in res["images"]],
            "sheet": store.rel(res["sheet"]) if res["sheet"] else None, "page": store.rel(res["page"]),
            "status": status, "seconds": secs, "partial": partial, "rest_stale": bool(stale)}


def run_qa(store, ref, slide=None, format=None) -> dict:
    """Measure the rendered images (all, or one slide and/or format); saves qa.json. {"summary": text, "report"}."""
    folder = store.resolve(ref)
    pid = store.pid(folder)
    slides, formats = _slide(slide), [format_key(format)] if format else None
    n = len(store.load(folder).get("slides") or [])
    if slides and n and not 1 <= slide <= n:
        raise ValueError(f"slide must be 1–{n}")
    with _job(pid, "qa"):
        rep = qa_mod.run(store, pid, slides=slides, formats=formats)
    return {"summary": qa_mod.summary(rep), "report": rep}
