"""Library-wide endpoints: the writing log, search and backups."""
import os
import subprocess
import sys
from pathlib import Path

from . import backup, config, routes, search, writing_log
from .backup import BackupError
from .store import StoreError


@routes.get("/api/writing")
def writing(h, q):
    h._send(200, writing_log.gather(h.store, h.store.root.parent / "Books"))


@routes.get("/api/search")
def search_library(h, q):
    """?q=&kind=&limit=: the index is checked first (waiting up to search.WAIT), then searched."""
    kind = q.get("kind") or None
    if kind is not None and kind not in dict(search.KINDS):
        raise StoreError("kind is one of: " + ", ".join(k for k, _ in search.KINDS))
    try:
        limit = int(q.get("limit") or 8)
    except ValueError:
        raise StoreError("limit is a whole number, from 1 to 200") from None
    idx = search.index()
    idx.ensure()
    h._send(200, idx.search(q.get("q", ""), kinds=[kind] if kind else None, limit=min(200, max(1, limit))))


@routes.post("/api/search/warm")
def search_warm(h, body):
    """Start building or checking the index (the search panel calls this when it opens)."""
    idx = search.index()
    idx.ensure(wait=0)
    h._send(200, idx.state())


@routes.get("/api/backups")
def backups(h, q):
    """The settings and state of backups, the backups in the folder, and what isn't backed up."""
    info = backup.status()
    try:
        listed = backup.list_backups()
    except BackupError as e:
        listed = []
        info["folder_problem"] = info["folder_problem"] or str(e)
    h._send(200, {**info, "backups": listed, "outside": backup.outside(config.ART)})


@routes.get("/api/backups/brief")
def backups_brief(h, q):
    """{problem}: the sentence for Home when backups have failed or stopped, else null."""
    h._send(200, backup.brief())


@routes.post("/api/backups/run")
def backups_run(h, body):
    """Back up now: answers when the backup has started; its progress and outcome come through GET /api/backups."""
    backup.start_run("manual")
    h._send(200, backup.status())


@routes.get("/api/backups/items")
def backups_items(h, q):
    """?name=: the poems, books and pieces in that backup, and whether each is in the library now."""
    h._send(200, backup.items(q.get("name") or ""))


@routes.post("/api/backups/restore")
def backups_restore(h, body):
    """{name, kind, ref, mode}: one poem, book or piece (backup.restore_item); {name, all: true}: the whole backup into
    a new folder next to the library, {path}. Waits up to 30 seconds for a backup that runs, then answers 409."""
    if body.get("all") is True:
        return h._send(200, {"path": str(backup.restore_all(body.get("name")))})
    h._send(200, backup.restore_item(body.get("name"), body.get("kind"), body.get("ref"), body.get("mode")))


@routes.post("/api/backups/reveal")
def backups_reveal(h, body):
    """{name}: one backup, selected in its folder; {path}: a folder a whole restore made; {}: the backup folder."""
    folder = Path(config.BACKUPS)
    name, path = body.get("name"), body.get("path")
    if name is not None:
        if not isinstance(name, str) or not backup.NAME.fullmatch(name) or not (folder / name).is_file():
            raise BackupError(backup.NO_SUCH, 404)
        return _show(h, folder / name, select=True)
    if path is not None:
        made = [r.get("path") if isinstance(r, dict) else r for r in backup.state().get("restored") or []]
        wanted = os.path.normcase(os.path.normpath(str(path))) if isinstance(path, str) and path else None
        if not wanted or not any(isinstance(p, str) and os.path.normcase(os.path.normpath(p)) == wanted for p in made) \
                or not Path(path).is_dir():
            raise BackupError("There's no such restored folder.", 404)
        return _show(h, Path(path), select=False)
    if not folder.is_dir():
        raise BackupError(f"The backup folder {folder} isn't there yet: it is made by the first backup.", 404)
    _show(h, folder, select=False)


def _show(h, target: Path, select: bool):
    """Show a folder, or a file selected in its folder, in the system's file manager (as /api/reveal does)."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(target)] if select else ["explorer", str(target)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)] if select else ["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target.parent if select else target)])
    h._send(200, {"ok": True})
