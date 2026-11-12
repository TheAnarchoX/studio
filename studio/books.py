"""Books on disk: Books/<title>/ with a book.json, one Markdown file per piece, images, dated snapshots, editions.

The text of every piece goes through `manuscript` (Markdown <-> the editor's document); this module owns the
files: the order of the book, saving with a stale-write check, snapshots, the trash, editions, sources, search and
replace. Files are the database: every read goes to disk and `book.json` keys Studio doesn't know are kept.

Snapshots (drafts/<file stem>/<YYYY-MM-DDTHHMM>.md) hold the text as saved at that moment. A save makes one when
the text differs from the newest snapshot and either the writer is `leaving` the piece, or at least 30 minutes have
passed since the newest snapshot; a piece with no snapshot yet counts as long ago, so its first save that changes
the text makes the first one. Identical text and empty text never make one.
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import shutil
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, manuscript, styles
from .store import StoreError, folder_name, read_text, write_text

PIECE_KINDS = ("dedication", "epigraph", "content-note", "foreword", "preface", "introduction", "prologue", "part",
               "chapter", "interlude", "epilogue", "afterword", "acknowledgements", "appendix", "about-author")
AUTO = ("half-title", "title-page", "copyright", "toc", "notes", "bibliography", "index")
FRONT = ["half-title", "title-page", "copyright"]
BACK_AUTOS = ("notes", "bibliography", "index")
BACK_MATTER = ("afterword", "acknowledgements", "appendix", "about-author") + BACK_AUTOS      # book.js's BOOK_BACK
FORMS = ("prose", "poem", "essay", "letter")
STATUSES = ("idea", "draft", "revised", "final")
NOTES = ("off", "footnotes", "endnotes", "both")
NUMBERING = ("chapter", "book")


def _features(notes, numbering, sources, index, figures):
    return {"notes": notes, "noteNumbering": numbering, "sources": sources, "index": index, "figures": figures,
            "contentNote": False}


def _chapter(title="Chapter 1", form="prose"):
    return {"kind": "chapter", "title": title, "form": form}


# Per kind: the feature defaults, the pieces a new book starts with (after the three title-page autos), and the
# auto pages that close it. A kind only sets defaults.
KINDS = {
    "fiction": {"features": _features("off", "chapter", False, False, False),
                "contents": [_chapter()], "back": []},
    "memoir": {"features": _features("endnotes", "chapter", False, False, False),
               "contents": [{"kind": "dedication"}, {"auto": "toc"}, _chapter()], "back": ["notes"]},
    "nonfiction": {"features": _features("endnotes", "chapter", True, True, False),
                   "contents": [{"auto": "toc"}, {"kind": "introduction", "title": "Introduction"}, _chapter()],
                   "back": ["notes", "bibliography", "index"]},
    "academic": {"features": _features("footnotes", "book", True, True, True),
                 "contents": [{"auto": "toc"}, {"kind": "introduction", "title": "Introduction"}, _chapter(),
                              {"kind": "appendix", "title": "Appendix"}],
                 "back": ["notes", "bibliography", "index"]},
    "poetry": {"features": _features("off", "chapter", False, "first-lines", False),
               "contents": [{"auto": "toc"}, _chapter("Untitled", "poem")], "back": ["index"]},
    "essays": {"features": _features("endnotes", "chapter", False, False, False),
               "contents": [{"auto": "toc"}, _chapter("Essay 1", "essay")], "back": ["notes"]},
}

BOOK_FILE = "book.json"
MARGIN = 40                     # characters of context around a search match
SNAPSHOT_STAMP = "%Y-%m-%dT%H%M"
EDITION = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2}) (?P<name>.+)")      # editions/<date> <name>
SNAPSHOT_EVERY = timedelta(minutes=30)
SNAPSHOT = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{4})(?:-(\d+))?")      # a second one in a minute gets -2, -3
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp")      # not .svg: served from the library it could carry a script
QUIET = ("editions", "drafts", "exports")      # they don't change what is open
EDITION_ITEMS = ("book.json", "manuscript", "images", "sources.json", "cover")
LANGUAGE = config.LANGUAGE_TAG          # a language code: at most 35 characters, 6 subtags
GAP = "￼"                  # stands for an inline node that isn't text (a note, a citation) while searching
ON_OFF = {"sources": "Sources are", "figures": "Figures are", "contentNote": "The content note is"}
SHEET = {"quotes": "“…”", "numbers": "words to ten", "terms": [], "notes": ""}     # book.json "style": the style sheet
TERM_SHAPE = "Each term is a word to use, the forms not to use and a note."
STYLE_DIRS = ("looks", "palettes", "fonts")     # Styles/ folders a book's look is drawn from
_LOCK = threading.RLock()
# A piece's counts and title by (path, mtime, size, form): a shelf or book read parses only pieces that changed.
_COUNTS = {}
_COUNTS_MAX = 4096


class BooksError(StoreError):
    """code 400 for a bad request, 404 for an unknown book or piece, 409 for a stale save (extra: {"current": piece})."""

    def __init__(self, message, code=400, extra=None):
        super().__init__(message)
        self.code = code
        self.details = extra or {}


@contextlib.contextmanager
def _bad_request():
    """StoreErrors from the styles module become 400s."""
    try:
        yield
    except BooksError:
        raise
    except StoreError as e:
        raise BooksError(str(e)) from None


def _when(now):
    if now is None:
        return datetime.now()
    return datetime.fromtimestamp(now) if isinstance(now, (int, float)) else now


_LETTERS = {ord(a): b for a, b in zip("øæßłœđþØÆŁŒĐÞ", ["o", "ae", "ss", "l", "oe", "d", "th", "O", "AE", "L", "OE", "D", "Th"])}


def _slug(title, kind):
    """A file stem: the title without diacritics, lower case, dashes; the piece kind when nothing is left."""
    title = str(title or "").translate(_LETTERS)
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", re.sub(r"['’]", "", folded)).strip("-")[:60].strip("-")
    return s or kind


def _squash(s):
    return " ".join(str(s or "").split())


def _dump(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _is_link(path: Path, parent: Path) -> bool:
    """A symlink, or on Windows a junction: anything that doesn't resolve to a folder of the same name in `parent`."""
    if path.is_symlink() or getattr(os.path, "isjunction", lambda p: False)(path):
        return True
    return path.resolve() != parent.resolve() / path.name


