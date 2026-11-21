"""Importing a book from a .docx (through mammoth) or a Markdown file.

`propose` reads the file and returns what Studio would make of it, without writing anything: the title, subtitle
and author, the pieces (kind, form, title, Markdown, word count, first words) and the images (base64). The writer
reviews the proposal; `commit` then creates the book from the reviewed version.

Both sources end up as the same list of blocks (`html_to_blocks` for mammoth's HTML, the dialect's own parse for
Markdown), and the rules are applied to the blocks, in order:
 1. the Title style (or the first heading before any body text) is the book's title; ALL CAPS is title-cased;
 2. a Subtitle or `h2` right after it is the author when it equals the signature, else the subtitle;
 3. empty headings and paragraphs are dropped;
 4. a body paragraph of at most 40 words, entirely italic, before the first piece heading is a dedication;
 5. each remaining `h1` starts a piece, its kind from HEADING_KINDS (else chapter);
 6. at the start of a piece, one to four quote-like paragraphs followed by a `-`, `–` or `—` line are an epigraph;
 7. `h2`/`h3` inside a piece stay `##`/`###`;
 8. images are kept under their own names and referenced as `../images/<name>`;
 9. list items stay list items, nested levels kept: from a .docx in the numbering format and at the number Word shows
    them with, when the document's numbered paragraphs line up one to one with mammoth's items (else bullets, and
    numbers by level: decimal, lower-alpha, lower-roman, decimal); they are never quote-like or a dedication;
10. underline and strikethrough are kept (alignment and point sizes are not);
11. Word equations are not imported: the proposal's warnings say how many the file has.
Documents are built as ProseMirror JSON and written with `manuscript.serialize`, so the Markdown is canonical
(escaping, notes `^[…]`, italics, lists) and nothing is concatenated by hand.
"""
import base64
import binascii
import hashlib
import io
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from . import manuscript
from .books import FORMS, KINDS, LANGUAGE, PIECE_KINDS, Books, BooksError
from .manuscript_lists import STYLES, normalize

STYLE_MAP = """p[style-name='Title'] => h1.doc-title:fresh
p[style-name='Subtitle'] => p.doc-subtitle:fresh
p[style-name='Quote'] => blockquote > p:fresh
p[style-name='Intense Quote'] => blockquote > p:fresh
u => u"""

HEADING_KINDS = {
    "voorwoord": "foreword", "foreword": "foreword", "preface": "preface",
    "inleiding": "introduction", "introduction": "introduction",
    "proloog": "prologue", "prologue": "prologue", "epiloog": "epilogue", "epilogue": "epilogue",
    "nawoord": "afterword", "afterword": "afterword",
    "dankwoord": "acknowledgements", "acknowledgements": "acknowledgements", "acknowledgments": "acknowledgements",
    "opdracht": "dedication", "dedication": "dedication",
    "bijlage": "appendix", "appendix": "appendix",
    "over de auteur": "about-author", "about the author": "about-author",
}

TEXT_TYPES = (".md", ".markdown", ".txt")
DEDICATION_WORDS = 40
EPIGRAPH_LINES = 4
ATTRIBUTION_WORDS = 12
QUOTE_MARKS = "\"“„‘'«‚”’»"
DASHES = "-–—"
IMAGE_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
CONVERTIBLE = ("image/bmp", "image/tiff", "image/x-tiff")      # re-encoded as PNG
VOID = {"br", "img", "hr", "meta", "link", "input"}
NOTE_REF = re.compile(r"#(?:foot|end)note-\d+")
NOTE_ID = re.compile(r"(?:foot|end)note-\d+")
BACK_LINK = re.compile(r"#(?:foot|end)note-ref-\d+")
FRONT_PIECES = ("dedication", "epigraph", "content-note")


# ---------------------------------------------------------------------------------------------------------
# HTML -> tree

