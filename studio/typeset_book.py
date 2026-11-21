"""Typesetting a whole book: one Typst source for every page, from the half-title to the index.

Spec: docs/superpowers/specs/2026-11-13-books-part-2-design.md ("Page rules", "Generated pages", "Citations").
`book` writes, in this order:
  1. the values the template reads: `design` (the resolved design, lengths in mm and sizes in pt), `fonts`, `book`
     (the details the title pages print), `pieces` (per contents entry its kind, plain title, number and label) and
     `body-start`. They come before the template because a Typst function only sees the names defined above it;
  2. the template, studio/typeset_template.typ: the page rules and the functions that set the generated pages;
  3. `#show: book-setup`, then every contents entry in order: a piece as `typeset.piece` writes it, in a scope of its
     own, and an auto page as a call of its template function, with the data gathered while the pieces were set.
The pieces are converted first, so the collectors (notes, citations, index terms, first lines) are full when the
generated pages are written; everything is then placed in contents order, so the author orders the generated pages
in the list of pieces as before. A generated page whose feature is off, or that has nothing to list, is left out
(`left_out`): no page, no contents line. Arabic page 1 is the first piece of the body as the list of pieces groups
the book (`body_range`).

As in typeset.py, the author's text (and book.json's) only enters as string literals (`typeset.lit`); labels and
names are built from indices and from this module's own words.
"""
import math
import re
from pathlib import Path

from . import citations, typeset
from .books import BACK_MATTER

TEMPLATE = Path(__file__).with_name("typeset_template.typ")
_TEMPLATE = None

# Their title is the file's name for them: never a heading or a contents line.
UNTITLED = ("dedication", "epigraph")

# The list of pieces' groups (book.js: BOOK_FRONT, BOOK_BACK and bookGroups): front matter runs from the start while
# the entries are of these kinds, back matter (books.BACK_MATTER) from the end; the rest is the body.
FRONT_MATTER = ("half-title", "title-page", "copyright", "toc", "dedication", "epigraph", "content-note", "foreword",
                "preface")
# Studio's names for the generated pages that can be left out, as the checks say them.
_PAGE_NAMES = {"notes": "The notes page", "bibliography": "The bibliography", "index": "The index",
               "first-lines": "The index of first lines"}

# The words the template prints itself, in the book's language (other languages read as English).
WORDS = {"en": {"page": "p.", "missing": "Image missing", "set-in": "Set in {}."},
         "nl": {"page": "blz.", "missing": "Afbeelding ontbreekt", "set-in": "Gezet uit de {}."}}
# Characters the template sets in the text face around the author's text: folios (digits and roman), leaders and
# punctuation of the generated pages, the copyright sign, en and em dashes, the scene break.
_FOLIOS = "0123456789ivxlcdm"
_SCENE = {"asterisks": "*", "asterism": "⁂"}

# Paths in the design whose numbers are lengths (mm) or type sizes (pt); every other number is written bare.
_MM = {("width",), ("height",), ("margins", "inside"), ("margins", "outside"), ("margins", "top"),
       ("margins", "bottom"), ("headings", "sink")}
_PT = {("text", "size"), ("text", "line"), ("headings", "size"), ("notes", "size")}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_KEYWORDS = {"none", "auto", "true", "false", "not", "and", "or", "let", "set", "show", "if", "else", "for", "in",
             "while", "break", "continue", "return", "import", "include", "context", "as"}

_EN = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
       "eighteen nineteen").split()
_EN_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_NL = ("een twee drie vier vijf zes zeven acht negen tien elf twaalf dertien veertien vijftien zestien zeventien "
       "achttien negentien").split()
_NL_TENS = "twintig dertig veertig vijftig zestig zeventig tachtig negentig".split()
_ROMAN = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
          (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))


def template() -> str:
    """The template's text, read once per process."""
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = TEMPLATE.read_text(encoding="utf-8")
    return _TEMPLATE


# ---------------------------------------------------------------------------------------------------------
# Values as Typst

def _key(k) -> str:
    k = str(k)
    return k if _IDENT.match(k) and k not in _KEYWORDS else typeset.lit(k)


