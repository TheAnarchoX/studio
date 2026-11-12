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
  drafts/<piece>/<stamp>.md      snapshots
  editions/<date name>/          frozen copies
  exports/                       .docx, Markdown, zip
Books/.trash/                    deleted books and pieces
```

## Route tables

`studio/routes.py` holds the web API as tables: `@routes.get(path)`, `@routes.post(path)` and
`@routes.get_prefix(prefix)` register handlers in `routes_*.py` (`routes_update`, `routes_styles`,
`routes_making`, `routes_books`). `Handler` in `web.py` dispatches to them, so every endpoint keeps the Host check, and every
POST the Origin and JSON-only checks. Handlers reply with `h._send` and raise `StoreError` for a 400.

## Books

- **Store:** `studio/books.py` reads and writes the folders above (atomic writes, `folder_name(title)` for folder and
  file names, piece history, editions, search and replace across a book). A save carries the file's mtime and gets a
  409 when the file changed since, so a piece open in an editor is never overwritten under the cursor.
- **Manuscript dialect:** plain Pandoc-compatible Markdown with a few extensions (notes `^[...]`, citations `[@key]`,
  spans `[text]{.idx}` and `{.comment}`, `:::` blocks for epigraph, poem, linked poem and page break). It has one
  implementation, `studio/manuscript.py`, built on `markdown-it-py` and `mdit-py-plugins`, which parses to and
  serializes from a document tree and normalises everything to one canonical form. The dialect's table is in the
  books spec.
- **Import and export:** `book_import.py` (.docx through `mammoth`, then into the dialect; Markdown files) and
  `book_export.py` (.docx with `python-docx`, Markdown).
- **API:** `routes_books.py`: `/api/books`, `/api/book`, `/api/book/piece`, `.../history`, `.../restore`, `.../edition`,
  `.../export` (a POST: it also writes a dated copy into `exports/`), `.../search`, `.../replace`, `.../sources`,
  `.../image`, `.../import`; a book's images are served under `/bookfiles/<book>/images/<name>`.
- **Writing window** (plain scripts, loaded after `app.js`): `book.js` (the shelf, book settings, the page frame),
  `book-schema.js` (the ProseMirror schema for the dialect), `book-text.js` (the text column: marks, `/` menu,
  notes in the margin, citations), `book-editor.js` (the list of pieces, piece loading and saving),
  `book-rail.js` (outline, sources, history, comments, find) and `book-tools.js` (the second pane, command palette,
  focus mode, style-sheet checks, echo finder, counts).
- **Vendored editor:** ProseMirror is bundled into one file, `static/vendor/prosemirror.js`, which is committed;
  there is no build step at runtime. Rebuild it only when you change `tools/vendor-entry.js` or
  `tools/package.json`; the steps are in CONTRIBUTING.md.

## Updates

`studio/updater.py` asks the GitHub releases API once a day (never raises, retries after an hour on error) and
compares versions. `install_kind()` is `frozen`, `source` (a git checkout) or `package`. Applying an update
pulls and runs `pip install` for a source install; a frozen Windows build downloads
`Studio-windows-x64.zip` and swaps its files after the app exits, then restarts. Requests carry only
`User-Agent: Studio/<version>`. The endpoints are in `routes_update.py`; the UI is Settings → Updates and the
Info page.

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
  `/files/` serves only from the `Poems` folder, `/bookfiles/` only images of real books in `Books`.
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
