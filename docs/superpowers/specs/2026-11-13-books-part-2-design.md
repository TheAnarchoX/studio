# Books in Studio, part 2: the composer — design

*13 November 2026. Follows `2026-11-12-books-design.md` (part 1, shipped as v1.2.0), whose outline of part 2 was the
starting point. The author decided the PDF target and where the pages show; the rest are the builder's calls,
marked "(call)" with the reason, made after the author asked to skip further questions.*

## Why

Part 1 made a place to write a book. What the author still can't do is see the book: today's .docx export has a
plain title page and notes after each piece, the other generated pages (half-title, copyright page, contents,
notes, bibliography, index) are missing, and nothing has page numbers. A book of mixed
prose, poems and opinion, headed for print, is the case to get right. Part 2 makes Studio set the book as real pages, show them while the
author writes, and export a PDF a print-on-demand service accepts, with every generated page right.

Part 4 (Claude's tools for books) comes straight after this part, so every capability here sits in a service
module the interface and the future MCP tools share.

## Goals

1. **Pages.** The book set at its trim size (A5, 135 × 210 mm, 5.5 × 8.5 in, 6 × 9 in, custom): running heads,
   roman page numbers in the front matter and arabic in the body, chapters on right-hand pages, poems set as poems,
   hyphenation in the book's language (Dutch included), notes as footnotes or endnotes per the book's settings.
2. **Generated pages that are right:** half-title, title page, copyright page, contents, notes, bibliography (from
   `sources.json`), index (from the index terms), and for poetry an index of first lines.
3. **A preview that is the PDF:** big, zoomable pages and spreads in a Compose view, and a pages pane beside the
   text while writing; both redraw a moment after a save.
4. **PDF output** to print-on-demand specifications, plus **print checks**: widows and orphans, overfull lines,
   fonts, image resolution, page count and margins against the chosen printer.
5. **Spelling in several languages at once**: the book's language plus languages the author adds, and every
   `lang` span in its own language.
6. **Findable tools:** split view, the command palette, the pages pane and Compose are visible on screen, not only
   behind keys.
7. **.docx export** gains the generated pages in a simple form.

## Non-goals (this part)

- The cover (with the spine width from page count and paper): the next step after this part; the printer and
  paper settings here already feed it.
- PDF/X, CMYK conversion, crop marks, imposition. Typst writes PDF/A and PDF/UA, not PDF/X; IngramSpark recommends
  PDF/X-1a but accepts a high-quality PDF with embedded fonts. A conversion step can follow if a printer insists.
- Bleed in the interior: nothing in the manuscript can run off the page edge yet, so the interior has no bleed;
  the printer's bleed is kept for the cover.
- Drop caps: Typst can't flow text around a letter without a package; chapter openings get small capitals instead.
- Real Word footnotes and endnotes in .docx (the simple form lists notes as text, as part 1 does).
- A baseline grid, per-paragraph manual tweaks, EPUB.

## Anti-goals

- A preview that differs from the PDF. One engine makes both.
- User text reaching Typst as code. Every piece of user text is a Typst string literal; the compiler reads only
  its own staging folder in the cache (the generated source and the book's images), and never the network.
- A design panel full of options whose defaults don't already make a good book. The first preview of any book must
  look like a finished book.
- Export blocked by a warning. Checks inform; the author decides.
- Badges, flourishes, decorative "live" indicators.

## Constraints (from part 1, binding)

- Works equally well with and without Claude; nobody touches a config file.
- Typing is never lost; an open piece is never overwritten under the cursor (saves carry mtime → 409). The composer
  only reads pieces.
- Files are the database: atomic writes; Studio never rewrites a user's file on read. Book designs live in
  `book.json`; unknown keys are kept.
- Every book view escapes user text. Book images are served under `/bookfiles/`.
- A text column is never narrower than 360 px.
- Interface copy is plain, in sentence case, with no badges or flourishes.
- Nothing personal in the repo. Tests never touch the author's library or config (temp `STUDIO_CONFIG`,
  `STUDIO_ART`, `STUDIO_CACHE`; ports 4748–4766).

## Decisions

| Question | Decision | By |
|---|---|---|
| What the PDF is for | One interior PDF built to print-on-demand specs, checked against the printer chosen in the design: KDP, IngramSpark or *Other printer* (Dutch services and print shops). Exact trim size, no crop marks, fonts embedded, text in grey-scale black, images in grey, even page count, clickable contents, notes and index plus bookmarks, so it also serves as a reading copy. | Author |
| Where pages show | Both: a **Compose** view (big pages, zoom, the design panel, checks, export) and a **pages pane** in the writing window that shows the spread the cursor is on. | Author |
| Page engine | Typst through the `typst` Python package (0.15.2, pinned), compiled in the server process; one `Compiler` per open book, so a recompile after an edit is incremental. | Part 1, confirmed by a spike |
| Preview format | SVG per page, shown as `<img>` (sharp at every zoom; no script runs in an `<img>`), addressed by a hash of its content so unchanged pages come from the browser cache. | Call: all 183 pages of a test book render to SVG in 0.37 s against 1.7 s for PNG at 96 ppi, and PNG blurs when zoomed |
| Fonts in the PDF | Static instances cut from the families' files with fontTools (regular, italic, bold, bold italic at the text's optical size), cached on disk. | Call: Typst sets variable fonts only at their default instance (spike: only weight 400 was seen) |
| Citations and bibliography | Formatted in Python (one implementation for PDF and .docx), author-date, Dutch name particles kept ("van Dijk"). | Call: Typst's citation engine dropped the particle ("Dijk") and merges adjacent citations |
| Spelling engine | Hunspell 1.7 compiled to WebAssembly, in a Web Worker, with bundled dictionaries; decorations in the editor. | Call: Windows' own spell checker has no Dutch on this machine; a pure-Python Hunspell took over five minutes to load the Dutch dictionary; Hunspell in WebAssembly loads it in 75 ms and checks 3,000 words in 9 ms |
| Where the work is built | A worktree on branch `books-part-2`, merged with the author's go-ahead. | Call: the author's own Studio runs from the main checkout |

