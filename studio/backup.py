"""Backups: verified zips of the library's Studio folders, in a folder outside the library (spec part 1, B1-B13).

What goes in (B1, B2): Poems/, Books/, Styles/ and Research/, whichever exist, without what Studio can make again or
threw away: `Design renders/`, `.trash`, `__pycache__` and `node_modules` folders at any depth; in a poem folder, the
kit's renders (PNG files named `<slug>-...` anywhere below it) and the preview page `<slug>.html`; Studio's temp files
(`.<name>.<pid>.<thread>.tmp`) and `*.partial`. Links and junctions inside those folders are never followed. The other
folders and files of the library folder are not backed up; `outside()` says which, for Settings.

A backup (B3-B5, B11, B13) is `Studio backup 2026-11-13 0300.zip` (`-2`, `-3` for another one in that minute),
written as `<name>.zip.partial` beside it, flushed and synced, read back (every member's CRC, and the manifest), then
renamed into place. Its last member, `studio-backup.json`, says what it holds: the library and the computer, when, the
fingerprint (a hash of the path, size and time of every file it holds: when the library's matches the newest backup's,
a scheduled run makes no new zip; a file left out because it couldn't be read is tried again), the skip rules, the
warnings, and the series, poems, books and pieces in it (so a restore needs no scan). A file whose name a zip can't
hold (not valid UTF-16) is left out with a warning.

The library is only read. Each file is opened, read whole and closed at once, on Windows with read, write and delete
sharing: a save meanwhile is never refused, and nothing stays open that would stop the next save replacing the file.
One backup at a time in this process (`_BUSY`, which restores take too) and in the backup folder (the lock file
`.studio-backup.lock`, naming the computer and process; let go at exit, and stale once its process is gone). Every
outcome is kept in `<cache>/backups/state.json`; a failure as a sentence that names the folder and what to do.

A restore (B14-B16) never writes over what is there. A poem, book or piece comes back as a copy next to the current
one, in place of the current one (which goes to the trash first, and comes back out when the restore fails), or where
it was when it is missing; a whole backup goes into a new folder next to the library. Every member of the zip is
checked before anything is written, and files are unpacked into a dot-named folder next to the destination that one
rename puts in place.
"""
from __future__ import annotations

import atexit
import contextlib
import copy
import errno
import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import sys
import threading
import time
import traceback
import zipfile
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Callable
from urllib.parse import quote

from . import __version__, books, config, manuscript
from .books import BOOK_FILE, valid_file
from .store import SERIES_FILE, Store, StoreError, dump_poem, slugify, write_text

FOLDERS = ("Poems", "Books", "Styles", "Research")
SKIP_DIRS = {"Design renders", ".trash", "__pycache__", "node_modules"}
MANIFEST = "studio-backup.json"
FORMAT = 1
NAME = re.compile(r"Studio backup (\d{4})-(\d{2})-(\d{2}) (\d{2})(\d{2})(?:-(\d+))?\.zip")
STORED = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".woff", ".woff2", ".zip", ".docx", ".epub"}
LOCK = ".studio-backup.lock"
LOCK_STALE = 2 * 3600
OUTSIDE_FOR = 600               # seconds outside() keeps its answer for a library
TRIES = 3                       # reads of a file that keeps changing before it is taken as read
DEFLATE_LEVEL = 6
SKIPPED = {"folders": sorted(SKIP_DIRS), "files": [".*.tmp", "*.partial"],
           "in a poem folder": ["<slug>.html", "<slug>-*.png, at any depth"], "links": "never followed"}
ZIP_FIRST, ZIP_LAST = datetime(1980, 1, 1), datetime(2107, 12, 31, 23, 59, 58)     # the times a zip can hold
BUSY = "A backup is already running."
FOLDER_BUSY = "Another Studio is backing up into this folder. Try again in a moment."
NO_SUCH = "There's no such backup."
UNSTORABLE = "A {} in {} has a name a backup can't store; rename it to include it."
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_BUSY = threading.Lock()        # one backup or restore at a time in this process (spec B16)
_STATE_LOCK = threading.Lock()  # the state file and the running counts
_CACHE_LOCK = threading.Lock()
_running: dict | None = None    # {"reason", "done", "total"} while a backup runs
_UNSAVED: dict = {}             # state file -> the state, while that file can't be written
_MANIFESTS: dict = {}           # (folder, name) -> (size, mtime_ns, manifest or None)
_OUTSIDE: dict = {}             # library -> (monotonic time, outside())
_HELD: dict = {}                # lock file -> its bytes, while this process holds it (let go at exit too)
_first_check_done = False       # this process's scheduler has finished its first auto(): see brief()

if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)      # Studio's own instance: these argtypes stay here
    _CreateFileW = _k32.CreateFileW
    _CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                             wintypes.DWORD, wintypes.HANDLE]
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _k32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL
    _GetCurrentThread = _k32.GetCurrentThread
    _GetCurrentThread.argtypes = []
    _GetCurrentThread.restype = wintypes.HANDLE
    _SetThreadPriority = _k32.SetThreadPriority
    _SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    _SetThreadPriority.restype = wintypes.BOOL
    _OpenProcess = _k32.OpenProcess
    _OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _OpenProcess.restype = wintypes.HANDLE
    _GetExitCodeProcess = _k32.GetExitCodeProcess
    _GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _GetExitCodeProcess.restype = wintypes.BOOL
    _INVALID_HANDLE = wintypes.HANDLE(-1).value
    PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
    ERROR_ACCESS_DENIED = 5
    GENERIC_READ = 0x80000000
    SHARE_ALL = 0x1 | 0x2 | 0x4                 # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    OPEN_EXISTING = 3
    FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
    BACKGROUND_BEGIN, BACKGROUND_END = 0x00010000, 0x00020000      # THREAD_MODE_BACKGROUND_*: low I/O priority
_NAME_SURROGATE = 0x20000000    # reparse tags that point elsewhere: symlinks, junctions, mount points


class BackupError(StoreError):
    """A backup that can't be made, found or read, as a sentence for the author; `code` is the HTTP status (400; 404
    for no such backup; 409 while another one runs)."""

    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


# ——— reading the library ———
def open_shared(path: Path) -> BinaryIO:
    """The file's bytes as a file object: read whole at once, and closed before this returns. On Windows the file is
    opened with read, write and delete sharing (CreateFileW), so a program that writes, renames or deletes it during
    the read isn't refused. Nothing is held open afterwards: Windows refuses to replace a file while any handle to it is
    open, whatever its sharing, and an atomic save is a replace. Raises FileNotFoundError, PermissionError and other
    OSErrors as open() does."""
    if sys.platform != "win32":
        with open(path, "rb") as f:
            return io.BytesIO(f.read())
    h = _CreateFileW(_win_path(path), GENERIC_READ, SHARE_ALL, None, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, None)
    if h is None or h == _INVALID_HANDLE:
        code = ctypes.get_last_error()
        raise OSError(0, ctypes.FormatError(code).strip(), str(path), code)    # winerror picks open()'s subclass
    try:
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _CloseHandle(h)
        raise
    with os.fdopen(fd, "rb") as f:
        return io.BytesIO(f.read())


def _win_path(path) -> str:
    """A path CreateFileW takes at any length: from 260 characters on, with \\\\?\\ in front."""
    p = os.path.abspath(path)
    if len(p) < 260 or p.startswith("\\\\?\\"):
        return p
    return "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p


def read_stable(path: Path) -> tuple[bytes, os.stat_result, bool]:
    """The file's bytes and its stat after the read. Read again (up to 3 times in all) while its size or modification
    time differs before and after the read; the bool says whether the last read was a steady one."""
    for _ in range(TRIES):
        before = os.stat(path)
        with open_shared(path) as f:
            data = f.read()
        after = os.stat(path)
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and len(data) == after.st_size:
            return data, after, True
    return data, after, False


def _is_link(entry: os.DirEntry) -> bool:
    """A symlink, a junction or another reparse point that names somewhere else: never followed, never backed up.
    (Cloud placeholders are reparse points too, but not links: they are files.)"""
    try:
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            return True
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return True                 # can't tell: gone, or not ours to follow
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                and getattr(st, "st_reparse_tag", 0) & _NAME_SURROGATE)


def included(library: Path, warnings: list | None = None) -> list[tuple[Path, str]]:
    """(file, path in the zip) of every file a backup holds, sorted by the zip path (B1, B2). A folder that can't be
    listed is left out, with a sentence in `warnings` when given."""
    library = Path(library)
    out = []
    for top in FOLDERS:
        folder = library / top
        if folder.is_dir():         # followed when it is itself a link: Studio reads and writes the library through it
            _gather(folder, top, out, warnings)
    out.sort(key=lambda f: f[1])
    return out


