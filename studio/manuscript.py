r"""The manuscript dialect: a piece's Markdown file <-> the editor's document (ProseMirror JSON).

This is the dialect's only implementation (spec: docs/superpowers/specs/2026-11-12-books-design.md,
"Manuscript format"); word counts, search, import, export and the editor all go through it.

Documents are ProseMirror JSON as `Node.toJSON()` writes it: `attrs` carry every attribute of the type
(null defaults written out), `content` and `marks` are left out when empty, marks on a node are in the
order of SCHEMA["marks"], and adjacent text nodes with the same marks are merged.

`serialize` writes the canonical form, which `parse` reads back unchanged:
- blocks separated by one blank line, one newline at the end, LF only;
- `*em*`, `**strong**`; span marks on the same range combine into one span with a fixed order,
  `[text]{.idx .comment .smallcaps term="…" note="…" lang=en}` (`term`/`note` always quoted, with
  \" \\ \{ \} escaped; `lang` bare when it is letters, digits and hyphens);
- notes `^[…]`, citations `[see @key, p. 12; @other]`, a hard break is a backslash at the line end
  (in poems a plain line break, stanzas separated by a blank line);
- a backslash before \ * _ [ ] ` ^ and, at a line start, before # > - + = :::, and before the . or )
  after a number; `\!` before a citation, `\{` after one; no-break spaces that start a block as an entity.
Italic or bold that CommonMark can't write (punctuation at its edge next to a letter outside, `x*(y)*z`)
is narrowed to what it can (`x(*y*)z`), or dropped; it never comes back as printed asterisks.

Poem lines are not read as Markdown blocks: inside `::: poem` there are only lines and stanzas, and a piece
whose form is poem keeps the dialect's blocks (title, `##` headings, quotations, scene breaks, `:::`
blocks) but reads lists and underlined headings as lines.
"""
import re

from markdown_it import MarkdownIt
from markdown_it.common.utils import isMdAsciiPunct, isPunctChar, isWhiteSpace
from mdit_py_plugins.attrs import attrs_plugin
from mdit_py_plugins.attrs.parse import ParseError, parse as parse_attrs
from mdit_py_plugins.colon_fence import colon_fence_plugin
from mdit_py_plugins.footnote import footnote_plugin

SCHEMA = {"nodes": ["doc", "title", "heading", "paragraph", "blockquote", "scene_break", "epigraph", "attribution",
                    "poem", "image", "page_break", "hard_break", "note", "cite", "text"],
          "marks": ["em", "strong", "idx", "comment", "smallcaps", "lang"]}

_RANK = {name: i for i, name in enumerate(SCHEMA["marks"])}
_SPAN = ("idx", "comment", "smallcaps", "lang")      # span marks, in the order they are written
_FENCES = ("epigraph", "poem", "pagebreak")


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


def _squash(s):
    return " ".join(str(s or "").split())


def _unescape(value):
    return _ESCAPED.sub(r"\1", value)


def _cite_items(body):
    """`see @a, p. 3; @b` -> [{"key", "prefix", "locator"}], or None when it isn't a citation."""
    items = []
    for part in body.split(";"):
        m = _CITE_ITEM.fullmatch(part)
        if not m:
            return None
        items.append({"key": m["bkey"] or m["key"], "prefix": _squash(m["prefix"]), "locator": _squash(m["locator"])})
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


def _cite_rule(state, silent):
    """`[@key]`, `[see @key, p. 12]`, `[@a; @b, pp. 3–5]`; runs before links and spans."""
    src, start = state.src, state.pos
    if src[start] != "[":
        return False
    end = src.find("]", start + 1, state.posMax)
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
    md.inline.ruler.before("link", "cite", _cite_rule)
    md.inline.ruler.after("image", "image_attrs", _image_attrs_rule)
    if block_only:
        md.block.ruler.enableOnly(block_only)
    md.block.ruler.disable(list(block_off))
    return md


