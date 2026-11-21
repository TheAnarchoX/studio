# How Studio fits together

Studio is a local app for writing poems and making their artwork, with tools that let Claude do part of the
making. This page explains the moving parts for anyone changing the code.

## Shape

- **Data** is plain files in the library folder (`Poems/<Series>/<Poem>/`). No database: the app, the user and
  Claude read and write the same files, so each can see what the others did.
- **Two entry points, one core:**
  - `studio app` / `studio web` serve the web app on `http://127.0.0.1:4747` (in a native window via pywebview,
    or in a browser).
  - `studio mcp` is the MCP server over stdio. Claude starts it itself and may run several, so it doesn't host
    the web app; the two meet in the files.
- The web app polls a cheap change stamp every 2 s, so renders made by Claude appear while you watch.
- Settings live in a per-user config file (`studio/config.py`), never in the code.

## Files

```
Styles/                          looks/, palettes/, fonts/<Family>/, rules.md (the library's styles)
Poems/<Series>/
  series.json                    tagline, description, palette, fonts, signature, formats, checks
  README.md, CONCEPTS.md         rules and concept catalogue (read by Claude)
  _kit/                          the series' renderer (optional, see KITS.md; Studio never edits it)
  stamps/<slug>.json             reusable layers for the Design tab
  <Poem>/
    poem.json                    title, slug, number, author, lines, slides, status
    drafts/2026-11-12T0310.md    one file per saved version ("# Title", blank line, the poem)
    writing-notes.md             the poet's notes
    BRIEF.md                     Claude's brief for the carousel
    NOTES.md                     posting notes and alt text
    qa.json                      the last QA report
    designs/<slug>.json          Design tab files
    Design renders/<slug>/       their exports
    <slug>.html, Carousel …/     the kit's preview page and PNGs
```

- Writing notes are `writing-notes.md`, not `notes.md`: on Windows and macOS `notes.md` and `NOTES.md` are the
  same file. Likewise exports go to `Design renders/`, not `Designs/`, which would be `designs/`.
- `status` is `draft | ready | in review | approved | exported`. Missing means inferred (`in review` when renders
  exist, else `draft`). Rendering a `ready` poem moves it to `in review`.
- Saving a draft writes `drafts/<YYYY-MM-DDTHHMM>.md` and the text into `poem.json`. A second save in the same
  minute replaces that minute's file; an unchanged text isn't saved. The first save of a poem without drafts
  snapshots its existing text first.
- `poem.json` is written in a compact, hand-editable style (one slide per line).
- Deleting moves things to `Poems/.trash/`.

Books live next to `Poems/`:

```
Books/<Book>/
  book.json                      title, kind, features, order (front, body, back), goals; unknown keys are kept
  manuscript/<piece>.md          one Markdown file per piece
  images/, sources.json          images used in the text, the bibliography (CSL-JSON)
  .studio/days.json              words written per day (the daily goal)
  suggestions.json               Claude's suggestions, waiting for the author
  .studio/books.lock             lock around suggestions.json and sources.json writes
  drafts/<piece>/<stamp>.md      snapshots
  editions/<date name>/          frozen copies
  exports/                       .docx, Markdown, zip
  research/                      this book's board (see Research board below)
Books/.trash/                    deleted books and pieces
Research/                        the shared board, same layout as a book's research/
```

## Route tables

`studio/routes.py` holds the web API as tables: `@routes.get(path)`, `@routes.post(path)` and
`@routes.get_prefix(prefix)` register handlers in `routes_*.py` (`routes_update`, `routes_styles`,
`routes_making`, `routes_books`, `routes_research`). `Handler` in `web.py` dispatches to them, so every endpoint keeps the Host check, and every
POST the Origin and JSON-only checks. Handlers reply with `h._send` and raise `StoreError` for a 400.

## Books

- **Store:** `studio/books.py` reads and writes the folders above (atomic writes, `folder_name(title)` for folder and
  file names, piece history, editions, search and replace across a book). A save carries the file's mtime and gets a
  409 when the file changed since, so a piece open in an editor is never overwritten under the cursor.