## Approaches considered

1. **Typst for everything (chosen).** Python turns the manuscript and the design into Typst source; Typst lays out
   the book (Knuth–Plass justification, hyphenation patterns for Dutch and many other languages, footnotes,
   introspection for page references), and the same compile gives the SVG pages and the PDF. Costs a 30 MB native
   dependency and a page image rather than live HTML in the preview.
2. **HTML and CSS paged media** (a paged-media polyfill in the window, Chrome's print to PDF). The preview would
   be live DOM, but justification is line-by-line, footnotes and cross-references across pages are weak, long books
   are slow to paginate, and the PDF would depend on Chrome being installed.
3. **Both:** HTML while writing, Typst for the PDF. Two engines means the preview lies about line breaks and page
   numbers, which is exactly what the author wants to see. Rejected.

## On disk

Nothing new in the book folder except what the author makes: `exports/` receives the PDF (dated, like the other
exports). The design is in `book.json`:

```json
"design": {
  "template": "literary",
  "trim": "135x210",
  "printer": "other",
  "paper": "cream",
  "margins": {"inside": 19, "outside": 15, "top": 18, "bottom": 23},
  "text": {"font": "Literata", "size": 10.5, "line": 14.5, "align": "justify", "hyphenate": true,
           "paragraph": "indent"},
  "headings": {"font": null, "size": 18, "case": "as-written", "number": "none", "sink": 42, "start": "right",
               "opening": "smallcaps"},
  "heads": {"verso": "title", "recto": "piece", "style": "smallcaps", "folio": "bottom-centre"},
  "poems": {"place": "optical-centre", "keepStanzas": true},
  "scene": "asterisks",
  "notes": {"size": 8.5, "pageRefs": true},
  "citations": {"style": "chicago", "list": "cited"},
  "pages": {"labels": {}, "contentsSections": false, "leaders": false, "setIn": true}
}
```

- `design` holds only what the author changed from the template; Studio resolves the rest from the template, so
  switching templates moves everything not set by hand. Lengths are millimetres; sizes points.
- `trim` is a preset id (`a5`, `135x210`, `5.5x8.5in`, `6x9in`) or `custom` with `width` and `height` in mm.
- Spelling adds `"spelling": {"languages": ["nl", "en"], "words": []}` to `book.json`: the first language is the
  book's; `words` is the book's own word list.
- `design.interior` is `grey` (default) or `colour`; with grey, images are converted for the preview and the PDF
  alike.
- Caches (not library files): `STUDIO_CACHE/typeset-fonts/` (cut instances), `STUDIO_CACHE/compose/<book>/` (the
  staging folder Typst compiles from: the generated source and copies of the book's images, grey ones for a grey
  interior, refreshed by modification time), and in memory the compiled pages.

## The composer

### Templates

A template is a full set of design values. A book's kind picks one by default (call: four are enough to cover the
six kinds):

