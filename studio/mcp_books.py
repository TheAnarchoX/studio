"""Claude's tools for books (registered on the Studio MCP server, see mcp_server.py).

Read: list_books, read_book, read_piece, search_book, list_sources. Write: add_source, and suggest / list_suggestions /
withdraw_suggestions, which only keep proposals in suggestions.json. The author writes; no tool changes manuscript text.
Every tool opens the library afresh (`_books()`), because Settings can move it while the MCP process runs.
"""
import json
import shutil
from typing import Any

from . import compose, config, manuscript, suggestions
from . import preflight as checks         # the preflight tool has this module's name
from . import suggestions as suggestions_mod      # the suggest tool has a parameter named suggestions
from .books import Books
from .research import Research
from .mcp_server import _preview, _run, server

SOURCES_MAX, TERMS_MAX, VERSIONS_MAX, HITS_MAX = 500, 500, 20, 200
RESEARCH_MAX = 300


def _books() -> Books:
    config.refresh()
    return Books(config.BOOKS)


def _research() -> Research:
    config.refresh()
    return Research(config.ART)


def _board(research: Research, book: str | None):
    """The board id for a book named by id or title; None (the shared board) when no book is named."""
    return research.books.book_id(book) if book else None


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)


def _waiting(books: Books, book: str, file: str | None = None):
    """The open suggestions: how many for a piece, or {file: n} for the book."""
    items = suggestions.listing(books, book, file, "open")
    if file is not None:
        return len(items)
    out: dict = {}
    for s in items:
        out[s["file"]] = out.get(s["file"], 0) + 1
    return out


def _label(item) -> str:
    """A source in a few words: the first author's family name (with its particle) or literal name, and the year."""
    if not isinstance(item, dict):
        return ""
    authors = item.get("author")
    p = authors[0] if isinstance(authors, list) and authors and isinstance(authors[0], dict) else {}
    name = " ".join(str(x) for x in (p.get("non-dropping-particle"), p.get("family")) if x) or str(p.get("literal") or "")
    issued = item.get("issued")
    parts = issued.get("date-parts") if isinstance(issued, dict) else None
    year = parts[0][0] if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0] else ""
    return " ".join(x for x in (name or str(item.get("title") or ""), str(year)) if x)


def _capped(items: list, limit: int, field: str, out: dict):
    out[field] = items[:limit]
    if len(items) > limit:
        out[field + "_more"] = len(items) - limit


@server.tool(structured_output=False)
async def list_books() -> str:
    """The books on the shelf: id, title, author, kind, language, words, pieces, how many pieces per status and how
    many suggestions are waiting for the author."""
    def go():
        books = _books()
        out = []
        for b in books.list():
            if "error" in b:
                out.append({"id": b["id"], "title": b["title"], "error": b["error"]})
                continue
            keep = {k: b[k] for k in ("id", "title", "author", "kind", "language", "words", "pieces", "by_status")}
            out.append({**keep, "suggestions_waiting": suggestions.summary(books, b["id"])["open"]})
        return out
    return _json(await _run(go))


@server.tool(structured_output=False)
async def read_book(book: str) -> str:
    """One book: its details, features and style sheet, the contents (each piece with its file, kind, form,
    status, title, words and notes), the sources (id and a short label; read them with list_sources), the index
    terms in use, the frozen editions and the suggestions waiting per piece. Name the book by id or title."""
    def go():
        books = _books()
        b = books.read(books.book_id(book))
        keep = ("file", "auto", "kind", "form", "status", "title", "words", "notes")
        out = {k: b.get(k) for k in ("id", "title", "subtitle", "author", "language", "kind", "features", "details",
                                     "style_sheet")}
        out["contents"] = [{k: e[k] for k in keep if k in e} for e in b["contents"]]
        sources = [{"id": s.get("id"), "label": _label(s)} for s in books.sources(b["id"]) if isinstance(s, dict)]
        _capped(sources, SOURCES_MAX, "sources", out)
        if (b.get("features") or {}).get("index"):
            _capped(books.index_terms(b["id"]), TERMS_MAX, "index_terms", out)
        out["editions"] = [{"name": e["name"], "date": e["date"]} for e in books.editions(b["id"])]
        out["suggestions_waiting"] = _waiting(books, b["id"])
        return out
    return _json(await _run(go))