- **Manuscript dialect:** plain Pandoc-compatible Markdown with a few extensions (notes `^[...]`, citations `[@key]`,
  spans `[text]{.idx}`, `{.comment}`, `{.underline}` and the sizes `{.x-small}`, `{.small}`, `{.large}`,
  `{.x-large}`, `~~strikethrough~~`, lists `- `, `1. `, `a. ` and `I.  `, `:::` blocks for epigraph, poem, linked
  poem and page break, and `::: center` / `::: right` around aligned paragraphs,
  Pandoc pipe tables `| a | b |` with a delimiter row that sets each column's alignment,
  LaTeX math `$x^2$` in the text and `$$` lines around display math). It has one implementation,
  `studio/manuscript.py`, with its list rules in `studio/manuscript_lists.py`, built on `markdown-it-py` and
  `mdit-py-plugins`, which parses to and serializes from a document tree and normalises everything to one canonical
  form. The dialect's table is in the books spec; lists, alignment, the newer marks, tables and math are in the book
  editor power spec.
- **Import and export:** `book_import.py` (.docx through `mammoth`, then into the dialect; Markdown files) and
  `book_export.py` (.docx with `python-docx`, Markdown).
- **API:** `routes_books.py`: `/api/books`, `/api/book`, `/api/book/piece`, `.../history`, `.../restore`, `.../edition`,
  `.../export` (a POST: it also writes a dated copy into `exports/`), `.../search`, `.../replace`, `.../sources`,
  `.../image`, `.../import`; a book's images are served under `/bookfiles/<book>/images/<name>`.
