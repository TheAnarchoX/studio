# Styles, home and first run — design

*12 November 2026. Agreed in the same design conversation as the books spec
(`2026-11-12-books-design.md`), and built before books part 1, because books use it.*

## Goal

**Principle:** Studio works equally well with AI as without, and nobody ever has to touch a config file;
everyone gets a tailored experience. Every capability Claude's tools have also has a control in the interface,
and every setting, rule and style is editable in the app. The one exception is connecting Claude itself, which
stays a copy-paste on the Info page.

Studio is open source, so it has to be a great experience straight after installing, for people whose taste is
not the author's. That means: looks, palettes, fonts and rules you can choose and change yourself, globally and
per series, book, poem or piece; a home page now that Studio holds more than poems; a light theme; and a short
welcome.

**Principle: meaningful choice.** Offer a broad but curated set up front (about ten looks, about twelve
bundled font families) and put depth one click further (edit, more fonts, detach). Every choice should change
something the person cares about; no settings for their own sake.

## Decisions

| Question | Decision |
|---|---|
| Font sources | All four: a bundled curated set, Google Fonts in-app, your own files, fonts installed on the computer. |
| Inheritance | Global → series or book → poem or piece. Linked by default; *Detach* makes an own copy. Every value shows where it comes from. |
| Editable rules | Global house rules, series rules and concepts, book style sheet, design checks. |
| First run | A three-step welcome, an optional example series and book, starter looks, light and dark app theme. |
| Home | A general home page above Poems, Books and (later) Board and Articles. |

## On disk

```
<library>/
  Styles/
    looks/<name>.json        a palette and a font pairing, by reference
    palettes/<name>.json     named swatches with roles
    fonts/<Family>/          added fonts: the font files and family.json
    rules.md                 global house rules
  Poems/ …  Books/ …
```

Bundled starter looks, palettes and fonts live in the app (`studio/static/styles/`, `studio/static/fonts/`) and
appear in the library as read-only; editing one saves an own copy in `Styles/` under the same name, which then
takes precedence. So updates to Studio can improve the starters without overwriting anyone's changes.

### Palettes

```json
{"name": "Signal", "swatches": [
  {"name": "Night", "hex": "#0C0E11", "role": "background"},
  {"name": "Paper", "hex": "#EEEAE2", "role": "text"},
  {"name": "Signal red", "hex": "#DA291C", "role": "accent"},
  {"name": "Fog", "hex": "#959AA2", "role": "muted"},
  {"name": "Fog ink", "hex": "#77726B"}]}
```

Roles (`background`, `text`, `accent`, `muted`, optional) let templates, the composer and new designs use a
palette sensibly; extra swatches have no role. Palettes can be made from scratch, duplicated, pasted as a list
of hex codes, or pulled from an image (a dominant-colour extraction on the server, offering 5–8 swatches to
keep or drop). A contrast check (WCAG ratio) marks text and background pairs under 4.5:1.

### Fonts

`family.json`: `{"family", "category": "serif|sans|display|mono|hand", "source": "bundled|google|file|system",
"license": "OFL-1.1|…|unknown", "files": [...], "axes": {"wght": [100, 900], "wdth": [62.5, 125]},
"italic": true}`, read from the font files with fontTools (name table, `fvar`, `OS/2` embedding bits).

- **Bundled** (about 12 OFL families, ~8 MB in all): the current Newsreader and Archivo, plus serif text faces
  for books (for example Literata, EB Garamond, Source Serif 4), sans (Inter, Work Sans), display (Fraunces,
  Bebas Neue), a mono (IBM Plex Mono), a hand (Caveat), a highly legible face (Atkinson Hyperlegible). The final
  list is chosen for quality, language coverage (including Dutch and other Latin-script languages) and real
  italics.
- **Google Fonts:** the catalogue from Google's public font metadata, searchable by name and category with live
  previews; *Add* downloads the family's files into `Styles/fonts/`. Network is used only when browsing or adding.
- **Own files:** drop .ttf, .otf or .woff2; Studio groups them into families, reads the licence and the embedding
  permission, and warns when embedding in a PDF may not be allowed.
- **System:** fonts in the OS font folders, listed under *On this computer*; anything using one shows a warning
  that it won't look the same elsewhere, and exports name the missing font.

Everything that draws text uses the library: the app serves `@font-face` rules for all families
(`/api/fonts.css`); `design-core.js` takes weights and widths from each family's axes instead of the hardcoded
`WEIGHTS`/`WIDTHS`; `metrics.py` measures any font file; Typst (books part 2) gets the font folders. Series kits
keep their own fonts and are not touched.

The font manager page: families as specimen rows in your own sample text, filters by category and source,
licence and axes per family, *Add fonts* (Google, files), and where each family is used.

### Looks

```json
{"name": "Signal", "palette": "Signal",
 "fonts": {"display": {"family": "Archivo", "weight": 900, "width": 87.5},
           "text": {"family": "Newsreader", "weight": 400},
           "label": {"family": "Archivo", "weight": 700, "width": 100}}}
```