class _El:
    __slots__ = ("tag", "attrs", "kids")

    def __init__(self, tag, attrs=None):
        self.tag, self.attrs, self.kids = tag, dict(attrs or {}), []

    def has_class(self, name):
        return name in (self.attrs.get("class") or "").split()


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _El("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].kids.append(el)
        if tag not in VOID:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].kids.append(_El(tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].kids.append(data)


def _tree(html):
    t = _Tree()
    t.feed(html)
    t.close()
    return t.root


def _take_notes(el, notes):
    """Move mammoth's footnote and endnote lists out of the tree into `notes` (id -> <li>)."""
    kept = []
    for k in el.kids:
        if isinstance(k, _El) and k.tag in ("ol", "ul"):
            items = [i for i in k.kids if isinstance(i, _El) and i.tag == "li"]
            if items and all(NOTE_ID.fullmatch(i.attrs.get("id", "")) for i in items):
                for i in items:
                    notes[i.attrs["id"]] = i
                continue
        if isinstance(k, _El):
            _take_notes(k, notes)
        kept.append(k)
    el.kids = kept


# ---------------------------------------------------------------------------------------------------------
# Inline nodes

_RANK = {name: i for i, name in enumerate(manuscript.SCHEMA["marks"])}


NBSP = "\N{NO-BREAK SPACE}"


def _indent(ws):
    """Spaces and tabs that start a poem line as no-break spaces, a tab two: Markdown keeps those."""
    return "".join(NBSP * 2 if c == "\t" else NBSP for c in ws)


def _text(out, text, marks):
    text = text.replace("\t", " ").replace("\r", "").replace("\n", " ")
    if not text:
        return
    ms = [{"type": m} for m in sorted(marks, key=_RANK.get)]
    last = out[-1] if out else None
    if last and last["type"] == "text" and last.get("marks", []) == ms:
        last["text"] += text
        return
    node = {"type": "text"}
    if ms:
        node["marks"] = ms
    node["text"] = text
    out.append(node)


def _trim(nodes, keep_nbsp=False):
    """Spaces at both ends of a run of inline nodes go (no-break spaces too, unless they indent a line)."""
    edge = " " if keep_nbsp else "  "
    nodes = [n for n in nodes]
    while nodes and nodes[0]["type"] == "text":
        nodes[0] = dict(nodes[0], text=nodes[0]["text"].lstrip(edge))
        if nodes[0]["text"]:
            break
        nodes.pop(0)
    while nodes and nodes[-1]["type"] == "text":
        nodes[-1] = dict(nodes[-1], text=nodes[-1]["text"].rstrip(edge))
        if nodes[-1]["text"]:
            break
        nodes.pop()
    return nodes


def _note_of(li, notes):
    """A footnote's list item -> a note node: its paragraphs one after another, the back link left out."""
    parts = []
    for k in li.kids:
        part = _trim(_inline(k.kids if isinstance(k, _El) and k.tag == "p" else [k], set(), notes, True))
        if part:
            parts.append(part)
    content = []
    for part in parts:
        if content:
            _text(content, " ", set())
        content.extend(part)
    return {"type": "note", "content": _trim(content)}


def _inline(kids, marks, notes, in_note=False, lines=None):
    """`lines`: {"start": bool} for a paragraph with line breaks in it (a stanza): the spaces and tabs that start each of
    its lines are kept, as no-break spaces."""
    out = []
    for k in kids:
        if isinstance(k, str):
            if lines is not None and lines["start"]:
                ws = re.match(r"[ \t]*", k)[0]
                k = _indent(ws) + k[len(ws):]
                lines["start"] = not k.strip(NBSP)
            _text(out, k, marks)
            continue
        t = k.tag
        if t in ("em", "i"):
            sub = _inline(k.kids, marks | {"em"}, notes, in_note, lines)
        elif t in ("strong", "b"):
            sub = _inline(k.kids, marks | {"strong"}, notes, in_note, lines)
        elif t == "u":
            sub = _inline(k.kids, marks | {"underline"}, notes, in_note, lines)
        elif t in ("s", "del", "strike"):
            sub = _inline(k.kids, marks | {"strike"}, notes, in_note, lines)
        elif t == "br":
            if in_note:
                _text(out, " ", marks)
            else:
                out.append({"type": "hard_break"})
                if lines is not None:
                    lines["start"] = True
            continue
        elif t == "img":
            continue
        elif t == "a" and BACK_LINK.fullmatch(k.attrs.get("href", "")):
            continue
        elif t == "a" and NOTE_REF.fullmatch(k.attrs.get("href", "")):
            li = notes.get(k.attrs["href"][1:])
            if li is not None and not in_note:
                out.append(_note_of(li, notes))
                if lines is not None:
                    lines["start"] = False
            continue
        else:       # links, sup, sub, spans: the text stays
            sub = _inline(k.kids, marks, notes, in_note, lines)
        for n in sub:
            if n["type"] == "text":
                _text(out, n["text"], {m["type"] for m in n.get("marks", [])})
            else:
                out.append(n)
    return out


def _images(kids):
    for k in kids:
        if isinstance(k, _El):
            if k.tag == "img":
                yield k
            else:
                yield from _images(k.kids)


def _plain(nodes):
    return "".join(n["text"] if n["type"] == "text" else " " if n["type"] == "hard_break" else "" for n in nodes)


def _md_of(nodes):
    if not nodes:
        return ""
    return manuscript.serialize({"type": "doc", "content": [{"type": "paragraph", "content": nodes}]}, "prose").strip()


def _italic_only(nodes):
    texts = [n for n in nodes if n["type"] == "text" and n["text"].strip()]
    return bool(texts) and all(any(m["type"] == "em" for m in n.get("marks", [])) for n in texts) \
        and all(n["type"] in ("text", "hard_break", "note") for n in nodes)


def _block(kind, nodes, keep_nbsp=False):
    """`keep_nbsp`: the no-break spaces that indent its first line stay (a stanza, or Markdown, which has none to lose)."""
    indented = bool(nodes) and nodes[0]["type"] == "text" and nodes[0]["text"][:1] in (" ", NBSP)
    nodes = _trim(nodes, keep_nbsp)
    empty = not any(n["type"] != "text" or n["text"].strip() for n in nodes)
    return {"type": kind, "md": _md_of(nodes), "italic_only": _italic_only(nodes), "empty": empty, "nodes": nodes,
            "indented": indented}


def _image_block(img):
    src = (img.attrs.get("src") or "").strip()
    if not src or ":" in src:
        return None
    name = src.replace("\\", "/").rsplit("/", 1)[-1]
    node = {"type": "image", "attrs": {"src": "../images/" + name, "alt": _plain_alt(img), "width": None}}
    return {"type": "image", "md": "", "italic_only": False, "empty": False, "node": node}


def _plain_alt(img):
    return " ".join((img.attrs.get("alt") or "").split())


# ---------------------------------------------------------------------------------------------------------
# HTML -> blocks

def html_to_blocks(html: str, list_styles: list[tuple[str, int, int]] | None = None) -> list[dict]:
    """mammoth's HTML -> blocks {"type": h1|h2|h3|p|li|quote|title|subtitle|image, "md", "italic_only", "empty", ...}.
    `md` is the block's text in the dialect's inline syntax; footnotes and endnotes become `^[…]` at their
    reference. Tables become `table` blocks ("node"); links and the like keep the text. Each list item is an `li` block
    with "list" (a style of `manuscript_lists.STYLES`), "level" (how deeply it is nested) and "_n" (the number it
    shows): from `list_styles`, one (style, level, number) per item in order (`_docx_list_styles`), when they line up
    with the items, else DEFAULT_STYLES and the item's place in its list."""
    root = _tree(html)
    notes = {}
    _take_notes(root, notes)
    out, items = [], []
    _walk(root.kids, notes, out, items)
    _style_items(items, list_styles)
    return out


def _walk(kids, notes, out, items):
    for k in kids:
        if not isinstance(k, _El):
            continue
        t = k.tag
        if re.fullmatch(r"h[1-6]", t):
            level = int(t[1])
            kind = "title" if level == 1 and k.has_class("doc-title") else f"h{min(level, 3)}"
            _paragraph(k, kind, notes, out)
        elif t == "p":
            _paragraph(k, "subtitle" if k.has_class("doc-subtitle") else "p", notes, out)
        elif t == "blockquote":
            inner = [c for c in k.kids if isinstance(c, _El) and c.tag == "p"]
            if inner:
                for p in inner:
                    _paragraph(p, "quote", notes, out)
            else:
                _paragraph(k, "quote", notes, out)
        elif t in ("ul", "ol"):
            _list(k, notes, out, items)
        elif t == "table":
            _table(k, notes, out, items)
        elif t not in ("script", "style", "head", "img", "br", "hr"):
            _walk(k.kids, notes, out, items)


def _has_br(el):
    return any(isinstance(k, _El) and (k.tag == "br" or _has_br(k)) for k in el.kids)


def _paragraph(el, kind, notes, out):
    lines = {"start": True} if _has_br(el) else None        # a stanza: its lines keep their indentation
    block = _block(kind, _inline(el.kids, set(), notes, lines=lines), keep_nbsp=lines is not None)
    if not block["empty"]:
        out.append(block)
    for img in _images(el.kids):
        image = _image_block(img)
        if image:
            out.append(image)


def _list(el, notes, out, items, depth=0):
    """An `ol` or `ul`: per item an `li` block (its paragraphs joined by a space), the pictures in it after it, then its
    nested lists one level deeper. Every item, also one without text, goes into `items` for `_style_items`; an `li`
    holding nothing but a nested list (mammoth opens one when a list starts deeper than the one before it) is no item."""
    place = 0
    for li in el.kids:
        if not isinstance(li, _El) or li.tag != "li":
            continue
        rest, nested = [], []
        for c in li.kids:
            if isinstance(c, _El) and c.tag in ("ul", "ol"):
                nested.append(c)
            elif isinstance(c, _El) and c.tag == "p":
                rest.extend(c.kids)
                rest.append(" ")
            else:
                rest.append(c)
        if not (nested and all(isinstance(c, str) and not c.strip() for c in rest)):
            place += 1
            block = _block("li", _inline(rest, set(), notes))
            items.append({"block": None if block["empty"] else block, "level": depth, "ordered": el.tag == "ol",
                          "place": place})
            if not block["empty"]:
                out.append(block)
            for img in _images(rest):
                image = _image_block(img)
                if image:
                    out.append(image)
        for c in nested:
            _list(c, notes, out, items, depth + 1)


def _rows(table):
    """The `tr` elements of a table (not those of tables nested in its cells)."""
    for k in table.kids:
        if isinstance(k, _El) and k.tag == "tr":
            yield k
        elif isinstance(k, _El) and k.tag in ("thead", "tbody", "tfoot"):
            yield from _rows(k)


def _flat(kids, rest, lists):
    """A cell's content as inline `kids` in `rest`: paragraphs and nested tables' cells one after another, apart by a
    space; lists go to `lists`."""
    for c in kids:
        if not isinstance(c, _El):
            rest.append(c)
        elif c.tag in ("ul", "ol"):
            lists.append(c)
        elif c.tag in ("p", "tr", "td", "th", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"):
            _flat(c.kids, rest, lists)
            rest.append(" ")
        elif c.tag in ("table", "thead", "tbody", "tfoot", "colgroup"):
            _flat(c.kids, rest, lists)
        else:
            rest.append(c)


def _table(el, notes, out, items):
    """A `table` -> one block with a table node: the cell's paragraphs joined by a space, a line break a space, a nested
    table its cells' text, a list its items' text (still counted in `items`, which `_docx_list_styles` counts too),
    rows padded to the widest, `header` always true (the first row of a Word table is nearly always a header; the author
    can turn it off), `align` all None.
    The pictures in it come after the table."""
    rows, pictures = [], []
    for tr in _rows(el):
        cells = [c for c in tr.kids if isinstance(c, _El) and c.tag in ("td", "th")]
        if not cells:
            continue
        row = []
        for c in cells:
            rest, lists = [], []
            _flat(c.kids, rest, lists)
            nodes = _inline(rest, set(), notes)
            pictures.extend(_image_block(img) for img in _images(rest))
            for li in lists:
                scratch, listed = [], []
                _list(li, notes, scratch, listed)
                for item in listed:
                    item["block"] = None
                items.extend(listed)
                for b in scratch:
                    if b["type"] == "li":
                        if nodes:                   # apart by a space; nothing before a list the cell starts with
                            _text(nodes, " ", set())
                        nodes.extend(b["nodes"])
                    elif b["type"] == "image":
                        pictures.append(b)
            merged = []                             # a line break is a space; text with the same marks one node
            for n in nodes:
                if n["type"] in ("text", "hard_break"):
                    _text(merged, n.get("text", " "), {m["type"] for m in n.get("marks", [])})
                else:
                    merged.append(n)
            nodes = _trim(merged)
            row.append({"type": "table_cell", "content": nodes} if nodes else {"type": "table_cell"})
        rows.append(row)
    if not rows:
        return
    width = max(len(r) for r in rows)
    content = [{"type": "table_row", "content": r + [{"type": "table_cell"} for _ in range(width - len(r))]}
               for r in rows]
    node = {"type": "table", "attrs": {"header": True, "align": [None] * width}, "content": content}
    out.append({"type": "table", "md": "", "italic_only": False, "empty": False, "node": node})
    out.extend(image for image in pictures if image)


DEFAULT_STYLES = ("decimal", "lower-alpha", "lower-roman", "decimal")     # an `ol` item's style by level


def _style_items(items, list_styles):
    """Give each item's block its "list", "level" and "_n": Word's style and number when `list_styles` has one entry
    per item at the item's own level, else bullet for `ul`, DEFAULT_STYLES for `ol` and its place in its list."""
    word = list_styles is not None and len(list_styles) == len(items) and all(
        style in STYLES and level == item["level"] for (style, level, _), item in zip(list_styles, items))
    for k, item in enumerate(items):
        if item["block"] is None:
            continue
        if word:
            style, _, n = list_styles[k]
        else:
            style = DEFAULT_STYLES[min(item["level"], 3)] if item["ordered"] else "bullet"
            n = item["place"]
        item["block"].update(list=style, level=item["level"], _n=n)


# ---------------------------------------------------------------------------------------------------------
# Markdown -> blocks

MARKER = re.compile(r"<!--\s*kind:\s*([A-Za-z-]*)\s*(?:;\s*form:\s*([A-Za-z-]*)\s*)?-->")
_BLOCK_LINE = re.compile(r"#|>|:::|(?:\*[ \t]*){3,}$|(?:-[ \t]*){3,}$|(?:_[ \t]*){3,}$")     # the dialect's own block lines


def marker(kind, form):
    """The line Studio's Markdown export writes before each piece, and import reads back."""
    return f"<!-- kind: {kind}; form: {form} -->"


def _display_end(lines, i):
    """The line that ends the display math starting at line `i` (as the dialect's `$$` block rule reads it), or None
    when there is none there: `$$…$$` on one line, else `$$` and the first later line ending in `$$` before a blank
    line. Not indented four columns or more, and no `$$` later in the first line unless it ends there."""
    first = lines[i].expandtabs(4)
    stripped = first.strip()
    if not stripped.startswith("$$") or len(first) - len(first.lstrip()) >= 4:
        return None
    if len(stripped) > 3 and stripped.endswith("$$"):
        return i
    if "$$" in stripped[2:]:
        return None
    for j in range(i + 1, len(lines)):
        line = lines[j].strip()
        if not line:
            return None
        if line.endswith("$$"):
            return j
    return None


def _poem_lines(text, poem):
    """Spaces and tabs that start a poem line become no-break spaces (a tab two), written as entities so that Markdown
    keeps them, also at a stanza's start: the lines inside a ::: poem block, and in a piece whose form is poem every
    line but the dialect's own block lines (headings, quotations, scene breaks, ::: lines) and the lines of display
    math (TeX, `_display_end`). Prose stays as it is."""
    lines = text.split("\n")
    out, open_, i = [], [], 0             # the ::: blocks around the line, by name
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        end = _display_end(lines, i) if not open_ or open_[-1] != "poem" else None   # in `::: poem` `$$` is a line
        if end is not None:
            out += lines[i:end + 1]
            i = end + 1
            continue
        i += 1
        if stripped.startswith(":::"):
            name = stripped[3:].strip()
            if not name:
                if open_:
                    open_.pop()
            else:
                open_.append("poem" if re.match(r"\{?\s*\.?poem\b", name) else name.split()[0])
            out.append(line)
            continue
        inside = open_[-1] if open_ else None
        m = re.match(r"([ \t]+)([^ \t].*)$", line)
        if m and (inside == "poem" or (poem and inside != "pagebreak" and not _BLOCK_LINE.match(m[2]))):
            line = "&#xA0;" * len(_indent(m[1])) + m[2]
        out.append(line)
    return "\n".join(out)


def _sections(text):
    """The file cut into sections {"text", "marker": (kind, form) | None}: at every marker line (`<!-- kind: chapter;
    form: poem -->`, which Studio's Markdown export writes before each piece; the line itself is not text) and before
    every `# ` heading outside a fence, except the first heading after a marker, which is that piece's own title."""
    sections, current, mark, titled, fence, colons = [], [], None, True, None, 0

    def close():
        if mark is not None or any(line.strip() for line in current):
            sections.append({"text": "\n".join(current), "marker": mark})

    for line in text.split("\n"):
        stripped = line.strip()
        if fence:
            if stripped.startswith(fence):
                fence = None
        elif stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
        elif stripped.startswith(":::"):
            colons = colons - 1 if stripped == ":::" and colons else colons + 1 if stripped != ":::" else colons
        elif not colons and MARKER.fullmatch(stripped):
            close()
            m = MARKER.fullmatch(stripped)
            current, titled = [], False
            mark = (m[1] if m[1] in PIECE_KINDS else "chapter", m[2] if m[2] in FORMS else "prose")
            continue
        elif not colons and (re.match(r"#[ \t]", line) or line.rstrip() == "#"):
            if mark is not None and not titled and not any(x.strip() for x in current):
                titled = True        # the marked piece's title
            else:
                close()
                current, mark = [], None
        current.append(line)
    close()
    return sections


def _section_blocks(text, form="prose", sec=None):
    """A section's blocks, read in `form`; each knows its section and the document node it came from ("sec", "at")."""
    doc = manuscript.parse(_poem_lines(text, form == "poem"), form)
    out = []
    for at, n in enumerate(doc.get("content") or []):
        t = n["type"]
        content = n.get("content") or []
        if t == "title":
            made = [_block("h1", content, True)]
        elif t == "heading":
            made = [_block("h2" if (n.get("attrs") or {}).get("level", 2) <= 2 else "h3", content, True)]
        elif t == "paragraph":
            made = [_block("p", content, True)]
        elif t == "blockquote" and content and all(c["type"] == "paragraph" for c in content):
            made = [_block("quote", c.get("content") or [], True) for c in content]
        elif t == "image":
            made = [{"type": "image", "md": "", "italic_only": False, "empty": False, "node": n}]
        else:
            made = [{"type": "raw", "md": "", "italic_only": False, "empty": False, "node": n}]
        for b in made:
            b.update(sec=sec, at=at)
        out += made
    return [b for b in out if not b["empty"]]


def _rebuild(source, kind, form):
    """A piece from the Markdown it was made from, read in `form` (what the review screen chose): after a marker line
    as it is (Studio's own canonical Markdown), any other through the import rules."""
    first, _, rest = source.partition("\n")
    if MARKER.fullmatch(first.strip()):
        doc = manuscript.parse(_poem_lines(rest, form == "poem"), form)
        md = manuscript.serialize(doc, form)
        return _proposed(kind, form, manuscript.title_of(md) or "", md)
    blocks = _section_blocks(source, form)
    title = blocks.pop(0)["nodes"] if blocks and blocks[0]["type"] == "h1" else None
    return _piece(kind, title, blocks, form)


_YAML = re.compile(r"\A---[ \t]*\n(.*?\n)(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.S)


_YAML_LINE = re.compile(r"[A-Za-z_][\w-]*\s*:|\s+\S|\s*#|\s*-\s")


def _is_yaml(block) -> bool:
    """Whether the lines between the dashes are metadata: `key: value` lines (or their indented continuations,
    comments and list items), none blank at the very top (Pandoc's rule); prose between two rules stays text."""
    lines = block.split("\n")[:-1]
    if not lines or not lines[0].strip():
        return False
    return all(not l.strip() or _YAML_LINE.match(l) for l in lines)


def _markdown(text, signature, fallback):
    """A Markdown or text file -> the proposal. Text before the first marker follows the rules (title, dedication, a
    piece at every `# `); each marker starts a piece of its kind and form. Every piece keeps its `source`."""
    text = manuscript._clean(text)
    head = _YAML.match(text)
    if head and not _is_yaml(head.group(1)):
        head = None             # a thematic break and a scene break are not a metadata block
    if head:        # Studio's own export (and Pandoc) start with a YAML block: not text, but it names the book
        title = re.search(r"^title:\s*(.+?)\s*$", head.group(1), re.M)
        fallback = (title.group(1).strip("\"'") if title else "") or fallback
        text = text[head.end():]
    sections = _sections(text)
    for i, s in enumerate(sections):
        s["blocks"] = [] if s["marker"] else _section_blocks(s["text"], "prose", i)
    k = next((i for i, s in enumerate(sections) if s["marker"]), len(sections))
    out = _assemble([b for s in sections[:k] for b in s["blocks"]], signature, fallback)
    for s in sections[k:]:
        if s["marker"]:
            kind, form = s["marker"]
            source = marker(kind, form) + "\n" + s["text"]
            out["pieces"].append({**_rebuild(source, kind, form), "source": source})
        else:
            out["pieces"] += _split_pieces(list(s["blocks"]))
    _sources(out["pieces"], sections)
    return out


def _sources(pieces, sections):
    """Each piece made by the rules keeps the Markdown it came from as its `source` (the lines of its blocks in their
    section), so the form chosen on review reads that again and a plain-text poem keeps its lines. Only when the source
    makes the very piece proposed; otherwise there is none and the proposed Markdown is used."""
    spans = [(p, p.pop("_blocks", None)) for p in pieces]
    for i, (p, blocks) in enumerate(spans):
        if not blocks or "source" in p or blocks[0].get("sec") is None or any(b.get("sec") != blocks[0]["sec"] for b in blocks):
            continue
        sec = sections[blocks[0]["sec"]]
        starts = sec.setdefault("starts", manuscript.block_starts(sec["text"]))
        lines, at = sec["text"].split("\n"), blocks[0]["at"]
        if at and at >= len(starts):
            continue
        nxt = spans[i + 1][1] if i + 1 < len(spans) else None
        end = len(lines)
        if nxt and nxt[0].get("sec") == blocks[0]["sec"] and nxt[0]["at"] < len(starts):
            end = starts[nxt[0]["at"]]
        source = "\n".join(lines[starts[at] if at else 0:end])
        if _rebuild(source, p["kind"], p["form"])["md"] == p["md"]:
            p["source"] = source


# ---------------------------------------------------------------------------------------------------------
# Rules

def _title_case(title, force=False):
    letters = [c for c in title if c.isalpha()]
    if not force and (not letters or not all(c.isupper() for c in letters)):
        return title

    def word(w):
        w = w.lower()
        for i, c in enumerate(w):
            if c.isalpha():
                return w[:i] + c.upper() + w[i + 1:]
        return w
    return " ".join(word(w) for w in title.split(" "))


def _heading_kind(title):
    return HEADING_KINDS.get(" ".join(title.lower().split()).rstrip(".:"), "chapter")


def _quote_like(block, indented_dash):
    """Italic-only and Quote-style paragraphs always; one that merely starts with a quote mark (so also Dutch
    dialogue) only when the dash line after it is set apart like an attribution (indented)."""
    if block["type"] == "quote":
        return True
    if block["type"] != "p":
        return False
    return block["italic_only"] or (indented_dash and _plain(block["nodes"]).lstrip().startswith(tuple(QUOTE_MARKS)))


def _attribution(block):
    """The attribution node when the block is a `- Name` line, else None."""
    if block["type"] not in ("p", "quote"):
        return None
    nodes = [dict(n) for n in block["nodes"]]
    first = nodes[0] if nodes else None
    if not first or first["type"] != "text":
        return None
    text = first["text"].lstrip()
    if len(text) < 1 or text[0] not in DASHES or text[1:2] in tuple(DASHES):
        return None
    first["text"] = text[1:].lstrip()
    if not first["text"]:
        nodes.pop(0)
    nodes = _trim(nodes)
    if not nodes or len(_plain(nodes).split()) > ATTRIBUTION_WORDS:
        return None
    if block["italic_only"]:
        for n in nodes:
            if n.get("marks"):
                marks = [m for m in n["marks"] if m["type"] != "em"]
                n.pop("marks")
                if marks:
                    n["marks"] = marks
        merged = []
        for n in nodes:
            if n["type"] == "text":
                _text(merged, n["text"], {m["type"] for m in n.get("marks", [])})
            else:
                merged.append(n)
        nodes = merged
    return {"type": "attribution", "content": nodes}


def _epigraph(body):
    """(epigraph node, blocks used) when the piece starts with one, else (None, 0)."""
    for n in range(1, EPIGRAPH_LINES + 1):
        if n >= len(body):
            break
        if not _quote_like(body[n - 1], True):
            break
        attribution = _attribution(body[n])
        if attribution and all(_quote_like(b, body[n].get("indented", False)) for b in body[:n]):
            paragraphs = [{"type": "paragraph", "content": b["nodes"]} for b in body[:n]]
            return {"type": "epigraph", "content": paragraphs + [attribution]}, n + 1
    return None, 0


def _body_nodes(blocks):
    """Blocks -> document nodes; adjacent quotations share one blockquote; list items are made canonical by
    `manuscript_lists.normalize` (levels clamped, `start` from the number an item showed where it starts a list)."""
    nodes = []
    for b in blocks:
        t = b["type"]
        if t == "quote":
            para = {"type": "paragraph", "content": b["nodes"]}
            if nodes and nodes[-1]["type"] == "blockquote" and nodes[-1].get("_open"):
                nodes[-1]["content"].append(para)
            else:
                nodes.append({"type": "blockquote", "content": [para], "_open": True})
            continue
        if t in ("h2", "h3", "h1", "title"):
            nodes.append({"type": "heading", "attrs": {"level": 3 if t == "h3" else 2}, "content": b["nodes"]})
        elif t in ("p", "subtitle"):
            nodes.append({"type": "paragraph", "content": b["nodes"]})
        elif t == "li":
            nodes.append({"type": "list_item", "attrs": {"list": b["list"], "level": b["level"], "start": None},
                          "content": b["nodes"], "_n": b["_n"]})
        else:
            nodes.append(b["node"])
    for n in nodes:
        n.pop("_open", None)
    return normalize(nodes)


def _piece(kind, title_nodes, blocks, form="prose"):
    content = []
    if title_nodes is not None:
        content.append({"type": "title", "content": title_nodes})
    epigraph, used = _epigraph(blocks)
    if epigraph:
        content.append(epigraph)
    content += _body_nodes(blocks[used:])
    md = manuscript.serialize({"type": "doc", "attrs": {"form": form}, "content": content}, form)
    md = manuscript.serialize(manuscript.parse(md, form), form)         # canonical, whatever the source
    return _proposed(kind, form, _plain(title_nodes or []).strip() if title_nodes else "", md)


def _proposed(kind, form, title, md):
    """A proposed piece: its kind, form, title, canonical Markdown, words and first words."""
    doc = manuscript.parse(md, form)
    body = [n for n in doc["content"] if n["type"] not in ("title", "epigraph")]
    words = manuscript.plain_text({"type": "doc", "content": body}).split()
    first = " ".join(words[:12]) + (" …" if len(words) > 12 else "")
    return {"kind": kind, "form": form, "title": title, "md": md, "words": manuscript.counts(md, form)["words"],
            "first": first}


def _assemble(blocks, signature, fallback):
    """Rules 1-5 on a file's blocks. `fallback` is the file's name, the title when the file gives none (as it is, only
    ALL CAPS set in title case, as for a title from the file)."""
    blocks = [b for b in blocks if not b["empty"]]
    title_nodes, i = None, 0
    if blocks and blocks[0]["type"] in ("title", "h1") and not (
            blocks[0]["type"] == "h1" and _heading_kind(_plain(blocks[0]["nodes"])) != "chapter"):
        title_nodes, i = blocks[0]["nodes"], 1
    shown = _plain(title_nodes).strip() if title_nodes else str(fallback or "").strip()
    title = _title_case(shown)
    subtitle = author = ""
    if title_nodes and i < len(blocks):
        nxt = blocks[i]
        text = _plain(nxt["nodes"]).strip() if "nodes" in nxt else ""
        sig = " ".join(str(signature or "").lower().split())
        if nxt["type"] in ("subtitle", "h2") or (nxt["type"] == "p" and sig and " ".join(text.lower().split()) == sig):
            if sig and " ".join(text.lower().split()) == sig:
                author = text
            elif nxt["type"] != "p":
                subtitle = text
            i += 1
    rest = blocks[i:]
    for b in rest:      # later Title-style paragraphs are headings too, later Subtitles plain paragraphs
        if b["type"] == "title":
            b["type"] = "h1"
        elif b["type"] == "subtitle":
            b["type"] = "p"
    return {"title": title or "Untitled", "title_cased": bool(title) and title != shown, "subtitle": subtitle,
            "author": author, "pieces": _split_pieces(rest)}


def _split_pieces(rest):
    """Rules 4 and 5: a short italic paragraph before the first heading is the dedication, other text there an untitled
    chapter, and each `h1` starts a piece. Each piece knows the blocks it was made of ("_blocks", for its source)."""
    pieces, preamble = [], []

    def made(piece, used):
        piece["_blocks"] = used
        pieces.append(piece)
    while rest and rest[0]["type"] != "h1":
        preamble.append(rest.pop(0))
    if preamble and preamble[0]["type"] == "p" and preamble[0]["italic_only"] \
            and len(_plain(preamble[0]["nodes"]).split()) <= DEDICATION_WORDS:
        first = preamble.pop(0)
        made(_piece("dedication", None, [first]), [first])
    if preamble:
        made(_piece("chapter", None, preamble), preamble)
    i = 0
    while i < len(rest):
        head, i = rest[i], i + 1
        body = []
        while i < len(rest) and rest[i]["type"] != "h1":
            body.append(rest[i])
            i += 1
        name = _plain(head["nodes"]).strip()
        made(_piece(_heading_kind(name), head["nodes"], body), [head, *body])
    return pieces


# ---------------------------------------------------------------------------------------------------------
# Word's numbering

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_FORMATS = {"bullet": "bullet", "none": "bullet", "lowerLetter": "lower-alpha", "upperLetter": "upper-alpha",
            "lowerRoman": "lower-roman", "upperRoman": "upper-roman"}         # any other numFmt is a number: decimal
# Paragraph styles that STYLE_MAP or mammoth's own style map make something else before its list rules (a numbered
# heading is a heading); names compare without case, as mammoth's do, ids exactly.
_NOT_ITEM_NAMES = {"title", "subtitle", "quote", "intense quote", "heading", "footnote text", "endnote text",
                   "annotation text", "footnote", "endnote", *(f"heading {i}" for i in range(1, 7))}
_NOT_ITEM_IDS = {"Heading", *(f"Heading{i}" for i in range(1, 7))}
_MAMMOTH_LEVELS = ("0", "1", "2", "3", "4")      # its list rules go five levels deep; deeper is a paragraph
_UNREAD = {_W + t for t in ("pPr", "rPr", "sectPr", "tblPr", "trPr", "tcPr", "sdtPr", "del", "moveFrom")} | {_MC + "Choice"}
_INLINE = {_W + t for t in ("r", "hyperlink", "ins", "moveTo", "smartTag", "customXml", "sdtContent")}
_SHOWN = {_W + t for t in ("tab", "sym", "noBreakHyphen", "softHyphen", "footnoteReference", "endnoteReference",
                           "drawing", "pict", "object")}


def _val(el):
    return None if el is None else el.get(_W + "val")


def _number(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format(lvl):
    """A `w:lvl` -> (style, start); Word starts a level without `w:start` at 0, but a list from such a file is read
    as starting at 1, which is what its writer meant."""
    return _FORMATS.get(_val(lvl.find(_W + "numFmt")), "decimal"), _number(_val(lvl.find(_W + "start")), 1)


def _paragraphs(el):
    """The `w:p` elements mammoth reads, in its order (not those in deletions, deleted rows or an mc:Choice whose
    Fallback it reads instead)."""
    for c in el:
        if c.tag in _UNREAD or (c.tag == _W + "tr" and c.find(f"{_W}trPr/{_W}del") is not None):
            continue
        if c.tag == _W + "p":
            yield c
        yield from _paragraphs(c)


def _shows(el):
    """Whether mammoth writes anything for this paragraph's content (it leaves an empty paragraph out)."""
    for c in el:
        t = c.tag
        if t == _W + "t":
            shown = bool(c.text)
        elif t == _W + "br":
            shown = c.get(_W + "type") in (None, "textWrapping")
        elif t == _W + "bookmarkStart":
            shown = c.get(_W + "name") != "_GoBack"
        elif t == _W + "sdt":
            shown = _shows(c.find(_W + "sdtContent") if c.find(_W + "sdtContent") is not None else [])
        elif t == _MC + "AlternateContent":
            shown = _shows(c.find(_MC + "Fallback") if c.find(_MC + "Fallback") is not None else [])
        else:
            shown = t in _SHOWN or (t in _INLINE and _shows(c))
        if shown:
            return True
    return False


def _docx_list_styles(data: bytes) -> list[tuple[str, int, int]]:
    """(style, level, number) for each paragraph of the .docx that mammoth makes a list item, in document order: the
    numbering format of its level (`w:numFmt`) and the number Word shows it with. A paragraph's numbering is found as
    mammoth finds it (its own `w:numPr`, else a list linked to its paragraph style). Word counts per list
    (`w:abstractNum`) and level, from the level's `w:start`: every `w:num` of a list goes on with the same count, except
    that a `w:num` with a `w:startOverride` for a level starts that level there the first time it is used; a deeper
    level starts again when a shallower one goes on. Numbered paragraphs mammoth doesn't make items (empty ones,
    numbered headings) are counted too. [] when the file has no numbering or can't be read."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            numbering, document, styles = (ET.fromstring(z.read(name)) if name in names else None
                                           for name in ("word/numbering.xml", "word/document.xml", "word/styles.xml"))
        if numbering is None or document is None or document.find(_W + "body") is None:
            return []
        return _count(numbering, styles, document.find(_W + "body"))
    except Exception:       # the numbering only refines what mammoth read; without it the import still works
        return []


def _count(numbering, styles, body):
    abstracts, linked = {}, {}      # abstractNumId -> {"levels": {ilvl: lvl}, "link"}; paragraph style -> (abstract, ilvl)
    for a in numbering.findall(_W + "abstractNum"):
        aid, levels, loose = a.get(_W + "abstractNumId"), {}, None
        for lvl in a.findall(_W + "lvl"):
            ilvl = lvl.get(_W + "ilvl")
            if ilvl is None:
                loose = lvl
            else:
                levels[ilvl] = lvl
        if loose is not None:
            levels.setdefault("0", loose)
        for ilvl, lvl in levels.items():
            if _val(lvl.find(_W + "pStyle")) is not None:
                linked[_val(lvl.find(_W + "pStyle"))] = (aid, ilvl)
        abstracts[aid] = {"levels": levels, "link": _val(a.find(_W + "numStyleLink"))}
    nums = {}                       # numId -> {"abstract", "starts": {ilvl: startOverride}, "levels": {ilvl: lvl}}
    for n in numbering.findall(_W + "num"):
        num = nums[n.get(_W + "numId")] = {"abstract": _val(n.find(_W + "abstractNumId")), "starts": {}, "levels": {}}
        for o in n.findall(_W + "lvlOverride"):
            if o.find(_W + "startOverride") is not None:
                num["starts"][o.get(_W + "ilvl")] = _number(_val(o.find(_W + "startOverride")), 1)
            if o.find(_W + "lvl") is not None:
                num["levels"][o.get(_W + "ilvl")] = o.find(_W + "lvl")
    names, num_styles = {}, {}      # paragraph style id -> name (lower case); numbering style id -> numId
    for s in styles.findall(_W + "style") if styles is not None else []:
        if s.get(_W + "type") == "paragraph":
            names[s.get(_W + "styleId")] = (_val(s.find(_W + "name")) or "").lower()
        elif s.get(_W + "type") == "numbering":
            num_styles[s.get(_W + "styleId")] = _val(s.find(f"{_W}pPr/{_W}numPr/{_W}numId"))

    def find(num_id, ilvl, seen=()):
        """(abstractNumId, ilvl) of a numbering level, following a list style's link, as mammoth does; else None."""
        num = nums.get(num_id)
        abstract = abstracts.get(num["abstract"]) if num and num_id not in seen else None
        if abstract is None:
            return None
        if abstract["link"] is not None:
            return find(num_styles.get(abstract["link"]), ilvl, (*seen, num_id))
        return (num["abstract"], ilvl) if ilvl in abstract["levels"] else None

    out, counts, restarted, carried = [], {}, set(), False
    for p in _paragraphs(body):
        ppr = p.find(_W + "pPr")
        if ppr is not None and ppr.find(f"{_W}rPr/{_W}del") is not None:     # its text joins the next paragraph
            carried = carried or _shows(p)
            continue
        shows, carried = carried or _shows(p), False
        num_id = _val(p.find(f"{_W}pPr/{_W}numPr/{_W}numId"))
        ilvl = _val(p.find(f"{_W}pPr/{_W}numPr/{_W}ilvl"))
        style_id = _val(p.find(f"{_W}pPr/{_W}pStyle"))
        if num_id is not None and ilvl is not None:
            found = find(num_id, ilvl)
        elif style_id in linked:
            found, num_id = linked[style_id], None
        else:
            found = find(num_id, "0") if num_id is not None else None
        if found is None:
            continue
        aid, ilvl = found
        num = nums.get(num_id) or {"starts": {}, "levels": {}}
        style, start = _format(num["levels"].get(ilvl, abstracts[aid]["levels"][ilvl]))
        level, count = _number(ilvl, 0), counts.setdefault(aid, {})
        if ilvl in num["starts"] and (num_id, ilvl) not in restarted:
            restarted.add((num_id, ilvl))
            count[level] = num["starts"][ilvl]
        else:
            count[level] = count[level] + 1 if level in count else start
        for deeper in [k for k in count if k > level]:
            del count[deeper]
        if (shows and ilvl in _MAMMOTH_LEVELS and style_id not in _NOT_ITEM_IDS
                and names.get(style_id) not in _NOT_ITEM_NAMES):
            out.append((style, level, count[level]))
    return out


# ---------------------------------------------------------------------------------------------------------
# Propose

def _docx_blocks(data):
    import mammoth      # only imports need it

    images, seen, skipped = {}, {}, [0]

    def convert(image):
        with image.open() as f:
            raw = f.read()
        ctype = (image.content_type or "").lower()
        if ctype in CONVERTIBLE:
            try:
                from PIL import Image
                buf = io.BytesIO()
                Image.open(io.BytesIO(raw)).convert("RGBA").save(buf, "PNG")
                raw, ctype = buf.getvalue(), "image/png"
            except Exception:
                pass
        ext = IMAGE_EXT.get(ctype)
        if not ext or not raw:
            skipped[0] += 1
            return {"src": ""}
        key = hashlib.sha1(raw).hexdigest()
        if key not in seen:
            seen[key] = f"image-{len(seen) + 1}{ext}"
            images[seen[key]] = base64.b64encode(raw).decode("ascii")
        return {"src": seen[key], "alt": image.alt_text or ""}

    try:
        result = mammoth.convert_to_html(io.BytesIO(data), style_map=STYLE_MAP,
                                         convert_image=mammoth.images.img_element(convert))
    except Exception:
        raise BooksError("That file couldn't be read as a Word document. Save it again as .docx and retry.") from None
    return html_to_blocks(result.value, _docx_list_styles(data)), images, skipped[0]


_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def _docx_equations(data: bytes) -> int:
    """How many Word equations (`m:oMath`) the .docx holds, in its text, footnotes and endnotes: Studio doesn't import
    them (mammoth leaves them out), and the review screen says so. 0 when that can't be read."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            parts = [z.read(name) for name in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
                     if name in z.namelist()]
        return sum(1 for part in parts for _ in ET.fromstring(part).iter(_M + "oMath"))
    except Exception:       # the count only adds a warning; the import itself already read the file
        return 0


def propose(name: str, data: bytes, signature: str = "") -> dict:
    """What importing this file would make: {"title", "subtitle", "author", "pieces", "images", "warnings"}."""
    ext = Path(str(name or "")).suffix.lower()
    stem = Path(str(name or "")).stem
    images, skipped, equations = {}, 0, 0
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise BooksError("The file is empty.")
    fallback = stem.replace("_", " ").strip()
    if ext == ".docx":
        blocks, images, skipped = _docx_blocks(bytes(data))
        equations = _docx_equations(bytes(data))
        out = _assemble(blocks, signature, fallback)
        for p in out["pieces"]:
            p.pop("_blocks", None)
    elif ext in TEXT_TYPES:
        try:
            text = bytes(data).decode("utf-8-sig")
        except UnicodeDecodeError:
            raise BooksError("That file isn't UTF-8 text. Save it as UTF-8 and retry.") from None
        out = _markdown(text, signature, fallback)
    else:
        raise BooksError("Studio imports .docx, .md, .markdown and .txt files.")
    out["images"] = images
    out["warnings"] = ([f"{skipped} image{'s' if skipped != 1 else ''} in a format Studio can't use "
                        f"{'were' if skipped != 1 else 'was'} left out."] if skipped else [])
    if equations:
        out["warnings"].append(f"This file has {equations} equation{'s' if equations != 1 else ''}; "
                               f"Studio doesn't import equations yet.")
    return out


# ---------------------------------------------------------------------------------------------------------
# Commit

def _retarget(node, mapping):
    if node.get("type") == "image":
        src = (node.get("attrs") or {}).get("src", "")
        if src in mapping:
            node["attrs"] = dict(node["attrs"], src=mapping[src])
    for c in node.get("content") or []:
        _retarget(c, mapping)


def _retitle(doc, title):
    """Set the piece's title heading to plain text `title` (none when empty), keeping the rest."""
    text = " ".join(str(title or "").split())
    content = doc.setdefault("content", [])
    has = bool(content) and content[0].get("type") == "title"
    if has:
        content.pop(0)
    if text:
        content.insert(0, {"type": "title", "content": [{"type": "text", "text": text}]})


def commit(books: Books, final: dict) -> dict:
    """Create the book from a reviewed proposal and return it as `Books.read` does."""
    if not isinstance(final, dict):
        raise BooksError("Send the reviewed import.")
    pieces = final.get("pieces")
    if not isinstance(pieces, list) or not pieces:
        raise BooksError("There is nothing to import.")
    kind = final.get("kind", "memoir")
    if not isinstance(kind, str) or kind not in KINDS:
        raise BooksError("The kind is " + ", ".join(KINDS) + ".")
    language = final.get("language", "en")
    if not isinstance(language, str) or not LANGUAGE.fullmatch(language.strip() or "en"):
        raise BooksError("The language is a code like en or nl.")
    title = final.get("title")
    if not isinstance(title, str) or not title.strip():
        raise BooksError("Give the book a title.")
    for key in ("author", "subtitle"):
        if not isinstance(final.get(key, ""), str):
            raise BooksError(f"The {key} is text.")
    for p in pieces:
        if not isinstance(p, dict) or not isinstance(p.get("md"), str):
            raise BooksError("Each piece needs its text.")
        if not isinstance(p.get("kind"), str) or p["kind"] not in PIECE_KINDS:
            raise BooksError("A piece's kind is " + ", ".join(PIECE_KINDS) + ".")
        if not isinstance(p.get("form", "prose"), str) or p.get("form", "prose") not in FORMS:
            raise BooksError("A piece's form is " + ", ".join(FORMS) + ".")
        if not isinstance(p.get("title", ""), str):
            raise BooksError("A piece's title is text.")
        if not isinstance(p.get("source") or "", str):
            raise BooksError("A piece's source is text.")
    raw = {}
    given = final.get("images", {})
    if not isinstance(given, dict):
        raise BooksError("The images must be a list of names and data.")
    for name, b64 in given.items():
        try:
            if not isinstance(b64, str):
                raise ValueError(name)
            raw[str(name)] = base64.b64decode(b64, validate=True)
        except (ValueError, TypeError, binascii.Error):
            raise BooksError(f"{name} couldn't be read.") from None
    book = books.create(title, final.get("author") or "", language, kind, start=False)
    try:
        mapping = {f"../images/{n}": books.save_image(book["id"], n, data) for n, data in raw.items()}
        d = books.dir(book["id"])
        for p in pieces:
            form = p.get("form") or "prose"
            made = books.new_piece(book["id"], p["kind"], form, (p.get("title") if p.get("retitled") is True else p.get("title") or manuscript.title_of(p["md"])) or "")
            # the Markdown it came from, read in the form chosen on review (a plain-text poem keeps its lines)
            md = _rebuild(p["source"], p["kind"], form)["md"] if p.get("source") else p["md"]
            doc = manuscript.parse(md, form)
            if p.get("retitled") is True:       # the title was edited on the review screen
                _retitle(doc, p.get("title"))
            _retarget(doc, mapping)
            books.write_bytes(d / "manuscript" / made["file"], manuscript.serialize(doc, form).encode("utf-8"))
        meta = books.read(book["id"])
        contents = [{k: v for k, v in e.items() if k in ("file", "auto", "kind", "form", "status")}
                    for e in meta["contents"]]
        if any(a.get("auto") == "toc" for a in KINDS[kind]["contents"]):
            at = next((i for i, e in enumerate(contents) if e.get("file") and e.get("kind") not in FRONT_PIECES),
                      len(contents))
            contents.insert(at, {"auto": "toc"})
        fields = {"contents": contents}
        if final.get("subtitle"):
            fields["subtitle"] = final["subtitle"]
        return books.update(book["id"], fields)
    except BaseException:
        shutil.rmtree(books.dir(book["id"]), ignore_errors=True)      # this call made the folder a moment ago
        raise
