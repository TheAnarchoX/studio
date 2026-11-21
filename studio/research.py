"""The research store: one board of notes, quotes, sources, clips, images, pieces and links per book, and a shared one.

A board is a folder of Markdown files (front matter, then the text) with a board.json holding positions. Nothing is
written on read; files Studio can't read are listed and never written over. Every write to a board runs under its
lock, which also holds off the other process (the Studio app and the MCP server both write boards)."""
from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
import threading
import time
import unicodedata
from collections import namedtuple
from contextlib import ExitStack, contextmanager, suppress
from datetime import datetime
from pathlib import Path
from urllib.parse import quote as _url

from markdown_it import MarkdownIt

from . import config, frontmatter, manuscript, styles
from .books import IMAGE_TYPES, Books, BooksError, _slug, _squash, _write_bytes, valid_file
from .research_sources import _cite_key, _next_key, same_source, same_work, short_label, source_key
from .store import StoreError, folder_name, read_text, write_text

if os.name == "nt":
    import msvcrt
else:
    import fcntl

KINDS = ("note", "quote", "source", "clip", "image", "piece", "link")
KIND_NAME = {"note": "Note", "quote": "Quote", "source": "Source", "clip": "Web clip", "image": "Image", "piece": "Piece",
             "link": "Link"}                                    # as board-core.js names them
NAME_MAX = 60                   # the first words that stand for an item without a title
ADDABLE = ("note", "quote", "source", "piece", "link")          # clips and images have their own functions
CARD_W = {"note": 240, "quote": 280, "source": 260, "clip": 300, "image": 240, "piece": 260, "link": 260}
CARD_H = {"note": 160, "quote": 170, "source": 120, "clip": 280, "image": 200, "piece": 150, "link": 160}   # estimates
FILE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf")
SHARED_DIR = "Research"
SHARED_URL = "_shared"
EXCERPT = 280
TAG_MAX = 40
COLUMN_GAP = 80                 # between the placed cards and the column of unplaced ones
STACK_GAP = 24
BOARD_FILE = "board.json"
UNREADABLE = "This item isn't readable text: Studio reads items as UTF-8. Its file is unchanged; save it as UTF-8 " \
             "in another editor to open it here."
CHANGEABLE = ("title", "text", "tags", "source", "locator", "csl", "from")
_PIECE_FIELDS = ("book", "file")
_LOCK = threading.RLock()
# An item file's parse by (path, mtime_ns, size): a board read parses only the files that changed.
_PARSED = {}
_PARSED_MAX = 4096
LOCK_FILE = ".lock"             # a dot-file: listings and the stamp skip it
LOCK_WAIT = 10.0                # seconds to wait for another window, or Claude, to finish writing a board
BUSY = "The board is busy; try again."
_HELD = {}                      # board folder -> [lock file descriptor, depth]: this process's board locks, under _LOCK
POS_MAX = 1_000_000             # positions within a million units of the centre
CARD_WIDTHS, CARD_HEIGHTS = (120, 1200), (60, 2000)
FRAME_MIN = 160
FRAME_TITLE = 80
FRAME_PAD, FRAME_HEAD = 24, 56  # an item added into a frame: from its left (and below the last), from its top
FRAME_ID = re.compile(r"f-[a-z0-9-]{1,64}")
NO_FRAME = "There's no such frame."
NOT_IN_TEXT = "Notes and links to pieces don't go into the text."
SOURCE_GONE = "This quote's source isn't on its board any more."
SNIPPET = 40                    # characters either side of a search match
_SEARCH = {}                    # (path, mtime_ns, size) -> (the text as plain words, its fold)
_MARKS = re.compile(r"[̀-ͯ᪰-᫿᷀-᷿⃐-⃿︠-︯]")
_TRASHED = re.compile(r"(\d{8}T\d{6}) (.+)\.md")       # <stamp> <id>.md, as delete names it
_INLINE = ("text", "hard_break", "note", "cite")
_Target = namedtuple("_Target", "board id dir path parsed")     # an item a link points at


class ResearchError(StoreError):
    """code 400 for a bad request, 404 for an unknown board or item, 409 for a stale save (details: {"current": item})
    or a board another process keeps busy."""

    def __init__(self, message, code=400, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


# ——— one writer per board ———
def _lock_fd(path: Path, timeout: float) -> int:
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout
    while True:
        try:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise ResearchError(BUSY, 409) from None
            time.sleep(0.02)


def _unlock_fd(fd: int):
    try:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        os.close(fd)


@contextmanager
def _board_lock(d: Path, timeout: float | None = None):
    """The board's writer: this process's lock, then `<board>/.lock` against the other process (the Studio app and the
    MCP server both write boards). The same thread may take it again; busy past `timeout` (LOCK_WAIT) → 409."""
    timeout = LOCK_WAIT if timeout is None else timeout
    if not _LOCK.acquire(timeout=timeout):
        raise ResearchError(BUSY, 409)
    try:
        key = os.path.normcase(str(d))
        held = _HELD.get(key)
        if held is None:
            d.mkdir(parents=True, exist_ok=True)
            held = _HELD[key] = [_lock_fd(d / LOCK_FILE, timeout), 0]
        held[1] += 1
        try:
            yield
        finally:
            held[1] -= 1
            if held[1] == 0:
                del _HELD[key]
                _unlock_fd(held[0])
    finally:
        _LOCK.release()


@contextmanager
def _board_locks(*dirs: Path):
    """Several boards' locks, always taken in the same order (by path), so two moves never wait on each other."""
    with ExitStack() as stack:
        for _, d in sorted({os.path.normcase(str(d)): d for d in dirs}.items()):
            stack.enter_context(_board_lock(d))
        yield


# ——— text ———
def _clean_tags(tags) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list):
        raise ResearchError("Tags are a list of words.")
    out, seen = [], set()
    for t in tags:
        if not isinstance(t, str):
            raise ResearchError("Tags are a list of words.")
        t = _squash(t)
        if not t:
            continue
        if len(t) > TAG_MAX:
            raise ResearchError(f"A tag is at most {TAG_MAX} characters.")
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


_ESCAPED = re.compile(r"\\([!-/:-@\[-`{-~])")          # a Markdown backslash escape of ASCII punctuation
_KEPT = re.compile(r"\x00([0-9a-f]{2})\x00")             # an escaped character, kept aside while the markup goes


def _strip(body: str) -> str:
    """The body as plain words (a cheap Markdown strip, for cards, the list and search): links, block markers and
    emphasis go, escaped characters (`\\[1\\]`, `\\*`) stay as the characters, a hard break is a space."""
    s = _ESCAPED.sub(lambda m: f"\x00{ord(m[1]):02x}\x00", body)
    s = s.replace("\\\n", "\n")
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)", "", s, flags=re.M)
    s = re.sub(r"[*_`~]+", "", s)
    return _squash(_KEPT.sub(lambda m: chr(int(m[1], 16)), s))


def _plain(body: str) -> str:
    """The body's first EXCERPT characters as plain text."""
    return _strip(body)[:EXCERPT]


def _md() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": False, "linkify": False})


def _html(body: str) -> str:
    md = _md()
    tokens = md.parse(body)
    for t in tokens:
        for c in t.children or []:
            if c.type == "link_open":
                c.attrSet("target", "_blank")
                c.attrSet("rel", "noopener noreferrer")
            elif c.type == "image":         # never fetch what the author didn't ask for: show the alt text instead
                c.type, c.tag, c.nesting, c.attrs, c.children, c.content = "text", "", 0, {}, None, f"[image: {c.content}]"
    return md.renderer.render(tokens, md.options, {})


def _flat(node) -> str:
    """A block's words as one line (notes and citations left out)."""
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "hard_break":
        return " "
    if t in ("note", "cite"):
        return ""
    kids = [c for c in node.get("content") or [] if isinstance(c, dict)]
    return ("" if all(c.get("type") in _INLINE for c in kids) else " ").join(_flat(c) for c in kids)


def _paragraphs(body: str) -> list:
    """A quote's paragraphs as the editor's inline nodes; any other block becomes one text node."""
    out = []
    for n in manuscript.parse(body).get("content") or []:
        if n.get("type") == "paragraph":
            out.append(n.get("content") or [])
        elif _squash(_flat(n)):
            out.append([{"type": "text", "text": _squash(_flat(n))}])
    return out


def _sfold(s) -> str:
    """Text as search compares it: NFKD, without accents, case-folded."""
    return _MARKS.sub("", unicodedata.normalize("NFKD", str(s or ""))).casefold()


def _snippet(text: str, folded: str, q: str):
    """SNIPPET characters either side of the first match of q (folded) in text, … where it was cut; None: no match."""
    k = folded.find(q)
    if k < 0:
        return None
    n, start, end = 0, None, len(text)
    for i, ch in enumerate(text):              # text offsets of the match (folding can change lengths)
        n += len(_sfold(ch))
        if start is None and n > k:
            start = i
        if n >= k + len(q):
            end = i + 1
            break
    a, b = max(0, (start or 0) - SNIPPET), min(len(text), end + SNIPPET)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def _searched(fields: dict) -> list[str]:
    """What search reads besides the title and text: tags, URL, site, the source's title, container title and names."""
    out = _tags_of(fields)
    out += [fields[k] for k in ("url", "site") if isinstance(fields.get(k), str)]
    csl = fields.get("csl")
    if isinstance(csl, dict):
        out += [csl[k] for k in ("title", "container-title") if isinstance(csl.get(k), str)]
        for value in csl.values():
            if isinstance(value, list):
                out += [" ".join(str(p[k]) for k in ("given", "dropping-particle", "non-dropping-particle", "family",
                                                      "literal") if p.get(k)) for p in value if isinstance(p, dict)]
    return out


