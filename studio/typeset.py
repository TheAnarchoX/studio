r"""Typesetting: a piece's document (ProseMirror JSON from `manuscript.parse`) as Typst source.

Spec: docs/superpowers/specs/2026-11-13-books-part-2-design.md ("Page rules", "Generated pages", "Citations"). The
source written here calls the functions of the book's Typst template (`#piece-start`, `#piece-title`, `#poem`, ...):
this module says what is on the page, the template decides how it looks.

The author's text never reaches Typst as code. Every string from a piece (or from book.json) goes in through `lit`,
as a Typst string literal: `#"…"` in markup, a plain literal among a call's arguments. Everything outside literals is
written here: calls, markers and labels, whose names come from indices only. A literal in markup is always followed
by `#`, `]` or a line break, never by `(`, `[` or `.`, which Typst would read as a call or a field access.

Markers, invisible on the page and read back with queries after a compile:
  `#metadata((p: i, b: k))<blk>`     before top-level block k of piece i (which page each block is on)
  `#metadata((p: i, b: k))<blkend>`  after a paragraph's last inline node (widows and orphans)
  `#metadata((t: key))<idx>`         after the text of an index mark (the index's page numbers)
  `<noteref-i-n>`                     on the reference of endnote n of piece i; the notes page labels the note
                                      itself `<note-i-n>`

Mapping:
  title -> #piece-title(i)[…] (the first one; a later one is a section)   heading -> #section(2 | 3)[…]
  paragraph -> its inline content; in a poem piece consecutive paragraphs are the stanzas of one #poem
  blockquote -> #quote(block: true)[…]   scene_break -> #scene-break()   page_break -> #pagebreak(weak: true)
  epigraph -> #epigraph(([para], …), [attribution] | none)
  poem -> #poem((([line], …), …)): stanzas of lines; a linked poem's lines come from `Context.linked`
  image -> #image-block("path", 60%, [caption] | none), or #missing-image([caption] | none) when it isn't staged
  list_item -> #list-item(level, "marker")[…]   aligned -> #aligned("center" | "right")[…]
  table -> #book-table(header, (auto | left | center | right, …), (([cell], …), …))
  math -> #math-tex("tex")   math_display -> #math-tex-block("tex"): the TeX source, until a converter comes
  em, strong, smallcaps, underline, strike -> #emph[…], #strong[…], #smallcaps[…], #underline[…], #strike[…]
  lang -> #text(lang: "en", region: "GB")[…]   size -> #text(size: 1.2em)[…]   idx -> its text, then a marker
  comment -> its text only   hard_break -> #linebreak()   cite -> the citation as text
  note -> per `Context.notes`: #footnote[…], #note-ref(i, n)<noteref-i-n> with the body collected, or nothing
Any other node prints its text as a paragraph; any other mark is left out.
"""
import importlib
import re
from dataclasses import dataclass, field
from typing import Callable

from . import citations, config

# The sentence the writing window and the .docx export show for a linked poem that has gone from the Poems library.
MISSING_POEM = "This poem is no longer in your Poems library."

_LIT = {c: None for c in range(32)}                 # C0 controls have no place in a book: dropped
_LIT.update({ord("\\"): "\\\\", ord('"'): '\\"', ord("\n"): "\\n", ord("\t"): "\\t"})
_SURROGATE = re.compile("[\ud800-\udfff]")          # a lone surrogate can't be written as UTF-8 at all


def lit(s) -> str:
    """`s` as a Typst string literal. Typst's escapes are not JSON's (`\\u{41}`, not `\\u0041`), so this writes only
    the four it needs and keeps every other character as itself: `„Één”` stays readable in the source."""
    s = str(s)
    if not s.isascii():
        s = _SURROGATE.sub("", s)
    return '"' + s.translate(_LIT) + '"'


def _squash(s) -> str:
    return " ".join(str(s or "").split())


def split_term(term: str) -> tuple[str, str]:
    """An index term and its subentry: `trauma > jeugd` -> ("trauma", "jeugd"); without `>` the subentry is ""."""
    head, sep, sub = str(term or "").partition(">")
    return (_squash(head), _squash(sub)) if sep else (_squash(head), "")


def _no_linked_poems(src) -> dict:
    return {"missing": True}


