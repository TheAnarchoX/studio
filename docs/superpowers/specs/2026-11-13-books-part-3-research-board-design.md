# Books, part 3: the research board — design

*13 November 2026. Written overnight from part 1's spec (`2026-11-12-books-design.md`, "Decisions" and "Parts 2–4")
while the author slept; they handed over the open questions ("do anything you want"). Every decision that wasn't
already in part 1's spec is recorded as a **Ruling**, with what it costs if it turns out wrong, so the author can
overturn any of them in the morning.*

## Why

A book written over years is fed by what piles up outside the text: notes to self, photos and
scans, articles read on the web, quotes from books, the sources behind them. Today they live in other apps and
browser tabs, and every quote is retyped with its source by hand. The board keeps them next to the book, in the same
library of plain files, and turns a quote into a cited sentence by dragging it into the text.

Success, in the author's terms: open a book, open its board, gather things there for a week (clips, photos, quotes,
notes), arrange them in frames by chapter or theme, then write with the board beside the text and drag quotes in —
each one landing in the book's quote marks with its citation, and its source in the bibliography.

**Principles that bind this part** (from part 1 and the author):

- Studio works equally well with AI as without, and nobody touches a config file. Everything here has a control in
  the interface; part 4 gives Claude `list_research` and `add_research` over the same store.
- Typing is never lost and an open item is never overwritten under the cursor.
- Files are the database: plain files the author can open anywhere, atomic writes, never a rewrite on read.
- Every endpoint goes through the route tables; every view escapes user text; interface copy is plain and in
  sentence case; right-click menus wherever there are lists.
- Nothing personal in the repository.

**Goals.** One board per book and one shared board; notes, images, web clips, quotes, sources and links to pieces;
a canvas view and a list view over the same items; frames, tags and search; moving and linking items between boards;
quotes dragged into the text with their citation; the board beside the text in the writing window.

**Non-goals.** Syncing or sharing boards with other people; a browser extension; clipping pages behind a login;
full-page archives (WARC); OCR of images and PDFs; mind-map connectors between cards; a research row on Home.

**Anti-goals** (would make it a failure even if it works): Studio fetching anything the author didn't ask for, or
sending anything about them; a clipped page running its scripts; a board that loses a note being typed; a canvas that
feels like a toy (bouncy motion, badges, colour for decoration); research files only Studio can read.

## Approaches considered

1. **Items as files with front matter, positions in `board.json`** (chosen). One Markdown file per item, its fields in
   a front matter block, its body the text; images and screenshots beside it in `files/`. `board.json` holds only
   where things are on the canvas and the frames. Readable and editable anywhere (it is the convention of Obsidian and
   Pandoc), merges cleanly when Claude or the author adds files by hand, and matches part 1's "one file per piece".
2. **One `board.json` holding everything.** Simplest to read and write atomically, but a 3 MB file of quotes and clipped
   articles nobody can read outside Studio, a write of everything for every move, and conflicts between windows.
   Against "files are the database".
3. **A folder per item** (`research/<item>/item.json`, `text.md`, `screenshot.jpg`). Tidy for clips, but doubles the
   file count for notes and quotes, and gives the author folders to click through for a one-line note.

**Ruling: approach 1** — cost if wrong: a converter to another layout; the store is the only module that knows it.

## On disk

```
Books/<Book>/research/       this book's board
  board.json                 positions, sizes, frames
  <item>.md                  one file per item: front matter, then the text
  files/                     images, page screenshots, PDFs the items use
  .trash/                    items moved to the trash, with their files
Research/                    the shared board, at the library root next to Poems/ and Books/: the same layout
```

### An item file

```markdown
---
type: "quote"
title: ""
tags: ["childhood", "1987"]
source: "van-dijk-1998"
locator: "p. 12"
created: "2026-11-13T01:20:00"
---
The quoted text, as Markdown.
```

- The front matter is YAML whose values Studio writes as JSON (JSON is valid YAML), one `key: value` per line, so a
  YAML reader, Pandoc and Obsidian read it, and Studio's own reader needs no YAML library. Studio also reads what a
  person types by hand: plain unquoted strings (`title: A letter`) and block lists (`tags:` then `  - a` lines). A
  file without front matter is a `note`. Keys Studio doesn't know are kept on every write. Files are UTF-8; a file
  that isn't is shown as unreadable and never written over (as part 1 does for pieces).
  **Ruling** — cost if wrong: hand-written YAML beyond this subset (anchors, multi-line `|` blocks) reads as plain text
  and is left untouched on disk until the item is saved from Studio, which writes the subset back.
