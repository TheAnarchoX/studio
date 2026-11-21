r"""The manuscript dialect: a piece's Markdown file <-> the editor's document (ProseMirror JSON).

This is the dialect's only implementation (spec: docs/superpowers/specs/2026-11-12-books-design.md,
"Manuscript format"); word counts, search, import, export and the editor all go through it.

Documents are ProseMirror JSON as `Node.toJSON()` writes it: `attrs` carry every attribute of the type
(null defaults written out), `content` and `marks` are left out when empty, marks on a node are in the
order of SCHEMA["marks"], and adjacent text nodes with the same marks are merged.

`serialize` writes the canonical form, which `parse` reads back unchanged:
- blocks separated by one blank line, one newline at the end, LF only;
- `*em*`, `**strong**`, `~~strike~~`; span marks on the same range combine into one span with a fixed order,
  `[text]{.idx .comment .smallcaps .underline .large term="…" note="…" lang=en}` (one size of `SIZES`;
  `term`/`note` always quoted, with \" \\ \{ \} \| escaped; `lang` bare when it is letters, digits and hyphens);
- notes `^[…]`, citations `[see @key, p. 12; @other]` (leaving out `[];`, with \\ \| \$ escaped), a hard break is a
  backslash at the line end (in poems a plain line break, stanzas separated by a blank line);
- centred and right-aligned paragraphs in `::: center` / `::: right` fences, neighbours with the same
  alignment in one fence (in a poem piece they hold stanzas);
- lists (flat `list_item` blocks; manuscript_lists.py has the rules): `- `, `1. `, `a. `, `i. `, `A.  `, `I.  `,
  nested items and continued lines indented to the item's text, tight; a numbered list right after another at its
  level takes the other delimiter (`a. een` then `i) een`);
- tables as pipe tables: `| a | b |` with one space each side (an empty cell `|  |`), delimiter cells `---`, `:--`,
  `:-:`, `--:`, every row as many cells as the table has columns; a table without a header has an empty first row;
  a cell is one line (a line break in its notes is a space), with a no-break space at either end as an entity;
- LaTeX math as Pandoc's `tex_math_dollars` reads it: inline `$E = mc^2$` (one line, no space next to the dollars, no
  lone backslash at its end; in a table cell `|` is `\vert` and `\|` `\Vert`; a digit right after it as an entity),
  display math as `$$`, its lines (no blank ones), `$$`, a block of its own; a `$` that would end the math is `\$`
  (in inline math any outside `\text{…}`, in display math dollars side by side), empty math isn't written;
- a backslash before \ * _ [ ] ` ^ ~ | $ and, at a line start, before # > - + = :::, before the . or ) after a
  number, wherever a list marker would be read (`a\.`, `iv\.`, `A\)`, `\(a)`, `\(1)`) and before a `:-` line that
  would make the line above it a table's header; `\!` before a citation, `\{` after one; no-break spaces that start
  a block as an entity.
Italic, bold or strikethrough that CommonMark can't write (punctuation at its edge next to a letter outside,
`x*(y)*z`) is narrowed to what it can (`x(*y*)z`), or dropped; it never comes back as printed asterisks or tildes.

Poem lines are not read as Markdown blocks: inside `::: poem` there are only lines and stanzas, and a piece
whose form is poem keeps the dialect's blocks (title, `##` headings, quotations, scene breaks, `:::`
blocks) but reads lists, tables and underlined headings as lines.
"""
import re
import textwrap
from itertools import groupby

from markdown_it import MarkdownIt
from markdown_it.common.utils import isMdAsciiPunct, isPunctChar, isWhiteSpace
from mdit_py_plugins.attrs import attrs_plugin
from mdit_py_plugins.attrs.parse import ParseError, parse as parse_attrs
from mdit_py_plugins.colon_fence import colon_fence_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.dollarmath.index import math_block_dollar
from mdit_py_plugins.footnote import footnote_plugin

from .manuscript_lists import escape_line_start, list_rule, markers, md_marker, normalize

SCHEMA = {"nodes": ["doc", "title", "heading", "paragraph", "list_item", "aligned", "blockquote", "scene_break",
                    "epigraph", "attribution", "poem", "image", "page_break", "table", "table_row", "table_cell",
                    "math_display", "hard_break", "note", "cite", "math", "text"],
          "marks": ["em", "strong", "idx", "comment", "smallcaps", "lang", "underline", "strike", "size"]}
SIZES = ("x-small", "small", "large", "x-large")     # the size mark's steps; normal text has no size mark
ALIGNS = ("center", "right")                         # an aligned block's alignment; "as the book" has no block
COLUMN_ALIGNS = ("left", "center", "right")          # a table column's alignment; None is as the book

_RANK = {name: i for i, name in enumerate(SCHEMA["marks"])}
_SPAN = ("idx", "comment", "smallcaps", "underline", "size", "lang")     # span marks, in the order they are written
_RUNS = ("em", "strong", "strike")                   # marks written with delimiters around the text
_FENCES = ("epigraph", "poem", "pagebreak") + ALIGNS


# ---------------------------------------------------------------------------------------------------------
# Inline syntax the plugins don't cover: citations and image attributes

_KEY = r"\w(?:[\w:.#$%&+?~/-]*\w)?"
_KEY_RE = re.compile(_KEY)
CITE_KEY = _KEY_RE      # public name: books.py checks source ids against it
_CITE_ITEM = re.compile(r"\s*(?:(?P<prefix>[^@]*?)\s+)?@(?:\{(?P<bkey>[^{}]+)\}|(?P<key>" + _KEY + r"))"
                        r"(?:(?:\s*,\s*|\s+)(?P<locator>.*?))?\s*", re.S)
_ATTR_BLOCK = re.compile(r"\{([^{}\n]*)\}")
_ATTR = re.compile(r'(?:\.(?P<cls>[^\s.#{}"=]+)|#[^\s.#{}"=]+|(?P<key>[\w:-]+)='
                   r'(?:"(?P<quoted>(?:[^"\\]|\\.)*)"|(?P<bare>[^\s"{}]+)))\s*', re.S)
_ESCAPED = re.compile(r"\\(.)", re.S)
_CITE_ESCAPED = re.compile(r"\\([\\|$])")     # the only escapes inside a citation


def _squash(s):
    return " ".join(str(s or "").split())


def _unescape(value):
    return _ESCAPED.sub(r"\1", value)


def _cite_items(body):
    """`see @a, p. 3; @b` -> [{"key", "prefix", "locator"}], or None when it isn't a citation. `\\|`, `\\$` and `\\\\`
    are a pipe, a dollar and a backslash (as the writer writes them); any other backslash is itself, as v1.2 wrote
    it."""
    def text(s):
        return _CITE_ESCAPED.sub(r"\1", s or "")
    items = []
    for part in body.split(";"):
        m = _CITE_ITEM.fullmatch(part)
        if not m:
            return None
        items.append({"key": text(m["bkey"]) or m["key"], "prefix": _squash(text(m["prefix"])),
                      "locator": _squash(text(m["locator"]))})
    return items


def _span_follows(src, pos, end):
    """`{…}` span attributes at pos: then `[text with @]{…}` is a span, not a citation."""
    if pos >= end or src[pos] != "{":
        return False
    try:
        parse_attrs(src[pos:end])
    except ParseError:
        return False
    return True


def _bracket_end(state, start):
    """Where the `]` that closes the bracket at `start` is, or -1: one in math (`[$x]@y$]{.idx}`) or after a
    backslash doesn't close it, as in Pandoc."""
    src, pos, was = state.src, start + 1, state.pos
    try:
        while pos < state.posMax:
            c = src[pos]
            if c == "]":
                return pos
            if c == "$":
                state.pos = pos
                if _math_rule(state, True):
                    pos = state.pos
                    continue
            pos += 2 if c == "\\" else 1
        return -1
    finally:
        state.pos = was


