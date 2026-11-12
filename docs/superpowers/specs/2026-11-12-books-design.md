# Books in Studio — design

*12 November 2026. Agreed in a design conversation with the author; this spec details part 1 and outlines
parts 2–4, which get their own specs before they are built.*

## Goal

A place in Studio to write a book and take it to an almost print-ready PDF: a writing window that feels light and
comfortable but has everything under the hood, a composer for book design, a board for whatever feeds the
writing, and tools that let Claude help without touching the prose. Books are a separate area from poems;
articles (blogs, essays, media pieces) follow later as a third area built on the same parts.

The first book is a Dutch memoir that mixes prose, poems and opinion, written over many years and imported from
Google Docs. It sets the bar: mixed forms in one book, editions over time, notes and references, Dutch typesetting.

## Decisions

| Question | Decision |
|---|---|
| Where a book is written | In Studio. Import from Google Docs once; Studio is the source from then on. |
| Notes and references | All four: footnotes, endnotes in the back, sources and bibliography, subject index. |
| Idea and research space | One board per book plus one shared board; items can be moved or linked between them. |
| Claude | Everything but the prose: reads all, writes research, sources and suggestions, sets up design and PDF. Never edits manuscript text; suggested edits are accepted or rejected by the author. |
| Split | Part 1 books and writing editor, part 2 composer and PDF, part 3 research board, part 4 Claude's tools. |
| Page engine | Typst (the `typst` Python package, compiler included). |
| Manuscript | One Markdown file per piece, Pandoc-compatible dialect, edited in a ProseMirror editor that never shows Markdown. |
| Adaptive interface | A book has a kind that presets features; the interface shows only what the book uses. |
| Mixed forms | Each piece has a form (prose, poem, essay, letter); poems can link to the Poems library. |
| Growth over time | Editions freeze a dated copy of the whole book; per-piece history for day-to-day changes. |

## On disk

Next to `Poems/` in the library folder:

```
Books/
  <Book title>/
    book.json            details, kind, features, the order of the book, goals, design (part 2)
    manuscript/          one Markdown file per piece
    images/              images used in the text
    drafts/<piece>/      dated snapshots per piece (YYYY-MM-DDTHHMM.md)
    editions/<date name>/ frozen copies: book.json, manuscript/, sources.json, cover/, the PDF
    sources.json         the bibliography, CSL-JSON
    suggestions.json     Claude's suggested edits, waiting for the author (part 4)
    research/            this book's board (part 3)
    cover/               the cover design (part 2)
    exports/             PDF, .docx, Markdown
Research/                the shared board (part 3)
```

Deleting a book or a piece moves it to `Books/.trash/`, like poems.

### book.json

```json
{
  "version": 1,
  "title": "", "subtitle": "", "author": "", "language": "nl",
  "kind": "memoir",
  "features": {"notes": "endnotes", "noteNumbering": "chapter", "sources": true, "index": true,
               "figures": false, "contentNote": false},
  "details": {"isbn": "", "publisher": "", "edition": "", "year": 2026, "copyright": "", "contentNote": ""},
  "contents": [
    {"auto": "half-title"}, {"auto": "title-page"}, {"auto": "copyright"},
    {"file": "dedication.md", "kind": "dedication"},
    {"auto": "toc"},
    {"file": "foreword.md", "kind": "foreword", "status": "draft"},
    {"file": "part-1.md", "kind": "part"},
    {"file": "chapter-1.md", "kind": "chapter", "form": "prose", "status": "idea"},
    {"file": "a-poem.md", "kind": "chapter", "form": "poem", "status": "final"},
    {"auto": "notes"}, {"auto": "bibliography"}, {"auto": "index"}
  ],
  "goals": {"daily": 0},
  "design": {}
}
```

- `contents` is the order of the book; reordering never renames files. A piece's title is the first `# ` heading
  of its file (pieces without one, like a dedication, show their kind).
- `auto` entries are pages Studio generates from the details and the text: half-title, title page, copyright
  page, table of contents, notes, bibliography, index. They can be moved or removed like any entry.