- **The id is the file stem**: made once from the title or the first words (part 1's slug rules: no diacritics, lower
  case, dashes, at most 60 characters, `-2`, `-3` for repeats, Windows-reserved stems get `-1`) and never renamed when
  the title changes, so positions and links stay valid. **Ruling** — cost if wrong: file names drift from titles; a
  *Rename file* action could be added.
- `created` is written once; `updated` is the file's modification time, not stored.

**Kinds** (`type`) and their fields:

| Type | Fields | Body | Card shows |
|---|---|---|---|
| `note` | `title?` | the note | title, the text |
| `quote` | `source?` (citation key), `locator?`, `from?` (the item it was taken from) | the quoted text | the text in quote marks, *Author year, p. 12* |
| `source` | `csl` (one CSL-JSON item; its `id` is the key) | notes about the source | *Author year*, title, type |
| `clip` | `url`, `site`, `author?`, `published?`, `fetched`, `shot?` (`files/…jpg`), `file?` (`files/…pdf`), `csl` | the readable copy | the picture's top, title, site, date |
| `image` | `file` (`files/…`), `title?`, `csl?` | caption or notes | the image, title |
| `piece` | `book`, `file` (a piece of a book) | why it's here | the piece's title, kind, status, words, first lines |
| `link` | `board` (a book id, or `null` for the shared board), `item` (an id there) | — | the linked item, with a quiet "From …" line |

Every item has `tags` (a list of strings) and `created`. Any item that has `csl` is **citable**: sources, clips
(their CSL is made when they are clipped), and images when the author gives them a source.

### board.json

```json
{
  "version": 1,
  "items": {"van-dijk-1998": {"x": 120, "y": 80, "w": 280, "h": null, "z": 4, "frame": "f-childhood"}},
  "frames": [{"id": "f-childhood", "title": "Childhood", "x": 0, "y": 0, "w": 900, "h": 640, "z": 0}]
}
```

- Positions are canvas units (1 unit = 1 CSS pixel at 100%). `w` is the card's width; `h` is `null` (the card is as
  tall as its content, up to a cap) or a height the author dragged it to. `z` orders cards; frames are always behind
  cards. Unknown keys are kept.
- `frame` is the frame an item belongs to, set when the item is dropped (the frame that contains the card's centre;
  the smallest when frames overlap) and when it is added into a frame. **Ruling: membership is stored, not computed on
  read** — cost if wrong: an item placed into a frame's area by hand-editing positions isn't in that frame until moved
  once on the canvas.
- Items with no entry (made by hand, or by another program) are given a position when the board is read — in a
  column to the right of everything placed, in order of creation — and that position is written only when the author
  moves one. **Ruling: never write on read** (the binding rule).
- The canvas's pan and zoom are this window's own, kept in the browser, not in `board.json`. **Ruling** — cost if
  wrong: the view isn't the same on two computers.

### Deleting

Items go to `<board>/.trash/<stamp> <id>.md` with their files (as `<stamp> <id> <file name>`), like poems and pieces.
A deleted frame leaves its items where they are, no longer in a frame. Deleting a book takes its board with it to
`Books/.trash/` (part 1 already moves the whole folder).

## Links, moves and sources

**Linking** puts a `link` item on another board that shows the original: editing it there edits the original (it *is*
the original); deleting the link removes only the link; a link whose original is gone says so and offers *Remove*.

**Moving** moves the file and its files to the other board (a new id if the name is taken there), drops its position
here and places it there, and rewrites every link on any board that pointed at it. **Ruling** — cost if wrong: one
scan of all boards per move; fine at hundreds of items, and only moves pay it.

**Sources work by key, like the manuscript.** A quote's `source` is a citation key. A key is found, in order, on:

1. this board: its citable items and the citable items its links point at;
2. the shared board (from a book's board);
3. the book's own `sources.json` (from a book's board).

**Keeping a quote's source** when things move (rulings from the builder check; cost if wrong: a stray link or copy the
author can delete):