_MD = _markdown()
# A piece whose form is poem keeps the dialect's blocks (`# ` title, `##` heading, `> ` quotation, scene break,
# `:::` blocks); Markdown outside the dialect (lists, underlined headings) stays lines of the poem.
_POEM_MD = _markdown(block_off=("lheading", "list"))
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
    if attrs.get("lang"):
        marks.append({"type": "lang", "attrs": {"lang": _unescape(attrs["lang"])}})
    return marks


def _alt(children):
    return "".join(t.content if t.type in ("text", "text_special") else " " if t.type == "softbreak" else ""
                   for t in children or [])


def _trim(run):
    """Drop spaces, tabs and line breaks at both ends (paragraph text around an image)."""
    def loose(n):
        return n["type"] == "hard_break" or (n["type"] == "text" and not n["text"].strip(" \t"))
    while run and loose(run[0]):
        run.pop(0)
    while run and loose(run[-1]):
        run.pop()
    if run and run[0]["type"] == "text":
        run[0]["text"] = run[0]["text"].lstrip(" \t")
    if run and run[-1]["type"] == "text":
        run[-1]["text"] = run[-1]["text"].rstrip(" \t")
    return run


def _paragraphs(nodes):
    """Flatten blocks into paragraphs (inside quotations, epigraphs, poems and notes)."""
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
        elif t in ("blockquote", "epigraph", "poem"):
            out.extend(_paragraphs(content))
        elif t == "image" and n["attrs"]["alt"]:
            out.append(_node("paragraph", [{"type": "text", "text": n["attrs"]["alt"]}]))
    return out


def _with_marker(nodes, marker):
    """A list item becomes paragraphs; its marker (`-`, `1.`) stays as text."""
    if nodes and nodes[0]["type"] == "paragraph":
        content = []
        _add_text(content, marker + " ", [])
        for c in nodes[0].get("content", []):
            _append(content, c)
        return [_node("paragraph", content)] + nodes[1:]
    return [_node("paragraph", [{"type": "text", "text": marker}])] + nodes


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
                inner, i = self._blocks(tokens, i + 1, t[:-5] + "_close")
                out.extend(inner)
            elif t == "list_item_open":
                inner, i = self._blocks(tokens, i + 1, "list_item_close")
                out.extend(_with_marker(inner, (tok.info or "") + tok.markup))
            elif t == "hr":
                out.append(_node("scene_break"))
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
            elif t in ("em_open", "strong_open", "span_open"):
                stack.append(_span_marks(tok.attrs) if t == "span_open" else [{"type": t[:-5]}])
                marks = _merge(stack)
            elif t in ("em_close", "strong_close", "span_close"):
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
        was, self.in_note = self.in_note, True
        try:
            label = tok.meta.get("label")
            if label is None:                       # ^[inline note]
                return self._inline(self.env["footnotes"]["list"][tok.meta["id"]]["tokens"])
            self.used.add(label)                    # [^label] with a definition elsewhere
            if label in self.expanding:
                return []
            self.expanding.add(label)
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
            self.in_note = was


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
    return _node("doc", nodes, {"form": form})


# ---------------------------------------------------------------------------------------------------------
# Document -> Markdown

_ESCAPES = str.maketrans({c: "\\" + c for c in "\\*_[]`^"})     # `^` too: `^[` opens a note
_ENTITY = re.compile(r"&(?=#[0-9]{1,7};|#[xX][0-9a-fA-F]{1,6};|[A-Za-z][A-Za-z0-9]{1,31};)")
_NUMBERED = re.compile(r"\d{1,9}(?=[.)])")
_HEADING_END = re.compile(r"(^|[ \t])(#+)$")
_BARE_LANG = re.compile(r"[A-Za-z0-9-]+")
_BARE_WIDTH = re.compile(r"[\w.%-]+")
_ORDER = {"span": 0, "strong": 1, "em": 2}          # which delimiter goes outside when runs are equally long


def _esc(s):
    s = s.translate(_ESCAPES)
    return _ENTITY.sub(r"\\&", s) if "&" in s else s


def _esc_line_start(s):
    m = _NUMBERED.match(s)
    if m:
        return s[:m.end()] + "\\" + s[m.end():]
    if s[:1] in ("#", ">", "-", "+", "=") or s.startswith(":::"):
        return "\\" + s
    return s


