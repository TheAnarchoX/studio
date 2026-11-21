# The writing window, more powerful — design

*13 November 2026. Written from the author's request without them at hand, so every open question is answered here
as a ruling, each with what it costs if it turns out wrong. Builds on part 1 (`2026-11-12-books-design.md`,
"Manuscript format" and "Studio interface"), alongside parts 2–4.*

## Why

The author asked for the common tools of a writing program, lists and inline text sizes among them, chosen and shaped
for writing rather than taken over whole: a much more capable editor that stays as calm as it is now, and leaves the
writer in charge.

A test piece showed list markers (`1.`, `2.`, `a.`, `b.`, `I.`) typed on lines of their own and `LEFT CENTER RIGHT`
staying plain text: today the dialect has no lists (a list in Markdown is read as paragraphs that keep their marker
as text, and `1.` at a line start is escaped), no alignment, and no sizes. Google Docs' toolbar and Format menu are
the reference for the common tools.

So: the common tools a book's text needs, chosen for a book rather than copied from a word processor; each reachable
by typing, by a key, by a quiet panel and by the Ctrl+K palette; each stored in the Markdown dialect so that the
files stay plain, Pandoc-readable text.

## Goals, non-goals, anti-goals

**Goals**
- Real lists — bulleted, numbered, lettered (a., A.), roman (i., I.) — nested up to four levels, with Tab and
  Shift+Tab, made by typing `- `, `1. `, `a. `, `I. ` at the start of a paragraph, each undone by one Backspace.
- Centred and right-aligned paragraphs.
- Inline text sizes as four steps around the body size, not points.
- Underline, strikethrough and small caps (small caps exists in the dialect but had no control).
- Clear formatting.
- A format panel (Alt+O, and *Format* in the selection bar) that shows what applies at the cursor and the state it
  is in, with every key shown; the selection bar shows only what fits the selection; the Ctrl+K palette knows every
  command.
- Lists for typing-first writers too: `/` offers bulleted and numbered lists.
- Every new element round-trips through the dialect and works in word counts, find and replace, .docx export and
  .docx import, and in parts 2–4.

- Tables (added by the author later that night): Pandoc pipe tables in the dialect, a calm table editor, real .docx
  tables both ways.
- LaTeX math (likewise): `$…$` and `$$…$$`, rendered while writing and edited as source on click, with a vendored
  renderer.
- After those, three extras the author asked for (see "Later"): a corkboard of the pieces, every key in one sheet,
  and "Make a design from this passage".

**Non-goals** (each is a ruling below): fonts, colours, line and paragraph spacing, columns, headers, footers and page
numbers in the text; merged table cells and multi-line cells; raw LaTeX blocks and a LaTeX export; superscript and
subscript; links; checklists; free indentation; per-paragraph justification.

**Anti-goals** — what would make this a failure even if it worked:
- A toolbar. The text column keeps no toolbar; nothing appears uninvited.
- Formatting that the book's design can't honour, or that a writer has to undo in every chapter (colours, fonts,
  point sizes).
- A shortcut that eats a character: a typing shortcut that fires where the author meant text, without one Backspace
  to take it back.
- A list that looks right in the editor and comes back different after a reload.

## How it gets built — approaches

**Lists in the document.**
1. *Nested lists, ProseMirror's usual model* (`bullet_list > list_item > paragraph`): maps 1:1 to Markdown nesting;
   needs `prosemirror-schema-list`, which isn't in the vendored bundle (a rebuild, and a merge risk with siblings
   who might rebuild it too); its editing commands are known to feel stiff (lifting, joining).
2. **Flat list items (chosen):** a list item is a top-level text block with its list style and level as attributes,
   like a paragraph that knows it is item 2 of a numbered list. Tab and Shift+Tab change one attribute. This is how
   Word and Google Docs model lists, so .docx export and import map directly; the composer can nest them or not. The
   cost: an item holds one paragraph (Shift+Enter for a line break inside it), and an item can't hold a quotation or
   a poem; hand-written Markdown with such items keeps the extra blocks, between the items.
3. *Lists as paragraphs with a marker attribute:* every paragraph gets an attribute, so every paragraph's JSON
   changes (`"attrs": {"list": null}`), across parts 2–4 and every test; rejected for the ripple.

**Alignment.**
1. *An `align` attribute on paragraphs:* the same ripple as 3 above.
2. **A container, like the epigraph (chosen):** `aligned` holds paragraphs and is written as a fenced div,
   `::: center` … `:::`, exactly as Pandoc writes a div. Paragraphs stay as they are.

**Sizes, underline, strikethrough.** Marks, written as Pandoc spans (`[text]{.underline}`, `[text]{.large}`) or
Pandoc's strikeout (`~~text~~`), so the span machinery the dialect already has carries them.

**Where the code goes.** A new `book-format.js` (and `book-format.css`) holds the commands, typing rules, keys,
list markers, the format panel and the palette's format actions; the shared files get a few lines each that call
it, as `book-text.js` already does for `book-tools.js`. On the server a new `studio/manuscript_lists.py` holds the
list block rule and the list markers, so `manuscript.py`'s own diff stays small.