@dataclass
class Context:
    """What setting a piece needs from the book, and what it collects for the pages set after the pieces.

    `images` maps an image's `src` as the manuscript writes it to its staged copy, relative to the compiler's root; a
    `src` that isn't there (missing, unreadable, outside the book's images/) is shown as missing. `linked` is
    `Books.linked_poem`. The collectors fill while pieces are set: `endnotes` ({"piece", "n", "body"}, `body` being
    Typst markup to set inside `[...]`), index `terms` ((term, subentry) -> marker key), `first_lines` of poem pieces
    ((text, piece)), `cited` source keys in order, `missing_images` ((piece, src)), `chars` (every character printed
    in the text's font, for the font check), `math` (how many formulas print as TeX source)."""
    design: dict = field(default_factory=dict)
    lang: str = "en"
    sources: list = field(default_factory=list)
    notes: str = "footnotes"            # off, footnotes, endnotes, both
    numbering: str = "chapter"          # chapter: notes count from 1 in every piece; book: on through the book
    images: dict = field(default_factory=dict)
    linked: Callable = _no_linked_poems
    endnotes: list = field(default_factory=list)
    terms: dict = field(default_factory=dict)
    first_lines: list = field(default_factory=list)
    cited: list = field(default_factory=list)
    missing_images: list = field(default_factory=list)
    chars: set = field(default_factory=set)
    note_counter: int = 0
    math: int = 0


def piece(i: int, entry: dict, doc: dict, ctx: Context) -> str:
    """The Typst source of piece `i` (its index in the book's contents): `#piece-start`, its blocks, `#piece-end`."""
    return _Piece(i, entry, doc, ctx).source()


# ---------------------------------------------------------------------------------------------------------
# Inline content

_WRAP = {"em": "#emph[", "strong": "#strong[", "smallcaps": "#smallcaps[", "underline": "#underline[",
         "strike": "#strike["}
_SIZES = {"x-small": "0.75em", "small": "0.875em", "large": "1.2em", "x-large": "1.44em"}
# Marks that open together on the same text nest in this order (the dialect's order), outermost first.
_RANK = {name: k for k, name in enumerate(("em", "strong", "idx", "comment", "smallcaps", "lang", "underline",
                                           "strike", "size"))}
_INLINE = ("text", "hard_break", "note", "cite", "math", "image")
_IDX_MARKER = re.compile(r'#metadata\(\(t: "t\d+"\)\)<idx>')       # can't occur inside a literal: `"` is escaped there
_OPENING_STOP = re.compile("[,.;:—]")
_WORD = re.compile(r"\S+")
_PERCENT = re.compile(r"\s*(\d{1,3}(?:\.\d{1,4})?)\s*%\s*")
_ALIGNS = ("left", "center", "right")


def _language(value):
    """`nl` -> ("nl", None), `en-GB` -> ("en", "GB"): Typst takes the language and the region apart. None for what
    isn't a language code, so a stray value can't stop the book from setting."""
    if not isinstance(value, str) or not config.LANGUAGE_TAG.fullmatch(value.strip()):
        return None
    parts = value.strip().split("-")
    region = next((p.upper() for p in parts[1:] if len(p) == 2 and p.isalpha()), None)
    return parts[0].lower(), region


def _set_marks(node):
    """The marks of an inline node that change how it is set; a comment, an unknown mark or a bad value sets nothing."""
    out = []
    for m in node.get("marks") or []:
        if not isinstance(m, dict):
            continue
        t, attrs = m.get("type"), m.get("attrs") or {}
        if (t in _WRAP or t == "idx" or (t == "lang" and _language(attrs.get("lang")))
                or (t == "size" and attrs.get("size") in _SIZES)):
            out.append(m)
    return out


def _flat(nodes):
    """Inline nodes as the setter knows them. Anything else gives its text: the content of an unknown node (a space
    between its blocks), or its `text`."""
    out = []
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        if n.get("type") in _INLINE:
            out.append(n)
        elif isinstance(n.get("content"), list):
            inner = _flat(n["content"])
            if inner and out:
                out.append({"type": "text", "text": " "})
            out.extend(inner)
        elif isinstance(n.get("text"), str):
            out.append({"type": "text", "text": n["text"], "marks": n.get("marks") or []})
    return out