- A quote moved to a board where its key can't be found: a link to the item that holds the key is added there; when
  the key was only in the old book's `sources.json` (no item to link to), a `source` item is made on the new board from
  that entry (a copy: the book's entry stays the one that prints).
- A citable item moved off a board whose quotes still cite its key: a link to it is left behind on that board.
- A citable item moved to the trash: the quotes citing it keep their key and show it as the label (as part 1 shows an
  unknown key); `use` then cites the key without adding a source, and says "This quote's source isn't on its board any
  more."
- `use` resolves a key on the item's own board (as above), then in the `sources.json` of the book being written — so a
  quote from the shared board finds a source the book already has.

**Ruling: the board's sources stay apart from the book's `sources.json`.** Gathering a source on the board doesn't put
it in the book's bibliography; citing it does (dragging a quote or a source into the text), or *Add to the book's
sources* on the card. A source card on a book's board says whether its key is in the book's sources. Cost if wrong:
two places to correct a source's details — Studio never overwrites the book's entry, so the book's copy is the one that
prints.

**Adding a source to the book** (`use`, below): the key is not in `sources.json` → added as it is. The key is there and
is the same source (same URL, or the same title and year, compared without case and spacing) → nothing changes. The
key is there for a different source → added under the next free key and that key is cited: part 1's rule for new keys
(`vandijk1998` → `vandijk1998b`, `c` …) when the key ends in a digit, else `-2`, `-3` (`field-notes-2`). New keys on the
board (sources, clips) are made with part 1's rule too (`sourceKey` in `book-tools.js`: the first author's family name
with its particle, or the title's first word that isn't an article, then the year). **Ruling** — cost if wrong: a
duplicate entry the author merges by hand.

## Web clips

A clip is made only when the author asks for one: *Add → Web clip…*, or dropping or pasting a link on the board (the
drop is the ask). Studio never refetches a clip on its own; *Clip again* refetches when asked.

### Fetching (`studio/clip.py`)

- **Only `http` and `https`**; no user name or password in the URL.
- **Only addresses on the internet**: loopback, private, link-local, shared, multicast and reserved addresses are
  refused — checked on the connected socket itself (so DNS tricks don't help) and again for every redirect. This keeps
  a page from steering Studio at the author's own computer (Studio's API is on 127.0.0.1) or network.
  **Ruling** — cost if wrong: an intranet page can't be clipped; the error says why.
- **Nothing about the author is sent**: no cookies (none are kept), no referrer, no `Accept-Language`, a plain
  `User-Agent: Mozilla/5.0 (compatible; Studio/<version>)`. **Ruling** — cost if wrong: a site that refuses unknown
  agents refuses the clip; Studio says the site refused and keeps nothing.
- At most 5 redirects, 20 seconds and 10 MB. Gzip and deflate are accepted and decoded.
- What comes back decides what is made: HTML → a clip; an image (`png`, `jpeg`, `gif`, `webp`) → an image item with
  the link as its source; a PDF → a clip that keeps the PDF in `files/` (no readable copy, no picture; *Show the file*
  opens its folder); anything else is refused with its type named. **Ruling** — cost if wrong: a PDF's text isn't
  searchable.

### The readable copy

Studio extracts the article itself, with the standard library's HTML parser (no new dependency):

- details: the title (`og:title`, then `<title>` without its " | Site" tail), the site (`og:site_name`, then the
  host without `www.`), the author (`author` and `article:author` meta, JSON-LD `author.name`), the date published
  (`article:published_time`, JSON-LD `datePublished`, the first `<time datetime>`), the language (`<html lang>`), the
  canonical URL;
- the text: scripts, styles, navigation, headers, footers, asides, forms, menus and hidden elements are dropped; the
  `<article>`, `<main>` or the block with the most paragraph text (and the fewest links per word) is kept, and written
  as Markdown: headings (`##`, `###`), paragraphs, block quotes, lists, emphasis, links (`[text](absolute URL)`),
  line breaks, preformatted text. Images, tables, embeds and comments are left out.

**Ruling: Studio's own extractor, Markdown out, images left out** — cost if wrong: weaker on unusual pages than a
library such as trafilatura (which can replace the function later behind the same signature); the picture shows what
was left out.