def _cite_rule(state, silent):
    """`[@key]`, `[see @key, p. 12]`, `[@a; @b, pp. 3–5]`; runs before links and spans."""
    src, start = state.src, state.pos
    if src[start] != "[":
        return False
    end = _bracket_end(state, start)
    if end < 0:
        return False
    body = src[start + 1:end]
    if "@" not in body or "[" in body or _span_follows(src, end + 1, state.posMax):
        return False
    items = _cite_items(body)
    if items is None:
        return False
    if not silent:
        state.push("cite", "", 0).meta = {"items": items}
    state.pos = end + 1
    return True


def _attributes(s):
    """`.a #b key=value key="quoted \\"value\\""` -> {"class": [...], key: value}; None when malformed.

    The attrs plugin's own parser refuses `%` in bare values, so `{width=60%}` (and fence infos) go through here."""
    out, pos, s = {"class": []}, 0, s.strip()
    while pos < len(s):
        m = _ATTR.match(s, pos)
        if not m:
            return None
        if m["cls"]:
            out["class"].append(m["cls"])
        elif m["key"]:
            out[m["key"]] = _unescape(m["quoted"]) if m["quoted"] is not None else m["bare"]
        pos = m.end()
    return out


def _image_attrs_rule(state, silent):
    """`{width=60%}` right after an image."""
    if state.src[state.pos] != "{" or state.pending or not state.tokens or state.tokens[-1].type != "image":
        return False
    m = _ATTR_BLOCK.match(state.src, state.pos, state.posMax)
    attrs = _attributes(m[1]) if m else None
    if attrs is None:
        return False
    if not silent and attrs.get("width"):
        state.tokens[-1].attrs["width"] = attrs["width"]
    state.pos = m.end()
    return True


def _text_group_end(src, pos, stop):
    """Where a `\\text{…}` group at `pos` ends (just after its closing brace), or None: not one, or its braces don't
    close before `stop`. In inline math Pandoc reads such a group as it is, `$` and all (`\\text{if $y>0$}`); inside
    it a backslash and the character after it count as one."""
    if not src.startswith("\\text{", pos):
        return None
    depth, i = 0, pos + 5
    while i < stop:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        depth += {"{": 1, "}": -1}.get(c, 0)
        i += 1
        if not depth:
            return i
    return None


_MATH_BLOCK = math_block_dollar(allow_labels=False, allow_blank_lines=False)


def _math_block_rule(state, start, end, silent):
    """dollarmath's `$$` block rule (no labels, no blank lines). It pushes its token even when only asked whether a
    block starts here (silently, by a paragraph or list that checks whether it ends there): asked so, it runs on a
    token list that is thrown away."""
    if not silent:
        return _MATH_BLOCK(state, start, end, False)
    tokens, line = state.tokens, state.line
    state.tokens = []
    try:
        return _MATH_BLOCK(state, start, end, True)
    finally:
        state.tokens, state.line = tokens, line


def _math_rule(state, silent):
    """`$tex$` as Pandoc's `tex_math_dollars` reads it: the opening `$` has a non-space right after it, the closing one
    a non-space right before it and no digit right after it (`$20 en $30` is text); a backslash and the character
    after it are TeX (`\\$` doesn't close), and so is a `\\text{…}` group (`$a \\text{if $b$} c$`). It takes the place
    of dollarmath's inline rule, which also refuses a digit before the opening `$` (Pandoc reads `2$\\pi$` as math)
    and takes a `$` that starts a line for escaped when the line ends in a backslash (it reads `src[-1]`)."""
    src, start, stop = state.src, state.pos, state.posMax
    if src[start] != "$" or start + 1 >= stop or src[start + 1] == "$" or isWhiteSpace(ord(src[start + 1])):
        return False
    pos = start + 1
    while pos < stop and src[pos] != "$":
        if src[pos] == "\\":
            end = _text_group_end(src, pos, stop)
            pos = pos + 2 if end is None else end
        else:
            pos += 1
    if pos >= stop or isWhiteSpace(ord(src[pos - 1])) or (pos + 1 < stop and src[pos + 1] in "0123456789"):
        return False
    if not silent:
        token = state.push("math_inline", "math", 0)
        token.content, token.markup = src[start + 1:pos], "$"
    state.pos = pos + 1
    return True


class _Markdown(MarkdownIt):
    """Image paths are kept exactly as written: nothing here is rendered as HTML."""

    def normalizeLink(self, url):
        return url

    def validateLink(self, url):
        return True


def _markdown(block_off=(), block_only=None):
    md = _Markdown("commonmark", {"html": False})
    # The dialect has no code, raw HTML, links or link references: such text stays text.
    md.disable(["code", "fence", "html_block", "html_inline", "reference", "link", "autolink", "backticks"])
    md.use(footnote_plugin)                 # ^[inline] and [^label] notes
    md.core.ruler.disable("footnote_tail")  # definitions stay in place: unused ones are kept as text
    md.use(attrs_plugin, spans=True, after=())
    md.use(colon_fence_plugin)
    md.enable("strikethrough")              # `~~text~~`
    md.enable("table")                      # pipe tables (GFM's rule reads Pandoc's pipe tables); not in poems
    # `$$` display blocks: no labels, no blank lines in them (Pandoc ends display math there), and `$$…$$` inside a
    # line isn't display math; one may interrupt a paragraph (text, display math, text: dollarmath registers its rule
    # without that); `block_only` (inside `::: poem`) leaves the block rule out. Inline `$tex$` is read by
    # `_math_rule`, in place of the plugin's own.
    md.use(dollarmath_plugin, allow_labels=False, allow_blank_lines=False, double_inline=False)
    md.block.ruler.at("math_block", _math_block_rule, {"alt": ["paragraph", "reference", "blockquote", "list"]})
    md.inline.ruler.at("math_inline", _math_rule)
    # lists with letters and roman numerals too; under the same name, so `block_off`/`block_only` still reach it
    md.block.ruler.at("list", list_rule, {"alt": ["paragraph", "reference", "blockquote"]})
    md.inline.ruler.before("link", "cite", _cite_rule)
    md.inline.ruler.after("image", "image_attrs", _image_attrs_rule)
    if block_only:
        md.block.ruler.enableOnly(block_only)
    md.block.ruler.disable(list(block_off))
    return md


_MD = _markdown()
# A piece whose form is poem keeps the dialect's blocks (`# ` title, `##` heading, `> ` quotation, scene break,
# `:::` blocks); Markdown outside the dialect (lists, tables, underlined headings) stays lines of the poem.
_POEM_MD = _markdown(block_off=("lheading", "list", "table"))
# Inside `::: poem`: only lines and stanzas.
_LINES_MD = _markdown(block_only=("paragraph", "footnote_def"))


# ---------------------------------------------------------------------------------------------------------
# Document nodes

def _node(type_, content=None, attrs=None, marks=None):
    node = {"type": type_}
    if attrs is not None:
        node["attrs"] = attrs
    if content:
        node["content"] = content
    if marks:
        node["marks"] = [dict(m, attrs=dict(m["attrs"])) if "attrs" in m else dict(m) for m in marks]
    return node


def _add_text(out, text, marks):
    """Append text, merging it into the previous text node when the marks are the same."""
    if not text:
        return
    last = out[-1] if out else None
    if last is not None and last["type"] == "text" and last.get("marks", []) == marks:
        last["text"] += text
    else:
        node = _node("text", marks=marks)
        node["text"] = text
        out.append(node)


def _append(out, node):
    if node["type"] == "text":
        _add_text(out, node["text"], node.get("marks", []))
    else:
        out.append(node)


def _merge(stack):
    by_type = {}
    for group in stack:
        for mark in group:
            by_type[mark["type"]] = mark
    return sorted(by_type.values(), key=lambda m: _RANK[m["type"]])


def _span_marks(attrs):
    classes = str(attrs.get("class", "")).split()
    marks = []
    if "idx" in classes:
        marks.append({"type": "idx", "attrs": {"term": _unescape(attrs["term"]) if "term" in attrs else None}})
    if "comment" in classes:
        marks.append({"type": "comment", "attrs": {"note": _unescape(attrs.get("note", ""))}})
    if "smallcaps" in classes:
        marks.append({"type": "smallcaps"})
    if "underline" in classes:
        marks.append({"type": "underline"})
    size = next((c for c in classes if c in SIZES), None)      # one size per text: the first
    if size:
        marks.append({"type": "size", "attrs": {"size": size}})
    if attrs.get("lang"):
        marks.append({"type": "lang", "attrs": {"lang": _unescape(attrs["lang"])}})
    return marks


