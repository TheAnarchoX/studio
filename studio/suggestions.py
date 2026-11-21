"""Claude's suggestions for a book: Books/<title>/suggestions.json.

Claude proposes (an edit, a note, an index entry, a citation, a comment) and the writer decides. This module owns
the file; the app's web API and the MCP server both go through it, so the writes that must not interleave take the
book's `file_lock`. The file is read tolerantly and written carefully: keys Studio doesn't know are kept, entries it
can't make sense of are left alone, and a file that can't be parsed is never overwritten.
"""
from __future__ import annotations

import copy
import json
import re
import secrets
from datetime import datetime
from pathlib import Path

from . import books, manuscript
from .books import BooksError
from .store import write_text

_books = books          # the module: the functions below name their Books argument `books`

FILE = "suggestions.json"
KINDS = ("edit", "note", "index", "cite", "comment")
CONTEXT = 32            # characters of text kept either side of a quote, to find it again after the text moves
MAX_QUOTE = 1000
MAX_TERM = 200
MAX_ITEMS = 200         # suggestions in one call
MAX_OPEN = 1000         # open suggestions in one book
KEEP_DECIDED = 1000     # decided suggestions kept; the oldest `decided` go first


def read(books, book) -> dict:
    """The file as {"version": 1, "suggestions": [...]}; a missing file is empty (and isn't created)."""
    return _read(books._dir(book))