The readable copy is shown rendered from Markdown on the server (markdown-it with raw HTML off, so nothing in the page
becomes markup; links open in the system's browser). **Ruling: the fetched page itself isn't kept** — cost if wrong:
the copy can't be extracted again once the page is gone; a saved page could be added later behind *Clip again*.

### The picture

Studio's headless Chrome (`studio/shoot.py`) photographs **Studio's own script-free copy** of the fetched page, not
the live page:

- every `<script>`, inline event handler, `javascript:` URL, `<base>`, `<meta http-equiv="refresh">`, `<iframe>`,
  `<object>`, `<embed>` and prefetch hint is removed; a `Content-Security-Policy` meta that forbids scripts, frames,
  objects and form posts is put first in `<head>`, then a `<base>` with the page's own address, so its styles, images
  and fonts load from the site;
- the copy is written to a temporary file and opened in a throwaway Chrome profile (no cookies, no history), with the
  same `User-Agent`, `--accept-lang=en` (so the computer's languages aren't sent), and background networking, sync,
  component updates and pings off;
- a 1280 × 1600 window at 1×, saved as `files/<id>.jpg` (quality 85) and a thumbnail on demand.

Measured on 13 November 2026: Chrome's own switch for turning scripts off (`--blink-settings=scriptEnabled=false`)
stops `--screenshot` from writing anything, so the policy route is the one that works; with it, an inline script and
an `onerror` handler did not run and a remote image did load. **Ruling** — cost if wrong: a page that builds itself
with scripts photographs bare (the readable copy may still have its text); no Chrome found → the clip is saved
without a picture and says so.

The fetch makes one request for the page (and its redirects); the picture makes the requests the page's own HTML
names (styles, images, fonts). Those are part of the page the author asked for; no script runs to make more.

**Chrome's own requests go through the same rules** (ruling from the builder check — cost if wrong: about 150 lines of
proxy; without it a hostile page could name `http://192.168.1.1/…` or Studio's own API in an `<img>`). For each
picture, `clip.py` starts a small HTTP proxy on 127.0.0.1 (a free port, alive only while Chrome runs) and starts Chrome
with `--proxy-server=http://127.0.0.1:<port>`, `--proxy-bypass-list=<-loopback>` (so even loopback addresses go
through it) and `--disable-quic`. The proxy resolves each host itself, connects, and checks the connected address with
the same `public_only` rule before passing a byte — for plain HTTP requests (where it also drops `Cookie`, `Referer`
and `Accept-Language` and sets the `User-Agent`) and for HTTPS tunnels (`CONNECT`, where the bytes inside are
encrypted and only the address can be checked). Refused requests get a 403 and the picture simply lacks that image. The
copy also carries `<meta name="referrer" content="no-referrer">`. Limits: 20 MB through the proxy per picture, 30
seconds per connection.

### What a clip holds

Its front matter: `url` (the address asked for), `site`, `author`, `published`, `fetched` (ISO time), `shot`, and a
`csl` item of type `webpage` (title, `container-title` = site, author when found, `issued` from the date published,
`URL`, `accessed` = the fetch date), keyed like the rail's sources (family name and year, else the first word of the
title that isn't an article, made unique among the keys in reach of the board). Its body is the readable copy. It works offline: nothing on
the card or in the panel loads from the web.

## Quotes into the text

In the writing window, the board's rail panel lists the book's board (and, switched, the shared board). A **quote**,
a **source** (or anything citable: a clip, an image with a source) or an **image** can be dragged from it into the
text, or put at the cursor with its *Quote at the cursor* / *Cite at the cursor* / *Put in the text* button (the
keyboard way). `POST /api/research/use` prepares it:

- a quote → its text, its key (resolved as above, and the source added to the book's `sources.json` when it isn't
  there) and its locator;
- a source or a clip → its key, added the same way (an image with a source is put in as an image, not cited);
- an image → copied into the book's `images/` (part 1's `save_image`), returning `../images/<name>` and its title as
  the caption.

The text then gets:

- **a short quote** (one paragraph, at most 40 words), dropped in a line of text: the quote in the book's style-sheet
  quote marks, a space, and the citation: `„Het was koud.” [@van-dijk-1998, p. 12]`;
- **a long quote** (more paragraphs, or more than 40 words): a block quotation after the paragraph it was dropped on,
  with the citation at the end of its last paragraph;
- **a source**: the citation alone; **an image**: an image block with its caption.

A quote without a source goes in without a citation, and the window says "This quote has no source yet." A book whose
sources feature is off still gets the citation (shown quietly, as part 1 does with marks of a feature that is off).

**Rulings:** 40 words as the line between inline and block (cost if wrong: one constant); only quotes, citable items
and images go into the text, not notes or piece links (cost if wrong: small, the same endpoint can grow); the insert lands where
the drop was even if the text changed while the server answered, because the drop position is kept in a ProseMirror
plugin and mapped through every change.

## The interface

### Where the boards are