def _stem_ok(name) -> bool:
    return isinstance(name, str) and name != "" and not name.startswith(".") and not any(c in "/\\:" or ord(c) < 32 for c in name)


def _kind(fields: dict) -> str:
    return fields.get("type") if fields.get("type") in KINDS else "note"


def _title_of(fields: dict) -> str:
    return "" if isinstance(fields.get("title"), frontmatter.RawYaml) else str(fields.get("title") or "")


def _source_name(csl: dict) -> str:
    """What a source without a title of its own is named by: its work's title, else its key."""
    title = csl.get("title")
    return _squash(title) if isinstance(title, str) and _squash(title) else str(csl.get("id") or "")


def _first_words(text: str) -> str:
    """Up to NAME_MAX characters of text, cut between words, with … when there is more."""
    text = " ".join(str(text or "").split())
    if len(text) <= NAME_MAX:
        return text
    cut = text[:NAME_MAX + 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut[:NAME_MAX]).rstrip() + "…"


def _book_key(entries: list, csl: dict):
    """The key a source is cited under, from a book's sources.json entries: its own key when that entry is the same
    source or the same work (its title corrected there); else the key of an entry that is the same source; None when
    the book doesn't have it. What Research.use cites, and what a card's "in the book" says."""
    by = {e.get("id"): e for e in entries if isinstance(e, dict)}
    key = csl.get("id")
    if key in by and (same_source(by[key], csl) or same_work(by[key], csl)):
        return key
    return next((e["id"] for e in by.values() if _cite_key(e.get("id")) and same_source(e, csl)), None)