def _read(d: Path) -> dict:
    try:
        raw = (d / FILE).read_text(encoding="utf-8-sig")
    except (FileNotFoundError, NotADirectoryError):
        return {"version": 1, "suggestions": []}
    except (OSError, UnicodeDecodeError) as e:      # unreadable is not missing: never let a save write over it
        raise BooksError(f"{FILE} can't be read: {e}") from None
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise BooksError(f"{FILE} can't be read: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("suggestions", []), list):
        raise BooksError(f"{FILE} can't be read: it should hold an object with a list of suggestions.")
    data.setdefault("version", 1)
    data.setdefault("suggestions", [])
    return data


def _save(books, d: Path, data: dict):
    """Write the file (the caller holds the lock), dropping the oldest decided suggestions beyond KEEP_DECIDED."""
    items = data["suggestions"]
    decided = [(i, s) for i, s in enumerate(items) if isinstance(s, dict) and s.get("status") not in (None, "open")]
    if len(decided) > KEEP_DECIDED:
        decided.sort(key=lambda p: str(p[1].get("decided") or ""))
        drop = {i for i, _ in decided[:len(decided) - KEEP_DECIDED]}
        data = {**data, "suggestions": [s for i, s in enumerate(items) if i not in drop]}
    write_text(d / FILE, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


TEXT_FIELDS = ("before", "after", "in", "text", "term", "source", "locator", "made", "decided")


def entries(data) -> list:
    """The well-formed suggestions: objects with a string id, file, quote and status, a known kind, and text in the
    other fields Studio reads when they are there (a hand edit that puts a number in one is left alone)."""
    return [s for s in data.get("suggestions", []) if isinstance(s, dict) and s.get("kind") in KINDS
            and all(isinstance(s.get(k), str) for k in ("id", "file", "quote", "status"))
            and all(isinstance(s[k], str) for k in TEXT_FIELDS if k in s)]

# ——— finding the words again, and applying a suggestion (pure functions on a piece's document) ———

def matches(doc: dict, quote: str) -> list:
    """Every place the quote occurs, in the numbering Find uses (all containers, captions included)."""
    return books._matches(doc, books._pattern(quote, False, True))


def score(text: str, start: int, end: int, before: str, after: str) -> int:
    """How much of the stored context sits next to a match: the common run before it plus the common run after."""
    a, b = text[:start], before
    n = 0
    while n < min(len(a), len(b)) and a[-1 - n] == b[-1 - n]:
        n += 1
    a, b = text[end:], after
    m = 0
    while m < min(len(a), len(b)) and a[m] == b[m]:
        m += 1
    return n + m


def locate(doc: dict, s: dict) -> dict | None:
    """The suggestion's words in the document: {"kind", "box", "start", "end", "index", "text"}, or None (changed)."""
    kind = s.get("in", "text")
    found = [(i, m) for i, m in enumerate(matches(doc, s["quote"])) if m[0] == kind]
    if not found:
        return None
    if len(found) > 1:
        context = (s.get("before") or "") + (s.get("after") or "")
        scored = [(score(m[4], m[2], m[3], s.get("before") or "", s.get("after") or ""), -i, i, m)
                  for i, (_, m) in enumerate(found)]
        best = max(scored, key=lambda t: t[:2])
        if context and best[0] == 0:
            return None
        found = [found[best[2]]]
    index, (kind, box, start, end, text) = found[0]
    return {"kind": kind, "box": box, "start": start, "end": end, "index": index, "text": text}


def context(text: str, start: int, end: int) -> tuple[str, str]:
    """The text kept either side of a quote (CONTEXT characters), to find it again."""
    return text[max(0, start - CONTEXT):start], text[end:end + CONTEXT]


def _split(box: list, offset: int) -> int:
    """Split the text node that holds `offset` (a note or citation counts as one character) and return the index
    of the node where `offset` begins; the length of the box when it is the end."""
    at = 0
    for i, n in enumerate(box):
        size = len(n["text"]) if n.get("type") == "text" else 1
        if offset == at:
            return i
        if offset < at + size:
            cut = offset - at
            box[i:i + 1] = [{**n, "text": n["text"][:cut]}, {**n, "text": n["text"][cut:]}]
            return i + 1
        at += size
    return len(box)


def _marked(node: dict, mark: dict) -> list:
    """The node's marks with `mark` set (replacing an idx; joining a comment's note), in the schema's order."""
    old = node.get("marks") or []
    if mark["type"] == "comment":
        for m in old:
            if m["type"] == "comment" and (m.get("attrs") or {}).get("note"):
                mark = {**mark, "attrs": {"note": m["attrs"]["note"] + " · " + mark["attrs"]["note"]}}
    marks = [m for m in old if m["type"] != mark["type"]] + [mark]
    rank = manuscript.SCHEMA["marks"]
    return sorted(marks, key=lambda m: rank.index(m["type"]) if m["type"] in rank else len(rank))


def _shared_marks(left, right) -> list:
    """The marks the nodes on both sides of an insertion point have in common: what the parser gives a note or
    citation inside a marked run, so the run isn't split when it is written out."""
    if not left or not right:
        return []
    return [m for m in left.get("marks") or [] if m in (right.get("marks") or [])]


def apply(doc: dict, s: dict, sources: list) -> bool:
    """Make the suggestion in the document, in place. False, with the document untouched, when its words aren't
    there any more, or when a citation names a source the book doesn't have."""
    kind = s.get("kind")
    if kind == "cite" and s.get("source") not in {x.get("id") for x in sources if isinstance(x, dict)}:
        return False
    at = locate(doc, s)
    if at is None:
        return False
    box, start, end = at["box"], at["start"], at["end"]
    if kind == "edit":
        books._rewrite(box, at["kind"], [(start, end)], s["text"])
    elif at["kind"] == "caption":
        return False                # a caption is a plain string: it can't carry marks, notes or citations
    elif kind in ("index", "comment"):
        a = _split(box, start)
        b = _split(box, end)
        if kind == "index":
            term = s.get("term")
            mark = {"type": "idx", "attrs": {"term": None if not term or term == s["quote"] else term}}
        else:
            mark = {"type": "comment", "attrs": {"note": s["text"]}}
        for n in box[a:b]:
            if n.get("type") == "text":
                n["marks"] = _marked(n, mark)
    elif kind in ("note", "cite") and at["kind"] == "text":     # no note inside a note
        node = ({"type": "note", "content": [{"type": "text", "text": s["text"]}]} if kind == "note" else
                {"type": "cite", "attrs": {"items": [{"key": s["source"], "prefix": "",
                                                       "locator": s.get("locator", "")}]}})
        at_end = _split(box, end)
        shared = _shared_marks(box[at_end - 1] if at_end else None, box[at_end] if at_end < len(box) else None)
        if shared:
            node["marks"] = shared
        box.insert(at_end, node)
    else:
        return False
    return True


# ——— making suggestions ———

MAX_WHY = 500


class _Refused(Exception):
    """One item of a call that can't be made; the message is the reason, written for Claude to act on."""


def _text_field(item: dict, name: str, what: str, required=True) -> str:
    v = item.get(name)
    if v is None and not required:
        return ""
    if not isinstance(v, str):
        raise _Refused(f"{what} must be text.")
    return v


def _one_line(text: str) -> str:
    """Line breaks become single spaces (a break would split the paragraph a note or comment ends up in)."""
    return re.sub(r"\s*[\r\n]+\s*", " ", text)


def _check_kind(item: dict, kind: str, quote: str, meta: dict, source_ids) -> dict:
    """The kind's own fields, checked: {"text"} / {"term"} / {"source", "locator"} (and nothing the kind doesn't use)."""
    features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
    if kind == "index" and features.get("index") is not True:
        raise _Refused("This book has no index: turn the index on in the book's features before suggesting index terms.")
    if kind == "cite" and features.get("sources") is not True:
        raise _Refused("This book doesn't use sources: turn sources on in the book's features before suggesting citations.")
    if kind == "note" and features.get("notes") in (None, "off"):
        raise _Refused("This book has notes turned off: turn notes on in the book's features before suggesting a note.")
    if kind == "edit":
        text = _text_field(item, "text", "An edit's text (the replacement)")
        text = _one_line(text)
        if text == quote:
            raise _Refused("The edit's text is the same as the quote: give the words you want instead, different from the quote.")
        return {"text": text}
    if kind in ("note", "comment"):
        text = _text_field(item, "text", f"A {kind}'s text")
        text = _one_line(text)
        if not text.strip():
            raise _Refused(f"A {kind} needs its text: say what the {kind} should say.")
        return {"text": text.strip()}
    if kind == "index":
        term = _text_field(item, "term", "The index term", required=False).strip()
        if len(term) > MAX_TERM:
            raise _Refused(f"The index term is longer than {MAX_TERM} characters: shorten it.")
        return {"term": term} if term else {}
    source, ids = item.get("source"), source_ids()
    if not isinstance(source, str) or source not in ids:
        known = ", ".join(sorted(ids)) or "none yet"
        raise _Refused(f"The book has no source {source!r}: use one of its source ids ({known}).")
    locator = _text_field(item, "locator", "The locator", required=False).strip()
    return {"source": source, "locator": locator} if locator else {"source": source}


def _find(doc: dict, item: dict, kind: str, quote: str, file: str) -> tuple[str, str, str, str]:
    """(the quote as the piece spells it, where it sits: "text" | "note", before, after) for the words in the piece."""
    every = matches(doc, quote)
    found = [m for m in every if m[0] == "text" or (kind == "edit" and m[0] == "note")]
    if not found:
        hint = ""
        if any(m[0] == "note" for m in every) and kind != "edit":
            hint = " The words are inside a note, and only an edit can go there."
        elif every:
            hint = " The words are in an image caption, which suggestions can't change."
        raise _Refused(f"Couldn't find \"{quote}\" in {file}. Quote the words exactly as they read, without Markdown "
                       f"(no `*`, `^[…]` or `[@…]`), spelling, punctuation and capitals as in the piece.{hint} Copy "
                       "no-break spaces and curly quotes („…”, ‘…’, ’) as they are in the piece, too.")
    pick = found[0]
    if len(found) > 1:
        before, after = (item.get(k) if isinstance(item.get(k), str) else "" for k in ("before", "after"))
        if not before.strip() and not after.strip():
            raise _Refused(f"The quote occurs {len(found)} times in {file}: add `before` or `after`, a few words "
                           "that sit just before or after the one you mean.")
        best = max(((_near(m[4], m[2], m[3], before, after), -i, m) for i, m in enumerate(found)), key=lambda t: t[:2])
        if best[0] == 0:
            raise _Refused(f"The quote occurs {len(found)} times in {file} and the words you gave in `before` or "
                           "`after` sit next to none of them: give a few words that read just before or after the "
                           "one you mean, spelled as in the piece.")
        pick = best[2]
    where, _box, start, end, text = pick
    return (text[start:end], where) + context(text, start, end)


def _near(text: str, start: int, end: int, before: str, after: str) -> int:
    """`score` for the context Claude gives: the space where it meets the quote doesn't count, so "Then" before
    "he said" fits "Then he said". The stored context (and `locate`) stays exact."""
    left, right = text[:start].rstrip(), text[end:].lstrip()
    return score(left + right, len(left), len(left), before.rstrip(), after.lstrip())


def _key(s: dict) -> tuple:
    """What makes two suggestions the same one: the same words in the same place asking for the same thing."""
    vals = (s.get(k) or None for k in ("file", "kind", "quote", "in", "before", "after", "text", "term", "source",
                                       "locator"))
    return tuple(v if v is None or isinstance(v, str) else repr(v) for v in vals)    # a hand-edited value may be a list


def _day(stamp) -> str:
    try:
        d = datetime.fromisoformat(str(stamp)[:10])
        return f"{d.day} {d:%b %Y}"
    except ValueError:
        return "an earlier day"


def _prepare(books, d: Path, item, meta: dict, source_ids, docs: dict) -> dict:
    """One item checked and found in its piece: the suggestion without id, group, by, made and status."""
    if not isinstance(item, dict):
        raise _Refused("Each suggestion is an object with a piece, a kind and a quote.")
    name = item.get("piece")
    if not isinstance(name, str) or not name.strip():
        raise _Refused("Say which piece: its file name or its title.")
    try:
        file = books.find_piece(d.name, name)
    except BooksError as e:
        raise _Refused(str(e)) from None
    kind, quote = item.get("kind"), item.get("quote")
    if kind not in KINDS:
        raise _Refused("The kind is one of " + ", ".join(KINDS) + ".")
    if not isinstance(quote, str) or not 1 <= len(quote) <= MAX_QUOTE:
        raise _Refused(f"The quote is the exact words in the piece, 1 to {MAX_QUOTE} characters.")
    why = " ".join(_text_field(item, "why", "The why", required=False).split())
    if len(why) > MAX_WHY:
        raise _Refused(f"The why is longer than {MAX_WHY} characters: shorten it to a sentence.")
    fields = _check_kind(item, kind, quote, meta, source_ids)
    if file not in docs:
        try:
            docs[file] = books.piece(d.name, file)["doc"]
        except (BooksError, ValueError, KeyError, OSError) as e:
            docs[file] = str(e)
    if isinstance(docs[file], str):
        raise _Refused(f"{file} can't be read: {docs[file]}")
    exact, where, before, after = _find(docs[file], item, kind, quote, file)
    s = {"file": file, "kind": kind, "quote": exact, "before": before, "after": after, "in": where, **fields}
    if why:
        s["why"] = why
    return s


def add(books, book, items, label=None, by="Claude", now=None) -> dict:
    """Store suggestions (they change nothing in the book until the writer accepts them). Each item is checked on
    its own: {"added": [...], "refused": [{"item": n, "reason": ...}], "group": id | None}."""
    if not isinstance(items, list) or not items:
        raise BooksError("Send a list of suggestions, each with a piece, a kind and a quote.")
    if len(items) > MAX_ITEMS:
        raise BooksError(f"Send at most {MAX_ITEMS} suggestions in one call; this has {len(items)}.")
    d = books._dir(book)
    meta = books._meta(d)
    cached = []

    def source_ids() -> set:        # sources.json is read only when a citation asks for it
        if not cached:
            try:
                cached.append({x["id"] for x in books.sources(d.name) if isinstance(x, dict) and isinstance(x.get("id"), str)})
            except BooksError as e:
                raise _Refused(str(e)) from None
        return cached[0]
    now = now or datetime.now()
    group = f"g-{now:%Y-%m-%dT%H%M}-{secrets.token_hex(2)}" if len(items) >= 2 else None
    label = " ".join(str(label).split()) if label else ""
    docs = {}                       # each piece is parsed once, before the lock is taken
    prepared = []                   # (item number, suggestion or the reason it was refused)
    for n, item in enumerate(items, 1):
        try:
            prepared.append((n, _prepare(books, d, item, meta, source_ids, docs)))
        except _Refused as e:
            prepared.append((n, str(e)))
    added, refused = [], []
    with _books._LOCK, _books.file_lock(_books.lock_path(d)):
        data = _read(d)             # read inside the lock: another process may have written since
        existing = entries(data)
        known = {}
        for s in existing:
            if s["status"] == "open":
                known[_key(s)] = s
            elif s["status"] == "rejected":
                known.setdefault(_key(s), s)
        ids = {s["id"] for s in data["suggestions"] if isinstance(s, dict) and isinstance(s.get("id"), str)}
        waiting = sum(1 for s in existing if s["status"] == "open")
        for n, s in prepared:
            if isinstance(s, str):
                refused.append({"item": n, "reason": s})
                continue
            twin = known.get(_key(s))
            if twin and twin["status"] == "open":
                refused.append({"item": n, "reason": f"Left out: already waiting as {twin['id']}."})
            elif twin:
                refused.append({"item": n, "reason": f"Left out: the author rejected this on {_day(twin.get('decided'))}; "
                                                      "don't suggest it again."})
            elif waiting >= MAX_OPEN:
                refused.append({"item": n, "reason": f"Left out: the book has {MAX_OPEN} suggestions waiting; "
                                                      "ask the author to go through them first."})
            else:
                s["id"] = "s-" + secrets.token_hex(4)
                while s["id"] in ids:
                    s["id"] = "s-" + secrets.token_hex(4)
                ids.add(s["id"])
                if group:
                    s["group"] = group
                if label:               # a single suggestion keeps it too: the panel heads it with the label
                    s["label"] = label
                s.update(by=by, made=now.isoformat(timespec="seconds"), status="open")
                known[_key(s)] = s
                waiting += 1
                added.append(s)
        if added:
            data["suggestions"].extend(added)
            _save(books, d, data)
    return {"added": added, "refused": refused, "group": group}


# ——— listing them ———

def listing(books, book, file=None, status="open") -> list:
    """The well-formed suggestions (of one piece, when `file` is given) with where their words are now: `piece` (its
    title), `found`, `index` (the place among the matches Find numbers) and `missing` (the piece left the book).
    status is open, decided (accepted, rejected or withdrawn) or all."""
    if status not in ("open", "decided", "all"):
        raise BooksError("The status is open, decided or all.")
    d = books._dir(book)
    data = _read(d)
    # as Books._pieces: an entry whose name isn't a file right in manuscript/ is never read; its suggestions are missing
    contents = [e for e in books._meta(d)["contents"] if isinstance(e, dict) and _books.valid_file(e.get("file"))]
    order = {e["file"]: i for i, e in enumerate(contents)}
    kinds = {e["file"]: e.get("kind") for e in contents}
    wanted = [s for s in entries(data) if (file is None or s["file"] == file)
              and (status == "all" or (s["status"] == "open") == (status == "open"))]
    docs = {}                       # each piece is parsed once
    for f in {s["file"] for s in wanted}:
        if f not in order:
            docs[f] = None
            continue
        try:
            p = books.piece(d.name, f)
            docs[f] = (p["doc"], p["title"] or kinds.get(f) or "")
        except (BooksError, ValueError, KeyError, OSError):
            docs[f] = None
    out = []
    for s in wanted:
        got = docs[s["file"]]
        at = locate(got[0], s) if got else None
        gone = s["file"] not in order or (got is None and not (d / "manuscript" / s["file"]).exists())
        out.append({**s, "piece": "" if gone else (got[1] if got else kinds.get(s["file"]) or ""),
                    "found": at is not None, "index": at["index"] if at else None, "missing": gone,
                    "_at": _position(got[0], at) if at else None})
    opened = sorted((s for s in out if s["status"] == "open"),
                    key=lambda s: (order.get(s["file"], len(order)), not s["found"], s["_at"] or (0, 0), s.get("made") or ""))
    decided = sorted((s for s in out if s["status"] != "open"), key=lambda s: str(s.get("decided") or ""), reverse=True)
    return [{k: v for k, v in s.items() if k != "_at"} for s in opened + decided]


def _position(doc: dict, at: dict) -> tuple:
    """Where the located words sit in reading order: (which container, offset in it)."""
    boxes = []
    _books._containers(doc, boxes)
    n = next((i for i, (_, box) in enumerate(boxes) if box is at["box"]), len(boxes))
    return n, at["start"]


def summary(books, book) -> dict:
    """{"open": n, "any": bool} for the book's page; never raises (a book must always open)."""
    try:
        data = _read(books._dir(book))
        return {"open": sum(1 for s in entries(data) if s["status"] == "open"), "any": bool(data["suggestions"])}
    except Exception as e:          # noqa: BLE001 - whatever is wrong with the file, the book still opens
        return {"open": 0, "any": True, "error": str(e)}


# ——— deciding ———

DECISIONS = {"accept": "accepted", "reject": "rejected", "reopen": "reopened", "withdraw": "withdrawn"}


def decide(books, book, ids: list, decision: str, now=None) -> dict:
    """Accept, reject, bring back or withdraw suggestions: {"accepted", "rejected", "reopened", "withdrawn", "changed",
    "unknown"}, each a list of ids. Accepting is the only way a suggestion changes a piece: each piece is written once
    (with a snapshot of the text before), and a suggestion whose words moved on, or that wouldn't survive being
    written and read back, stays open and is reported as `changed`. Reject, accept and withdraw act on open
    suggestions; reopen on rejected and withdrawn ones (an accepted one is in the text now), unless the same suggestion
    is open again."""
    if decision not in DECISIONS:
        raise BooksError("The decision is " + ", ".join(DECISIONS) + ".")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise BooksError("Send a list of suggestion ids.")
    d = books._dir(book)
    now = now or datetime.now()
    stamp = now.isoformat(timespec="seconds")
    out = {name: [] for name in (*DECISIONS.values(), "changed", "unknown")}
    states = ("rejected", "withdrawn") if decision == "reopen" else ("open",)
    with _books._LOCK, _books.file_lock(_books.lock_path(d)):
        data = _read(d)
        by_id = {s["id"]: s for s in entries(data)}
        # one brought back while the same suggestion is open (Claude made it again) would be a twin: accepting both
        # would make the change twice
        waiting = {_key(s) for s in by_id.values() if s["status"] == "open"} if decision == "reopen" else set()
        chosen = []
        for i in dict.fromkeys(ids):
            if i in by_id and by_id[i]["status"] in states and _key(by_id[i]) not in waiting:
                chosen.append(by_id[i])
                if decision == "reopen":
                    waiting.add(_key(by_id[i]))
            else:
                out["unknown"].append(i)
        if decision == "accept":
            done = _accept(books, d, chosen, out, now)
        else:
            done = chosen
        for s in done:
            if decision == "reopen":
                s["status"] = "open"
                s.pop("decided", None)
            else:
                s.update(status=DECISIONS[decision], decided=stamp)
            out[DECISIONS[decision]].append(s["id"])
        if done:
            _save(books, d, data)
    return out


def _accept(books, d: Path, chosen: list, out: dict, now) -> list:
    """Apply the chosen suggestions piece by piece, in book order; the ones made, the rest noted in out["changed"]."""
    # as Books._pieces: an entry whose name isn't a file right in manuscript/ is never read or written
    contents = [e for e in books._meta(d)["contents"] if isinstance(e, dict) and _books.valid_file(e.get("file"))]
    by_file = {}
    for s in chosen:
        by_file.setdefault(s["file"], []).append(s)
    sources = []
    if any(s["kind"] == "cite" for s in chosen):
        try:
            sources = books.sources(d.name)
        except BooksError:          # without readable sources a citation can't be made; the rest still can
            pass
    done = []
    for e in contents:
        if e["file"] not in by_file:
            continue
        made = _accept_in_piece(books, d, e, by_file.pop(e["file"]), sources, now)
        done += made[0]
        out["changed"] += made[1]
    for rest in by_file.values():           # pieces that left the book
        out["changed"] += [s["id"] for s in rest]
    return done


def _accept_in_piece(books, d: Path, entry: dict, group: list, sources: list, now) -> tuple[list, list]:
    """(the suggestions made, the ids that couldn't be) for one piece; the piece is written once, or not at all."""
    everything = ([], [s["id"] for s in group])
    path, form = books._path(d, entry["file"]), books._form(entry)
    try:
        old = _books._read_piece(path)
        if old is None:
            return everything
        doc = manuscript.parse(old, form)
    except (BooksError, ValueError, TypeError, KeyError):
        return everything
    made = []
    for s in group:
        backup = copy.deepcopy(doc)
        try:
            if apply(doc, s, sources):
                made.append(s)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):     # a hand-edited suggestion
            doc.clear()
            doc.update(backup)
    if not made:
        return everything
    try:
        text = manuscript.serialize(doc, form)
        if manuscript.serialize(manuscript.parse(text, form), form) != text:        # it must read back the same
            return everything
    except (ValueError, TypeError, KeyError):
        return everything
    if text != old:
        try:
            books._snapshot(d, entry["file"], old, now, True)       # accepting can be undone from the history
            write_text(path, text)
        except (OSError, ValueError):       # ValueError: a newest snapshot that isn't UTF-8 can't be compared
            return everything
    failed = [s["id"] for s in group if s not in made]
    return made, failed
