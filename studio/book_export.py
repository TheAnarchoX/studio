"""Exporting a book: .docx, Markdown (one file) and a zip of the book's own files.

Every export reads the book through `Books` (pieces in `contents` order) and the manuscript dialect through
`manuscript.parse`; nothing here parses Markdown. The .docx uses plain styles (Title, Heading 1-3, Normal, Quote):
book design is part 2.

Mapping of the document nodes to .docx:
  title -> Heading 1 (none for a dedication)       heading -> Heading 2 / 3
  paragraph -> Normal, em/strong -> italic/bold runs, smallcaps -> small caps, lang -> the run's language
  scene_break -> centred `* * *`                   page_break -> a page break
  epigraph -> italic paragraphs, attribution right-aligned
  poem -> one paragraph per stanza with line breaks, left aligned   blockquote -> Quote style, indented
  image -> a centred picture (width as a share of the text width)   cite -> `cite_text`
  note -> a superscript number, the text listed after the piece under *Notes* / *Noten*
  comment, idx -> only their text
"""
import io
import os
import re
import threading
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu

from . import book_import, manuscript
from .books import BOOK_FILE, FORMS, IMAGE_TYPES, BooksError
from .store import folder_name
from .styles import RESERVED

FORMATS = {"docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
           "md": ("md", "text/markdown; charset=utf-8"),
           "zip": ("zip", "application/zip")}
MISSING_POEM = "This poem is no longer in your Poems library."


def clean(text) -> str:
    """Text for a .docx: Word's vertical tab is a line break, the other characters XML can't hold are dropped."""
    return _XML_BAD.sub("", str(text or "").replace(chr(11), chr(10)))


_XML_BAD = re.compile("[" + chr(0) + "-" + chr(8) + chr(12) + chr(14) + "-" + chr(31) + chr(0xfffe) + chr(0xffff) + "]")


# ---------------------------------------------------------------------------------------------------------
# Citations

def _family(source):
    """The first author's (or editor's) family name as cited, with its particles: CSL keeps "van" and "de" apart
    (`non-dropping-particle`, `dropping-particle`), a citation reads "van Dijk", "de Wit"."""
    for key in ("author", "editor"):
        people = source.get(key)
        if isinstance(people, list) and people and isinstance(people[0], dict):
            p = people[0]
            name = " ".join(str(p[k]).strip() for k in ("dropping-particle", "non-dropping-particle", "family")
                            if p.get(k) and str(p[k]).strip()) if p.get("family") else p.get("literal")
            if name:
                return str(name)
    return str(source.get("title") or source.get("id") or "")


def _year(source):
    try:
        year = source["issued"]["date-parts"][0][0]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(year) if year not in (None, "") else ""


def cite_text(items, sources) -> str:
    """`(Family year, p. 12)`; several items joined with `; `; an item's prefix comes first; an unknown key stands
    for itself."""
    by_id = {s.get("id"): s for s in sources or [] if isinstance(s, dict)}
    parts = []
    for item in items or []:
        key = str(item.get("key") or "")
        src = by_id.get(key)
        label = " ".join(x for x in (_family(src), _year(src)) if x) if src else key
        text = f"{item['prefix']} {label}" if item.get("prefix") else label
        if item.get("locator"):
            text += f", {item['locator']}"
        parts.append(text)
    return "(" + "; ".join(parts) + ")"


# ---------------------------------------------------------------------------------------------------------
# Reading the book

def _pieces(books, book):
    """[(entry, piece)] in contents order; entries without a file (the auto pages) and missing files are skipped. A
    piece that isn't readable text stops the export, by name: a book without one of its pieces is no export."""
    out = []
    for e in books.read(book)["contents"]:
        if e.get("unreadable"):
            raise BooksError(f"{e['file']} isn't readable text (Studio reads pieces as UTF-8), so the book wasn't "
                             f"exported. Save that file as UTF-8 and export again.")
        if e.get("file") and not e.get("missing"):
            out.append((e, books.piece(book, e["file"])))
    return out


def _plain(nodes):
    """The text of inline nodes, as it is read in a note, a title or an attribution."""
    return "".join(n.get("text", "") if n.get("type") == "text" else "\n" if n.get("type") == "hard_break" else ""
                   for n in nodes or [])


# ---------------------------------------------------------------------------------------------------------
# .docx