@server.tool(structured_output=False)
async def read_piece(book: str, piece: str, version: str | None = None) -> str:
    """One piece as Markdown, exactly as on disk, after a JSON header (file, title, kind, form, status, words,
    notes, the saved versions newest first, suggestions waiting) and a line with ---. Name the piece by file name
    or title. version is one of the header's versions (its "when"): you get the text as it was then."""
    def go():
        books = _books()
        b = books.book_id(book)
        file = books.find_piece(b, piece)
        p = books.piece(b, file)
        history = books.history(b, file)
        md = books.snapshot_text(b, file, version) if version else p["md"]
        c = manuscript.counts(md, p["form"]) if version else p      # a version's counts are its own
        head = {"file": file, "title": p["title"], "kind": p["kind"], "form": p["form"], "status": p["status"],
                "words": c["words"], "note_words": c["note_words"], "notes": c["notes"],
                "versions": history[:VERSIONS_MAX], "suggestions_waiting": _waiting(books, b, file)}
        if version:
            head["version"] = version
        if len(history) > VERSIONS_MAX:
            head["versions_more"] = len(history) - VERSIONS_MAX
        return _json(head) + "\n---\n" + md
    return await _run(go)


@server.tool(structured_output=False)
async def search_book(book: str, query: str, whole_words: bool = False, match_case: bool = False) -> str:
    """Find words in the text of every piece, as the author's Find does: each hit has the piece (file, title),
    where it is (in: text, note or caption), the words before and after, and the match. At most 200 hits."""
    def go():
        books = _books()
        hits = books.search(books.book_id(book), query, whole_words, match_case)
        out = [{k: h[k] for k in ("file", "title", "in", "before", "match", "after")} for h in hits[:HITS_MAX]]
        if len(hits) > HITS_MAX:
            out.append({"more": len(hits) - HITS_MAX})
        return out
    return _json(await _run(go))


@server.tool(structured_output=False)
async def list_sources(book: str) -> str:
    """The book's sources (sources.json, CSL-JSON): the keys a citation [@key] can use."""
    def go():
        books = _books()
        return books.sources(books.book_id(book))
    return _json(await _run(go))


@server.tool(structured_output=False)
async def add_source(book: str, source: dict[str, Any]) -> str:
    """Add one source to the book's sources.json (CSL-JSON, e.g. {"title": "Tides", "author": [{"family": "Dijk",
    "non-dropping-particle": "van", "given": "Sam"}], "issued": {"date-parts": [[2019]]}, "publisher": "..."}). It needs a
    title; type defaults to book and the key (id) is made for you unless you give one. A source that repeats an
    existing one (same key, DOI, URL, or title and year) is refused, naming it. Use the key in a cite suggestion."""
    def go():
        books = _books()
        added = books.add_source(books.book_id(book), source)
        return f"Added {added['id']}: {_label(added)}"
    return await _run(go)


SUGGEST_DOC = f"""Propose changes to a book for the author to accept or reject. Nothing changes until the author accepts:
the proposals wait in the writing window's Suggestions panel. Send up to {suggestions.MAX_ITEMS} items at once,
optionally under one label.
""" + """
Each item: {"piece", "kind", "quote", "before"?, "after"?, "text"?, "term"?, "source"?, "locator"?, "why"?}
- piece: the piece's file name or title. kind: edit, note, index, cite or comment.
- quote: the words exactly as they read, without Markdown (no *, [], ^[ ]); they must occur in the piece. If they
  occur more than once, give before and/or after to choose which: a few words that read just before or after them
  (the space between those words and the quote may be left out).
- why: one line telling the author the reason.
Kinds:
- edit: text replaces the quoted words; empty text deletes them; their formatting is kept.
- note: text becomes a note right after the quoted words.
- index: term (default: the quoted words; "main > sub" for a subentry) marks the words for the index.
- cite: source is a key from list_sources, locator like "p. 12"; the citation is inserted right after the words.
- comment: text is a remark on the words for the author.
Each item is checked on its own; the ones that can't be made are reported with the reason."""


@server.tool(structured_output=False, description=SUGGEST_DOC)
async def suggest(book: str, suggestions: list[dict[str, Any]], label: str | None = None) -> str:
    def go():
        books = _books()
        r = suggestions_mod.add(books, books.book_id(book), suggestions, label=label)
        n = len(r["added"])
        head = f"Added {n} suggestion{'' if n == 1 else 's'}"
        stored = r["added"][0].get("label") if r["added"] else None      # as kept: spaces squeezed
        head += f' ({"group" if r["group"] else "label"} "{stored}").' if stored else "."
        lines = [head] if n else ["Nothing was added."]
        lines += [f"Not added: item {x['item']} — {x['reason']}" for x in r["refused"]]
        lines.append("The author sees them in the writing window's Suggestions panel.")
        return "\n".join(lines)
    return await _run(go)


