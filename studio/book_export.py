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
  list_item -> a List Paragraph numbered by a real Word list (`docx_lists`), one list per run of items
  aligned (center, right) -> its paragraphs aligned     underline, strike -> underlined, struck runs
  size mark -> the run's size, a factor of the paragraph style's (`SIZE_FACTORS`)
  table -> a Word table (Table Grid), the header row bold and repeated on each page, a column's alignment on its
           cells' paragraphs; notes in cells are numbered with the rest; an empty paragraph between two tables (Word
           would join them)
  math -> its source as `$tex$` in Cambria Math       math_display -> a centred paragraph `$$tex$$` in Cambria Math
           (Word 365 makes a real equation of either with Equation › LaTeX › Convert)
  comment -> only its text                         idx -> its text, then a hidden Word `XE` index field
The book's generated pages (`auto` entries) are written where they stand in `contents`, in a simple form: half-title,
title page, copyright, a contents field, notes at the back, the bibliography and an index field. The PDF's rule leaves
some out (typeset_book.left_out: a feature that is off, nothing to list), and so does this.
"""
import io
import os
import re
import threading
import unicodedata
import json
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt

from . import book_design, book_import, citations, manuscript, typeset, typeset_book
from .docx_lists import Numbering
from .manuscript_lists import markers
from .books import BOOK_FILE, FORMS, IMAGE_TYPES, NOTES, BooksError
from .store import folder_name
from .styles import RESERVED

FORMATS = {"docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
           "md": ("md", "text/markdown; charset=utf-8"),
           "zip": ("zip", "application/zip")}
FORMATS["pdf"] = ("pdf", "application/pdf")         # set by the composer (compose.pdf)
SIZE_FACTORS = {"x-small": 0.75, "small": 0.875, "large": 1.2, "x-large": 1.44}
MISSING_POEM = "This poem is no longer in your Poems library."
MATH_FONT = "Cambria Math"


def clean(text) -> str:
    """Text for a .docx: Word's vertical tab is a line break, the other characters XML can't hold are dropped."""
    return _XML_BAD.sub("", str(text or "").replace(chr(11), chr(10)))


_XML_BAD = re.compile("[" + chr(0) + "-" + chr(8) + chr(12) + chr(14) + "-" + chr(31) + chr(0xfffe) + chr(0xffff) + "]")


# ---------------------------------------------------------------------------------------------------------
# Citations: one formatter, `citations`, shared with the PDF composer; the alias keeps part 1 callers working.

from .citations import cite_text  # noqa: E402,F401


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
        self.collected, self.notes_at_back = [], False
        self.numbering = Numbering(self.doc)
        self.lists = {}           # a piece's list runs -> their numId

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
    def _run(p, text, em=False, strong=False, smallcaps=False, lang=None, sup=False, underline=False, strike=False,
             size=None, math=False):
        r = p.add_run(clean(text))
        if math:                # the font for every script, so Word doesn't pick another for the TeX's symbols
            fonts = r._r.get_or_add_rPr().get_or_add_rFonts()
            for key in ("ascii", "hAnsi", "cs"):
                fonts.set(qn(f"w:{key}"), MATH_FONT)
        if underline:
            r.underline = True
        if strike:
            r.font.strike = True
        if size in SIZE_FACTORS:
            # Word stores sizes in half-points: python-docx rounds 13.2 pt to the 13 pt that is saved
            base = p.style.font.size or p.part.document.styles["Normal"].font.size
            r.font.size = Pt(round((base.pt if base else 11) * SIZE_FACTORS[size], 1))
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
                          smallcaps="smallcaps" in marks, lang=(marks.get("lang", {}).get("attrs") or {}).get("lang"),
                          underline="underline" in marks, strike="strike" in marks,
                          size=(marks.get("size", {}).get("attrs") or {}).get("size"))
                if "idx" in marks:
                    self.index_entry(p, (marks["idx"].get("attrs") or {}).get("term") or n["text"])
            elif t == "hard_break":
                p.add_run().add_break()
            elif t == "cite":
                self._run(p, cite_text((n.get("attrs") or {}).get("items"), self.sources), em=italic)
            elif t == "math":
                tex = str((n.get("attrs") or {}).get("tex") or "").strip()
                if tex:
                    self._run(p, f"${tex}$", math=True)
            elif t == "note" and notes is not None:
                self.number += 1
                notes.append((self.number, n.get("content") or []))
                self._run(p, str(self.number), sup=True)

    # ——— blocks ———
    def block(self, n, notes, kind, italic=False, quote=False, align=None, marker=None):
        t = n.get("type")
        content = n.get("content") or []
        if t == "title":
            if kind != "dedication":
                self.heading(None, 1, content, notes)
        elif t == "heading":
            self.heading(None, int((n.get("attrs") or {}).get("level") or 2), content, notes)
        elif t == "paragraph":
            p = self._paragraph(style="Quote" if quote else None,
                                align=WD_ALIGN_PARAGRAPH.CENTER if kind == "dedication" else align)
            if quote:
                p.paragraph_format.left_indent = Cm(1)
            self.inline(p, content, notes, italic=italic or kind == "dedication")
        elif t == "list_item" and marker:
            self.list_item(content, notes, marker)
        elif t == "table":
            self.table(n, notes)
        elif t == "math_display":
            tex = str((n.get("attrs") or {}).get("tex") or "").strip()
            if tex:
                self._run(self._paragraph(align=WD_ALIGN_PARAGRAPH.CENTER), f"$${tex}$$", math=True)
        elif t == "aligned":
            side = WD_ALIGN_PARAGRAPH.CENTER if (n.get("attrs") or {}).get("align") == "center" else WD_ALIGN_PARAGRAPH.RIGHT
            for c in content:
                self.block(c, notes, kind, italic, quote, align=side)
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

    def list_item(self, content, notes, m):
        if m["run"] not in self.lists:
            self.lists[m["run"]] = self.numbering.num_id(m["list"], m["level"], m["n"])
        has = "List Paragraph" in [st.name for st in self.doc.styles]
        p = self._paragraph(style="List Paragraph" if has else None)
        self.numbering.apply(p, self.lists[m["run"]], m["level"])
        self.inline(p, content, notes)

    def table(self, n, notes):
        rows = [r.get("content") or [] for r in n.get("content") or []]
        align = (n.get("attrs") or {}).get("align") or []
        cols = max([len(align)] + [len(r) for r in rows])
        if not rows or not cols:
            return
        last = self.doc.element.body[-1] if len(self.doc.element.body) else None
        if last is not None and last.tag == qn("w:sectPr"):
            last = last.getprevious()
        if self.first_on_page or (last is not None and last.tag == qn("w:tbl")):
            # a table can't start a page itself: an empty paragraph carries the break; and Word joins two tables with
            # nothing between them into one
            self._paragraph()
        head = (n.get("attrs") or {}).get("header")
        sides = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                 "right": WD_ALIGN_PARAGRAPH.RIGHT}
        table = self.doc.add_table(rows=len(rows), cols=cols)
        table.style = "Table Grid"
        for i, cells in enumerate(rows):
            for j, c in enumerate(cells[:cols]):
                p = table.cell(i, j).paragraphs[0]
                if j < len(align) and align[j] in sides:
                    p.alignment = sides[align[j]]
                self.inline(p, c.get("content"), notes)
                if head and i == 0:
                    for r in p.runs:
                        r.bold = True
            if head and i == 0:
                table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))

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
        self._paragraph(style="Title").add_run(clean(meta.get("title")))
        if meta.get("subtitle"):
            self.doc.add_paragraph(clean(meta["subtitle"]), style="Subtitle")
        if meta.get("author"):
            self.doc.add_paragraph(clean(meta["author"])).alignment = WD_ALIGN_PARAGRAPH.LEFT
        publisher = (meta.get("details") or {}).get("publisher") if isinstance(meta.get("details"), dict) else None
        if isinstance(publisher, str) and publisher.strip():
            self.doc.add_paragraph(clean(publisher.strip()))
        self.first_on_page = True

    def piece(self, entry, piece, restart, listed=True):
        """One piece; `listed` False keeps its notes for the notes page at the back instead of listing them here."""
        if restart:
            self.number = 0
        notes = []
        kind = entry.get("kind")
        self.first_on_page = True
        blocks = piece["doc"].get("content") or []
        self.lists = {}
        for n, m in zip(blocks, markers(blocks)):
            self.block(n, notes, kind, marker=m)
        if notes and not listed:
            self.collected.append((entry.get("title") or "", notes))
        elif notes:
            self.heading("Noten" if self.dutch else "Notes", 2)
            self.note_list(notes)

    def note_list(self, notes):
        for number, content in notes:
            p = self._paragraph()
            p.add_run(f"{number}. ")
            self.inline(p, content)

    # ——— generated pages ———
    @property
    def design(self):
        if not hasattr(self, "_design"):
            self._design = book_design.resolve(self.meta, self.meta.get("style") or {})
        return self._design

    def label(self, key):
        return ((self.design.get("pages") or {}).get("labels") or {}).get(key) or key

    def field(self, p, instruction, result="", hidden=False):
        """A complex Word field in paragraph `p`: begin, the instruction, separate, a placeholder result, end."""
        def run(child):
            r = p.add_run()
            if hidden:
                r.font.hidden = True
            r._r.append(child)

        def char(kind):
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
            return el
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = f" {instruction} "
        run(char("begin"))
        run(instr)
        run(char("separate"))
        if result:
            t = OxmlElement("w:t")
            t.text = clean(result)
            t.set(qn("xml:space"), "preserve")
            run(t)
        run(char("end"))

    def index_entry(self, p, term):
        """A hidden `XE` field after the marked text; `a > b` becomes the entry `a` with the subentry `b`."""
        head, sub = typeset.split_term(clean(term))
        if head:
            entry = f"{head}:{sub}" if sub else head
            self.field(p, 'XE "%s"' % entry.replace('"', "'"), hidden=True)

    def auto(self, key, pieces):
        details = self.meta.get("details") if isinstance(self.meta.get("details"), dict) else {}
        features = self.meta.get("features") or {}
        if key == "half-title":
            self._paragraph(style="Title", align=WD_ALIGN_PARAGRAPH.CENTER).add_run(clean(self.meta.get("title")))
            self.first_on_page = True
        elif key == "title-page":
            self.title_page()
        elif key == "copyright":
            self.copyright_page(details)
        elif key == "toc":
            self._run(self._paragraph(), self.label("toc"), strong=True).font.size = Pt(18)
            self.field(self._paragraph(), 'TOC \\o "1-2" \\h \\z \\u')
            self.first_on_page = True
        elif key == "notes":
            if self.notes_at_back and self.collected:
                self.first_on_page = True
                self.heading(self.label("notes"), 1)
                for title, notes in self.collected:
                    if title:
                        self.heading(title, 3)
                    self.note_list(notes)
        elif key == "bibliography":
            cites = self.design.get("citations") or {}
            cited = None if cites.get("list") == "all" else citations.cited_keys([p["doc"] for _, p in pieces])
            entries = citations.bibliography(self.sources, cited, cites.get("style") or "chicago",
                                             str(self.meta.get("language") or "en"))
            if entries:
                self.first_on_page = True
                self.heading(self.label("bibliography"), 1)
                for runs in entries:
                    p = self._paragraph()
                    for text, italic in runs:
                        if text:
                            self._run(p, text, em=italic)
        elif key == "index":
            self.first_on_page = True
            self.heading(self.label("first-lines" if features.get("index") == "first-lines" else "index"), 1)
            self.field(self._paragraph(), 'INDEX \\c "2"')

    def copyright_page(self, details):
        """The lines of the PDF's copyright page, small, then a page break."""
        def detail(k):
            v = details.get(k)
            return "" if isinstance(v, (dict, list, bool)) or v is None else re.sub(r"\s+", " ", str(v)).strip()
        lines = []
        holder = " ".join(x for x in (detail("year"), clean(self.meta.get("author"))) if x)
        if holder:
            lines.append("\u00a9 " + holder)
        for k, prefix in (("edition", ""), ("isbn", "ISBN "), ("nur", "NUR "), ("publisher", "")):
            if detail(k):
                lines.append(prefix + detail(k))
        rights = detail("copyright") or str(self.design.get("rights") or "")
        if rights:
            lines.append(rights)
        for text in lines:
            self._run(self._paragraph(), text).font.size = Pt(8)
        self.first_on_page = True

    def left_out(self, by_file) -> dict:
        """The generated pages the PDF leaves out, by the PDF's own rule (typeset_book.left_out): the pieces go through
        the typesetter for what it collects (notes, citations, index terms, first lines); its source isn't kept."""
        features = self.meta.get("features") if isinstance(self.meta.get("features"), dict) else {}
        ctx = typeset.Context(design=self.design, lang=str(self.meta.get("language") or "en"), sources=self.sources,
                              notes=features.get("notes") if features.get("notes") in NOTES else "footnotes",
                              numbering="book" if features.get("noteNumbering") == "book" else "chapter",
                              linked=self.books.linked_poem)
        for i, e in enumerate(self.meta.get("contents") or []):
            if not e.get("auto") and e.get("file") in by_file:
                typeset.piece(i, e, by_file[e["file"]][1]["doc"], ctx)
        return typeset_book.left_out(self.meta, self.design, ctx)

    def build(self) -> bytes:
        pieces = _pieces(self.books, self.book)
        by_file = {e["file"]: (e, p) for e, p in pieces}
        left = self.left_out(by_file)
        features = self.meta.get("features") or {}
        restart = (features.get("noteNumbering") or "chapter") != "book"
        autos = [e.get("auto") for e in self.meta.get("contents") or [] if e.get("auto")]
        # endnotes are listed where the notes page stands; without such an entry they stay after their piece
        self.notes_at_back = features.get("notes") in ("endnotes", "both") and "notes" in autos
        cp = self.doc.core_properties
        cp.title, cp.author = clean(self.meta.get("title")), clean(self.meta.get("author"))
        cp.language = clean(self.meta.get("language"))
        if not autos:
            self.title_page()                   # a book without generated pages keeps part 1's plain title page
        for i, e in enumerate(self.meta.get("contents") or []):
            if e.get("auto"):
                if i not in left:
                    self.auto(e["auto"], pieces)
            elif e.get("file") in by_file:
                self.piece(*by_file[e["file"]], restart, listed=not self.notes_at_back)
        el = OxmlElement("w:updateFields")          # Word fills the contents and index fields on opening
        el.set(qn("w:val"), "true")
        self.doc.settings.element.append(el)
        out = io.BytesIO()
        self.doc.save(out)
        return out.getvalue()