def _tags_of(fields: dict) -> list[str]:
    """An item's tags as words; a number typed by hand (`tags: [childhood, 1987]`) is the word."""
    tags = fields.get("tags")
    return [t if isinstance(t, str) else str(t) for t in tags if isinstance(t, str) or _num(t)] if isinstance(tags, list) else []


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _coord(v) -> bool:
    return _num(v) and abs(v) <= POS_MAX


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Research:
    def __init__(self, library: Path | None = None):
        self.library = Path(library or config.ART).resolve()
        self.books = Books(self.library / "Books")

    # ——— boards ———
    def board_dir(self, board) -> Path:
        """A board's folder: Research/ for the shared board (None), else the book's research/ folder."""
        if board is None:
            return self.library / SHARED_DIR
        try:
            return self.books.dir(board) / "research"
        except BooksError as e:
            raise ResearchError(str(e), 404) from None

    def _canon(self, board):
        """A board as links store it: None, or the book's folder name."""
        return None if board is None else self.board_dir(board).parent.name

    def _where(self, board, memo=None):
        """(board, folder) of a board as an item names it (None or "" for the shared board); None: no such book."""
        board = board or None
        if board is not None and not isinstance(board, str):
            return None
        if memo is not None and ("where", board) in memo:
            return memo["where", board]
        if board is None:
            out = (None, self.library / SHARED_DIR)
        else:
            try:
                d = self.books.dir(board)
                out = (d.name, d / "research")
            except BooksError:
                out = None
        if memo is not None:
            memo["where", board] = out
        return out

    def _all_boards(self) -> list:
        return [(None, self.board_dir(None))] + [(d.name, d / "research") for d in self.books.dirs()]

    @staticmethod
    def _same(a, b) -> bool:
        a, b = a or None, b or None
        return a == b if a is None or b is None else str(a).lower() == str(b).lower()

    def _title(self, board) -> str:
        if board is None:
            return "Shared board"
        d = self.books.dir(board)
        try:
            return str(self.books._meta(d).get("title") or d.name)
        except BooksError:
            return d.name

    def _board_title(self, board, memo) -> str:
        if ("title", board) not in memo:
            try:
                memo["title", board] = self._title(board)
            except BooksError:
                memo["title", board] = str(board)
        return memo["title", board]

    @staticmethod
    def _md_files(d: Path) -> list[Path]:
        if not d.is_dir():
            return []
        return sorted(p for p in d.iterdir() if p.suffix == ".md" and not p.name.startswith(".") and p.is_file())

    def boards(self) -> list[dict]:
        """The shared board, then every book's board in shelf order: {"board", "title", "items"}."""
        out = [{"board": None, "title": "Shared board", "items": len(self._md_files(self.board_dir(None)))}]
        for b in self.books.list():
            out.append({"board": b["id"], "title": b.get("title") or b["id"],
                        "items": len(self._md_files(self.board_dir(b["id"])))})
        return out

    # ——— reading files ———
    def _parsed(self, p: Path):
        """(fields, body, error, excerpt, stat) of an item file, or None when it is gone."""
        try:
            st = p.stat()
        except OSError:
            return None
        key = (str(p), st.st_mtime_ns, st.st_size)
        hit = _PARSED.get(key)
        if hit is None:
            try:
                text = read_text(p)
            except UnicodeDecodeError:
                hit = ({}, "", UNREADABLE, "")
            else:
                if text is None:
                    return None
                fields, body, _ = frontmatter.parse(text)
                hit = (fields, body, None, _plain(body))
            if len(_PARSED) >= _PARSED_MAX:
                _PARSED.clear()
            _PARSED[key] = hit
        return (*hit, st)

    def _layout(self, d: Path) -> dict:
        """board.json as {"items": {id: entry}, "frames": [...], ...}; an unreadable one reads as empty and is left alone."""
        try:
            data = json.loads((d / BOARD_FILE).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict):
            data = {}
        if not isinstance(data.get("items"), dict):
            data["items"] = {}
        data["items"] = {k: v for k, v in data["items"].items() if isinstance(v, dict)}
        data["frames"] = [f for f in data.get("frames") or [] if isinstance(f, dict)] if isinstance(data.get("frames"), list) else []
        return data

    def _write_layout(self, d: Path, layout: dict):
        write_text(d / BOARD_FILE, json.dumps({"version": 1, **layout}, ensure_ascii=False, indent=2) + "\n")

    def _thumb(self, board, d: Path, name):
        if not isinstance(name, str) or not name:
            return None
        name = Path(name.replace("\\", "/")).name
        if Path(name).suffix.lower() not in FILE_TYPES or Path(name).suffix.lower() == ".pdf":
            return None
        try:
            ns = (d / "files" / name).stat().st_mtime_ns
        except OSError:
            return None
        return f"/researchfiles/{_url(board if board is not None else SHARED_URL, safe='')}/{_url(name, safe='')}?w=640&v={ns}"

    def _summary(self, board, d: Path, p: Path, parsed) -> dict:
        fields, body, error, excerpt, st = parsed
        kind = _kind(fields)
        created = fields.get("created")
        s = {"id": p.stem, "type": kind, "title": _title_of(fields), "excerpt": excerpt,
             "tags": _tags_of(fields),
             "created": created if isinstance(created, str) and created else datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
             "updated": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}
        own = {"quote": ("source", "locator", "from"), "source": (),
               "clip": ("url", "site", "author", "published", "fetched", "shot", "file"),
               "image": ("file",), "piece": _PIECE_FIELDS, "link": ("board", "item"), "note": ()}[kind]
        for k in own:
            if k in fields:
                s[k] = fields[k]
        if kind in ("source", "clip", "image") and isinstance(fields.get("csl"), dict):
            s["csl"] = fields["csl"]
        thumb = self._thumb(board, d, fields.get("shot") if kind == "clip" else fields.get("file") if kind == "image" else None)
        if thumb:
            s["thumb"] = thumb
        if error:
            s["error"] = error
        return s

    def _resolve(self, fields: dict, memo, depth=0):
        """The item a link's fields point at (through a link to a link), or None when it is gone."""
        where = self._where(fields.get("board"), memo)
        item = fields.get("item")
        if where is None or not _stem_ok(item):
            return None
        p = where[1] / f"{item}.md"
        parsed = self._parsed(p) if p.is_file() else None
        if parsed is None:
            return None
        if _kind(parsed[0]) == "link" and not parsed[2]:
            return self._resolve(parsed[0], memo, depth + 1) if depth < 8 else None
        return _Target(where[0], item, where[1], p, parsed)

    def _follow(self, s: dict, memo):
        """A link's summary becomes its original's, under the link's own id, with `link` saying where that is."""
        stored = s.get("board") or None
        stored = stored if stored is None or isinstance(stored, str) else str(stored)
        t = self._resolve({"board": stored, "item": s.get("item")}, memo)
        if t is None:
            s["link"] = {"board": stored, "board_title": self._board_title(stored, memo), "item": s.get("item"), "missing": True}
            return
        own = {k: s[k] for k in ("id", "created", "board", "item") if k in s}
        s.clear()
        s.update(self._summary(t.board, t.dir, t.path, t.parsed))
        s.update(own)
        s["link"] = {"board": t.board, "board_title": self._board_title(t.board, memo), "item": t.id, "missing": False}

    def _enrich(self, board, items: list, memo):
        """What summaries take from elsewhere: a link's original, a quote's source label, a citable item's place in
        the book's sources.json (whether Research.use would cite it as it is there, adding nothing)."""
        for s in items:
            if s["type"] == "link" and "error" not in s:
                self._follow(s, memo)
            if s["type"] == "piece" and "error" not in s:
                s["piece"] = self._piece_details(s, memo)
            if s["type"] == "quote":
                home = s["link"]["board"] if "link" in s else board
                s["source_label"] = self._label(home, s.get("source"), s.get("locator"), memo)
            csl = s.get("csl")
            if board is not None and isinstance(csl, dict) and isinstance(csl.get("id"), str):
                s["in_book"] = _book_key(self._book_sources(board, memo), csl) is not None

    def _piece_details(self, fields: dict, memo) -> dict:
        """The piece a piece link points at, as its book has it (read, never written): {"book", "file", "title",
        "kind", "status", "words", "missing", "book_title"}; missing when the book or the piece can't be found."""
        book, file = fields.get("book"), fields.get("file")
        out = {"book": book, "file": file, "title": "", "kind": "", "status": "", "words": 0, "missing": True,
               "book_title": ""}
        if not isinstance(book, str) or not book.strip():
            return out
        if ("book", book.lower()) not in memo:
            try:
                memo["book", book.lower()] = self.books.read(book.strip())
            except BooksError:
                memo["book", book.lower()] = None
        b = memo["book", book.lower()]
        if b is None:
            return out
        out.update(book=b["id"], book_title=str(b.get("title") or b["id"]))
        e = next((e for e in b["contents"] if valid_file(file) and e.get("file") == file), None)
        if e is None or e.get("missing"):
            return out
        out.update(title=str(e.get("title") or ""), kind=str(e.get("kind") or ""), status=str(e.get("status") or ""),
                   words=e.get("words") if _num(e.get("words")) else 0, missing=False)
        return out

    def _name(self, fields: dict, excerpt: str, memo) -> tuple:
        """(what an item is called where it is listed, whether that is a stand-in): its title; else its work's title
        (CSL); else its piece's title; else its text's first words, or its kind's name (stand-ins)."""
        csl, kind = fields.get("csl"), _kind(fields)
        title = _title_of(fields) or (_squash(csl["title"]) if isinstance(csl, dict) and isinstance(csl.get("title"), str) else "")
        if not title and kind == "piece":
            title = self._piece_details(fields, memo)["title"]
        if title:
            return _squash(title), False
        return _first_words(excerpt) or KIND_NAME[kind], True

    def _label(self, board, key, locator, memo) -> str:
        """A quote's citation as its card shows it, `van Dijk 1998, p. 12`; the key when its source isn't in reach."""
        if not _cite_key(key):
            return ""
        entry = next((c for c in self._citable(board, memo) if c["key"] == key), None)
        return (entry["label"] if entry else key) + (f", {locator}" if isinstance(locator, str) and locator else "")

    def _read(self, board) -> dict:
        d = self.board_dir(board)
        layout = self._layout(d)
        items = []
        for p in self._md_files(d):
            parsed = self._parsed(p)
            if parsed:
                items.append(self._summary(board, d, p, parsed))
        self._enrich(board, items, {})
        entries = layout["items"]
        placed = {s["id"]: entries[s["id"]] for s in items
                  if isinstance(entries.get(s["id"]), dict) and all(isinstance(entries[s["id"]].get(k), (int, float)) for k in "xy")}
        right, top = None, None
        for s in items:
            e = placed.get(s["id"])
            if e:
                r = e["x"] + (e.get("w") if isinstance(e.get("w"), (int, float)) else CARD_W[s["type"]])
                right = r if right is None else max(right, r)
                top = e["y"] if top is None else min(top, e["y"])
        for f in layout["frames"]:
            if all(isinstance(f.get(k), (int, float)) for k in ("x", "y", "w")):
                right = f["x"] + f["w"] if right is None else max(right, f["x"] + f["w"])
                top = f["y"] if top is None else min(top, f["y"])
        x, y = (0 if right is None else right + COLUMN_GAP), (0 if top is None else top)
        for s in sorted((s for s in items if s["id"] not in placed), key=lambda s: (s["created"], s["id"])):
            w = CARD_W[s["type"]]
            s["pos"] = {"x": x, "y": y, "w": w, "h": None, "z": 0, "frame": None, "placed": False}
            y += CARD_H[s["type"]] + STACK_GAP
        for s in items:
            e = placed.get(s["id"])
            if e:
                s["pos"] = {"x": e["x"], "y": e["y"], "w": e["w"] if isinstance(e.get("w"), (int, float)) else CARD_W[s["type"]],
                            "h": e["h"] if isinstance(e.get("h"), (int, float)) else None,
                            "z": e["z"] if isinstance(e.get("z"), (int, float)) else 0,
                            "frame": e.get("frame") if isinstance(e.get("frame"), str) else None, "placed": True}
        items.sort(key=lambda s: (s["created"], s["id"]))
        tags, kinds = {}, {}
        for s in items:
            kinds[s["type"]] = kinds.get(s["type"], 0) + 1
            for t in s["tags"]:
                tags[t] = tags.get(t, 0) + 1
        return {"board": board, "title": self._title(board), "items": items, "frames": layout["frames"], "tags": tags,
                "kinds": kinds, "stamp": self.stamp(board)}

    def read(self, board) -> dict:
        """A board with every item's summary and position; items with no place get one here, not on disk."""
        with _LOCK:
            return self._read(board)

    def _path(self, board, id) -> Path:
        if not _stem_ok(id):
            raise ResearchError(f"There's no item {id} on this board.", 404)
        p = self.board_dir(board) / f"{id}.md"
        if not p.is_file():
            raise ResearchError(f"There's no item {id} on this board.", 404)
        return p

    def item(self, board, id) -> dict:
        """One item in full: its summary and "text", "html", "mtime" and "extra" (front matter Studio doesn't know);
        a link's are its original's."""
        with _LOCK:
            p = self._path(board, id)
            summary = next((s for s in self._read(board)["items"] if s["id"] == p.stem), None)
            if summary is None:
                raise ResearchError(f"There's no item {id} on this board.", 404)
            return self._full(board, summary)

    def _full(self, board, s: dict) -> dict:
        link = s.get("link")
        where = self._where(link["board"]) if link and not link["missing"] else None
        p = where[1] / f"{link['item']}.md" if where else self.board_dir(board) / f"{s['id']}.md"
        parsed = self._parsed(p)
        if parsed is None:
            raise ResearchError(f"There's no item {s['id']} on this board.", 404)
        fields, body, st = parsed[0], parsed[1], parsed[4]
        return {**s, "text": body, "html": _html(body), "mtime": st.st_mtime,
                "extra": {k: v for k, v in fields.items() if k not in frontmatter.ORDER}}

    def _items_on(self, board, ids) -> list[dict]:
        """Items of one board in full, in the order given (one read of the board)."""
        by = {s["id"]: s for s in self._read(board)["items"]}
        return [self._full(board, by[i]) for i in dict.fromkeys(ids) if i in by]

    # ——— sources in reach ———
    def _reach(self, board, memo) -> list:
        """One board's citable items, its own then its links' originals: [(csl, board, id)]."""
        if ("reach", board) in memo:
            return memo["reach", board]
        out, where = [], self._where(board, memo)
        if where:
            links = []
            for p in self._md_files(where[1]):
                parsed = self._parsed(p)
                if not parsed or parsed[2]:
                    continue
                if _kind(parsed[0]) == "link":
                    links.append(parsed[0])
                elif isinstance(parsed[0].get("csl"), dict):
                    out.append((parsed[0]["csl"], where[0], p.stem))
            for fields in links:
                t = self._resolve(fields, memo)
                if t and isinstance(t.parsed[0].get("csl"), dict):
                    out.append((t.parsed[0]["csl"], t.board, t.id))
        memo["reach", board] = out
        return out

    def _book_sources(self, book, memo) -> list:
        """A book's sources.json entries; [] when it can't be read (reads never fail on it)."""
        if ("sources", book) not in memo:
            try:
                memo["sources", book] = [e for e in self.books.sources(book) if isinstance(e, dict)]
            except BooksError:
                memo["sources", book] = []
        return memo["sources", book]

    def _citable(self, board, memo) -> list:
        if ("citable", board) in memo:
            return memo["citable", board]
        found = list(self._reach(board, memo))
        if board is not None:
            found += self._reach(None, memo) + [(e, None, None) for e in self._book_sources(board, memo)]
        out, seen = [], set()
        for csl, b, i in found:
            key = csl.get("id")
            if _cite_key(key) and key not in seen:
                seen.add(key)
                out.append({"key": key, "label": short_label(csl) or key, "title": str(csl.get("title") or ""),
                            "csl": csl, "board": b, "id": i})
        memo["citable", board] = out
        return out

    def citable(self, board) -> list[dict]:
        """The sources in reach of a board, in the order a key is found: the board's citable items and its links'
        originals; then (a book's board) the shared board's; then the book's sources.json (`board` and `id` null).
        The first of a key wins."""
        with _LOCK:
            self.board_dir(board)
            return copy.deepcopy(self._citable(board, {}))

    def _keys_in_reach(self, board) -> set:
        """The citation keys a new source must not take: every key in reach of the board."""
        return {c["key"] for c in self._citable(board, {})}

    # ——— writing ———
    def _csl(self, board, csl, previous=None):
        """A CSL item checked, with a key if it has none: the previous item's; else that of the same source in reach
        of the board (a work the book has already); else a new one that no source in reach has."""
        if not isinstance(csl, dict):
            raise ResearchError("A source's data is an object (CSL-JSON).")
        csl = copy.deepcopy(csl)
        if not csl.get("id") and isinstance(previous, dict) and previous.get("id"):
            csl["id"] = previous["id"]
        if not csl.get("id"):
            reach = self._citable(board, {})
            csl["id"] = next((c["key"] for c in reach if same_source(c["csl"], csl)), None) \
                or source_key(csl, {c["key"] for c in reach})
        if not _cite_key(csl["id"]):
            raise ResearchError("A source's key is letters, digits and - . : _ (for example vandijk1998).")
        if not isinstance(csl.get("type"), str) or not csl["type"]:
            raise ResearchError("A source needs a type (book, article-journal, webpage …).")
        return csl

    def _new_id(self, d: Path, title, text, kind) -> str:
        words = " ".join(str(text or "").split()[:6])
        stem = _slug(title or words, kind)
        taken = {p.name.lower() for p in d.glob("*")} if d.is_dir() else set()
        n = 1 if stem.split(".")[0].upper() in styles.RESERVED else 0
        while True:
            cand = stem if n == 0 else f"{stem}-{n}"
            if f"{cand}.md".lower() not in taken:
                return cand
            n = max(n, 1) + 1

    @staticmethod
    def _free(folder: Path, name: str) -> str:
        """name, or name-2, name-3 … (before its suffix) when the folder has it already, in any case."""
        taken = {p.name.lower() for p in folder.iterdir()} if folder.is_dir() else set()
        stem, suffix = os.path.splitext(name)
        cand, n = name, 2
        while cand.lower() in taken:
            cand, n = f"{stem}-{n}{suffix}", n + 1
        return cand

    def _text_of(self, fields) -> str:
        text = fields.get("text", "")
        if not isinstance(text, str):
            raise ResearchError("An item's text is a string.")
        return text

    def add(self, board, fields: dict, at: dict | None = None, frame: str | None = None) -> dict:
        """A new note, quote, source, piece or link, placed at `at` ({"x", "y"}), else inside `frame`, else by the
        column rule; on top of the board."""
        if not isinstance(fields, dict):
            raise ResearchError("Say what to add.")
        kind = fields.get("type")
        if kind in ("clip", "image"):
            raise ResearchError("Clips and images are added with their own calls.")
        if kind not in ADDABLE:
            raise ResearchError("An item's type is " + ", ".join(ADDABLE) + ".")
        d = self.board_dir(board)
        with _board_lock(d):
            body, title = self._text_of(fields), _squash(fields.get("title"))
            out = {"type": kind, "title": title, "tags": _clean_tags(fields.get("tags"))}
            shown = kind
            if kind == "quote":
                self._set_source(out, fields.get("source"))
                if _squash(fields.get("locator")):
                    out["locator"] = _squash(fields["locator"])
                if fields.get("from"):
                    out["from"] = self._str(fields["from"], "from")
            elif kind == "source":
                out["csl"] = self._csl(board, fields.get("csl"))
            elif kind == "piece":
                out.update(self._piece(fields))
            elif kind == "link":
                t = self._link_target(board, fields)
                out["board"], out["item"] = t.board, t.id
                shown = _kind(t.parsed[0])
            if kind not in ("source", "link") and isinstance(fields.get("csl"), dict):
                out["csl"] = self._csl(board, fields["csl"])
            out["created"] = _now()
            name = out["item"] if kind == "link" else _source_name(out["csl"]) if kind == "source" else ""
            id = self._new_id(d, title or name, body, kind)
            layout = self._place(d, id, shown, at, frame)
            write_text(d / f"{id}.md", frontmatter.dump(out, body))
            self._write_layout(d, layout)
            return self.item(board, id)

    @staticmethod
    def _picture_kind(data: bytes):
        """The image type the bytes' signature says (extensions it goes with), or None."""
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return (".png",)
        if data[:3] == b"\xff\xd8\xff":
            return (".jpg", ".jpeg")
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return (".gif",)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return (".webp",)
        return None

    def add_image(self, board, name, data: bytes, fields: dict | None = None, at: dict | None = None,
                  frame: str | None = None) -> dict:
        """An image card: `data` saved as files/<name> (made unique, in any case), placed like `add`. The bytes' signature
        (PNG, JPEG, GIF, WebP) must agree with the name's extension."""
        fields = fields if fields is not None else {}
        if not isinstance(fields, dict):
            raise ResearchError("Say what to add.")
        base = folder_name(os.path.basename(str(name or "").replace("\\", "/")))
        stem, ext = os.path.splitext(base)
        kinds = self._picture_kind(bytes(data)) if isinstance(data, (bytes, bytearray)) else None
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ResearchError("There is no image.")
        if ext.lower() not in IMAGE_TYPES or kinds is None or ext.lower() not in kinds:
            raise ResearchError("Images are .jpg, .jpeg, .png, .gif or .webp.")
        stem = stem.strip(". ") or "image"
        d = self.board_dir(board)
        with _board_lock(d):
            body, title = self._text_of(fields), _squash(fields.get("title")) or stem
            out = {"type": "image", "title": title, "tags": _clean_tags(fields.get("tags"))}
            if isinstance(fields.get("csl"), dict):
                out["csl"] = self._csl(board, fields["csl"])
            folder = d / "files"
            taken = {p.name.lower() for p in folder.iterdir()} if folder.is_dir() else set()
            n = 1 if stem.split(".")[0].upper() in styles.RESERVED else 0
            while True:
                cand = f"{stem}{ext}" if n == 0 else f"{stem}-{n}{ext}"
                if cand.lower() not in taken:
                    break
                n = max(n, 1) + 1
            out["file"] = f"files/{cand}"
            out["created"] = _now()
            id = self._new_id(d, title, body, "image")
            layout = self._place(d, id, "image", at, frame)
            _write_bytes(folder / cand, bytes(data))
            try:
                write_text(d / f"{id}.md", frontmatter.dump(out, body))
                self._write_layout(d, layout)
            except BaseException:
                (folder / cand).unlink(missing_ok=True)
                raise
            return self.item(board, id)

    # ——— clips (the network is in clip.py) ———
    def clip(self, board, url, at: dict | None = None, frame: str | None = None, *, fetch=None, shoot=None,
             id=None) -> dict:
        """Clip a web page the author asked for. The page is fetched, read and photographed first, with no board lock
        held; then the clip is written under the lock. What comes back decides what is made: HTML → a clip (the
        readable copy as its body, its picture at files/<id>.jpg, a webpage CSL item keyed like the board's sources),
        with "warning" when the picture couldn't be taken; an image → an image item with the address as its source;
        a PDF → a clip that keeps the file (files/<id>.pdf); anything else → ClipError. An address without a scheme
        gets https://. With `id`, that clip is fetched again (from `url`, else its own address): its body, details
        and picture are replaced; its title, tags, key, created and place are kept. A link stands for its original
        (which is clipped again where it is; the link is returned). `fetch` and `shoot` stand in for clip.fetch and
        clip.picture (tests)."""
        from . import clip as web           # clip.py imports this module
        asked = (board, id)
        if id is not None:
            board, id = self._clip_home(board, id)
        d = self.board_dir(board)
        old = self._clip_fields(board, id) if id is not None else None
        if old is None:
            self._place(d, "", "clip", at, frame)       # a bad place or frame is said before anything is fetched
        url = web.address(url or (old or {}).get("url"))
        got = (fetch or web.fetch)(url)
        stamp = _now()
        if got.ctype in web.IMAGE_TYPES:
            if old is not None:
                raise web.ClipError("This address gives an image now; add it to the board as an image.")
            return self._clip_image(board, d, web, got, url, stamp, at, frame)
        if got.ctype in web.HTML_TYPES:
            html = web.decode_html(got.data, got.charset)
            details = web.readable(html, got.final_url)
            with tempfile.TemporaryDirectory(prefix="studio-clip-") as tmp:
                shot, why = (shoot or web.picture)(html, got.final_url, Path(tmp) / "shot.jpg")
                data = shot.read_bytes() if shot else None
            body, kind = details.pop("markdown"), "shot"
        elif got.ctype == web.PDF:
            if b"%PDF-" not in got.data[:1024]:
                raise web.ClipError("The site's PDF couldn't be read.")
            name = web.file_name(got.final_url) or web.file_name(url)
            title = name[:-4] if name.lower().endswith(".pdf") else name
            details = {"title": _squash(title), "site": web.site_of(url), "author": "", "published": ""}
            body, kind, data, why = "", "file", got.data, ""
        else:
            raise web.ClipError(f"Studio can't clip {got.ctype or 'this kind of file'}.")
        with _board_lock(d):
            item = self._write_clip(board, d, web, id if old is not None else None, url, details, body,
                                    kind, data, stamp, at, frame)
        if old is not None and (board, id) != asked:
            item = self.item(*asked)        # clipped through a link: the link, as its board shows it
        if kind == "shot" and data is None:
            item["warning"] = why or web.NO_PICTURE
        return item

    def _clip_home(self, board, id) -> tuple:
        """(board, id) of the clip to clip again: the item itself, or a link's original (404 when that is gone)."""
        parsed = self._parsed(self._path(board, id))
        if parsed and not parsed[2] and _kind(parsed[0]) == "link":
            t = self._resolve(parsed[0], {})
            if t is None:
                raise ResearchError("The original of this link is gone.", 404)
            return t.board, t.id
        return board, id

    def _clip_fields(self, board, id) -> dict:
        """The front matter of a clip to clip again; 404 when it is gone, 400 when it isn't a clip."""
        parsed = self._parsed(self._path(board, id))
        if parsed is None:
            raise ResearchError(f"There's no item {id} on this board.", 404)
        if parsed[2] or _kind(parsed[0]) != "clip":
            raise ResearchError("Only clips can be clipped again.")
        return copy.deepcopy(parsed[0])

    def _clip_image(self, board, d: Path, web, got, url, stamp, at, frame) -> dict:
        """An address that gives an image: an image item named after the address's file, with the address as its
        source."""
        kinds = self._picture_kind(got.data)
        if kinds is None:
            raise web.ClipError("The site's image isn't a PNG, JPEG, GIF or WebP file.")
        name = folder_name(web.file_name(got.final_url)) or "image"
        stem, ext = os.path.splitext(name)
        if ext.lower() not in kinds:
            name = (stem.strip(". ") or "image") + kinds[0]
        with _board_lock(d):
            details = {"title": os.path.splitext(name)[0], "site": web.site_of(url), "author": "", "published": ""}
            csl = web.webpage_csl(details, url, stamp, self._keys_in_reach(board))
            return self.add_image(board, name, got.data, {"csl": csl}, at, frame)

    def _named_by_another(self, d: Path, name: str, id) -> bool:
        """Whether another clip or image on the board names this file in files/ (its `shot` or `file`)."""
        for p in self._md_files(d):
            parsed = None if p.stem == id else self._parsed(p)
            if not parsed or parsed[2] or _kind(parsed[0]) not in ("clip", "image"):
                continue
            for key in ("shot", "file"):
                v = parsed[0].get(key)
                if isinstance(v, str) and v and Path(v.replace("\\", "/")).name.lower() == name.lower():
                    return True
        return False

    def _own_file(self, d: Path, rel, id, ext):
        """The name in files/ that a clip's `shot` or `file` field points at, when it is the clip's own and there:
        <id>.<ext> or <id>-<n>.<ext> as Studio names them, but not the name of another item (<id>-2 is an id too) and
        not a file another item names. A hand-edited field naming another item's file is never written over or
        deleted."""
        name = Path(rel.replace("\\", "/")).name if isinstance(rel, str) and rel else ""
        if not re.fullmatch(re.escape(id) + r"(-\d+)?" + re.escape(ext), name, re.I) or not (d / "files" / name).is_file():
            return None
        stem = os.path.splitext(name)[0]
        if (stem.lower() != id.lower() and (d / f"{stem}.md").is_file()) or self._named_by_another(d, name, id):
            return None
        return name

    def _clip_name(self, d: Path, id, ext) -> str:
        """A new name for a clip's file: <id>.<ext>, else <id>-2.<ext> …, skipping names taken in files/ and names of
        other items (so the item <id>-2 keeps <id>-2.jpg for itself)."""
        folder = d / "files"
        taken = {p.name.lower() for p in folder.iterdir()} if folder.is_dir() else set()
        n = 1
        while True:
            stem = id if n == 1 else f"{id}-{n}"
            if f"{stem}{ext}".lower() not in taken and (n == 1 or not (d / f"{stem}.md").is_file()):
                return f"{stem}{ext}"
            n += 1

    def _write_clip(self, board, d: Path, web, id, url, details, body, kind, data, stamp, at, frame) -> dict:
        """A clip's file and .md, under the board's lock. A new clip (id None) gets an id and a place; an old one keeps
        its title, tags, key, created and place. The file is written first and the .md after; when the .md can't be
        written a new file is removed again, so a failure leaves no half item."""
        if id is None:
            fields = {"type": "clip", "title": _squash(details["title"] or details["site"] or url), "tags": []}
            id = self._new_id(d, fields["title"], body, "clip")
            layout, key = self._place(d, id, "clip", at, frame), None
        else:
            fields, layout = self._clip_fields(board, id), None
            key = fields["csl"].get("id") if isinstance(fields.get("csl"), dict) else None
        fields["url"], fields["site"], fields["fetched"] = url, details["site"], stamp
        for k in ("author", "published"):
            if details.get(k):
                fields[k] = details[k]
            else:
                fields.pop(k, None)
        csl = web.webpage_csl(details, url, stamp, self._keys_in_reach(board))
        if _cite_key(key):
            csl["id"] = key                 # quotes cite the clip by its key: clipping again keeps it
        fields["csl"] = csl
        fields.setdefault("created", stamp)
        folder, ext, made = d / "files", (".jpg" if kind == "shot" else ".pdf"), None
        if data is not None:
            name = self._own_file(d, fields.get(kind), id, ext) or self._clip_name(d, id, ext)
            made = None if (folder / name).exists() else folder / name
            _write_bytes(folder / name, data)
            fields[kind] = f"files/{name}"
        other = "file" if kind == "shot" else "shot"
        stale = self._own_file(d, fields.pop(other, None), id, ".pdf" if other == "file" else ".jpg")
        try:
            write_text(d / f"{id}.md", frontmatter.dump(fields, body))
        except BaseException:
            if made is not None:
                made.unlink(missing_ok=True)
            raise
        if layout is not None:
            self._write_layout(d, layout)
        if stale:
            (folder / stale).unlink(missing_ok=True)
        return self.item(board, id)

    def _link_target(self, board, fields):
        """The original a new link points at (a link's own original when given a link); 400 when it is missing or on
        this board."""
        other = fields.get("board") or None
        if other is not None and not isinstance(other, str):
            raise ResearchError("A link's board is a book's id, or null for the shared board.")
        item = self._str(fields.get("item"), "item")
        here = self._canon(board)
        t = None if self._same(other, here) else self._resolve({"board": other, "item": item}, {})
        if t is None and not self._same(other, here):
            raise ResearchError(f"There's no item {item} to link to.")
        if t is None or self._same(t.board, here):
            raise ResearchError("A link shows an item of another board; this one is on this board.")
        return t

    @staticmethod
    def _str(value, name) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ResearchError(f"{name} is needed.")
        return value.strip()

    def _set_source(self, out: dict, source):
        if source in (None, ""):
            out.pop("source", None)
        elif _cite_key(source):
            out["source"] = source
        else:
            raise ResearchError("A quote's source is a citation key (letters, digits and - . : _).")

    def _piece(self, fields) -> dict:
        book, file = fields.get("book"), fields.get("file")
        if not isinstance(book, str) or not book.strip() or not valid_file(file):
            raise ResearchError("A piece is a book's id and the piece's file name.")
        return {"book": book.strip(), "file": file}

    # ——— placing ———
    def _kinds(self, d: Path) -> dict:
        out = {}
        for p in self._md_files(d):
            parsed = self._parsed(p)
            if parsed:
                out[p.stem] = _kind(parsed[0])
        return out

    def _boxes(self, d: Path, layout) -> list:
        """The placed items as (left, top, right, bottom, frame), with the estimated height of a card left free."""
        kinds, out = self._kinds(d), []
        for id, e in layout["items"].items():
            if id in kinds and _num(e.get("x")) and _num(e.get("y")):
                w = e["w"] if _num(e.get("w")) else CARD_W[kinds[id]]
                h = e["h"] if _num(e.get("h")) else CARD_H[kinds[id]]
                out.append((e["x"], e["y"], e["x"] + w, e["y"] + h, e.get("frame")))
        return out

    def _spot(self, d: Path, layout) -> tuple:
        """Where an item nobody placed goes, written at once: the column read() gives unplaced items, 80 right of
        everything placed and from its top; while that column is the rightmost thing on the board, below its last card."""
        boxes = self._boxes(d, layout)
        frames = [(f["x"], f["y"], f["x"] + f["w"], f["y"] + (f["h"] if _num(f.get("h")) else 0))
                  for f in layout["frames"] if all(_num(f.get(k)) for k in ("x", "y", "w"))]
        if not boxes and not frames:
            return 0, 0
        if boxes:
            col = max(b[0] for b in boxes)
            rest = [b for b in boxes if b[0] != col] + frames
            if (not rest and col == 0) or (rest and col == max(b[2] for b in rest) + COLUMN_GAP):
                return col, max(b[3] for b in boxes if b[0] == col) + STACK_GAP
        everything = boxes + frames
        return max(b[2] for b in everything) + COLUMN_GAP, min(b[1] for b in everything)

    def _in_frame(self, d: Path, layout, f: dict, kind) -> tuple:
        """Inside a frame: FRAME_PAD from its left, FRAME_HEAD from its top or STACK_GAP below its lowest item; the
        frame grows to hold it."""
        inside = [b for b in self._boxes(d, layout) if b[4] == f.get("id")]
        x, y = f["x"] + FRAME_PAD, max(b[3] for b in inside) + STACK_GAP if inside else f["y"] + FRAME_HEAD
        need = y + CARD_H[kind] + FRAME_PAD - f["y"]
        if not _num(f.get("h")) or f["h"] < need:
            f["h"] = need
        return x, y

    @staticmethod
    def _top(layout) -> int | float:
        return max([e["z"] for e in layout["items"].values() if _num(e.get("z"))] + [-1]) + 1

    def _place(self, d: Path, id, kind, at, frame) -> dict:
        """board.json with a new item's entry: at `at`, else inside `frame`, else by the column rule (`frame` is kept
        either way); its z is the board's highest + 1."""
        layout = self._layout(d)
        f = None
        if frame is not None:
            f = next((x for x in layout["frames"] if isinstance(frame, str) and x.get("id") == frame), None)
            if f is None or not all(_num(f.get(k)) for k in ("x", "y")):
                raise ResearchError(NO_FRAME)
        if at is not None:
            if not isinstance(at, dict) or not all(_coord(at.get(k)) for k in "xy"):
                raise ResearchError("Where to put it is {x, y}.")
            x, y = at["x"], at["y"]
        elif f is not None:
            x, y = self._in_frame(d, layout, f, kind)
        else:
            x, y = self._spot(d, layout)
        entry = {"x": x, "y": y, "w": CARD_W[kind], "h": None, "z": self._top(layout)}
        if frame is not None:
            entry["frame"] = frame
        layout["items"][id] = entry
        return layout

    def _put(self, d: Path, layout, id, kind):
        """An item that arrives on a board (moved, linked) placed by the column rule in `layout`."""
        x, y = self._spot(d, layout)
        layout["items"][id] = {"x": x, "y": y, "w": CARD_W[kind], "h": None, "z": self._top(layout)}

    @staticmethod
    def _patch(e) -> dict:
        """An item's new place, checked."""
        if not isinstance(e, dict):
            raise ResearchError("A position is {x, y, w, h, z, frame}.")
        out = {}
        for k in ("x", "y"):
            if k in e:
                if not _coord(e[k]):
                    raise ResearchError("A position is a number within a million of the centre.")
                out[k] = e[k]
        if "w" in e:
            if not (_num(e["w"]) and CARD_WIDTHS[0] <= e["w"] <= CARD_WIDTHS[1]):
                raise ResearchError("A card is {} to {} wide.".format(*CARD_WIDTHS))
            out["w"] = e["w"]
        if "h" in e:
            if e["h"] is not None and not (_num(e["h"]) and CARD_HEIGHTS[0] <= e["h"] <= CARD_HEIGHTS[1]):
                raise ResearchError("A card is {} to {} high, or as high as its text (null).".format(*CARD_HEIGHTS))
            out["h"] = e["h"]
        if "z" in e:
            if not _num(e["z"]):
                raise ResearchError("A card's z is a number.")
            out["z"] = e["z"]
        if "frame" in e:
            if e["frame"] is not None and not isinstance(e["frame"], str):
                raise ResearchError(NO_FRAME)
            out["frame"] = e["frame"]
        return out

    @staticmethod
    def _frame(frames: list, f):
        """Add or change a frame, by id. A new one's id comes from its title (f-childhood); an unused id of the form
        f-… makes a frame with that id (undo brings a deleted frame back so)."""
        if not isinstance(f, dict):
            raise ResearchError("A frame is {title, x, y, w, h}.")
        fid = f.get("id")
        cur = next((x for x in frames if fid is not None and x.get("id") == fid), None)
        if fid is not None and cur is None and not (isinstance(fid, str) and FRAME_ID.fullmatch(fid)):
            raise ResearchError(NO_FRAME)
        new = {}
        if "title" in f or cur is None:
            new["title"] = _squash(f.get("title")) or "Frame"
            if len(new["title"]) > FRAME_TITLE:
                raise ResearchError(f"A frame's title is at most {FRAME_TITLE} characters.")
        for k in ("x", "y", "w", "h", "z"):
            if k not in f:
                continue
            if k in "wh" and not (_num(f[k]) and FRAME_MIN <= f[k] <= 2 * POS_MAX):
                raise ResearchError(f"A frame is at least {FRAME_MIN} wide and high.")
            if k in "xy" and not _coord(f[k]) or k == "z" and not _num(f[k]):
                raise ResearchError("A frame's place is numbers within a million of the centre.")
            new[k] = f[k]
        if cur is not None:
            cur.update(new)
            return
        if not all(k in new for k in ("x", "y", "w", "h")):
            raise ResearchError("A frame is {title, x, y, w, h}.")
        if fid is None:
            base, taken, n = "f-" + _slug(new["title"], "frame"), {x.get("id") for x in frames}, 2
            fid = base
            while fid in taken:
                fid, n = f"{base}-{n}", n + 1
        z = new.pop("z", max([x["z"] for x in frames if _num(x.get("z"))] + [-1]) + 1)
        frames.append({"id": fid, **new, "z": z})

    def layout(self, board, items: dict | None = None, frames: list | None = None, remove_frames: list | None = None) -> dict:
        """Positions and frames merged into board.json by id, so two windows (or Claude) keep each other's changes:
        `items` {id: {x, y, w?, h?, z?, frame?}} (ids not on the board are ignored), `frames` added or changed,
        `remove_frames` gone (their items no longer in a frame, where they are). Returns the board."""
        if items is not None and not isinstance(items, dict):
            raise ResearchError("Positions are {id: {x, y}}.")
        if frames is not None and not isinstance(frames, list):
            raise ResearchError("Frames are a list.")
        if remove_frames is not None and not (isinstance(remove_frames, list) and all(isinstance(f, str) for f in remove_frames)):
            raise ResearchError("Say which frames to remove.")
        patches = {k: self._patch(v) for k, v in (items or {}).items()}
        d = self.board_dir(board)
        if not frames and not d.is_dir():
            return self.read(board)
        with _board_lock(d):
            lay = self._layout(d)
            for f in frames or []:
                self._frame(lay["frames"], f)
            ids, present = {f.get("id") for f in lay["frames"]}, self._kinds(d)
            changed = bool(frames)
            for id, patch in patches.items():
                if patch.get("frame") is not None and patch["frame"] not in ids:
                    raise ResearchError(NO_FRAME)
                if id in present:
                    entry = {**lay["items"].get(id, {}), **patch}
                    if not (_num(entry.get("x")) and _num(entry.get("y"))):
                        raise ResearchError("Where to put it is {x, y}.")
                    lay["items"][id], changed = entry, True
            gone = set(remove_frames or ())
            if gone:
                lay["frames"] = [f for f in lay["frames"] if f.get("id") not in gone]
                for e in lay["items"].values():
                    if e.get("frame") in gone:
                        e["frame"] = None
                changed = True
            if changed:
                self._write_layout(d, lay)
        return self.read(board)

    # ——— changing and removing ———
    def update(self, board, id, fields: dict, base_mtime=None, force=False) -> dict:
        """Change an item's title, text, tags, source, locator, csl or from (a piece's book and file); through a link,
        its original's. A file that changed since `base_mtime` is a 409 carrying the current item, unless `force`."""
        if not isinstance(fields, dict):
            raise ResearchError("Say what to change.")
        with _LOCK:
            p = self._path(board, id)
            parsed = self._parsed(p)
            if parsed and not parsed[2] and _kind(parsed[0]) == "link":
                t = self._resolve(parsed[0], {})
                if t is None:
                    raise ResearchError("The original of this link is gone.", 404)
                try:
                    self.update(t.board, t.id, fields, base_mtime, force)
                except ResearchError as e:
                    if e.code == 409 and "current" in e.details:     # a stale save, not a busy board
                        e.details = {"current": self.item(board, id)}
                    raise
                return self.item(board, id)
            with _board_lock(p.parent):
                return self._update(board, id, fields, base_mtime, force)

    def _update(self, board, id, fields, base_mtime, force) -> dict:
        p = self._path(board, id)
        parsed = self._parsed(p)
        if parsed is None:
            raise ResearchError(f"There's no item {id} on this board.", 404)
        old, body, error, _, st = parsed
        if error:
            raise ResearchError(error, 400)
        kind = _kind(old)
        allowed = CHANGEABLE + (_PIECE_FIELDS if kind == "piece" else ())
        for k in fields:
            if k not in allowed:
                raise ResearchError(f"{k} can't be changed here.")
        try:
            base = None if base_mtime is None else float(base_mtime)
        except (TypeError, ValueError):
            raise ResearchError("base_mtime is the modification time the editor was given.") from None
        if base is not None and not force and abs(st.st_mtime - base) > 1e-6:
            raise ResearchError(f"{id} changed since you opened it.", 409, {"current": self.item(board, id)})
        new = copy.deepcopy(old)
        if old.get("type") in KINDS or old.get("type") in (None, ""):    # a kind Studio doesn't know is kept as typed
            new["type"] = kind
        if "text" in fields:
            body = self._text_of(fields)
        if "title" in fields:
            new["title"] = _squash(fields["title"])
        if "tags" in fields:
            new["tags"] = _clean_tags(fields["tags"])
        if "source" in fields:
            self._set_source(new, fields["source"])
        if "locator" in fields:
            if _squash(fields["locator"]):
                new["locator"] = _squash(fields["locator"])
            else:
                new.pop("locator", None)
        if "from" in fields:
            if fields["from"]:
                new["from"] = self._str(fields["from"], "from")
            else:
                new.pop("from", None)
        if "csl" in fields:
            if fields["csl"] is None and kind != "source":
                new.pop("csl", None)
            else:
                new["csl"] = self._csl(board, fields["csl"], old.get("csl"))
        if kind == "piece" and any(k in fields for k in _PIECE_FIELDS):
            new.update(self._piece({**old, **fields}))
        write_text(p, frontmatter.dump(new, body))
        return self.item(board, id)

    def delete(self, board, ids: list[str]) -> list[str]:
        """Move items (and the files they hold) to <board>/.trash and drop their positions; returns the trash paths."""
        if not isinstance(ids, list) or not ids:
            raise ResearchError("Say which items.")
        d = self.board_dir(board)
        self._path(board, ids[0])           # an unknown item is a 404 before anything is made
        with _board_lock(d):
            return self._discard(d, list(dict.fromkeys(self._path(board, i) for i in ids)))

    def _discard(self, d: Path, paths: list) -> list[str]:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        out = [str(self._to_trash(d, p, stamp)) for p in paths]
        layout_file = d / BOARD_FILE
        if layout_file.is_file():
            try:
                data = json.loads(layout_file.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                data = None
            if isinstance(data, dict) and isinstance(data.get("items"), dict) and any(p.stem in data["items"] for p in paths):
                for p in paths:
                    data["items"].pop(p.stem, None)
                write_text(layout_file, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return out

    def _to_trash(self, d: Path, p: Path, stamp) -> Path:
        trash = d / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        parsed = self._parsed(p)
        fields = parsed[0] if parsed else {}
        for key in ("shot", "file"):
            name = fields.get(key)
            src = d / "files" / Path(name.replace("\\", "/")).name if isinstance(name, str) and name else None
            if src and src.is_file() and not self._named_by_another(d, src.name, p.stem):    # never another item's
                self._move(src, trash, f"{stamp} {p.stem} {src.name}")
        return self._move(p, trash, f"{stamp} {p.stem}.md")

    @staticmethod
    def _move(path: Path, trash: Path, name: str) -> Path:
        dest, n = trash / name, 2
        base = Path(name)
        while dest.exists():
            dest, n = trash / f"{base.stem}-{n}{base.suffix}", n + 1
        os.replace(path, dest)
        return dest

    def restore(self, board, names: list[str]) -> list[dict]:
        """Items back from <board>/.trash with their files: `names` are the file names of the paths `delete` returned.
        An id taken meanwhile becomes -2 …, a file name taken in files/ too; positions come back through `layout`."""
        if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
            raise ResearchError("Say which items to bring back.")
        d = self.board_dir(board)
        trash = d / ".trash"

        def found(n):
            p = trash / n
            if n != Path(n).name or "/" in n or "\\" in n or n.startswith(".") or not n.endswith(".md") or not p.is_file():
                raise ResearchError(f"There's no {n} in the trash.", 404)
            return p
        found(names[0])
        with _board_lock(d):
            paths = [found(n) for n in dict.fromkeys(names)]
            return self._items_on(board, [self._untrash(d, p) for p in paths])

    def _untrash(self, d: Path, p: Path) -> str:
        m = _TRASHED.fullmatch(p.name)
        stamp, old = (m[1], m[2]) if m else (None, p.stem)
        parsed = self._parsed(p)
        fields, body = (copy.deepcopy(parsed[0]), parsed[1]) if parsed and not parsed[2] else ({}, "")
        renamed = False
        for key in ("shot", "file"):
            name = fields.get(key)
            if not stamp or not isinstance(name, str) or not name:
                continue
            base = Path(name.replace("\\", "/")).name
            src = d / ".trash" / f"{stamp} {old} {base}"
            if base and src.is_file():
                (d / "files").mkdir(exist_ok=True)
                dest = self._free(d / "files", base)
                os.replace(src, d / "files" / dest)
                if dest != base:
                    fields[key], renamed = f"files/{dest}", True
        id = self._free(d, f"{old if _stem_ok(old) else 'item'}.md")[:-3]
        os.replace(p, d / f"{id}.md")
        if renamed:
            write_text(d / f"{id}.md", frontmatter.dump(fields, body))
        return id

    # ——— moving and linking ———
    def move(self, board, ids, to, link=False) -> list[dict]:
        """Items to another board (`to`: a book's id, or None for the shared board), or with `link` links to them put
        there. Returns the items as they are on `to`, in the order asked.

        An item moves whole or not at all. When one fails, those moved before it stay moved, with their positions and
        the links that pointed at them, and the error is raised. Links are rewritten board by board: a board that
        stays busy keeps its links as they were, and every returned item then carries `warnings` naming it."""
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            raise ResearchError("Say which items.")
        to = to or None
        if to is not None and not isinstance(to, str):
            raise ResearchError("Say which board: a book's id, or null for the shared board.")
        with _LOCK:
            d, dt = self.board_dir(board), self.board_dir(to)
            if os.path.normcase(str(d)) == os.path.normcase(str(dt)):
                raise ResearchError("They're on that board already.")
            here, there = self._canon(board), self._canon(to)
            paths = list(dict.fromkeys(self._path(board, i) for i in ids))
            if link:
                return self._link_all(paths, here, there, dt)
            with _board_locks(d, dt):
                out, moved, error = self._carry(paths, here, d, there, dt)
            warnings = self._relink(here, there, moved)
            if error is not None:
                raise error
            items = self._items_on(there, out)
            if warnings:
                for it in items:
                    it["warnings"] = list(warnings)
            return items

    def _link_on(self, d: Path, board, id):
        """The id of a link on board folder d to (board, id), or None."""
        for p in self._md_files(d):
            parsed = self._parsed(p)
            if parsed and not parsed[2] and _kind(parsed[0]) == "link" and parsed[0].get("item") == id \
                    and self._same(parsed[0].get("board"), board):
                return p.stem
        return None

    def _new_link(self, d: Path, layout, board, id, kind) -> str:
        """A link on board folder d to (board, id), placed by the column rule in `layout` (the caller writes it)."""
        lid = self._new_id(d, id, "", "link")
        write_text(d / f"{lid}.md", frontmatter.dump({"type": "link", "title": "", "tags": [], "board": board,
                                                      "item": id, "created": _now()}, ""))
        self._put(d, layout, lid, kind)
        return lid

    def _link_all(self, paths, here, there, dt) -> list[dict]:
        """Links on `there` to each item (a link's original for a link); one already there is used again, and an
        original that is on `there` itself is returned as it is."""
        targets = []
        for p in paths:
            parsed = self._parsed(p) or ({}, "", None, "", None)
            t = _Target(here, p.stem, p.parent, p, parsed)
            if _kind(parsed[0]) == "link" and not parsed[2]:
                t = self._resolve(parsed[0], {})
                if t is None:
                    raise ResearchError(f"The original of {p.stem} is gone.", 404)
            targets.append(t)
        out = []
        with _board_lock(dt):
            layout, changed = self._layout(dt), False
            for t in targets:
                lid = t.id if self._same(t.board, there) else self._link_on(dt, t.board, t.id)
                if lid is None:
                    lid, changed = self._new_link(dt, layout, t.board, t.id, _kind(t.parsed[0])), True
                out.append(lid)
            if changed:
                self._write_layout(dt, layout)
        return self._items_on(there, out)

    def _carry(self, paths, here, d: Path, there, dt: Path):
        """The move itself (both boards' locks held), item by item: files, positions and the quotes' sources. Returns
        the ids on `there` in the order asked, {old id: new id} of the items whose links must follow, and the error
        that stopped it, if one did (the items before it stay moved; both layouts are written either way)."""
        lay_from, lay_to = self._layout(d), self._layout(dt)
        batch, stamp = {p.stem for p in paths}, datetime.now().strftime("%Y%m%dT%H%M%S")
        result, moved, failed = {}, {}, None
        try:
            # citable items first: a quote moved with its source then finds it on the new board
            for p in sorted(paths, key=lambda p: _kind((self._parsed(p) or ({},))[0]) == "quote"):
                parsed = self._parsed(p)
                if parsed is None:
                    continue
                fields, body, error = copy.deepcopy(parsed[0]), parsed[1], parsed[2]
                kind = shown = _kind(fields)
                if kind == "link" and not error:
                    t = self._resolve(fields, {})
                    if t is not None:
                        shown = _kind(t.parsed[0])
                        there_already = t.id if self._same(t.board, there) else self._link_on(dt, t.board, t.id)
                        if there_already:       # a link moved home, or to a board that links the original already
                            self._to_trash(d, p, stamp)
                            lay_from["items"].pop(p.stem, None)
                            result[p.stem] = there_already
                            continue
                new = self._free(dt, p.name)[:-3]
                self._carry_item(p, d, dt, dt / f"{new}.md", fields, body, files=not error)
                lay_from["items"].pop(p.stem, None)
                self._put(dt, lay_to, new, shown)
                result[p.stem] = new
                if kind != "link":
                    moved[p.stem] = new
                if kind == "quote" and not error and _cite_key(fields.get("source")):
                    self._bring_source(here, there, dt, lay_to, fields["source"])
                csl = fields.get("csl")
                if kind != "link" and not error and isinstance(csl, dict) and _cite_key(csl.get("id")):
                    self._leave_link(here, d, lay_from, csl["id"], batch, there, new, kind)
        except Exception as e:          # noqa: BLE001 — move() raises it once the links of what moved follow
            failed = e
        finally:
            self._write_layout(d, lay_from)
            self._write_layout(dt, lay_to)
        return [result[p.stem] for p in paths if p.stem in result], moved, failed

    def _carry_item(self, p: Path, d: Path, dt: Path, target: Path, fields: dict, body: str, files=True):
        """One item to the other board, whole or not at all: its files first, then its .md (the front matter rewritten
        when a file was renamed, else the file moved as it is); when the .md can't move, its files go back."""
        done = self._carry_files(d, dt, fields, p.stem) if files else []
        try:
            if any(src.name != dst.name for src, dst in done):
                write_text(target, frontmatter.dump(fields, body))
                try:
                    os.remove(p)
                except OSError:
                    with suppress(OSError):
                        target.unlink()
                    raise
            else:
                os.replace(p, target)
        except BaseException:
            self._put_back(done)
            raise

    def _carry_files(self, d: Path, dt: Path, fields: dict, id) -> list:
        """An item's files (`shot`, `file`) to the other board's files/, renamed when the name is taken there (the front
        matter follows); [(from, to)] of those moved. A file another item names stays where it is. When one can't move,
        the others go back."""
        done = []
        try:
            for key in ("shot", "file"):
                name = fields.get(key)
                base = Path(name.replace("\\", "/")).name if isinstance(name, str) and name else ""
                if not base or not (d / "files" / base).is_file() or self._named_by_another(d, base, id):
                    continue
                (dt / "files").mkdir(parents=True, exist_ok=True)
                dest = dt / "files" / self._free(dt / "files", base)
                os.replace(d / "files" / base, dest)
                done.append((d / "files" / base, dest))
                if dest.name != base:
                    fields[key] = f"files/{dest.name}"
        except BaseException:
            self._put_back(done)
            raise
        return done

    @staticmethod
    def _put_back(done: list):
        for src, dst in reversed(done):
            with suppress(OSError):
                os.replace(dst, src)

    def _bring_source(self, here, there, dt: Path, layout, key):
        """Keep a moved quote's source in reach: a link on the new board to the item that holds the key, or — when the
        key was only in the old book's sources.json — a source made from that entry (a copy; the book's entry stays
        the one that prints)."""
        if any(c["key"] == key for c in self._citable(there, {})):
            return
        entry = next((c for c in self._citable(here, {}) if c["key"] == key), None)
        if entry is None:
            return
        if entry["id"] is not None:
            if self._link_on(dt, entry["board"], entry["id"]) is None:
                self._new_link(dt, layout, entry["board"], entry["id"], "source")
            return
        sid = self._new_id(dt, _source_name({**entry["csl"], "id": key}), "", "source")
        write_text(dt / f"{sid}.md", frontmatter.dump({"type": "source", "title": "", "tags": [],
                                                       "csl": copy.deepcopy(entry["csl"]), "created": _now()}, ""))
        self._put(dt, layout, sid, "source")

    def _leave_link(self, here, d: Path, layout, key, batch, there, new, kind):
        """A citable item moved off a board whose quotes (those staying) still cite its key leaves a link to it, unless
        another item or link of that board holds the key."""
        for p in self._md_files(d):
            parsed = self._parsed(p)
            if p.stem not in batch and parsed and not parsed[2] and _kind(parsed[0]) == "quote" \
                    and parsed[0].get("source") == key:
                if not any(csl.get("id") == key for csl, _, _ in self._reach(here, {})):
                    self._new_link(d, layout, there, new, kind)
                return

    def _points_at(self, p: Path, board, ids: dict) -> bool:
        parsed = self._parsed(p)
        return bool(parsed) and not parsed[2] and _kind(parsed[0]) == "link" and isinstance(parsed[0].get("item"), str) \
            and parsed[0]["item"] in ids and self._same(parsed[0].get("board"), board)

    def _relink(self, here, there, moved: dict) -> list[str]:
        """Every link on every board that pointed at a moved item points at it on its new board; a link on that board
        itself goes to the trash (the item is there now). Board by board, at best: a board that stays busy (or can't
        be written) keeps its links as they were and is named in the warnings returned."""
        warnings, memo = [], {}
        if not moved:
            return warnings
        for b, bd in self._all_boards():
            if not any(self._points_at(p, here, moved) for p in self._md_files(bd)):
                continue
            try:
                with _board_lock(bd):
                    self._relink_on(b, bd, here, there, moved)
            except (ResearchError, OSError) as e:
                why = "was busy" if isinstance(e, ResearchError) else "couldn't be written"
                warnings.append(f"{self._board_title(b, memo)} {why}, so its links to the moved items still point at "
                                "where they were.")
        return warnings

    def _relink_on(self, b, bd: Path, here, there, moved: dict):
        hits = [p for p in self._md_files(bd) if self._points_at(p, here, moved)]
        gone = [p for p in hits if self._same(b, there)]
        for p in hits:
            if p not in gone:
                fields, body = copy.deepcopy(self._parsed(p)[0]), self._parsed(p)[1]
                fields["board"], fields["item"] = there, moved[fields["item"]]
                write_text(p, frontmatter.dump(fields, body))
        if gone:
            self._discard(bd, gone)

    # ——— search ———
    def search(self, q, board=None, every=False) -> list[dict]:
        """Items whose title, text, tags, URL, site or source details hold `q`, without case or accents:
        [{"board", "board_title", "id", "type", "title", "snippet"}] ("title" is what the item is called, with
        "untitled": true when that is its first words or its kind); one board, or with `every` all of them. Links
        are left out (their originals are found); fewer than 2 characters finds nothing."""
        q = _squash(q) if isinstance(q, str) else ""
        fq = _sfold(q)
        if len(q) < 2 or not fq:
            return []
        with _LOCK:
            boards = self._all_boards() if every else [(self._canon(board), self.board_dir(board))]
            memo, out = {}, []
            for b, d in boards:
                for p in self._md_files(d):
                    parsed = self._parsed(p)
                    if not parsed or parsed[2] or _kind(parsed[0]) == "link":
                        continue
                    snippet = self._match(p, parsed, fq)
                    if snippet is not None:
                        title, untitled = self._name(parsed[0], parsed[3], memo)
                        out.append({"board": b, "board_title": self._board_title(b, memo), "id": p.stem,
                                    "type": _kind(parsed[0]), "title": title, "snippet": snippet,
                                    **({"untitled": True} if untitled else {})})
            return out

    @staticmethod
    def _match(p: Path, parsed, q: str):
        """The snippet of an item that holds q: around the first match in the text, else in the title; the title when
        only a tag, the URL, the site or the source details hold it; None when nothing does."""
        fields, body, st = parsed[0], parsed[1], parsed[4]
        key = (str(p), st.st_mtime_ns, st.st_size)
        hit = _SEARCH.get(key)
        if hit is None:
            text = _strip(body)
            hit = (text, _sfold(text))
            if len(_SEARCH) >= _PARSED_MAX:
                _SEARCH.clear()
            _SEARCH[key] = hit
        title = _title_of(fields)
        found = _snippet(*hit, q)
        if found is None:
            found = _snippet(title, _sfold(title), q)
        if found is None and any(q in _sfold(x) for x in _searched(fields)):
            found = title
        return found

    # ——— into the text ———
    def use(self, book, board, id) -> dict:
        """An item made ready for the text of `book` (a link stands for its original): a quote → its paragraphs, words,
        key and locator; a source or anything else with CSL → its key; an image → copied into the book's images/. A
        key is resolved on the item's own board, then in the book's sources.json; the source is added to sources.json
        when it isn't there (`added`), under the next free key when that key is another source's."""
        with _LOCK:
            try:
                self.books.dir(book)
            except BooksError as e:
                raise ResearchError(str(e), 404) from None
            p = self._path(board, id)
            parsed = self._parsed(p)
            if parsed is None:
                raise ResearchError(f"There's no item {id} on this board.", 404)
            home, d = self._canon(board), p.parent
            if _kind(parsed[0]) == "link" and not parsed[2]:
                t = self._resolve(parsed[0], {})
                if t is None:
                    raise ResearchError("The original of this link is gone.", 404)
                home, d, parsed = t.board, t.dir, t.parsed
            fields, body, error = parsed[0], parsed[1], parsed[2]
            if error:
                raise ResearchError(error)
            kind = _kind(fields)
            if kind in ("note", "piece"):
                raise ResearchError(NOT_IN_TEXT)
            if kind == "image":
                return self._use_image(book, d, fields)
            if kind == "quote":
                key = fields["source"] if _cite_key(fields.get("source")) else None
                out = {"kind": "quote", "paragraphs": _paragraphs(body), "words": manuscript.counts(body)["words"],
                       "key": key, "locator": fields["locator"] if isinstance(fields.get("locator"), str) else "",
                       "added": False}
                if key:
                    entry = next((c for c in self._citable(home, {}) if c["key"] == key), None)
                    if entry is not None and entry["id"] is None and self._same(home, self._canon(book)):
                        pass                    # from this book's own sources.json: cited as it is
                    elif entry is not None:
                        out["key"], out["added"] = self._to_book(book, entry["csl"])
                    elif key not in {e.get("id") for e in self._sources(book) if isinstance(e, dict)}:
                        out["warning"] = SOURCE_GONE
                return out
            csl = fields.get("csl")
            if not isinstance(csl, dict) or not _cite_key(csl.get("id")):
                raise ResearchError("This item has no source to cite.")
            key, added = self._to_book(book, csl)
            return {"kind": "cite", "key": key, "added": added}

    def _sources(self, book) -> list:
        try:
            return self.books.sources(book)
        except BooksError as e:
            raise ResearchError(str(e)) from None

    def _to_book(self, book, csl: dict) -> tuple:
        """(the key to cite, whether it was added to the book's sources.json): the same source already there is cited
        under its key (its own first, else any); else it is added, under the next free key when its key is another
        source's. Written only through Books.save_sources."""
        items = self._sources(book)
        by = {e.get("id"): e for e in items if isinstance(e, dict)}
        key = csl["id"]
        same = _book_key(items, csl)
        if same:
            return same, False
        cand, n = key, 0
        while cand in by:
            cand, n = _next_key(key, n), n + 1
        try:
            self.books.save_sources(book, items + [{**copy.deepcopy(csl), "id": cand}])
        except BooksError as e:
            raise ResearchError(str(e)) from None
        return cand, True

    def _use_image(self, book, d: Path, fields: dict) -> dict:
        name = fields.get("file")
        base = Path(name.replace("\\", "/")).name if isinstance(name, str) and name else ""
        if not base or not (d / "files" / base).is_file():
            raise ResearchError("This image's file isn't on its board any more.", 404)
        try:
            src = self.books.save_image(book, base, (d / "files" / base).read_bytes())
        except BooksError as e:
            raise ResearchError(str(e), e.code) from None
        return {"kind": "image", "src": src, "alt": _squash(_title_of(fields))}

    # ——— change markers and files ———
    def _newest(self, d: Path) -> float:
        newest = 0.0
        if not d.is_dir():
            return newest
        paths = [d, d / BOARD_FILE, d / "files"] + self._md_files(d)
        for p in paths:
            try:
                newest = max(newest, p.stat().st_mtime)
            except OSError:
                pass
        return newest

    def stamp(self, board, every=False) -> float:
        """A change marker: the newest modification time of a board's folder, items, board.json and files/ (not the
        trash); with `every`, of every board."""
        if not every:
            return self._newest(self.board_dir(board))
        newest = self._newest(self.board_dir(None))
        for b in self.books.dirs():
            newest = max(newest, self._newest(b / "research"))
        return newest

    def file(self, rel) -> Path:
        """A file of a board to serve: rel is `<_shared or a book id>/<name>`, a name in that board's files/ with a
        known type. Never a dot-name, never outside; anything else is a 404."""
        parts = str(rel).replace("\\", "/").split("/")
        if len(parts) != 2 or any(p in ("", ".", "..") or p.startswith(".") or ":" in p for p in parts):
            raise ResearchError("not found", 404)
        try:
            d = self.board_dir(None if parts[0] == SHARED_URL else parts[0])
        except ResearchError:
            raise ResearchError("not found", 404) from None
        folder = (d / "files").resolve()
        p = (d / "files" / parts[1]).resolve()
        if p.parent != folder or p.suffix.lower() not in FILE_TYPES or not p.is_file():
            raise ResearchError("not found", 404)
        return p