def _plain(nodes) -> str:
    """The words of inline nodes, a formula as its TeX source between dollars, as it was written (a first line, a
    contents title): until a converter comes, the pages show a formula as its source too."""
    def words(n):
        if n.get("type") == "text":
            return n.get("text") or ""
        return f"${(n.get('attrs') or {}).get('tex') or ''}$" if n.get("type") == "math" else ""
    return _squash("".join(words(n) for n in _flat(nodes)))


def _array(items) -> str:
    """A Typst array: `(a, b)`, and `(a,)` for one item, which would otherwise be just `a` in parentheses."""
    items = list(items)
    return "(" + ", ".join(items) + ("," if len(items) == 1 else "") + ")"


def _width(value) -> str:
    """An image's width as a share of the measure: `60%` as written; anything else (or more than the measure) 100%."""
    m = _PERCENT.fullmatch(str(value)) if value is not None else None
    v = float(m[1]) if m else 0
    return f"{v:g}%" if 0 < v <= 100 else "100%"


def _stanzas(nodes):
    """A poem paragraph's inline nodes -> stanzas of lines (lists of nodes): a hard break ends a line, an empty line
    (spaces and tabs only) ends a stanza, as in the dialect."""
    stanzas, lines, line = [], [], []
    for n in _flat(nodes) + [None]:
        if n is not None and n.get("type") != "hard_break":
            line.append(n)
            continue
        if all(x.get("type") == "text" and not (x.get("text") or "").strip(" \t") for x in line):
            if lines:
                stanzas.append(lines)
                lines = []
        else:
            lines.append(line)
        line = []
    return stanzas + ([lines] if lines else [])


def _linked_stanzas(lines):
    """A Poems-library poem's lines -> stanzas: blank lines split them."""
    stanzas, stanza = [], []
    for line in list(lines or []) + [""]:
        line = str(line).rstrip()
        if line.strip():
            stanza.append(line)
        elif stanza:
            stanzas.append(stanza)
            stanza = []
    return stanzas


def _fallback_markers(blocks):
    """List markers when `manuscript_lists` (the writing window's lists) isn't installed: `•` for bullets, numbers
    counted per level and style (`1.`, `2.`); any other block ends every list."""
    out, open_ = [], {}         # level -> (style, n)
    for b in blocks:
        if b.get("type") != "list_item":
            open_ = {}
            out.append(None)
            continue
        attrs = b.get("attrs") or {}
        style, level, start = attrs.get("list"), attrs.get("level"), attrs.get("start")
        level = min(max(level if type(level) is int else 0, 0), 3)
        open_ = {lv: v for lv, v in open_.items() if lv <= level}
        same = open_.get(level)
        n = same[1] + 1 if same and same[0] == style else (start if type(start) is int and start > 1 else 1)
        open_[level] = (style, n)
        out.append({"marker": "•" if style == "bullet" else f"{n}.", "level": level})
    return out


def _list_markers(blocks):
    """Per top-level block, what a list item shows, from the writing window's own rule (`manuscript_lists`, which
    arrives with the lists of the book-editor-power work) so the page and the editor agree; the fallback until then."""
    try:
        lists = importlib.import_module(__package__ + ".manuscript_lists")
    except ModuleNotFoundError as e:
        if e.name != __package__ + ".manuscript_lists":
            raise
        return _fallback_markers(blocks)
    return lists.markers(blocks)


# ---------------------------------------------------------------------------------------------------------
# A piece