## The tools, curated

Google Docs' toolbar and Format menu, item by item: what a book's text gets, and where the rest lives.

| Docs | Ruling | Lives in |
|---|---|---|
| Normal text, Title, Headings | Paragraph, Heading (`##`), Subheading (`###`), Quotation; the title stays the piece's first line | the text |
| Font | The book's look | Styles, composer (part 2) |
| Font size in points | Four steps — extra small, small, large, extra large — written as classes; the composer turns them into points | the text (step), composer (points) |
| Bold, italic | As now | the text |
| Underline | Yes: letters, documents and signs quoted in a memoir use it, and .docx from Docs carries it | the text |
| Strikethrough | Yes: crossed-out words are a device in memoir and poetry | the text |
| Superscript, subscript | No | — |
| Text colour | No: a book's text is one colour | the look |
| Highlight | That is what a comment is in a manuscript | the text (comments) |
| Align left/centre/right | Centre and right per paragraph; "as the book" for the rest | the text |
| Justify, default alignment | The book's design decides | composer |
| Indent | Lists (levels) and quotations; no free indents | the text |
| First-line indent | The book's design | composer |
| Line and paragraph spacing | The book's design | composer |
| Columns | The book's design; not in part 2's outline, so a later design option | composer, later |
| Bullets and numbering | Real lists | the text |
| Headers and footers, page numbers | Running heads and feet | composer (part 2) |
| Page orientation, pageless | Trim size | composer (part 2) |
| Table | Yes, simple tables (pipe tables) | the text |
| Equation | LaTeX math, inline and display | the text |
| Image | As now (`/` → Image) | the text |
| Borders and lines | The scene break is the line a book has | the text |
| Clear formatting | Yes | the text |
| Link, checklist, paint format, capitalisation | No | — |

Rulings, with what each costs if wrong:

- **Ruling: no superscript or subscript** — *cost if wrong:* `m²` and ordinals are typed with their Unicode
  characters until a later round adds `^x^` and `~x~`; nothing in the files would need to change.
- **Ruling: no text colour; highlight is a comment** — *cost if wrong:* an author who wants a highlight without a note
  gets an empty margin comment, which is also how they'd find it again.
- **Ruling: no free indentation; "indent" means a list level or a quotation** — *cost if wrong:* an indented passage
  that isn't a quotation is written as one anyway; in print the two look the same.
- **Ruling: alignment is centre or right, for paragraphs only** (not headings, list items, poems or epigraphs, whose
  alignment is the design's) — *cost if wrong:* a centred heading or stanza needs a later round; the dialect's fence
  can hold them without a format change.
- **Ruling: no links** — the dialect leaves links out on purpose (part 1) — *cost if wrong:* a URL stays text, which
  is what print shows anyway.

## The dialect: new elements

| Element | Markdown | Document |
|---|---|---|
| Bulleted list | `- item` (`*` and `+` read too) | `list_item {list: "bullet", level, start: null}` |
| Numbered list | `1. item`; a list starting elsewhere writes its first number (`3. item`) | `list: "decimal"`, `start` 3 |
| Lettered list | `a. item`; capitals with two spaces, `A.  item` (Pandoc) | `"lower-alpha"`, `"upper-alpha"` |
| Roman list | `i. item`; capitals with two spaces, `I.  item` | `"lower-roman"`, `"upper-roman"` |
| Nested item | indented to the parent item's text | `level` 1–3 |
| Centred, right-aligned | `::: center` … `:::`, `::: right` … `:::` around paragraphs | `aligned {align: "center" \| "right"}`, content `paragraph+` |
| Underline | `[text]{.underline}` | mark `underline` |
| Strikethrough | `~~text~~` | mark `strike` |
| Size | `[text]{.x-small}`, `{.small}`, `{.large}`, `{.x-large}` | mark `size {size: "x-small" \| "small" \| "large" \| "x-large"}` |

`manuscript.SCHEMA` becomes:

```
nodes: doc, title, heading, paragraph, list_item, aligned, blockquote, scene_break, epigraph, attribution, poem,
       image, page_break, table, table_row, table_cell, math_display, hard_break, note, cite, math, text
marks: em, strong, idx, comment, smallcaps, lang, underline, strike, size
```

(Tables and math come in later tasks; until they land, the list stops at `text` without them.)

`list_item` comes after `paragraph`, so the paragraph stays the block ProseMirror makes by default; `list_item.list`
and `aligned.align` have no default (like `heading.level`), so neither is ever made implicitly. The new marks come
last, so existing documents keep their mark order.

### Lists in detail

**Flat items.** A list is a run of consecutive `list_item` blocks at the top level of a piece. Items are not nested
in the document; `level` (0–3) says how deep an item is. What number or letter an item shows is computed, never
stored, by one rule used everywhere (Python `manuscript_lists.markers`, JavaScript `BookFormat.markers`):

```
walk the top-level blocks with a stack of open lists, one per level
  a block that isn't a list item closes every list
  an item's level is clamped to at most one deeper than the stack (the first item of a list is level 0)
  lists deeper than the item close
  the same list style at that level continues it (n + 1, its `start` ignored)
  another style, or nothing open at that level, starts a list there at `start` (1 when null)
```

- `start` is kept only on an item that starts a list, and only when it isn't 1 (`3. item` → `start: 3`; `1. item` →
  null). For letters and roman numerals it is a number too (`c.` → 3).
