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
Poems/<Series>/
  series.json                    tagline, description, palette, fonts, signature, formats
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

- Binds 127.0.0.1 only, checks the Host and Origin headers, accepts JSON-only writes, and confines file paths to
  the `Poems` folder.
- The front end is plain JavaScript without a build step: `app.js` (pages), `editor.js` (Design tab),
  `design-core.js` (the renderer shared with exports), `menu.js` (context menus).

## Desktop

`studio/desktop.py` opens a pywebview window (WebView2, WebKit, or GTK/Qt) with Studio's icon and starts the
server in the same process unless one is running. Without a native backend it falls back to a Chrome app window,
then the browser. `studio install` adds a launcher; on Windows the shortcut carries an AppUserModelID, so the
window groups under a pinned taskbar icon. `packaging/studio.spec` builds `Studio.exe` (windowed) and
`studio-cli.exe` (console, for MCP) with PyInstaller.