def _quote(value):
    value = re.sub(r"[\r\n\t]", " ", str(value))
    return '"' + re.sub(r'([\\"{}])', r"\\\1", value) + '"'


def _fmt(marks):
    """Marks -> {("em",), ("strong",), ("span", ((name, value), ...))}: all span marks of a node make one span."""
    out, span = set(), {}
    for mark in marks:
        t, attrs = mark.get("type"), mark.get("attrs") or {}
        if t in ("em", "strong"):
            out.add((t,))
        elif t == "idx":
            span["idx"] = attrs.get("term")
        elif t == "comment":
            span["comment"] = attrs.get("note") or ""
        elif t == "smallcaps":
            span["smallcaps"] = True
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
    parts = ["." + k for k in ("idx", "comment", "smallcaps") if k in d]
    if d.get("idx") is not None:
        parts.append("term=" + _quote(d["idx"]))
    if d.get("comment"):
        parts.append("note=" + _quote(d["comment"]))
    if "lang" in d:
        parts.append("lang=" + (d["lang"] if _BARE_LANG.fullmatch(d["lang"]) else _quote(d["lang"])))
    return "{" + " ".join(parts) + "}"


def _open(mark):
    return {"span": "[", "em": "*", "strong": "**"}[mark[0]]


def _close(mark):
    return "]" + _span_attrs(mark[1]) if mark[0] == "span" else _open(mark)


def _cite_md(items):
    def clean(s, drop):
        return re.sub("[" + re.escape(drop) + "]", "", _squash(s))
    parts = []
    for item in items:
        key = clean(item.get("key"), "[];{}")
        if not key:
            continue
        prefix, locator = clean(item.get("prefix"), "[];@"), clean(item.get("locator"), "[];")
        key = "@" + (key if _KEY_RE.fullmatch(key) else "{" + key + "}")
        parts.append((prefix + " " if prefix else "") + key + (", " + locator if locator else ""))
    return "[" + "; ".join(parts) + "]" if parts else ""


def _cls(c):
    """A character as CommonMark's emphasis rules see it: W(hitespace), P(unctuation) or A (anything else)."""
    code = ord(c)
    if isWhiteSpace(code):
        return "W"
    return "P" if isMdAsciiPunct(code) or isPunctChar(c) else "A"


def _class_runs(text):
    """`„ja”,` -> `„`, `ja`, `”,`: the pieces an em/strong run can be trimmed by."""
    classes = [_cls(c) for c in text]
    parts, start = [], 0
    for k in range(1, len(text) + 1):
        if k == len(text) or classes[k] != classes[start]:
            parts.append(text[start:k])
            start = k
    return parts