- Markers: bullet `•` `◦` `▪` `•` by level; decimal `1.`; lower-alpha `a.` … `z.` (after `z.`, items show `aa.`, `ab.`
  and the Markdown keeps writing `z.`, which reads back as the same list); upper-alpha `A.`; roman `i.`, `I.`.
- Two lists of the same style directly after each other are one list. **Ruling** — *cost if wrong:* to restart
  numbering the author puts a line of text between the lists; Markdown has no other way either.
- A list goes on counting across what comes between its items, as in Word and Docs, whatever the edit (a command,
  Enter twice, a block put between two items by `/`, paste or drag): an item that continued a list and now starts
  one gets as its `start` the number after the last item before it that was in the same list (1, a paragraph, 2, 3;
  Enter twice after item 2 of 1–4 and typing gives 1, 2, text, 3, 4). A list that counted on from an earlier one
  (its start is the number after that list's last item, same style and level) belongs to the same list, so
  1, 2, ¶, 3, 4 with 3 made a paragraph gives 1, 2, ¶, ¶, 3; and it follows when the earlier list grows or shrinks
  (Enter after 2 gives 1, 2, 3, ¶, 4, 5). A sublist never counts on across a shallower item: it
  belongs to that item (1. A, a. B, b. X, c. D with X moved out gives 1. A, a. B, 2. X, a. D). When no item of that
  list is left before it (they were deleted, or made paragraphs), it starts at 1. An item whose own style or level changed starts afresh.
  One plugin does this after every change, and also drops `start` from items that continue a list and clamps levels,
  so the editor's document always equals what a reload gives. **Ruling** — *cost if wrong:* to number from 1 again,
  the author makes the item a paragraph and types `1. `; there is no "start at" control.
- **Ruling: a roman list continued at v, x, l, c, d or m, or a lettered list continued at i, reads back in the other
  style**, because Pandoc reads a lone `v.` as the 22nd letter and a lone `i.` as roman 1; a lettered list continued
  past z reads back starting at z — *cost if wrong:* in those rare split lists the items after the split change
  style or number after a reload.
- **Ruling: files written before this change are read with the new rules, without a migration.** v1.2 escaped `1\.`,
  `\-` and `\+` but not letters, so a paragraph that starts `a. `, `c. 1900` or `p. 12` (one space after a lower-case
  letter) now opens as a lettered list item, as Pandoc has always read it; `A. Einstein` and `I. Kant` (one space
  after a capital) stay sentences; `1\.`, `\-` and `• ` paragraphs stay text. By the same Pandoc rule a capital roman
  numeral of several letters is a marker with one space (`II. Deel`), as are abbreviations that happen to be roman
  numerals (`di. 5 mei`, `cm.`). The palette's *Make a list of these
  lines* turns selected paragraphs that start with a typed marker (`•`, `-`, `1.`, `a.`, `I.` …) into list items, for
  lists that earlier imports wrote as text — *cost if wrong:* a paragraph that began with an abbreviation shows as a
  list item; Ctrl+Z after opening doesn't help, but making it a paragraph and retyping the abbreviation does.
- An item is one paragraph: Shift+Enter breaks a line inside it. **Ruling** — *cost if wrong:* a list item can't hold
  a second paragraph, a quotation or a poem; hand-written Markdown with those keeps them as blocks between the items,
  and the next item carries its number as `start`, so the numbering survives (`1. a`, paragraph, `2. b`) — at the top
  level; a block inside a nested item ends the outer list too, so the outer items after it continue the nested
  item's list.
- Lists live at the top level of prose pieces: not inside quotations, epigraphs, poems or notes. In those places,
  and in a piece whose form is poem, Markdown list lines stay lines of text, as today. A list inside `::: center`
  comes out as a real list between the aligned blocks, unaligned. **Ruling** — *cost if wrong:* a list quoted
  inside a quotation shows its markers as text.
- **Ruling: changing a piece's form to poem turns its lists into lines** (the file is read again as a poem; the next
  save writes them as escaped lines, so switching back to prose keeps them as lines); `::: center` blocks read as
  aligned stanzas in a poem piece — *cost if wrong:* a form change is rare and nothing is lost but the list shape.
- Tight lists only: items are written without blank lines between them. **Ruling** — *cost if wrong:* none in
  print; loose lists from other tools are read and written tight.

**Reading** (`manuscript_lists.py`): a copy of markdown-it-py's list rule (MIT, credited), extended with Pandoc's
`fancy_lists` markers: decimal, `a.`/`a)`, `A.`/`A)`, `i.`/`i)`, `I.`/`I)`. As in Pandoc:
- `i.` and `I.` alone are roman (1); another single letter is a letter (`v.` is 22nd letter, `c.` the third); several
  letters are roman when they are a valid numeral (`ii.`, `xiv.`, `IV.`).
