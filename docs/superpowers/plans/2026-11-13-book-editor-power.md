# The writing window, more powerful — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real lists, alignment, inline sizes, underline, strikethrough, clear formatting and a format panel in the
book writing window, stored in the Markdown dialect and carried through counts, find, .docx export and import.

**Architecture:** The dialect (`studio/manuscript.py`, with a new `studio/manuscript_lists.py`) gains a flat
`list_item` text block, an `aligned` container and three marks; `book-schema.js` mirrors it. A new classic script
`book-format.js` holds every editor command, typing rule, key, the list-marker decorations, the format panel and the
palette's format actions; `book-text.js` and `book-tools.js` call it in a few lines.

**Tech Stack:** Python 3 stdlib web server, markdown-it-py 4 + mdit-py-plugins, python-docx, mammoth; plain JS on the
vendored ProseMirror bundle (`window.PM`, no rebuild); node for JS tests.

**Spec:** `docs/superpowers/specs/2026-11-13-book-editor-power-design.md` — read it before any task; every task
implements part of it, and its tables (dialect, keys, typing, list keys) are the source of exact values.

## Global Constraints

- Work only in `<worktree>` (branch `book-editor-power`).
  Never edit the main checkout, `<library folder>` or `<config file>`.
- Python: `<venv>\Scripts\python.exe`, run from the worktree root
  (`cd <worktree>`, then `../../.venv/Scripts/python.exe`).
  Full suite: `../../.venv/Scripts/python.exe -m unittest discover tests` (380 OK at the start).
- No new dependencies, no vendor rebuild: `window.PM` exports only what `tools/vendor-entry.js` lists.
- Front end: classic scripts, no build step; the new file sets `window.BookFormat`; pure helpers and commands must
  run in node (no DOM at load time; DOM code only behind `typeof document !== "undefined"`).
- Interface copy: plain, sentence case, British spelling ("Centre"), no badges or flourishes; keys written
  `Ctrl+Shift+E` (on macOS `⌘⇧E` via the existing `keyName` style). Every view escapes user text (`esc`).
- A text column is never narrower than 360 px.
- Nothing personal: invented Dutch test text only; no real names, titles, paths or emails.
- Canonical Markdown: for every sample `serialize(parse(md)) == md` and `parse(serialize(parse(md))) == parse(md)`.
- `manuscript.SCHEMA` nodes `doc, title, heading, paragraph, list_item, aligned, blockquote, scene_break, epigraph,
  attribution, poem, image, page_break, hard_break, note, cite, text`; marks `em, strong, idx, comment, smallcaps,
  lang, underline, strike, size` — `book-schema.js` line 1 and its spec order match exactly.
- Commits: normal signed `git commit` (never `--no-gpg-sign`), messages end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No push, tag, merge, version change or release notes.
- Scratch servers only on ports 4748–4757 with temp `STUDIO_CONFIG`, `STUDIO_ART`, `STUDIO_CACHE`; stop every process.
- Shared front-end files (`book-text.js`, `book-tools.js`, `book-editor.js`, `book-rail.js`, `book.css`,
  `book-tools.css`, `index.html`, `app.js`): smallest possible edits; put new code in `book-format.js/.css`.

## Review Focus

1. **Files written by v1.2 read the same.** v1.2 escaped `1\.`, `\-`, `\+` but not letters: `I. Kant`, `A. Einstein`
   (one space) must stay paragraphs; `a. een` becomes a lettered list (spec). → Task 1 test
   `test_v12_files_read_as_before`.
2. **Strikethrough never prints tildes.** `~~` at punctuation edges, crossing `*`, inside spans and notes degrades like
   `*` does. → Task 2 test `test_unwritable_strike_degrades`.
3. **Items carry everything a paragraph carries:** notes, citations, comments, index terms, hard breaks, Dutch quotes.
   → Task 1 samples.
4. **Undo is exact:** one Backspace after a typing trigger restores the typed text; Ctrl+Z after Tab, Enter, align,
   size restores the document. → Task 6/7 JS scenarios `undo:*`.
5. **Poems are left alone:** no list trigger, list key or list paste in a poem piece or `::: poem` block; Tab there
   still indents with no-break spaces. → Task 6 scenarios `poem:*`.

---

### Task 1: Lists in the dialect (Python)

**Files:**
- Create: `studio/manuscript_lists.py`
- Modify: `studio/manuscript.py` (SCHEMA, `_markdown`, `_Reader._blocks`, `_paragraphs`, `_esc_line_start`, `_block`,
  `serialize`, `_block_text`), `studio/static/book-schema.js` (line 1 + `list_item` node),
  `studio/static/book-text.js` (`docWords` counts a `list_item` like a paragraph — one line, so the word-count
  parity test stays green)
- Test: `tests/test_manuscript.py`