| Template | Kinds | Character |
|---|---|---|
| Literary | memoir, fiction, essays | 10.5/14.5 pt, justified, indented paragraphs, chapters on right-hand pages with a deep sink and opening words in small capitals, running heads in small capitals |
| Nonfiction | nonfiction | as Literary with numbered chapters, sections in the contents, endnotes with page references |
| Academic | academic | 10/13.5 pt, footnotes at 8/10 pt, chapters on any page, numbered sections |
| Poetry | poetry | one poem per page start, poems optically centred, no running heads on poem openings, index of first lines |

Default trim: 135 × 210 mm for books in Dutch and other European languages, 5.5 × 8.5 in for English (call: the
usual trade sizes). Default text font: the book's look's text font; headings in the same family (call: book
convention; the look's display font is one choice away).

### Page rules

- **Margins** default to proportions of the trim (inside 14 % and outside 11 % of the width, top 8.5 % and bottom
  11 % of the height; 135 × 210 gives 19/15/18/23 mm). The printer's minimum inside margin for the page count is a
  print check, not a silent change.
- **Type:** size over line pitch ("10.5/14.5"), set exactly: Typst's text edges are fixed to 1 em so the pitch
  is the stated one. Justified with hyphenation in the book's language; `lang` spans hyphenate in theirs. Typst's
  widow and orphan prevention is on. Paragraphs indent 1 em except after a heading, scene break, epigraph or poem,
  or are spaced (a design choice).
- **Order and sides:** page 1 is a right-hand page. Half-title (i), blank, title page (iii), copyright (iv),
  dedication and epigraph pieces on right-hand pages, contents on a right-hand page, front-matter pieces each on a
  new page, then the body: each part on a right-hand page with a blank back, each chapter on a right-hand page
  (or the next page, per the design). Back matter follows the same rule as chapters. The total is made even with
  blank pages at the end.
- **Page numbers:** roman (lowercase) from the half-title, printed only from the contents onwards; arabic from 1 at
  the first piece of the body as the list of pieces groups the book (a prologue or introduction placed before
  chapter 1 counts from 1; foreword and preface stay in the front matter), always on a right-hand page. None on
  blank pages, half-title, title page, copyright page, dedication, epigraph and part pages; on chapter openings only
  at the foot.
- **Running heads:** verso the book title (or author, or none), recto the piece's title (for generated back pages
  their label); none on openings and the pages that have no number.
- **Poems** (`poem` form and `::: poem`): lines kept, no justification, no hyphenation; the block placed so its
  longest line is centred (optical centre) or at the text's left edge; a line too long for the measure wraps with
  a hanging indent; stanzas kept whole when they fit on a page. A poem piece starts on a new page.
- **Epigraphs:** narrower measure towards the outside, italic as written, attribution set right after an em dash.
- **Scene breaks:** `* * *`, `⁂` or space (call: asterisks by default, since a space break disappears at a page
  break).
- **Images:** their width as a share of the measure, the caption beneath; never wider than the measure.
- Comments are never printed; `idx` marks print their text; small caps use the font's real small capitals.

### Generated pages

Each `auto` entry in the book's contents is set where it stands, so the author orders and removes them in the
list of pieces as before. An entry whose feature is off, and Notes, Bibliography and Index (or First lines) with
nothing to list (no endnotes, no source to list, no index terms, no poems), are left out: no page, no contents line,
nothing in the .docx; the checks say which, and Compose's contents shows such an entry as not in the pages. Labels come in the book's language (Dutch: Inhoud, Noten, Bibliografie, Register,
Deel; English: Contents, Notes, Bibliography, Index, Part) and can be renamed in the design.

- **Half-title:** the title alone in the upper third.
- **Title page:** title, subtitle, author; the publisher at the foot when set.
- **Copyright page** (left-hand, set at the foot, small): © year and author, edition, ISBN, NUR code for Dutch
  books (new `details.nur`), publisher, the rights notice (`details.copyright`, or a standard notice in the book's
  language when empty), and "Set in <font>" (design option, on by default).