def _number(v, unit="") -> str:
    if isinstance(v, float) and not math.isfinite(v):
        return "none"
    s = str(v) if isinstance(v, int) else f"{v:.4f}".rstrip("0").rstrip(".")
    return s + unit


def value(v, path=()) -> str:
    """A Python value as a Typst value: strings as literals, numbers with the unit their place in the design asks for
    (mm for lengths, pt for type sizes), dictionaries with their keys as names where they can be."""
    if v is None:
        return "none"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return _number(v, "mm" if path in _MM else "pt" if path in _PT else "")
    if isinstance(v, str):
        return typeset.lit(v)
    if isinstance(v, dict):
        if not v:
            return "(:)"
        return "(" + ", ".join(f"{_key(k)}: {value(x, path + (str(k),))}" for k, x in v.items()) + ")"
    if isinstance(v, (list, tuple)):
        return typeset._array(value(x, path) for x in v)
    return typeset.lit(str(v))


def _dict(**fields) -> str:
    """A Typst dictionary of values already written as Typst (keys are this module's own names)."""
    return "(" + ", ".join(f"{k.replace('_', '-')}: {v}" for k, v in fields.items()) + ")"


# ---------------------------------------------------------------------------------------------------------
# Numbers

def roman(n: int) -> str:
    out = []
    for v, s in _ROMAN:
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