def _gather(top_folder: Path, top: str, out: list, warnings: list | None):
    stack = [(top_folder, top, None)]
    while stack:
        folder, arc, slug = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = list(it)
        except OSError as e:
            if warnings is not None:
                warnings.append(f"{arc}/ couldn't be read ({_reason(e)}).")
            continue
        at_poem = top == "Poems" and arc.count("/") == 2           # Poems/<Series>/<Poem>
        if at_poem and any(os.path.normcase(e.name) == "poem.json" for e in entries):
            slug = _slug(folder / "poem.json")
        for e in entries:
            if _is_link(e):
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            name, path = e.name, f"{arc}/{e.name}"
            if is_dir:
                if name not in SKIP_DIRS:
                    stack.append((Path(e.path), path, slug))
            elif not _skipped(name, slug, at_poem):
                out.append((Path(e.path), path))


def _slug(path: Path) -> str | None:
    """The poem's slug from its poem.json; None when it can't be read or has none."""
    try:
        with open_shared(path) as f:
            poem = json.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError):
        return None
    slug = poem.get("slug") if isinstance(poem, dict) else None
    return slug if isinstance(slug, str) and slug.strip() else None


def _temp_file(name: str) -> bool:
    """Studio's temp files (`.<name>.<pid>.<thread>.tmp`) and `*.partial`."""
    return name.endswith(".partial") or (len(name) > 4 and name.startswith(".") and name.endswith(".tmp"))


def _skipped(name: str, slug: str | None, at_poem: bool) -> bool:
    if _temp_file(name):
        return True
    if slug:
        if at_poem and name == f"{slug}.html":
            return True
        if name.lower().endswith(".png") and name.startswith(f"{slug}-"):
            return True
    return False


def _stats(files) -> list[tuple[str, int, int]]:
    """(path in the zip, size, mtime_ns) of each file that is still there."""
    out = []
    for path, arc in files:
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append((arc, st.st_size, st.st_mtime_ns))
    return out


def _fingerprint(stats) -> str:
    h = hashlib.sha256()
    for arc, size, mtime in stats:
        h.update(f"{arc}\0{size}\0{mtime}\n".encode("utf-8", "surrogatepass"))
    return h.hexdigest()


def fingerprint(files: list[tuple[Path, str]]) -> str:
    """A hash of every file's path in the zip, size and modification time: the same until something changes."""
    return _fingerprint(_stats(files))


def _storable(files, warnings: list) -> list[tuple[Path, str]]:
    """The files whose path a zip can hold (UTF-8). A name that isn't valid UTF-16 (a lone surrogate, which some file
    systems allow) can't be: that file, or every file in such a folder, is left out with one sentence per folder."""
    out, told = [], set()
    for path, arc in files:
        if _encodes(arc):
            out.append((path, arc))
            continue
        parts = arc.split("/")
        bad = next(i for i, p in enumerate(parts) if not _encodes(p))      # never the first: Studio's own folders
        said = UNSTORABLE.format("file" if bad == len(parts) - 1 else "folder", "/".join(parts[:bad]))
        if said not in told:
            told.add(said)
            warnings.append(said)
    return out


def _encodes(text: str) -> bool:
    try:
        text.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def outside(library: Path) -> dict:
    """What a backup leaves out of the library folder: {"folders": [names], "files": n, "bytes": n}, the folders
    (not dot-folders, not Studio's) and the files right in it, and their size in all (links are listed, never
    followed). Kept for 10 minutes per library: the other folders can be large."""
    library = Path(library)
    key = os.path.normcase(str(library))
    with _CACHE_LOCK:
        hit = _OUTSIDE.get(key)
    if hit and time.monotonic() - hit[0] < OUTSIDE_FOR:
        return copy.deepcopy(hit[1])
    ours = {os.path.normcase(f) for f in FOLDERS}
    folders, files, size = [], 0, 0
    try:
        with os.scandir(library) as it:
            entries = sorted(it, key=lambda e: (e.name.lower(), e.name))
    except OSError:
        entries = []
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            if e.is_dir():
                if os.path.normcase(e.name) in ours:
                    continue
                folders.append(e.name)
                if not _is_link(e):
                    size += _tree_size(e.path)
            elif e.is_file():
                files += 1
                size += e.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    found = {"folders": folders, "files": files, "bytes": size}
    with _CACHE_LOCK:
        _OUTSIDE[key] = (time.monotonic(), found)
    return copy.deepcopy(found)


def _tree_size(folder: str) -> int:
    total, stack = 0, [folder]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            try:
                if _is_link(e):
                    continue
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    total += e.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


# ——— the backup folder ———
def check_folder(path: Path, library: Path) -> str | None:
    """None when `path` can hold the library's backups; else the sentence why not."""
    problem = config.backup_folder_problem(path, library)
    if problem:
        return problem
    try:
        if Path(path).exists() and not Path(path).is_dir():
            return f"That's a file, not a folder: {path}."
    except OSError:
        pass
    return None


def same_disk(folder: Path, library: Path) -> bool:
    """Whether the folder (or, while it isn't there yet, its nearest existing parent) is on the library's disk; False
    when either can't be read."""
    p = Path(folder)
    try:
        while not p.exists():
            if p.parent == p:
                return False
            p = p.parent
        return os.stat(p).st_dev == os.stat(library).st_dev
    except OSError:
        return False


def size_text(n: int) -> str:
    """Bytes as the sentences say them: "940 KB", "12 MB", "1.2 GB" (one decimal under 10)."""
    n = max(0, int(n))
    if n < 1024 ** 2:
        return f"{max(1, round(n / 1024))} KB"
    for unit, div in (("MB", 1024 ** 2), ("GB", 1024 ** 3), ("TB", 1024 ** 4)):
        v = n / div
        if v < 1024 or unit == "TB":
            return f"{v:.1f} {unit}" if v < 10 else f"{v:.0f} {unit}"


# ——— state ———
def _state_file() -> Path:
    return Path(config.CACHE) / "backups" / "state.json"


def _read_state_file(f: Path) -> dict:
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}                   # none yet, or not readable: Studio's own cache, written over on the next outcome
    return data if isinstance(data, dict) else {}


def state() -> dict:
    """The kept outcomes: "last_ok" {when, name, bytes, files, warnings}, "last_check", "last_result" (made,
    unchanged, failed), "last_error" {when, message, reason}; {} before any."""
    f = _state_file()
    with _STATE_LOCK:
        s = _UNSAVED.get(str(f))
        return copy.deepcopy(s) if s is not None else _read_state_file(f)


def _update_state(change: dict, drop=()) -> dict:
    f = _state_file()
    with _STATE_LOCK:
        s = copy.deepcopy(_UNSAVED.get(str(f))) or _read_state_file(f)
        s.update(change)
        for k in drop:
            s.pop(k, None)
        try:
            write_text(f, json.dumps(s, ensure_ascii=False, indent=1) + "\n")
            _UNSAVED.pop(str(f), None)
        except OSError:
            _UNSAVED[str(f)] = s    # kept in memory until the file can be written
        return copy.deepcopy(s)


def _set_running(value: dict | None):
    global _running
    with _STATE_LOCK:
        _running = value


def _step(done: int, total: int, progress: Callable[[int, int], None] | None):
    with _STATE_LOCK:
        if _running is not None:
            _running.update(done=done, total=total)
    if progress:
        progress(done, total)


def status() -> dict:
    """The settings ("on", "folder", "default_folder", "env_folder": STUDIO_BACKUPS sets the folder, over the
    setting), whether the folder can be used and is on the library's disk, the kept state, and the backup that runs."""
    folder, library = Path(config.BACKUPS), config.ART
    with _STATE_LOCK:
        running = dict(_running) if _running is not None else None
    return {"on": config.BACKUPS_ON, "folder": str(folder), "default_folder": str(config.default_backups()),
            "env_folder": bool(os.environ.get("STUDIO_BACKUPS")),
            "folder_problem": check_folder(folder, library), "same_disk": same_disk(folder, library),
            "state": state(), "running": running}


# ——— the backups there ———
def list_backups(folder: Path | None = None) -> list[dict]:
    """The backups in the folder, newest first: {"name", "when", "bytes" (the zip's size), "files", "library",
    "computer", "same_library", "readable", "fingerprint"}. "This library" is the library's path on this computer
    (B12). Only files named like Studio's backups are looked at. A folder that isn't there yet (its parent is) has
    none; one that can't be listed is a BackupError with its sentence."""
    folder = Path(folder or config.BACKUPS)
    try:
        with os.scandir(folder) as it:
            entries = [e for e in it if NAME.fullmatch(e.name)]
    except FileNotFoundError:
        if folder.parent.is_dir():
            return []
        raise BackupError(f"The backup folder {folder} isn't there. Is the drive connected?") from None
    except NotADirectoryError:
        raise BackupError(f"That's a file, not a folder: {folder}.") from None
    except OSError:
        raise BackupError(f"Studio can't read {folder}. Choose another folder.") from None
    me, node = os.path.normcase(os.path.normpath(str(config.ART))), platform.node()
    out, names = [], set()
    for e in entries:
        try:
            if not e.is_file():
                continue
            st = e.stat()
        except OSError:
            continue
        names.add(e.name)
        out.append(_entry(e.name, st, _manifest_of(folder, e.name, st), me, node))
    with _CACHE_LOCK:               # forget the zips that are gone
        here = os.path.normcase(str(folder))
        for key in [k for k in _MANIFESTS if k[0] == here and k[1] not in names]:
            del _MANIFESTS[key]
    out.sort(key=lambda b: (b["when"], _number(b["name"])), reverse=True)
    return out