- **Contents:** every piece after the contents page that has a title, plus the generated back pages; parts as
  group lines; sections (`##`) optionally; page numbers from the laid-out book (Typst resolves them, so they are
  always right); dot leaders optional. Pieces before the contents (dedication, epigraph) are left out.
- **Notes:** with `endnotes` (or `both`), the notes of every piece listed in order under the piece's title, each
  with its number and, by default, the page its reference is on; the number in the text and in the list link to
  each other. Numbering per piece or through the book follows `features.noteNumbering`, in footnotes too.
- **Bibliography:** the sources cited in the text (or all of `sources.json`, a design option), sorted by family name
  with particles placed the Dutch way ("Dijk, A. van"), formatted author-date for books, articles, chapters,
  web pages and reports.
- **Index:** every index term with the pages it is on, subentries under their term, page runs joined (12–14), letter
  groups, two columns; terms sorted ignoring case and accents. **First lines** (poetry): every poem's first line
  and its page.

### Citations

`[@key]`, `[see @key, p. 12]` and `[@a; @b]` print author-date in parentheses, the locator as written: "(see van
Dijk 2019, p. 12)" (Chicago), "(see van Dijk, 2019, p. 12)" (APA). Two styles, chosen in the design (call: covers memoir and popular nonfiction;
notes-style citations are a later addition for academic books). The same formatter serves the .docx export.

### Preview