def valid_file(name) -> bool:
    """A piece's file name as book.json may hold it: a .md file right in manuscript/, never a folder, a drive or a
    stream (`/`, `\\`, `:`), never hidden. Entries with any other name are left alone: never read, never written."""
    return (isinstance(name, str) and name.endswith(".md") and not name.startswith(".")
            and not any(c in "/\\:" or ord(c) < 32 for c in name))


UNREADABLE = "This piece isn't readable text: Studio reads pieces as UTF-8. Its file is unchanged; save it as UTF-8 " \
             "in another editor to open it here."


def _read_piece(p: Path):
    """A piece's text (None when the file is gone); a file that isn't UTF-8 is a 400, and is never written over."""
    try:
        return read_text(p)
    except UnicodeDecodeError:
        raise BooksError(UNREADABLE, 400) from None


def _piece_counts(p: Path, form):
    """{"words", "note_words", "notes", "title", "mtime"} of a piece file, or None when it is gone; a file that isn't
    UTF-8 counts nothing and says so ("unreadable"). Parsed once per version of the file (its path, mtime, size and
    form); the cache is emptied when it grows past _COUNTS_MAX."""
    try:
        st = p.stat()
    except OSError:
        return None
    key = (str(p), st.st_mtime_ns, st.st_size, form)
    hit = _COUNTS.get(key)
    if hit is None:
        try:
            md = read_text(p)
        except UnicodeDecodeError:
            md = ""
            hit = {"words": 0, "note_words": 0, "notes": 0, "title": "", "mtime": st.st_mtime, "unreadable": True}
        if md is None:
            return None
        hit = hit or {**manuscript.counts(md, form), "title": manuscript.title_of(md) or "", "mtime": st.st_mtime}
        if len(_COUNTS) >= _COUNTS_MAX:
            _COUNTS.clear()
        _COUNTS[key] = hit
    return dict(hit)


def _read_term(t):
    """A term as book.json may hold it (hand edits included) -> {use, not, note}, or None when it has no word to use."""
    if isinstance(t, str):
        t = {"use": t}
    if not isinstance(t, dict) or not isinstance(t.get("use"), str) or not _squash(t["use"]):
        return None
    nots = t.get("not")
    nots = nots.split(",") if isinstance(nots, str) else nots if isinstance(nots, list) else []
    note = t.get("note")
    return {"use": _squash(t["use"]), "not": [_squash(n) for n in nots if isinstance(n, str) and _squash(n)],
            "note": note.strip() if isinstance(note, str) else ""}


def style_sheet(style) -> dict:
    """book.json's "style" as the app reads it: quotes, numbers, terms and notes, defaults where missing, every term
    {use, not, note}."""
    s = style if isinstance(style, dict) else {}
    terms = s.get("terms") if isinstance(s.get("terms"), list) else []
    return {"quotes": s["quotes"] if isinstance(s.get("quotes"), str) else SHEET["quotes"],
            "numbers": s["numbers"] if isinstance(s.get("numbers"), str) else SHEET["numbers"],
            "terms": [x for x in map(_read_term, terms) if x],
            "notes": s["notes"] if isinstance(s.get("notes"), str) else SHEET["notes"]}


def _terms(given):
    """The terms to write: a list of {use, not: [...], note} or plain words; anything else is refused."""
    if not isinstance(given, list):
        raise BooksError(TERM_SHAPE)
    out = []
    for t in given:
        t = {"use": t} if isinstance(t, str) else t
        if not isinstance(t, dict):
            raise BooksError(TERM_SHAPE)
        use, nots, note = t.get("use", ""), t.get("not", []), t.get("note", "")
        if not (isinstance(use, str) and isinstance(note, str) and isinstance(nots, list) and all(isinstance(n, str) for n in nots)):
            raise BooksError(TERM_SHAPE)
        if not _squash(use):
            raise BooksError("Each term needs the word to use.")
        out.append({"use": _squash(use), "not": [_squash(n) for n in nots if _squash(n)], "note": note.strip()})
    return out


def _write_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    for attempt in range(20):       # Windows refuses to replace a file someone has open: wait a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


def _text_of(nodes):
    out = []
    for n in nodes:
        out.append(n.get("text", "") if n.get("type") == "text" else "\n" if n.get("type") == "hard_break" else GAP)
    return "".join(out)


def _containers(node, out):
    """The places text lives in a document, in reading order: [("text" | "note", [inline nodes]), ("caption", image)]."""
    t = node.get("type")
    if t in ("title", "heading", "paragraph", "attribution"):
        content = node.get("content") or []
        out.append(("text", content))
        for n in content:
            if n.get("type") == "note":
                out.append(("note", n.get("content") or []))
    elif t in ("blockquote", "epigraph", "poem", "doc"):
        for c in node.get("content") or []:
            _containers(c, out)
    elif t == "image" and (node.get("attrs") or {}).get("alt"):
        out.append(("caption", node))