@server.tool(structured_output=False)
async def list_suggestions(book: str, piece: str | None = None, status: str = "open") -> str:
    """The suggestions in a book (of one piece when piece is given): id, file, piece, kind, quote, text, term, source,
    locator, why, label, status, found (whether the words are still in the piece), missing (the piece left the book),
    made and decided. status is open (the default), decided (accepted, rejected or withdrawn) or all. Look at the
    decided ones to see what the author turned down."""
    def go():
        books = _books()
        b = books.book_id(book)
        keep = ("id", "file", "piece", "kind", "quote", "text", "term", "source", "locator", "why", "label", "status",
                "found", "missing", "made", "decided")
        file = books.find_piece(b, piece) if piece else None
        return [{k: s[k] for k in keep if k in s} for s in suggestions_mod.listing(books, b, file, status)]
    return _json(await _run(go))


@server.tool(structured_output=False)
async def withdraw_suggestions(book: str, ids: list[str]) -> str:
    """Take back open suggestions of yours by id (the author sees them gone from the panel; they stay in the decided list)."""
    def go():
        books = _books()
        r = suggestions_mod.decide(books, books.book_id(book), ids, "withdraw")
        out = [f"Withdrew {len(r['withdrawn'])}."]
        if r["unknown"]:
            out.append("Not open: " + ", ".join(r["unknown"]))
        return "\n".join(out)
    return await _run(go)


RESEARCH_DROP = ("pos", "thumb", "html")


@server.tool(structured_output=False)
async def list_research(book: str | None = None, query: str | None = None, tag: str | None = None,
                        kind: str | None = None) -> str:
    """The items on a research board: the book's board when book is given (id or title), else the shared board. Each
    has id, type (note, quote, source, piece, link, clip, image), title, excerpt, tags and where it came from. query
    searches the board's text instead (hits with a snippet, in items); tag and kind (a type) narrow the listing. At most 300."""
    def go():
        r = _research()
        board = _board(r, book)
        if query:
            items = r.search(query, board)
        else:
            data = r.read(board)
            items = [{k: v for k, v in s.items() if k not in RESEARCH_DROP} for s in data["items"]
                     if (not tag or tag in s["tags"]) and (not kind or s["type"] == kind)]

        out = {"board": data["title"] if not query else r._title(board)}
        if not query:
            out["tags"], out["kinds"] = data["tags"], data["kinds"]
        _capped(items, RESEARCH_MAX, "items", out)
        return out
    return _json(await _run(go))


@server.tool(structured_output=False)
async def read_research(id: str, book: str | None = None) -> str:
    """One research item in full: its fields and its Markdown text. On the book's board when book is given (id or
    title), else on the shared board. Get ids from list_research."""
    def go():
        r = _research()
        item = r.item(_board(r, book), id)
        return {k: v for k, v in item.items() if k not in RESEARCH_DROP}
    return _json(await _run(go))


@server.tool(structured_output=False)
async def add_research(item: dict[str, Any], book: str | None = None) -> str:
    """Add one item to a research board: the book's (id or title) or, without book, the shared board. It never
    touches the manuscript. item is {"type": "note" | "quote" | "source" | "link", "title"?, "tags"?, "text"?}:
    note: text is the body. quote: text is the quoted words, source is a source key, locator like "p. 12". source:
    csl is a CSL-JSON item (its id is the key). link: board and item name the original. A piece is {"type": "piece",
    "book", "file"}. For a web page give {"type": "clip", "url"}: Studio fetches it, keeps a readable copy and a
    picture, and adds it as a source."""
    def go():
        r = _research()
        board = _board(r, book)
        if not isinstance(item, dict):
            raise ValueError("Say what to add.")
        if item.get("type") == "clip":
            if not item.get("url"):
                raise ValueError("A clip needs a url.")
            added = r.clip(board, item["url"])
        else:
            added = r.add(board, item)
        said = f"Added {added['type']} {added['id']} to {r._title(board)}"
        return f"{said} ({added['warning']})" if added.get("warning") else said
    return await _run(go)


@server.tool(structured_output=False)
async def get_book_design(book: str) -> str:
    """A book's design as JSON: design (every setting, resolved), stored (what the author or Claude set in book.json;
    the rest comes from the template), and the choices: templates, trims (mm), printers and the fonts Studio has."""
    def go():
        books = _books()
        return compose.get_design(books, books.book_id(book))
    return _json(await _run(go))


@server.tool(structured_output=False)
async def set_book_design(book: str, changes: dict[str, Any] | None = None, template: str | None = None,
                          reset: list[str] | str | None = None) -> str:
    """Change a book's design, the only part of book.json Claude changes (the manuscript is never touched). The author
    sees the change in the Compose window and can change it back. changes is a partial nested design as get_book_design
    shows it, e.g. {"trim": "a5", "margins": {...}}; template picks a template by id; reset is a list of design sections
    (or "all") put back to the template's values before the rest is applied. Returns the resolved design and the choices;
    a value that isn't allowed is refused with the reason. Look at the result with render_pages."""
    def go():
        books = _books()
        return compose.set_design(books, books.book_id(book), changes, template,
                                  [reset] if isinstance(reset, str) and reset != "all" else (reset or ()))
    return _json(await _run(go))