- **Compose view** (`#/book/<id>/compose`, the *Compose* tab of a book):
  - Left: the book's contents, as in the list of pieces; clicking any entry, generated pages included, scrolls to
    its first page. The entry of the page in view is marked.
  - Middle: spreads (page 1 alone on the right) or single pages, on a neutral desk; zoom to fit width, fit page,
    real size (96 CSS px per inch × the page's size) and steps up to 400 %, Ctrl+wheel; page numbers beneath each
    page. Double-clicking a page opens the writing window at that paragraph.
  - Right: the design panel, sections Size and printer, Margins, Text, Headings and openings, Running heads and
    numbers, Poems, Notes, Generated pages; a template choice at the top with *Reset to template* per section.
    A change redraws the pages within a second or two.
  - Top: trim size, spreads or pages, zoom, *Check* (with the number of findings), *Export PDF*.
  - Foot: "214 pages · set in 0.8 s", or Typst's error in plain words with the last good pages kept.
- **Pages pane** in the writing window: *Pages* in the status bar (and the palette) opens the spread holding the
  cursor's paragraph in the second-pane slot (so split view and the pages pane alternate); it redraws after each
  save and follows the cursor; clicking a page opens Compose there. It closes itself, with a short note, when the
  window is too narrow to keep the text column at 360 px.
- Page ↔ text mapping: every top-level block of every piece carries an invisible position marker in the Typst
  source; one query after each compile gives the page of each block.

### PDF

*Export PDF* (Compose, the book's settings, the palette, the shelf menu) compiles the book, embeds the fonts
(subset), writes black as grey (Typst writes one-channel ICC grey, value 0, which prints as 100 % K), uses the
grey copies of the images for a grey interior, sets document title, author and language, writes bookmarks for the pieces, and keeps a dated copy
in `exports/` like the other exports. Before exporting, the dialog shows the latest checks' summary with *Export
PDF* and never blocks.

### Printers

`studio/printers.py` holds one profile per printer: trim sizes it prints, bleed (for the cover), minimum margins
(the inside one by page count), page-count limits and multiple, paper thicknesses for the spine, and a link to the
service's specification page. The numbers are verified against the services' pages while building and dated in
the file. *Other printer* asks only for what can't be assumed (call): minimum margins 10 mm, even page count.

### Print checks

Run from *Check* in Compose and before a PDF export; results listed in Compose with page and piece, each one
opening its page (and, where it has one, its paragraph in the writing window). Settings for thresholds sit in
`book.json` `checks`, which part 1 already reserves.

| Check | How |
|---|---|
| Widows and orphans | paragraph start and end markers: a paragraph that leaves one line at the foot or carries one line to the next page |
| Short last pages | a piece whose last page holds fewer than four lines (setting) |
| Overfull lines | the pages rendered as PNG and measured like `qa.py` measures a carousel: ink beyond the text block's edge |
| Fonts | each font embeddable (OS/2 `fsType`), every character of the text present in the font that sets it, real small capitals where small caps are used, no fallback font used |
| Images | effective resolution at the printed size: below 300 ppi a warning, below 200 a failure; colour images noted (printed in grey) |
| Page count and margins | within the printer's limits; inside margin at least the printer's minimum for this page count; trim size offered by the printer |
| Generated pages | notes on but no Notes entry; citations of keys not in `sources.json`; index on but no Index entry; an empty contents; for the record, each generated page left out and why |
| Typst warnings | passed through in plain words |
| Pieces not final | listed for information |

## Spelling in several languages

Settings → Spelling (one language for the whole window, WebView2) stays for everything outside the book text.
Inside the book text Studio checks spelling itself:

- Hunspell (WebAssembly, vendored like ProseMirror: `tools/` builds `studio/static/vendor/hunspell.js`, Hunspell
  under its MPL 1.1 option, the wrapper MIT) runs in a Web Worker. Dictionaries bundled under
  `studio/static/dictionaries/<lang>/` with their licences: Dutch (OpenTaal, BSD/CC BY 3.0) and English (SCOWL,
  en-US and en-GB). Other languages come later, as a download into the cache on demand (call: several common
  dictionaries are GPL-licensed and can't be bundled in an MIT repository, and Dutch and English cover the first
  book); until then a span in another language is left unchecked.
- A word is right when any of the book's spelling languages knows it, or it is in the book's word list. A `lang`
  span is checked in its own language only. Notes are checked like the text.
- A misspelt word gets the familiar wavy red underline. Right-click: up to five suggestions, *Add to this book's
  words*, *Ignore*; the book's settings get a Spelling section (languages, word list).
- The editor's own `spellcheck` is off where Studio's checker covers the language, so nothing is underlined twice;
  for a language without a dictionary the window's own spelling stays on.
- Default for a new or existing book: its language, plus English for books in another language (call: the author
  asked for mixed-language checking; English loanwords are the common case in Dutch prose).

## Findable tools

- The book's header in the list of pieces becomes three tabs: **Write · Compose · Settings**.
- Status bar, left: *Pieces · Split · Pages*; right: the writing tools as now, then *Commands* (Ctrl+K).
- Right-click a piece: *Open beside* (Alt+click).
- Generated pages in the list of pieces open in Compose (today they do nothing).
- A *Keys and tools* sheet (Ctrl+/, the palette and the Info page) lists every tool and its keys.
- The rail's icons get their names beside them when the rail is open (call: tooltips alone hide four panels).

## .docx and Markdown export (simple form)

- .docx: half-title, title and copyright pages as in the PDF; a contents field (Word fills it on opening); notes
  per `features.notes`: endnotes listed at the back under their pieces, footnotes after each piece as in part 1;
  the bibliography from the shared formatter; the index as Word index fields at the index terms plus an index
  field where the index stands.
- Markdown: a YAML block at the top (title, subtitle, author, lang, date) so Pandoc reads it.

## Server

New modules:

| Module | Role |
|---|---|
| `studio/typeset.py` | manuscript documents and the design → Typst source. Pure functions, no I/O. |
| `studio/citations.py` | author-date citations and bibliography entries from CSL-JSON (moves `cite_text` here). |
| `studio/typeset_fonts.py` | static instances of a family for a design, cached in `STUDIO_CACHE/typeset-fonts/`. |
| `studio/compose.py` | **the service:** design (templates, validation, merge), compiling (one job per book, a `Compiler` per book), pages, locating, PDF export, the hooks part 4 wraps. |
| `studio/printers.py` | printer profiles. |
| `studio/preflight.py` | the print checks. |
| `studio/routes_compose.py` | the endpoints below. |

Endpoints (same local-only checks as the rest):

| Endpoint | |
|---|---|
| `GET /api/book/design?b=` | resolved design, the stored changes, templates, trims, printers, the fonts list |
| `POST /api/book/design` `{b, changes?, template?, reset?}` | change the design; returns it resolved |
| `GET /api/book/pages?b=` | compiles when the book changed; `{signature, pages: [{hash, folio, side, entry, blank, shown}], blocks, seconds, warnings, error, count, width, height, paper, left: [{entry, why}]}` |
| `GET /api/book/cutting?b=` | the families being cut for print while the book's pages wait for them (`{families}`), answered at once |
| `GET /api/book/page?h=` | one page as SVG, cached for good (the hash changes with the page), under a policy that lets it run and fetch nothing |
| `POST /api/book/preflight` `{b}` | runs the checks; the report |
| `POST /api/book/export` `{b, format: "pdf"}` | the PDF, with a dated copy in `exports/` |
| `GET /static/dictionaries/<lang>/…` | the bundled dictionaries (static files) |

### Hooks for part 4

Part 4's MCP tools wrap `compose.py` and `preflight.py` the way `render` and `qa` wrap `making.py`; no logic lives
in the tools. The MCP server runs in its own process, so nothing here depends on the web server's memory: each
process compiles for itself, and a lock file in the book's staging folder lets one process compile a book at a
time (another waits up to 60 s, then gets "<book> is being set in another window; try again in a moment").

| Tool (part 4) | Function |
|---|---|
| `get_book_design` | `compose.get_design(books, book)` → `{design, stored, templates, trims, printers, fonts}` |
| `set_book_design` | `compose.set_design(books, book, changes=None, template=None, reset=())` → the same as `get_design` |
| `render_pages` | `compose.render_pages(books, book, pages=None, fmt="png", ppi=96)` → PNG bytes per page, 1-based `pages` (the app uses SVG) |
| `export_pdf` | `compose.export_pdf(books, book, now=None)` → `{name, path, pages, size}`; `path` is the dated copy in `exports/` |
| `preflight` | `preflight.run(books, book)` → `{summary, items: [{check, level, message, page, file, block}], pages, at}` |
| (spelling) | the book's word list through `books.update(book, {"spelling": …})` |

## Front end

New files: `book-compose.js` (Compose view, design panel, checks), `book-pages.js` (the page viewer used by Compose
and the pages pane), `book-spell.js` and `book-spell-worker.js`, `book-compose.css`. Changes: `book-editor.js`
(tabs, status bar, pages pane slot, generated pages clickable), `book-tools.js` (palette actions, keys sheet,
*Open beside*), `book.js` (PDF in the export lists, Spelling and NUR in the settings), `book-rail.js` (labels).

## Testing

- `tests/test_typeset.py`: escaping (user text with `#`, `[`, `"`, `\`, `<`, `@`, `$` prints literally); every
  dialect node; notes numbered per piece and per book; endnotes grouped; index terms collated and subentries
  nested; contents entries. Compiled with Typst and read back through queries: chapters start on odd physical
  pages, folios roman then arabic, the contents' page numbers equal the pages the pieces start on, every index
  page number is a page the term is on.
- `tests/test_citations.py`: particles, prefixes and locators, both styles, each source type, unknown keys.
- `tests/test_compose.py`: template resolution and validation, unknown keys kept, incremental compile, page hashes
  stable for unchanged pages, the PDF's page size equals the trim, fonts embedded, no RGB colour in the text.
- `tests/test_preflight.py`: a book made to have a widow, an overfull line (a long URL), a 72 ppi image, a
  character missing from the font, too few pages for KDP.
- `tests/test_typeset_fonts.py`: instances have the right weight and style, are cached and reused.
- Spelling: the worker checked under Node when present (Dutch and English words, a `lang` span), dictionary
  licences present.
- Browser: Compose on a scratch book (spreads, zoom, every design section, checks opening their pages, PDF export),
  the pages pane following the cursor, the tabs and status bar; alignment measured on rendered pages (text block
  edges across a spread, folio centring), as the author notices misalignment at once.

## Risks

- **Book size:** a 300-page book compiles in about a second on this machine; pages are fetched lazily and cached
  by hash. A slower machine shows "Setting the pages…" and keeps the last good pages.
- **Font instancing** takes about 3.5 s per face once (some 18 s for a new family, weight or optical size); it runs
  on first use and is cached, and while it runs the viewer says "Preparing Literata for print (once)…".
- **The packaged app** grows by about 30 MB (Typst's native module); PyInstaller needs it collected and the frozen
  app checked compiling a book.
- **Printer numbers change:** profiles carry the date they were checked and a link.
- **Typst upgrades** can change layout: the version is pinned, and tests compile real books.

## After this part

The cover (in Studio's design editor at the book's trim size with the spine from the page count and paper, a cover
PDF with bleed), then part 4 (Claude's tools), then part 3 (the research board).