def _number(name: str) -> int:
    m = NAME.fullmatch(name)
    return int(m.group(6) or 1) if m else 0


def _manifest_of(folder: Path, name: str, st: os.stat_result) -> dict | None:
    key = (os.path.normcase(str(folder)), name)
    with _CACHE_LOCK:
        hit = _MANIFESTS.get(key)
    if hit and hit[:2] == (st.st_size, st.st_mtime_ns):
        return hit[2]
    m = _read_manifest(folder / name)
    with _CACHE_LOCK:
        _MANIFESTS[key] = (st.st_size, st.st_mtime_ns, m)
    return m


def _read_manifest(path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read(MANIFEST).decode("utf-8"))
    except Exception:  # noqa: BLE001 - whatever a zip, or a file that isn't one, raises: it isn't a readable backup
        return None
    return m if isinstance(m, dict) else None


def _when(m: dict | None, name: str, st: os.stat_result) -> str:
    """When a backup was made: its manifest's "created", else the time in its name, else the file's time."""
    created = m.get("created") if m else None
    if isinstance(created, str):
        try:
            d = datetime.fromisoformat(created)
            return (d.astimezone().replace(tzinfo=None) if d.tzinfo else d).isoformat(timespec="seconds")
        except ValueError:
            pass
    try:
        return datetime(*(int(g) for g in NAME.fullmatch(name).groups()[:5])).isoformat(timespec="seconds")
    except (AttributeError, ValueError):
        return datetime(*_zip_time(st.st_mtime)).isoformat(timespec="seconds")


def _entry(name: str, st: os.stat_result, m: dict | None, me: str, node: str) -> dict:
    def text(k):
        return m.get(k) if m and isinstance(m.get(k), str) else None
    library, computer = text("library"), text("computer")
    files = m.get("files") if m and isinstance(m.get("files"), int) else None
    return {"name": name, "when": _when(m, name, st), "bytes": st.st_size, "files": files, "library": library,
            "computer": computer,
            "same_library": bool(library) and os.path.normcase(os.path.normpath(library)) == me and computer == node,
            "readable": m is not None, "fingerprint": text("fingerprint")}


def newest(now: datetime | None = None) -> dict | None:
    """The newest readable backup of this library on this computer (never one from another library or computer, nor,
    given `now`, one made after it: a clock that was wrong never stops the next backup); None when there is none or
    the folder can't be listed."""
    try:
        listed = list_backups()
    except BackupError:
        return None
    cutoff = now.isoformat(timespec="seconds") if now else None
    return next((b for b in listed if b["readable"] and b["same_library"] and (cutoff is None or b["when"] <= cutoff)),
                None)


def manifest(name: str) -> dict:
    """The manifest of the backup `name` in the backup folder."""
    folder = Path(config.BACKUPS)
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise BackupError(NO_SUCH, 404)
    try:
        st = (folder / name).stat()
    except OSError:
        raise BackupError(NO_SUCH, 404) from None
    if not stat.S_ISREG(st.st_mode):
        raise BackupError(NO_SUCH, 404)
    m = _manifest_of(folder, name, st)
    if m is None:
        raise BackupError(f"Studio can't read {name}: it isn't a complete backup.")
    return copy.deepcopy(m)


# ——— making one ———
def run(reason: str = "manual", progress: Callable[[int, int], None] | None = None,
        now: datetime | None = None) -> dict:
    """Back up the library now (B4-B7, B11, B13). `reason` is "manual" (always makes a zip), "start" or "daily" (no
    new zip when nothing changed since the newest backup: "unchanged"). `progress(done, total)` is called after each
    file. Returns {"result": "made" | "unchanged", "name", "bytes", "files", "warnings"}; every outcome is kept in the
    state, and a failure is raised as a BackupError with its sentence (409 while another backup runs)."""
    if not _BUSY.acquire(blocking=False):
        raise BackupError(BUSY, 409)
    return _run_holding(reason, progress, now)


def start_run(reason: str = "manual") -> None:
    """Start run() on a thread of its own and return at once: status() shows it running from now on (its progress,
    then its outcome in the state). 409 while one runs."""
    if not _BUSY.acquire(blocking=False):
        raise BackupError(BUSY, 409)
    _set_running({"reason": reason, "done": 0, "total": 0})

    def work():
        try:
            _run_holding(reason, None, None)
        except BackupError:
            pass                    # its sentence is in the state
    try:
        threading.Thread(target=work, name="studio-backup-now", daemon=True).start()
    except BaseException:
        _set_running(None)
        _BUSY.release()
        raise


def _run_holding(reason, progress, now) -> dict:
    """run() with _BUSY taken; releases it."""
    try:
        _set_running({"reason": reason, "done": 0, "total": 0})
        with _background():
            return _make(reason, progress, now or datetime.now())
    finally:
        _set_running(None)
        _BUSY.release()


@contextlib.contextmanager
def _background():
    """On Windows, this thread reads and writes at background priority while the backup runs (failures ignored)."""
    began = False
    if sys.platform == "win32":
        try:
            began = bool(_SetThreadPriority(_GetCurrentThread(), BACKGROUND_BEGIN))
        except OSError:
            pass
    try:
        yield
    finally:
        if began:
            try:
                _SetThreadPriority(_GetCurrentThread(), BACKGROUND_END)
            except OSError:
                pass


def _make(reason: str, progress, now: datetime) -> dict:
    folder, library = Path(config.BACKUPS), config.ART
    warnings, partial, lock, estimate = [], None, None, None
    try:
        if not library.is_dir():    # never an empty backup of a library on a drive that isn't connected
            raise BackupError(f"Your library {library} isn't there. Is the drive connected?")
        problem = check_folder(folder, library)
        if problem:
            raise BackupError(problem)
        if not folder.is_dir():
            if not folder.parent.is_dir():
                raise BackupError(f"The backup folder {folder} isn't there. Is the drive connected?")
            folder.mkdir(exist_ok=True)
        lock = _lock_folder(folder)
        _clean_leftovers(folder)
        files = _storable(included(library, warnings), warnings)
        stats = _stats(files)
        fp = _fingerprint(stats)    # the library now; the manifest keeps the fingerprint of the files the zip holds
        _step(0, len(files), progress)
        last = newest(now)
        if reason != "manual" and last and last["fingerprint"] == fp:
            _update_state({"last_check": _iso(now), "last_result": "unchanged"})
            return {"result": "unchanged", "name": last["name"], "bytes": last["bytes"], "files": last["files"],
                    "warnings": []}
        estimate = int(1.2 * (last["bytes"] if last else sum(size for _, size, _ in stats)))
        free = _free(folder)
        if free is not None and free < estimate:
            raise BackupError(_full(folder, free, estimate))
        name = _free_name(folder, now)
        partial = folder / f"{name}.partial"
        count, size = _write(partial, files, library, reason, now, warnings, progress)
        _verify(partial, count)
        _replace(partial, folder / name)
        partial = None
        made = {"when": _iso(now), "name": name, "bytes": size, "files": count, "warnings": warnings}
        _update_state({"last_ok": made, "last_check": _iso(now), "last_result": "made"}, drop=("last_error",))
        told = list(warnings)
        _prune(now, told)
        return {"result": "made", "name": name, "bytes": size, "files": count, "warnings": told}
    except Exception as e:  # noqa: BLE001 - every failure is kept and told as a sentence
        _discard(partial)           # first: the free space in the sentence counts without it
        partial = None
        if isinstance(e, BackupError) and e.code == 409:
            raise                   # another backup is at work: its business, not a failure to keep
        err = e if isinstance(e, BackupError) else BackupError(_sentence(e, folder, estimate))
        _update_state({"last_error": {"when": _iso(now), "message": str(err), "reason": reason},
                       "last_result": "failed"})
        if err is e:
            raise
        raise err from e
    finally:
        _discard(partial)
        if lock is not None:
            _unlock_folder(folder, lock)