def _alt(children):
    """An image's caption is text: math in it stays its source."""
    return "".join(t.content if t.type in ("text", "text_special") else " " if t.type == "softbreak"
                   else "$" + _one_line(t.content) + "$" if t.type == "math_inline" else "" for t in children or [])


def _one_line(tex):
    """Inline TeX is one line: a line break (and the spaces around it) is a space, as Pandoc reads it."""
    return re.sub(r"\s*[\r\n]\s*", " ", str(tex or ""))


def _display_lines(tex):
    """Display TeX as its block holds it: no blank lines (Pandoc can't hold them), no spaces at line ends, no
    indentation all its lines share (a list item's, read by hand), nothing around it."""
    lines = [line.rstrip() for line in str(tex or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return textwrap.dedent("\n".join(line for line in lines if line.strip())).strip()


def _trim(run, end=" \t"):
    """Drop spaces, tabs and line breaks at both ends (paragraph text around an image). `end=None`: any whitespace at
    the end, as Markdown drops it at a paragraph's end (a table row made a paragraph)."""
    def loose(n, spaces=" \t"):
        return n["type"] == "hard_break" or (n["type"] == "text" and not n["text"].strip(spaces))
    while run and loose(run[0]):
        run.pop(0)
    while run and loose(run[-1], end):
        run.pop()
    if run and run[0]["type"] == "text":
        run[0]["text"] = run[0]["text"].lstrip(" \t")
    if run and run[-1]["type"] == "text":
        run[-1]["text"] = run[-1]["text"].rstrip(end)
    return run


def _paragraphs(nodes):
    """Flatten blocks into paragraphs (inside quotations, epigraphs, poems and notes; alignment is lost there). A
    table is a paragraph per row that has text, its cells joined by ` | `; display math is inline math."""
    out = []
    for n in nodes:
        t, content = n["type"], n.get("content", [])
        if t == "paragraph":
            out.append(n)
        elif t in ("title", "heading", "attribution"):
            if t == "attribution":
                lead = []
                _add_text(lead, "— ", [])
                for c in content:
                    _append(lead, c)
                content = lead
            if content:
                out.append(_node("paragraph", content))
        elif t == "list_item":
            out.append(_with_marker(n))
        elif t == "table":
            for r in content:
                cells = [c.get("content") or [] for c in r.get("content") or []]
                if not any(cells):
                    continue
                line = []
                for k, cell in enumerate(cells):
                    if k:
                        _add_text(line, " | ", [])
                    for c in cell:
                        _append(line, c)
                out.append(_node("paragraph", _trim(line, None)))   # no space at its ends (an empty edge cell)
        elif t in ("blockquote", "epigraph", "poem", "aligned"):
            out.extend(_paragraphs(content))
        elif t == "math_display":           # inline math in a paragraph of its own, as inline math is written
            tex = _inline_tex(n["attrs"]["tex"])
            if tex:
                out.append(_node("paragraph", [_node("math", attrs={"tex": tex})]))
        elif t == "image" and n["attrs"]["alt"]:
            out.append(_node("paragraph", [{"type": "text", "text": n["attrs"]["alt"]}]))
    return out


def _with_marker(item):
    """A list item where lists can't be becomes a paragraph; its marker (`-`, `1.`, `c.`) stays as text."""
    style = item["attrs"]["list"]
    marker = "-" if style == "bullet" else md_marker(style, item.get("_n", 1)).strip()
    content = []
    _add_text(content, marker + (" " if item.get("content") else ""), [])
    for c in item.get("content", []):
        _append(content, c)
    return _node("paragraph", content)


def _attribution(paragraph):
    content = list(paragraph["content"])
    rest = content[0]["text"][1:].lstrip()
    if rest:
        content[0] = dict(content[0], text=rest)
    else:
        content.pop(0)
    return _node("attribution", content)


def _fence_info(info):
    info = info.strip().rstrip(":").strip()
    if info.startswith("{") and info.endswith("}"):
        attrs = _attributes(info[1:-1]) or {"class": []}
        known = [c for c in attrs["class"] if c in _FENCES]
        return (known or attrs["class"] or [""])[0], attrs
    return (info.split() or [""])[0], {}


# ---------------------------------------------------------------------------------------------------------
# Markdown -> document

_DELIMITED = {"em_open": "em", "strong_open": "strong", "s_open": "strike"}
_CELL_ALIGN = {"text-align:" + a: a for a in COLUMN_ALIGNS}     # the style markdown-it gives th and td


def _join_aligned(blocks):
    """Neighbouring aligned blocks with the same alignment are one block, as the writer writes them."""
    out = []
    for n in blocks:
        if n["type"] == "aligned" and out and out[-1]["type"] == "aligned" and out[-1]["attrs"] == n["attrs"]:
            out[-1] = dict(out[-1], content=out[-1]["content"] + n["content"])
        else:
            out.append(n)
    return out


class _Reader:
    """Turns markdown-it tokens into document nodes. `md` is the parser for the piece's form; outside prose
    (`lines`) every line break is kept."""

    def __init__(self, md):
        self.md, self.lines = md, md is not _MD
        self.env = {}
        self.defs = {}          # footnote label -> its tokens (the first definition counts)
        self.def_order = []     # (label, tokens) of every definition, in order
        self.used = set()
        self.expanding = set()
        self.in_note = False
        self.in_cell = False    # reading a table cell's text (its `\|` came in without the backslash)
        self.level = 0          # how deep the list being read is

    def read(self, text, md=None):
        """Blocks of `text`, read with `md` (default: the piece's parser), e.g. `_LINES_MD` in a poem."""
        was = self.md, self.lines
        self.md = md or self.md
        self.lines = self.md is not _MD
        try:
            tokens = self.md.parse(text, self.env)
            self._collect(tokens)
            return self._blocks(tokens, 0)[0]
        finally:
            self.md, self.lines = was

    def leftovers(self):
        """Footnote definitions nothing refers to (or repeated ones) stay in the text as paragraphs."""
        used, out = set(self.used), []
        for label, tokens in list(self.def_order):
            if label not in used or self.defs[label] is not tokens:
                out.extend(self._blocks(tokens, 0)[0])
        return out

    def _collect(self, tokens):
        i = 0
        while i < len(tokens):
            if tokens[i].type == "footnote_reference_open":
                j = i + 1
                while tokens[j].type != "footnote_reference_close":
                    j += 1
                label, body = tokens[i].meta["label"], tokens[i + 1:j]
                self.defs.setdefault(label, body)
                self.def_order.append((label, body))
                i = j
            i += 1

    def _blocks(self, tokens, i, close=None):
        out = []
        while i < len(tokens):
            tok = tokens[i]
            t = tok.type
            if t == close:
                return out, i + 1
            if t == "paragraph_open":
                out.extend(self._paragraph(tokens[i + 1].children or []))
                i += 3
            elif t == "heading_open":
                content = self._inline(tokens[i + 1].children or [], heading=True)
                out.append(_node("heading", content, {"level": min(int(tok.tag[1:]), 3)}))
                i += 3
            elif t == "blockquote_open":
                inner, i = self._blocks(tokens, i + 1, "blockquote_close")
                paragraphs = _paragraphs(inner)
                if paragraphs:
                    out.append(_node("blockquote", paragraphs))
            elif t in ("bullet_list_open", "ordered_list_open"):
                items, i = self._list(tokens, i)
                out.extend(items)
            elif t == "table_open":
                table, i = self._table(tokens, i)
                out.append(table)
            elif t == "hr":
                out.append(_node("scene_break"))
                i += 1
            elif t == "math_block":
                tex = _display_lines(tok.content)
                if tex:
                    out.append(_node("math_display", attrs={"tex": tex}))
                i += 1
            elif t == "colon_fence":
                out.extend(self._fence(tok))
                i += 1
            elif t == "footnote_reference_open":
                while tokens[i].type != "footnote_reference_close":
                    i += 1
                i += 1
            else:
                i += 1
        return out, i

    def _list(self, tokens, i):
        """A Markdown list -> flat list items, a nested list one level deeper. An item is its first paragraph; its
        other blocks (a second paragraph, a quotation, an image) follow it. Each item carries `_n`, its number in the
        Markdown list, until `normalize`."""
        style, n = tokens[i].meta["list"], tokens[i].meta["start"]
        close, out, i = tokens[i].type[:-5] + "_close", [], i + 1
        while tokens[i].type != close:          # list_item_open
            self.level += 1
            inner, i = self._blocks(tokens, i + 1, "list_item_close")
            self.level -= 1
            lead = inner.pop(0) if inner and inner[0]["type"] == "paragraph" else {}
            item = _node("list_item", lead.get("content"), {"list": style, "level": self.level, "start": None})
            item["_n"] = n
            out += [item] + inner
            n += 1
        return out, i + 1

    def _table(self, tokens, i):
        """A pipe table -> table › table_row › table_cell, a cell's text read as one line (an image is its caption).
        Each column's alignment is its header cell's; markdown-it has cut long rows and filled short ones. A header row
        of empty cells is how a table without a header is written (Pandoc reads it so), unless the table has no text at
        all: a table just put in, nothing typed yet, keeps its header and every row. In a cell a pipe can only be
        written `\\|`, and markdown-it drops that backslash: a pipe in a cell's math was TeX's `\\|`, read as `\\Vert`."""
        rows, align = [], []
        while tokens[i].type != "table_close":
            tok = tokens[i]
            if tok.type == "tr_open":
                rows.append([])
            elif tok.type in ("th_open", "td_open"):
                if tok.type == "th_open":
                    align.append(_CELL_ALIGN.get(tok.attrs.get("style")))
                self.in_cell = True
                try:
                    rows[-1].append(_node("table_cell", self._inline(tokens[i + 1].children or [], heading=True)))
                finally:
                    self.in_cell = False
                i += 2
            i += 1
        header = any(c.get("content") for c in rows[0]) or not any(c.get("content") for r in rows for c in r)
        rows = [_node("table_row", r) for r in (rows if header else rows[1:])]
        return _node("table", rows, {"header": header, "align": align}), i + 1

    def _fence(self, tok):
        name, attrs = _fence_info(tok.info)
        if name == "pagebreak":
            return [_node("page_break")]
        if name == "poem":
            if attrs.get("src"):
                return [_node("poem", attrs={"src": attrs["src"]})]    # the text comes from the Poems library
            return [_node("poem", _paragraphs(self.read(tok.content, _LINES_MD)), {"src": None})]
        if name == "epigraph":
            paragraphs = _paragraphs(self.read(tok.content))
            last = paragraphs[-1].get("content", [{}])[0] if paragraphs else {}
            if last.get("type") == "text" and last["text"].startswith("—"):
                paragraphs[-1] = _attribution(paragraphs[-1])
            return [_node("epigraph", paragraphs)]
        if name in ALIGNS:
            # its paragraphs (in a poem piece, stanzas) are aligned; any other block comes out between them, unaligned
            out = []
            for n in self.read(tok.content):
                if n["type"] != "paragraph":
                    out.append(n)
                elif out and out[-1]["type"] == "aligned" and out[-1]["attrs"]["align"] == name:
                    out[-1]["content"].append(n)
                else:
                    out.append(_node("aligned", [n], {"align": name}))
            return out
        return self.read(tok.content)     # an unknown block: keep its text

    def _paragraph(self, children):
        content = self._inline(children)
        if not any(n["type"] == "image" for n in content):
            return [_node("paragraph", content)] if content else []
        out, run = [], []
        for n in content + [None]:
            if n is None or n["type"] == "image":
                run = _trim(run)
                if run:
                    out.append(_node("paragraph", run))
                if n is not None:
                    out.append(n)
                run = []
            else:
                run.append(n)
        return out

    def _inline(self, children, heading=False):
        out, stack, marks = [], [], []
        for tok in children:
            t = tok.type
            if t in ("text", "text_special"):
                _add_text(out, tok.content, marks)
            elif t in ("softbreak", "hardbreak"):
                if heading or (t == "softbreak" and not self.lines):
                    _add_text(out, " ", marks)
                else:
                    out.append(_node("hard_break", marks=marks))
            elif t in ("em_open", "strong_open", "s_open", "span_open"):
                stack.append(_span_marks(tok.attrs) if t == "span_open" else [{"type": _DELIMITED[t]}])
                marks = _merge(stack)
            elif t in ("em_close", "strong_close", "s_close", "span_close"):
                stack.pop()
                marks = _merge(stack)
            elif t == "footnote_ref":
                content = self._note(tok)
                if self.in_note:            # notes can't contain notes: keep the text
                    for n in content:
                        _append(out, n)
                else:
                    out.append(_node("note", content, marks=marks))
            elif t == "cite":
                out.append(_node("cite", attrs={"items": tok.meta["items"]}, marks=marks))
            elif t == "math_inline":
                tex = _one_line(tok.content)
                out.append(_node("math", attrs={"tex": _no_pipes(tex, "\\Vert") if self.in_cell else tex}, marks=marks))
            elif t == "image":
                alt = _alt(tok.children)
                if heading or self.in_note:
                    _add_text(out, alt, marks)
                else:
                    out.append(_node("image", attrs={"src": tok.attrs.get("src", ""), "alt": alt,
                                                     "width": tok.attrs.get("width")}))
            elif tok.content:
                _add_text(out, tok.content, marks)
        return out

    def _note(self, tok):
        was, cell, self.in_note = self.in_note, self.in_cell, True
        try:
            label = tok.meta.get("label")
            if label is None:                       # ^[inline note]
                return self._inline(self.env["footnotes"]["list"][tok.meta["id"]]["tokens"])
            self.used.add(label)                    # [^label] with a definition elsewhere
            if label in self.expanding:
                return []
            self.expanding.add(label)
            self.in_cell = False                    # the definition's text isn't a cell's
            try:
                blocks = self._blocks(self.defs.get(label, []), 0)[0]
            finally:
                self.expanding.discard(label)
            content = []
            for p in _paragraphs(blocks):
                if content and p.get("content"):
                    _add_text(content, " ", [])
                for n in p.get("content", []):
                    _append(content, n)
            return content
        finally:
            self.in_note, self.in_cell = was, cell


def _clean(md):
    if md.startswith("\N{BYTE ORDER MARK}"):
        md = md[1:]
    return md.replace("\r\n", "\n").replace("\r", "\n")


def parse(md: str, form: str = "prose") -> dict:
    """A piece's Markdown -> the editor's document. `form` "poem" keeps every line break."""
    reader = _Reader(_POEM_MD if form == "poem" else _MD)
    nodes = reader.read(_clean(md)) + reader.leftovers()
    for k, n in enumerate(nodes):
        if n["type"] == "heading" and n["attrs"]["level"] == 1:
            if k == 0:
                nodes[0] = _node("title", n.get("content"))     # the piece title is the first line
            else:
                n["attrs"]["level"] = 2
    return _node("doc", normalize(_join_aligned(nodes)), {"form": form})


# ---------------------------------------------------------------------------------------------------------
# Document -> Markdown

# `^[` opens a note; `~~` strikes; `|` ends a cell; `$` opens math
_ESCAPES = str.maketrans({c: "\\" + c for c in "\\*_[]`^~|$"})
_ENTITY = re.compile(r"&(?=#[0-9]{1,7};|#[xX][0-9a-fA-F]{1,6};|[A-Za-z][A-Za-z0-9]{1,31};)")
_NUMBERED = re.compile(r"\d{1,9}(?=[.)])")
_HEADING_END = re.compile(r"(^|[ \t])(#+)$")
# A line that is only `:-`, `:--:` …: under a line with a `|` in it (escaped or not) it is a table's delimiter row.
# (`-` and `|` at a line start are escaped anyway, so this is the only one-column delimiter row text can make.)
_DELIMITER_ROW = re.compile(r":-+:?[ \t]*")
_COLUMN_MD = {"left": ":--", "center": ":-:", "right": "--:"}   # a column without alignment: `---`
_BARE_LANG = re.compile(r"[A-Za-z0-9-]+")
_BARE_WIDTH = re.compile(r"[\w.%-]+")
_ORDER = {"span": 0, "strong": 1, "em": 2, "strike": 3}     # which delimiter goes outside when runs are equally long


def _esc(s):
    s = s.translate(_ESCAPES)
    return _ENTITY.sub(r"\\&", s) if "&" in s else s


def _esc_line_start(s):
    m = _NUMBERED.match(s)
    if m:
        return s[:m.end()] + "\\" + s[m.end():]
    if s[:1] in ("#", ">", "-", "+", "=") or s.startswith(":::") or _DELIMITER_ROW.fullmatch(s):
        return "\\" + s
    return escape_line_start(s)


def _quote(value):
    """An attribute value in quotes. `|` is escaped too: in a table cell it would end the cell."""
    value = re.sub(r"[\r\n\t]", " ", str(value))
    return '"' + re.sub(r'([\\"{}|])', r"\\\1", value) + '"'


def _fmt(marks):
    """Marks -> {("em",), ("strong",), ("strike",), ("span", ((name, value), ...))}: all span marks of a node make one
    span."""
    out, span = set(), {}
    for mark in marks:
        t, attrs = mark.get("type"), mark.get("attrs") or {}
        if t in _RUNS:
            out.add((t,))
        elif t == "idx":
            span["idx"] = attrs.get("term")
        elif t == "comment":
            span["comment"] = attrs.get("note") or ""
        elif t == "smallcaps":
            span["smallcaps"] = True
        elif t == "underline":
            span["underline"] = True
        elif t == "size":
            if attrs.get("size") in SIZES:          # a size the dialect doesn't have is normal text
                span["size"] = attrs["size"]
        elif t == "lang":
            if attrs.get("lang"):
                span["lang"] = attrs["lang"]
        else:
            raise ValueError(f"unknown mark: {t!r}")
    if span:
        out.add(("span", tuple((k, span[k]) for k in _SPAN if k in span)))
    return frozenset(out)


def _span_attrs(key):
    d = dict(key)
    parts = ["." + k for k in ("idx", "comment", "smallcaps", "underline") if k in d]
    if "size" in d:
        parts.append("." + d["size"])
    if d.get("idx") is not None:
        parts.append("term=" + _quote(d["idx"]))
    if d.get("comment"):
        parts.append("note=" + _quote(d["comment"]))
    if "lang" in d:
        parts.append("lang=" + (d["lang"] if _BARE_LANG.fullmatch(d["lang"]) else _quote(d["lang"])))
    return "{" + " ".join(parts) + "}"


def _open(mark):
    return {"span": "[", "em": "*", "strong": "**", "strike": "~~"}[mark[0]]


def _close(mark):
    return "]" + _span_attrs(mark[1]) if mark[0] == "span" else _open(mark)


def _cite_md(items):
    def clean(s, drop):         # squashed after dropping, so no space is left where a dropped character was
        return _squash(re.sub("[" + re.escape(drop) + "]", "", str(s or "")))

    def esc(s):                 # `|` would end a table cell, `$` open math; `\\` so that `\|` in the text stays itself
        return re.sub(r"([\\|$])", r"\\\1", s)
    parts = []
    for item in items:
        key = clean(item.get("key"), "[];{}")
        if not key:
            continue
        prefix, locator = esc(clean(item.get("prefix"), "[];@")), esc(clean(item.get("locator"), "[];"))
        key = "@" + (key if _KEY_RE.fullmatch(key) else "{" + esc(key) + "}")
        parts.append((prefix + " " if prefix else "") + key + (", " + locator if locator else ""))
    return "[" + "; ".join(parts) + "]" if parts else ""


_BARE_DOLLAR = re.compile(r"(?<!\\)((?:\\\\)*)\$")       # a `$` after an even number of backslashes (none too)
_TEX_PIPE = re.compile(r"\\.|\|", re.S)                  # a backslash with what it escapes, or a pipe


def _display_dollars(tex):
    """Display math ends at `$$`: a bare `$` next to another `$` is `\\$` (TeX's own literal dollar), so no `$$` is
    left inside; a single `$` stays (`\\text{if $y>0$}`)."""
    def sub(m):
        at = m.end() - 1
        return m[1] + "\\$" if "$" in (tex[at - 1:at], tex[at + 1:at + 2]) else m[0]
    return _BARE_DOLLAR.sub(sub, tex)


def _inline_dollars(tex):
    """Inline math ends at a bare `$`: one is `\\$`, except in a `\\text{…}` group, which is read as it is
    (`_text_group_end`). The `{` of a `\\text{` that doesn't close in the TeX is set apart (`\\text {`, the same in TeX),
    so that no brace after the math can close it."""
    out, i = [], 0
    while i < len(tex):
        if tex[i] == "\\":
            end = _text_group_end(tex, i, len(tex))
            if end is None and tex.startswith("\\text{", i):
                out.append("\\text ")
                i += 5
                continue
            end = end or i + 2
            out.append(tex[i:end])
            i = end
        else:
            out.append("\\$" if tex[i] == "$" else tex[i])
            i += 1
    return "".join(out)


def _inline_tex(tex):
    """Inline TeX as `$…$` holds it: one line; no space at its ends (Pandoc needs a non-space next to each dollar),
    no lone backslash at its end (it would escape the closing dollar: dropped, it meant nothing there); `$` as `\\$`
    (`_inline_dollars`). "" when nothing is left: the math isn't written."""
    tex = _one_line(tex).strip()
    while (len(tex) - len(tex.rstrip("\\"))) % 2:
        tex = tex[:-1].rstrip()
    return _inline_dollars(tex)


def _no_pipes(tex, bare="\\vert"):
    """TeX without pipes, for a table cell, where a pipe would end the cell: `\\|` is `\\Vert` and `|` is `\\vert` (the
    same symbols), or `bare` (a cell's `|` as read, which was written `\\|`)."""
    tex = str(tex or "")

    def sub(m):
        if m[0] not in ("|", "\\|"):
            return m[0]
        nxt = tex[m.end():m.end() + 1]
        return (bare if m[0] == "|" else "\\Vert") + (" " if nxt.isalpha() or nxt == "@" else "")
    return _TEX_PIPE.sub(sub, tex)


def _cell_math(nodes):
    """A cell's inline nodes with the math in them (in its notes too) written without pipes."""
    out = []
    for n in nodes:
        if n.get("type") == "math":
            attrs = n.get("attrs") or {}
            n = dict(n, attrs=dict(attrs, tex=_no_pipes(attrs.get("tex"))))
        elif n.get("type") == "note":
            n = dict(n, content=_cell_math(n.get("content") or []))
        out.append(n)
    return out


def _cls(c):
    """A character as CommonMark's emphasis rules see it: W(hitespace), P(unctuation) or A (anything else)."""
    code = ord(c)
    if isWhiteSpace(code):
        return "W"
    return "P" if isMdAsciiPunct(code) or isPunctChar(c) else "A"


def _class_runs(text):
    """`„ja”,` -> `„`, `ja`, `”,`: the pieces an em/strong/strike run can be trimmed by."""
    classes = [_cls(c) for c in text]
    parts, start = [], 0
    for k in range(1, len(text) + 1):
        if k == len(text) or classes[k] != classes[start]:
            parts.append(text[start:k])
            start = k
    return parts


def _items(nodes, heading, edges, single_breaks, end_spaces=None):
    """Inline nodes -> (kind, value, marks), kind text, br, note, cite or math (its TeX as written, `_inline_tex`;
    empty math is left out). Italic, bold and struck text is split into runs of letters, punctuation and spaces, so
    a run's edges can be trimmed (see `_layout`).
    `edges`: drop what Markdown drops at the edges of a block (line breaks; spaces at the start, any
    whitespace at the end, or only `end_spaces`: a table cell keeps a no-break space at its end as an entity);
    `single_breaks`: no empty lines (in a poem's notes they would end the stanza)."""
    items = []
    for n in nodes:
        t, fmt = n.get("type"), _fmt(n.get("marks") or [])
        if t == "text":
            text = re.sub(r"[\r\n]", " ", n.get("text") or "")
            if text and any((name,) in fmt for name in _RUNS):
                items += [("text", part, fmt) for part in _class_runs(text)]
            elif text:
                items.append(("text", text, fmt))
        elif t == "hard_break":
            items.append(("text", " ", fmt) if heading else ("br", "", fmt))
        elif t == "note":
            items.append(("note", n.get("content") or [], fmt))
        elif t == "cite":
            items.append(("cite", (n.get("attrs") or {}).get("items") or [], fmt))
        elif t == "math":
            tex = _inline_tex((n.get("attrs") or {}).get("tex"))
            if tex:
                items.append(("math", tex, fmt))
        else:
            raise ValueError(f"unknown inline node: {t!r}")

    def blank(item, spaces=" \t"):      # gone at a line start (spaces, tabs), or at a block's end (any)
        return item[0] == "text" and not item[1].strip(spaces) and not any(m[0] == "span" for m in item[2])
    if single_breaks:
        kept = []
        for item in items:
            if item[0] == "br":
                j = len(kept)
                while j and blank(kept[j - 1]):
                    j -= 1
                if j and kept[j - 1][0] == "br":
                    del kept[j:]
                    continue
            kept.append(item)
        items = kept
    if edges:
        while items and (items[0][0] == "br" or blank(items[0])):
            items.pop(0)
        while items and (items[-1][0] == "br" or blank(items[-1], end_spaces)):
            items.pop()
    return items


def _stanzas(content):
    """In a poem a blank line ends the stanza: split a paragraph where two line breaks meet."""
    def blank(n):               # a line of spaces or tabs is empty (no-break spaces and spans are not)
        return (n.get("type") == "text" and not (n.get("text") or "").strip(" \t")
                and not any(m.get("type") in _SPAN for m in n.get("marks") or []))
    groups, current, pending = [], [], []      # pending: a line break and the spaces after it
    for n in content:
        if n.get("type") == "hard_break" and pending:
            groups.append(current)
            current, pending = [], []
        elif n.get("type") == "hard_break" or (pending and blank(n)):
            pending.append(n)
        else:
            current += pending + [n]
            pending = []
    return groups + [current + pending]


# How the marks nest is decided from the text alone, so the Markdown reads back to a document that is written
# the same way. Worked examples (`b` is also an index term):
#   `x b y` in italics           -> `*x [b]{.idx} y*`   the span lies strictly inside the run
#   `x b` in italics, then `z`   -> `*x* [*b*]{.idx}z`  `*` after `}` can't close before a letter: the run is
#                                                       cut at the span, its part inside goes inside
#   `x`, `(y)` in italics, `z`   -> `x(*y*)z`           `*(` can't open after a letter, nor `)*` close before
#                                                       one: the brackets leave the run
#   `x`, `…` in italics, `y`     -> `x…y`               nothing solid is left: the mark is dropped

def _layout(items):
    """Give each em/strong/strike run an identity and decide where it starts and ends.

    A run is cut where a span would straddle it, so a span lies strictly inside the run or the run inside
    the span (`*a [b]{.idx} c*`, `[*a*]{.idx} *b*`). At its edges a run sheds spaces, line breaks, notes,
    citations and math (the mark means nothing on them, and asterisks must touch text), and punctuation that
    sits next to a letter outside the run (in `x*(y)*z` neither asterisk works: it becomes `x(*y*)z`); a
    run left with nothing loses its mark. Returns the items with these marks and, per item, where each
    mark ends."""
    n = len(items)
    solid = [kind == "text" and bool(val.strip()) for kind, val, _ in items]
    weak = [solid[k] and _cls(val[0]) == "P" for k, (kind, val, _) in enumerate(items)]   # punctuation only
    span_of = [next((m for m in fmt if m[0] == "span"), None) for _, _, fmt in items]
    marks = [set() if s is None else {s} for s in span_of]
    ends = [{} for _ in range(n)]
    groups, i = [], 0
    while i < n:
        j = i + 1
        while j < n and span_of[j] == span_of[i]:
            j += 1
        if span_of[i] is not None:
            groups.append((i, j))
            for k in range(i, j):
                ends[k][span_of[k]] = j
        i = j

    def edge(k, last):          # the class of the first (or last) character item k is written with
        kind, val, _ = items[k]
        if kind == "text":
            return _cls(val[-1] if last else val[0])
        return "W" if kind == "br" else "P"        # a note or citation is written with brackets, math with dollars

    def before(k):              # what an opening asterisk at item k would follow (other asterisks don't count)
        if k == 0:
            return "W"
        return "P" if span_of[k - 1] != span_of[k] else edge(k - 1, True)

    def after(k):               # what a closing asterisk before item k would precede
        if k == n:
            return "W"
        return "P" if span_of[k] != span_of[k - 1] else edge(k, False)

    def place(name, i, e):
        while i < e and (not solid[i] or (weak[i] and before(i) == "A")):
            i += 1
        while e > i and (not solid[e - 1] or (weak[e - 1] and after(e) == "A")):
            e -= 1
        if i >= e:
            return
        for s, t in groups:
            if s < e and t > i and not (i < s and t < e) and not (s <= i and e <= t):
                for a, b in ((i, max(i, s)), (max(i, s), min(e, t)), (min(e, t), e)):
                    if a < b:
                        place(name, a, b)
                return
        for k in range(i, e):
            marks[k].add((name, i))
            ends[k][(name, i)] = e

    for name in _RUNS:
        i = 0
        while i < n:
            j = i
            while j < n and (name,) in items[j][2]:
                j += 1
            if j > i:
                place(name, i, j)
            i = max(j, i + 1)
    return [(kind, val, frozenset(marks[k])) for k, (kind, val, _) in enumerate(items)], ends


def _close_into(out, mark, opened_at):
    """Close a mark. Spaces, line breaks, notes, citations and math at the end of an em/strong/strike run that has
    to close early (another run crosses it) move outside, since asterisks and tildes must touch text: with
    `*a ` open and `b` arriving without italics, `*`, `a ` becomes `*`, `a`, `*`, ` `."""
    if mark[0] == "span":
        out.append(("mark", _close(mark)))
        return
    tail = []
    while len(out) - 1 > opened_at:
        kind, s = out[-1]
        if kind == "text" and s != s.rstrip():
            out.pop()
            core = s.rstrip()
            tail.insert(0, ("text", s[len(core):]))
            if core:
                out.append(("text", core))
                break
        elif kind in ("br", "note", "cite", "math"):
            tail.insert(0, out.pop())
        else:
            break
    out.append(("mark", _close(mark)))
    out.extend(tail)


def _emit(items, ends, lines, start, heading):
    """Write laid-out items. Text is escaped a whole run at a time (between two marks), so splitting an item
    never hides `1.` or `&amp;` from the escapes. Worked example (prose, `start`): `1. ` + `nee`(em) + ` !`
    + citation + `{x}` gives `1\\. *nee* \\![@a]\\{x}`: the number's dot is escaped at the line start, the `!`
    before a citation would make it an image, and `{` after one would make it a span. A digit right after math is an
    entity (`$x$&#x35;`): after a digit the closing dollar would not close."""
    out, stack, buf = [], [], []    # out: (kind, markdown); stack: (mark, index of its opening); buf: raw text
    at_start, first_line = start, start

    def flush():
        nonlocal at_start
        if not buf:
            return
        raw = "".join(buf)
        buf.clear()
        if at_start:
            raw = raw.lstrip(" \t")                 # Markdown drops these at a line start; other spaces stay
            if not raw:
                return
        text = _esc(raw)
        if at_start:
            if first_line and text[0].isspace():    # ...but at a block's start it drops all of them
                text = f"&#x{ord(text[0]):X};" + text[1:]
            text, at_start = _esc_line_start(text), False
        out.append(("text", text))

    for i, (kind, val, fmt) in enumerate(items):
        if kind != "text" or not val.strip():
            # spaces, breaks, notes, citations and math don't open em/strong/strike; they only stay inside an open run
            opened = {m for m, _ in stack}
            fmt = frozenset(m for m in fmt if m[0] == "span" or m in opened)
        keep = 0
        while keep < len(stack) and stack[keep][0] in fmt:
            keep += 1
        opening = sorted((m for m in fmt if m not in {s for s, _ in stack[:keep]}),
                         key=lambda m: (-ends[i][m], _ORDER[m[0]]))
        if keep < len(stack) or opening:
            flush()
        while len(stack) > keep:
            _close_into(out, *stack.pop())
        # the mark that reaches furthest goes outside; with equal reach a span goes outside, then strong
        for mark in opening:
            if mark[0] != "span" and kind == "text" and val != val.lstrip():
                buf.append(val[:len(val) - len(val.lstrip())])        # spaces go before the asterisks
                val = val.lstrip()
                flush()
            stack.append((mark, len(out)))
            out.append(("mark", _open(mark)))
            at_start = False
        if kind == "text":
            buf.append(val)
            continue
        flush()
        if kind == "br":
            out.append(("br", "\n" if lines else "\\\n"))
            at_start, first_line = True, False
        elif kind == "note":
            out.append(("note", "^[" + _inline_md(val, lines and not heading, False, heading, note=True) + "]"))
            at_start = False
        elif kind == "cite":
            out.append(("cite", _cite_md(val)))
            at_start = False
        else:
            out.append(("math", "$" + val + "$"))
            at_start = False
    flush()
    while stack:
        _close_into(out, *stack.pop())
    for k in range(1, len(out)):            # after the moves above: what touches a citation or math
        if out[k][0] == "cite" and out[k - 1][0] == "text" and out[k - 1][1].endswith("!"):
            out[k - 1] = ("text", out[k - 1][1][:-1] + "\\!")     # `![@a](x)` would be an image
        if out[k - 1][0] == "cite" and out[k][0] == "text" and out[k][1].startswith("{"):
            out[k] = ("text", "\\" + out[k][1])                   # `[@a]{.idx}` would be a span
        if out[k - 1][0] == "math" and out[k][0] == "text" and out[k][1][:1] in tuple("0123456789"):
            out[k] = ("text", f"&#x{ord(out[k][1][0]):X};" + out[k][1][1:])     # `$x$5` would be text
    return "".join(s for _, s in out)


def _units(nodes_or_items, from_items):
    """The visible text with its marks, one unit per non-space character (and per note, citation or math, with its
    TeX), to check that Markdown reads back as meant; for items, also which em/strong/strike runs cover each unit."""
    units = []
    for entry in nodes_or_items:
        if from_items:
            kind, val, fmt = entry
            runs = frozenset(m for m in fmt if m[0] != "span")
            kinds = frozenset(m[0] if m[0] != "span" else m for m in fmt)
        else:
            kind, val = entry.get("type"), entry.get("text", "")
            runs, kinds = frozenset(), frozenset(m[0] if m[0] != "span" else m for m in _fmt(entry.get("marks") or []))
        if kind == "text":
            units += [((c, kinds), runs) for c in val if not c.isspace()]
        elif kind in ("note", "cite", "image"):
            units.append(((kind, None), frozenset()))
        elif kind == "math":
            units.append((("math", val if from_items else (entry.get("attrs") or {}).get("tex")), frozenset()))
    return units


def _misread(md, items, lines, heading, note):
    """None when `md` reads back as `items` mean; otherwise the em/strong/strike run to give up: the shortest one
    at the first difference, and of equally short ones a strike first (`~~` can't share a delimiter run with `*`,
    so without it the asterisks can often meet: `*b***c**`). Italic, bold or strikethrough Markdown can't write must
    never come back as printed asterisks or tildes."""
    reader = _Reader(_MD)
    reader.lines, reader.in_note = lines, note
    tokens = _MD.parseInline(md, reader.env)
    got = [u for u, _ in _units(reader._inline(tokens[0].children or [], heading=heading), False)]
    meant = _units(items, True)
    if got == [u for u, _ in meant]:
        return None
    sizes = {}
    for _, runs in meant:
        for r in runs:
            sizes[r] = sizes.get(r, 0) + 1
    if not sizes:
        return None                         # nothing left to give up
    p = next((k for k, (u, _) in enumerate(meant) if k >= len(got) or got[k] != u), len(meant))
    near = set().union(*(meant[k][1] for k in (p - 1, p) if 0 <= k < len(meant))) or set(sizes)
    return min(near, key=lambda r: (sizes[r], r[0] != "strike", r))


def _inline_md(nodes, lines, start, heading=False, note=False, cell=False):
    """Inline nodes -> Markdown. `start`: the text begins a line; `lines`: a hard break is a plain newline;
    `cell`: a table cell (see `_cell_edges`). Lays the marks out, writes them, and reads the result back: a run
    Markdown can't write is dropped and the text written again (`x` + `…`(em) + `y` gives `x…y`)."""
    items, ends = _layout(_items(nodes, heading, not note, lines, " \t" if cell else None))
    while True:
        md = _emit(items, ends, lines, start, heading)
        bad = _misread(md, items, lines, heading, note)
        if bad is None:
            if note:
                return md
            return _cell_edges(md) if cell else md.rstrip()    # a block's trailing whitespace is gone anyway
        items = [(kind, val, fmt - {bad}) for kind, val, fmt in items]


def _trimmed(c):
    """markdown-it trims this from a table cell's ends (CommonMark's whitespace and the line separators)."""
    return isWhiteSpace(ord(c)) or c in "\u2028\u2029"


def _cell_edges(md):
    """A cell's Markdown without spaces and tabs at its ends; any other space there that markdown-it would trim (a
    no-break space, U+3000, U+202F …) is written as an entity, so it is kept, as at a block's start."""
    md = md.strip(" \t\n\r\x0b\x0c")
    if md and _trimmed(md[0]):
        md = f"&#x{ord(md[0]):X};" + md[1:]
    if md and _trimmed(md[-1]):
        md = md[:-1] + f"&#x{ord(md[-1]):X};"
    return md


def _fenced(name, parts):
    body = "\n\n".join(p for p in parts if p)
    return f"::: {name}\n" + (body + "\n" if body else "") + ":::"


def _image_md(attrs):
    src = str(attrs.get("src") or "")
    if re.search(r"[\s()<>]", src):
        src = "<" + re.sub(r"([<>])", r"\\\1", src) + ">"
    out = "![" + _esc(_squash(attrs.get("alt"))) + "](" + src + ")"
    width = attrs.get("width")
    if width:
        width = str(width)
        out += "{width=" + (width if _BARE_WIDTH.fullmatch(width) else _quote(width)) + "}"
    return out


def _table_md(attrs, rows):
    """A table -> a pipe table: the header row (an empty one when the table has none), the delimiter row with each
    column's alignment, the other rows. The table is as wide as `align` or its longest row, whichever is more, so no
    cell is lost; short rows get empty cells. A cell is one line: its text as a heading's (a line break in a note is a
    space), without spaces and tabs at its ends (`_cell_edges`), its math without pipes (`_cell_math`). A table without
    rows or cells isn't written. A table with no text at all is written with its rows as they are, header or not: it
    reads back with the header on and every row (`_table`), so an empty row put above them would come back as a row
    more."""
    cells = [[_inline_md(_cell_math(c.get("content") or []), False, False, heading=True, cell=True)
              for c in r.get("content") or []] for r in rows]
    align = list(attrs.get("align") or [])
    width = max([len(align)] + [len(r) for r in cells])
    if not cells or not any(cells):
        return ""
    if not attrs.get("header", True) and any(s for r in cells for s in r):
        cells.insert(0, [])                 # Pandoc reads an empty first row as a table without a header
    align += [None] * (width - len(align))
    lines = ["| " + " | ".join(r + [""] * (width - len(r))) + " |" for r in cells]
    lines.insert(1, "| " + " | ".join(_COLUMN_MD.get(a, "---") for a in align) + " |")
    return "\n".join(lines)


def _block(node, lines):
    t, content, attrs = node.get("type"), node.get("content") or [], node.get("attrs") or {}
    if t == "paragraph":
        if lines:
            out = "\n\n".join(s for s in (_inline_md(g, True, True) for g in _stanzas(content)) if s)
        else:
            out = _inline_md(content, False, True)
    elif t in ("title", "heading"):
        level = 1 if t == "title" else min(max(int(attrs.get("level") or 2), 2), 3)
        text = _HEADING_END.sub(r"\1\\\2", _inline_md(content, False, False, heading=True).strip())
        out = "#" * level + (" " + text if text else "")
    elif t == "blockquote":
        inner = "\n\n".join(b for b in (_block(c, lines) for c in content) if b)
        out = "\n".join("> " + line if line else ">" for line in inner.split("\n")) if inner else ""
    elif t == "scene_break":
        out = "***"
    elif t == "page_break":
        out = "::: pagebreak\n:::"
    elif t == "epigraph":
        out = _fenced("epigraph", [_block(c, lines) for c in content])
    elif t == "attribution":
        out = "— " + _inline_md(content, lines, False).lstrip()
    elif t == "poem":
        if attrs.get("src"):
            out = "::: {.poem src=" + _quote(attrs["src"]) + "}\n:::"
        else:
            out = _fenced("poem", [_block(c, True) for c in content])
    elif t == "image":
        out = _image_md(attrs)
    elif t == "table":
        out = _table_md(attrs, content)
    elif t == "math_display":
        tex = _display_dollars(_display_lines(attrs.get("tex")))
        out = f"$$\n{tex}\n$$" if tex else ""       # no `$$` is left inside: no line ends in it but the closing one
    elif t == "aligned":
        parts = [_block(c, lines) for c in content]
        if attrs.get("align") not in ALIGNS:
            out = "\n\n".join(p for p in parts if p)        # "as the book": plain paragraphs
        else:
            out = _fenced(attrs["align"], parts) if any(parts) else ""     # one without text is dropped
    else:
        raise ValueError(f"unknown block: {t!r}")
    return "\n".join(line.rstrip(" \t") for line in out.split("\n"))


def _list_md(items):
    """Consecutive top-level list items -> one Markdown block. Each item is its marker and text; a nested item and the
    lines after a line break are indented to the text of the item they belong to. A blank line comes before an item
    that starts a list, except a nested list that can interrupt its parent's text (it starts at 1 and isn't empty)
    and one under an empty item (there a blank line would end the empty item). A numbered list right after another
    at its level (no shallower item between) takes the other delimiter, `.` then `)`, since a new delimiter is what
    starts a new list in CommonMark and Pandoc: else `a. b. i.` would read as one lettered list."""
    lines, columns, texts = [], [], []
    runs = []       # per level, the open list: (style, delimiter)
    found = markers(items)
    for k, (item, m) in enumerate(zip(items, found)):
        level, style = m["level"], m["list"]
        del runs[level + 1:]
        if m["first"]:
            before = runs[level] if level < len(runs) else None
            after_numbered = style != "bullet" and before is not None and before[0] != "bullet"
            runs[level:] = [(style, ")" if after_numbered and before[1] == "." else ".")]
        marker = md_marker(style, m["n"], runs[level][1])
        indent = columns[level - 1] if level else 0
        columns[level:] = [indent + len(marker)]
        text = _inline_md(item.get("content") or [], False, True)
        can_interrupt = m["n"] == 1 and bool(text)    # CommonMark: a list may interrupt text when it starts at 1
        under_empty = level and found[k - 1]["level"] == level - 1 and not texts[k - 1]
        if m["first"] and k and (level == 0 or not (can_interrupt or under_empty)):
            lines.append("")
        texts.append(text)
        lines.append(" " * indent + marker + text.replace("\n", "\n" + " " * columns[level]))
    return "\n".join(line.rstrip(" \t") for line in "\n".join(lines).split("\n"))


def _together(node):
    """What top-level blocks are written as one: a run of list items; neighbouring aligned blocks with the same
    alignment (one fence). None: the block on its own."""
    t = node.get("type")
    if t == "list_item":
        return ("list",)
    return ("aligned", (node.get("attrs") or {}).get("align")) if t == "aligned" else None


def serialize(doc: dict, form: str | None = None) -> str:
    """The editor's document -> canonical Markdown. `form` defaults to the document's own (`attrs.form`)."""
    form = form or (doc.get("attrs") or {}).get("form") or "prose"
    blocks = []
    for key, run in groupby(doc.get("content") or [], key=_together):
        run = list(run)
        if key == ("list",):
            blocks.append(_list_md(run))
        elif key is not None:
            content = [c for n in run for c in n.get("content") or []]
            blocks.append(_block({"type": "aligned", "attrs": {"align": key[1]}, "content": content}, form == "poem"))
        else:
            blocks += [_block(n, form == "poem") for n in run]
    blocks = [b for b in blocks if b]
    return "\n\n".join(blocks) + "\n" if blocks else ""


# ---------------------------------------------------------------------------------------------------------
# Text, counts, titles

_WORD = re.compile(r"[^\W_]")
# Dutch clitics ('s, ’t, 'n, 'k, 'm, 'r, 'ns) are part of the next word ('s avonds); `‘Ik`, `'em` are words
_CLITIC = re.compile(r"[(\[„“\"«‹]*['’‘](?:s|t|n|k|m|r|ns)")


def _text_of(nodes):
    return "".join(n.get("text", "") if n.get("type") == "text" else "\n" if n.get("type") == "hard_break" else ""
                   for n in nodes)


def _block_text(node, out):
    t = node.get("type")
    if t in ("blockquote", "epigraph", "poem", "aligned"):
        for c in node.get("content") or []:
            _block_text(c, out)
    elif t in ("title", "heading", "paragraph", "list_item", "attribution"):
        out.append(_text_of(node.get("content") or []))
    elif t == "table":
        for r in node.get("content") or []:
            cells = [_text_of(c.get("content") or []) for c in r.get("content") or []]
            if any(cells):
                out.append(" | ".join(cells))


def plain_text(doc: dict) -> str:
    """The body text: blocks separated by a blank line (a table's rows too, their cells joined by ` | `); no notes,
    comment notes, citations or captions."""
    out = []
    for n in doc.get("content") or []:
        _block_text(n, out)
    return "\n\n".join(out)


def _notes(node):
    for c in node.get("content") or []:
        if c.get("type") == "note":
            yield c
        else:
            yield from _notes(c)


def _word_count(text):
    return sum(1 for w in text.split() if _WORD.search(w) and not _CLITIC.fullmatch(w))


def counts(md: str, form: str = "prose") -> dict:
    """Words of the text (not its `# ` title: an empty new piece has none; `##` headings count), and its notes."""
    doc = parse(md, form)
    notes = list(_notes(doc))
    body = {**doc, "content": [n for n in doc.get("content") or [] if n.get("type") != "title"]}
    return {"words": _word_count(plain_text(body)),
            "note_words": sum(_word_count(_text_of(n.get("content") or [])) for n in notes),
            "notes": len(notes)}


def block_starts(md: str) -> list[int]:
    """The line (from 0) where each top-level block of `md` starts, as `parse` reads prose: where an import can cut a
    file between blocks."""
    return [t.map[0] for t in _MD.parse(_clean(md), {}) if t.level == 0 and t.nesting >= 0 and t.map]


def title_of(md: str) -> str | None:
    """The piece title (`# Title` as the first block), as plain text; None when the piece has none."""
    text = _clean(md).lstrip()
    gap = re.search(r"\n[ \t]*\n", text)
    head = text[:gap.start()] if gap else text
    if "[^" in head:                     # a note defined further down
        head = text
    content = parse(head).get("content") or [{}]
    if content[0].get("type") != "title":
        return None
    return _squash(_text_of(content[0].get("content") or [])) or None