def _items(nodes, heading, edges, single_breaks):
    """Inline nodes -> (kind, value, marks), kind text, br, note or cite. Italic and bold text is split into
    runs of letters, punctuation and spaces, so a run's edges can be trimmed (see `_layout`).
    `edges`: drop what Markdown drops at the edges of a block (line breaks; spaces at the start, any
    whitespace at the end); `single_breaks`: no empty lines (in a poem's notes they would end the stanza)."""
    items = []
    for n in nodes:
        t, fmt = n.get("type"), _fmt(n.get("marks") or [])
        if t == "text":
            text = re.sub(r"[\r\n]", " ", n.get("text") or "")
            if text and (("em",) in fmt or ("strong",) in fmt):
                items += [("text", part, fmt) for part in _class_runs(text)]
            elif text:
                items.append(("text", text, fmt))
        elif t == "hard_break":
            items.append(("text", " ", fmt) if heading else ("br", "", fmt))
        elif t == "note":
            items.append(("note", n.get("content") or [], fmt))
        elif t == "cite":
            items.append(("cite", (n.get("attrs") or {}).get("items") or [], fmt))
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
        while items and (items[-1][0] == "br" or blank(items[-1], None)):
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
    """Give each em/strong run an identity and decide where it starts and ends.

    A run is cut where a span would straddle it, so a span lies strictly inside the run or the run inside
    the span (`*a [b]{.idx} c*`, `[*a*]{.idx} *b*`). At its edges a run sheds spaces, line breaks, notes
    and citations (the mark means nothing on them, and asterisks must touch text), and punctuation that
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
        return "W" if kind == "br" else "P"        # a note or citation is written with brackets

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

    for name in ("em", "strong"):
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
    """Close a mark. Spaces, line breaks, notes and citations at the end of an em/strong run that has to
    close early (another run crosses it) move outside, since asterisks must touch text: with `*a ` open
    and `b` arriving without italics, `*`, `a ` becomes `*`, `a`, `*`, ` `."""
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
        elif kind in ("br", "note", "cite"):
            tail.insert(0, out.pop())
        else:
            break
    out.append(("mark", _close(mark)))
    out.extend(tail)


def _emit(items, ends, lines, start, heading):
    """Write laid-out items. Text is escaped a whole run at a time (between two marks), so splitting an item
    never hides `1.` or `&amp;` from the escapes. Worked example (prose, `start`): `1. ` + `nee`(em) + ` !`
    + citation + `{x}` gives `1\\. *nee* \\![@a]\\{x}`: the number's dot is escaped at the line start, the `!`
    before a citation would make it an image, and `{` after one would make it a span."""
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
            # spaces, breaks, notes and citations don't open em/strong; they only stay inside an open run
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
        else:
            out.append(("cite", _cite_md(val)))
            at_start = False
    flush()
    while stack:
        _close_into(out, *stack.pop())
    for k in range(1, len(out)):            # after the moves above: what touches a citation
        if out[k][0] == "cite" and out[k - 1][0] == "text" and out[k - 1][1].endswith("!"):
            out[k - 1] = ("text", out[k - 1][1][:-1] + "\\!")     # `![@a](x)` would be an image
        if out[k - 1][0] == "cite" and out[k][0] == "text" and out[k][1].startswith("{"):
            out[k] = ("text", "\\" + out[k][1])                   # `[@a]{.idx}` would be a span
    return "".join(s for _, s in out)


def _units(nodes_or_items, from_items):
    """The visible text with its marks, one unit per non-space character (and per note or citation), to check
    that Markdown reads back as meant; for items, also which em/strong runs cover each unit."""
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
    return units


def _misread(md, items, lines, heading, note):
    """None when `md` reads back as `items` mean; otherwise the em/strong run to give up (the shortest one at
    the first difference). Italic or bold Markdown can't write must never come back as printed asterisks."""
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
    return min(near, key=lambda r: (sizes[r], r))


def _inline_md(nodes, lines, start, heading=False, note=False):
    """Inline nodes -> Markdown. `start`: the text begins a line; `lines`: a hard break is a plain newline.
    Lays the marks out, writes them, and reads the result back: a run Markdown can't write is dropped and the
    text written again (`x` + `…`(em) + `y` gives `x…y`)."""
    items, ends = _layout(_items(nodes, heading, not note, lines))
    while True:
        md = _emit(items, ends, lines, start, heading)
        bad = _misread(md, items, lines, heading, note)
        if bad is None:
            return md if note else md.rstrip()      # a block's trailing whitespace is gone in Markdown anyway
        items = [(kind, val, fmt - {bad}) for kind, val, fmt in items]


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
    else:
        raise ValueError(f"unknown block: {t!r}")
    return "\n".join(line.rstrip(" \t") for line in out.split("\n"))


def serialize(doc: dict, form: str | None = None) -> str:
    """The editor's document -> canonical Markdown. `form` defaults to the document's own (`attrs.form`)."""
    form = form or (doc.get("attrs") or {}).get("form") or "prose"
    blocks = [b for b in (_block(n, form == "poem") for n in doc.get("content") or []) if b]
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
    if t in ("blockquote", "epigraph", "poem"):
        for c in node.get("content") or []:
            _block_text(c, out)
    elif t in ("title", "heading", "paragraph", "attribution"):
        out.append(_text_of(node.get("content") or []))


def plain_text(doc: dict) -> str:
    """The body text: blocks separated by a blank line; no notes, comment notes, citations or captions."""
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