def number_words(n: int, lang: str) -> str:
    """A chapter's number as a word, capitalised: "Twenty-One", "Eenentwintig"; digits outside 1–99 or for other
    languages."""
    if not 1 <= n <= 99 or lang not in ("en", "nl"):
        return str(n)
    if lang == "en":
        if n < 20:
            return _EN[n - 1].capitalize()
        tens, unit = _EN_TENS[n // 10 - 2], n % 10
        return tens.capitalize() + ("-" + _EN[unit - 1].capitalize() if unit else "")
    if n == 1:
        return "Eén"
    if n < 20:
        return _NL[n - 1].capitalize()
    tens, unit = _NL_TENS[n // 10 - 2], n % 10
    if not unit:
        return tens.capitalize()
    u = _NL[unit - 1]
    return (u + ("ën" if u.endswith("e") else "en") + tens).capitalize()


def _styled(n: int, style: str, lang: str) -> str:
    return str(n) if style == "digits" else roman(n) if style == "roman" else number_words(n, lang)


# ---------------------------------------------------------------------------------------------------------
# The book

def _title_of(doc) -> tuple[bool, str]:
    """(has a title, its plain text): the first `title` node, as typeset.piece sets it."""
    for n in (doc or {}).get("content") or []:
        if isinstance(n, dict) and n.get("type") == "title":
            return True, typeset._plain(n.get("content"))
    return False, ""


def _sections(doc):
    """(block index, plain text) of the `##` sections (and later titles) of a document, for the contents."""
    out, titled = [], False
    for k, n in enumerate((doc or {}).get("content") or []):
        if not isinstance(n, dict):
            continue
        t, level = n.get("type"), (n.get("attrs") or {}).get("level")
        if t == "title" and not titled:
            titled = True
        elif t == "title" or (t == "heading" and (type(level) is not int or level <= 2)):
            text = typeset._plain(n.get("content"))
            if text:
                out.append((k, text))
    return out


def _fold(s) -> str:
    return citations._fold(s)       # the bibliography's rule: case and accents ignored, so Één sits among the Es


def _squash(s) -> str:
    return " ".join(str(s if s is not None else "").split())


def _is_auto(entry) -> bool:
    return entry.get("auto") is not None        # as Books reads the contents: an entry with an auto page's name


def body_range(contents) -> tuple[int, int]:
    """(a, z): the body is contents[a:z], as the list of pieces groups the book (book.js, bookGroups). Arabic page
    numbers start at its first piece, whatever its kind: a prologue or an introduction there counts from 1."""
    def kind(e):
        return (e.get("auto") or e.get("kind")) if isinstance(e, dict) else None
    contents = list(contents or [])
    a, z = 0, len(contents)
    while a < z and kind(contents[a]) in FRONT_MATTER:
        a += 1
    while z > a and kind(contents[z - 1]) in BACK_MATTER:
        z -= 1
    return a, z


def auto_on(features, auto) -> bool:
    """Whether a generated page is in the book as the list of pieces shows it (book.js, bookAutoOn): Notes while the
    notes aren't off (footnotes too: the entry shows, its page is left out for having nothing to list), Bibliography
    while sources are on, Index while the index is; the other generated pages always."""
    f = features if isinstance(features, dict) else {}
    if auto == "notes":
        return bool(f.get("notes")) and f.get("notes") != "off"
    if auto == "bibliography":
        return f.get("sources") is True
    if auto == "index":
        return bool(f.get("index"))
    return True


def left_out(meta: dict, design: dict, ctx: typeset.Context) -> dict:
    """{contents index: why} of the generated pages the book leaves out, `why` ending the sentence "… is left out:".
    A page is left out when its feature is off (`auto_on`), and Notes, Bibliography and Index (or First lines) when
    they have nothing to list: no endnotes collected, no source to list (none cited, or none at all when the design
    lists every source), no index terms, no poems. `ctx` must be full: every piece set (typeset.piece) first. The
    PDF, its contents page, the .docx and the checks all ask this one rule."""
    meta = meta if isinstance(meta, dict) else {}
    return _left_out(meta.get("features"), design, ctx, enumerate(meta.get("contents") or []))


def _left_out(features, design, ctx, entries) -> dict:
    """left_out over (contents index, entry) pairs."""
    features = features if isinstance(features, dict) else {}
    cites = (design or {}).get("citations") or {}
    sources = [s for s in ctx.sources or [] if isinstance(s, dict)]
    known = {s.get("id") for s in sources}
    out = {}
    for i, e in entries:
        auto = e.get("auto") if isinstance(e, dict) else None
        why = None
        if auto == "notes":
            why = ("notes are off in this book" if not auto_on(features, auto)
                   else "the notes are footnotes" if ctx.notes == "footnotes"
                   else "the book has no endnotes yet" if not ctx.endnotes else None)
        elif auto == "bibliography":
            if not auto_on(features, auto):
                why = "sources are off in this book"
            elif cites.get("list") == "all":
                why = None if sources else "the book has no sources yet"
            elif not ctx.cited:
                why = "nothing in the book cites a source yet"
            elif not any(k in known for k in ctx.cited):
                why = "no citation names one of the book's sources yet"
        elif auto == "index":
            if not auto_on(features, auto):
                why = "the index is off in this book"
            elif features.get("index") == "first-lines":
                why = None if ctx.first_lines else "the book has no poems yet"
            elif not ctx.terms:
                why = "no index terms are marked yet"
        if why:
            out[i] = why
    return out


def left_out_name(meta: dict, i: int) -> str:
    """The page contents entry i stands for, as the checks name it: "The notes page", "The index of first lines"."""
    meta = meta if isinstance(meta, dict) else {}
    contents = meta.get("contents") or []
    e = contents[i] if 0 <= i < len(contents) and isinstance(contents[i], dict) else {}
    auto = e.get("auto")
    features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
    if auto == "index" and features.get("index") == "first-lines":
        auto = "first-lines"
    return _PAGE_NAMES.get(auto, "A generated page")


class _Book:
    def __init__(self, meta, pieces, design, fonts, ctx):
        self.meta = meta if isinstance(meta, dict) else {}
        self.design = design if isinstance(design, dict) else {}
        self.fonts = fonts if isinstance(fonts, dict) else {}
        self.ctx = ctx
        self.entries = []
        for p in pieces or []:
            i, entry, doc = p
            self.entries.append((int(i), entry if isinstance(entry, dict) else {}, doc))
        self.features = self.meta.get("features") if isinstance(self.meta.get("features"), dict) else {}
        self.labels = (self.design.get("pages") or {}).get("labels") or {}
        lang = typeset._language(self.meta.get("language") or ctx.lang) or ("en", None)
        self.lang, self.region = lang
        self.words = WORDS.get(self.lang, WORDS["en"])
        self.info = {}
        self.out = {}               # the generated pages left out (left_out), known once the pieces are set
        self.placed = self.entries  # the entries set, in contents order

    # ——— strings ———
    def _s(self, s) -> str:
        """A literal whose text is printed (in the text or heading face): its characters go to the font check."""
        s = str(s if s is not None else "")
        self.ctx.chars.update(c for c in s if c >= " " and not "\ud800" <= c <= "\udfff")
        return typeset.lit(s)

    def _content(self, s) -> str:
        return f"[#{self._s(s)}]" if s else "[]"

    def _label(self, auto) -> str:
        if auto == "index" and self.features.get("index") == "first-lines":
            auto = "first-lines"
        return str(self.labels.get(auto) or "")

    # ——— per entry ———
    def _kind(self, entry) -> str:
        return str(entry.get("auto") if _is_auto(entry) else entry.get("kind") or "")

    def _plan(self):
        """`info[i]`: kind, auto, plain title, number, whether the entry's heading carries <piece-i>, and whether it
        is `bare`: a numbered chapter without a title, whose number piece-start sets in the opening instead. A
        generated page left out later (`_leave_out`) goes from it again."""
        headings = self.design.get("headings") or {}
        style = headings.get("number") or "none"
        chapters = parts = 0
        for i, entry, doc in self.entries:
            kind, auto = self._kind(entry), _is_auto(entry)
            number = None
            if auto:
                title = self._label(kind) if kind in ("toc", "notes", "bibliography", "index") else ""
                labelled = bool(title)
            else:
                has_title, title = _title_of(doc)
                labelled = has_title and kind not in UNTITLED
                if kind == "chapter" and style != "none":
                    chapters += 1
                    number = _styled(chapters, style, self.lang)
                elif kind == "part":
                    parts += 1
                    number = _styled(parts, style if style != "none" else "roman", self.lang)
            bare = kind == "chapter" and number is not None and not labelled
            self.info[i] = {"kind": kind, "auto": auto, "title": title, "number": number, "labelled": labelled,
                            "bare": bare}

    def _leave_out(self):
        """The generated pages with nothing to list or whose feature is off are taken out (`left_out`); called once
        the pieces are set, so the collectors are full."""
        self.out = _left_out(self.features, self.design, self.ctx, ((i, e) for i, e, _ in self.entries))
        self.placed = [x for x in self.entries if x[0] not in self.out]
        for i in self.out:
            self.info.pop(i, None)

    def _body_start(self):
        """The contents index where arabic page 1 is: the first entry set in the body (`body_range`), or None."""
        contents = self.meta.get("contents")
        if not isinstance(contents, list):          # a caller without the book's contents: the entries are it
            n = max((i for i, _, _ in self.entries), default=-1) + 1
            given = {i: e for i, e, _ in self.entries}
            contents = [given.get(k, {}) for k in range(n)]
        a, z = body_range(contents)
        return next((i for i, _, _ in self.placed if a <= i < z), None)

    def _pieces(self) -> str:
        out = []
        for i, p in self.info.items():
            out.append(f"{typeset.lit(str(i))}: " + _dict(
                kind=typeset.lit(p["kind"]), generated=value(p["auto"]), title=self._s(p["title"]),
                number=self._s(p["number"]) if p["number"] is not None else "none", bare=value(p["bare"]),
                start=f"<piece-{i}>" if p["labelled"] else "none"))
        return "(" + ", ".join(out) + ")" if out else "(:)"

    def _book(self) -> str:
        m, details = self.meta, self.meta.get("details") if isinstance(self.meta.get("details"), dict) else {}

        def detail(k):
            v = details.get(k)
            return "" if isinstance(v, (dict, list, bool)) else _squash(v)

        rights = detail("copyright") or str(self.design.get("rights") or "")
        # "Set in Literata.": the family the text is really set in. Its cut faces are named "<family> Text", so a
        # family that fell back to Literata says so here too.
        face = str(self.fonts.get("text") or "")
        family = face[:-len(" Text")] if face.endswith(" Text") else str((self.design.get("text") or {}).get("font")
                                                                          or face)
        on = (self.design.get("pages") or {}).get("setIn")
        set_in = self.words["set-in"].format(family) if on and family else None
        notes_linked = self.ctx.notes in ("endnotes", "both") and any(
            e.get("auto") == "notes" for _, e, _ in self.placed)
        checks = m.get("checks") if isinstance(m.get("checks"), dict) else {}
        return _dict(
            title=self._s(_squash(m.get("title"))), subtitle=self._s(_squash(m.get("subtitle"))),
            author=self._s(_squash(m.get("author"))),
            publisher=self._s(detail("publisher")), year=self._s(detail("year")), edition=self._s(detail("edition")),
            isbn=self._s(detail("isbn")), nur=self._s(detail("nur")), rights=self._s(rights),
            set_in=self._s(set_in) if set_in else "none",
            lang=typeset.lit(self.lang), region=typeset.lit(self.region) if self.region else "none",
            notes=typeset.lit(self.ctx.notes), numbering=typeset.lit(self.ctx.numbering),
            notes_linked=value(notes_linked),
            allow_widows=value(checks.get("allowWidows") is True),     # book.json `checks`: the author's call
            words=_dict(page=typeset.lit(self.words["page"]), missing=typeset.lit(self.words["missing"])))

    # ——— generated pages ———
    def _contents(self) -> str:
        at = next((n for n, (_, e, _) in enumerate(self.placed) if e.get("auto") == "toc"), None)
        if at is None:
            return "()"
        sections = (self.design.get("pages") or {}).get("contentsSections")
        lines = []
        for i, entry, doc in self.placed[at + 1:]:
            p = self.info[i]
            if not p["labelled"] or not p["title"]:
                continue
            number = self._s(p["number"]) if p["number"] is not None else "none"
            lines.append(_dict(level="1", title=self._content(p["title"]), number=number, target=f"<piece-{i}>",
                               part=value(p["kind"] == "part")))
            if sections and not p["auto"]:
                for k, text in _sections(doc):
                    lines.append(_dict(level="2", title=self._content(text), number="none",
                                       target=f"(p: {i}, b: {k})", part="false"))
        return typeset._array(lines)

    def _notes(self) -> str:
        groups = []
        for e in self.ctx.endnotes:
            i, n = int(e["piece"]), int(e["n"])
            if not groups or groups[-1][0] != i:
                groups.append((i, []))
            groups[-1][1].append(_dict(n=str(n), body=f"[{e['body']}]", ref=f"<noteref-{i}-{n}>",
                                       label=f"<note-{i}-{n}>"))
        out = []
        for i, notes in groups:
            p = self.info.get(i) or {}
            title = p.get("title") or ""
            if not title and p.get("number"):
                title = f"{self.labels.get('chapter') or ''} {p['number']}".strip()
            out.append(_dict(title=self._s(title), notes=typeset._array(notes)))
        return typeset._array(out)

    def _runs(self, runs) -> str:
        return "[" + "".join(f"#emph[#{self._s(t)}]" if italic else f"#{self._s(t)}" for t, italic in runs if t) + "]"

    def _bibliography(self) -> str:
        cites = self.design.get("citations") or {}
        keys = None if cites.get("list") == "all" else list(self.ctx.cited)
        entries = citations.bibliography(self.ctx.sources, keys, cites.get("style") or "chicago", self.lang)
        return typeset._array(self._runs(runs) for runs in entries)

    def _index(self) -> str:
        terms = {}
        for (term, sub), key in self.ctx.terms.items():
            t = terms.setdefault(term, {"key": None, "subs": []})
            if sub:
                t["subs"].append((sub, key))
            else:
                t["key"] = key
        groups = []
        for term in sorted(terms, key=lambda s: (_fold(s), s)):
            folded = _fold(term)
            letter = folded[0].upper() if folded and folded[0].isalpha() else ""
            if not groups or groups[-1][0] != letter:
                groups.append((letter, []))
            t = terms[term]
            subs = typeset._array(_dict(term=self._s(s), key=typeset.lit(k))
                                  for s, k in sorted(t["subs"], key=lambda x: (_fold(x[0]), x[0])))
            groups[-1][1].append(_dict(term=self._s(term), key=typeset.lit(t["key"]) if t["key"] else "none",
                                       subs=subs))
        return typeset._array(_dict(letter=typeset.lit(letter), terms=typeset._array(ts)) for letter, ts in groups)

    def _first_lines(self) -> str:
        lines = sorted(self.ctx.first_lines, key=lambda x: (_fold(x[0]), x[0]))
        return typeset._array(_dict(text=self._content(text), piece=str(int(i))) for text, i in lines)

    def _auto(self, i, kind) -> str:
        out = [f"#piece-start({i}, {typeset.lit(kind)})"]
        if self.info[i]["labelled"]:
            out.append(f"#piece-title({i})[#{self._s(self.info[i]['title'])}]")
        if kind == "half-title":
            out.append("#half-title()")
        elif kind == "title-page":
            out.append("#title-page()")
        elif kind == "copyright":
            out.append("#copyright-page()")
        elif kind == "toc":
            out.append(f"#contents-page({self._contents()})")
        elif kind == "notes":
            out.append(f"#notes-page({self._notes()})")
        elif kind == "bibliography":
            out.append(f"#bibliography-page({self._bibliography()})")
        elif kind == "index" and self.features.get("index") == "first-lines":
            out.append(f"#first-lines-page({self._first_lines()})")
        elif kind == "index":
            out.append(f"#index-page({self._index()})")
        out.append(f"#piece-end({i})")
        return "\n".join(out) + "\n"

    def _printed(self, sources):
        """The characters the template sets in the text face itself, as far as this book uses them, for the font
        check: folios, the scene break, dashes, the copyright page's words, the notes' page references, leaders."""
        text = sources.values()
        kinds = {p["kind"] for p in self.info.values()}
        out = _FOLIOS + ".,()"
        if any("#scene-break()" in t for t in text):
            out += _SCENE.get(self.design.get("scene"), "")
        if any("#epigraph(" in t for t in text):
            out += "—"
        if any("#missing-image(" in t for t in text):
            out += self.words["missing"]
        if "part" in kinds:
            out += str(self.labels.get("part") or "")
        if "copyright" in kinds:
            out += "© ISBN NUR"
        if "notes" in kinds:
            out += self.words["page"]
        if "index" in kinds:
            out += "–"
        self._s(out)

    def source(self) -> str:
        self._plan()
        sources = {i: typeset.piece(i, entry, doc if isinstance(doc, dict) else {}, self.ctx)
                   for i, entry, doc in self.entries if not _is_auto(entry)}
        self._leave_out()
        body_start = self._body_start()
        head = [
            f"#let design = {value(self.design)}",
            "#let fonts = " + _dict(text=typeset.lit(self.fonts.get("text") or "Literata"),
                                    heading=typeset.lit(self.fonts.get("heading") or self.fonts.get("text")
                                                        or "Literata")),
            f"#let book = {self._book()}",
            f"#let pieces = {self._pieces()}",
            f"#let body-start = {body_start if body_start is not None else 'none'}",
        ]
        body = []
        for i, entry, doc in self.placed:
            if i == body_start:
                body.append('#set page(numbering: "1")')        # a set rule: it must stand at the top level
            if _is_auto(entry):
                body.append(self._auto(i, self.info[i]["kind"]))
            else:
                body.append(f"#[#show: piece-body.with({typeset.lit(self.info[i]['kind'])})\n{sources[i]}]\n")
        body.append("#blank-to-even()\n")
        self._printed(sources)
        return "\n".join(head) + "\n\n" + template() + "\n#show: book-setup\n\n" + "\n".join(body)


def book(meta: dict, pieces: list, design: dict, fonts: dict, ctx: typeset.Context) -> str:
    """The whole book's Typst source. `pieces` holds `(i, entry, doc)` for each contents entry, `i` its index in the
    book's contents and `doc` its document (None for an auto page); `design` is `book_design.resolve`'s; `fonts` the
    family names of the cut faces (`typeset_fonts.prepare(...)["names"]`); `ctx` collects as the pieces are set."""
    return _Book(meta, pieces, design, fonts, ctx).source()
