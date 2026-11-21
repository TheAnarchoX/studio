"""One search across the library: poems, pieces, books, series, designs and the research boards' items.

An index in memory, checked against the files on use (spec S1–S8). Each item keeps its fields as Studio shows them,
the same fields folded for matching (case and accents don't matter), and the (mtime, size) of the files it was read
from. A check walks the library, re-reads only the items whose files changed, and swaps the new index in with one
assignment, so a search always reads a whole index. Nothing is written anywhere.

Ranges in a reply (`title_marks`, a snippet's `marks`, a poem jump's `start` and `end`) count UTF-16 code units, as the
browser's strings do: the same numbers as Python's indices unless the text holds characters beyond the BMP (an emoji).
"""
from __future__ import annotations

import bisect
import importlib
import importlib.util
import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from . import config, manuscript
from .books import BOOK_FILE, Books, _containers, valid_file
from .home import _kind_name
from .store import SERIES_FILE, WRITING_NOTES, Store, iso

KINDS = [("poem", "Poems"), ("piece", "Pieces"), ("book", "Books"), ("series", "Series"), ("design", "Designs"),
         ("research", "Research")]       # group order and labels
FRESH = 3.0         # seconds a check stays fresh: a search after that starts another
WAIT = 0.15         # seconds a search waits for a running check
TERMS = 12          # at most this many terms in a query
TERM_LENGTH = 200   # characters of a term
AROUND = 40         # characters of a snippet either side of the match
WIDEN = 20          # at most this many more, to end a snippet at a word boundary
POSTING_NOTES = "NOTES.md"
SCAN_THREADS = 8            # threads that list poem folders during a check of a large library
SCAN_THREADS_FROM = 200     # poem folders: below this one thread does it
FIELDS = ("title", "text", "name", "tagline", "subtitle", "notes", "posting", "note")     # in the order ties go
LABELS = {"notes": "Writing notes", "posting": "Posting notes", "note": "In a note", "tagline": "Tagline",
          "subtitle": "Subtitle"}
_MAIN = ("title", "text", "name", "tagline", "subtitle")     # an item found there ranks above one found in notes
_COUNTS = {"poem": "poems", "series": "series", "design": "designs", "book": "books", "piece": "pieces"}
_QUOTES = "\"“”„"
_TOKEN = re.compile(f"[{_QUOTES}]([^{_QUOTES}]*)(?:[{_QUOTES}]|\\Z)|[^\\s{_QUOTES}]+")
_SPACES = str.maketrans("\n\r\t", "   ")
_FOLDED: dict[str, str] = {}


# ——— folding ———
def _fold_char(c: str) -> str:
    f = _FOLDED.get(c)
    if f is None:
        f = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x)).casefold()
        f = "".join(x for x in unicodedata.normalize("NFKD", f) if not unicodedata.combining(x))
        _FOLDED[c] = f
    return f


def fold_map(s: str) -> tuple[str, list[int]]:
    """s folded (NFKD, combining marks dropped, casefold, per character), and for each folded character the index in s
    of the character it came from ("Straße" -> "strasse", the two s's both from the ß)."""
    if s.isascii():
        return s.lower(), list(range(len(s)))
    parts = [_fold_char(c) for c in s]
    folded = "".join(parts)
    if set(map(len, parts)) == {1}:
        return folded, list(range(len(s)))
    back = []
    for i, p in enumerate(parts):
        back.extend([i] * len(p))
    return folded, back


def fold(s: str) -> str:
    if s.isascii():
        return s.lower()
    get = _FOLDED.get
    return "".join([get(c) or _fold_char(c) for c in s])


def parse_query(q: str) -> list[str]:
    """The query's terms, folded: words, and phrases in quotes (the closing quote may be left off) with their inner
    spaces collapsed. Empty and repeated terms are dropped; at most TERMS terms of at most TERM_LENGTH characters."""
    terms = []
    for m in _TOKEN.finditer(str(q or "")):
        raw = m.group(0) if m.group(1) is None else m.group(1)
        term = " ".join(fold(raw).split())[:TERM_LENGTH].rstrip()
        if term and term not in terms:
            terms.append(term)
            if len(terms) == TERMS:
                break
    return terms