- **The shared board:** *Research* in the top bar (`#/research`), after *Books*.
- **A book's board:** `#/book/<id>/board`, reached from the writing window's rail (the *Board* panel's *Open the
  board*), a *Board* tab after *Write* on the settings pages, and the board's own tabs *Write · Board · Settings*.
  **Ruling** (revised after the browser check: a *Board* link beside *Settings* cut "Books · Memoir" short) — the
  writing window's head stays as part 1 made it; part 2 turns it into tabs *Write · Compose · Settings*, and on merge
  *Board* joins them. Cost if wrong: one click more from the writing window tonight.
- **Beside the text:** a *Board* panel in the writing window's rail (part 1's rail, 340 px, one panel at a time),
  showing the board as a list. **Ruling: the canvas itself isn't put beside the text** — cost if wrong: the second
  pane of split view could host the canvas later; the rail panel is where dragging into the text happens.

### The board page

A full window under the top bar, with the writing window's proportions:

```
┌──────────────┬───────────────────────────────────────────────────┬──────────────────┐
│ BOOKS · MEMOIR   Write  Settings                                  │                  │
│ A Year of    │ [Canvas | List]   [Search the board………]  Add ▾  │  the open item   │
│ Small Things │                                                   │  (400 px)        │
│ Board        │   ┌──Childhood────────────────────┐               │                  │
│              │   │ ┌─────┐ ┌──────────┐          │   ┌─────┐     │  title           │
│ FRAMES       │   │ │note │ │„quote”   │          │   │clip │     │  text / fields   │
│ Childhood  7 │   │ └─────┘ │Author 98 │          │   │     │     │  tags            │
│ The house  4 │   │         └──────────┘          │   └─────┘     │  actions         │
│ KINDS        │   └───────────────────────────────┘               │                  │
│ Quotes    12 │                                                   │                  │
│ TAGS         │                                                   │                  │
├──────────────┴───────────────────────────────────────────────────┴──────────────────┤
│ Board  ·  24 items, 3 frames  ·  Saved                              Fit  −  100%  + │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

- **Left (272 px, hideable like the binder):** the head (kicker *Books · Memoir* with *Write* and *Settings*, or
  *Research*; the book's title; "Board"), then **Frames** (click: the canvas goes to the frame, the list scrolls to
  it), **Kinds** with counts (click: filter), **Tags** with counts (click: filter; one filter of each kind at a time).
- **Middle:** a slim toolbar — *Canvas* / *List*, the search field, *Add* (Note, Quote, Source, Web clip…, Image…,
  Link to a piece…, Frame) — over the canvas or the list.
- **Right (400 px, so its text is at least 360 px wide):** the open item; closed when nothing is open.
- **Status bar (36 px):** counts, the save state, and on the canvas *Fit*, zoom out, the zoom, zoom in.

### Canvas

- Pan by dragging empty space (or Space-drag, or the wheel); zoom with Ctrl+wheel, the status bar, Ctrl+0 (fit),
  Ctrl+1 (100%); 25–200%. Cards are real text at every zoom.
- Click selects, Shift/Ctrl-click adds, dragging on empty space with Shift draws a selection box; dragging a card moves
  the selection; arrows nudge by 8 (Shift: 1). The moved cards' positions (and frames) save after the drop.
- Double-click a card or press Enter: open it in the panel. Double-click empty space: a new note there. Delete: to
  the trash (asks first for more than one).
- Cards have one width per kind (note 240, quote 280, source 260, clip 300, image 240, piece 260) and grow with their
  text up to 360 tall, then fade; the corner handle resizes (width and a fixed height).
- **Undo** (Ctrl+Z, Ctrl+Shift+Z or Ctrl+Y) takes back the board's own actions in this window: moves, resizes, frame
  changes (add, move, resize, rename, delete), adding items (they go to the trash), moving to the trash (they come
  back from it, `POST /api/research/restore`), and moving items to another board (they move back). The last 50
  actions are kept while the page is open; typing in the item panel has the text field's own undo. **Ruling** (from
  the builder check) — cost if wrong: none; a canvas without undo would feel like a toy.
- **Frames:** a titled rectangle behind the cards. Dragging its title moves it with its items; its corner resizes it;
  double-click the title renames it. Items dropped inside join it.
- **Dropping on the canvas:** image files → image items; a link → a clip; text → a note; all where they were
  dropped. Pasting does the same at the centre of the view.
- **Right-click a card:** Open; Edit tags…; Move to › (Shared board, each book); Link on › (the same); Quote this
  (clips: the selection in the panel); Open the page ↗ (clips); Clip again (clips); Add to the book's sources
  (citable items on a book's board); Open the piece (piece links); Copy text; Move to the trash. **Right-click empty
  space:** New note here, New frame here, Paste. **Right-click a frame:** Rename, Select its items, Delete the frame.

### List

The same items as rows, grouped by frame (frames in reading order: top to bottom, then left to right; then "Not in a
frame"), each group sortable by *Added*, *Title* or *Kind*. A row: the kind, the title or first words, the source
label (quotes), the tags, the date added. Same selection, keys, right-click menu and panel as the canvas; dragging
rows onto a group's head moves them into that frame (the server places them inside it).

### The open item (right panel)

Title (editable), then per kind:

- **note:** the text in a plain text field (light Markdown: `*italic*`, `**bold**`, lists), saved 1 s after typing
  stops and when the panel closes. **Ruling: notes are plain text with light Markdown, not a rich-text editor** — cost
  if wrong: a small ProseMirror editor on the manuscript schema could replace the field later, since notes are already
  Markdown.
- **quote:** the text; *Source* (a select of the citable items in reach, plus *New source…*); *Locator* (`p. 12`).
- **source:** part 1's source form (type, title, authors as `Family, Given; …`, year, publisher, container, URL,
  accessed), its key, and on a book's board "In the book's sources" or *Add to the book's sources*.
- **clip:** site · author · date published; "Clipped 13 Nov 2026" and *Open the page ↗*; two tabs, *Text* (the
  readable copy) and *Picture* (the screenshot). Selecting text in the copy shows a small *Quote* button: it makes a
  quote item (source: the clip's key, `from`: the clip) next to the clip on the canvas.
- **image:** the image (fit to the panel), its caption/notes, an optional source (*Add a source*).
- **piece:** the piece's kind, status, words and first lines; *Open in the writing window*; why it's here (notes).
- **link:** the original's panel, with "From the shared board" (or the book's title) and *Go to the original*.

Then **Tags** (a field with suggestions from the board's tags) and the item's dates.

**Saving and conflicts** follow the writing window: every save carries the file's modification time; a file changed
elsewhere (another window, Claude, a hand edit) gives a bar "This item changed outside the board." with *Reload* and
*Keep mine*; until a save goes through, the text is also kept in the browser. **Ruling** — cost if wrong: none; it is
part 1's rule applied.

### The rail panel (writing window)

Kicker *Board*, the book's title, a quiet line of counts; a search field; *This book* / *Shared board*; the items as
compact rows grouped by frame (kind, title or first words, the source label for quotes). A row opens in place to show
the full text and its buttons: *Quote at the cursor* (a quote), *Cite at the cursor* (a source or a clip), *Put in the
text* (an image), and *Open on the board* (every kind).
Quotes, sources and images can be dragged into the text; the row's title says so.

### Search

The search field filters both views by the server's search over every item's title, text (all of a clip's readable
copy), tags, URL and source details; matches on the canvas stay lit and the rest dim, the list shows only matches.
*Every board* lists matches on all boards, each with its board, and opens them there. **Ruling: search runs on the
server** — cost if wrong: a round trip per query (debounced), cheap on localhost.

### Live changes

The board reads a change stamp of its own every 2 seconds while open (`GET /api/research/stamp?b=`), and reads the
board again when it moved, keeping what is being typed. `research/` joins the folders that don't move the books'
stamp, so board edits don't make the writing window reread its book. **Ruling** — cost if wrong: none visible.

### Copy and look

Plain sentence case ("Clip a web page", "Clipping example.org…", "The site refused the request (403).", "Studio clips
pages on the internet, not on this computer or its network."). Studio's tokens for both themes; cards on `--panel`
with a hairline, quotes set in the serif, the selection as the red rule used everywhere else; no shadows that float,
no badges, no animation beyond the existing ease on panels.

## Server

### `studio/research.py` — the store (part 4 wraps it)

```python
BOARD = None | str               # None: the shared board; a book's id (its folder name) for that book's board
KINDS = ("note", "quote", "source", "clip", "image", "piece", "link")