About ten starters, each a complete, good-looking pairing: Signal (the author's own), Editorial light, Warm
linen, Pastel, Monochrome, High contrast, Academic, Botanical, Riso, Children's book. Shown as preview cards
(a sample poem slide and a sample book page in that look).

### Inheritance

| Level | Where | Fields |
|---|---|---|
| Global | Settings → *Default look*; `Styles/rules.md` | look, house rules |
| Series | `series.json` | `look` or own `palette` and `fonts`; rules (README.md), concepts, `checks` |
| Book | `book.json` | `look` or own `palette` and `fonts`; `style` (style sheet); `checks` |
| Poem | `poem.json` | optional `look`, `palette`, `fonts` |
| Piece | `book.json` contents entry | optional `fonts` (for example a poem set in another face) |

A string (`"palette": "Signal"`) links to the library; an object or array is an own copy. Existing
`series.json` files with palette and font arrays keep working as own copies. *Detach* turns a link into a copy;
*Link to…* replaces an own copy by a library item. Resolution walks up the levels; the interface shows each
value with its source ("Signal · from series Calls", "own").

## Rules

- **Global house rules** (`Styles/rules.md`): free text, for example voice, language, spelling preferences, what
  Claude should always or never do. Claude's tools return them before series or book rules; new series and books
  start from them.
- **Series:** the Rules and Concepts tabs become editable (a Markdown editor with preview), next to the Look tab.
- **Book style sheet** (`book.json` → `style`):
  `{"quotes": "“…”|„…”|«…»|‘…’", "numbers": "words to ten|words to hundred|digits", "terms": [{"use": "GGZ",
  "not": ["ggz", "G.G.Z."], "note": ""}], "notes": "free text"}`. The writing editor underlines text that breaks
  it (a quiet dotted line, with the preferred form on hover and one-click fix), and Claude follows it.
- **Design checks** (`checks` in `series.json` or `book.json`): the thresholds now in `studio/qa.py`
  (`ALIGN`, `NEAR`, `MIN_PHONE`, `STORY_SAFE`) per series, with the current values as defaults; for books (part 2)
  widows and orphans, minimum image resolution, page-count multiple. Edited as a short form with the default
  next to each field.

## Home

`#/` becomes Home; poems move to `#/poems` (old links redirect).

- **Continue:** the most recent poem, piece or design you worked on, with its last sentence and one button.
- **New:** poem, book, series, idea (the board, once part 3 exists), import.
- **Books:** covers (or typographic covers) with kind and word count.
- **Series:** name, poems, how many ready for art.
- **Recent:** the last ten things changed anywhere, by you or by Claude, with where and when.

The top bar becomes *Home · Poems · Books* (Board and Articles join later), with Info and Settings on the right
and a *New* menu.

## Light theme

Studio's interface gets a light theme next to the dark one: Settings → Appearance: *System*, *Light*, *Dark*.
All interface colours already come from CSS variables in `app.css`; the light theme redefines them. Canvases
(the design board, book pages) keep showing the work's own colours.

## First run

When no config file exists:

1. **Where your work lives:** the library folder (default `~/Studio`), with *Choose…*.
2. **Your name:** the signature for poems and the author for books (skippable).
3. **A starting look:** the starter looks as preview cards; becomes the global default.

Then *Add examples* (default on): a series *Examples* with two poems and a few designs, and a short book with a
dedication, a foreword with a note and a source, two chapters and a poem, all written for Studio and free to
use. They carry `"example": true`; Settings → *Remove examples* deletes them (to the trash). The welcome can be
skipped; every step is in Settings later.

## Server and files

- `studio/styles.py`: the library (looks, palettes, fonts, rules), resolution through the levels, palette from
  image, contrast; Google Fonts catalogue and download (with a cached catalogue file); system font listing.
- Endpoints: `GET /api/styles` (looks, palettes, fonts with source and licence), `POST /api/styles/palette`,
  `/look`, `/rules`, `/delete`; `POST /api/fonts/add` (files, base64), `GET /api/fonts/google?q=`,
  `POST /api/fonts/google/add`; `GET /api/fonts.css`; `POST /api/palette/from-image`;
  `POST /api/series/checks`, `POST /api/examples`, `POST /api/examples/remove`; `GET /api/home`.
- Front end: `styles.js` (fonts, palettes, looks pages), the welcome flow, Home, theme switch; the series Look,
  Rules and Concepts tabs become editors.
- MCP: `read_poem` and `get_rules` include the resolved look and the house rules; `save_design` validates fonts
  against the library.

## Testing

- `tests/test_styles.py`: resolution through every level (linked, detached, overridden), bundled vs own copy
  precedence, palette from image, contrast, family grouping and licence reading from font files, old
  `series.json` files unchanged.
- Fonts: a Google Fonts add against a recorded catalogue and family response (no network in tests).
- In the browser: the welcome on an empty config, examples added and removed, a look applied to a series and
  detached, a new font used in the design editor and exported, the light theme on every page, Home.

## Not in this part

Book design and the composer (books part 2), per-piece fonts in print (part 2), the board (part 3).