class _Writer:
    def __init__(self, books, book):
        self.books, self.book = books, book
        self.meta = books.read(book)
        self.dir = books.dir(book)
        self.sources = books.sources(book)
        self.dutch = str(self.meta.get("language") or "").lower().split("-")[0] == "nl"
        self.doc = Document()
        self.number = 0           # the note counter
        sec = self.doc.sections[0]
        self.text_width = sec.page_width - sec.left_margin - sec.right_margin
        self.first_on_page = False

    # ——— runs and paragraphs ———
    def _paragraph(self, style=None, align=None):
        p = self.doc.add_paragraph(style=style)
        if align is not None:
            p.alignment = align
        if self.first_on_page:
            p.paragraph_format.page_break_before = True
            self.first_on_page = False
        return p

    @staticmethod
    def _run(p, text, em=False, strong=False, smallcaps=False, lang=None, sup=False):
        r = p.add_run(clean(text))
        if em:
            r.italic = True
        if strong:
            r.bold = True
        if smallcaps:
            r.font.small_caps = True
        if sup:
            r.font.superscript = True
        if lang:
            el = OxmlElement("w:lang")
            el.set(qn("w:val"), lang)
            r._r.get_or_add_rPr().append(el)
        return r

    def inline(self, p, nodes, notes=None, italic=False):
        for n in nodes or []:
            t = n.get("type")
            if t == "text":
                marks = {m["type"]: m for m in n.get("marks") or []}
                self._run(p, n["text"], em=italic or "em" in marks, strong="strong" in marks,
                          smallcaps="smallcaps" in marks, lang=(marks.get("lang", {}).get("attrs") or {}).get("lang"))
            elif t == "hard_break":
                p.add_run().add_break()
            elif t == "cite":
                self._run(p, cite_text((n.get("attrs") or {}).get("items"), self.sources), em=italic)
            elif t == "note" and notes is not None:
                self.number += 1
                notes.append((self.number, n.get("content") or []))
                self._run(p, str(self.number), sup=True)

    # ——— blocks ———
    def block(self, n, notes, kind, italic=False, quote=False):
        t = n.get("type")
        content = n.get("content") or []
        if t == "title":
            if kind != "dedication":
                self.heading(None, 1, content, notes)
        elif t == "heading":
            self.heading(None, int((n.get("attrs") or {}).get("level") or 2), content, notes)
        elif t == "paragraph":
            p = self._paragraph(style="Quote" if quote else None,
                                align=WD_ALIGN_PARAGRAPH.CENTER if kind == "dedication" else None)
            if quote:
                p.paragraph_format.left_indent = Cm(1)
            self.inline(p, content, notes, italic=italic or kind == "dedication")
        elif t == "scene_break":
            self._run(self._paragraph(align=WD_ALIGN_PARAGRAPH.CENTER), "* * *")
        elif t == "page_break":
            self._paragraph().add_run().add_break(WD_BREAK.PAGE)
        elif t == "blockquote":
            for c in content:
                self.block(c, notes, kind, italic, True)
        elif t == "epigraph":
            for c in content:
                if c.get("type") == "attribution":
                    p = self._paragraph(align=WD_ALIGN_PARAGRAPH.RIGHT)
                    self.inline(p, c.get("content"), notes)
                else:
                    self.block(c, notes, kind, True)
        elif t == "poem":
            self.poem(n, notes)
        elif t == "image":
            self.image(n.get("attrs") or {})

    def heading(self, text, level, content=None, notes=None):
        p = self._paragraph(style=f"Heading {min(max(level, 1), 3)}")
        if content is not None:
            self.inline(p, content, notes)
        else:
            p.add_run(clean(text))
        return p

    def poem(self, n, notes):
        stanzas = []
        src = (n.get("attrs") or {}).get("src")
        if src:
            poem = self.books.linked_poem(src)
            if poem.get("missing"):
                self._paragraph().add_run(MISSING_POEM)
                return
            stanza = []
            for line in list(poem.get("lines") or []) + [""]:
                if str(line).strip():
                    stanza.append(str(line))
                elif stanza:
                    stanzas.append(stanza)
                    stanza = []
            for lines in stanzas:
                p = self._paragraph(align=WD_ALIGN_PARAGRAPH.LEFT)
                for i, line in enumerate(lines):
                    if i:
                        p.add_run().add_break()
                    p.add_run(clean(line))
            return
        for c in n.get("content") or []:
            p = self._paragraph(align=WD_ALIGN_PARAGRAPH.LEFT)
            self.inline(p, c.get("content"), notes)

    def image(self, attrs):
        name = Path(str(attrs.get("src") or "").replace("\\", "/")).name
        path = self.dir / "images" / name
        if not name or path.suffix.lower() not in IMAGE_TYPES or not path.is_file():
            return
        p = self._paragraph(align=WD_ALIGN_PARAGRAPH.CENTER)
        try:
            pic = p.add_run().add_picture(str(path))
        except Exception:        # an unreadable image leaves a gap, not a broken file
            self.doc.element.body.remove(p._p)
            return
        pic._inline.docPr.set("descr", clean(attrs.get("alt")))
        width = str(attrs.get("width") or "")
        ratio = pic.height / pic.width
        if width.endswith("%") and width[:-1].replace(".", "", 1).isdigit():
            target = int(self.text_width * min(float(width[:-1]), 100) / 100)
        else:
            target = min(pic.width, self.text_width)
        if target > 0:
            pic.width, pic.height = Emu(target), Emu(int(target * ratio))

    # ——— the book ———
    def title_page(self):
        meta = self.meta
        self.doc.add_paragraph(clean(meta.get("title")), style="Title")
        if meta.get("subtitle"):
            self.doc.add_paragraph(clean(meta["subtitle"]), style="Subtitle")
        if meta.get("author"):
            self.doc.add_paragraph(clean(meta["author"])).alignment = WD_ALIGN_PARAGRAPH.LEFT
        cp = self.doc.core_properties
        cp.title, cp.author = clean(meta.get("title")), clean(meta.get("author"))
        cp.language = clean(meta.get("language"))
        self.first_on_page = True

    def piece(self, entry, piece, restart):
        if restart:
            self.number = 0
        notes = []
        kind = entry.get("kind")
        self.first_on_page = True
        for n in piece["doc"].get("content") or []:
            self.block(n, notes, kind)
        if notes:
            self.heading("Noten" if self.dutch else "Notes", 2)
            for number, content in notes:
                p = self._paragraph()
                p.add_run(f"{number}. ")
                self.inline(p, content)

    def build(self) -> bytes:
        self.title_page()
        restart = ((self.meta.get("features") or {}).get("noteNumbering") or "chapter") != "book"
        for entry, piece in _pieces(self.books, self.book):
            self.piece(entry, piece, restart)
        out = io.BytesIO()
        self.doc.save(out)
        return out.getvalue()