- Within a list, the next marker is read in that list's style (`i.` after `h.` continues a lettered list).
- A capital letter, or a capital roman numeral equal to 1, 5, 10, 50, 100, 500 or 1000, followed by a period needs two
  spaces or a tab after it (`A.  item`), so `A. Einstein` and `I. Kant` stay sentences; at the end of a line (an
  empty item) it is an item.
- A list may interrupt a paragraph only when it starts at 1 and its first item isn't empty (CommonMark's rule);
  letters and roman numerals interrupt only inside a list item (a nested list), never top-level text, so a v1.2 line
  break followed by `a. een` stays one paragraph.
- The delimiter `)` is read and written back as `.`, except that an ordered list directly after another ordered list
  at the same level is written with the other delimiter (`.`, `)`, `.` …), so the two never merge on reading. `(a)` markers are not read (Pandoc's two-parenthesis form); the
  writer escapes them at a line start so Pandoc doesn't read them either.

**Writing** (canonical):
- Bullets `-`; decimal `N.`; letters and roman numerals per item in sequence; one space after the marker, two after a
  capital `A.`–`Z.` or capital roman marker with a period (always, for the whole list: `II.  item` too).
- A nested item is indented to its parent's text (`- ` → 2, `1. ` → 3, `10. ` → 4, `A.  ` → 4).
- A line break inside an item continues on the next line, indented to the item's text.
- A blank line before an item that starts a list, unless it is a nested list whose first item can interrupt a
  paragraph (starts at 1, isn't empty), or a nested list right under an empty item (a blank line would end the empty
  item). Between lists at level 0 always.
- Starts above 999 999 999 (CommonMark's nine digits) are not kept.
- Lists are one block: a blank line before and after, like every block.
- At a line start (a block's start, after a line break) the writer escapes what the reader would take as a list
  marker: `a\.`, `iv\.`, `A\.` before two spaces, `\(a)`; decimals as today (`1\.`).

**Flattening** (where a list can't be): inside quotations, epigraphs and notes, and in poem lines, an item becomes a
paragraph that keeps its marker as text, as lists do today.

### Alignment in detail

- `aligned` holds one or more paragraphs; Enter inside it makes another aligned paragraph; Enter on an empty last
  paragraph leaves it, like a quotation.
- Neighbouring aligned blocks with the same alignment are joined when the editor makes them, and written as one div.
- Reading: `::: center` and `::: {.center}` (likewise `right`) at the top level; inside, paragraphs become the aligned
  block; any other block in the fence comes out between aligned blocks, unaligned.
- **Ruling: "as the book" is the only other alignment** (no explicit left, no justify) — *cost if wrong:* a
  ragged-right paragraph in a justified book needs a third value later; the fence form takes it without migration.

### Marks in detail

- Spans combine as today, in one fixed order: `[text]{.idx .comment .smallcaps .underline .large term="…" note="…"
  lang=en}`. One size per text: a new size replaces the old.
- `~~strike~~` follows the same rules as `*` and `**` (delimiter runs, punctuation at the edges, narrowing when
  CommonMark can't write it); a literal `~` in text is written `\~`.
- Sizes are steps relative to the text around them: the editor shows 0.75, 0.875, 1.2 and 1.44 em; .docx uses the
  same factors of the paragraph's size; the composer decides its own (part 2).
- **Ruling: four size steps, no "medium"** — Normal is the absence of the mark — *cost if wrong:* a fifth step is one
  more class name.

### Tables in detail

| Element | Markdown | Document |
|---|---|---|
| Table | Pandoc pipe table: `\| Kop \| Kop \|`, `\| --- \| :-: \|`, `\| a \| b \|` | `table {header: bool, align: [null \| "left" \| "center" \| "right", …]}` › `table_row` › `table_cell` (content `inline*`) |

- **Ruling: pipe tables, not grid tables** — markdown-it reads them (GFM's table rule, which is Pandoc's pipe table),
  Pandoc reads and writes them, and they stay readable as text. A cell holds one line of text with marks, notes,
  citations and math; no line breaks, paragraphs or lists in a cell, no merged cells — *cost if wrong:* a table that
  needs those is a later round with grid tables; nothing written now would change.
- **Ruling: no table captions in this round** (Pandoc's `: caption` line) — *cost if wrong:* a caption is written
  as a paragraph under the table for now.
- A table always has a header row in Markdown. `header: false` is written as an empty first row, which Pandoc reads
  as a table without a header; an empty first row reads back as `header: false` — except in a table with no text
  at all, which stays `header: true` with all its rows (a table just put in, still empty, survives a reload
  unchanged). **Ruling:** a header row left empty above rows with text reads back as no header, and the empty row is
  gone (Markdown has no way to write it) — *cost if wrong:* a row added above the header and left empty disappears
  on the next opening. **Ruling:** a table with no text at all is written with its rows as they are, header or not —
  *cost if wrong:* a still-empty table with Header row off comes back with it on.
- A cell holds one line, whatever is pasted or deleted: text pasted into a cell joins into one line (a table's
  cells with " | "), and a table pasted from Word, Docs or the web has each cell's paragraphs, line breaks and list
  items joined by a space, its formatting kept; deleting across cells, or across the table's edge, clears their
  text and keeps the rows and columns (the text selected outside the table is deleted on its own, never joined
  with a cell), and the editor keeps every table rectangular with one alignment per column. Column alignment comes
  from the delimiter row: `---` none, `:--` left, `:-:` centre, `--:` right.
- Canonical: `| a | b |` with one space each side, delimiter cells `---`, `:--`, `:-:`, `--:`; every row has the
  table's number of cells (short rows are filled, long rows cut, as markdown-it reads them). `|` in text is written
  `\|` everywhere (in a cell it would end the cell).
- Tables live at the top level of prose pieces; in a poem piece table lines are lines.
- Word counts and find count cell text; a cell is a text container, after the cells before it in reading order.

### Math in detail

| Element | Markdown | Document |
|---|---|---|
| Inline math | `$E = mc^2$` | inline atom `math {tex}` |
| Display math | `$$` on its own line, the TeX, `$$` on its own line | block atom `math_display {tex}` |

- Pandoc's `tex_math_dollars` rules: an opening `$` has a non-space right after it, a closing `$` a non-space right
  before it and no digit right after it, so `$20 en $30` is text; `$` in text is written `\$` everywhere.
- Display math is a block of its own (Pandoc reads it as a paragraph holding display math). Inline math sits in any
  text: paragraphs, items, headings, notes, cells.
- Math is not words: counts and find skip it, like citations.
- **Ruling: math only — no raw LaTeX blocks and no LaTeX export.** The book's pages are set by Typst (part 2), so raw
  LaTeX would only ever reach a LaTeX export; and the Markdown export already turns into LaTeX with
  `pandoc book.md -o book.tex` because the dialect is Pandoc's — *cost if wrong:* an author who needs a `\begin{…}`
  environment writes it as display math when KaTeX knows it, or waits for a later round.
- **Ruling: the renderer is KaTeX, vendored** into `static/vendor/katex/` (its MIT licence beside it, woff2 fonts only),
  pinned in `tools/package.json` and copied by `tools/build_vendor.mjs`, so Studio needs no Node or network at
  runtime — *cost if wrong:* KaTeX doesn't know every LaTeX package; what it can't render shows as its source in red,
  never as nothing.
- **Ruling: .docx gets the LaTeX source, not Word equations.** Converting TeX to OMML needs a TeX → MathML → OMML chain
  that Studio doesn't have (Microsoft's stylesheet isn't ours to ship); the source goes in as `$…$` / `$$…$$` text in
  Cambria Math, which Word 365 turns into a real equation with *Equation → LaTeX → Convert* — *cost if wrong:* a
  Word reader sees source until they convert it.
- **Ruling: Word equations in an imported .docx are not converted**; the review screen says how many equations the
  file has and that they aren't imported — *cost if wrong:* the author retypes them as LaTeX.
- For part 2's Typst pages: Typst doesn't read LaTeX math; the suggestion to part 2 is the `mitex` Typst package
  (LaTeX math in Typst, MIT/Apache), bundled offline, or a small TeX-to-Typst converter for the common subset.

## The writing window

### Typing

At the start of a top-level paragraph in a prose piece (not a heading, the title, a poem or a container):

| Type | Becomes |
|---|---|
| `- ` or `• ` | a bulleted item |
| `1. ` or `1) ` (any number) | a numbered item starting there |
| `a. ` `A. ` `i. ` `I. ` (and with `)`) | a lettered or roman item starting at a / A / i / I |
| `~~text~~` | strikethrough (like `*text*`) |

- One Backspace right after takes it back, leaving what was typed.
- The rest of the paragraph stays: typing `- ` at the start of an existing paragraph makes it an item.
- **Ruling: letters and roman numerals start a list only from their first value** — so `J. ` before a name never
  makes a list — *cost if wrong:* a lettered list that starts at c. is made with the panel or by typing a. and
  editing the Markdown; rare.
- **Ruling: `* ` does not start a list** — `* * *` is the scene break — *cost if wrong:* Markdown habit; `- ` works.
- **Ruling: `- ` at a paragraph start makes a list** even though some Dutch dialogue starts with a dash — *cost if
  wrong:* one Backspace each time; dialogue dashes are usually the en or em dash, which don't trigger.

### In a list

| Key | Does |
|---|---|
| Enter | a new item of the same style and level (the rest of the line goes into it) |
| Enter on an empty item | one level out; at level 0, back to a paragraph (the list ends) |
| Shift+Enter | a line break inside the item |
| Backspace at an item's start | one level out; at level 0, back to a paragraph |
| Tab / Ctrl+] | one level in (at most one deeper than the item before, at most level 3) |
| Shift+Tab / Ctrl+[ | one level out (at level 0 nothing happens, and the key stays in the text) |

- Going in, a numbered item becomes lettered, then roman, then numbered (Word's and Docs' multilevel default); a
  bullet stays a bullet. If the list already has items at that level just above, the item takes their style instead,
  so it continues that sublist. Going out, the item takes the style of the list it rejoins.
- Tab outside lists and poem lines behaves as before.

### The format panel

Alt+O, *Format* at the end of the selection bar, or *Format…* in the palette. A small panel under the cursor:

```
┌──────────────────────────────────────────────────────────┐
│ TEXT    Paragraph   Heading   Subheading   Quotation     │
│ LIST    •   1.   a.   A.   i.   I.        Outdent  Indent │
│ ALIGN   As the book   Centre   Right                      │
│ SIZE    A   A   A   A   A                                 │
│ STYLE   B   I   U   S   Small caps              Clear    │
├──────────────────────────────────────────────────────────┤
│ Centre                                     Ctrl+Shift+E  │
└──────────────────────────────────────────────────────────┘
```

- **State shown:** the current text style, list style, alignment and size are marked as on; B, I, U, S and small caps
  show pressed when the selection (or the text about to be typed) has them.
- **Only what applies:** rows that don't apply at the cursor are left out — in a note, the title, an epigraph or a
  `::: poem` block only Size and Style; in a poem piece no List or Align; Align only where the cursor (or every
  selected block) is a top-level paragraph. The Size ladder shows each step at its own size.
- **Keys shown:** the bottom line names the button under the pointer or the keyboard focus, with its key.
- **Keyboard:** the panel opens with the focus on the current choice of its first row; arrows move (left/right in a row,
  up/down between rows), Enter or Space applies, Escape closes; the focus returns to the text.
- A choice applies and closes the panel, as a menu does. Block choices (text style, list, alignment) apply to every
  block the selection touches, or the cursor's block. Character choices (size, B, I, U, S, small caps) apply to the
  selection; with only a cursor they apply to what is typed next, as Ctrl+B does. **Ruling** — *cost if wrong:* to
  size a whole paragraph the author selects it first.
- **Ruling: a panel, not a menu with submenus** — it shows the state at a glance and every choice is one step —
  *cost if wrong:* the palette lists the same commands by name for those who prefer typing.
- **Ruling: Alt+O** (Docs' Format menu key) — Ctrl+/ is part 2's *Keys and tools* sheet — *cost if wrong:* one key.

### The selection bar

Shows only what fits the selection:
- in one block of text: Bold, Italic, Note, Source, Index, Comment (by the book's features, as today) and Format;
- across blocks: Bold, Italic and Format (a note, a source, an index term and a comment belong to one place);
- in a note's text: Bold, Italic, Source and Format.

### The / menu

Gains *Bulleted list* and *Numbered list* (prose pieces only), so a writer who doesn't know `- ` finds lists where
they find everything else.

### Tables in the writing window

- `/` → *Table* puts in a table of three columns: a header row and two rows, the cursor in the first cell.
- Tab goes to the next cell, Shift+Tab to the previous; Tab in the last cell adds a row. Enter goes to the cell
  below; in the last row it leaves the table into the paragraph after it (made when there is none). Arrow keys move
  as in text. Backspace in an empty table selects it; a second Backspace removes it.
- While the cursor is in a table, the format panel shows a *Table* row instead of Text, List and Align: *Row above,
  Row below, Column left, Column right, Delete row, Delete column, Header row* (on/off), the column's alignment
  (*As the book, Left, Centre, Right*), *Delete table*. The palette has the same commands, and a quiet *Table*
  button at the table's top right (only while the cursor is in it) opens them as a menu.
- Keys: Ctrl+Alt+↑ / ↓ add a row above / below; Ctrl+Alt+← / → add a column left / right — Docs has none, these are
  Notion's and Word's habits — *Ruling, cost if wrong:* four keys; the panel and the palette do the same.
- The table looks like the book's text: hairlines between rows, the header row in the label style, no fills; cells
  take the column's alignment; the table scrolls sideways inside the text column when it is wider, never widening
  the column.
- **Ruling: no table made by typing** (Typora's `| a | b |` + Enter) — a pipe in prose is rare but real — *cost if
  wrong:* `/ Table` is one step more.

### Math in the writing window

- Typing `$x^2$` (the closing `$` typed after a non-space, not after a backslash) turns into inline math, rendered;
  one Backspace takes it back. `$$` + Enter at the start of an empty paragraph puts in display math with its source
  open. `/` → *Math* puts in display math too.
- Clicking math (or Enter when it is selected) opens its source in a small field under it, with the rendering
  updating as it is typed; Enter (inline) or Ctrl+Enter (display) or a click elsewhere closes it; Escape closes and
  goes back to the text (right after inline math, into the line after display math, made when there is none); an
  empty source removes the math. Text typed on selected display math goes into the line after it, as text typed on
  a selected note goes after it.
- Math that KaTeX can't render shows its source in the red of Studio's warnings, with KaTeX's message as its title.
- Spelling never marks math.

### The palette

A *Format* group with every command, its key as the hint: Paragraph, Heading, Subheading, Quotation, Bulleted list,
Numbered list, Lettered list, Lettered list (capitals), Roman list, Roman list (small), Indent, Outdent, Align as the
book, Centre, Right, Larger, Smaller, Normal size, Bold, Italic, Underline, Strikethrough, Small caps, Clear
formatting, Format…. Commands that don't apply at the cursor are left out.

### Keys

| Key | Command | From |
|---|---|---|
| Ctrl+B, Ctrl+I | bold, italic | as now |
| Ctrl+U | underline | Docs, Word |
| Alt+Shift+5 | strikethrough | Docs |
| Ctrl+Shift+K | small caps | Word |
| Ctrl+Shift+. / Ctrl+Shift+, | larger / smaller (one step) | Docs, Word |
| Ctrl+Space | clear formatting | Word (Docs' Ctrl+\ shows and hides the list of pieces here) |
| Ctrl+Alt+0 / 2 / 3 | paragraph / heading / subheading | Docs |
| Ctrl+Shift+8 / Ctrl+Shift+7 | bulleted / numbered list (again: back to a paragraph) | Docs |
| Tab, Shift+Tab, Ctrl+], Ctrl+[ | list level; Ctrl+] / Ctrl+[ also into and out of a quotation | Docs |
| Ctrl+Shift+L / E / R | align as the book / centre / right | Docs |
| Alt+O | the format panel | Docs' Format menu |

A key that doesn't apply where the cursor is does nothing and stays in the text (Ctrl+Shift+R never reloads the
window). On a keyboard where Ctrl+Alt+digit types a character (AltGr), the character wins (ProseMirror's rule).
On macOS Ctrl is ⌘ and the panel is ⌃⌥O, so ⌥O still types ø.

### Clear formatting

Removes bold, italic, underline, strikethrough, small caps and size from the selection (with an empty selection: from
what will be typed) and sets the selected paragraphs' alignment back to the book's. It keeps notes, citations, index
terms, comments and languages, and leaves headings, lists and quotations as they are. **Ruling** — *cost if wrong:*
Docs also turns headings back into text; here that is Ctrl+Alt+0, so structure is never lost by a cleanup.

### Paste

- HTML lists (Docs, Word, the web) become list items: level from nesting or Docs' `aria-level`, style from the list's
  `type` or `list-style-type`, start from `start`. Word's own list paragraphs (`mso-list: lN levelM`) use their level
  and the marker Word wrote before it is dropped.
- Plain text is not turned into lists. **Ruling** — *cost if wrong:* a pasted plain list is made into one with
  *Make a list of these lines*, by typing `- ` or with the panel.
- In a poem piece pasted list items become lines with their marker as text.
- **Ruling: inside Studio everything survives copy, cut, paste and drag** (between pieces and panes too): the
  editor's own HTML carries list items, alignment, sizes, underline and strike. Other apps get paragraphs in
  text/html, and text/plain carries the computed markers and indentation (`1. `, `a. `, `• `), so a list pasted into
  an email keeps its numbers — *cost if wrong:* Word or Docs get plain paragraphs from a copy; export is the way out
  with real lists.
- **Ruling: alignment and point sizes are not taken from outside** — not from paste (`text-align`, `font-size`) nor
  from .docx import — because Word and Docs files fake headings and emphasis with sizes and centring; underline and
  strikethrough are taken from both — *cost if wrong:* a centred line from a .docx is centred again by hand.

### Look

- List items hang their marker in a gutter as wide as the widest marker of their list (so `9.` and `10.` and `VIII.`
  line up on their full stops); a sublist starts at its parent item's text edge, so its markers never stand left
  of the parent's text; bullets centred in the gutter. Two lists directly after each other (different styles) are
  set apart by the space between paragraphs.
- Centred and right-aligned paragraphs as said; nothing else marks them.
- Underline: solid, 1 px, in the text colour, closer to the text than the index terms' dotted line, so the two can be
  told apart; strikethrough: 1 px through the middle.
- Measured on real renders, light and dark, at the narrowest text column (360 px).

## Elsewhere in Studio

- **Word counts:** list items and aligned paragraphs count; markers don't. Python and JS agree (`counts`,
  `docWords`).
- **Find and replace, echoes, style checks, rhythm, read aloud:** list items are text containers and aligned blocks are
  walked into, in `books._containers` and `BookTools.containersOf` alike (part 4's locate mirrors both).
- **.docx export:** real Word lists (one numbering definition per list run, so each restarts at its own start; numbering
  formats bullet, decimal, lowerLetter, upperLetter, lowerRoman, upperRoman; 0.63 cm per level), paragraph alignment,
  underline, strike, and run sizes as the same factors of the paragraph style's size.
- **Markdown export:** the pieces' Markdown, as now.
- **.docx tables:** export writes real Word tables (the header row bold and repeated on each page, cells aligned by
  column); import makes tables of them, the first row as the header (Word files rarely mark it), a cell's
  paragraphs joined with a space and a list in a cell as its text.
- **.docx import:** mammoth's lists become list items, nested levels kept; the numbering format and the numbers Word
  shows (start values, numbering that continues across a paragraph) come from the document's own numbering
  definitions when the numbered paragraphs line up one to one with mammoth's items, else the level default
  (decimal, lower-alpha, lower-roman, decimal); underline and strike are kept.
- **Markdown import:** lists read through the dialect.
- **Parts 2–4:** told by message (below).

## For the sibling parts

- **Part 2 (composer, PDF, .docx):** renders `list_item` (flat; `manuscript_lists.markers(blocks)` gives each block's
  marker text and clamped level, or None), `aligned` (`center`, `right`), and the marks `underline`, `strike`,
  `size`. Part 2's richer .docx export should keep this design's list numbering (in `studio/docx_lists.py`).
- **Part 3 (board):** a quote dropped while the cursor is in a list item lands after the item, as for a paragraph;
  citations work inside items.
- **Part 4 (Claude's tools):** list items are text containers and aligned blocks are walked into; the marks order gains
  `underline`, `strike`, `size` at the end; `read_piece` shows lists as Markdown lists.

## Code

| File | Change |
|---|---|
| `studio/manuscript_lists.py` (new) | the fancy list block rule, `markers(blocks)`, marker formatting, line-start escapes |
| `studio/manuscript.py` | the new nodes and marks, reading and writing them; plain text and counts |
| `studio/books.py` | `_containers`: `list_item`, `aligned` |
| `studio/docx_lists.py` (new) | Word numbering definitions for list runs |
| `studio/book_export.py` | lists, alignment, underline, strike, sizes |
| `studio/book_import.py` | lists as list items (with the .docx numbering formats), underline, strike |
| `studio/static/book-schema.js` | the new nodes and marks |
| `studio/static/book-format.js` (new) | commands, typing rules, keys, list markers (decorations), the panel, palette actions |
| `studio/static/book-format.css` (new) | lists, alignment, marks, the panel |
| `studio/static/book-text.js` | a few lines: the format plugins and keys, the bar's Format button and fit rules, the / menu items, word counts |
| `studio/static/book-tools.js` | `containersOf`; the palette's Format group |
| `studio/static/index.html` | the new script and stylesheet |
| `studio/static/book-table.js` (new) | table node view, commands, Tab and Enter in cells |
| `studio/static/book-math.js` (new), `static/vendor/katex/` (vendored) | math node views, source editing, typing rules |
| `tools/package.json`, `tools/build_vendor.mjs`, `CONTRIBUTING.md` | KaTeX pinned, copied and documented |

## Testing

- `tests/test_manuscript.py`: samples for every new element (round trip), canonical forms of hand-written lists
  (`*`/`+` bullets, `)` delimiters, loose lists, multi-paragraph items, odd levels, `A. Einstein`, `I. Kant`, `i.` in a
  lettered list, a list that starts at 3, lists in quotations and poems), line-start escapes, strikethrough edges, `~`.
- `tests/test_schema_parity.py`: picks up the samples; the JS schema loads every document unchanged.
- `tests/js/book_format.js` (+ `tests/test_book_format.py`): markers agree with Python's for every sample; commands on
  editor states in node (typing rules and their Backspace, Enter/Backspace/Tab in lists, alignment, sizes, clear
  formatting); paste flattening.
- `tests/test_export.py`, `tests/test_import.py`: .docx lists (numbering formats, levels, restarts), alignment, sizes;
  a .docx made with lettered and nested lists imports as list items.
- In the browser, with a throwaway library: typing every trigger and Backspace; Tab/Shift+Tab; the panel by mouse and
  keyboard; the bar across blocks; the palette; paste from HTML; light and dark screenshots; the 360 px column.

## Later: three extras, after everything above is built and reviewed

1. **Corkboard.** A *Cards* view of the book beside the list of pieces: one card per piece (title, kind, status,
   words, and a short synopsis), in the book's order; drag to reorder, which moves the piece in `contents` exactly as
   the list of pieces does. The synopsis is a new optional `synopsis` key on the piece's `contents` entry in
   `book.json` (plain text, at most 400 characters), edited on the card; unknown keys are already kept, so older
   Studios leave it alone. Calm cards on the book's grid, light and dark.
2. **Every key in one sheet.** Part 2 builds the *Keys and tools* sheet on Ctrl+/; this branch makes `?` (when the
   cursor isn't in text) open it too, and gives it every key of the writing window from one source,
   `BookFormat.KEYS` plus the window's own keys, so it is always current.
3. **Make a design from this passage.** *Design* in the selection bar (and in the palette) when a passage is
   selected: Studio makes a new design from the design starters, with the passage as its text and the book's look,
   and opens it in the design editor. Where it goes: the poem it links to when the passage is in a linked poem; else a
   series named *Book quotes* (made on first use, with the book's look) — *Ruling, cost if wrong:* the design can be
   moved later like any design.

These get their own short plan when the work above is done; whatever isn't reached tonight is listed in the morning
summary.

## Left to the builder

The exact panel spacing and type sizes (within Studio's tokens), the bullet glyphs' optical size, how the panel is
positioned near the bottom of the window, and the order of palette items within the Format group.