def _iso(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def _lock_folder(folder: Path) -> bytes:
    """Take the folder's lock file (B7), which names this computer and process; its bytes, to release only our own.
    A lock is stale, and replaced, when it is older than LOCK_STALE or when it is from this computer and its process
    isn't running (a Studio that stopped mid-backup: closing the app's window ends its server thread at once)."""
    lock = folder / LOCK
    mine = json.dumps({"pid": os.getpid(), "computer": platform.node(),
                       "when": datetime.now().isoformat(timespec="seconds")}).encode("utf-8")
    for attempt in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            try:
                stale = _stale(lock)
            except FileNotFoundError:
                continue            # let go of just now
            if attempt == 0 and stale:
                lock.unlink(missing_ok=True)
                continue
            raise BackupError(FOLDER_BUSY, 409) from None
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(mine)
        except BaseException:
            # made a moment ago and not written (a full FAT or exFAT drive makes the entry, then fails the write):
            # never left behind, or every run for 2 hours would say another Studio is backing up
            with contextlib.suppress(OSError):
                lock.unlink(missing_ok=True)
            raise
        with _STATE_LOCK:
            _HELD[lock] = mine
        return mine
    raise BackupError(FOLDER_BUSY, 409)


def _stale(lock: Path) -> bool:
    """Whether a lock someone left can be replaced: older than LOCK_STALE, or from this computer and a process that
    isn't running (a pid that is this process's own is a leftover too: one backup at a time runs here)."""
    if abs(time.time() - lock.stat().st_mtime) > LOCK_STALE:
        return True
    try:
        held = json.loads(lock.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return False                # being written, or not ours to read: its age decides
    if not isinstance(held, dict) or held.get("computer") != platform.node():
        return False                # another computer's (or an older Studio's): its age decides
    pid = held.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    return pid == os.getpid() or not _running_here(pid)


def _running_here(pid: int) -> bool:
    """Whether a process with this id runs on this computer (True when that can't be told)."""
    if pid > 0xFFFFFFFF:
        return False                # no process has such an id
    if sys.platform == "win32":
        h = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED      # there, but not ours to look at
        try:
            code = wintypes.DWORD()
            return not _GetExitCodeProcess(h, ctypes.byref(code)) or code.value == STILL_ACTIVE
        finally:
            _CloseHandle(h)
    try:
        os.kill(pid, 0)             # signal 0: only asks (never on Windows, where it would end the process)
    except ProcessLookupError:
        return False
    except OSError:
        return True                 # there, but someone else's
    return True


def _unlock_folder(folder: Path, mine: bytes):
    lock = folder / LOCK
    with _STATE_LOCK:
        if _HELD.get(lock) == mine:
            del _HELD[lock]
    try:
        if lock.read_bytes() == mine:
            lock.unlink()
    except OSError:
        pass


@atexit.register
def _let_go_at_exit():
    """When Studio exits with a backup running (its thread is a daemon's, ended without its `finally`), the lock goes
    with it, so the next Studio needn't wait for it to go stale. Only our own lock: its bytes are checked."""
    with _STATE_LOCK:
        held = list(_HELD.items())
    for lock, mine in held:
        _unlock_folder(lock.parent, mine)


def _clean_leftovers(folder: Path):
    """Delete the .partial files a run that stopped (a crash, a power cut) left; only ones named like Studio's."""
    with os.scandir(folder) as it:
        for e in it:
            if e.name.endswith(".partial") and NAME.fullmatch(e.name.removesuffix(".partial")):
                try:
                    if e.is_file(follow_symlinks=False):
                        os.unlink(e.path)
                except OSError:
                    pass


def _free_name(folder: Path, now: datetime) -> str:
    base = f"Studio backup {now:%Y-%m-%d %H%M}"
    n = 1
    while True:
        name = f"{base}.zip" if n == 1 else f"{base}-{n}.zip"
        if not (folder / name).exists() and not (folder / f"{name}.partial").exists():
            return name
        n += 1


def _free(folder: Path) -> int | None:
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None


def _full(folder: Path, free: int | None, need: int | None) -> str:
    if free is None or not need:
        return f"The disk with {folder} is full. Free some space or choose another folder."
    return (f"The disk with {folder} is full ({size_text(free)} free; a backup needs about {size_text(need)}). "
            "Free some space or choose another folder.")


def _plain(text) -> str:
    """An error's text as the end of a sentence: no final period, lower case first unless it is an initialism."""
    text = str(text).strip().rstrip(".")
    return text[:1].lower() + text[1:] if text[1:2].islower() or len(text) == 1 else text


def _reason(e: OSError) -> str:
    if getattr(e, "winerror", None) in (32, 33):
        return "another program has it open"
    if isinstance(e, PermissionError):
        return "permission denied"
    return _plain(e.strerror or e or type(e).__name__)


def _sentence(e: Exception, folder: Path, estimate: int | None) -> str:
    if isinstance(e, OSError):
        if e.errno == errno.ENOSPC or getattr(e, "winerror", None) in (39, 112):    # ERROR_HANDLE_DISK_FULL, ..._FULL
            return _full(folder, _free(folder), estimate)
        if isinstance(e, PermissionError):
            return f"Studio can't write in {folder}. Choose another folder."
        return f"The backup didn't finish: {_plain(e.strerror or e)}."
    return f"The backup didn't finish: {_plain(e) or type(e).__name__}."


def _zip_time(ts: float) -> tuple:
    """A file time as a zip holds it: local, and within 1980-01-01 .. 2107-12-31 (an older or later time is clamped)."""
    try:
        d = datetime.fromtimestamp(ts)
    except (OverflowError, OSError, ValueError):
        d = ZIP_FIRST if ts < 0 else ZIP_LAST
    return max(ZIP_FIRST, min(d, ZIP_LAST)).timetuple()[:6]


def _take(path: Path, arc: str, warnings: list):
    """(bytes, stat) of a file to back up, or None when it is left out: gone since it was listed, or unreadable (with a
    warning)."""
    try:
        data, st, stable = read_stable(path)
    except FileNotFoundError:
        return None
    except OSError as e:
        warnings.append(f"{arc} couldn't be read ({_reason(e)}).")
        return None
    if not stable:
        warnings.append(f"{arc} changed while it was copied.")
    return data, st


def _add(z: zipfile.ZipFile, arc: str, data: bytes, date_time: tuple):
    info = zipfile.ZipInfo(arc, date_time)
    info.external_attr = (stat.S_IFREG | 0o644) << 16          # a plain file (a restore refuses links)
    if os.path.splitext(arc)[1].lower() in STORED:              # already compressed
        z.writestr(info, data, compress_type=zipfile.ZIP_STORED)
    else:
        z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=DEFLATE_LEVEL)


def _write(partial: Path, files, library: Path, reason: str, now: datetime, warnings: list,
           progress) -> tuple[int, int]:
    """Write the zip as `partial`, the manifest last; flushed and synced. (members but the manifest, the zip's size)
    The manifest's fingerprint is of the files taken, as they were read: a file left out (it couldn't be read) makes
    the library differ from the newest backup, so the next scheduled run tries it again."""
    items = _Items()
    count = size = 0
    taken_stats = []
    with open(partial, "xb") as raw:
        with zipfile.ZipFile(raw, "w", allowZip64=True) as z:
            for i, (path, arc) in enumerate(files, 1):
                taken = _take(path, arc, warnings)
                if taken is not None:
                    data, st = taken
                    _add(z, arc, data, _zip_time(st.st_mtime))
                    items.add(arc, data)
                    taken_stats.append((arc, st.st_size, st.st_mtime_ns))
                    count += 1
                    size += len(data)
                _step(i, len(files), progress)
            m = {"format": FORMAT, "studio": __version__, "library": str(library), "computer": platform.node(),
                 "created": _iso(now), "reason": reason, "files": count, "bytes": size,
                 "fingerprint": _fingerprint(taken_stats), "skipped": SKIPPED, "warnings": warnings,
                 "items": items.as_dict()}
            _add(z, MANIFEST, json.dumps(m, ensure_ascii=False, indent=1).encode("utf-8"), _zip_time(now.timestamp()))
        raw.flush()
        os.fsync(raw.fileno())
        return count, os.fstat(raw.fileno()).st_size


def _verify(partial: Path, count: int):
    """Read the new zip back: every member's CRC, and a manifest that counts the members."""
    try:
        with zipfile.ZipFile(partial) as z:
            bad = z.testzip()
            members = len(z.infolist())
            m = json.loads(z.read(MANIFEST).decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError, EOFError) as e:
        raise BackupError(f"The backup didn't finish: the new zip didn't read back ({_plain(e)}).") from None
    if bad is not None:
        raise BackupError(f"The backup didn't finish: {bad} didn't read back.")
    if not isinstance(m, dict) or m.get("files") != members - 1 or count != members - 1:
        raise BackupError("The backup didn't finish: the new zip didn't read back.")


def _replace(partial: Path, final: Path):
    for attempt in range(20):       # a virus scanner or sync client may hold the new file for a moment
        try:
            os.replace(partial, final)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def _discard(path: Path | None):
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# ——— the manifest's items ———
def _visible(name: str) -> bool:
    return not name.startswith((".", "_"))


def _json(data: bytes) -> dict:
    try:
        v = json.loads(data.decode("utf-8-sig"))
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _title(meta: dict, fallback: str) -> str:
    t = meta.get("title")
    return " ".join(t.split()) if isinstance(t, str) and t.strip() else fallback


class _Items:
    """The series, poems, books and pieces in a backup (B11), from the poem.json, book.json and piece bytes as they go
    into the zip: no extra reads."""

    def __init__(self):
        self.series, self.poems, self.books, self.titles = set(), [], {}, {}

    def add(self, arc: str, data: bytes):
        parts = arc.split("/")
        if len(parts) < 3 or not _visible(parts[1]):
            return
        if parts[0] == "Poems":
            if parts[2:] in ([SERIES_FILE], ["_kit", "build.py"]):
                self.series.add(parts[1])
            elif len(parts) == 4 and parts[3] == "poem.json" and _visible(parts[2]):
                self.series.add(parts[1])
                self.poems.append({"id": f"{parts[1]}/{parts[2]}", "title": _title(_json(data), parts[2]),
                                   "series": parts[1]})
        elif parts[0] == "Books":
            if len(parts) == 3 and parts[2] == BOOK_FILE:
                meta = _json(data)
                entries, seen = [], set()
                for e in meta.get("contents") if isinstance(meta.get("contents"), list) else []:
                    if isinstance(e, dict) and valid_file(e.get("file")) and e["file"] not in seen:
                        seen.add(e["file"])
                        kind, form = (e.get(k) if isinstance(e.get(k), str) else "" for k in ("kind", "form"))
                        entries.append((e["file"], kind, form))
                self.books[parts[1]] = {"title": _title(meta, parts[1]), "entries": entries}
            elif len(parts) == 4 and parts[2] == "manuscript" and valid_file(parts[3]):
                self.titles[(parts[1], parts[3])] = _piece_title(data)

    def as_dict(self) -> dict:
        books = []
        for bid in sorted(self.books):
            b = self.books[bid]
            pieces = [{"file": f, "title": self.titles[(bid, f)] or _kind_label(kind, f), "kind": kind, "form": form}
                      for f, kind, form in b["entries"] if (bid, f) in self.titles]      # only pieces in the zip
            books.append({"id": bid, "title": b["title"], "pieces": pieces})
        return {"series": [{"name": s} for s in sorted(self.series)],
                "poems": sorted(self.poems, key=lambda p: p["id"]), "books": books}


def _piece_title(data: bytes) -> str | None:
    try:
        return manuscript.title_of(data.decode("utf-8-sig"))
    except Exception:  # noqa: BLE001 - a title is a nicety: the piece is in the backup either way
        return None


def _kind_label(kind: str, file: str) -> str:
    return kind.replace("-", " ").capitalize() if kind else file.removesuffix(".md")


# ——— what is kept (B10, B12) ———
KEEP_DAYS, KEEP_WEEKS, KEEP_MONTHS = 7, 4, 12


def prune(now: datetime | None = None) -> list[str]:
    """Delete the backups of this library on this computer that no rule keeps (B10); the names deleted. Kept: every
    one within 24 hours of `now`, and the newest of each of the 7 most recent days, 4 most recent ISO weeks and 12
    most recent months that have one. Backups after `now`, unreadable zips, other libraries' or computers' backups
    and files not named like Studio's are never touched (B12). A delete that fails is left out of the answer."""
    return _prune(now or datetime.now(), [])


def _prune(now: datetime, warnings: list) -> list[str]:
    """prune() with its failures, as sentences, added to `warnings`; never raises."""
    try:
        listed = list_backups()
    except BackupError as e:
        warnings.append(f"Old backups weren't tidied: {e}")
        return []
    except Exception as e:  # noqa: BLE001 - tidying is never a reason for a backup to fail
        warnings.append(f"Old backups weren't tidied: {_plain(e) or type(e).__name__}.")
        return []
    cutoff = _iso(now)
    mine = [b for b in listed if b["readable"] and b["same_library"] and b["when"] <= cutoff]     # newest first
    keep = {b["name"] for b in mine if datetime.fromisoformat(b["when"]) > now - timedelta(hours=24)}
    for count, key in ((KEEP_DAYS, lambda d: d.date()),
                       (KEEP_WEEKS, lambda d: d.isocalendar()[:2]),
                       (KEEP_MONTHS, lambda d: (d.year, d.month))):
        seen = []
        for b in mine:
            k = key(datetime.fromisoformat(b["when"]))
            if k not in seen:
                if len(seen) == count:
                    break
                seen.append(k)
                keep.add(b["name"])
    folder, deleted = Path(config.BACKUPS), []
    for b in mine:
        if b["name"] in keep:
            continue
        try:
            os.remove(folder / b["name"])
            deleted.append(b["name"])
        except FileNotFoundError:
            pass
        except OSError as e:
            warnings.append(f"{b['name']} couldn't be deleted ({_reason(e)}).")
    return deleted


# ——— when they run (B6, B7) ———
START_AFTER, DAILY_AFTER = timedelta(hours=1), timedelta(hours=24)
STALE_AFTER = timedelta(days=3)


def due(now: datetime, at_start: bool, newest: dict | None) -> bool:
    """Whether a scheduled backup is due: none yet, or the newest is an hour (at Studio's start) or a day old."""
    if newest is None:
        return True
    try:
        age = now - datetime.fromisoformat(newest["when"])
    except (KeyError, TypeError, ValueError):
        return True
    return age >= (START_AFTER if at_start else DAILY_AFTER)


def auto(at_start: bool, now: datetime | None = None) -> dict | None:
    """The scheduled backup: None when backups are off or none is due, else run()'s answer. A failure is in the state
    already (run() kept it), so it isn't raised."""
    if not config.BACKUPS_ON:
        return None
    now = now or datetime.now()
    if not due(now, at_start, newest(now)):
        return None
    try:
        return run("start" if at_start else "daily", now=now)
    except BackupError:
        return None


_SCHEDULER_LOCK = threading.Lock()
_scheduler: tuple[threading.Thread, threading.Event] | None = None


def start_scheduler(first_delay: float = 60, every: float = 900) -> bool:
    """Start the thread that backs up on schedule (B7), once per process: after `first_delay` seconds a start check,
    then a daily check every `every` seconds. False when it already runs."""
    global _scheduler
    with _SCHEDULER_LOCK:
        if _scheduler is not None and _scheduler[0].is_alive():
            return False
        stop = threading.Event()

        def loop():
            global _first_check_done
            if stop.wait(first_delay):
                return
            at_start = True
            while True:
                checks = config.BACKUPS_ON          # with backups off, auto() looks at nothing
                try:
                    auto(at_start)
                except Exception:  # noqa: BLE001 - the next round tries again
                    if sys.stderr:
                        traceback.print_exc()
                finally:
                    if checks:
                        _first_check_done = True    # brief() may say backups stopped from now on
                at_start = False
                if stop.wait(every):
                    return
        thread = threading.Thread(target=loop, name="studio-backups", daemon=True)
        _scheduler = (thread, stop)
        thread.start()
        return True


def stop_scheduler() -> None:
    """End the scheduler thread (for tests) and wait for it; start_scheduler() may be called again after."""
    global _scheduler
    with _SCHEDULER_LOCK:
        current, _scheduler = _scheduler, None
    if current:
        current[1].set()
        if current[0] is not threading.current_thread():
            current[0].join(10)


def brief(now: datetime | None = None) -> dict:
    """{"problem": sentence | None} for the Home line (B13), only while backups are on: the last failure's message
    when it is newer than the last success and the last check; else "Studio hasn't been able to back up since 9 Nov
    2026." when the newest of those is over 3 days old and this Studio's scheduler has made its first check (before
    that, an old backup only says Studio was closed); else None. A refusal because another backup runs is never a
    problem."""
    if not config.BACKUPS_ON:
        return {"problem": None}
    now = now or datetime.now()
    s = state()
    good = max((d for d in (_parse(_when_of(s.get(k))) for k in ("last_ok", "last_check")) if d), default=None)
    err = s.get("last_error")
    if isinstance(err, dict) and isinstance(err.get("message"), str) and err["message"] not in (BUSY, FOLDER_BUSY):
        failed = _parse(err.get("when"))
        if failed and (good is None or failed > good):
            return {"problem": err["message"]}
    if _first_check_done and good and now - good > STALE_AFTER:
        return {"problem": f"Studio hasn't been able to back up since {_day_text(good)}."}
    return {"problem": None}


def _day_text(d: datetime) -> str:
    """A date as Studio's sentences say it, "9 Nov 2026", in English whatever the computer's locale."""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def _when_of(v):
    return v.get("when") if isinstance(v, dict) else v


def _parse(text) -> datetime | None:
    try:
        return datetime.fromisoformat(text) if isinstance(text, str) else None
    except ValueError:
        return None


# ——— restoring (B14-B16) ———
RESTORE_WAIT = 30               # seconds a restore waits for a backup that is running (B16)
RESTORE_BUSY = "A backup is running. Try again in a minute."
RESTORE_KINDS = ("poem", "book", "piece")
RESTORE_MODES = ("copy", "replace", "restore")
KEEP_RESTORED = 20              # whole restores kept in the state, for Show in folder
MOVE_TRIES, MOVE_WAIT = 10, 0.2     # a rename Windows refuses for a moment (a virus scanner reading the new files)
DAYS = (".studio", "days.json")     # the writing log of a poem or book: it follows the writing, not the version
UNSAFE = "This backup holds a file Studio won't unpack: {}."
_PROBE = os.path.abspath(os.path.join(os.sep, "studio-restore"))     # where a name is tried before anything is written


def items(name: str) -> dict:
    """What the backup `name` holds, from its manifest, and whether each is in the library now (B15): {"name", "when",
    "library", "same_library", "poems": [{"id", "title", "series", "exists"}], "books": [{"id", "title", "exists",
    "pieces": [{"file", "title", "kind", "form", "exists"}]}]}. A piece exists when its book does, its file is in the
    book's contents and the file is on disk."""
    _, m, entry = _backup(name)
    lib, listed = Path(config.ART), _listed(m)
    shelf = []
    for b in listed["books"]:
        here = _book_here(lib, b["id"])
        files = _book_files(lib, b["id"]) if here else set()
        shelf.append({**b, "exists": here,
                      "pieces": [{**p, "exists": here and _piece_here(lib, b["id"], p["file"], files)}
                                 for p in b["pieces"]]})
    return {"name": name, "when": entry["when"], "library": entry["library"], "same_library": entry["same_library"],
            "poems": [{**p, "exists": _poem_here(lib, p["id"])} for p in listed["poems"]], "books": shelf}


def restore_item(name: str, kind: str, ref, mode: str, now: datetime | None = None) -> dict:
    """Restore one poem (ref: its id, "<Series>/<Folder>"), book (ref: its folder name) or piece (ref: {"book",
    "file"}) from the backup `name` (B14). `mode` "copy" puts it next to the current one, "replace" in the current one's
    place (the current one goes to the trash first), "restore" where it was (it must be missing). Returns {"kind",
    "title", "href", "path", "trash"}. Waits up to RESTORE_WAIT seconds for a backup that runs (B16); a refusal or a
    failure is a BackupError with its sentence, and the library is left as it was. The names of copies carry the
    backup's date, not today's: `now` is taken like run()'s and changes nothing."""
    if kind not in RESTORE_KINDS:
        raise BackupError("Say what to restore: a poem, a book or a piece.")
    if mode not in RESTORE_MODES:
        raise BackupError("Say how to restore it: copy, replace or restore.")
    if kind == "piece" and not (isinstance(ref, dict) and isinstance(ref.get("book"), str)
                                and isinstance(ref.get("file"), str)):
        raise BackupError("Say which piece: its book and its file.")
    with _restoring(name):
        path, m, entry = _backup(name)
        lib, item = Path(config.ART), _find(_listed(m), kind, ref)
        if not lib.is_dir():        # never a new, partial library on a drive that isn't connected
            raise BackupError(f"Your library {lib} isn't there. Is the drive connected?")
        here = (_poem_here(lib, item["id"]) if kind == "poem" else _book_here(lib, item["id"]) if kind == "book"
                else _piece_here(lib, item["book"], item["file"]))
        if mode == "restore" and here:
            raise BackupError(f"“{item['title']}” is in the library now. Restore a copy or replace it.", 409)
        if mode != "restore" and not here:
            raise BackupError(f"“{item['title']}” isn't in the library now. Restore it instead.", 409)
        with zipfile.ZipFile(path) as z:
            members = _checked(z)
            return _RESTORE[kind](z, members, item, mode, lib, datetime.fromisoformat(entry["when"]))


def restore_all(name: str, now: datetime | None = None) -> Path:
    """Unpack the whole backup `name` (all but its manifest) into a new folder next to the library, never into it
    (B14): `<library folder> restored 2026-11-13 0300`, with " 2", " 3" while that is taken. The folder is kept in the
    state's "restored" (the last KEEP_RESTORED), so Settings can show it in its folder. Waits for a running backup as
    restore_item() does."""
    now = now or datetime.now()
    with _restoring(name):
        path, _, entry = _backup(name)
        when = datetime.fromisoformat(entry["when"])
        lib = Path(config.ART)
        dest = _free_path(lib.parent, f"{lib.name or 'Library'} restored {when:%Y-%m-%d %H%M}")
        with zipfile.ZipFile(path) as z:
            _place(z, [(i, p) for i, p in _checked(z) if p != [MANIFEST]], dest, name)
        made = state().get("restored")
        made = [r for r in made if isinstance(r, (dict, str))] if isinstance(made, list) else []
        _update_state({"restored": made[-(KEEP_RESTORED - 1):] + [
            {"path": str(dest), "when": _iso(now), "backup": name}]})
    return dest


@contextlib.contextmanager
def _restoring(name: str):
    """One restore at a time and never during a backup (`_BUSY`, waited for up to RESTORE_WAIT seconds), and every
    failure as a BackupError with a sentence. A restore is never a backup failure: the state doesn't keep it."""
    if not _BUSY.acquire(timeout=RESTORE_WAIT):
        raise BackupError(RESTORE_BUSY, 409)
    try:
        yield
    except BackupError:
        raise
    except StoreError as e:                 # the store's and the books' own sentences (a folder Windows holds on to)
        raise BackupError(str(e), getattr(e, "code", 400)) from e
    except Exception as e:  # noqa: BLE001 - every failure is told as a sentence
        raise BackupError(_restore_sentence(e, name)) from e
    finally:
        _BUSY.release()


def _restore_sentence(e: Exception, name: str) -> str:
    if isinstance(e, (zipfile.BadZipFile, zlib.error, EOFError)):
        return f"Studio can't read {name}: {_plain(e) or 'it is damaged'}. Your library is as it was."
    if isinstance(e, OSError) and (e.errno == errno.ENOSPC or getattr(e, "winerror", None) in (39, 112)):
        return "The disk is full. Free some space, then restore again. Your library is as it was."
    reason = _reason(e) if isinstance(e, OSError) else _plain(e) or type(e).__name__
    return f"The restore didn't finish: {reason}. Your library is as it was."


def _not_put_back(title: str, trashed: Path) -> BackupError:
    return BackupError(f"The restore didn't finish, and “{title}” as it was couldn't be put back: it is in {trashed}.")


def _backup(name) -> tuple[Path, dict, dict]:
    """(the zip, its manifest, its entry in the list: "when", "library", "same_library") of the backup `name`."""
    m = manifest(name)                      # 404 when there is no such backup, 400 when it can't be read
    path = Path(config.BACKUPS) / name
    try:
        st = path.stat()
    except OSError:
        raise BackupError(NO_SUCH, 404) from None
    return path, m, _entry(name, st, m, os.path.normcase(os.path.normpath(str(config.ART))), platform.node())


# what a backup holds
def _listed(m: dict) -> dict:
    """The manifest's poems and books (with their pieces) whose names Studio can restore under; nothing else."""
    got = m.get("items") if isinstance(m.get("items"), dict) else {}

    def rows(v):
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

    def text(v, fallback):
        return v if isinstance(v, str) and v else fallback
    poems, shelf = [], []
    for p in rows(got.get("poems")):
        parts = p["id"].split("/") if isinstance(p.get("id"), str) else []
        if len(parts) == 2 and all(map(_safe_name, parts)):
            poems.append({"id": p["id"], "title": text(p.get("title"), parts[1]), "series": parts[0]})
    for b in rows(got.get("books")):
        if _safe_name(b.get("id")):
            pieces = [{"file": x["file"], "title": text(x.get("title"), x["file"]), "kind": text(x.get("kind"), ""),
                       "form": text(x.get("form"), "")}
                      for x in rows(b.get("pieces")) if valid_file(x.get("file")) and _safe_name(x["file"])]
            shelf.append({"id": b["id"], "title": text(b.get("title"), b["id"]), "pieces": pieces})
    return {"poems": poems, "books": shelf}


def _find(listed: dict, kind: str, ref) -> dict:
    """The item `ref` names in the backup (a piece with its book's "book" and "book_title"); 404 when it has none."""
    if kind == "poem":
        hit = next((p for p in listed["poems"] if p["id"] == ref), None)
    elif kind == "book":
        hit = next((b for b in listed["books"] if b["id"] == ref), None)
    else:
        b = next((b for b in listed["books"] if b["id"] == ref["book"]), None)
        p = next((p for p in b["pieces"] if p["file"] == ref["file"]), None) if b else None
        hit = {**p, "book": b["id"], "book_title": b["title"]} if p else None
    if hit is None:
        raise BackupError(f"This backup has no such {kind}.", 404)
    return hit


def _poem_here(lib: Path, pid: str) -> bool:
    series, folder = pid.split("/")
    return (lib / "Poems" / series / folder / "poem.json").is_file()


def _book_here(lib: Path, bid: str) -> bool:
    return (lib / "Books" / bid / BOOK_FILE).is_file()


def _book_files(lib: Path, bid: str) -> set:
    """The piece files in the book's contents now; none when its book.json can't be read."""
    try:
        meta = books.Books(lib / "Books")._meta(lib / "Books" / bid)
    except StoreError:
        return set()
    return {e["file"] for e in meta["contents"] if isinstance(e, dict) and valid_file(e.get("file"))}


def _piece_here(lib: Path, bid: str, file: str, files: set | None = None) -> bool:
    if not _book_here(lib, bid):
        return False
    return file in (_book_files(lib, bid) if files is None else files) and \
        (lib / "Books" / bid / "manuscript" / file).is_file()


# the zip's members
def _inside(path, root) -> bool:
    """Whether `path` is below `root` once the system has made it absolute (on Windows that is where a `..`, a
    trailing dot or space and a device name like NUL are read)."""
    p, r = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    return p.startswith(r.rstrip(os.sep) + os.sep)


def _safe_name(name) -> bool:
    """A name that is one file or folder right inside the folder it goes in: not empty, not dots, no / \\ or : (a
    drive or a stream), no control characters, no device."""
    return (isinstance(name, str) and bool(name.strip(". ")) and not any(c in "/\\:" or ord(c) < 32 for c in name)
            and _inside(os.path.join(_PROBE, name), _PROBE))


def _checked(z: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, list[str]]]:
    """Every member of the zip with the parts of its path, once they are all checked (B14), before anything is
    written: a name with a leading /, a drive (:), a backslash, a `..` or an empty part, or a link (its mode in
    external_attr) raises the sentence."""
    out = []
    for info in z.infolist():
        raw = info.orig_filename            # zipfile reads a backslash as / on Windows: the name as the zip has it
        parts = (info.filename[:-1] if info.is_dir() else info.filename).split("/")
        if "\\" in raw or "\x00" in raw or not all(map(_safe_name, parts)) or stat.S_ISLNK(info.external_attr >> 16):
            raise BackupError(UNSAFE.format(raw))
        out.append((info, parts))
    return out