- **Writing window** (plain scripts, loaded after `app.js`): `book.js` (the shelf, book settings, the page frame),
  `book-schema.js` (the ProseMirror schema for the dialect), `book-text.js` (the text column: marks, `/` menu,
  notes in the margin, citations),
  `book-format.js` (lists, alignment, text styles, sizes and marks: their commands, keys and list markers),
  `book-panel.js` (the format panel, Alt+O, and the palette's Format group),
  `book-table.js` (tables: `/ Table`, rows and columns, the cell keys, the Table button and its menu),
  `book-math.js` (math: typing `$…$`, display math, KaTeX's rendering and the source field under it),
  `book-editor.js` (the list of pieces, piece loading and saving),
  `book-rail.js` (outline, sources, history, comments, find) and `book-tools.js` (the second pane, command palette,
  focus mode, style-sheet checks, echo finder, counts) and `book-suggest.js` (helpers, the Suggestions panel, the
  preview of a suggestion in the text).
- **Claude's book tools:** `mcp_books.py` registers `list_books`, `read_book`, `read_piece`, `search_book`,
  `list_sources`, `add_source`, `suggest`, `list_suggestions` and `withdraw_suggestions` on the MCP server. No tool
  writes manuscript text: `suggest` stores proposals in `suggestions.json`. `suggestions.py` is the shared service
  (the file, locating a suggestion in the current text, applying it, deciding); the app's
  `GET /api/book/suggestions` and `POST /api/book/suggestions/decide` use it. Writes to `suggestions.json` and
  `sources.json` take a lock file per book, `Books/<Book>/.studio/books.lock`, shared by the app and the MCP process.
- **Vendored editor:** ProseMirror is bundled into one file, `static/vendor/prosemirror.js`, which is committed;
  there is no build step at runtime. Rebuild it only when you change `tools/vendor-entry.js` or
  `tools/package.json`; the steps are in CONTRIBUTING.md.
  KaTeX is vendored by the same build into `static/vendor/katex/` (its minified script, style sheet and woff2 fonts).

## Research board

- **Store:** `studio/research.py` (`Research`: one board per book, plus the shared `Research/`). An item is one
  Markdown file, `<id>.md`; the id is the file stem and never changes. The front matter is YAML written as JSON values
  (`studio/frontmatter.py`, no YAML library; hand-typed plain strings, block lists and flow lists of plain values are
  read; unknown keys, maps, block scalars, comments and stray lines are kept and written back as typed).
  Kinds: note, quote, source, clip, image, piece, link. A quote's source is a citation key, found on the board, then
  the shared board, then the book's `sources.json` (`research_sources.py`).
- **board.json:** positions, sizes and frames only, merged by id so two writers keep each other's changes. Items with
  no entry are placed when read, and nothing is written on read. Files are in `files/`; deleted items and their files
  go to `.trash/`.
- **Locks:** every write takes a lock file in the board's folder (`msvcrt` on Windows, `fcntl` elsewhere), so the app,
  the MCP server and a second Studio process do not interleave writes. A save carries the file's mtime and gets a 409
  when the file changed since. Reads are cached by (path, mtime, size).
- **Clips:** `studio/clip.py`. Only `http` and `https`, no credentials in the URL, public addresses only (checked on the
  connected socket and again for every redirect), at most 5 redirects, 20 seconds and 10 MB. No cookies, no
  referrer, no `Accept-Language`, a plain `User-Agent`. The readable copy (`studio/clip_read.py`) is extracted with
  the standard library's HTML parser and written as Markdown. For the picture, the page is made script-free (scripts,
  handlers, frames and refresh
  removed, a Content-Security-Policy added) and photographed by headless Chrome (`shoot.py`) in a throwaway profile.
  Chrome goes through a small HTTP proxy on 127.0.0.1 that applies the same public-address rule to every request, for
  plain HTTP and for `CONNECT` tunnels, and drops cookies and referrer; refused requests get a 403.
- **API:** `routes_research.py`: `/api/research`, `.../boards`, `.../stamp`, `.../item`, `.../update`, `.../delete`,
  `.../restore`, `.../layout`, `.../move`, `.../image`, `.../clip`, `.../search`, `.../citable`, `.../use`,
  `.../reveal`. A board's images, pictures and PDFs are served under `/researchfiles/<board>/<file>`.
- **Front end:** `board-core.js` (pure helpers: frame membership, placement, the text a quote becomes), `board.js` (the
  board page, list and item panel), `board-canvas.js` (the canvas and undo), `board.css`, and `board-rail.js` /
  `board-rail.css` (the rail panel and dragging quotes into the text).
- The example book comes with a small board (a frame, a note, a source and a quote); it goes to the trash with the book.

### The composer

- **Modules:** `book_design.py` (templates, trims, `resolve` / `clean` / `reset` of the stored design), `typeset.py`
  (`lit()` turns every user string into a Typst string literal; the dialect's nodes as Typst), `typeset_book.py`
  (`book()` assembles the whole source: front matter, pieces, notes, bibliography, index, contents),
  `typeset_template.typ` (the one template, driven by a design dictionary), `typeset_fonts.py` (cuts font instances
  into `STUDIO_CACHE/typeset-fonts/`), `citations.py` (author-date citations, Chicago and APA, from `sources.json`),
  `printers.py` (printer margins and limits), `compose.py` (staging, compiling, pages, PDF, design calls),
  `preflight.py` (print checks), `routes_compose.py` (the API).
- **Staging:** Typst compiles from `STUDIO_CACHE/compose/<hash>/`, which holds the generated source and copies of
  the book's images (grey for a grey interior, refreshed by modification time). It is the compiler's root: no
  `#import`, no network, package paths point at an empty folder. A lock file there lets one process compile a book
  at a time. The compiled pages are kept in memory.
- **Page map:** every top-level block carries an invisible marker; one query after each compile gives the page and
  position of each block, so the editor and Compose can find each other and the checks can find a paragraph.
- **Checks:** `preflight.run` reads the compile and the markers; the last result is written to
  `.studio/preflight.json`.
- **Spelling:** `book-spell.js` talks to `book-spell-worker.js`, which runs Hunspell (`vendor/hunspell.js`, with its
  licence) over the dictionaries in `static/dictionaries/<lang>/`.
- **Packaging:** `packaging/studio.spec` names the composer modules, collects the `typst` package with its native
  library and ships `typeset_template.typ`; `static/` (dictionaries, vendor) is collected whole.

#### Hooks for part 4

Part 4's MCP tools wrap `compose.py` and `preflight.py` the way `render` and `qa` wrap `making.py`; no logic lives
in the tools. Each process compiles for itself; the lock file lets one process compile a book at a time (another
waits up to 60 s).

| Tool (part 4) | Function |
|---|---|
| `get_book_design` | `compose.get_design(books, book)` → `{design, stored, templates, trims, printers, fonts}` |
| `set_book_design` | `compose.set_design(books, book, changes=None, template=None, reset=())` → as `get_design` |
| `render_pages` | `compose.render_pages(books, book, pages=None, fmt="png", ppi=96)` → PNG bytes per page, 1-based |
| `export_pdf` | `compose.export_pdf(books, book, now=None)` → `{name, path, pages, size}` |
| `preflight` | `preflight.run(books, book)` → `{summary, items, pages, at}` |
| (spelling) | the word list through `books.update(book, {"spelling": …})` |

## Updates

`studio/updater.py` asks the GitHub releases API once a day (never raises, retries after an hour on error) and
compares versions. `install_kind()` is `frozen`, `source` (a git checkout) or `package`. Applying an update
pulls and runs `pip install` for a source install; a frozen Windows build downloads
`Studio-windows-x64.zip` and swaps its files after the app exits, then restarts. Requests carry only
`User-Agent: Studio/<version>`. The endpoints are in `routes_update.py`; the UI is Settings → Updates and the
Info page.

## Writing log

`studio/writing_log.py` keeps words written per day in `.studio/days.json` in each poem and book folder (`{"2026-11-13": 320}`);
`static/writing.js` draws the page (`#/writing`) and a section on Home (through `window.homeSections`). Rulings W1-W6 are in
`docs/superpowers/specs/2026-11-13-library-tools-design.md`, section 2.

- **Counting:** a poem's saved text adds the words gained (never negative); books add as they are written. A file Studio
  can't read is never overwritten. Nothing is stored beyond the day's count.
- **Endpoint:** `GET /api/writing` returns `{today, week_start, days: {iso: {poems: {id: n}, books: {id: n}}}, books: [{id, title,
  goal, first_day}], poems: {id: {title, series}}}`; existing books only, and not the examples (a series or book marked
  `"example": true`: adding them saves their text, which isn't writing).
- **Page:** summary line (today, this week Monday to Sunday, this month, this year), a Days, Weeks or Months control (kept
  as `writing.period`), a table of 30 days, 12 weeks or 12 months newest first with Poems, each book and a Total and a bar
  scaled to the largest, then the books with their daily goal and the poems' month. Numbers are right-aligned in tabular
  figures; the bars use a neutral token. No streaks, colours for good or bad days, or celebration.
- **Helpers:** `window.WritingLog` (dates in UTC, weeks from Monday, `periods`, `totals`, `summary`, `goalStats`) touches no DOM;
  `tests/js/writing.js` runs it in node.

## Backups

`studio/backup.py` keeps copies of the library's Studio folders; `static/backups.js` draws Settings → Backups
(through `window.settingsSections`, which `showSettings` renders before Updates) and the line on Home. The rulings
are in `docs/superpowers/specs/2026-11-13-library-tools-design.md`, section 1.

- **What:** `Poems/`, `Books/`, `Styles/` and `Research/`, whichever exist. Left out, because Studio can make them
  again or they were thrown away: `Design renders/`, a kit's renders in a poem folder (PNGs named `<slug>-…` and
  `<slug>.html`), `.trash`, `__pycache__`, `node_modules`, Studio's temp files and `*.partial`. Other folders and
  files in the library aren't backed up, and Settings names them with their size.
- **Format:** one zip per backup, `Studio backup 2026-11-13 0300.zip` (`-2`, `-3` within one minute), with paths
  relative to the library; files that are compressed already (images, PDFs, fonts, zips, .docx, .epub) are stored,
  the rest deflated. `studio-backup.json` inside
  holds the library path, the computer's name, when, the file count and size, a fingerprint (every path, size and
  time of the files it holds: one that couldn't be read is tried again by the next run), the skip rules, warnings, and the series, poems, books and pieces the restore dialog lists. A backup is
  written as `<name>.zip.partial`, synced, read back (every CRC and the manifest), then renamed; a `.partial` left by
  a crash is removed by the next run.
- **When:** only the app's own server (`web.serve` starts the scheduler; never the MCP server or the tests): a first
  check 60 seconds after Studio starts, then every 15 minutes. A check backs up when the fingerprint differs from
  this library's newest backup and that backup is at least a day old (an hour, for the first check after a start);
  otherwise it records "checked, nothing changed". *Back up now* always makes one. The `backups` setting turns the
  automatic runs off. One backup or restore runs at a time (a module lock; a restore waits up to 30 seconds for a
  backup), and a lock file in the folder (`.studio-backup.lock`: the computer and process id; let go at exit, stale
  once that process on this computer has ended, or after 2 hours) keeps two Studios apart.
- **Where:** `STUDIO_BACKUPS` in the environment, the `backup_folder` setting, else `Documents/Studio backups` in
  the home folder (`Studio backups` when there is no `Documents`). It must be outside the library and the library
  outside it; `config.save` refuses otherwise in a sentence. Free space is checked before writing (1.2 times the
  newest backup).
- **Kept:** after each successful backup, every backup of this library from the last 24 hours, plus the newest of
  each of the last 7 days, 4 weeks (Monday to Sunday) and 12 months that have one. Backups whose manifest names
  another library or another computer, zips Studio can't read, and files that aren't Studio's backups are never
  deleted.
- **Reading the library while you write:** a backup only reads. Each file is opened (on Windows through
  `CreateFileW` with read, write and delete sharing), read whole and closed at once, and zipped from memory; a file
  that changed while it was read is read again, up to 3 times. Measured on Windows 11: `os.replace` onto a file fails
  while any handle to it is open, even one opened with full sharing, so the backup never holds a file longer than
  the read itself (milliseconds for these files), and Studio's saves (`store.write_text`) retry a refused replace for
  a second. A save never fails because of a backup. The backup thread runs at background I/O priority.
- **Failures are told:** each outcome goes to `<cache>/backups/state.json` (the last success, the last failure as a
  sentence that names the folder and what to do, the last check, the last result). Settings shows it; while backups
  are on, Home shows one line (`brief()`) when the last run failed, or when nothing succeeded for 3 days (counted once
  this Studio's scheduler has made its first check: a Studio that was closed isn't failing).
- **Restoring never writes over anything:** a poem, book or piece comes back as a copy next to the current one
  (`<Poem> (restored 13 Nov 2026)`, with a slug of its own; a piece as `<stem> restored 2026-11-13.md` right after the original), in its
  place (the current one goes to `Poems/.trash` or `Books/.trash` first, after a confirmation; a poem keeps its kit
  renders and design exports), or, when it is gone, where it was. A whole backup is unpacked into a new folder next
  to the library, `<library> restored 2026-11-13 0300`, which Settings can then make the library. Every path in the
  zip is checked before anything is written (no absolute paths, drives, `..`, devices or links); files are unpacked
  into a hidden folder beside the destination and renamed into place. The writing log follows the writing: a copy
  leaves the backup's `.studio/days.json` out, a replace keeps the current one.
- **Endpoints** (`routes_library.py`): `GET /api/backups` (the settings, state and progress, the backups in the
  folder, what isn't backed up), `POST /api/backups/run` (answers when the backup has started), `GET
  /api/backups/items?name=`, `POST /api/backups/restore` (`{name, kind, ref, mode}`, or `{name, all: true}`), `POST
  /api/backups/reveal` (`{name}`, `{path}` or `{}`) and `GET /api/backups/brief` (Home's line). `backups` and
  `backup_folder` are saved through `POST /api/settings`.

## Search

`studio/search.py` keeps one index of the library in memory; `static/search.js` is the panel, its keys and the jumps.
The rulings (S1-S8) are in `docs/superpowers/specs/2026-11-13-library-tools-design.md`, section 3.

- **The index:** poems (title, text, `writing-notes.md`, `NOTES.md`), series (name, tagline), designs (name), books
  (title, subtitle) and pieces (title, text with captions, the text of notes), and research items through
  `research.Research(library).search` once `studio/research.py` exists. Not drafts, briefs, kits, bibliographies or
  trash. Each item keeps its fields as shown, the same fields folded (case and accents removed, per character, so a
  match maps back to the original text) and the (modification time, size) of its files. Every term of a query must be
  in the item; a term matches inside words; text in quotes is one term. Ranking inside a group: the title is the
  query, starts with it, holds every term, then the text, then notes; ties go to the newest.
- **Freshness:** nothing is written to disk. The index is built on first use (`POST /api/search/warm`, which the panel
  calls when it opens). A search whose last check is older than 3 seconds starts a check in the background (a walk
  comparing times and sizes, re-reading only what changed, swapped in with one assignment) and waits up to 150 ms
  for it. The reply says when the files were last checked (`checked`, local time), whether a check runs (`checking`)
  and how far the first read is (`building: {done, total}`); while either is true the panel asks again every 400 ms
  (20 times at most), and its footer says "Checking for changes…", "Reading the library… 1,200 of 5,000", or
  "Checked just now".
- **Endpoints** (`routes_library.py`): `GET /api/search?q=&kind=&limit=` (`kind` one group, `limit` 1 to 200, 8 by
  default) returns `{q, groups: [{kind, label, total, items: [{title, title_marks, where, href, field, field_label,
  snippet: {text, marks} | null, jump}]}], checked, checking, building, counts, errors}`; empty groups are left out,
  and the groups come in the order poems, pieces, books, series, designs, research. Every range (marks, a poem jump's
  `start` and `end`) counts UTF-16 code units, so the browser slices its strings with them as they are; it escapes
  each piece of text and puts the marks in by index. `POST /api/search/warm` starts the build or a check and returns
  the state.
- **The panel:** Ctrl+K anywhere but a book's writing window, or *Search* in the top bar. The input waits 120 ms after
  a key; an answer to anything but the newest request is dropped. ↓/Tab and ↑/Shift+Tab move, PageDown and PageUp by
  8, Enter opens (or shows all of a group, up to 200), Esc and Ctrl+K close and give the focus back. Every key in the
  panel stops there (`stopPropagation`), so the design editor's and the book's shortcuts never see it. The query and
  its results stay while Studio runs.
- **The jumps** (`LibrarySearch.go(result)`): the panel closes and `location.hash` becomes the result's `href`; then,
  for up to 3 seconds, a timer checks every 50 ms whether the page is drawn (not animation frames, which stop while
  the window isn't drawing). A poem's match is selected in `#title`, `#text`,
  `#notes` or the Art tab's posting notes (switched to Write), at the server's `start` when the text there is still the
  match, else at its first occurrence in any case, else the page simply opens; the field is focused and scrolled so
  the line shows (a long poem's line goes to the middle of the window). On the tab that is already showing the match the
  page isn't drawn again, so nothing typed there is lost. A design is opened by setting the editor's remembered
  design first (`studio.ed.last.<poem id>`). A piece opens in the writing window; the rail's Find gets the query, and
  the first match in the piece is selected through `BookTools` and `PM.TextSelection` and scrolled a third down. A
  click or a key while a page opens cancels the selection.
- **In a book** Ctrl+K stays the book's command palette (book-tools.js listens first, and search.js leaves a key the
  palette took). The palette's first action is *Search the library for "…"*, carrying what was typed; it is the one
  line of search in `book-tools.js` (`actions()`), and appears only when `window.LibrarySearch` exists.

## Fonts

`studio/fonts.py` is the font registry: one entry per family, read from the font files (axes, cap height,
licence, whether embedding is allowed). Sources, first wins: the library's `Styles/fonts/<Family>/` (your own
files and added Google Fonts, with an optional `family.json`), the bundled families in `static/fonts` described
by `families.json`, and fonts installed on the computer (indexed on demand). The registry writes the
`@font-face` rules (`/api/fonts.css`), serves files (`/fonts/...`) and tells `metrics.py` which file a text
layer uses. `save_design` refuses families the registry doesn't know.

## Styles and inheritance

`studio/styles.py` holds palettes, looks and house rules. Starters are bundled in `static/styles`; the library's
own are `Styles/palettes/<name>.json`, `Styles/looks/<name>.json` and `Styles/rules.md`. An own file with a
starter's name replaces it, and deleting that copy brings the starter back. A palette is named swatches, some
with a role (background, text, accent, muted); a look is a palette by name plus a font per role (display, text,
label).

Style resolves through levels: global, series, poem. A level may set a look, a palette (a name links to the
library; a list of swatches is an own copy) and fonts per role. What a level doesn't set, or names but the
library lacks, comes from the level above. **Detach** copies the inherited value into the level, **Link**
removes it again. 1.0 data (`series.json` palette lists, `voice`/`command` fonts) still reads. A series also
carries its own design checks (QA thresholds), and designs honour the series' formats. Endpoints are in
`routes_styles.py`; the UI is `static/styles.js`.

## Home and welcome

`studio/home.py` gathers recent items from SOURCES (callables returning `{kind, title, where, when, href}`)
and picks the one to continue. `static/home.js` draws it. A new install shows `static/welcome.js`, which can
add the Examples series from `studio/examples.py` (marked `"example": true`; removing moves it to `.trash`).

## Making carousels in the app

`studio/making.py` is the one place for rendering and measuring a kit's carousel: the Art tab (through
`routes_making.py`) and the MCP `render` and `qa` tools both call it. The Art tab chooses slides from the
series' concepts, writes the brief and posting notes, renders with progress, and runs QA. One job per poem runs
at a time.

## Carousels

`render` imports the series' `_kit/build.py` (fresh each call) and uses `build_html` for the self-contained
preview page, `shoot` for each PNG (in parallel, one Chrome profile per worker) and `contact_sheet` for the
overview. The tool returns the paths plus a downscaled contact sheet, so Claude sees the result.

## QA

For each slide and format, a **plate** is rendered: the same page with all text made transparent. Ink is every
pixel that differs from the plate. From the ink, per image:

- the ink box and margins (in 1080-wide slide pixels), and text touching the frame;
- rows of text and their left and right ink edges;
- alignment: edges within 1 px form a column; edges 1–10 px off a column are near misses;
- story safe zones (9:16: no ink in the top 280 px or bottom 330 px);
- the smallest row at phone width (430 px);
- that the unsigned image differs from the signed one only in the name.

The report goes back to Claude and is saved as `qa.json`; the Art tab shows a line per slide.

## Design editor

- A design is `designs/<slug>.json`: a background and a list of elements (`text`, `rect`, `ellipse`, `shape`,
  `line`, `path`). The full format is in `save_design`'s description in `studio/mcp_server.py`.
- It renders as HTML and SVG (`static/design-core.js`), like a kit, so variable font widths and tracking match
  the exports exactly. Text sits on its ink: letter edges come from the font files (`studio/metrics.py`,
  `/api/metrics`), and the cap height Chrome uses is measured in the page.
- Each design exists in 1:1, 4:5 and 9:16. Layout keys can be overridden per format (`e.at[fmt]`), and layers
  hidden per format (`e.hide`).
- Masks (`clip`, `clipInvert`) clip a layer to the one below it, like Krita's inherit alpha, via SVG clip paths.
- Exports render `static/render.html` in headless Chrome at 2× (`studio/shoot.py`). The MCP server runs a private
  web server for this, so it doesn't depend on the app running.

## Web server

- Binds 127.0.0.1 only, checks the Host and Origin headers, accepts JSON-only writes, and confines file paths:
  `/files/` serves only from the `Poems` folder, `/bookfiles/` only images of real books in `Books`,
  `/researchfiles/` only images and PDFs from a board's `files/` folder (never a dot-folder).
- The front end is plain JavaScript without a build step: `app.js` (pages), the `book*.js` files (books), `editor.js` (Design tab),
  `design-core.js` (the renderer shared with exports), `menu.js` (context menus).

## Desktop

`studio/desktop.py` opens a pywebview window (WebView2, WebKit, or GTK/Qt) with Studio's icon and starts the
server in the same process unless one is running. On Windows it starts WebView2 with `--accept-lang`: the language of
Settings → Spelling (`spelling` in the config: `auto`, the newest book's language, or a language tag) comes first,
because WebView2 checks spelling in the first language only, in the whole window. Without a native backend it falls back to a Chrome app window,
then the browser. `studio install` adds a launcher; on Windows the shortcut carries an AppUserModelID, so the
window groups under a pinned taskbar icon. `tools/design_regression.py` exports every design of a library
and compares pixels and metrics, for changes to the renderer or fonts. `packaging/studio.spec` builds `Studio.exe` (windowed) and
`studio-cli.exe` (console, for MCP) with PyInstaller.