def to_docx(books, book) -> bytes:
    return _Writer(books, book).build()


# ---------------------------------------------------------------------------------------------------------
# Markdown and zip

def to_markdown(books, book) -> bytes:
    """A YAML block (title, subtitle, author, lang, date; Pandoc reads it), then all pieces in order, each led by its kind and form as a comment (`<!-- kind: chapter; form: poem -->`, which
    import reads back as the start of a piece); the pieces' own Markdown, LF only."""
    meta = books.read(book)
    details = meta.get("details") if isinstance(meta.get("details"), dict) else {}
    year = details.get("year")
    year = year if isinstance(year, (int, str)) and not isinstance(year, bool) and str(year).strip() else \
        datetime.now().year
    head = ["---"]
    for key, value in (("title", meta.get("title")), ("subtitle", meta.get("subtitle")),
                       ("author", meta.get("author")), ("lang", meta.get("language")), ("date", year)):
        value = re.sub(r"\s+", " ", str(value or "")).strip()
        if value or key == "title":
            head.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    head.append("---")
    parts = ["\n".join(head) + "\n"]
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
    return save(books, book, fmt, now)[:3]


def save(books, book, fmt, now=None):
    """`export`, and the dated copy's path as well (None when the exports/ folder can't be written)."""
    if fmt not in FORMATS:
        raise BooksError("Choose PDF, .docx, Markdown or zip.")
    ext, ctype = FORMATS[fmt]
    when = now if isinstance(now, datetime) else datetime.now()
    if fmt == "pdf":
        from . import compose          # here, not at the top: compose imports this module for export_pdf
        data = compose.pdf(books, book, now=when)
    else:
        data = {"docx": to_docx, "md": to_markdown, "zip": to_zip}[fmt](books, book)
    stem = folder_name(str(books.read(book)["title"] or "")) or "book"
    if stem.split(".")[0].upper() in RESERVED:
        stem += "-1"
    try:
        path = _keep(books.dir(book) / "exports", f"{stem} {when:%Y-%m-%d %H%M}", ext, data)
    except OSError:
        path = None     # the folder can't be written (read-only, a full disk): the download still goes out
    return f"{stem}.{ext}", data, ctype, path


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