def _below(members, prefix: tuple) -> list:
    """The members below the folder `prefix` (path parts), with their parts inside it."""
    n = len(prefix)
    return [(i, p[n:]) for i, p in members if len(p) > n and tuple(p[:n]) == prefix]


def _without_days(members) -> list:
    """All but the writing log: a copy's log would count those days twice, a replace keeps the current one."""
    return [(i, p) for i, p in members if tuple(p) != DAYS]


# writing
def _suffix(when: datetime) -> str:
    return f" (restored {_day_text(when)})"


def _free_path(parent: Path, base: str) -> Path:
    """parent/base, or "base 2", "base 3"... while one is there."""
    n = 1
    while os.path.lexists(parent / (base if n == 1 else f"{base} {n}")):
        n += 1
    return parent / (base if n == 1 else f"{base} {n}")


def _href(kind: str, ref: str, file: str | None = None) -> str:
    """The app's route to a poem (by id), a book, or a piece of a book."""
    if kind == "poem":
        return f"#/poem/{quote(ref, safe='')}"
    return f"#/book/{quote(ref, safe='')}" + (f"/write/{quote(file, safe='')}" if file else "")


def _done(kind: str, title: str, href: str, path: Path, trash: Path | None = None) -> dict:
    return {"kind": kind, "title": title, "href": href, "path": str(path), "trash": str(trash) if trash else None}