class ResearchError(StoreError): # code 400, 404 (no such board or item), 409 (stale save, details {"current": item})

class Research:
    def __init__(self, library: Path | None = None)       # config.ART by default; boards: Research/, Books/<id>/research/
    def boards(self) -> list[dict]                         # [{"board": None, "title": "Shared board", "items": n}, {"board": id, "title": book title, "items": n}, ...]
    def read(self, board) -> dict                          # {"board", "title", "items": [item summary + "pos"], "frames", "tags": {tag: n}, "kinds": {kind: n}, "stamp"}
    def item(self, board, id) -> dict                      # one item in full: fields, "text" (the body), "html" (rendered), "mtime", "resolved" (links), "source_label"
    def add(self, board, fields: dict, at=None, frame=None) -> dict          # note, quote, source, piece, link (text in fields["text"])
    def add_image(self, board, name, data: bytes, fields=None, at=None, frame=None) -> dict
    def clip(self, board, url, at=None, frame=None, *, fetch=None, shoot=None) -> dict    # the network; fetch/shoot injectable for tests
    def update(self, board, id, fields: dict, base_mtime=None, force=False) -> dict      # 409 when the file changed since base_mtime
    def delete(self, board, ids) -> list[str]              # to <board>/.trash; the trash paths of the .md files
    def restore(self, board, names) -> list[dict]          # back from <board>/.trash (names: those paths' file names); new ids when taken
    def layout(self, board, items: dict | None = None, frames: list | None = None, remove_frames: list | None = None) -> dict
    def move(self, board, ids, to, link=False) -> list[dict]
    def search(self, q, board=None, every=False) -> list[dict]   # [{"board", "board_title", "id", "type", "title", "snippet"}]
    def citable(self, board) -> list[dict]                 # [{"key", "label", "csl", "board", "id"}] in reach of a board, in resolution order
    def use(self, book, board, id) -> dict                 # for the text; adds the source to the book's sources.json
    def file(self, rel) -> Path                            # a file to serve under /researchfiles/
    def stamp(self, board, every=False) -> float           # one board, or every board