class _Piece:
    """One piece being set: its blocks in order, the collectors in `ctx` filled on the way."""

    def __init__(self, i, entry, doc, ctx):
        self.i, self.ctx = int(i), ctx
        self.entry = entry if isinstance(entry, dict) else {}
        doc = doc if isinstance(doc, dict) else {}
        self.content = [b if isinstance(b, dict) else {} for b in doc.get("content") or []]
        form = (doc.get("attrs") or {}).get("form") or self.entry.get("form")
        self.poem_piece = form == "poem"
        self.design = ctx.design if isinstance(ctx.design, dict) else {}
        self.first_line_due = self.poem_piece
        self.markers = None

    # ——— strings ———
    def _s(self, s) -> str:
        """A literal argument whose text is printed: its characters go to the font check."""
        s = str(s)
        self.ctx.chars.update(c for c in s if c >= " " and not "\ud800" <= c <= "\udfff")
        return lit(s)

    def _t(self, s) -> str:
        """Printed text in markup."""
        return "#" + self._s(s) if s else ""

    def _blk(self, k, end=False) -> str:
        return f"#metadata((p: {self.i}, b: {k}))<{'blkend' if end else 'blk'}>"

    # ——— the piece ———
    def source(self) -> str:
        ctx, i = self.ctx, self.i
        if ctx.numbering != "book":
            ctx.note_counter = 0
        out = [f"#piece-start({i}, {lit(self.entry.get('kind') or '')})"]
        titled = opening = False
        run = []            # (k, stanzas) of the paragraphs of a poem piece waiting to be set as one poem
        for k, n in enumerate(self.content):
            t = n.get("type")
            stanzas = _stanzas(n.get("content")) if self.poem_piece and t == "paragraph" else None
            if stanzas:
                run.append((k, stanzas))
                continue
            if run:
                out.append(self._stanza_run(run))
                run = []
            blk = self._blk(k)
            if t == "title" and not titled:
                titled = True
                opening = (self.design.get("headings") or {}).get("opening") == "smallcaps"
                out.append(f"{blk}#piece-title({i})[{self._inline(n.get('content'))}]")
            elif t == "paragraph":
                nodes = n.get("content")
                if opening:
                    nodes, opening = self._opening(nodes), False
                out.append(blk + self._inline(nodes) + self._blk(k, end=True))
            elif t == "list_item":
                out.append(blk + self._list_item(k, n))
            elif t in ("title", "heading", "blockquote", "aligned", "epigraph", "poem", "scene_break", "page_break",
                       "image", "table", "math_display"):
                out.append(blk + self._block(n, top=True))
            else:                               # a node this version doesn't know: its text, as a paragraph
                out.append(blk + self._inline([n]) + self._blk(k, end=True))
        if run:
            out.append(self._stanza_run(run))
        out.append(f"#piece-end({i})")
        return "\n\n".join(out) + "\n"

    def _blocks(self, nodes) -> str:
        """Blocks inside a container (a quotation, aligned text): no markers, paragraphs apart."""
        return "\n\n".join(s for s in (self._block(n) for n in nodes or [] if isinstance(n, dict)) if s)

    def _block(self, n, top=False) -> str:
        t, content, attrs = n.get("type"), n.get("content"), n.get("attrs") or {}
        if t == "paragraph":
            return self._inline(content)
        if t in ("title", "heading"):
            level = attrs.get("level") if t == "heading" and type(attrs.get("level")) is int else 2
            return f"#section({min(max(level, 2), 3)})[{self._inline(content)}]"
        if t == "blockquote":
            return f"#quote(block: true)[{self._blocks(content)}]"
        if t == "aligned":
            inner = self._blocks(content)
            align = attrs.get("align")
            return f"#aligned({lit(align)})[{inner}]" if align in ("center", "right") else inner
        if t == "epigraph":
            return self._epigraph(content)
        if t == "poem":
            return self._poem(n)
        if t == "scene_break":
            return "#scene-break()"
        if t == "page_break":
            return "#pagebreak(weak: true)" if top else ""     # Typst allows page breaks only at the top level
        if t == "image":
            return self._image(attrs)
        if t == "table":
            return self._table(n)
        if t == "math_display":
            return self._math(attrs, block=True)
        if t == "list_item":
            return f"#list-item(0, {self._s('•')})[{self._inline(content)}]"
        return self._inline([n])

    def _opening(self, nodes):
        """The chapter's opening words in small capitals: in its first text node, up to the first `,` `.` `;` `:`
        `—` or the end of the fifth word."""
        nodes = list(nodes or [])
        first = nodes[0] if nodes and isinstance(nodes[0], dict) else {}
        s = (first.get("text") or "") if first.get("type") == "text" else ""
        stop = _OPENING_STOP.search(s)
        cut = stop.start() if stop else len(s)
        words = list(_WORD.finditer(s))
        if len(words) >= 5:
            cut = min(cut, words[4].end())
        lead = s[:cut].rstrip()
        if not lead.strip():
            return nodes
        marks = [m for m in first.get("marks") or [] if isinstance(m, dict)]
        if not any(m.get("type") == "smallcaps" for m in marks):
            marks.append({"type": "smallcaps"})
        rest = s[len(lead):]
        return [dict(first, text=lead, marks=marks)] + ([dict(first, text=rest)] if rest else []) + nodes[1:]

    # ——— inline ———
    def _inline(self, nodes) -> str:
        """Inline nodes as markup. Marks become nested calls: a run of nodes that share a mark shares one call, and
        where marks start together the one that reaches further goes outside, so an index mark around partly
        italic text still gives one marker."""
        nodes = _flat(nodes)
        marks = [_set_marks(n) for n in nodes]
        out, stack = [], []         # stack: [mark, the text it holds so far (for an index term)]

        def reach(j, m):
            k = j
            while k < len(nodes) and m in marks[k]:
                k += 1
            return k - j

        for j, n in enumerate(nodes):
            want = marks[j]
            keep = 0
            while keep < len(stack) and stack[keep][0] in want:
                keep += 1
            while len(stack) > keep:
                out.append(self._close(*stack.pop()))
            held = [s[0] for s in stack]
            for m in sorted((m for m in want if m not in held),
                            key=lambda m: (-reach(j, m), _RANK.get(m.get("type"), len(_RANK)))):
                out.append(self._open(m))
                stack.append((m, []))
            t = n.get("type")
            if t == "text":
                s = n.get("text") or ""
                for _, held_text in stack:
                    held_text.append(s)
                out.append(self._t(s))
            elif t == "hard_break":
                out.append("#linebreak()")
            elif t == "note":
                out.append(self._note(n))
            elif t == "cite":
                out.append(self._cite(n))
            elif t == "math":
                out.append(self._math(n.get("attrs") or {}))
            elif t == "image":                  # an image inside text (a hand-made document): its description
                out.append(self._t(_squash((n.get("attrs") or {}).get("alt"))))
        while stack:
            out.append(self._close(*stack.pop()))
        return "".join(out)

    def _open(self, m) -> str:
        t, attrs = m.get("type"), m.get("attrs") or {}
        if t in _WRAP:
            return _WRAP[t]
        if t == "lang":
            lang, region = _language(attrs.get("lang"))
            return f"#text(lang: {lit(lang)}" + (f", region: {lit(region)}" if region else "") + ")["
        if t == "size":
            return f"#text(size: {_SIZES[attrs['size']]})["
        return ""                                   # idx: no call, a marker at its end

    def _close(self, m, held) -> str:
        if m.get("type") != "idx":
            return "]"
        term = (m.get("attrs") or {}).get("term")
        term, sub = split_term(term) if isinstance(term, str) and term.strip() else (_squash("".join(held)), "")
        if not term:
            term, sub = sub, ""
        if not term:
            return ""
        key = self.ctx.terms.get((term, sub))
        if key is None:
            key = self.ctx.terms[(term, sub)] = f"t{len(self.ctx.terms)}"
        return f"#metadata((t: {lit(key)}))<idx>"

    def _note(self, n) -> str:
        """A note per the book's notes setting. With `both` the footnote is the reference the notes page links back
        to, and its index markers stay with the footnote only, so a term isn't indexed twice."""
        mode = self.ctx.notes
        if mode not in ("footnotes", "endnotes", "both"):
            return ""
        body = self._inline(n.get("content"))
        self.ctx.note_counter += 1
        num, i = self.ctx.note_counter, self.i
        label = f"<noteref-{i}-{num}>"
        if mode != "footnotes":
            self.ctx.endnotes.append({"piece": i, "n": num, "body": _IDX_MARKER.sub("", body) if mode == "both"
                                      else body})
        if mode == "endnotes":
            return f"#note-ref({i}, {num}){label}"
        return f"#footnote[{body}]" + (label if mode == "both" else "")

    def _cite(self, n) -> str:
        items = [it for it in (n.get("attrs") or {}).get("items") or [] if isinstance(it, dict)]
        if not items:
            return ""
        for it in items:
            key = str(it.get("key") or "")
            if key and key not in self.ctx.cited:
                self.ctx.cited.append(key)
        style = (self.design.get("citations") or {}).get("style") or "chicago"
        return self._t(citations.cite_text(items, self.ctx.sources, style, self.ctx.lang))

    def _math(self, attrs, block=False) -> str:
        """TeX source, set in a monospace face by the template (so its characters aren't the text font's to cover)."""
        self.ctx.math += 1
        return f"#math-tex{'-block' if block else ''}({lit(attrs.get('tex') or '')})"

    # ——— blocks ———
    def _epigraph(self, content) -> str:
        paras, attribution = [], None
        for c in content or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "attribution":
                attribution = c
            else:
                paras.append(f"[{self._block(c)}]")
        by = f"[{self._inline(attribution.get('content'))}]" if attribution and attribution.get("content") else "none"
        return f"#epigraph({_array(paras)}, {by})"

    def _first_line(self, text):
        if self.first_line_due and text:
            self.ctx.first_lines.append((text, self.i))
            self.first_line_due = False

    def _poem_call(self, stanzas) -> str:
        return "#poem(" + _array(_array(f"[{line}]" for line in stanza) for stanza in stanzas) + ")"

    def _poem(self, n) -> str:
        src = (n.get("attrs") or {}).get("src")
        if src:
            poem = self.ctx.linked(src)
            if not isinstance(poem, dict) or poem.get("missing"):
                return self._t(MISSING_POEM)
            stanzas = _linked_stanzas(poem.get("lines"))
            if stanzas:
                self._first_line(_squash(stanzas[0][0]))
            return self._poem_call([[self._t(line) for line in stanza] for stanza in stanzas]) if stanzas else ""
        stanzas = [s for c in n.get("content") or [] for s in _stanzas([c])]
        for stanza in stanzas:
            for line in stanza:
                if not self.first_line_due:
                    break
                self._first_line(_plain(line))
        return self._poem_call([[self._inline(line) for line in stanza] for stanza in stanzas]) if stanzas else ""

    def _stanza_run(self, run) -> str:
        """The paragraphs of a poem piece, one poem: each paragraph's markers inside its first and last line, so they
        travel with the stanza when it moves to the next page."""
        out = []
        for k, stanzas in run:
            for line in (x for stanza in stanzas for x in stanza):
                if not self.first_line_due:
                    break
                self._first_line(_plain(line))
            lines = [[self._inline(line) for line in stanza] for stanza in stanzas]
            lines[0][0] = self._blk(k) + lines[0][0]
            lines[-1][-1] += self._blk(k, end=True)
            out.extend(lines)
        return self._poem_call(out)

    def _image(self, attrs) -> str:
        src, alt = str(attrs.get("src") or ""), _squash(attrs.get("alt"))
        caption = f"[{self._t(alt)}]" if alt else "none"
        path = self.ctx.images.get(src) if src and isinstance(self.ctx.images, dict) else None
        if not path:
            self.ctx.missing_images.append((self.i, src))
            return f"#missing-image({caption})"
        return f"#image-block({lit(path)}, {_width(attrs.get('width'))}, {caption})"

    def _list_item(self, k, n) -> str:
        if self.markers is None:
            self.markers = _list_markers(self.content)
        m = self.markers[k] if k < len(self.markers) and isinstance(self.markers[k], dict) else {}
        attrs = n.get("attrs") or {}
        level = m.get("level", attrs.get("level"))
        level = min(max(level if type(level) is int else 0, 0), 3)
        marker = str(m.get("marker") or ("•" if attrs.get("list") == "bullet" else "1."))
        return f"#list-item({level}, {self._s(marker)})[{self._inline(n.get('content'))}]"

    def _table(self, n) -> str:
        attrs = n.get("attrs") or {}
        rows = [[self._inline(cell.get("content")) for cell in row.get("content") or [] if isinstance(cell, dict)]
                for row in n.get("content") or [] if isinstance(row, dict)]
        rows = [r for r in rows if r]
        cols = max((len(r) for r in rows), default=0)
        if not cols:
            return ""
        given = attrs.get("align") if isinstance(attrs.get("align"), list) else []
        aligns = [a if a in _ALIGNS else "auto" for a in (given + [None] * cols)[:cols]]
        header = "false" if attrs.get("header") is False else "true"
        cells = [_array(f"[{c}]" for c in r + [""] * (cols - len(r))) for r in rows]
        return f"#book-table({header}, {_array(aligns)}, {_array(cells)})"