def _pattern(q, whole, case):
    p = re.escape(q)
    return re.compile((r"(?<!\w)" + p + r"(?!\w)") if whole else p, 0 if case else re.IGNORECASE)


def _matches(doc, pattern):
    """[(kind, container, start, end, text)] for every match in the document, in reading order."""
    boxes, found = [], []
    _containers(doc, boxes)
    for kind, box in boxes:
        text = box["attrs"]["alt"] if kind == "caption" else _text_of(box)
        for m in pattern.finditer(text):
            if GAP not in m.group() and "\n" not in m.group():
                found.append((kind, box, m.start(), m.end(), text))
    return found


def _rewrite(box, kind, spans, repl):
    """Apply replacements [(start, end)] (sorted, in one container) keeping the marks of the text they sit in."""
    if kind == "caption":
        text, out, cursor = box["attrs"]["alt"], "", 0
        for a, b in spans:
            out, cursor = out + text[cursor:a] + repl, b
        box["attrs"]["alt"] = out + text[cursor:]
        return
    offset, new = 0, []
    for n in box:
        size = len(n["text"]) if n.get("type") == "text" else 1
        if n.get("type") == "text":
            s, e, text, cursor, out = offset, offset + size, n["text"], offset, ""
            for a, b in spans:
                if b <= s or a >= e:
                    continue
                out += text[cursor - s:max(a, s) - s]
                if a >= s:
                    out += repl
                cursor = min(b, e)
            out += text[cursor - s:]
            if out:
                new.append({**n, "text": out})
        else:
            new.append(n)
        offset += size
    box[:] = new