```

An item summary in `read()`: `id`, `type`, `title` (or empty), `excerpt` (the body's first 280 characters as plain
text), `tags`, `created`, `updated`, the kind's own fields (`source`, `locator`, `source_label`, `url`, `site`,
`published`, `fetched`, `thumb` (an URL), `csl`, `piece` details, `link` details), `pos`
(`{"x", "y", "w", "h", "z", "frame", "placed": bool}`), and `error` for an unreadable file. Reads are cached by
(path, modification time, size), like part 1's piece counts: a board of 500 items reads in under half a second.

### `studio/clip.py` — fetching and reading pages

```python
def fetch(url, *, allow=public_only, timeout=20, limit=10_000_000) -> Fetched   # Fetched(url, final_url, status, ctype, charset, data)
def readable(html: str, url: str) -> dict          # {"title", "site", "author", "published", "lang", "canonical", "markdown"}
def safe_page(html: str, url: str) -> str          # the script-free copy with its policy and base
def picture(html: str, url: str, out: Path) -> Path | None    # Chrome on the safe copy → JPEG; None without Chrome
def webpage_csl(details, url, fetched, taken: set) -> dict
```

### Endpoints (`studio/routes_research.py`, through the route tables)

`b` is a book's id; without it, the shared board.

| Endpoint | |
|---|---|
| `GET /api/research/boards` | every board, for *Move to* and *Link on* |
| `GET /api/research?b=` | the board |
| `GET /api/research/stamp?b=` | its change stamp |
| `GET /api/research/item?b=&id=` | one item in full |
| `POST /api/research/item` `{b, fields, at?, frame?}` | add a note, quote, source, piece or link |
| `POST /api/research/update` `{b, id, fields, base_mtime, force?}` | change an item; 409 with `current` when stale |
| `POST /api/research/delete` `{b, ids}` | to the trash; returns `{"trash": [file names]}` |
| `POST /api/research/restore` `{b, names}` | back from the trash (undo) |
| `POST /api/research/layout` `{b, items?, frames?, remove_frames?}` | positions and frames (merged by id) |
| `POST /api/research/move` `{b, ids, to, link?}` | move or link items to another board (`to`: a book id or null) |
| `POST /api/research/image` `{b, name, data, at?, frame?}` | an image (base64) |
| `POST /api/research/clip` `{b, url, at?, frame?, id?}` | clip a page (`id`: clip an existing clip again) |
| `GET /api/research/search?b=&q=&every=` | search |
| `GET /api/research/citable?b=` | sources in reach (the quote's source select) |
| `POST /api/research/use` `{book, b, id}` | prepare an item for the text (adds its source to the book) |
| `POST /api/research/reveal` `{b, id}` | show a clip's PDF in the file manager |
| `GET /researchfiles/<board>/<file>?w=` | an item's image, picture or PDF; `<board>` is `_shared` or the book's id; `w` asks for a thumbnail |

`/researchfiles/` serves only from a board's `files/` folder, only images (`png`, `jpg`, `jpeg`, `gif`, `webp`) and
PDFs (as a download), never a dot-folder, never outside. Thumbnails are made with Pillow into Studio's cache folder,
not the library.

## Changes to shared files (kept small and additive for the morning merge)

- `studio/web.py`: import `routes_research` with the other route modules.
- `studio/books.py`: `research` joins `QUIET`.
- `studio/shoot.py`: `screenshot()` takes extra Chrome flags and a timeout (defaults unchanged).
- `studio/static/index.html`: *Research* in the top bar; `board.css`, `board.js` loaded after `book-rail.js`.
- `studio/static/app.js`: routes `#/research`, `#/book/<id>/board`.
- `studio/static/book.js`: the *Board* tab (after *Write*); `showBook` mounts the board for that tab;
  `refreshBookView` leaves the board tab to the board.