def _span(back, fa, fb, n):
    """The range in the original text of folded characters [fa, fb). Marks dropped while folding (a decomposed accent)
    stay with the letter before them."""
    last = back[fb - 1]
    end = back[fb] if fb < len(back) else n
    return back[fa], max(end, last + 1)


def _ranges(s, terms):
    """Every occurrence of every term in s, as merged, sorted [start, end) ranges of s."""
    folded, back = fold_map(s)
    spans = []
    for t in terms:
        i = folded.find(t)
        while i >= 0:
            spans.append(_span(back, i, i + len(t), len(s)))
            i = folded.find(t, i + 1)
    spans.sort()
    out = []
    for a, b in spans:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _units(s, ranges):
    """Ranges of s in UTF-16 code units (what the browser's strings count)."""
    if not ranges or s.isascii() or max(s) <= "\uffff":
        return [[a, b] for a, b in ranges]
    astral = [i for i, c in enumerate(s) if c > "\uffff"]
    return [[a + bisect.bisect_left(astral, a), b + bisect.bisect_left(astral, b)] for a, b in ranges]


def _first(text, candidates):
    """(start, end) in text of the first candidate (folded) that occurs in it, or None."""
    folded, back = fold_map(text)
    for c in candidates:
        i = folded.find(c)
        if i >= 0:
            return _span(back, i, i + len(c), len(text))
    return None


def _cut(text, a, b):
    """About AROUND characters either side of [a, b), widened to word boundaries (up to WIDEN more)."""
    n = len(text)
    start = max(0, a - AROUND)
    if 0 < start and not text[start - 1].isspace() and not text[start].isspace():
        s = start
        while s > 0 and not text[s - 1].isspace() and start - s < WIDEN:
            s -= 1
        if s == 0 or text[s - 1].isspace():
            start = s
    while start < a and text[start].isspace():
        start += 1
    end = min(n, b + AROUND)
    if end < n and not text[end].isspace() and not text[end - 1].isspace():
        e = end
        while e < n and not text[e].isspace() and e - end < WIDEN:
            e += 1
        if e == n or text[e].isspace():
            end = e
    while end > b and text[end - 1].isspace():
        end -= 1
    return start, end


def _snippet(text, terms):
    """{"text", "marks"} around the first occurrence of the first term found in text; None when no term is there."""
    found = _first(text, terms)
    if found is None:
        return None
    start, end = _cut(text, *found)
    lead, tail = ("…" if start > 0 else ""), ("…" if end < len(text) else "")
    body = text[start:end].translate(_SPACES)
    shown = lead + body + tail
    marks = [(a + len(lead), b + len(lead)) for a, b in _ranges(body, terms)]
    return {"text": shown, "marks": _units(shown, marks)}


# ——— reading the library ———
def _read(path) -> str:
    """A file's text as Studio reads it: UTF-8, universal newlines. Raises OSError or ValueError."""
    return Path(path).read_text(encoding="utf-8")


def _case(name: str) -> str:
    """A file name as the file system compares it: os.path.normcase, without its cost (it runs per file per check)."""
    return name.lower() if os.name == "nt" else name


def _scan(path) -> dict:
    """{_case(name): DirEntry} of a folder; {} when it can't be listed."""
    try:
        with os.scandir(path) as it:
            if os.name == "nt":
                return {e.name.lower(): e for e in it}
            return {e.name: e for e in it}
    except OSError:
        return {}


_POEM_FILES = tuple(_case(n) for n in ("poem.json", WRITING_NOTES, POSTING_NOTES))
_DESIGNS = _case("designs")


def _stat(entry):
    """(st_mtime_ns, st_size) of a file's DirEntry; None when there is no such file."""
    if entry is None:
        return None
    try:
        if not entry.is_file():
            return None
        st = entry.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _is_dir(entry):
    try:
        return entry.is_dir()
    except OSError:
        return False