class Books:
    def __init__(self, root=None):
        self.root = Path(root or config.BOOKS).resolve()
        self.styles = styles.Styles(self.root.parent)       # the library: Poems/, Books/ and Styles/ side by side

    # ——— finding things ———
    def dirs(self):
        if not self.root.exists():
            return []
        return [d for d in sorted(self.root.iterdir()) if d.is_dir() and not d.name.startswith((".", "_"))
                and (d / BOOK_FILE).exists()]

    def file(self, rel) -> Path:
        """A book image to serve: rel is the path after /bookfiles/, `<book>/images/<name>`. Only the book image types,
        never a dot-folder (.trash, .studio) and never outside the Books folder; anything else is a 404."""
        parts = str(rel).replace("\\", "/").split("/")
        if len(parts) < 2 or any(p in ("", ".", "..") or p.startswith(".") or ":" in p for p in parts):
            raise BooksError("not found", 404)
        if parts[0].startswith("_") or not (self.root / parts[0] / BOOK_FILE).is_file():       # a real book only
            raise BooksError("not found", 404)
        p = self.root.joinpath(*parts).resolve()
        if self.root not in p.parents or p.suffix.lower() not in IMAGE_TYPES or not p.is_file():
            raise BooksError("not found", 404)
        return p

    def dir(self, book) -> Path:
        """A book's folder, by its id (the folder name)."""
        return self._dir(book)

    def linked_poem(self, src) -> dict:
        """A poem of the Poems library as {"title", "lines"}, or {"missing": True}."""
        return self._poem(src)

    @staticmethod
    def write_bytes(path: Path, data: bytes):
        """Atomic write (with a short retry on Windows)."""
        _write_bytes(path, data)

    def _dir(self, book):
        name = str(book or "").strip()
        if not name:
            raise BooksError("Say which book.", 404)
        if "/" not in name and "\\" not in name and not name.startswith("."):
            for d in self.dirs():
                if d.name == name or d.name.lower() == name.lower():
                    return d
        raise BooksError(f"There's no book called {name} in Books.", 404)

    def _meta(self, d: Path) -> dict:
        try:
            meta = json.loads((d / BOOK_FILE).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise BooksError(f"{d.name}/{BOOK_FILE} can't be read: {e}", 400) from None
        if not isinstance(meta, dict):
            raise BooksError(f"{d.name}/{BOOK_FILE} can't be read: not an object", 400)
        if not isinstance(meta.get("contents"), list):
            meta["contents"] = []
        return meta

    def _save_meta(self, d: Path, meta):
        write_text(d / BOOK_FILE, _dump(meta))

    def _entry(self, meta, file):
        for e in meta["contents"] if valid_file(file) else []:
            if isinstance(e, dict) and e.get("file") == file:
                return e
        raise BooksError(f"There's no piece {file} in this book.", 404)

    def _path(self, d, file):
        return d / "manuscript" / file

    def _style(self, meta):
        return self.styles.resolve([("global", {"look": config.DEFAULT_LOOK}), ("book", meta)])

    def style(self, book) -> dict:
        """A book's resolved style (look, palette, fonts), as `read()` gives it."""
        return self._style(self._meta(self._dir(book)))

    def shelf_styles(self) -> list[dict]:
        """{"id", "title", "style"} for every book whose book.json can be read: what the Styles pages count."""
        out = []
        for d in self.dirs():
            try:
                meta = self._meta(d)
            except BooksError:
                continue
            out.append({"id": d.name, "title": str(meta.get("title") or d.name), "style": self._style(meta)})
        return out

    def stamp(self) -> float:
        """A change marker: the newest modification time across the books (their files and manuscripts) and the looks,
        palettes and fonts in Styles/ they are drawn from."""
        newest = self._mtime(self.root)         # a book added or deleted
        for sub in STYLE_DIRS:                  # a book's look can change without any of its own files
            folder = self.styles.dir / sub
            if folder.is_dir():
                newest = max([newest, self._mtime(folder)] + [self._mtime(f) for f in folder.glob("*.json")])
        for d in self.dirs():
            for base, folders, files in os.walk(d):
                folders[:] = [f for f in folders if not f.startswith(".") and not (base == str(d) and f in QUIET)]
                inside = [] if base == str(d) else [base]       # a book folder's own time moves with editions/ and exports/
                for path in inside + [os.path.join(base, f) for f in files if not f.startswith(".")]:
                    try:
                        newest = max(newest, os.stat(path).st_mtime)
                    except OSError:
                        pass                    # gone while we looked
        return newest

    # ——— the shelf ———
    def list(self) -> list[dict]:
        out = []
        for d in self.dirs():
            try:
                meta = self._meta(d)
            except BooksError as e:
                out.append({"id": d.name, "title": d.name, "error": str(e)})
                continue
            words, pieces, by_status, updated = 0, 0, {}, self._mtime(d / BOOK_FILE)
            for e in meta["contents"]:
                if not isinstance(e, dict) or not valid_file(e.get("file")):
                    continue
                pieces += 1
                if e.get("status") in STATUSES:
                    by_status[e["status"]] = by_status.get(e["status"], 0) + 1
                c = _piece_counts(self._path(d, str(e["file"])), self._form(e))
                if c:
                    updated = max(updated, c["mtime"])
                    words += c["words"]
            out.append({"id": d.name, "title": meta.get("title") or d.name, "author": meta.get("author", ""),
                        "kind": meta.get("kind", ""), "language": meta.get("language", ""), "words": words,
                        "pieces": pieces, "updated": updated, "by_status": by_status, "style": self._style(meta)})
        return out

    @staticmethod
    def _mtime(path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    @staticmethod
    def _form(entry):
        return entry.get("form") if entry.get("form") in FORMS else "prose"

    def create(self, title, author="", language="en", kind="memoir", look=None, start=True) -> dict:
        title = _squash(title)
        folder = folder_name(title)
        if not folder:
            raise BooksError("Give the book a title.")
        if folder.split(".")[0].upper() in styles.RESERVED:
            raise BooksError(f"{folder} can't be used as a book title; choose another.")
        if folder.startswith(("_", ".")):
            raise BooksError("A book title can't start with an underscore or a dot.")
        if kind not in KINDS:
            raise BooksError("The kind is " + ", ".join(KINDS) + ".")
        language = _squash(language) or "en"
        if not LANGUAGE.fullmatch(language):
            raise BooksError("The language is a code like en or nl.")
        with _bad_request():
            look = self.styles.look(look)["name"] if look else None
        with _LOCK:
            d = self.root / folder
            if d.exists():
                raise BooksError(f"{folder} already exists in Books.")
            d.mkdir(parents=True)
            try:
                (d / "manuscript").mkdir()
                (d / "images").mkdir()
                spec = KINDS[kind]
                meta = {"version": 1, "title": title, "subtitle": "", "author": _squash(author),
                        "language": language, "kind": kind, "features": copy.deepcopy(spec["features"]),
                        "details": {"isbn": "", "publisher": "", "edition": "", "year": date.today().year,
                                    "copyright": "", "contentNote": ""},
                        "contents": [], "goals": {"daily": 0},
                        "style": {"quotes": "“…”", "numbers": "words to ten", "terms": [], "notes": ""},
                        "checks": {}, "design": {}}
                if look:
                    meta["look"] = look
                meta["contents"] = [{"auto": a} for a in FRONT]
                for item in spec["contents"] if start else []:
                    if "auto" in item:
                        meta["contents"].append({"auto": item["auto"]})
                        continue
                    form = item.get("form", "prose")
                    name = self._new_name(d, meta, item.get("title", ""), item["kind"])
                    write_text(self._path(d, name), f"# {item['title']}\n" if item.get("title") else "")
                    entry = {"file": name, "kind": item["kind"]}
                    if item["kind"] not in ("dedication",):
                        entry.update({"form": form, "status": "idea"})
                    meta["contents"].append(entry)
                meta["contents"] += [{"auto": a} for a in spec["back"]]
                self._save_meta(d, meta)
            except BaseException:
                shutil.rmtree(d, ignore_errors=True)     # this call made the folder a moment ago
                raise
        return self.read(d.name)

    def read(self, book) -> dict:
        d = self._dir(book)
        meta = self._meta(d)
        contents, total = [], 0
        for e in meta["contents"]:
            e = dict(e) if isinstance(e, dict) else {}
            if "file" in e and not valid_file(e["file"]):
                continue                    # a name Studio won't read (another folder, a drive): left out, left alone
            if e.get("file"):
                c = _piece_counts(self._path(d, str(e["file"])), self._form(e))
                if c:
                    e.update({k: c[k] for k in ("title", "words", "note_words", "notes", "mtime")})
                    if c.get("unreadable"):
                        e["unreadable"] = True
                    total += c["words"]
                else:
                    e.update({"title": "", "words": 0, "note_words": 0, "notes": 0, "mtime": 0.0, "missing": True})
            contents.append(e)
        # `style` in the reply is the resolved look, as for series and poems; book.json's own "style" (the style sheet)
        # comes as `style_sheet`
        meta.update({"id": d.name, "path": str(d), "contents": contents, "words": total, "days": self._days(d, True),
                     "style_sheet": style_sheet(meta.get("style")), "style": self._style(meta)})
        return meta

    # ——— the book's details ———
    def update(self, book, fields) -> dict:
        fields = fields if isinstance(fields, dict) else {}
        with _LOCK:
            d = self._dir(book)
            meta = self._meta(d)
            for k in ("title", "subtitle", "author"):
                if k in fields:
                    meta[k] = _squash(fields[k])
                    if k == "title" and not meta[k]:
                        raise BooksError("Give the book a title.")
            if "language" in fields:
                lang = _squash(fields["language"])
                if not LANGUAGE.fullmatch(lang):
                    raise BooksError("The language is a code like en or nl.")
                meta["language"] = lang
            if "kind" in fields:
                if fields["kind"] not in KINDS:
                    raise BooksError("The kind is " + ", ".join(KINDS) + ".")
                meta["kind"] = fields["kind"]
            if fields.get("apply_kind_defaults"):
                if meta.get("kind") not in KINDS:
                    raise BooksError("This book's kind has no defaults.")
                meta["features"] = copy.deepcopy(KINDS[meta["kind"]]["features"])
            if "features" in fields:
                meta["features"] = self._features(meta.get("features"), fields["features"])
            if "details" in fields:
                if not isinstance(fields["details"], dict):
                    raise BooksError("The details are an object.")
                details = dict(meta["details"]) if isinstance(meta.get("details"), dict) else {}
                for k, v in fields["details"].items():
                    if k == "year":
                        try:
                            v = int(v) if str(v).strip() else ""
                        except (TypeError, ValueError):
                            raise BooksError("The year is a number.") from None
                    elif isinstance(v, str):
                        v = v.strip()
                    details[k] = v
                meta["details"] = details
            if "goals" in fields:
                meta["goals"] = self._goals(meta.get("goals"), fields["goals"])
            for key in ("style_sheet", "style"):        # "style" is the plan's name for the style sheet
                if key in fields:
                    meta["style"] = self._house_style(meta.get("style"), fields[key])
            if "contents" in fields:
                meta["contents"] = self._contents(d, fields["contents"], meta["contents"])
            changes = {}
            with _bad_request():        # the styles module speaks StoreError
                if fields.get("detach"):
                    meta = self.styles.detach(meta, self._style(meta))
                if fields.get("link"):
                    meta = self.styles.link(meta, fields["link"])
                if "look" in fields:
                    changes["look"] = self.styles.look(fields["look"])["name"] if fields["look"] else None
                if "palette" in fields:
                    changes["palette"] = self._palette(fields["palette"])
                if "fonts" in fields:
                    changes["fonts"] = styles.clean_fonts(fields["fonts"], every=False) if fields["fonts"] else None
            for k, v in changes.items():
                if v is None:
                    meta.pop(k, None)
                else:
                    meta[k] = v
            self._save_meta(d, meta)
        return self.read(d.name)

    def _palette(self, palette):
        if palette in (None, "", []):
            return None
        if isinstance(palette, str):
            return self.styles.palette(palette)["name"]
        if isinstance(palette, dict):
            name = _squash(palette["name"])[:60] if isinstance(palette.get("name"), str) else ""
            return {**({"name": name} if name else {}), "swatches": styles.clean_swatches(palette.get("swatches"))}
        return styles.clean_swatches(palette)

    @staticmethod
    def _features(current, given):
        if not isinstance(given, dict):
            raise BooksError("The features are an object.")
        out = dict(current) if isinstance(current, dict) else {}
        for k, v in given.items():
            if k == "notes" and v not in NOTES:
                raise BooksError("Notes are " + ", ".join(NOTES) + ".")
            if k == "noteNumbering" and v not in NUMBERING:
                raise BooksError("Note numbering is chapter or book.")
            if k in ON_OFF and not isinstance(v, bool):
                raise BooksError(f"{ON_OFF[k]} on or off.")
            if k == "index" and not (isinstance(v, bool) or v == "first-lines"):
                raise BooksError("The index is on, off or first-lines.")
            out[k] = v
        return out

    @staticmethod
    def _goals(current, given):
        if not isinstance(given, dict):
            raise BooksError("The goals are an object.")
        out = dict(current) if isinstance(current, dict) else {}
        for k, v in given.items():
            if k == "daily":
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v != v:
                    raise BooksError("The daily goal is a number of words, 0 or more.")
                v = int(v)
            out[k] = v
        return out

    @staticmethod
    def _house_style(current, given):
        """book.json's style sheet after `given`; keys Studio doesn't know stay."""
        if not isinstance(given, dict):
            raise BooksError("The style sheet is an object.")
        out = dict(current) if isinstance(current, dict) else {}
        for k, v in given.items():
            if k in ("quotes", "numbers", "notes") and not isinstance(v, str):
                raise BooksError(f"The style sheet's {k} is text.")
            out[k] = _terms(v) if k == "terms" else v
        return out

    def _contents(self, d, given, current=()):
        """The order of the book. Entries are auto pages or pieces whose file exists; keys Studio doesn't know stay.
        A list read before another window added a piece doesn't hold it: the pieces of `current` (book.json as it is)
        missing from `given` stay, at the end of the body. Only delete_piece takes a piece out of the book."""
        if not isinstance(given, list):
            raise BooksError("The contents are a list.")
        out, seen = [], set()
        for e in given:
            if not isinstance(e, dict):
                raise BooksError("Each entry of the book is an object.")
            if e.get("auto") is not None:
                if e["auto"] not in AUTO:
                    raise BooksError("The auto pages are " + ", ".join(AUTO) + ".")
            else:
                f = e.get("file")
                if not valid_file(f):
                    raise BooksError("A piece needs the name of its file.")
                if f.lower() in seen:
                    raise BooksError(f"{f} is in the book twice.")
                seen.add(f.lower())
                if e.get("kind") not in PIECE_KINDS:
                    raise BooksError("A piece's kind is " + ", ".join(PIECE_KINDS) + ".")
                if e.get("form") not in (None, *FORMS):
                    raise BooksError("A piece's form is " + ", ".join(FORMS) + ".")
                if e.get("status") not in (None, *STATUSES):
                    raise BooksError("A piece's status is " + ", ".join(STATUSES) + ".")
                if not self._path(d, f).exists():
                    raise BooksError(f"{f} isn't in the manuscript folder.", 404)
            out.append({k: v for k, v in e.items() if k not in ("title", "words", "note_words", "notes", "mtime", "missing",
                                                                 "unreadable")})
        kept = [e for e in current if isinstance(e, dict) and isinstance(e.get("file"), str) and e["file"]
                and e["file"].lower() not in seen]
        if kept:
            at = len(out)
            while at > 0 and (out[at - 1].get("auto") or out[at - 1].get("kind")) in BACK_MATTER:
                at -= 1
            out[at:at] = kept
        return out

    # ——— pieces ———
    def _new_name(self, d, meta, title, kind):
        stem = _slug(title, kind)
        taken = {str(e.get("file", "")).lower() for e in meta["contents"] if isinstance(e, dict)}
        taken |= {p.name.lower() for p in (d / "manuscript").glob("*")} if (d / "manuscript").exists() else set()
        # a trashed piece's History stays in drafts/<stem>/: a new piece never takes that name (and that History)
        taken |= {p.name.lower() + ".md" for p in (d / "drafts").iterdir() if p.is_dir()} if (d / "drafts").is_dir() else set()
        reserved = stem.split(".")[0].upper() in styles.RESERVED
        n = 1 if reserved else 0
        while True:
            cand = stem if n == 0 else f"{stem}-{n}"
            if f"{cand}.md".lower() not in taken:
                return f"{cand}.md"
            n = max(n, 1) + 1

    def new_piece(self, book, kind, form="prose", title="", after: str | None = None) -> dict:
        if kind not in PIECE_KINDS:
            raise BooksError("A piece's kind is " + ", ".join(PIECE_KINDS) + ".")
        if form not in FORMS:
            raise BooksError("A piece's form is " + ", ".join(FORMS) + ".")
        title = _squash(title)
        with _LOCK:
            d = self._dir(book)
            meta = self._meta(d)
            at = len(meta["contents"])
            if after is not None:
                at = next((i + 1 for i, e in enumerate(meta["contents"]) if isinstance(e, dict) and e.get("file") == after), None)
                if at is None:
                    raise BooksError(f"There's no piece {after} in this book.", 404)
            else:
                while at > 0 and isinstance(meta["contents"][at - 1], dict) and meta["contents"][at - 1].get("auto") in BACK_AUTOS:
                    at -= 1
            name = self._new_name(d, meta, title, kind)
            write_text(self._path(d, name), f"# {title}\n" if title else "")
            meta["contents"].insert(at, {"file": name, "kind": kind, "form": form, "status": "idea"})
            self._save_meta(d, meta)
        return self.piece(d.name, name)

    def piece(self, book, file) -> dict:
        d = self._dir(book)
        meta = self._meta(d)
        e = self._entry(meta, file)
        p = self._path(d, file)
        if not p.exists():
            raise BooksError(f"{file} is missing from the manuscript folder.", 404)
        md, form = _read_piece(p), self._form(e)
        doc = manuscript.parse(md, form)
        return {"file": file, "doc": doc, "md": md, "title": manuscript.title_of(md) or "", "kind": e.get("kind"),
                "form": form, "status": e.get("status"), "mtime": self._mtime(p),
                **manuscript.counts(md, form), "linked": self._linked(doc)}

    def _linked(self, doc):
        out = {}

        def walk(n):
            src = (n.get("attrs") or {}).get("src") if n.get("type") == "poem" else None
            if src and src not in out:
                out[src] = self._poem(src)
            for c in n.get("content") or []:
                walk(c)
        walk(doc)
        return out

    def _poem(self, src):
        parts = str(src).split("/")
        if len(parts) == 2 and all(p and p not in (".", "..") and "\\" not in p and ":" not in p for p in parts):
            try:
                poem = json.loads((self.root.parent / "Poems" / parts[0] / parts[1] / "poem.json").read_text(encoding="utf-8"))
                if isinstance(poem, dict):
                    return {"title": poem.get("title") or parts[1], "lines": poem.get("lines") or []}
            except (OSError, ValueError):
                pass
        return {"missing": True}

    def save_piece(self, book, file, doc=None, md=None, base_mtime=None, leaving=False, force=False, now=None) -> dict:
        if (doc is None) == (md is None):
            raise BooksError("Send the piece as a document or as Markdown.")
        with _LOCK:
            d = self._dir(book)
            meta = self._meta(d)
            e = self._entry(meta, file)
            form, p = self._form(e), self._path(d, file)
            try:
                base = None if base_mtime is None else float(base_mtime)
            except (TypeError, ValueError):
                raise BooksError("base_mtime is the modification time the editor was given.") from None
            # any other time is another version: a sync tool (OneDrive, Dropbox, rsync -t) can bring an older one
            if base is not None and not force and p.exists() and abs(self._mtime(p) - base) > 1e-6:
                raise BooksError(f"{file} changed since you opened it.", 409,
                                 {"current": self.piece(d.name, file)})
            try:
                if doc is not None:
                    if not isinstance(doc, dict):
                        raise ValueError("the document is not an object")
                    text = manuscript.serialize(doc, form)
                else:
                    text = manuscript.serialize(manuscript.parse(str(md), form), form)
            except (ValueError, TypeError, KeyError, AttributeError) as err:
                raise BooksError(f"This piece can't be saved: {err}", 400) from None
            old = _read_piece(p)                                            # a file that isn't UTF-8 is never written over
            shot = self._snapshot(d, file, text, _when(now), leaving)      # against the newest snapshot, not against the disk
            if text != old:
                write_text(p, text)
                old_words = manuscript.counts(old, form)["words"] if old else 0
                gained = manuscript.counts(text, form)["words"] - old_words
                if gained > 0:
                    try:
                        self._add_words(d, _when(now), gained)
                    except OSError:
                        pass        # the piece is saved; only today's count misses these words
            out = self.piece(d.name, file)
        return {**out, "snapshot": shot.stem if shot else None}      # the snapshot this save made (its `when`), if any

    def delete_piece(self, book, file) -> Path:
        with _LOCK:
            d = self._dir(book)
            meta = self._meta(d)
            self._entry(meta, file)
            p = self._path(d, file)
            meta["contents"] = [e for e in meta["contents"] if not (isinstance(e, dict) and e.get("file") == file)]
            self._save_meta(d, meta)
            if not p.exists():
                return p
            return self._trash(p, f"{d.name} {p.stem}", p.suffix)

    def delete_book(self, book) -> Path:
        with _LOCK:
            d = self._dir(book)
            return self._trash(d, d.name, "")

    def _trash(self, path: Path, name, suffix):
        trash = self.root / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        stem = f"{name} {datetime.now().strftime('%Y%m%dT%H%M%S')}"
        dest, n = trash / f"{stem}{suffix}", 2
        while dest.exists():
            dest, n = trash / f"{stem}-{n}{suffix}", n + 1
        os.replace(path, dest)
        return dest

    # ——— snapshots ———
    def _drafts(self, d, file):
        return d / "drafts" / Path(file).stem

    def _snapshots(self, d, file):
        folder = self._drafts(d, file)
        return sorted((p for p in folder.glob("*.md") if SNAPSHOT.fullmatch(p.stem)), key=self._snapshot_order) \
            if folder.exists() else []

    @staticmethod
    def _snapshot_order(p: Path):
        m = SNAPSHOT.fullmatch(p.stem)
        return m[1], int(m[2] or 1)

    def _snapshot(self, d, file, text, now, leaving):
        """The snapshot rule (see the module docstring). Returns the snapshot's path, or None when none was made."""
        if not text.strip():
            return None
        shots = self._snapshots(d, file)
        if shots:
            if read_text(shots[-1]) == text:
                return None
            newest = datetime.strptime(SNAPSHOT.fullmatch(shots[-1].stem)[1], SNAPSHOT_STAMP)
            due = now - newest >= SNAPSHOT_EVERY
        else:
            due = True
        if not (leaving or due):
            return None
        minute = now.strftime(SNAPSHOT_STAMP)       # minute resolution: a snapshot is never overwritten, the next one is -2, -3
        taken = [self._snapshot_order(p)[1] for p in shots if p.stem.startswith(minute)]
        name = minute if not taken else f"{minute}-{max(taken) + 1}"
        return write_text(self._drafts(d, file) / f"{name}.md", text)

    def history(self, book, file) -> list[dict]:
        d = self._dir(book)
        form = self._form(self._entry(self._meta(d), file))
        return [{"when": p.stem, "words": manuscript.counts(read_text(p), form)["words"]}
                for p in reversed(self._snapshots(d, file))]

    def _snapshot_path(self, d, file, when):
        if not SNAPSHOT.fullmatch(str(when)) or not (self._drafts(d, file) / f"{when}.md").exists():
            raise BooksError(f"There's no snapshot {when} of {file}.", 404)
        return self._drafts(d, file) / f"{when}.md"

    def snapshot_text(self, book, file, when) -> str:
        d = self._dir(book)
        self._entry(self._meta(d), file)
        return read_text(self._snapshot_path(d, file, when))

    def restore(self, book, file, when) -> dict:
        with _LOCK:
            d = self._dir(book)
            e = self._entry(self._meta(d), file)
            text = read_text(self._snapshot_path(d, file, when))
            p = self._path(d, file)
            current = _read_piece(p)
            if current is not None and current != text:
                self._snapshot(d, file, current, datetime.now(), True)
            write_text(p, text)
        return self.piece(d.name, file)

    # ——— words written ———
    def _days_file(self, d):
        return d / ".studio" / "days.json"

    def _days(self, d, recent=False):
        try:
            days = json.loads(self._days_file(d).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        days = {k: v for k, v in days.items() if isinstance(v, int)} if isinstance(days, dict) else {}
        if recent:
            first = (date.today() - timedelta(days=29)).isoformat()
            days = {k: v for k, v in days.items() if k >= first}
        return days

    def _add_words(self, d, when, n):
        days = self._days(d)
        key = when.date().isoformat()
        days[key] = days.get(key, 0) + n
        write_text(self._days_file(d), json.dumps(days, indent=2, sort_keys=True) + "\n")

    # ——— editions ———
    def edition(self, book, name, now=None) -> Path:
        label = folder_name(_squash(name))
        if not label:
            raise BooksError("Give the edition a name.")
        with _LOCK:
            d = self._dir(book)
            dest = d / "editions" / f"{_when(now).date().isoformat()} {label}"
            if dest.exists():
                raise BooksError(f"{dest.name} already exists.", 409)
            dest.mkdir(parents=True)
            try:
                for item in EDITION_ITEMS:
                    src = d / item
                    if src.is_dir():
                        shutil.copytree(src, dest / item)
                    elif src.exists():
                        shutil.copy2(src, dest / item)
            except BaseException:
                shutil.rmtree(dest, ignore_errors=True)       # this call made the folder a moment ago
                raise
        return dest

    def editions(self, book) -> list[dict]:
        """The frozen editions in editions/ as {"name", "date", "path"}, newest first: by date, and on one day by the
        folder's modification time. Folders named `<date> <name>`; a link (symlink or junction) is not an edition."""
        out = []
        folder = self._dir(book) / "editions"
        for e in sorted(folder.iterdir()) if folder.is_dir() else []:
            m = EDITION.fullmatch(e.name)
            if m and e.is_dir() and not _is_link(e, folder):
                out.append({"name": m["name"], "date": m["date"], "path": str(e), "_t": e.stat().st_mtime})
        out.sort(key=lambda e: (e["date"], e["_t"], e["name"].lower()), reverse=True)
        return [{k: v for k, v in e.items() if k != "_t"} for e in out]

    # ——— search and replace ———
    def search(self, book, q, whole=False, case=False) -> list[dict]:
        if not q:
            return []
        d = self._dir(book)
        pattern, out = _pattern(str(q), whole, case), []
        for e in self._pieces(d):
            md = self._text_or_none(d, e)
            if md is None:
                continue
            doc = manuscript.parse(md, self._form(e))
            first = (doc.get("content") or [{}])[0]
            title = _text_of(first.get("content") or []) if first.get("type") == "title" else ""
            title = _squash(title.replace(GAP, "")) or e.get("kind", "")
            for i, (kind, _, a, b, text) in enumerate(_matches(doc, pattern)):
                around = lambda s: s.replace(GAP, " ").replace("\n", " ")
                out.append({"file": e["file"], "title": title, "index": i, "in": kind,
                            "before": around(text[max(0, a - MARGIN):a]), "match": text[a:b],
                            "after": around(text[b:b + MARGIN])})
        return out

    def replace(self, book, q, repl, whole=False, case=False, file=None, index=None) -> dict:
        if not q:
            raise BooksError("Say what to look for.")
        if index is not None and file is None:
            raise BooksError("Replacing one match needs its piece.")
        pattern, total = _pattern(str(q), whole, case), 0
        with _LOCK:
            d = self._dir(book)
            if file is not None:
                self._entry(self._meta(d), file)
            for e in self._pieces(d):
                if file is not None and e["file"] != file:
                    continue
                form, p = self._form(e), self._path(d, e["file"])
                old = self._text_or_none(d, e)
                if old is None:
                    continue
                doc = manuscript.parse(old, form)
                found = _matches(doc, pattern)
                if index is not None:
                    found = found[index:index + 1] if 0 <= index < len(found) else []
                if not found:
                    continue
                by_box = {}
                for kind, box, a, b, _ in found:
                    by_box.setdefault(id(box), (kind, box, []))[2].append((a, b))
                for kind, box, spans in by_box.values():
                    _rewrite(box, kind, spans, str(repl))
                try:
                    text = manuscript.serialize(doc, form)
                except (ValueError, TypeError, KeyError) as err:
                    raise BooksError(f"{e['file']} can't be saved: {err}", 400) from None
                if text != old:
                    self._snapshot(d, e["file"], old, datetime.now(), True)     # a replace can be undone
                    write_text(p, text)
                total += len(found)
        return {"replaced": total}

    def _pieces(self, d):
        return [e for e in self._meta(d)["contents"]
                if isinstance(e, dict) and valid_file(e.get("file")) and self._path(d, e["file"]).exists()]

    def _text_or_none(self, d, e):
        """A piece's text for search and replace; None when it is gone or isn't UTF-8 (left out, never written)."""
        try:
            return read_text(self._path(d, e["file"]))
        except UnicodeDecodeError:
            return None

    # ——— sources and images ———
    def sources(self, book) -> list:
        d = self._dir(book)
        try:
            items = json.loads((d / "sources.json").read_text(encoding="utf-8-sig"))
        except OSError:
            return []
        except ValueError as e:
            raise BooksError(f"sources.json can't be read: {e}") from None
        return items if isinstance(items, list) else []

    def save_sources(self, book, items) -> list:
        if not isinstance(items, list):
            raise BooksError("The sources are a list.")
        seen = set()
        for i, it in enumerate(items, 1):
            if not isinstance(it, dict):
                raise BooksError(f"Source {i} is not an object.")
            key, kind = it.get("id"), it.get("type")
            if not isinstance(key, str) or not manuscript.CITE_KEY.fullmatch(key):
                raise BooksError(f"Source {i} needs an id that can be cited (letters, digits, - and _).")
            if key in seen:
                raise BooksError(f"Two sources have the id {key}.")
            if not isinstance(kind, str) or not kind.strip():
                raise BooksError(f"Source {key} needs a type (book, article-journal, webpage, ...).")
            seen.add(key)
        with _LOCK:
            write_text(self._dir(book) / "sources.json", _dump(items))
        return items

    def save_image(self, book, name, data: bytes) -> str:
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise BooksError("There is no image.")
        base = folder_name(os.path.basename(str(name).replace("\\", "/")))
        stem, ext = os.path.splitext(base)
        ext = ext.lower()
        if ext not in IMAGE_TYPES:
            raise BooksError("Images are .jpg, .jpeg, .png, .gif or .webp.")
        stem = re.sub(r"\s+", "-", stem.strip(". ")) or "image"
        with _LOCK:
            folder = self._dir(book) / "images"
            taken = {p.name.lower() for p in folder.glob("*")} if folder.exists() else set()
            cand, n = f"{stem}{ext}", 2
            while cand.lower() in taken or cand.split(".")[0].upper() in styles.RESERVED:
                cand, n = f"{stem}-{n}{ext}", n + 1
            _write_bytes(folder / cand, bytes(data))
        return f"../images/{cand}"