- `studio/static/book-editor.js`: a *Board* link beside *Settings* in the list's head.
- `studio/static/book-text.js`: one line adding `window.BoardDrop`'s plugins to the text's plugins (as it does for
  `BookTools`).
- `studio/static/book-rail.js`: a *Board* panel whose body `board.js` draws.
- `README.md`, `docs/DESIGN.md`: the board, its files and the clip's network rules.

## Testing

- `tests/test_research.py`: front matter round trip (JSON values, hand-typed strings and block lists, unknown keys
  kept, a file without front matter is a note); ids (diacritics, repeats, reserved names); add, read, update, 409 and
  force; layout merge from two writers; unplaced items placed on read without a write; frames and membership; delete
  to the trash with files; move with links rewritten and a link to the source added; link resolution and a missing
  original; key resolution order; `use` (added, same source reused, conflict → `-2`, quote without a source, image
  copied); search (bodies, tags, every board); a 500-item board reads in under 0.5 s.
- `tests/test_clip.py` (no network): `readable` on fixture pages (an article among navigation and ads, a Dutch page,
  JSON-LD details, a page with no `<article>`); `safe_page` removes scripts, handlers, `javascript:` URLs, refresh,
  frames and adds the policy and base; `fetch` refuses other schemes, a user in the URL, loopback and private
  addresses (including after a redirect, against a local test server with the default `allow`), too many redirects,
  too large a body, and fetches from the local test server when `allow` permits; images and PDFs become the right
  items; `webpage_csl` keys; `clip()` with injected fetch and picture.
- `tests/test_research_web.py`: the endpoints over HTTP (lifecycle, 404s, layout, image upload and serving, the
  `/researchfiles/` confinement, `use`), POST checks from the route tables.
- `tests/js/board.js` (node, skipped without node): the board's pure helpers — frame membership, placement in a free
  spot, reading order of frames, the text a quote becomes (inline or block, quote marks per style), drag payloads.
- Picture: one test runs Chrome on a local page (skipped when Chrome isn't found) and checks a script didn't run.
- In the browser, on a scratch library, light and dark: make each kind; frames; move, link, search; the list; a real
  clip of a public page; drag a short and a long quote into a Dutch piece and check the Markdown file and
  `sources.json`; two windows editing one note (409).

**Ruling: a clip is made in one request** (fetch, read, picture, then the card appears; the board shows "Clipping
example.org…" meanwhile) — cost if wrong: a few seconds' wait per clip; the picture could move to a background step
later without changing the store's functions. The store's public names were sent to part 4 and stay as they are; later
changes only add fields.

## Left to the builder

The extractor's scoring weights; card typography details within Studio's tokens; how the thumbnail cache is pruned;
the exact icon for the rail panel; keyboard shortcuts beyond those named.

## Risks

- **Pages that need scripts** photograph bare and extract little. The author sees it at once (the card shows the
  picture) and keeps the link.
- **Sites refusing an honest User-Agent.** The error says so; the author can save the page as an image or PDF and add
  that.
- **Merge with parts 2 and 4** touches the same few lines of `book.js`, `book-editor.js`, `book-rail.js`, `app.js` and
  `index.html`; each change here is a few added lines with a comment naming part 3.