def _set_time(path: Path, date_time: tuple):
    """The file's modification time as the zip holds it (local time): a restored file has the time it had."""
    try:
        t = time.mktime(tuple(date_time) + (0, 0, -1))
        os.utime(path, (t, t))
    except (OverflowError, OSError, ValueError):
        pass


def _move(src: Path, dst: Path):
    """Rename `src` (a file or a folder) to `dst`, which must not be there. os.rename, not os.replace: on Windows it
    never replaces anything. Tried again for 2 seconds while Windows refuses (a virus scanner reading the new files)."""
    for attempt in range(MOVE_TRIES):
        if os.path.lexists(dst):
            raise BackupError(f"There's already something at {dst}, and a restore never writes over it.", 409)
        try:
            os.rename(src, dst)
            return
        except PermissionError:
            if attempt == MOVE_TRIES - 1:
                raise
            time.sleep(MOVE_WAIT)


def _remove(folder: Path):
    """A restore's own temporary folder: only copies from the zip are in it."""
    shutil.rmtree(folder, ignore_errors=True)


def _unpack(z: zipfile.ZipFile, members, dest: Path) -> Path:
    """Unpack `members` ([(info, parts of its path inside dest)]) into a new dot-named folder next to `dest`, and
    return that folder; it is removed again when anything fails."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        tmp = dest.parent / f".{dest.name}.{os.getpid()}-{n}.restoring"
        try:
            tmp.mkdir()
            break
        except FileExistsError:
            n += 1
    try:
        for info, parts in members:
            target = tmp.joinpath(*parts)
            if not _inside(target, tmp):
                raise BackupError(UNSAFE.format(info.orig_filename))
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "xb") as out:     # x: a name twice in the zip never overwrites
                shutil.copyfileobj(src, out, 1 << 20)                  # the CRC is checked at the end of the read
            _set_time(target, info.date_time)
    except BaseException:
        _remove(tmp)
        raise
    return tmp


def _place(z: zipfile.ZipFile, members, dest: Path, title: str) -> Path:
    """Unpack `members` into `dest`, a folder that isn't there."""
    if os.path.lexists(dest):
        raise BackupError(f"There's a folder {dest} in the way. Move it, then restore “{title}”.", 409)
    tmp = _unpack(z, members, dest)
    try:
        _move(tmp, dest)
    except BaseException:
        _remove(tmp)
        raise
    return dest