- `status` per piece: `idea`, `draft`, `revised`, `final`.
- `features.notes`: `off`, `footnotes`, `endnotes` or `both` (footnote on the page and listed in the back);
  `features.noteNumbering`: `chapter` (restart per piece) or `book` (continuous).
- Unknown keys are kept on save, so later parts and hand edits survive.

### Book kinds

A kind only sets defaults. The kind can change at any time, and every feature can be switched on or off in the
book's settings.

| Kind | Notes | Sources | Index | Default structure |
|---|---|---|---|---|
| `fiction` (novel, stories, fanfic) | off | off | off | chapters, scenes, scene breaks |
| `memoir` (and creative nonfiction) | endnotes per chapter | optional | off | dedication, epigraphs, optional content-note page |
| `nonfiction` (popular) | endnotes keyed to the text | on | on | parts and chapters |
| `academic` | footnotes, citation style | on | on | figures and tables numbered, appendices, abstract |
| `poetry` | off | off | first lines | one poem per page, poems from the Poems library |
| `essays` (and anthologies) | per piece | optional | optional | each piece may have its own author |

Piece kinds: `dedication`, `epigraph`, `content-note`, `foreword`, `preface`, `introduction`, `prologue`, `part`,
`chapter`, `interlude`, `epilogue`, `afterword`, `acknowledgements`, `appendix`, `about-author`; plus the `auto`
pages. Forms: `prose` (default), `poem` (line breaks kept, not justified), `essay`, `letter`.

When a feature is off, its buttons, `/` items, rail panels and generated pages disappear. Marks already in the
text are never deleted: they stay, shown quietly, and come back when the feature is switched on.

## Manuscript format

Plain Markdown, Pandoc-compatible, so a file reads well anywhere and converts with standard tools.

| Element | Markdown |
|---|---|
| Piece title | `# Title` (first line) |
| Section heading inside a piece | `## Heading` |
| Italic, bold | `*italic*`, `**bold**` |
| Note | `^[note text, may contain *italics*]` placed where the number goes |
| Citation | `[@key]`, `[@key, p. 12]`, `[see @key, pp. 3–5]`; keys are in `sources.json` |
| Index term | `[Name]{.idx}`; `[the trauma]{.idx term="trauma"}`; subentry `term="trauma > childhood"` |
| Comment to self | `[marked text]{.comment note="check this date"}` (never printed or exported) |
| Small caps, other language | `[text]{.smallcaps}`, `[text]{lang=en}` |
| Scene break | `***` on its own line |
| Epigraph | `::: epigraph` … `:::`; a last paragraph starting with an em dash is the attribution |
| Poem inside prose | `::: poem` … `:::` (line breaks kept) |
| Linked poem | `::: {.poem src="<Series>/<Poem folder>"}` `:::` (text comes from the Poems library) |
| Image | `![caption](../images/name.jpg){width=60%}` |
| Page break | `::: pagebreak` `:::` |

In a piece whose form is `poem`, every line break is kept and blank lines separate stanzas.

One parser and serializer, in Python (`studio/manuscript.py`, built on `markdown-it-py` and `mdit-py-plugins`),
converts between Markdown and the editor's document (ProseMirror JSON). The editor loads and saves that JSON;
the server writes Markdown. Word counts, search, export, the composer and Claude's tools all use the same
module, so the dialect has a single implementation. Round-trip tests guarantee that Markdown → document →
Markdown returns the same text for every element above.

## Studio interface

**Navigation.** The top bar gets *Poems · Books*. The shared board joins in part 3; *Articles* later.

**Shelf** (`#/books`): a card per book (title, kind, word count, last written, status of its pieces), *New book*
and *Import*. Right-click a book for its actions (open, settings, freeze edition, export, move to trash).

**New book:** title, author (defaults to the signature in Settings), language, and the kind, shown as cards with
their defaults in one line each.

**Book** (`#/book/<title>/write/<piece>`): the writing window. *Compose* and *Board* tabs appear when parts 2 and
3 exist.

- **Binder (left, can be hidden):** front matter, body and back matter; drag to reorder, including into a part;
  word count and status per piece; `auto` pages shown as such; *+ Chapter* and a menu for other kinds;
  right-click for rename, kind, form, status, duplicate, split here, merge with next, move to trash.
