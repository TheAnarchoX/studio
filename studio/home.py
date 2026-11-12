"""Home: the newest work across the library, and the one thing to pick up again.

Each source is a callable returning items {kind, title, where, when (iso), href, excerpt?, label?}; `label` is what
Home calls an item when its kind is too general (a piece is "Chapter" or "Foreword"). The library source covers
poems, designs and series; the books source books and their pieces.
"""
import json
import re
from urllib.parse import quote

from . import manuscript
from .books import BOOK_FILE, Books, valid_file
from .store import SERIES_FILE, iso

WRITING = ("poem", "piece")      # kinds that count as writing for Continue; designs count too
EXCERPT = 140                    # characters of a piece's last paragraph shown on Continue
_store = None


def use(store):
    """Point the library source at a store (the web handler does this for each request)."""
    global _store
    _store = store


def _last_line(lines):
    for line in reversed(lines or []):
        if str(line).strip():
            return str(line).strip()
    return ""


def library():
    s = _store
    if s is None or not s.root.exists():
        return []
    out = []
    for sd in s.series_dirs():
        f = sd / SERIES_FILE
        if f.exists():
            out.append({"kind": "series", "title": sd.name, "where": "Series", "when": iso(f.stat().st_mtime),
                        "href": "#/series/" + quote(sd.name)})
    for d in s.poem_dirs():
        try:
            poem = json.loads((d / "poem.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(poem, dict):
            continue
        title = poem.get("title") or d.name
        pid = s.pid(d)
        stamps = [(d / "poem.json").stat().st_mtime]
        drafts = d / "drafts"
        if drafts.exists():
            stamps += [f.stat().st_mtime for f in drafts.glob("*.md")]
        out.append({"kind": "poem", "title": title, "where": d.parent.name, "when": iso(max(stamps)),
                    "href": "#/poem/" + quote(pid, safe=""), "excerpt": _last_line(poem.get("lines"))})
        designs = d / "designs"
        for f in sorted(designs.glob("*.json")) if designs.exists() else []:
            # only the time is read here; the design's own name is read later, for the items that are shown
            out.append({"kind": "design", "title": f.stem, "where": f"{title} · {d.parent.name}",
                        "when": iso(f.stat().st_mtime), "href": "#/poem/" + quote(pid, safe="") + "/design",
                        "excerpt": _last_line(poem.get("lines")), "_file": f})
    return out


def books():
    """Each book (when its book.json changed) and each of its pieces (when its file changed). Only times are read
    here; a piece's title and last paragraph are read later, for the items that are shown."""
    s = _store
    if s is None:
        return []
    out = []
    for d in Books(s.root.parent / "Books").dirs():          # Books/ sits next to Poems/ in the library
        try:
            meta = json.loads((d / BOOK_FILE).read_text(encoding="utf-8-sig"))
            when = (d / BOOK_FILE).stat().st_mtime
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        title, book = str(meta.get("title") or d.name), quote(d.name, safe="")
        out.append({"kind": "book", "title": title, "where": "Books", "when": iso(when), "href": "#/book/" + book})
        for e in meta.get("contents") if isinstance(meta.get("contents"), list) else []:
            f = e.get("file") if isinstance(e, dict) else None
            if not valid_file(f):           # only a file right in manuscript/: never one elsewhere
                continue
            p = d / "manuscript" / f
            try:
                when = p.stat().st_mtime
            except OSError:
                continue
            name = _kind_name(e.get("kind"))       # the label Home shows for it ("Chapter"), and its title until one is read
            out.append({"kind": "piece", "label": name, "title": name, "where": title, "when": iso(when),
                        "href": f"#/book/{book}/write/{quote(f, safe='')}",
                        "_piece": (p, "poem" if e.get("form") == "poem" else "prose")})
    return out


def _kind_name(kind):
    """What a piece without a title of its own is called: its kind ("Dedication", "About the author")."""
    kind = str(kind or "piece")
    return "About the author" if kind == "about-author" else kind.replace("-", " ").capitalize()


def _tail(text, form):
    """Where the writer stopped: a poem's last line, as Home shows for poems; else the last paragraph's last EXCERPT
    characters, from a word."""
    para = text.strip().split("\n\n")[-1] if text.strip() else ""
    if form == "poem":
        return _last_line(para.split("\n"))
    para = " ".join(para.split())
    if len(para) <= EXCERPT:
        return para
    cut = para[-EXCERPT:]
    return "…" + re.sub(r"^\S*\s", "", cut, count=1)


def _name(item):
    """Give a design item its own name (read from its file), and a piece its title and last paragraph; the file name
    or the piece's kind stands in when the file can't be read."""
    f = item.pop("_file", None)
    if f is not None:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return item
        if isinstance(data, dict) and isinstance(data.get("name"), str) and data["name"]:
            item["title"] = data["name"]
    piece = item.pop("_piece", None)
    if piece is not None:
        path, form = piece
        try:
            md = path.read_text(encoding="utf-8")
            doc = manuscript.parse(md, form)
            title = manuscript.title_of(md)
        except Exception:      # noqa: BLE001  one unreadable piece must not take Home down
            return item
        content = doc.get("content") or []
        if title:
            item["title"] = title
        body = content[1:] if content[:1] and content[0].get("type") == "title" else content
        tail = _tail(manuscript.plain_text({**doc, "content": body}), form)
        if tail:
            item["excerpt"] = tail
    return item


SOURCES = [library, books]


def _items():
    items = []
    for src in SOURCES:
        try:
            items += src()
        except Exception:      # one broken area must not take Home down
            continue
    items.sort(key=lambda i: i["when"], reverse=True)
    return items


def overview(limit=10):
    """Recent work and the Continue item from a single walk of the library."""
    items = _items()
    cont = next((i for i in items if i["kind"] in WRITING or i["kind"] == "design"), None)
    shown = items[:limit] if limit is not None else items
    for i in shown:
        _name(i)
    if cont is not None:
        _name(cont)
    clean = lambda i: {k: v for k, v in i.items() if not k.startswith("_")}
    return {"recent": [clean(i) for i in shown], "continue": clean(cont) if cont else None}


def recent(limit=10):
    """The newest items across the library; limit=None means all of them."""
    return overview(limit)["recent"]


def continue_item():
    return overview(limit=0)["continue"]