def _new_file(path: Path, data: bytes, date_time: tuple | None = None):
    """Write a file that isn't there: a temp file next to it, then one rename; with the backup's time when given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        if date_time:
            _set_time(tmp, date_time)
        _move(tmp, path)
    except BaseException:
        _discard(tmp)
        raise


def _retitle(f: Path, suffix: str, fallback: str, dump: Callable[[dict], str], slug: bool = False) -> str | None:
    """The suffix on the title in a copy's poem.json or book.json, written as Studio writes the file; the new title, or
    None when the file can't be read (it stays as it is). With `slug`, a poem copy's slug follows its new title, as a
    new poem's does, so a lookup by the original's slug still finds the original (a copy has no renders to keep the
    old one for: B2 leaves them out)."""
    try:
        meta = json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    title = meta.get("title")
    meta["title"] = f"{title.strip() if isinstance(title, str) and title.strip() else fallback}{suffix}"
    if slug:
        meta["slug"] = slugify(meta["title"])
    write_text(f, dump(meta))
    return meta["title"]


# replacing
def _swap(tmp: Path, current: Path, trash: Callable[[], Path], title: str, carry: bool = False) -> Path:
    """Put the unpacked `tmp` in the place of `current` (B14). `trash()` moves the current one to the trash and gives
    its path; its writing log is copied into `tmp` (the days written since the backup stay), and for a poem (`carry`)
    what the backup left out of it is moved over. Any failure puts the current one back. The trashed path."""
    try:
        trashed = trash()
    except BaseException:
        _remove(tmp)
        raise
    moved = []
    try:
        _copy_days(trashed, tmp)
        if carry:
            slug = _slug(trashed / "poem.json")
            _carry(trashed, tmp, slug, moved)
            _keep_slug(tmp, slug)
        _move(tmp, current)
    except BaseException:
        _put_back(tmp, moved, trashed, current, title)
        raise
    return trashed


def _put_back(tmp: Path, moved: list, trashed: Path, current: Path, title: str):
    """After a failed replace: what was moved over goes back into the trashed folder, the temporary folder goes, and
    the trashed folder goes back in its place."""
    stuck = False
    for src, dst in reversed(moved):
        try:
            _move(dst, src)
        except (OSError, BackupError):
            stuck = True
    if not stuck:
        _remove(tmp)
    try:
        _move(trashed, current)
    except (OSError, BackupError) as e:
        raise _not_put_back(title, trashed) from e
    if stuck:
        raise BackupError(f"The restore didn't finish. “{title}” is back as it was, but some of its renders are in "
                          f"{tmp}.")


def _copy_days(old: Path, new: Path):
    """The current writing log (old/.studio/days.json), when there is one, into the restored folder."""
    src = old.joinpath(*DAYS)
    if not src.is_file():
        return
    dst = new.joinpath(*DAYS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as f, open(dst, "xb") as g:
        shutil.copyfileobj(f, g)
    shutil.copystat(src, dst)


def _carry(old: Path, new: Path, slug: str | None, moved: list):
    """Move what a backup leaves out of a poem folder (B2) from `old` into `new`, at the same paths (B14): the kit's
    renders, the preview page, and the folders it skips (Design renders/, a designs/.trash...). Not temp files and not
    links; one whose path is taken in `new` stays in `old`. Each move goes into `moved` as (from, to)."""
    stack = [(old, ())]
    while stack:
        folder, rel = stack.pop()
        with os.scandir(folder) as it:
            entries = list(it)
        for e in entries:
            if _is_link(e):
                continue
            is_dir, here = e.is_dir(follow_symlinks=False), (*rel, e.name)
            if is_dir and e.name not in SKIP_DIRS:
                stack.append((Path(e.path), here))
            elif is_dir or (_skipped(e.name, slug, not rel) and not _temp_file(e.name)):
                target = new.joinpath(*here)
                if not os.path.lexists(target):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _move(Path(e.path), target)
                    moved.append((Path(e.path), target))


def _keep_slug(folder: Path, slug: str | None):
    """The slug names the renders, so it stays fixed once there is a preview page (as Store.save_text keeps it): a
    restored poem.json with another slug gets the current one."""
    f = folder / "poem.json"
    if not slug or not (folder / f"{slug}.html").is_file():
        return
    try:
        poem = json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return
    if isinstance(poem, dict) and poem.get("slug") != slug:
        poem["slug"] = slug
        write_text(f, dump_poem(poem))


# the three kinds
def _restore_poem(z, members, item: dict, mode: str, lib: Path, when: datetime) -> dict:
    series, folder = item["id"].split("/")
    poems = lib / "Poems"
    current = poems / series / folder
    mine = _below(members, ("Poems", series, folder))
    if not mine:                    # listed in the manifest, but not in the zip
        raise BackupError("This backup has no such poem.", 404)
    if mode == "copy":
        suffix = _suffix(when)
        dest = _free_path(poems / series, f"{folder}{suffix}")
        tmp = _unpack(z, _without_days(mine), dest)
        try:
            title = _retitle(tmp / "poem.json", suffix, folder, dump_poem, slug=True) or f"{item['title']}{suffix}"
            _move(tmp, dest)
        except BaseException:
            _remove(tmp)
            raise
        return _done("poem", title, _href("poem", f"{series}/{dest.name}"), dest)
    if mode == "replace":
        tmp = _unpack(z, _without_days(mine), current)
        trashed = _swap(tmp, current, lambda: Store(poems).delete_poem(item["id"]), item["title"], carry=True)
        return _done("poem", item["title"], _href("poem", item["id"]), current, trashed)
    if (poems / series).is_dir():
        _place(z, mine, current, item["title"])
    else:                   # the series went too: its own files come back with the poem (never its other poems)
        own = [(i, p[2:]) for i, p in members if p[:2] == ["Poems", series] and len(p) > 2
               and (p[2] in ("_kit", "stamps") or (len(p) == 3 and not i.is_dir()))]
        _place(z, own + [(i, [folder, *p]) for i, p in mine], poems / series, item["title"])
    return _done("poem", item["title"], _href("poem", item["id"]), current)


def _restore_book(z, members, item: dict, mode: str, lib: Path, when: datetime) -> dict:
    bid, root = item["id"], lib / "Books"
    current = root / bid
    mine = _below(members, ("Books", bid))
    if not mine:
        raise BackupError("This backup has no such book.", 404)
    if mode == "copy":
        suffix = _suffix(when)
        dest = _free_path(root, f"{bid}{suffix}")
        tmp = _unpack(z, _without_days(mine), dest)
        try:
            title = _retitle(tmp / BOOK_FILE, suffix, bid, books._dump) or f"{item['title']}{suffix}"
            _move(tmp, dest)
        except BaseException:
            _remove(tmp)
            raise
        return _done("book", title, _href("book", dest.name), dest)
    if mode == "replace":
        tmp = _unpack(z, _without_days(mine), current)
        with books._LOCK:           # no piece is saved into the book while it is swapped
            trashed = _swap(tmp, current, lambda: books.Books(root).delete_book(bid), item["title"])
        return _done("book", item["title"], _href("book", bid), current, trashed)
    _place(z, mine, current, item["title"])
    return _done("book", item["title"], _href("book", bid), current)


def _restore_piece(z, members, item: dict, mode: str, lib: Path, when: datetime) -> dict:
    bid, file = item["book"], item["file"]
    info = next((i for i, p in members if p == ["Books", bid, "manuscript", file]), None)
    if info is None:
        raise BackupError("This backup has no such piece.", 404)
    data = z.read(info)             # its CRC is checked
    then = next((i for i, p in members if p == ["Books", bid, BOOK_FILE]), None)
    then = _json(z.read(then)) if then else {}                  # the book.json in the backup
    before = then.get("contents") if isinstance(then.get("contents"), list) else []
    shelf = books.Books(lib / "Books")
    with books._LOCK:
        if mode == "restore" and not _book_here(lib, bid):
            raise BackupError(f"Restore the book “{item['book_title']}” first.", 409)
        d = shelf._dir(bid)
        meta = shelf._meta(d)
        p = d / "manuscript" / file
        if mode == "copy":
            suffix = _suffix(when)
            name = _piece_name(d, meta, p.stem, when)
            target = d / "manuscript" / name
            entry = shelf._entry(meta, file)
            _new_file(target, _retitle_piece(data, suffix))
            try:
                at = next(i for i, e in enumerate(meta["contents"]) if e is entry) + 1
                meta["contents"].insert(at, {**entry, "file": name})
                shelf._save_meta(d, meta)
            except BaseException:
                _discard(target)
                raise
            return _done("piece", f"{item['title']}{suffix}", _href("book", d.name, name), target)
        if mode == "replace":
            trashed = shelf._trash(p, f"{d.name} {p.stem}", ".md")
            try:
                _new_file(p, data, info.date_time)
            except BaseException:
                try:
                    _move(trashed, p)
                except (OSError, BackupError) as e:
                    raise _not_put_back(item["title"], trashed) from e
                raise
            return _done("piece", item["title"], _href("book", d.name, file), p, trashed)
        if os.path.lexists(p):
            raise BackupError(f"The manuscript folder of “{item['book_title']}” has a file {file} that isn't in the "
                              "book. Move that file away, then restore it.", 409)
        listed = any(isinstance(e, dict) and e.get("file") == file for e in meta["contents"])
        _new_file(p, data, info.date_time)
        if not listed:              # (in the book but not on disk: the file is all that comes back)
            try:
                meta["contents"].insert(_position(meta["contents"], before, file), _entry_back(before, file, item))
                shelf._save_meta(d, meta)
            except BaseException:
                _discard(p)
                raise
        return _done("piece", item["title"], _href("book", d.name, file), p)


def _piece_name(d: Path, meta: dict, stem: str, when: datetime) -> str:
    """`<stem> restored 2026-11-13.md`, " 2", " 3" before the extension while that is taken: in the manuscript folder,
    in the book, or as the History a trashed piece left in drafts/."""
    taken = {e["file"].lower() for e in meta["contents"] if isinstance(e, dict) and isinstance(e.get("file"), str)}
    for sub, ext in (("manuscript", ""), ("drafts", ".md")):
        with contextlib.suppress(OSError):
            taken |= {n.lower() + ext for n in os.listdir(d / sub)}
    base, n = f"{stem} restored {when:%Y-%m-%d}", 1
    while f"{base}{'' if n == 1 else f' {n}'}.md".lower() in taken:
        n += 1
    return f"{base}{'' if n == 1 else f' {n}'}.md"


def _retitle_piece(data: bytes, suffix: str) -> bytes:
    """A copied piece's text with its first line suffixed when that is a `# ` title; otherwise as it was."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    first, sep, rest = text[len(bom):].partition("\n")
    if not first.startswith("# "):
        return data
    cr = "\r" if first.endswith("\r") else ""
    return f"{bom}{first.rstrip()}{suffix}{cr}{sep}{rest}".encode("utf-8")