- **Text column (middle):** about 65 characters wide in the book's typeface, generous leading, no toolbar.
  - Selecting text shows a small bar: bold, italic, note, source, index, comment (only the enabled ones).
  - `/` at the start of a line or after a space opens the insert menu: note, citation, scene break, epigraph,
    poem, image, page break, linked poem.
  - Markdown shortcuts work while typing (`*`, `**`, `## `, `> `, `***`).
  - Notes stand in the margin next to their number while writing, wherever they end up in print. Clicking the
    number edits the note in place.
  - Citations show as a quiet label (*Author, year, p. 12*); index terms as a faint underline; comments as a
    highlight with the comment in the margin.
- **Rail (right, closed by default):** outline (headings, scene breaks, notes of this piece), sources (search,
  add, edit `sources.json` entries; insert a citation), history (snapshots with compare and restore), comments,
  find and replace across the book (plain or whole-word, case-sensitive option, replace one or all).
- **Focus mode:** hides binder and rail; the current paragraph lit, the rest dimmed; typewriter scrolling.
- **Command palette (Ctrl+K):** jump to any piece, run any action, change kind or features.
- **Split view:** two pieces side by side (the board joins in part 3).
- **Writing tools:** spellcheck in the book's language (and per `lang` span), read aloud, counts, echo finder
  (the same word, five letters or longer, again within 150 words), sentence rhythm, an optional daily word goal
  shown as a quiet line in the status bar.
- **Saving:** autosave after 1.5 s without typing and when leaving a piece; a snapshot in `drafts/` when leaving
  a piece that changed and after every 30 minutes of writing; unchanged text is never snapshotted.

**Book settings:** details (title, subtitle, author, language, ISBN, publisher, edition, year, copyright,
content note), kind and features, daily goal. **Freeze edition** asks for a name and copies the book into
`editions/`.

Style follows Studio: editorial, quiet, no badges or flourishes; right-click menus everywhere; keyboard first.

## Import

`POST /api/book/import` takes a .docx or Markdown file (base64 in JSON, like the rest of the API) and returns a
proposal; nothing is written until the author confirms on the review screen.

- .docx goes through `mammoth` to semantic HTML, then into the manuscript dialect: headings, italics, bold,
  footnotes and endnotes (as `^[…]`), quotes, lists, images (saved to `images/`).
- Splitting: each Heading 1 (or `# ` in Markdown) starts a piece. The Title style or a first `# ` before any text
  becomes the book title, and a following Subtitle or `## ` line the author when it matches the signature,
  otherwise the subtitle.
- Empty headings and runs of empty paragraphs used for spacing are dropped.
- A short italic paragraph before the first piece becomes a dedication. A quote at the start of a piece, followed
  by a line starting with a dash, becomes that piece's epigraph. Known headings (Voorwoord, Foreword, Preface,
  Inleiding, Introduction, Epiloog, Nawoord, Dankwoord, Acknowledgements …) get their kind.
- The review screen lists the proposed pieces with kind, form, first words and word count; the author can
  change kinds, merge or split before importing.
- Google Docs: export as .docx (File → Download) or let Claude fetch it from Drive; both end up here.

## Export (part 1)

- **.docx** (`python-docx`): piece titles as headings, italics, scene breaks, epigraphs, poems with line breaks;
  notes as a numbered *Notes* list at the end of each piece; comments left out.
- **Markdown:** the manuscript as one file, or a zip of `manuscript/` with `book.json`.
- PDF comes with part 2.

## Server

New module `studio/books.py` (the books store, like `store.py` for poems) and `studio/manuscript.py`. New
endpoints, with the same local-only checks as the rest:

