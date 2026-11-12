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

- **Poems:** every poem as a card, with status filters and search.
- **Series:** a body of work with its own look, in `Poems/<Series>/series.json` (tagline, palette, typefaces,
  signature) next to the `README.md` with its rules.
- **Write:** an editor that saves dated drafts, with writing notes and tools for the page: hinge words (words
  that recur, also inside other words), syllables, rhythm, counts, read aloud, focus mode and changes since any
  draft. **Ready for art** tells Claude the poem can be made.
- **Art:** the carousel in 1:1, 4:5 and 9:16, with and without your name, the brief, posting notes and a QA line
  per slide. Click an image for the viewer: step through every slide and design, copy, save, share, show it in
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
- Deleting moves poems, designs and stamps to a `.trash` folder.

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
| `list_poems`, `read_poem` | the poems, their text, drafts, notes, renders and QA |
| `get_rules`, `list_concepts` | a series' rules and visual concepts |
| `write_brief`, `set_slides`, `render` | brief a carousel, choose its slides, render it with the series' kit |
| `qa` | measure the renders: alignment, safe zones, phone legibility, the name |
| `get_design`, `save_design`, `render_design` | read, write and export designs in the Design tab |

Then ask, for example, "make the carousel for my new poem". Studio shows Claude's work as it happens.

## Series kits

A series can have a **kit**, `Poems/<Series>/_kit/build.py`, that renders its carousels. Studio imports it and
calls it; it never changes it. Without a kit, a series still has poems and designs, and you make images in the
Design tab. See [docs/KITS.md](docs/KITS.md) for what a kit provides.

## On disk

```
Poems/
  <Series>/
    series.json        name, tagline, palette, fonts, signature
    README.md          the series' rules (Claude reads them first)
    CONCEPTS.md        its visual concepts (optional)
    _kit/build.py      its carousel renderer (optional)
    stamps/            reusable pieces for the Design tab
    <Poem>/
      poem.json        title, lines, slides, status
      drafts/          one file per saved version
      writing-notes.md
      BRIEF.md         Claude's brief
      designs/         Design tab files
      Design renders/  exported designs
      qa.json          the last QA
```

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
python -m unittest discover tests      # store and QA
python tests/e2e_mcp.py                # the MCP tools end to end (needs Chrome, Chromium or Edge)
pip install -e ".[app,build]" && pyinstaller packaging/studio.spec --noconfirm   # the executables
```

How it fits together is in [docs/DESIGN.md](docs/DESIGN.md). Contributions are welcome: see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT, see [LICENSE](LICENSE). The bundled typefaces, Newsreader and Archivo, are under the SIL Open Font
License (`studio/static/fonts`).