def to_docx(books, book) -> bytes:
    return _Writer(books, book).build()


# ---------------------------------------------------------------------------------------------------------
# Markdown and zip

def to_markdown(books, book) -> bytes:
    """All pieces in order, each led by its kind and form as a comment (`<!-- kind: chapter; form: poem -->`, which
    import reads back as the start of a piece); the pieces' own Markdown, LF only."""
    parts = []
    for entry, piece in _pieces(books, book):
        md = piece["md"].replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        form = entry.get("form") if entry.get("form") in FORMS else "prose"
        parts.append(f"{book_import.marker(entry.get('kind') or 'chapter', form)}\n\n{md}\n")
    return "\n".join(parts).encode("utf-8")


def to_zip(books, book) -> bytes:
    """book.json, manuscript/, images/ and sources.json, as they are on disk."""
    d = books.dir(book)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in (BOOK_FILE, "sources.json"):
            if (d / name).is_file():
                z.write(d / name, name)
        for folder in ("manuscript", "images"):
            for p in sorted((d / folder).glob("*")) if (d / folder).is_dir() else []:
                if p.is_file() and not p.name.startswith("."):
                    z.write(p, f"{folder}/{p.name}")
    return out.getvalue()


# ---------------------------------------------------------------------------------------------------------
# One entry point for the route

def export(books, book, fmt, now=None):
    """-> (file name, bytes, content type). A copy is also kept in the book's exports/ folder, dated to the minute
    (`<Title> 2026-11-12 1405.docx`, then `-2`, `-3` in the same minute): never over an earlier one, which the author
    may have edited since."""
    if fmt not in FORMATS:
        raise BooksError("Choose .docx, Markdown or zip.")
    ext, ctype = FORMATS[fmt]
    maker = {"docx": to_docx, "md": to_markdown, "zip": to_zip}[fmt]
    data = maker(books, book)
    stem = folder_name(str(books.read(book)["title"] or "")) or "book"
    if stem.split(".")[0].upper() in RESERVED:
        stem += "-1"
    when = now if isinstance(now, datetime) else datetime.now()
    try:
        _keep(books.dir(book) / "exports", f"{stem} {when:%Y-%m-%d %H%M}", ext, data)
    except OSError:
        pass        # the folder can't be written (read-only, a full disk): the download still goes out
    return f"{stem}.{ext}", data, ctype


def _keep(folder: Path, stem, ext, data) -> Path:
    """Writes `data` as `<stem>.<ext>` in `folder`, or `<stem>-2.<ext>`, `-3` …: whole (a temp file first) and never
    over a file that is there (a rename on Windows, a hard link elsewhere: both refuse an existing name)."""
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{stem}.{os.getpid()}.{threading.get_ident()}.tmp"
    tmp.write_bytes(data)
    try:
        for n in range(1, 1000):
            dest = folder / (f"{stem}.{ext}" if n == 1 else f"{stem}-{n}.{ext}")
            try:
                (os.rename if os.name == "nt" else os.link)(tmp, dest)
                return dest
            except FileExistsError:
                continue
        raise OSError(f"no free name for {stem}.{ext}")
    finally:
        tmp.unlink(missing_ok=True)


def disposition(name) -> str:
    """Content-Disposition for a download: an ASCII fallback plus the real name (RFC 6266 / 5987)."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    ascii_name = "".join(c for c in ascii_name if c not in '"\\;%' and c >= " ").strip() or "book"
    ext = name.rpartition(".")[2]
    if not ascii_name.removesuffix("." + ext).strip():
        ascii_name = f"book.{ext}"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"