| Endpoint | |
|---|---|
| `GET /api/books` | the shelf |
| `POST /api/books` | create a book |
| `GET /api/book?b=` | book.json plus per-piece title, status, words |
| `POST /api/book/update` | details, kind, features, contents order, goals |
| `GET /api/book/piece?b=&f=` | the piece as editor JSON, plus words |
| `POST /api/book/piece` | save a piece (editor JSON); returns words and snapshot info |
| `POST /api/book/piece/new`, `/delete` | add a piece of a kind and form; move one to the trash |
| `GET /api/book/history?b=&f=`, `POST /api/book/restore` | snapshots; restore one |
| `POST /api/book/import`, `/import/commit` | propose an import; write it |
| `GET /api/book/export?b=&format=docx\|md` | download an export |
| `POST /api/book/edition` | freeze an edition |
| `GET /api/book/search?b=&q=` | find across the book; `POST /api/book/replace` |
| `GET /api/book/sources?b=`, `POST /api/book/sources` | read and write `sources.json` |

The poll stamp includes `Books/`, so changes by Claude or another window appear while writing (an open piece is
never overwritten under the cursor; a changed-on-disk notice offers to reload).

## Editor engine

ProseMirror, vendored as one ES module, `studio/static/vendor/prosemirror.js`, built from pinned npm versions by
`tools/build_vendor.mjs` (esbuild); the file is committed, so running Studio needs no Node and no build. Its
schema mirrors the manuscript dialect: nodes for doc, title, heading, paragraph, scene break, epigraph,
attribution, poem, linked poem, image, page break, note (inline, with its own content); marks for italic, bold,
citation, index, comment, small caps, language. New front-end files: `book.js` (shelf, settings, import),
`book-editor.js` (writing window), `book.css`.

## Parts 2–4 (outline; each gets its own spec)

**Part 2, composer and PDF.** Book design as data in `book.json` (`design`), turned into Typst by
`studio/compose.py`: templates per kind, trim size presets (A5, 135×210 mm, 5.5×8.5 in, 6×9 in, custom), margins
with inside/outside, bundled OFL book typefaces, running heads and feet per piece kind with first-page variants,
roman numbering in the front matter and arabic in the body, chapters on right-hand pages, drop caps, TOC, notes
as footnotes or endnotes (or both), bibliography in CSL styles, a subject index with page numbers, poems set as
poems. A live spread preview (pages as images, recompiled after each change), print checks (widows and orphans,
overfull lines, fonts, image resolution, page count), bleed, and the cover in Studio's design editor at the
book's trim size with a spine width from page count and paper. Exports: interior PDF, cover PDF.

**Part 3, research board.** A canvas and a list view over the same items: notes, images, web clips (fetched by
the server, saved as a readable copy with a screenshot and the link), quotes, sources, links to pieces; frames to
group, tags, search. Items are files in `research/` with positions in `research/board.json`; the shared board is
`Research/`. Dragging a quote into the text inserts it with a citation and adds the source.

**Part 4, Claude's tools.** `list_books`, `read_book`, `read_piece`, `search_book`, `list_research`,
`add_research`, `add_source`, `suggest` (index terms, notes, edits; stored in `suggestions.json` and shown in the
editor to accept or reject), `get_book_design`, `set_book_design`, `render_pages`, `export_pdf`, `preflight`.
No tool writes manuscript text.

## Testing

- `tests/test_manuscript.py`: round trip for every dialect element, poems, nested notes with italics, citations
  with locators, index subentries, Unicode and Dutch quotes; Markdown → editor JSON → Markdown is identical.
- `tests/test_books.py`: create, reorder, kinds and features, snapshots and restore, trash, editions, search and
  replace, unknown keys kept.
- `tests/test_import.py`: a .docx fixture generated in the test with python-docx (title, author line, spacer
  headings, dedication, epigraph, footnotes, two chapters) → the expected pieces and kinds.
- Export: the .docx opens with python-docx and holds the expected headings and notes.
- In the browser: typing, the selection bar, `/` menu, notes in the margin, binder drag and drop, autosave and
  history, focus mode, the import review screen, with a throwaway library.

## Not in part 1

PDF and book design, the board, Claude's tools, the cover, syncing with Google Docs, collaboration, mobile.

## Risks

- **Spellcheck in the app window:** WebView2 spellcheck for contenteditable must be verified early; fallback is a
  bundled Hunspell dictionary (nspell) for the book's language.
- **Dialect parity:** one Python implementation, and the editor never parses Markdown itself.
- **Large books:** pieces load one at a time; search and counts run on the server.
- **Import fidelity:** the review screen catches wrong splits before anything is written.