def _entry_back(before: list, file: str, item: dict) -> dict:
    """A restored piece's book.json entry: its kind, form and status as the backup's book.json has them."""
    e = next((e for e in before if isinstance(e, dict) and e.get("file") == file), None)
    if e is None:
        return {"file": file, **{k: item[k] for k in ("kind", "form") if item[k]}}
    return {"file": file, **{k: e[k] for k in ("kind", "form", "status") if k in e}}


def _position(contents: list, before: list, file: str) -> int:
    """Where a restored piece's entry goes (B14): where it was. That is right after the entry that preceded it in the
    backup (a piece by its file, an auto page by its name) when that entry is in the book now, or first when nothing
    preceded it. When the position is gone: before the first back matter, else at the end."""
    entries = [e for e in before if isinstance(e, dict)]
    at = next((i for i, e in enumerate(entries) if e.get("file") == file), None)
    if at == 0:
        return 0
    if at is not None:
        prev = entries[at - 1]
        key = ("file", prev["file"]) if valid_file(prev.get("file")) else \
            ("auto", prev["auto"]) if isinstance(prev.get("auto"), str) and prev["auto"] else None
        for i, e in enumerate(contents if key else []):
            if isinstance(e, dict) and e.get(key[0]) == key[1]:
                return i + 1
    for i, e in enumerate(contents):
        if isinstance(e, dict) and (e.get("auto") or e.get("kind")) in books.BACK_MATTER:
            return i
    return len(contents)


_RESTORE = {"poem": _restore_poem, "book": _restore_book, "piece": _restore_piece}