def _ascii_digits(t: str) -> bool:
    t = t.strip()
    return t.isascii() and t.isdecimal()


def _page_numbers(text: str, count: int) -> list[int]:
    """'1-4, 9' as [1, 2, 3, 4, 9]; a plain sentence for anything else or a page the book doesn't have."""
    bad = ValueError('Name pages like "1-4, 9" (numbered from 1).')
    out: list[int] = []
    for part in text.split(","):
        a, dash, b = part.strip().partition("-")
        if not _ascii_digits(a) or (dash and not _ascii_digits(b)):
            raise bad
        lo, hi = int(a), int(b) if dash else int(a)
        if lo > hi:
            raise ValueError(f"A range runs upwards: {part.strip()} should be {hi}-{lo}.")
        if lo < 1 or hi > count:
            raise ValueError(f"This book has {count} page{'' if count == 1 else 's'}; pages are numbered from 1.")
        out += [n for n in range(lo, hi + 1) if n not in out]
    return out


PAGES_MAX, PICTURES_MAX = 400, 4


@server.tool(structured_output=False)
async def render_pages(book: str, pages: str | None = None, ppi: int = 96) -> list:
    """Draw pages of the book as the PDF will have them. pages is like "1-4, 9" (numbered from 1; default the first 4),
    ppi the resolution (1-300, default 96). The PNGs are written to files (listed in the reply, the previous run's files
    are replaced) and up to 4 of the pages come back as pictures. Look at them after changing the design."""
    def go():
        if isinstance(ppi, bool) or not isinstance(ppi, int) or not 1 <= ppi <= 300:
            raise ValueError("The resolution is 1 to 300 pixels per inch.")
        books = _books()
        b = books.book_id(book)
        compiled =compose.compile_book(books, b)
        count = len(compiled.pages)
        if compiled.error and not count:
            raise ValueError(f"The book does not set yet: {compiled.error}")
        if not count:
            raise ValueError("This book has no pages yet.")
        wanted = list(range(1, min(count, PICTURES_MAX) + 1)) if pages is None else _page_numbers(pages, count)
        if len(wanted) > PAGES_MAX:
            raise ValueError(f"Ask for at most {PAGES_MAX} pages at a time.")
        images = compose.render_pages(books, b, wanted, "png", ppi)
        folder = config.CACHE / "mcp-pages" / b
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for n, data in zip(wanted, images):
            p = folder / f"page-{n:03d}.png"
            p.write_bytes(data)
            paths.append(p)
        head = f"Drew {len(paths)} of {count} pages at {ppi} ppi:"
        shown = [f"  {n}: {p}" for n, p in zip(wanted, paths)]
        if len(paths) > PICTURES_MAX:
            shown.append(f"Pictures of the first {PICTURES_MAX} follow; open the other files to see them.")
        if compiled.error:
            shown.insert(0, f"The book doesn't set now ({compiled.error}); these are the last good pages.")
        return ["\n".join([head, *shown])] + [_preview(p, 1100) for p in paths[:PICTURES_MAX]]
    return await _run(go)


@server.tool(structured_output=False)
async def export_pdf(book: str) -> str:
    """Make the book's print PDF (fonts embedded) and keep a dated copy in the book's exports folder; the reply says
    where it is, how many pages and how big. Checks nothing: run preflight for that."""
    def go():
        books = _books()
        r = compose.export_pdf(books, books.book_id(book))
        size = r["size"]
        human = f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{size / 1024:.1f} KB"
        head = f"Exported {r['name']}: {r['pages']} page{'' if r['pages'] == 1 else 's'}, {human}"
        if r["path"]:
            return f"{head} to {r['path']}"
        return f"{head}. The copy couldn't be kept in the book's exports folder (it can't be written to)."
    return await _run(go)


@server.tool(structured_output=False)
async def preflight(book: str) -> str:
    """Run the print checks on the book: a summary line, then one line per finding (fail, warn or info, with the page
    and piece where there is one). The checks save their report for the Compose view's print checks; they change
    nothing in the book's text or design."""
    def go():
        books = _books()
        r = checks.run(books, books.book_id(book))
        lines = [str(r["summary"])]
        for i in r["items"]:
            where = " ".join(x for x in ((f"page {i['page']}" if i.get("page") else ""), i.get("file") or "") if x)
            lines.append(f"{i['level']} {where}: {i['message']}" if where else f"{i['level']}: {i['message']}")
        return "\n".join(lines)
    return await _run(go)