def _look(folder: str):
    """What the file system says of a folder in a series (no file is opened): its poem.json, writing notes and
    posting notes as DirEntries, their (mtime, size) (None for a missing file), and its designs as (DirEntry, (mtime,
    size)). Only files right in designs/: never designs/.trash."""
    entries = _scan(folder)
    files = [entries.get(n) for n in _POEM_FILES]
    sig = tuple(_stat(e) for e in files)
    designs, d = [], entries.get(_DESIGNS)
    if sig[0] is not None and d is not None and _is_dir(d):
        for f in sorted(_scan(d.path).values(), key=lambda e: e.name):
            if not f.name.startswith(".") and _case(f.name).endswith(".json"):
                st = _stat(f)
                if st:
                    designs.append((f, st))
    return files, sig, designs


def _look_all(folders: list[str]) -> list:
    """_look for each folder. A large library is listed by a few threads at once: listing a folder waits on the
    system, not on Python (5,000 poem folders: 0.1 s instead of 0.5 s)."""
    if len(folders) < SCAN_THREADS_FROM:
        return [_look(f) for f in folders]
    n = min(SCAN_THREADS, os.cpu_count() or 1)
    size = -(-len(folders) // n)
    with ThreadPoolExecutor(n, thread_name_prefix="studio-search-scan") as pool:
        parts = pool.map(lambda chunk: [_look(f) for f in chunk],
                         [folders[i:i + size] for i in range(0, len(folders), size)])
        return [look for part in parts for look in part]


def _inline(nodes):
    return "".join(n.get("text", "") if n.get("type") == "text" else "\n" if n.get("type") == "hard_break" else ""
                   for n in nodes)


def _piece_text(doc):
    """(text, notes) of a parsed piece: blocks and captions, then the text of its notes; the title block left out."""
    content = doc.get("content") or []
    title = content[0].get("content") if content and content[0].get("type") == "title" else None
    boxes, text, notes = [], [], []
    _containers(doc, boxes)
    for kind, box in boxes:
        if kind == "caption":
            text.append(str(box["attrs"]["alt"]))
        elif kind == "note":
            notes.append(_inline(box))
        elif box is not title:
            text.append(_inline(box))
    return "\n".join(text), "\n".join(notes)


class _Item:
    """One thing search can find. fields: ((name, text), ...): the title (a design's or series' name) first, then the
    other fields that hold text, in FIELDS order (the order ties go). sig: what its files were when read."""
    __slots__ = ("kind", "sig", "fields", "folded", "hay", "time", "where", "info")

    def __init__(self, kind, sig, fields, when, where, info):
        self.kind, self.sig, self.time, self.where, self.info = kind, sig, when, where, info
        self.fields = (fields[0],) + tuple(sorted((f for f in fields[1:] if f[1]), key=lambda f: FIELDS.index(f[0])))
        self.folded = tuple(fold(t) for _, t in self.fields)
        self.hay = "\n".join(self.folded)          # a term never holds a newline: it can't match across fields

    @property
    def title(self):
        return self.fields[0][1]


def _newest(sig):
    return max((s[0] for s in sig if isinstance(s, tuple)), default=0) / 1e9


class Index:
    def __init__(self, library: Path):
        self.library = Path(library)
        self._snap = (None, None, None)           # (items, counts, checked at): None until the first build ends
        self._progress = [0, 0]                   # [done, total] of the first build
        self._cond = threading.Condition()
        self._lock = threading.Lock()             # one walk at a time
        self._running = 0                         # checks running or about to
        self._ended = None                        # time.monotonic() when the last check ended
        self._error = None

    # ——— freshness ———
    def check(self) -> None:
        """Walk the library now; re-read what changed, drop what's gone."""
        with self._cond:
            self._running += 1
        self._run(quiet=False)

    def ensure(self, wait: float = WAIT) -> None:
        """Start a check in the background unless one runs or the last ended less than FRESH seconds ago; then wait
        up to `wait` seconds for a running check to end."""
        with self._cond:
            if self._running == 0 and (self._ended is None or time.monotonic() - self._ended > FRESH):
                self._running += 1
                try:
                    threading.Thread(target=self._run, args=(True,), name="studio-search", daemon=True).start()
                except RuntimeError:
                    self._running -= 1
                    raise
            if wait and wait > 0:
                self._cond.wait_for(lambda: self._running == 0, timeout=wait)

    def _run(self, quiet):
        try:
            with self._lock:
                self._walk()
            self._error = None
        except Exception as e:      # noqa: BLE001  in the background a failure becomes a sentence in the reply
            if not quiet:
                raise
            self._error = f"Search couldn't read the library: {e}"
        finally:
            with self._cond:
                self._running -= 1
                self._ended = time.monotonic()
                self._cond.notify_all()

    def state(self) -> dict:
        return self._state(self._snap)

    def _state(self, snap):
        items, counts, checked = snap
        done, total = self._progress
        return {"checked": iso(checked) if checked else None, "checking": self._running > 0,
                "building": None if items is not None else {"done": done, "total": total},
                "counts": dict(counts or {v: 0 for v in _COUNTS.values()})}

    # ——— the walk ———
    def _walk(self):
        old = self._snap[0]
        progress = [0, 0]
        if old is None:
            self._progress = progress
            old = {}
        new = {}
        try:
            series_dirs = Store(self.library / "Poems").series_dirs()
        except OSError:
            series_dirs = []
        series, poems = [], []
        for sd in series_dirs:
            entries = _scan(sd)
            series.append((sd, entries.get(_case(SERIES_FILE))))
            poems += [(sd.name, e) for e in sorted(entries.values(), key=lambda e: e.name)
                      if not e.name.startswith(("_", ".")) and _is_dir(e)]
        pieces = []
        try:
            book_dirs = Books(self.library / "Books").dirs()
        except OSError:
            book_dirs = []
        for d in book_dirs:
            try:
                st = os.stat(d / BOOK_FILE)
            except OSError:
                continue
            key, sig = ("book", d.name), ((st.st_mtime_ns, st.st_size),)
            book = old.get(key)
            if book is None or book.sig != sig:
                book = self._read_book(d, sig)
            if book is None:
                continue
            new[key] = book
            files = _scan(d / "manuscript")
            for file, kind, form in book.info["contents"]:
                e = files.get(_case(file))
                if _stat(e):
                    pieces.append((book, file, kind, form, e))
        progress[1] = len(poems) + len(pieces)

        for (series_name, folder), look in zip(poems, _look_all([e.path for _, e in poems])):
            self._poem(series_name, folder.name, *look, old, new)
            progress[0] += 1
        for book, file, kind, form, e in pieces:
            key, sig = ("piece", book.info["id"], file), (_stat(e), form, kind, book.title)
            item = old.get(key)
            if item is None or item.sig != sig:
                item = self._read_piece(e.path, book, file, kind, form, sig)
            if item is not None:
                new[key] = item
            progress[0] += 1
        for sd, e in series:
            key, sig = ("series", sd.name), (_stat(e),)
            item = old.get(key)
            if item is None or item.sig != sig:
                item = self._read_series(sd, e, sig)
            if item is not None:
                new[key] = item

        counts = {v: 0 for v in _COUNTS.values()}
        for item in new.values():
            counts[_COUNTS[item.kind]] += 1
        self._snap = (new, counts, time.time())

    def _poem(self, series, folder, files, sig, designs, old, new):
        if sig[0] is None:
            return                          # not a poem folder
        pid = f"{series}/{folder}"          # Store.pid
        key = ("poem", pid)
        poem = old.get(key)
        if poem is None or poem.sig != sig:
            poem = self._read_poem(folder, pid, series, sig, files)
        if poem is None:
            return
        new[key] = poem
        for f, st in designs:
            dsig = (st, poem.title)
            slug = f.name[:-len(".json")]
            dkey = ("design", pid, slug)
            item = old.get(dkey)
            if item is None or item.sig != dsig:
                item = self._read_design(f.path, slug, poem, dsig)
            if item is not None:
                new[dkey] = item

    # ——— the sources (S1); a file that can't be read leaves its item out ———
    @staticmethod
    def _read_poem(folder, pid, series, sig, files):
        try:
            meta = json.loads(_read(files[0].path))
            notes, posting = (_read(e.path) if s else "" for e, s in zip(files[1:], sig[1:]))
        except (OSError, ValueError):
            return None
        if not isinstance(meta, dict):
            return None
        lines = meta.get("lines")
        text = "\n".join("" if x is None else str(x) for x in lines) if isinstance(lines, list) else ""
        fields = [("title", str(meta.get("title") or folder)), ("text", text), ("notes", notes), ("posting", posting)]
        return _Item("poem", sig, fields, _newest(sig), series, {"pid": pid})

    @staticmethod
    def _read_design(path, slug, poem, sig):
        try:
            data = json.loads(_read(path))
        except (OSError, ValueError):
            return None
        name = data.get("name") if isinstance(data, dict) else None
        name = name if isinstance(name, str) and name else slug
        pid = poem.info["pid"]
        return _Item("design", sig, [("name", name)], _newest(sig), f"{poem.title} · {poem.where}",
                     {"pid": pid, "slug": slug})

    @staticmethod
    def _read_series(sd, entry, sig):
        tagline = ""
        if sig[0] is not None:
            try:
                meta = json.loads(_read(entry.path))
            except (OSError, ValueError):
                return None
            value = meta.get("tagline") if isinstance(meta, dict) else None
            tagline = value if isinstance(value, str) else ""
        return _Item("series", sig, [("name", sd.name), ("tagline", tagline)], _newest(sig), "Series", {})

    @staticmethod
    def _read_book(d, sig):
        try:
            raw = _read(d / BOOK_FILE)
            meta = json.loads(raw[1:] if raw.startswith("\ufeff") else raw)       # as books.py reads it (utf-8-sig)
        except (OSError, ValueError):
            return None
        if not isinstance(meta, dict):
            return None
        contents, seen = [], set()
        for e in meta.get("contents") if isinstance(meta.get("contents"), list) else []:
            if isinstance(e, dict) and valid_file(e.get("file")) and e["file"] not in seen:
                seen.add(e["file"])
                contents.append((e["file"], e.get("kind"), Books._form(e)))
        subtitle = meta.get("subtitle") if isinstance(meta.get("subtitle"), str) else ""
        fields = [("title", str(meta.get("title") or d.name)), ("subtitle", subtitle)]
        return _Item("book", sig, fields, _newest(sig), "Books", {"id": d.name, "contents": tuple(contents)})

    @staticmethod
    def _read_piece(path, book, file, kind, form, sig):
        try:
            md = _read(path)
        except (OSError, ValueError):
            return None
        try:
            doc = manuscript.parse(md, form)
            title = manuscript.title_of(md) or _kind_name(kind)
        except Exception:       # noqa: BLE001  a piece the parser can't read is left out, never the whole check
            return None
        text, notes = _piece_text(doc)
        return _Item("piece", sig, [("title", title), ("text", text), ("note", notes)], _newest(sig), book.title,
                     {"book": book.info["id"], "file": file})

    # ——— searching ———
    def search(self, q: str, kinds: list[str] | None = None, limit: int = 8) -> dict:
        q = "" if q is None else str(q)
        limit = max(1, min(200, int(8 if limit is None else limit)))
        snap = self._snap                   # one index for the whole search, even if a check swaps in a newer one
        items = snap[0]
        st = self._state(snap)
        error = self._error                 # read once: a check in the background may change it meanwhile
        reply = {"q": q, "groups": [], "counts": st["counts"], "checked": st["checked"], "checking": st["checking"],
                 "building": st["building"], "errors": [error] if error else []}
        terms = parse_query(q)
        if items is None or not terms:
            return reply
        whole = " ".join(terms)
        found = {k: [] for k, _ in KINDS if kinds is None or k in kinds}
        for item in items.values():
            bucket = found.get(item.kind)
            if bucket is None:
                continue
            hay = item.hay
            for t in terms:
                if t not in hay:
                    break
            else:
                bucket.append((_score(item, terms, whole), item))
        for kind, label in KINDS:
            if kind not in found:
                continue
            if kind == "research":
                results, error = _research(self.library, q, terms)
                if error:
                    reply["errors"].append(error)
                if results:
                    reply["groups"].append({"kind": kind, "label": label, "total": len(results),
                                            "items": results[:limit]})
                continue
            hits = found[kind]
            if not hits:
                continue
            hits.sort(key=lambda h: (-h[0][0], -h[1].time, h[1].folded[0]))
            reply["groups"].append({"kind": kind, "label": label, "total": len(hits),
                                    "items": [_result(item, terms, whole, scored) for scored, item in hits[:limit]]})
        return reply


def _score(item, terms, whole):
    """(score, best field, distinct terms per field). The best field holds the most distinct terms (ties in FIELDS
    order); the score: 600 the title is the query, 500 it starts with it, 400 it holds every term, else 300 found
    mainly in the text (200 in notes); +50 when the whole query is in that field."""
    folded = item.folded
    counts = [sum(1 for t in terms if t in f) for f in folded]
    best = max(range(len(folded)), key=lambda i: (counts[i], -i))
    title = folded[0]
    if title == whole:
        score = 600
    elif title.startswith(whole):
        score = 500
    elif counts[0] == len(terms):
        score = 400 + (50 if whole in title else 0)
    else:
        score = (300 if item.fields[best][0] in _MAIN else 200) + (50 if whole in folded[best] else 0)
    return score, best, counts


def _result(item, terms, whole, scored):
    _, best, counts = scored
    field, text = item.fields[best]
    rest = [i for i in range(1, len(item.fields)) if counts[i]]
    near = max(rest, key=lambda i: (counts[i], -i)) if rest else None
    title = item.title
    out = {"kind": item.kind, "title": title, "title_marks": _units(title, _ranges(title, terms)),
           "where": item.where, "field": field, "field_label": LABELS.get(field, ""),
           "snippet": _snippet(item.fields[near][1], terms) if near is not None else None}
    info = item.info
    if item.kind in ("poem", "piece"):
        a, b = _first(text, [whole] + terms) or (0, 0)
        if item.kind == "poem":
            page = "art" if field == "posting" else "write"
            out["href"] = f"#/poem/{quote(info['pid'], safe='')}/{page}"
            start, end = _units(text, [(a, b)])[0]
            out["jump"] = {"type": "poem", "id": info["pid"], "field": field, "start": start, "end": end,
                           "match": text[a:b]}
        else:
            out["href"] = f"#/book/{quote(info['book'], safe='')}/write/{quote(info['file'], safe='')}"
            out["jump"] = {"type": "piece", "book": info["book"], "file": info["file"], "match": text[a:b]}
    elif item.kind == "design":
        out["href"] = f"#/poem/{quote(info['pid'], safe='')}/design"
        out["jump"] = {"type": "design", "id": info["pid"], "slug": info["slug"]}
    elif item.kind == "series":
        out["href"] = f"#/series/{quote(title, safe='')}"
        out["jump"] = {"type": "series"}
    else:
        out["href"] = f"#/book/{quote(info['id'], safe='')}"
        out["jump"] = {"type": "book"}
    return out


def _research(library, q, terms):
    """(results, error) from part 3's research board when studio/research.py is there; (None, None) when it isn't."""
    try:
        if importlib.util.find_spec("studio.research") is None:
            return None, None
    except (ImportError, ValueError):
        return None, None
    try:
        research = importlib.import_module("studio.research")
        out = []
        for x in research.Research(library).search(q, every=True):
            snippet = str(x.get("snippet") or "")
            title = str(x.get("title") or "") or " ".join(snippet.split())[:60]
            board = x.get("board")
            shown = snippet.translate(_SPACES)
            out.append({"kind": "research", "title": title, "title_marks": _units(title, _ranges(title, terms)),
                        "where": str(x.get("board_title") or ""),
                        "href": f"#/book/{quote(str(board), safe='')}/board" if board else "#/research",
                        "field": "text", "field_label": "",
                        "snippet": {"text": shown, "marks": _units(shown, _ranges(shown, terms))} if shown else None,
                        "jump": {"type": "research", "board": board, "id": x.get("id")}})
        return out, None
    except Exception as e:      # noqa: BLE001  the research board must not take the rest of the search down
        return None, f"Research couldn't be searched: {e}"


_index = None
_index_lock = threading.Lock()


def index() -> Index:
    """The current library's index; a new one when the library setting changes."""
    global _index
    with _index_lock:
        if _index is None or _index.library != config.ART:
            _index = Index(config.ART)
        return _index