**Interfaces:**
- Produces (`studio/manuscript_lists.py`):
  - `STYLES = ("bullet", "decimal", "lower-alpha", "upper-alpha", "lower-roman", "upper-roman")`
  - `list_rule(state, startLine, endLine, silent) -> bool` — markdown-it block rule; registered by
    `manuscript._markdown` with `md.block.ruler.at("list", list_rule, {"alt": ["paragraph", "reference",
    "blockquote"]})` so `block_off=("list",)` still disables it. Open tokens (`bullet_list_open`,
    `ordered_list_open`) carry `meta = {"list": style, "start": n}`.
  - `to_roman(n: int) -> str` (lower case), `from_roman(s: str) -> int | None`, `to_alpha(n: int) -> str`
    (1 → "a", 27 → "aa")
  - `marker_text(style: str, n: int, level: int) -> str` — display: bullets `•◦▪•` by level, `"1."`, `"a."`, `"A."`,
    `"iv."`, `"IV."`
  - `md_marker(style: str, n: int) -> str` — Markdown, with its trailing space(s): `"- "`, `"3. "`, `"c. "`,
    `"C.  "`, `"iv. "`, `"IV.  "`; letters past 26 write `z`
  - `markers(blocks: list[dict]) -> list[dict | None]` — per top-level block: None, or
    `{"marker": str, "level": int, "list": str, "n": int, "first": bool, "run": int}` (`level` clamped; `first`: the
    item starts a list; `run`: index in `blocks` of its list's first item)
  - `normalize(blocks: list[dict]) -> list[dict]` — clamps item levels and sets `attrs.start` from a temporary
    `"_n"` key (the number the item had in its source): `_n` on a run's first item when `_n != 1`, else None; drops
    `_n`; also drops `start` from items that aren't first (used by the reader and by import)
  - `escape_line_start(text: str) -> str` — backslash before what the reader would take as a list marker at a line
    start: `a\.`, `iv\.`, `A\.` only before a tab, two spaces or the end, `A\)`, `\(a)`; returns `text` unchanged
    otherwise
- Produces (`manuscript`): document nodes `{"type": "list_item", "attrs": {"list", "level", "start"}, "content"}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_manuscript.py`:
  - Append to `SAMPLES` (each must round-trip exactly):
    `"- Een\n- Twee met *nadruk*^[Een noot.]\n- Drie [@bron2020, p. 4]\n"`,
    `"1. Een\n2. Twee\n   a. Sub een\n   b. Sub twee\n      i. Diep\n3. Drie\n"`,
    `"Tekst ervoor.\n\n3. Drie\n4. Vier\n\nTekst erna.\n"`,
    `"A.  Eerste\nB.  Tweede\n"`, `"I.  Een\nII.  Twee\nIII.  Drie\n"`, `"i. een\nii. twee\n"`,
    `"- Een regel\\\n  en de volgende\n- [Opmerking]{.comment note=\"nakijken\"} hier\n"`,
    `"- Een\n\n1. Nu genummerd\n"`, `"-\n- Na een lege\n"`,
    `"a. een\nb. twee\nc. drie\nd. vier\ne. vijf\nf. zes\ng. zeven\nh. acht\ni. negen\n"`.
  - `test_list_documents`: `parse("1. Een\n   - Sub\n2. Twee\n")["content"]` equals three `list_item` nodes with attrs
    `{"list": "decimal", "level": 0, "start": None}`, `{"list": "bullet", "level": 1, "start": None}`,
    `{"list": "decimal", "level": 0, "start": None}`; `parse("3. Drie\n")` gives `start` 3; `parse("c. drie\n")` gives
    `{"list": "lower-alpha", "start": 3}`; `parse("v. vijf\n")` is lower-alpha with start 22.
  - `test_lists_normalise` (input → canonical, and the canonical is a fixed point):
    `"* een\n+ twee\n"` → `"- een\n- twee\n"` (adjacent lists of one style are one list); `"1) een\n2) twee\n"` → `"1. een\n2. twee\n"`;
    `"- een\n\n- twee\n"` → `"- een\n- twee\n"`;
    `"1. een\n\n   tweede alinea\n\n2. twee\n"` → `"1. een\n\ntweede alinea\n\n2. twee\n"`;
    `"1. een\n\n   > citaat\n\n2. twee\n"` → `"1. een\n\n> citaat\n\n2. twee\n"`;
    `"> - een\n> - twee\n"` → `"> \\- een\n>\n> \\- twee\n"`;
    `"z. laatste\n"` stays; a 28-item lettered list writes its last three markers `z.`, `z.`, `z.` and reads back
    as the same document.
  - `test_v12_files_read_as_before`: each of `"I. Kant schreef.\n"`, `"A. Einstein zei het.\n"`, `"1\\. geen lijst\n"`,
    `"\\- geen opsomming\n"`, `"Mr. Jansen kwam.\n"` parses to one paragraph and serializes unchanged.
  - `test_list_markers_escaped_at_line_starts`: a paragraph with text `"a. geen lijst"` serializes as
    `"a\\. geen lijst\n"`; `"iv. ook niet"` → `"iv\\. ook niet\n"`; `"(a) niet"` → `"\\(a) niet\n"`;
    `"A.  twee spaties"` → `"A\\.  twee spaties\n"`; `"A. een spatie"` → unchanged; the same text after a hard break
    is escaped too; each reads back as the same paragraph.
  - `test_lists_in_poems_stay_lines`: `parse("- een\n- twee\n", "poem")` is one paragraph with a hard break (as today).
  - `test_list_markers`: `manuscript_lists.markers(parse("1. a\n   - b\n   - c\n2. d\n\nx\n\n- e\n")["content"])`
    gives markers `["1.", "◦", "◦", "2.", None, "•"]` (None for the paragraph), `first` True for items 0, 1 and 5,
    `run` 0, 1, 1, 0, -, 5; `markers` of three items with levels `[0, 2, 3]` clamps them to `[0, 1, 2]`.
  - `test_counts_include_lists`: `counts("- een twee\n- drie\n")["words"] == 3`.

- [ ] **Step 2: Run them to see them fail**
  Run: `../../.venv/Scripts/python.exe -m unittest tests.test_manuscript tests.test_schema_parity -v`
  Expected: FAIL (no `list_item`; round trips differ).

- [ ] **Step 3: Implement `studio/manuscript_lists.py`.** `list_rule` is a copy of markdown-it-py's
  `rules_block/list.py` `list_block` (credit the MIT licence and source in the module docstring), changed to:
  read ordered markers `\d{1,9}`, one letter, or a valid roman numeral, followed by `.` or `)`; decide the style as
  Pandoc does (`i`/`I` alone roman; another single letter alpha; several letters roman when valid); read the next
  items of a list in that list's style (in a lettered list `i.` is the ninth letter); require a tab or two spaces
  after a capital single letter or capital roman 1, 5, 10, 50, 100, 500, 1000 with `.` (end of line allowed: empty
  item); let a list interrupt a paragraph only when its value is 1 and the item isn't empty; end the list when the
  style or the bullet/ordered kind changes; write `meta` on the open token.

- [ ] **Step 4: Wire it into `manuscript.py`.**
  - SCHEMA nodes as in Global Constraints (marks change in Task 2).
  - Reader: lists produce flat `list_item` nodes — the item's first paragraph is its content (no paragraph →
    empty item); nested lists come out at `level + 1`; any other block of the item (second paragraph, quotation,
    fence, image) comes out after it at the top level; every item gets `"_n"` (its number in the Markdown list), and
    `parse` calls `normalize` on the top-level content before returning.
  - `_paragraphs` (quotations, epigraphs, notes): a `list_item` becomes a paragraph led by its marker text and a space
    (`-` for bullets, `md_marker`'s text without its spaces for the rest), as lists are today.
  - Writer: consecutive top-level `list_item` nodes are one block, written by `_list_md(items)`: per item its
    `md_marker`, two spaces after the marker for every item of a capital-letter or capital-roman list, indentation to
    the parent item's text column, hard-break continuation lines indented to the item's text column, and a blank
    line before an item that starts a list unless it is nested and can interrupt (value 1, not empty); at level 0
    always. Item text is written with `_inline_md(content, False, True)` so line starts are escaped.
  - `_esc_line_start` also applies `escape_line_start`.
  - `_block_text` / `plain_text`: a `list_item` is text.

- [ ] **Step 5: Mirror the node in `book-schema.js`.** Line 1 per SCHEMA. After `paragraph`:
  `list_item: {attrs: {list: {}, level: {default: 0}, start: {default: null}}, content: "inline*", group: "block",
  parseDOM: [{tag: "p.bk-li", priority: OWN, getAttrs: …}], toDOM: n => ["p", {class: "bk-li", "data-list": …,
  "data-level": …, …(start ? {"data-start"} : {})}, 0]}` — `getAttrs` returns `false` for a `data-list` not in the
  six styles and clamps `data-level` to 0–3.

- [ ] **Step 6: Run the tests**
  Run: `../../.venv/Scripts/python.exe -m unittest tests.test_manuscript tests.test_schema_parity tests.test_book_text -v`
  Expected: PASS (the JS schema loads every new sample unchanged; `docWords` agrees with `counts` on every sample).

- [ ] **Step 7: Commit** — `git add studio/manuscript_lists.py studio/manuscript.py studio/static/book-schema.js
  tests/test_manuscript.py && git commit -m "Books: real lists in the manuscript dialect (flat list items)" -m
  "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

### Task 2: Alignment, underline, strikethrough and sizes in the dialect

**Files:**
- Modify: `studio/manuscript.py` (SCHEMA marks, `_SPAN`, `_FENCES`, `_span_marks`, `_Reader._inline`, `_Reader._fence`,
  `_paragraphs`, `_ESCAPES`, `_ORDER`, `_fmt`, `_span_attrs`, `_open`, `_items`, `_layout`, `_block`, `_block_text`),
  `studio/static/book-schema.js`, `studio/static/book-text.js` (`docWords` walks into `aligned`), `docs/DESIGN.md`
  (the dialect line under "Books")
- Test: `tests/test_manuscript.py`

**Interfaces:**
- Consumes: Task 1's SCHEMA and `book-schema.js` layout.
- Produces: node `{"type": "aligned", "attrs": {"align": "center" | "right"}, "content": [paragraph, …]}`; marks
  `{"type": "underline"}`, `{"type": "strike"}`, `{"type": "size", "attrs": {"size": "x-small" | "small" | "large" |
  "x-large"}}`; `manuscript.SIZES = ("x-small", "small", "large", "x-large")`.

- [ ] **Step 1: Write the failing tests:**
  - `SAMPLES` gains `"::: center\nIn het midden.\n\nNog een regel.\n:::\n\nGewoon verder.\n"`,
    `"::: right\nAmsterdam, 3 maart\n:::\n"`, `"Een [onderstreept]{.underline} woord.\n"`,
    `"Een ~~doorgestreept~~ woord, *schuin ~~en weg~~*.\n"`,
    `"[Klein]{.x-small}, [kleiner]{.small}, [groot]{.large} en [groter]{.x-large}.\n"`,
    `"[Alles]{.idx .comment .smallcaps .underline .large term=\"alles\" note=\"n\" lang=en} samen.\n"`,
    `"Een tilde \\~ blijft tekst.\n"`.
  - `test_aligned_documents`: `parse("::: {.center}\nA\n:::\n")["content"] == [{"type": "aligned", "attrs":
    {"align": "center"}, "content": [{"type": "paragraph", "content": [text("A")]}]}]`.
  - `test_aligned_normalises`: `"::: center\nA\n:::\n\n::: center\nB\n:::\n"` → `"::: center\nA\n\nB\n:::\n"`;
    `"::: center\nA\n\n## Kop\n\nB\n:::\n"` → `"::: center\nA\n:::\n\n## Kop\n\n::: center\nB\n:::\n"`;
    `"::: center\n:::\n"` → `""`; `"> ::: center\n> A\n> :::\n"` reads as a quotation holding paragraph `A`.
  - `test_unwritable_strike_degrades` (as `test_unwritable_emphasis_degrades`): `[text("x"), text("(y)", strike),
    text("z")]` → `"x(~~y~~)z\n"`; `[text("a", strike), text("b", strike, em), text("c", em), text("d")]` never
    leaves `~` in `plain_text` and reads back stable; a hard break at the edge of a strike run goes outside it.
  - `test_size_is_one_per_text`: a text node with `size` `large` written and read back keeps `{"size": "large"}`;
    `[text]{.small .large}` reads as `small` (the first).

- [ ] **Step 2: Run them to see them fail** — `../../.venv/Scripts/python.exe -m unittest tests.test_manuscript -v`.

- [ ] **Step 3: Implement.**
  - SCHEMA marks per Global Constraints; `_SPAN = ("idx", "comment", "smallcaps", "underline", "size", "lang")`;
    classes written in that order, then `term`, `note`, `lang`.
  - Strike: `md.enable("strikethrough")` in `_markdown`; `s_open`/`s_close` → mark `strike`; `"~"` in `_ESCAPES`;
    `_open` gives `"~~"`; `_ORDER = {"span": 0, "strong": 1, "em": 2, "strike": 3}`; `_items` and `_layout` treat
    `("strike",)` like `em`/`strong`.
  - `aligned`: `_FENCES` gains `center`, `right`; `_fence` reads the fence's blocks and groups consecutive paragraphs
    into `aligned` nodes, other blocks pass through; writer joins consecutive top-level `aligned` nodes with the same
    `align` into one fence `::: center\n…\n:::` and drops one without text; `_paragraphs` flattens `aligned` to its
    paragraphs; `_block_text` walks into it.
- [ ] **Step 4: Mirror in `book-schema.js`:** `aligned: {attrs: {align: {}}, content: "paragraph+", group: "block",
  defining: true, parseDOM: [{tag: "div.bk-align", priority: OWN, getAttrs: d => ["center", "right"].includes(…) ?
  {align} : false}], toDOM: n => ["div", {class: "bk-align", "data-align": n.attrs.align}, 0]}`; marks
  `underline` (`u`, and `text-decoration`/`text-decoration-line` containing `underline`; toDOM `["u", 0]`),
  `strike` (`s`, `del`, `strike`, `line-through`; toDOM `["s", 0]`), `size` (`span.bk-size[data-size]` with a
  known size only; toDOM `["span", {class: "bk-size", "data-size": size}, 0]`) — pasted point sizes are not kept.
  Add the parse-rule checks to `tests/js/schema_roundtrip.js` ("underline: u", "strike: del", "size: own spans only").
- [ ] **Step 5: `docs/DESIGN.md`:** the dialect bullet under "Books" lists lists (`- `, `1. `, `a. `, `I.  `),
  `::: center`/`::: right`, `{.underline}`, `~~strike~~` and size spans, and names `manuscript_lists.py`.
- [ ] **Step 6: Run** `../../.venv/Scripts/python.exe -m unittest tests.test_manuscript tests.test_schema_parity -v`
  — PASS.
- [ ] **Step 7: Commit** ("Books: alignment, underline, strikethrough and sizes in the dialect").

### Task 3: Text containers everywhere (find, counts, history)

**Files:**
- Modify: `studio/books.py` (`_containers`), `studio/static/book-tools.js` (`containersOf`, `plainBlocks` if it lists
  block types)
- Test: `tests/test_books.py`, `tests/js/book_tools.js` (+ its runner), `tests/test_book_text.py` (automatic via
  samples)

**Interfaces:**
- Consumes: Task 1–2 node types.
- Produces: `list_item` is a `("text", content)` container followed by its notes, exactly like `paragraph`;
  `aligned` is walked into like `blockquote` — in Python and JS alike (part 4's locate mirrors both).

- [ ] **Step 1: Failing tests.** `tests/test_books.py`: `test_search_and_replace_in_list_items_and_aligned_text` — a
  piece `"- Een appel\n- Twee appels\n\n::: center\nDrie appels\n:::\n"`; `search("appel")` finds 3; `replace`
  of `appels` → `peren` writes `"- Een appel\n- Twee peren\n\n::: center\nDrie peren\n:::\n"`. In
  `tests/js/book_tools.js` add a check that `containersOf` on the parsed doc of that piece yields text containers
  `["Een appel", "Twee appels", "Drie appels"]`.
- [ ] **Step 2: Run** `../../.venv/Scripts/python.exe -m unittest tests.test_books tests.test_book_tools tests.test_book_text -v` — FAIL.
- [ ] **Step 3: Implement** both containers. Read `plainBlocks`/`diffBlocks`, include `list_item` wherever
  `paragraph` is named and walk into `aligned` wherever `blockquote` is.
- [ ] **Step 4: Run** the same command — PASS; then the full suite.
- [ ] **Step 5: Commit** ("Books: list items and aligned text are found, counted and replaced").

### Task 4: .docx export — real lists, alignment, marks

**Files:**
- Create: `studio/docx_lists.py`
- Modify: `studio/book_export.py` (`_Writer._run`, `_Writer.inline`, `_Writer.block`, `_Writer.piece`, module docstring)
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `manuscript_lists.markers(blocks)` (Task 1), `manuscript.SIZES` (Task 2).
- Produces: `docx_lists.Numbering(document)`; `.num_id(style: str, level: int, start: int) -> int` — a new
  `w:abstractNum` (levels 0–3; the given level with its `numFmt`, `lvlText`, `start`; indentation left
  `720 + 360 * level` twips, hanging 360) and a new `w:num`; `.apply(paragraph, num_id: int, level: int) -> None`
  sets `w:numPr` (`w:ilvl`, `w:numId`). Formats: bullet → `bullet` with `•`, `◦`, `▪`, `•`; decimal → `decimal`
  `%N.`; `lowerLetter`, `upperLetter`, `lowerRoman`, `upperRoman` likewise. `SIZE_FACTORS = {"x-small": 0.75,
  "small": 0.875, "large": 1.2, "x-large": 1.44}` (in `book_export`).

- [ ] **Step 1: Failing test** `test_docx_lists_alignment_and_marks`: a piece
  `"1. Een\n2. Twee\n   a. Sub\n\nTussen.\n\n3. Drie\n\n- Punt\n\n::: center\nMidden\n:::\n\n::: right\nRechts\n:::\n\n"
  "Een [o]{.underline} ~~s~~ [g]{.large} woord.\n"` exported; reopened with python-docx: the list paragraphs have
  `numPr` with `ilvl` 0, 0, 1, 0, 0; items 1–2 share a `numId`, `Sub` has its own, `Drie` has its own whose level 0
  `start` is 3 and `numFmt` `decimal`, `Sub`'s level 1 `numFmt` is `lowerLetter`, `Punt`'s is `bullet`; `Midden` is
  centred, `Rechts` right-aligned; runs `o` underlined, `s` struck, `g` at `Normal`'s size × 1.2 (11 pt → 13.2 pt
  when the template's Normal has no size, use 11 pt).
- [ ] **Step 2: Run** `../../.venv/Scripts/python.exe -m unittest tests.test_export -v` — FAIL.
- [ ] **Step 3: Implement `studio/docx_lists.py`** with python-docx's oxml (`document.part.numbering_part.element`),
  ids above the template's highest `abstractNumId`/`numId`.
- [ ] **Step 4: Hook `book_export`:** `piece()` computes `markers(content)` once and passes each block its entry;
  a `list_item` is a `List Paragraph`-style paragraph numbered by `Numbering` (one `num_id` per `run`); an `aligned`
  block writes its paragraphs with `WD_ALIGN_PARAGRAPH.CENTER`/`RIGHT`; `_run` gains `underline`, `strike`,
  `size` keyword arguments; `inline` reads the marks; the docstring's mapping lists the new nodes and marks. Keep
  every hook small: part 2 reworks this file.
- [ ] **Step 5: Run** the export tests, then the full suite — PASS.
- [ ] **Step 6: Commit** ("Books: .docx export with real lists, alignment, underline, strike and sizes").

### Task 5: .docx import — lists as list items

**Files:**
- Modify: `studio/book_import.py` (`STYLE_MAP`, `_inline`, `html_to_blocks`, `_walk`, `_list`, `_body_nodes`,
  `_docx_blocks`, module docstring rule list)
- Test: `tests/test_import.py`

**Interfaces:**
- Consumes: `manuscript_lists.normalize`, `STYLES` (Task 1).
- Produces: `html_to_blocks(html: str, list_styles: list[tuple[str, int, int]] | None = None) -> list[dict]` (one
  `(style, level, number)` per numbered paragraph of the .docx, in order); `_docx_list_styles(data: bytes) ->
  list[tuple[str, int, int]]` reads `word/numbering.xml` and `word/document.xml` (Word's counters per `numId` and
  level, deeper levels restarting); blocks of type `"li"` with `"list"`, `"level"`, `"_n"`.

- [ ] **Step 1: Failing tests:**
  - `test_lists_from_mammoth_html`: `html_to_blocks("<ol><li>een<ol><li>sub</li></ol></li><li>twee</li></ol><ul><li>punt</li></ul>")`
    gives `li` blocks with (list, level) `(decimal, 0)`, `(lower-alpha, 1)`, `(decimal, 0)`, `(bullet, 0)`; a
    proposal from Markdown-free HTML through `_piece` writes `"1. een\n   a. sub\n2. twee\n\n- punt\n"`.
  - `test_docx_lists_keep_their_formats`: a .docx built in the test with python-docx whose numbering defines level 0
    `upperRoman` and level 1 `lowerLetter` (write `numbering.xml` entries with oxml), paragraphs I, II, nested a, and a
    paragraph between items continuing at III → the proposed Markdown is `"I.  Een\nII.  Twee\n     a. Sub\n\nTussen.\n\nIII.  Drie\n"`.
  - `test_underline_and_strike_are_kept`: `<p><u>o</u> <s>weg</s></p>` → `"[o]{.underline} ~~weg~~"`.
  - The existing tests stay green (lists used to import as `1. ` paragraphs: update only assertions that encoded
    that old behaviour, and say so in the commit message).
- [ ] **Step 2: Run** `../../.venv/Scripts/python.exe -m unittest tests.test_import -v` — FAIL.
- [ ] **Step 3: Implement:** `STYLE_MAP` gains `u => u` (mammoth already writes `<s>` for strikethrough); `_inline`
  maps `u` → `underline`, `s`/`del`/`strike` → `strike`; `_list` emits `li` blocks (style from `list_styles` when
  their count equals the number of `li` elements outside the notes lists, else bullet for `ul` and the level default
  `decimal, lower-alpha, lower-roman, decimal` for `ol`); `_body_nodes` turns `li` into `list_item` nodes and calls
  `normalize`; images inside an item come after it.
- [ ] **Step 4: Run** the import tests, then the full suite — PASS.
- [ ] **Step 5: Commit** ("Books: .docx and HTML lists import as real lists; underline and strike kept").

### Task 6: `book-format.js` — markers and list commands (no DOM)

**Files:**
- Create: `studio/static/book-format.js`, `tests/js/book_format.js`, `tests/test_book_format.py`
- Test: those two

**Interfaces:**
- Consumes: `window.BookSchema`, `window.PM` (only exported names), Task 1's marker rule.
- Produces (`window.BookFormat`):
  - `STYLES`, `markers(doc) -> Array<{pos, marker, level, list, n, first, run} | null>` (per top-level child; same
    rule and text as Python's `markers`), `markerText(list, n, level)`
  - `commands.setList(style)`, `commands.indent(dir: 1 | -1)`, `commands.listEnter`, `commands.listBackspace`,
    `commands.listTab`, `commands.listShiftTab` — ProseMirror commands `(state, dispatch?) => boolean`
  - `inputRules() -> InputRule[]` (the list triggers of the spec's typing table)
  - `numbersPlugin() -> Plugin` — appendTransaction after every doc change: (1) an item that continued a list
    before the change and starts one after it, whose previous item still exists (its inner position isn't
    `deleted` in the mapping), gets `start` = the number it showed (null when 1); (2) `start` is dropped from items
    that continue a list; (3) levels are clamped — so the editor's JSON equals what a reload gives
  - `MAX_LEVEL = 3`, `NEST = ["decimal", "lower-alpha", "lower-roman", "decimal"]`

- [ ] **Step 1: Write `tests/js/book_format.js` and `tests/test_book_format.py`.** The runner (like
  `tests/test_book_text.py`) passes the prosemirror bundle, `book-schema.js`, `book-format.js` and a JSON input of
  `{doc, markers}` for every `SAMPLES` entry (Python `manuscript_lists.markers`); the harness reports
  `{failures: [...], checked: n}`; the Python test asserts no failures and `checked >= len(SAMPLES) + 30`. Scenarios
  (each a named check on an `EditorState` built with the schema, `history()` and the rules; `type(state, text)` runs
  input rules through `handleTextInput` the way `prosemirror-inputrules` tests do):
  - `markers:parity` — every sample's JS markers equal Python's (marker, level, first).
  - `type:bullet` `- ` / `• ` at a paragraph start → bullet item, the dash gone; `type:number` `3. ` → decimal,
    start 3; `type:letters` `a. ` `A. ` `i. ` `I. ` and `a) `; `type:no-J` `J. ` stays text; `type:star` `* ` stays
    text; `type:keeps-rest` typing `- ` before existing text keeps the text.
  - `undo:trigger` — Backspace (`undoInputRule`) right after `- ` gives back `- ` as text.
  - `poem:no-list` — in a doc with `form: "poem"` and inside a `::: poem` block no trigger fires and `setList` returns
    false; `poem:tab` — `listTab` returns false in a poem line.
  - `enter:split` (new item, same style and level, `start` null), `enter:empty-nested` (level − 1),
    `enter:empty-top` (paragraph), `enter:keep-numbers` (ending item 2 of 1–4 leaves the next item `start` 3).
  - `backspace:start` (level − 1, then paragraph), `tab:in` (decimal → lower-alpha at level 1; bullet stays bullet;
    takes the style of an item just above at that level; not deeper than previous + 1, not past 3),
    `tab:out` (rejoins the parent list's style), `tab:top` (Shift+Tab at level 0 returns true and changes nothing).
  - `setList:toggle` (paragraph → decimal → paragraph; bullet → decimal keeps level; several selected paragraphs
    become one list), `numbers:levels`, `numbers:start-dropped`, `numbers:block-between` (a scene break inserted
    between items 2 and 3 of 1–4 leaves 3, 4), `numbers:deleted-renumber` (deleting items 1–2 of 1–4 shows 1, 2),
    `numbers:reload-equal` (after each scenario the state's doc JSON equals `parse(serialize(doc))` computed by
    Python — pass the expected JSON in from the runner for three fixed scenarios).
  - `undo:tab` — `undo` after `listTab` restores the document.
- [ ] **Step 2: Run** `../../.venv/Scripts/python.exe -m unittest tests.test_book_format -v` — FAIL (no file).
- [ ] **Step 3: Implement `book-format.js`'s first half** as a classic script in the style of `book-text.js`
  (`(function (root) { … })(typeof window !== "undefined" ? window : globalThis)`), pure helpers and commands only;
  commands use `tr.setNodeMarkup`, `tr.setBlockType`, `tr.split`, `tr.lift`, `tr.wrap` and never need `findWrapping`.
  Typing rules apply only to a `paragraph` whose parent is the doc, never when `doc.attrs.form === "poem"`.
- [ ] **Step 4: Run** the test — PASS; the full suite — PASS.
- [ ] **Step 5: Commit** ("Book editor: list commands, typing rules and markers (book-format.js)").

### Task 7: `book-format.js` — alignment, text style, size, marks, clear formatting

**Files:**
- Modify: `studio/static/book-format.js`, `tests/js/book_format.js`
- Test: `tests/test_book_format.py`

**Interfaces:**
- Consumes: Task 6.
- Produces: `commands.setAlign(align | null)`, `commands.setTextStyle("paragraph" | "heading" | "subheading" |
  "quotation")`, `commands.quote(dir: 1 | -1)` (Ctrl+] / Ctrl+[ outside lists), `commands.stepSize(dir: 1 | -1)`,
  `commands.setSize(size | null)`, `commands.toggle(markName)`, `commands.clearFormatting`;
  `current(state) -> {text, list, align, size, marks: {strong, em, underline, strike, smallcaps}}`;
  `applies(state) -> {text, list, align, size, style}` (booleans, per the spec's panel rules);
  `KEYS: Array<{id, label, key, group, run: (T) => void}>` — one row per command of the spec's key table, plus
  rows without a key for lettered, capital-lettered, roman, small-roman lists, Normal size and
  *Make a list of these lines* (`commands.listFromMarkers`: selected top-level paragraphs that start with a typed
  marker — `•`, `-`, `1.`/`1)`, `a.`, `A.`, `i.`, `I.` and a space — become items of that style, the marker removed,
  levels 0);
  `keymap(T) -> object` for `book-text.js` (`Mod-u`, `Alt-Shift-5`, `Mod-Shift-k`, `Mod-Shift-.`, `Mod->`,
  `Mod-Shift-,`, `Mod-<`, `Mod-Space`, `Mod-Alt-0/2/3`, `Mod-Shift-7/8`, `Mod-]`, `Mod-[`, `Mod-Shift-l/e/r`,
  `Alt-o` (macOS `Ctrl-Alt-o`)); every key returns true in the text even when it doesn't apply.

- [ ] **Step 1: Add scenarios:** `align:wrap` (centre a paragraph → `aligned` center holding it), `align:join`
  (centring the next paragraph joins it), `align:switch` (right on one paragraph of three in a centre block → centre,
  right, centre), `align:off`, `align:not-items` (`setAlign` false on a list item or heading);
  `style:heading` (paragraph and list item → heading 2; from inside `aligned` and `blockquote` it lifts first; a
  middle item made a heading keeps the numbers after it, as `enter:keep-numbers`),
  `style:paragraph` (heading → paragraph; quotation → lifted), `style:quotation` toggles;
  `size:step` (none → large → x-large → x-large; down to x-small; Normal via `setSize(null)`; empty selection sets
  the stored mark), `marks:toggle` for each of the five, `clear:keeps` (clears em, strong, underline, strike,
  smallcaps, size and the selected paragraphs' alignment; keeps idx, comment, lang, notes, cites),
  `applies:note-title-poem` (only size and style in a title; no list/align in a poem piece), `keys:table` (every
  `KEYS` key is bound in `keymap`), `undo:align`, `undo:size`, `markers:from-text` (`listFromMarkers` on paragraphs
  `• een`, `1\. twee` read from v1.2 Markdown, `a. drie` → items bullet, decimal, lower-alpha).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS, full suite PASS.
- [ ] **Step 5: Commit** ("Book editor: alignment, text styles, sizes, marks and clear formatting").

### Task 8: The writing window uses it — keys, bar, / menu, paste, look

**Files:**
- Create: `studio/static/book-format.css`
- Modify: `studio/static/book-format.js` (decorations plugin, `pasteLists(html)`), `studio/static/book-text.js`
  (plugins, keys, `enter` box list, `inlineRules` strike rule, `SLASH`, `slashItems`, `barButtons`, `SelBar.update`,
  `command`, `insert`, `cleanPaste`, `poemPasted`), `studio/static/index.html`, `tests/js/book_text.js`
- Test: `tests/test_book_text.py`, `tests/test_book_format.py`, browser

**Interfaces:**
- Consumes: Tasks 6–7.
- Produces: `BookFormat.plugins(T) -> Plugin[]` (marker decorations: `Decoration.node` with `data-marker` and
  `style="--bk-mw:<em>"`, the gutter width of the widest marker in the item's list; `numbersPlugin()`);
  `BookFormat.pasteLists(html: string) -> string` (HTML lists, Docs' `aria-level`, Word's `mso-list` → flat
  `<p class="bk-li" data-list data-level data-start>`; underline styles inside links dropped);
  `slashItems(query, features, form)`; `barButtons(features, {multi, inNote})` returning the spec's three sets with
  `["format", "Format"]` last; `T.command("format")` opens the panel (Task 9, via `root.BookFormat.openPanel?.(T)`);
  `BookFormat.clipboardText(slice) -> string` (book-text's `clipboardTextSerializer`: blocks on lines, list items
  led by their computed marker and two spaces of indentation per level).

- [ ] **Step 1: Update `tests/js/book_text.js`** expectations: `slashItems("", all, "prose")` ends with
  `bullets`, `numbers`; with `"poem"` they're absent; `barButtons(all)` ends with `Format`;
  `barButtons(all, {multi: true})` is `["bold", "italic", "format"]`; `barButtons(all, {inNote: true})` is
  `["bold", "italic", "source", "format"]`; add `strike:typing` (typing `~~weg~~` gives a strike mark) to
  `tests/js/book_format.js`. Run `../../.venv/Scripts/python.exe -m unittest tests.test_book_text tests.test_book_format -v` — FAIL.
- [ ] **Step 2: Integrate in `book-text.js`** (contained edits): `...BookFormat.inputRules()` in `blockRules`;
  strike in `inlineRules` (`markRule` with `~~`, length 2); keymap: `"Enter": chainCommands(F.listEnter, enter…)`,
  `"Tab": chainCommands(F.listTab, poemTab)`, `"Shift-Tab": F.listShiftTab`, `"Backspace": chainCommands(undoInputRule,
  F.listBackspace, linkedNeighbour(-1))`, then `...F.keymap(T)` (guarded by `!T.locked`); `N.aligned` joins the box
  types in `enter`; `...BookFormat.plugins(T)` in `plugins()`; `slashItems`, `insert("bullets" | "numbers")`;
  `barButtons` and `SelBar.update` (multi-block = `!sel.$from.sameParent(sel.$to)`); `cleanPaste` runs
  `BookFormat.pasteLists` first for any HTML with `<li` or `mso-list`; `poemPasted` turns list items into
  paragraphs led by their marker text.
- [ ] **Step 3: `index.html`:** `<link rel="stylesheet" href="/static/book-format.css">` after `book-tools.css`;
  `<script src="/static/book-format.js"></script>` between `book-schema.js` and `book.js`.
- [ ] **Step 4: `book-format.css`:** list items hang their marker in a gutter (`--bk-mw`), right-aligned for
  numbers and letters, centred for bullets, 1.5 em per level, all items of a list sharing one text edge;
  `.bk-align[data-align=center] p {text-align:center}` and right; `u` solid 1 px in the text colour, offset 0.12 em;
  `s` 1 px; sizes 0.75/0.875/1.2/1.44 em; light and dark from Studio's tokens.
- [ ] **Step 5: Run** the JS tests and the full suite — PASS.
- [ ] **Step 6: Browser check (controller):** scratch server, a throwaway memoir; type every trigger, Backspace,
  Tab/Shift+Tab, Enter on empty items, centre and right, sizes by key; paste a list from an HTML page; save, reload,
  compare; screenshots light and dark; measure marker alignment (`9.`/`10.`, `VIII.`) and the 360 px column.
- [ ] **Step 7: Commit** ("Book editor: lists, alignment and sizes in the writing window").

### Task 9: The format panel and the palette

**Files:**
- Modify: `studio/static/book-format.js` (`Panel`, `paletteActions`), `studio/static/book-format.css`,
  `studio/static/book-text.js` (`command("format")` only), `studio/static/book-tools.js` (palette group),
  `docs/DESIGN.md` (writing-window file list)
- Test: `tests/js/book_format.js` (pure parts), browser

**Interfaces:**
- Consumes: `current`, `applies`, `KEYS`, the commands (Task 7); `T.openPop`-style positioning (`T.page`, `T.over`).
- Produces: `BookFormat.openPanel(T)`, `BookFormat.paletteActions(T) -> Array<{label, hint, run}>` (only commands
  that apply, `hint` = key); the palette's `items()` gains a third group `["Format", …]`.

- [ ] **Step 1: Pure test** `palette:applies` — `paletteActions` for a state in a list item includes "Indent" and not
  "Centre"; in a poem piece no list commands. Run — FAIL.
- [ ] **Step 2: Implement the panel** as the spec draws it: rows Text, List, Align, Size, Style with their labels
  (`label` class), segmented buttons with `aria-pressed` for the current state, the Size ladder of five `A`s at
  their sizes (Normal in the middle), a footer naming the hovered or focused button and its key; rows that don't
  apply are left out; it opens under the cursor (above it when there's no room below), focus on the first row's
  current choice; arrows move, Enter/Space apply and close, Escape and a click outside close; focus returns to the
  text; it uses `T.over` and closes with `closePop`. `role="dialog"`, buttons in rows `role="toolbar"`.
- [ ] **Step 3: Palette:** `book-tools.js` `items()` returns `[["Pieces", …], ["Actions", …], ["Format", …]]` with
  `BookFormat.paletteActions(activePiece()?.text)`; `Format…` (Alt+O) is one of them.
- [ ] **Step 4: `docs/DESIGN.md`:** `book-format.js` in the writing-window file list.
- [ ] **Step 5: Run** all JS tests and the full suite — PASS.
- [ ] **Step 6: Browser check (controller):** the panel by mouse and by keyboard only; in a note, a title, a poem
  piece; the palette's Format group; screenshots light and dark of lists, alignment, sizes and the panel.
- [ ] **Step 7: Commit** ("Book editor: the format panel (Alt+O) and format commands in the palette").

---

## Tables and math (added the same night; spec sections "Tables in detail", "Math in detail", "Tables in the writing window", "Math in the writing window")

### Task 10: Tables in the dialect

**Files:**
- Modify: `studio/manuscript.py` (SCHEMA, `_markdown` enables `table`, reader, writer, `_ESCAPES` gains `|`,
  `_block_text`), `studio/books.py` (`_containers`), `studio/static/book-schema.js`, `studio/static/book-text.js`
  (`docWords`), `studio/static/book-tools.js` (`containersOf`)
- Test: `tests/test_manuscript.py`, `tests/test_books.py`, `tests/js/book_tools.js`

**Interfaces:**
- Produces: `{"type": "table", "attrs": {"header": bool, "align": [None | "left" | "center" | "right", …]},
  "content": [{"type": "table_row", "content": [{"type": "table_cell", "content": [inline…]}, …]}, …]}`; SCHEMA nodes
  gain `table, table_row, table_cell` after `page_break`. In `book-schema.js`: `table` (group block, `isolating`,
  attrs `header` default true, `align` default `[]`, content `table_row+`, toDOM `table.bk-table` › `tbody`),
  `table_row` (content `table_cell+`, `tr`), `table_cell` (content `(text | note | cite)*` — no `hard_break`; Task 14
  adds `math`; `td`, `isolating: true`); parseDOM for own tables and for pasted `table`/`tr`/`td`/`th` (a `th` row
  makes `header` true).

- [ ] **Step 1: Failing tests.** `SAMPLES` gains
  `"| Jaar | Plaats |\n| --- | :-: |\n| 1984 | Utrecht |\n| 1990 | *Gent*^[Een noot.] |\n"`,
  `"|  |  |\n| --- | --: |\n| a | b |\n"` (no header), `"Een pijp \\| in tekst.\n"`. `test_tables_normalise`:
  `"a | b\n--|--\nc | d\n"` → `"| a | b |\n| --- | --- |\n| c | d |\n"`; a row with 3 cells in a 2-column table is cut,
  one with 1 cell filled; `"| a |\n| --- |\n| x \\| y |\n"` keeps `x | y` as one cell; in a poem piece
  `"| a |\n| --- |\n"` stays lines. `test_counts_include_tables` (`"| een twee |\n| --- |\n| drie |\n"` → 3 words).
  `tests/test_books.py` `test_search_finds_table_cells`. `tests/js/book_tools.js`: `containersOf` lists cell texts.
- [ ] **Step 2: Run** `../../.venv/Scripts/python.exe -m unittest tests.test_manuscript tests.test_schema_parity tests.test_books tests.test_book_tools tests.test_book_text -v` — FAIL.
- [ ] **Step 3: Implement.** markdown-it's `table` rule gives `table_open`, `thead`, `tbody`, `tr`, `th`, `td` with
  `style="text-align:…"` per cell: read the column alignment from the header cells; a header row whose cells are all
  empty reads as `header: false`; inside quotations, epigraphs and notes a table flattens to one paragraph per row
  with its cells joined by ` | `.
- [ ] **Step 4: Run** the same command, then the full suite — PASS.
- [ ] **Step 5: Commit** ("Books: pipe tables in the dialect").

### Task 11: Tables in .docx export and import

**Files:**
- Modify: `studio/book_export.py`, `studio/book_import.py`
- Test: `tests/test_export.py`, `tests/test_import.py`

**Interfaces:**
- Consumes: Task 10's table node.
- Produces: export `_Writer.table(node, notes)` — `doc.add_table(rows, cols)` with style `Table Grid`, the header row
  bold and marked `w:tblHeader` (repeats on each page), each cell's paragraph aligned by its column, inline content
  through `inline()` (notes numbered as elsewhere); import: mammoth's `<table>` → a `table` block (a cell's
  paragraphs joined with a space; `th` cells or a `thead` first row make `header: true`, otherwise `header: false`).

- [ ] **Step 1: Failing tests:** exporting Task 10's first sample gives one Word table, 3 rows × 2 columns, row 1 bold
  with `tblHeader`, `Utrecht`'s paragraph centred, the note in a cell numbered and listed under *Notes*; importing
  `<table><tr><th>A</th><th>B</th></tr><tr><td><p>c</p><p>d</p></td><td>e</td></tr></table>` gives
  `"| A | B |\n| --- | --- |\n| c d | e |\n"`; a real .docx with a table built by python-docx imports as a table.
- [ ] **Step 2–4:** run `tests.test_export tests.test_import` (FAIL), implement, run (PASS), full suite.
- [ ] **Step 5: Commit** ("Books: tables in .docx export and import").

### Task 12: Tables in the writing window

**Files:**
- Create: `studio/static/book-table.js`, `tests/js/book_table.js`, `tests/test_book_table.py`
- Modify: `studio/static/book-format.js` (`applies`/`current` gain `table`; the panel's Table row; `KEYS` rows),
  `studio/static/book-format.css` (the table's look), `studio/static/book-text.js` (key chains, `/ Table`, node
  view), `studio/static/index.html`

**Interfaces:**
- Produces (`window.BookTable`): `commands.insertTable(cols = 3, rows = 2)`, `addRow(dir: -1 | 1)`,
  `addColumn(dir: -1 | 1)`, `deleteRow`, `deleteColumn`, `toggleHeader`, `setColumnAlign(align | null)`,
  `deleteTable`, `nextCell(dir: 1 | -1)` (Tab / Shift+Tab; Tab in the last cell adds a row), `cellEnter` (the cell
  below; in the last row a paragraph after the table), `cellBackspace` (in an empty table: select it, then delete);
  commands rebuild the table node (`tr.replaceWith`) and put the cursor in the right cell; `TableView` (node view:
  the table in a sideways-scrolling wrapper; the quiet *Table* button, shown only while the selection is inside,
  opens `StudioMenu.open` with the commands).

- [ ] **Step 1: Failing node scenarios:** `table:insert` (3 columns, header and two rows, cursor in cell 1),
  `table:tab` (Tab walks cells and adds a row at the end; Shift+Tab goes back), `table:enter` (down; last row →
  paragraph after), `table:rows-columns` (adding and deleting keep `align` the right length), `table:align`,
  `table:header`, `table:backspace-empty`, `table:no-poem` (no table in a poem piece), `undo:table` (one undo per
  command). Run `../../.venv/Scripts/python.exe -m unittest tests.test_book_table -v` — FAIL.
- [ ] **Step 2: Implement;** in `book-text.js` the `Tab`, `Shift-Tab`, `Enter` and `Backspace` chains try the table
  commands first; `Mod-Alt-ArrowUp/Down/Left/Right` add rows and columns; `/ Table` in prose pieces; the panel's
  Table row and the palette commands; CSS: hairlines between rows, the header row in the label style, no fills,
  cells aligned by column, cells at least 4 em wide.
- [ ] **Step 3: Run** the JS tests and the full suite — PASS. **Browser check (controller)** in light and dark.
- [ ] **Step 4: Commit** ("Book editor: tables (book-table.js)").

### Task 13: Vendor KaTeX

**Files:**
- Modify: `tools/package.json` (`"katex": "<exact version, published at least two weeks ago>"`),
  `tools/package-lock.json`, `tools/build_vendor.mjs` (copies `katex.min.js`, `katex.min.css`, the `fonts/*.woff2` and
  `LICENSE` into `studio/static/vendor/katex/`, and rewrites the CSS so it references only the woff2 files),
  `CONTRIBUTING.md` ("Rebuilding the vendored editor" names KaTeX); `packaging/studio.spec` only if static files are
  listed there (check how `vendor/prosemirror.js` gets in)
- Create: `studio/static/vendor/katex/` (committed), `tests/test_vendor.py`

- [ ] **Step 1:** `cd tools && npm install` (the npm registry only) and `node build_vendor.mjs`; rebuilding twice
  leaves every file unchanged; `prosemirror.js` comes out byte-identical to the committed one.
- [ ] **Step 2:** `tests/test_vendor.py`: the files exist, `LICENSE` is MIT, the CSS references no font file that
  isn't there; run it and the full suite — PASS.
- [ ] **Step 3: Commit** ("Vendor KaTeX <version> for math in books (<size> KB)").

### Task 14: Math in the dialect, counts, find, .docx

**Files:**
- Modify: `studio/manuscript.py` (`dollarmath_plugin(md, allow_space=False, allow_digits=False, allow_labels=False,
  double_inline=False)` for `_MD` and `_POEM_MD`; nodes `math` and `math_display` (SCHEMA: `math_display` after
  `table_cell`, `math` after `cite`); `$` in `_ESCAPES`; the writer; plain text skips math), `studio/static/book-schema.js`
  (`math`: inline atom `{tex}`, toDOM `span.bk-math[data-tex]`; `math_display`: block atom `{tex}`, toDOM
  `div.bk-mathd[data-tex]`; every inline content that admits `cite` admits `math`), `studio/books.py` and
  `book-tools.js` containers (math is one gap character, like a cite), `studio/book_export.py` (the source as
  `$tex$` / `$$tex$$` text in Cambria Math), `studio/book_import.py` (count `m:oMath` elements in the .docx and add
  `"warnings": ["This file has 3 equations; Studio doesn't import equations yet."]` to the proposal; the review screen
  in `book.js` shows `warnings` as a quiet line — check how the proposal is rendered)
- Test: `tests/test_manuscript.py`, `tests/test_export.py`, `tests/test_import.py`

- [ ] **Step 1: Failing tests.** `SAMPLES` gains `"Einstein schreef $E = mc^2$ en meer.\n"`,
  `"Een formule:\n\n$$\n\\int_0^1 x^2 \\, dx = \\frac{1}{3}\n$$\n\nEn verder.\n"`, `"Het kost \\$20 of \\$30.\n"`,
  `"| a |\n| --- |\n| $x$ |\n"`; `test_math_normalise`: `"Het kost $20 en $30.\n"` → `"Het kost \\$20 en \\$30.\n"`
  (text, not math), `"$ x $"` stays text; `counts("De som $a+b$ klopt.\n")["words"] == 3`; export: a run with text
  `$E = mc^2$` in font `Cambria Math`; import: the warning for a .docx whose document.xml holds one `m:oMath`.
- [ ] **Step 2–4:** run (FAIL), implement, run (PASS), full suite.
- [ ] **Step 5: Commit** ("Books: LaTeX math in the dialect, .docx and import").

### Task 15: Math in the writing window

**Files:**
- Create: `studio/static/book-math.js`, `tests/js/book_math.js`, `tests/test_book_math.py`
- Modify: `studio/static/index.html` (KaTeX's CSS and JS, `book-math.js`), `studio/static/book-text.js` (node views,
  input rules, `/ Math`), `studio/static/book-format.css` (or a new `book-math.css`)

**Interfaces:**
- Produces (`window.BookMath`): `inputRules()` (`$tex$` → `math` when the closing `$` follows a non-space and the
  opening `$` isn't escaped or followed by a space; `$$` + Enter in an empty top-level paragraph → `math_display`),
  `MathView` (inline and display node views: `katex.render(tex, el, {throwOnError: false, displayMode})`; the source
  field under it on click or Enter, live preview, Enter / Ctrl+Enter / Escape / a click outside close it, an empty
  source removes the node, the rendering has `spellcheck=false`).

- [ ] **Step 1: Failing node scenarios:** `math:typing` (`$x^2$` → math `x^2`; `$20 en $` stays text; `\$x$` stays
  text), `math:undo` (Backspace right after gives back the dollars), `math:display` (`$$` + Enter).
- [ ] **Step 2: Implement;** what KaTeX can't render shows its source in `var(--red)` with the message as `title`.
- [ ] **Step 3: Run** the JS tests and the full suite — PASS. **Browser check (controller):** inline and display math
  render, edit and undo; light and dark; the 360 px column.
- [ ] **Step 4: Commit** ("Book editor: LaTeX math rendered while writing (book-math.js)").

---

## Extras (spec "Later: three extras"; start only when Tasks 1–15 are built and reviewed)

### Task 16: Cards — a corkboard of the pieces

**Files:**
- Create: `studio/static/book-cards.js`, `studio/static/book-cards.css`
- Modify: `studio/static/book-editor.js` (a *Cards* switch in the binder head `.bb-head`, `renderBinder()` ~580; expose
  `move`, `saveContents`, `setEntry` and `openPiece` to `BookCards` through `BookEditor`), `studio/books.py`
  (`_contents`: `synopsis` is a string, control characters removed, at most 400 characters), `studio/static/book-tools.js`
  (palette action *Cards*), `studio/static/index.html`
- Test: `tests/test_books.py`, browser

**Interfaces:**
- Produces: `contents` entries may carry `"synopsis": str`; `window.BookCards = {show(W), hide(W), shown(W)}` — the
  cards replace the text page in `.bw-main` while shown; a card is the piece's title (italic kind for untitled),
  kind, status dot, words and its synopsis in a textarea (saved 600 ms after typing stops, and on blur, through
  `setEntry(file, {synopsis})`); drag a card to reorder (same `move()` as the list of pieces, so a part takes its
  pieces); clicking a card's title opens that piece and leaves the cards; auto pages show as small quiet cards that
  move but have no synopsis; Escape leaves the cards.
- [ ] **Step 1:** `test_synopsis_is_kept_and_cleaned` (a contents update with `synopsis` "Een\x07 korte\nsamenvatting"
  + 500 × "x" keeps `"Een korte samenvatting…"` cut to 400 characters; other entries untouched). Run — FAIL.
- [ ] **Step 2:** implement server and client; cards in a responsive grid (min 220 px), the book's text font for
  titles, label style for kind and words, hairline borders, no shadows; light and dark.
- [ ] **Step 3:** full suite PASS; browser check (drag, synopsis save and reload, open a piece, Escape, 360 px).
- [ ] **Step 4: Commit** ("Book editor: Cards, a corkboard of the pieces with synopses").

### Task 17: Every key in one sheet

**Files:**
- Modify: `studio/static/book-tools.js` (`writingKeys()`; the window keydown handler: `?` without modifiers when the
  focus is not in text, an input, a textarea or a contenteditable opens `window.KeysSheet?.open()`, else a fallback
  dialog), `studio/static/app.js` (the Info page's "Writing window keys" list reads `BookTools.writingKeys()` when it
  exists, ~1982), `tests/js/book_tools.js`
- **Interfaces:** `BookTools.writingKeys() -> Array<{group, key, label}>` — the window's own keys (palette, focus,
  find, replace, binder, Escape) plus every `BookFormat.KEYS` row with a key, plus `BookTable`/`BookMath` keys when
  loaded; part 2's Keys sheet can read the same function.
- [ ] **Step 1:** node check `keys:all` (`writingKeys()` contains Ctrl+K, Alt+O, Ctrl+Shift+E, Tab; no duplicates);
  run — FAIL. **Step 2:** implement; the fallback dialog uses `openDialog` with the keys grouped in two columns.
  **Step 3:** full suite; browser check (`?` in the binder opens it; `?` typed in the text types `?`).
  **Step 4: Commit** ("Book editor: every key in one place; ? opens the keys").

### Task 18: Make a design from this passage

**Files:**
- Create: `studio/static/book-passage.js`
- Modify: `studio/routes_books.py` (`POST /api/book/passage` `{b, text, src?}` → `{poem: "<Series>/<folder>"}`),
  `studio/static/book-text.js` (bar button `["design", "Design"]` for a selection in the text, not in notes; also for a
  selected linked poem; `command("design")`), `studio/static/book-tools.js` (palette action), `studio/static/index.html`,
  `tests/test_books_web.py`, `tests/js/book_text.js`
- **Interfaces:** the route: with `src` (a linked poem) → that poem; else the series *Book quotes* (made with the book's
  look on first use, through `Store.create_series`), a new poem in it titled from the passage's first words (at most
  eight, then "…"), lines = the passage's lines, `"source": {"book": b}` in poem.json. Client: `BookPassage.make(T)` —
  the selection's text (blocks as lines, no notes or citations), the route, then
  `Design.starter("page", fmt, {lines, title, fonts: book.style.fonts, palette: book.style.palette, signature})` for
  each format, `Design.mergeFormats`, `POST /api/design`, `pref.set("last." + poem, slug)`, and
  `location.hash = poemHash(poem, "design")`.
- [ ] **Step 1:** web test: POST a passage → the series and poem exist with the lines; a second passage makes a second
  poem; with `src` of an existing poem nothing is created. Run — FAIL. **Step 2:** implement. **Step 3:** full suite;
  browser check (select two lines → Design → the editor opens with the passage in the book's fonts).
  **Step 4: Commit** ("Book editor: make a design from a passage").
