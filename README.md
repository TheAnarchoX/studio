<p align="center"><img src="studio/static/icons/icon-192.png" width="96" alt=""></p>

# Studio

A local studio for poems and their artwork. Write and keep drafts, lay out the poem as images for Instagram
and X in a full design editor, and let Claude render, measure and fix carousels through MCP tools.

Everything runs on your computer. Your poems are plain files in a folder you choose: no account, no database,
nothing uploaded. Studio, you and Claude all read and write the same files.

## Install

**Windows:** download `Studio-windows-x64.zip` from [Releases](https://github.com/TheAnarchoX/studio/releases),
unzip it anywhere (for example `%LOCALAPPDATA%\Programs\Studio`) and run `Studio.exe`. The first run adds Studio
to the Start menu; right-click its taskbar icon and choose **Pin to taskbar**. The executable isn't code-signed,
so Windows SmartScreen may ask you to confirm the first time (**More info → Run anyway**).

**From source (Windows, macOS, Linux):** you need Python 3.11 or newer and Git.

```bash
git clone https://github.com/TheAnarchoX/studio.git
cd studio
./install.sh
```

On Windows, run `powershell -ExecutionPolicy Bypass -File install.ps1` instead of `./install.sh`. Both make a
virtual environment in `.venv` and add a launcher with Studio's icon: the Start menu on Windows,
`~/Applications/Studio.app` on macOS, your app menu on Linux. Add `--desktop` for a desktop shortcut too.

Studio renders images with **Chrome, Chromium or Edge**, which it finds by itself. Set a different browser in
Settings if you need to.

On Linux, Studio opens in its own window when your Python has GTK or Qt bindings (`python3-gi` on most
distributions); otherwise it opens as a Chrome/Chromium app window, or in your browser.

## First run

Open **Settings** and choose your library folder (default: `~/Studio`). Studio keeps poems in its `Poems`
folder, one folder per series. Add your name as the signature. Then create a series and a poem from **New poem**.

Settings are stored per user, outside the code:

| | |
|---|---|
| Windows | `%APPDATA%\Studio\config.json` |
| macOS | `~/Library/Application Support/Studio/config.json` |
| Linux | `~/.config/studio/config.json` |

`studio config` shows them and `studio config library=/path/to/folder` changes one. The environment variables
`STUDIO_ART`, `STUDIO_PORT`, `STUDIO_CHROME`, `STUDIO_CACHE` and `STUDIO_CONFIG` override them.

## What's in it

- **Home:** the newest work across the library and one thing to pick up again.
- **Poems:** every poem as a card, with status filters and search.
- **Series:** a body of work with its own look, in `Poems/<Series>/series.json` (tagline, palette, typefaces,
  signature) next to the `README.md` with its rules. Tabs for its look, rules, concepts and details, and its own
  design checks (the QA thresholds).
- **Styles:** looks, palettes and fonts, set once for the library and refined per series and per poem. A palette
  has roles (background, text, accent, muted), can be taken from an image, and shows its contrast. Fonts: twelve
  bundled open-licence families, Google Fonts, your own font files and fonts installed on the computer. House
  rules apply to everything. A series or poem inherits the level above and can **Detach** into its own copy or
  **Link** back.
- **Write:** an editor that saves dated drafts, with writing notes and tools for the page: hinge words (words
  that recur, also inside other words), syllables, rhythm, counts, read aloud, focus mode and changes since any
  draft. **Ready for art** tells Claude the poem can be made.
- **Art:** the carousel in 1:1, 4:5 and 9:16, with and without your name, the brief, posting notes and a QA line
  per slide. You can choose the slides, write the brief and posting notes, render and run QA here without
  Claude (the series needs a kit, see below). Click an image for the viewer: step through every slide and design, copy, save, share, show it in
  its folder or open it in the editor.
- **Design:** a full-window editor. Each design exists in all three formats, and each format keeps its own layout.
  - Text set on its ink (aligned to the letters, not the font box), rectangles, ellipses, polygons, stars, lines,
    arcs and pen paths. Fills and outlines in flat colour or multi-stop linear and radial gradients.
  - Masks: select layers, right-click a shape and choose **Use as mask**. Masked layers sit under their mask.
  - Groups, marquee selection, drag-and-drop layers, alignment, even spacing and exact gaps, snapping.
  - **Name** marks the signature, which the unsigned export leaves out. **Show in** hides a layer per format.
  - **Stamps** are layers saved once and reused in any design of the series.
  - **Export** renders every format at 2× into `Design renders/<design>/`.
  - Right-click anything for its actions.
- **Books:** a writing window for whole books, next to poems. A list of pieces, a text column, a rail for outline,
  sources, history, comments and find, and focus mode. Notes, citations, index terms and comments are plain Markdown marks
  in the text. Import a .docx or Markdown file, freeze editions, export to .docx, Markdown or zip. See [Books](#books).
- **Research board:** notes, images, web clips, quotes and sources for a book, on a canvas or in a list, with frames,
  tags and search, and quotes you drag into the text with their citation. See [Research board](#research-board).
- **Updates:** Studio checks GitHub for a newer release once a day and updates from Settings → Updates. Source
  installs pull and reinstall; the Windows `Studio.exe` downloads the release and swaps its files. Nothing else
  leaves the computer, apart from Google Fonts when you browse or add them.
- **Backups:** Studio keeps copies of your poems, books and styles in a folder you choose (Settings → Backups), when
  it starts and then once a day when something changed, or at once with **Back up now**. It keeps every backup from
  the last day, then one a day for a week, one a week for a month and one a month for a year. Restore a poem, a book
  or a piece as a copy next to the current one or in its place (the current one goes to the trash first), or unpack
  a whole backup into a new folder next to the library: a restore never writes over anything. When backups fail or
  stop, Home says so in one line.
- **Writing log:** words written per day, week and month, for poems and books, on Home and on its own page
  (Writing log). Poems are counted when their text is saved, books as you write; the page lists the last 30 days,
  12 weeks or 12 months, each book's daily goal and how often it was met. It is kept in plain files, nothing leaves
  the computer.
- **Search:** Ctrl+K anywhere (or **Search** in the top bar) searches the whole library: poems (title, text, writing
  notes and posting notes), series, designs, books and their pieces, notes included. Case and accents don't matter
  ("cafe" finds "Café"), every word must be there, and a word is found inside longer ones. Results come in groups with
  the match marked, up to eight a group with **Show all**; ↑ and ↓ move, Enter opens. A poem opens with the match
  selected in its field, a design on the Design tab, a piece in the book's writing window with Find showing the query.
  Inside a book, Ctrl+K stays the book's command palette, and its first action searches the library for what you
  typed.
- **Light theme** in Settings → Appearance. A new install opens a short welcome with optional example poems.
- **Spelling** in Studio's own window: Settings → Spelling checks in the language of the book you wrote in last, or
  in one language you choose, everywhere in the window. It takes effect the next time Studio starts.
- Deleting moves poems, designs and stamps to a `.trash` folder.

## Books

**New book** (on Home or the Books page) asks for a title and a kind: fiction, memoir, nonfiction, academic,
poetry or essays. The kind sets the defaults for notes, sources and the index, and each can be switched on or off
in the book's settings. What is off disappears from the buttons, the `/` menu and the rail. Marks already in the
text are never deleted.

A book is a folder, `Books/<Book>/`, with one Markdown file per piece in `manuscript/`. The files are Pandoc
compatible and read well in any editor: `*italic*`, `**bold**`, `^[a note]`, `[@key, p. 12]` for a citation from
`sources.json`, `***` for a scene break, and `::: poem` blocks. Studio's reader and writer for this dialect are
in `studio/manuscript.py`. A piece open in two places is never overwritten: a stale save is refused and the editor
offers **Reload** or **Keep mine**.

- **Write · Compose · Settings:** the tabs over the list of pieces (and over Compose's contents and the board's
  head) switch between writing, the set pages and the book's settings. The book's research board opens from the
  rail's **Board** panel.
- **List of pieces** (Ctrl+\ hides it): front matter, body and back matter; drag to reorder, right-click for
  rename, kind, form, status, open beside, duplicate, split, merge and trash. Alt-click a piece to open it in a second
  pane. The notes, bibliography and index pages show while their feature is on; a page made by Studio opens in Compose.
- **Status bar:** *Pieces*, *Split* (a second piece beside this one) and *Pages* on the left; the writing tools and
  *Commands* (the command palette) on the right.
- **Pages** (Ctrl+Shift+P): the set pages beside the text, at the spread of the paragraph you are in, set again after
  every save. Click a page to open Compose there.
- **Text column:** no toolbar. Select text for bold, italic, note, source, index and comment; type `/` for notes,
  citations, scene breaks, epigraphs, poems, images, page breaks and a poem linked from your Poems library.
  Text that breaks the book's style sheet gets a dotted underline with a one-click fix.
- **Rail:** outline, sources, history (snapshots with compare and restore), comments, and find and replace
  across the book (Ctrl+F, Ctrl+H).
- **Command palette** (Ctrl+K): jump to any piece or run any action. **Focus mode** (Ctrl+Shift+F) dims all but the
  current paragraph. **Keys and tools** (Ctrl+/) lists every tool and its keys.
- **Import:** a .docx (through `mammoth`) or a Markdown file. Each Heading 1 starts a piece, footnotes become
  notes, and you review the proposal before anything is written. Studio's own Markdown export imports back piece for
  piece, with each piece's kind and form.
- **Editions:** freeze a dated copy of the whole book under `editions/`. Piece history keeps day-to-day
  snapshots in `drafts/`.
- **Export:** .docx, Markdown or zip from the shelf, the book's settings or the command palette. Each export also
  leaves a dated copy in `exports/` (`<Title> 2026-11-12 1405.docx`); an earlier copy is never overwritten.
- **Compose:** the book as pages, set by the same engine that makes the PDF (Typst, bundled), so the preview and the
  PDF never differ. Pick a template, a trim size and a printer, and the margins, type, headings and generated pages
  (title pages, contents, notes, bibliography, index) follow. Only what you change from the template is stored.
- **PDF:** *Export PDF* embeds the fonts, writes black as one-channel grey (and grey images for a grey interior),
  sets the title, author and language, and adds bookmarks for the pieces. A dated copy goes in `exports/` like the
  other exports.
- **Print checks:** the checks a printer would care about (margins, resolution, widows and orphans, overfull
  lines, a page count that suits the binding). They inform; they never block an export.
- **Spelling in several languages:** the book text is checked by Studio itself (Hunspell in a worker), with Dutch
  and English bundled. A word is right when any of the book's spelling languages knows it or it is in the book's
  word list; a `lang` span is checked in its own language only. Settings has the languages and the word list.
- Deleting a book or a piece moves it to `Books/.trash/`.

## Research board

Each book has a board for what feeds it, and there is one shared board for everything else. In the writing window the
rail has a **Board** panel, so the board sits beside the text; **Open the board** in it (or Board in the book's
settings tabs) opens the whole board, and **Research** in the top bar opens the shared board.

- **Items:** notes, quotes, sources, web clips, images, links to pieces of a book, and links to items on another board.
  Add them from **Add**, by dropping files, text or a link on the canvas, or by pasting.
- **Canvas and list:** the same items two ways. Drag cards, group them in titled frames, tag them, and search
  all of their text. Ctrl+Z undoes moves, resizes and deletions; **Move to** and **Link on** in the right-click menu
  send an item to another board.
- **Into the text:** drag a quote from the panel into the text. It lands in the book's quote marks with its
  citation, and its source is added to the book's bibliography. Sources, clips and images go in the same way.
- **Files:** `Books/<Book>/research/` for a book and `Research/` for the shared board, next to `Poems/`. Each item is
  a Markdown file with its details at the top; positions are in `board.json`; pictures and PDFs are in `files/`.
  Any editor can read them. Deleted items go to `.trash` inside the board's folder.

**Web clips and the network.** Studio fetches a page only when you ask for one (**Add → Web clip**, or dropping a
link), and refetches only when you choose **Clip again**. It sends no cookies, no referrer and no language list,
and a plain user agent. It reaches public addresses only: not this computer, and not your network. The page's
scripts never run. The picture is taken by Studio's Chrome from a script-free copy of the page, with its requests
filtered by the same rules. A clip keeps its readable text and picture, so it works offline afterwards.

## Claude

Studio comes with an MCP server, so Claude can work on your poems when you ask. Studio's **Info** page shows
the exact command for your install, with a copy button. For Claude Code:

```bash
claude mcp add studio --scope user -- <path to studio> mcp
```

where `<path to studio>` is `.venv/bin/studio` (or `.venv\Scripts\studio.exe`) in your clone, or
`studio-cli.exe` next to `Studio.exe`. For Claude Desktop, add the same command to `claude_desktop_config.json`
under `mcpServers`.

| Tool | |
|---|---|
| `list_poems`, `read_poem` | the poems, their text, style, drafts, notes, renders and QA |
| `get_rules`, `list_concepts` | the house rules, a series' rules and its visual concepts |
| `write_brief`, `set_slides`, `render` | brief a carousel, choose its slides, render it with the series' kit |
| `qa` | measure the renders: alignment, safe zones, phone legibility, the name |
| `get_design`, `save_design`, `render_design` | read, write and export designs in the Design tab (`save_design` refuses fonts Studio doesn't have) |
| `list_books`, `read_book`, `read_piece`, `search_book` | your books, their outline and text, and a search through a book |
| `list_sources`, `add_source` | a book's bibliography; Claude can add a source |
| `suggest`, `list_suggestions`, `withdraw_suggestions` | Claude proposes edits, notes, index terms, citations and comments; you accept or reject them in the writing window's Suggestions panel. Claude never writes manuscript text itself |
| `get_book_design`, `set_book_design`, `render_pages`, `export_pdf`, `preflight` | Claude reads and changes a book's design (you see it in Compose and can change it back; the manuscript is never touched), looks at pages, makes the PDF and runs the print checks |
| `list_research`, `read_research`, `add_research` | Claude reads a book's research board (or the shared board) and adds notes, quotes, sources and links to it; the manuscript is never touched |

Then ask, for example, "make the carousel for my new poem". Studio shows Claude's work as it happens.

## Series kits

A series can have a **kit**, `Poems/<Series>/_kit/build.py`, that renders its carousels. Studio imports it and
calls it; it never changes it. Without a kit, a series still has poems and designs, and you make images in the
Design tab. See [docs/KITS.md](docs/KITS.md) for what a kit provides.

## On disk

```
Books/
  <Book>/
    book.json          details (incl. NUR), kind, features, the order of the book, goals, `design` (only what you
                       changed from the template; lengths in mm, sizes in pt), `spelling` (languages, word list)
    manuscript/        one Markdown file per piece
    images/            images used in the text
    drafts/<piece>/    dated snapshots per piece
    editions/<name>/   frozen copies of the whole book
    sources.json       the bibliography (CSL-JSON)
    suggestions.json   Claude's suggestions, waiting for the author
    .studio/days.json  words written per day (for the daily goal)
    .studio/preflight.json  the last print check
    exports/           .docx, Markdown, zip
    research/          this book's board: items as Markdown files, board.json, files/, .trash/
Research/              the shared research board (same layout as a book's research/)
Styles/
  looks/<name>.json    a palette and a font per role
  palettes/<name>.json named swatches with roles
  fonts/<Family>/      font files you added (your own or Google Fonts)
  rules.md             house rules
Poems/
  <Series>/
    series.json        name, tagline, palette, fonts, signature, checks
    README.md          the series' rules (Claude reads them first)
    CONCEPTS.md        its visual concepts (optional)
    _kit/build.py      its carousel renderer (optional)
    stamps/            reusable pieces for the Design tab
    <Poem>/
      poem.json        title, lines, slides, status
      .studio/days.json  words written per day (the writing log)
      drafts/          one file per saved version
      writing-notes.md
      BRIEF.md         Claude's brief
      designs/         Design tab files
      Design renders/  exported designs
      qa.json          the last QA
```

Backups go to a folder outside the library, `Documents/Studio backups` unless you choose another in Settings →
Backups. Each backup is one zip, `Studio backup 2026-11-13 0300.zip`, holding `Poems/`, `Books/`, `Styles/` and
`Research/` as they are in the library (without the trash, and without design exports and carousel renders, which
Studio can make again) and a `studio-backup.json` that lists what is in it. Unzipped, it is a library folder. Other
folders you keep in the library aren't backed up; Settings names them.

## Commands

```
studio                  open Studio
studio web [--open]     run only the local server (http://127.0.0.1:4747)
studio mcp              the MCP server, over stdio (Claude starts it)
studio install          add the launcher; studio uninstall removes it
studio config [k=v]     show or change settings
```

## Development

```bash
python -m unittest discover tests      # store, QA, styles, books, updates and the web API
python tests/e2e_mcp.py                # the MCP tools end to end (needs Chrome, Chromium or Edge)
pip install -e ".[app,build]" && pyinstaller packaging/studio.spec --noconfirm   # the executables
```

`tools/design_regression.py` exports every design of a library and compares pixels and metrics between two
runs, for changes to the renderer or the fonts.

How it fits together is in [docs/DESIGN.md](docs/DESIGN.md). Contributions are welcome: see
[CONTRIBUTING.md](CONTRIBUTING.md), which also has the steps for rebuilding the vendored ProseMirror bundle the
book editor uses.

## Licence

MIT, see [LICENSE](LICENSE). The bundled typefaces (Newsreader, Archivo, Literata, EB Garamond, Source Serif 4,
Inter, Work Sans, Fraunces, Bebas Neue, IBM Plex Mono, Caveat and Atkinson Hyperlegible) are under the SIL Open Font
License (`studio/static/fonts`).
