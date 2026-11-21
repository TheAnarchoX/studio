# Books, part 4: Claude's tools for books — design

*13 November 2026. Part 4 of the books design (`2026-11-12-books-design.md`, "Parts 2–4"). Written overnight while
the author was asleep: every open question was answered here, and each answer is recorded as a ruling with what it
would cost if it turns out wrong, so the author can overturn any of them in the morning.*

## Intent

Claude helps with a book in every way except writing it. It reads the whole book, searches it, keeps the
bibliography, files research, sets up the book's design and PDF, and proposes things for the author to decide on:
an edit, a note, an index term, a citation, a question. It never changes a word of the manuscript itself. Proposals
wait in the writing window, calmly, until the author accepts or rejects them.

The binding principle is part 1's: Studio works equally well with AI as without. Every capability a tool has also
has a control in the app, and nothing in this part needs a config file (connecting Claude stays the one copy-paste
on the Info page).

### Goals

- Claude can find its way around any book: the shelf, a book's details and order, a piece's text (and an earlier
  version of it), search across the book, the sources, the index terms in use.
- Claude can add sources to `sources.json`.
- Claude can propose edits, notes, index terms, citations and comments. They are stored in the book's
  `suggestions.json`, shown in the writing window and applied only when the author accepts them.
- The author reviews proposals one at a time or a whole batch at once, sees each in place in the text before
  deciding, can take an accepted change back with Ctrl+Z and can bring a rejected one back.
- Claude can see what the author decided, so it doesn't propose a rejected change again.
- The design, page, PDF and preflight tools wrap part 2's composer; the research tools wrap part 3's board.

### Non-goals

- No tool writes manuscript text, the book's details, a piece's status or the order of the book. The one part of
  `book.json` a tool changes is the book's design (`set_book_design`, through part 2's service).
- No chat inside Studio; Claude is used from Claude Code or Claude Desktop through MCP, as for poems.
- No proposals that move or restructure text (split a chapter, reorder pieces): Claude says so in its reply and the
  author does it in the binder.
- No suggestions in captions, titles of other pieces, or `book.json` fields.

### Anti-goals (it fails even if it works)

- A writing window that feels watched: suggestions in the text while the author is writing, counters that grow,
  colours that nag.
- An accept that overwrites typing, loses the cursor, or can't be undone.
- Claude's words appearing in the manuscript without the author's act.
- A tools list that only Claude can use: anything Claude's tools do, the author can do in the app.

## What exists (part 1, v1.2.0)

- `studio/books.py`, the books store: `Books.read`, `piece`, `save_piece` (mtime, 409), `search` and `replace`
  (over the document's text containers: `_containers`, `_matches`, `_rewrite`), `history`, `snapshot_text`,
  `sources`, `save_sources`, snapshots in `drafts/`.
- `studio/manuscript.py`, the only implementation of the dialect: `parse`, `serialize`, `counts`, `title_of`.
- `studio/mcp_server.py`: one `MCPServer("studio")` with the poem tools; `making.py` is the shared-service example
  (the app's routes and the MCP tools call the same functions).
- The writing window: `book-editor.js` (pieces, saving, the poll), `book-text.js` (the ProseMirror text, the margin
  with notes and comments), `book-tools.js` (decorations, `containersOf`, `matchesOf`, `findIn`, `guarded`, the
  palette, the status bar), `book-rail.js` (the panels: Outline, Sources, History, Comments, Find and replace).
- `BookTools.guarded(pieces, run)`: the way part 1 changes open pieces on disk (Find and replace, Restore): the
  pieces are saved, locked, changed on the server, and read again as one change undo can take back.

## Approaches

### Where accepting applies the change

1. **On the server, through the Find-and-replace path (chosen).** The panel calls `guarded(openPieces, decide)`:
   the open pieces are saved and locked, the server applies the change to the Markdown (via `manuscript`), keeps a
   snapshot of the text before, and the open piece is read again as one undo step. Works for a piece that isn't
   open, and for a batch across the book; one implementation of applying.
2. In the open editor, as a ProseMirror transaction. Natural undo, but a batch across twelve pieces would have to
   open twelve pieces, and applying would exist twice (editor and server) to keep Claude-side validation honest.
3. Suggestions written into the Markdown as marks (`[old]{.suggest new="…"}`). Claude would be writing manuscript
   files, every export and the dialect would have to skip them. Ruled out by the binding rule.

**Ruling:** accepting applies on the server through the guarded path — *cost if wrong:* a short pause (save, lock,
reload) per accept; moving to in-editor transactions later changes only the panel's accept call.

### How a suggestion is anchored

1. **The quoted words plus a little context on each side (chosen),** like a text-quote selector: robust to edits
   elsewhere in the piece, readable for Claude, checkable by the server when the suggestion is made.
2. Character offsets or ProseMirror positions: break on the first keystroke before them.
3. Block identifiers: the dialect has none, and adding them would change every file.

**Ruling:** quote plus up to 32 characters of context each side — *cost if wrong:* a short phrase repeated with the
same context lands on its first occurrence; the author sees the place highlighted before accepting.

### Where suggestions show

1. **A Suggestions panel in the rail, with a quiet preview in the text while the panel is open (chosen).**
2. Track changes always visible in the text: noisy while writing; against "calm".
3. Items in the margin beside notes and comments: the margin is already full of notes and comments, and narrows in
   split view.

**Ruling:** rail panel plus an in-text preview only while the panel is open — *cost if wrong:* an author who wants
them visible while writing needs a toggle later; it's one preference.

## The suggestions file

`Books/<Book>/suggestions.json`, written only by `studio/suggestions.py`:

```json
{
  "version": 1,
  "suggestions": [
    {
      "id": "s-7f3a9c21",
      "file": "chapter-1.md",
      "kind": "edit",
      "quote": "the words as they read",
      "before": "up to 32 characters before",
      "after": "up to 32 characters after",
      "in": "text",
      "text": "the replacement",
      "why": "one line for the author",
      "group": "g-2026-11-13T0215-4c1d",
      "label": "Tighten chapter 1",
      "by": "Claude",
      "made": "2026-11-13T02:15:07",
      "status": "open"
    }
  ]
}
```

- `kind` is one of five (**ruling:** edit, note, index, cite, comment — *cost if wrong:* a missing kind such as
  "make this italic" waits for a later round; an unused one is a little dead code):

  | kind | fields | accepting |
  |---|---|---|
  | `edit` | `text` (plain text; empty deletes) | replaces the quoted words, keeping their marks |
  | `note` | `text` (plain text, the note) | inserts a note right after the quoted words |
  | `index` | `term` (default: the quote; `main > sub` for a subentry) | marks the words as an index term |
  | `cite` | `source` (a key in `sources.json`), `locator` (optional, `p. 12`) | inserts a citation right after the words |
  | `comment` | `text` (one line) | marks the words with the author's comment mark, the remark as its note |

- **Ruling:** suggestion text (a replacement, a note, a comment) is plain text, no Markdown; a replacement keeps the
  marks of the words it replaces, as Find and replace does — *cost if wrong:* Claude can't propose italics or a note
  with a title in italics; a `marks` option can come later.
- `in` is `text` (the piece's lines) or `note` (inside a note). Only edits may sit in a note; notes, citations,
  index terms and comments only in the text (a note can't hold a note, and the margin shows comments of the text).
- `before` and `after` are taken from the piece by the server when the suggestion is made, not from Claude.
- `group` ties together the suggestions of one call; `label` is the call's optional name for the group.
- `status`: `open`, `accepted`, `rejected` or `withdrawn` (by Claude); `decided` holds the time of the decision.
- Keys Studio doesn't know are kept on every write, like `book.json`.
- **Ruling:** decided suggestions stay in the file, the newest 1000 of them, so Claude can see what was rejected
  and the author can bring one back — *cost if wrong:* a larger file in a long-running book; the cap is a constant.
- **Ruling:** a `suggestions.json` that can't be read (not JSON, not UTF-8) is never written over: making and
  deciding suggestions are refused with the reason, the panel says so, and the file is unchanged — *cost if wrong:*
  Claude can't suggest until the file is fixed or moved away; nothing is lost.
- Writes are atomic (`store.write_text`) and serialized across processes (the app and the MCP server are separate
  processes) by a lock file, `.studio/books.lock`, made with `O_CREAT | O_EXCL`, retried for up to 5 s and broken
  when older than 30 s. **Ruling:** the same lock covers `sources.json` writes — *cost if wrong:* a crash while
  holding the lock delays the next write by up to 30 s.
- Not in editions (`EDITION_ITEMS` stays as it is), never exported. Being in the book folder, it's part of the
  poll's stamp, so suggestions Claude makes appear in an open writing window.

## Finding the words again

`suggestions.locate(doc, s)` finds a suggestion's words in a piece's document (ProseMirror JSON), using the same
text containers and the same matching as Find (`books._containers`, `_matches`): literal, case-sensitive, never
across a note number, a citation or a line break.

- One occurrence of `quote` in the right kind of container (`in`): that one.
- Several: the one whose surrounding text best matches `before` and `after` (the longest common run next to the
  match, counted on both sides); a tie goes to the first. When the stored context is not empty and no occurrence
  shares any of it, the words count as changed.
- None: changed.

The result is the container, the start and end in its text, and the match's number among all matches of the quote
in the piece (the numbering Find uses). The writing window has the same function in JavaScript over
`BookTools.containersOf`, for the preview in the text.

**Ruling:** the JavaScript `locate` mirrors the Python one, and a shared fixture keeps them in step (as
`test_schema_parity.py` does for the schema) — *cost if wrong:* drift would show a highlight in the wrong place;
the server always locates again before applying, so a wrong place is never written.

## Applying a suggestion

`suggestions.apply(doc, s, sources)` changes the document (ProseMirror JSON) in place; `decide` serializes it with
`manuscript.serialize`, parses it back to check, keeps a snapshot of the text before (`Books._snapshot`, as replace
does, so History holds it), and writes the file once per piece, however many suggestions it accepts there.

- `edit`: like `books._rewrite`: the replacement takes the place of the words and the marks of the text it starts in.
- `index`: the `idx` mark with `term` (null when the term is the words themselves) on the words; marks keep the
  order of `manuscript.SCHEMA["marks"]`.
- `comment`: the `comment` mark with the remark as `note`. When the words already carry a comment, the two notes are
  joined with " · " (builder's call, below).
- `note`: a note node, its text the suggestion's, right after the words.
- `cite`: a cite node `{"items": [{"key", "prefix": "", "locator"}]}` right after the words.

A suggestion whose words have changed, or a citation whose source is no longer in `sources.json`, is not applied: it
stays open and is reported as changed. **Ruling:** a changed suggestion can only be rejected, never forced —
*cost if wrong:* none worth naming; Claude can make it again against the new text.

Accepting several suggestions in one piece locates each again after the ones before it were applied, so an edit
that removes another suggestion's words makes that one changed rather than wrong.

## The shared service: `studio/suggestions.py`

Like `making.py`, one module that the app's routes and the MCP tools both call, with no web or MCP code in it:

- `read(books, book) -> dict`: the file as stored (`{"version", "suggestions"}`), `{"version": 1, "suggestions": []}`
  when there is none; raises `BooksError` 400 when it can't be read.
- `add(books, book, items, label=None, by="Claude") -> {"added": [suggestion], "refused": [{"item": n, "reason"}],
  "group"}`: validates each item, resolves its piece, locates its words in the piece on disk, stores the context,
  refuses duplicates, writes once. Items that fail are reported, the rest are stored.
- `listing(books, book, file=None, status="open") -> [suggestion + {"piece": title, "found": bool, "index",
  "missing": bool}]`: in book order, then by position in the piece; `status` is `open`, `decided` or `all`.
- `decide(books, book, ids, decision, now=None) -> {"accepted", "rejected", "reopened", "changed", "withdrawn"}`:
  `decision` is `accept`, `reject`, `reopen` (a rejected or withdrawn one back to open) or `withdraw` (Claude's,
  open ones only). **Ruling:** an accepted suggestion can't be reopened: its change is in the text, and accepting it
  again would add a second note or citation; Ctrl+Z is its undo — *cost if wrong:* an author who undid an accept and
  wants it back asks Claude again.
- `locate(doc, s)` and `apply(doc, s, sources)`, pure functions on ProseMirror JSON.
- `summary(books, book) -> {"open": n, "any": bool}`, which `Books.read` adds to a book as `suggestions`.

Validation, with messages Claude can act on:

- **Ruling:** the piece is named by file name, file stem or title, case-insensitive; a title shared by two pieces is
  refused with both file names — *cost if wrong:* Claude has to repeat the call with the file name.
- The quote: 1–1000 characters, in one paragraph, heading or line of a poem; not found → "Couldn't find "…" in
  chapter-1.md. Quote the words exactly as they read, without Markdown (no `*`, `^[…]` or `[@…]`)"; several and no
  context given → "… occurs 3 times in chapter-1.md: add `before` or `after` with a few words around the one you
  mean".
- An edit whose text equals the quote, a note or comment without text, a cite of an unknown key, an index term
  longer than 200 characters: refused.
- **Ruling:** kinds whose feature is off are refused: index terms when the book's index is off (or set to first
  lines), citations when sources are off, notes when notes are off — *cost if wrong:* Claude can't prepare an index
  before the author switches it on; its refusal says where to switch it on.
- **Ruling:** a suggestion identical to an open one (same piece, kind, words, context and text/term/source) is
  refused as already waiting; identical to a rejected one, it is refused naming the day it was rejected — *cost if
  wrong:* Claude can't raise a rejected point again in the same words; it can word it differently and say why.
- At most 200 items per call and 1000 open suggestions per book (builder's call on the numbers).

## Claude's tools

Registered on the same `MCPServer("studio")` from a new module, `studio/mcp_books.py`, imported by `mcp_server.py`.
**Ruling:** book tools get their own module; the shared service is `suggestions.py` — *cost if wrong:* file
organisation only. A book is named by its id (folder name) or title, case-insensitive. Each call re-reads the
settings (`config.refresh()`) and makes a `Books(config.BOOKS)`, because the library can change in Settings while the
MCP process runs.

**Ruling:** two more branches exist tonight at `main`, `book-editor-power` and `library-tools`, with no spec yet; they
may touch the rail, the palette, `mcp_server.py` and the Info page. Part 4 keeps its edits to shared files to small
hooks (one panel in the rail, one plugin entry, one import in `mcp_server.py`, list entries in the docs) and is not
merged with them — *cost if wrong:* whoever merges second resolves small conflicts in those hooks.

| Tool | What it does | The same in the app |
|---|---|---|
| `list_books()` | the shelf: id, title, author, kind, language, words, pieces, pieces per status, suggestions waiting | the shelf |
| `read_book(book)` | details, kind, features, style sheet, the order of the book (file, kind, form, status, title, words, notes), source keys with a short label, index terms in use with counts, editions, suggestions waiting per piece | the writing window, book settings |
| `read_piece(book, piece, version=None)` | the piece as Markdown (the dialect), kind, form, status, words, notes, its open suggestions, its history (versions with words); `version` reads an earlier version | the text, History |
| `search_book(book, query, whole_words=False, match_case=False)` | Find across the book: piece, match with context, in the text or a note or caption | Find and replace |
| `list_sources(book)` | `sources.json` in full (CSL-JSON) | Sources |
| `add_source(book, source)` | adds a CSL-JSON item; makes its key when it has none (`vandijk2019`, as the Sources form does); refuses an existing key, and an item with the same DOI or URL, or the same title and year, naming the source already there | Sources → Add source |
| `suggest(book, suggestions, label=None)` | proposes edits, notes, index terms, citations and comments (a list; one group); reports each one it couldn't add | — the author writes directly |
| `list_suggestions(book, piece=None, status="open")` | the suggestions with whether their words are still there; `decided` shows what the author accepted and rejected, and when | the Suggestions panel |
| `withdraw_suggestions(book, ids)` | takes back open suggestions Claude made | Reject |
| `get_book_design(book)` | the design and its choices: `compose.get_design(books, book)` (part 2) | Compose |
| `set_book_design(book, changes, template=None, reset=None)` | changes the design: `compose.set_design(...)` (part 2) | Compose |
| `render_pages(book, pages=None)` | pictures of pages: `compose.render_pages(books, book, pages, fmt="png")` (part 2) | the page preview |
| `export_pdf(book)` | the interior PDF in `exports/`: `compose.export_pdf(books, book)` (part 2; the cover comes later) | Export PDF |
| `preflight(book)` | the print checks: `preflight.run(books, book)` (part 2) | print checks |
| `list_research(book=None, query=None, tag=None, kind=None)` | a book's board or the shared board: `Research.read` / `search` (part 3) | Board |
| `read_research(id, book=None)` | one item in full: `Research.item` (part 3) | Board |
| `add_research(item, book=None)` | adds a note, quote, source, link or web clip: `Research.add` / `clip` (part 3) | Board |

- **Ruling:** three tools beyond the outline in part 1's spec: `list_sources`, `list_suggestions` and
  `withdraw_suggestions` — *cost if wrong:* three small tools; without them Claude can't manage what it proposed.
- **Ruling:** `read_book` includes the source keys and the index terms in use, so citations and index terms stay
  consistent with what the book already has — *cost if wrong:* a long reply for a large book; both lists are capped
  at 500 entries with a count of the rest.
- **Ruling:** `read_piece` can read an earlier version — *cost if wrong:* one optional parameter.
- **Ruling:** `add_source` only adds; correcting a source is the author's, in Sources — *cost if wrong:* a wrong
  date stays until the author edits it; Claude can say what to fix.
- `suggest`'s item shape, in the tool's description:
  `{"piece", "kind", "quote", "before"?, "after"?, "text"?, "term"?, "source"?, "locator"?, "why"?}`. Its reply
  lists the number added and each refusal with the item's number and the reason.
- The server's instructions get a paragraph on books: the dialect in a few lines (notes `^[…]`, citations
  `[@key, p. 12]`, index terms `[words]{.idx term="…"}`, comments `[words]{.comment note="…"}`), that the author
  writes and Claude proposes, and the order of work (read_book → read_piece → suggest; list_suggestions to see what
  happened).
- **Ruling:** a guard test calls every book tool on a throwaway library and checks that no file under
  `manuscript/` changed — *cost if wrong:* none.

### Design and research tools (parts 2 and 3)

Parts 2 and 3 are built tonight on their own branches (`books-part-2`, `books-part-3`). Their tools here are thin
wrappers over the service functions those parts name, in the same pattern: the functions take the books store (or
the library) and the book id, run in the MCP process, and return data; the wrapper formats it for Claude and returns
pictures where the result is visual (as `render` does). **Ruling:** these tools are planned last and built only once
the other branch's service module is built and reviewed; that branch is merged into `books-part-4` (locally, never
into `main`) before they are written — *cost if wrong:* if the interfaces change before the merge, only the thin
wrappers change. If a part isn't ready by the end of the night, its tools are left for the morning and the summary
says so.

## The writing window

### The Suggestions panel

A sixth panel in the rail, after Comments: **Suggestions**, its icon the proofreader's caret.

- **Ruling:** the icon shows only in books that have suggestions (any, open or decided) — *cost if wrong:* an author
  who has never used Claude never sees an empty panel; it appears with the first suggestion. This follows part 1's
  rule that the interface shows only what the book uses.
- **Ruling:** while suggestions wait, the status bar shows a quiet "4 suggestions" after the counts; clicking it
  opens the panel. Nothing else counts or calls attention — *cost if wrong:* an author who wants no reminder at all
  needs a preference.
- The head: kicker *Suggestions*, the book's title, and a quiet line: "4 waiting in 2 pieces".
- A two-way switch under the head: **Whole book** · **This piece** (remembered per window, like the other panel
  settings).
- **Ruling:** the list shows groups newest first (one group per `suggest` call, headed by its label or "Suggested
  13 Nov, 02:15"), and in each group the suggestions in book order — *cost if wrong:* presentation only.
- Each suggestion is one row:
  - the kind, small: *Edit*, *Note*, *Index*, *Citation*, *Comment*; the piece's title when the list is the whole
    book;
  - what it does, in the book's text font: an edit as the words around it with the old struck through and the new
    underlined (the History panel's legend); a note as "after ‘…the words’" and the note's text; an index term as
    the words and "→ term"; a citation as its label (*Author, year, p. 12*) after the words; a comment as the words
    and the remark;
  - `why`, in the quiet secondary colour;
  - **Reject** and **Accept** (Accept the solid one).
- A group of two or more ends its head with **Reject all** and **Accept all**; accepting or rejecting more than one
  asks first ("Accept 14 suggestions in 6 pieces?"), with Studio's own dialog.
- A suggestion whose words have changed shows "The words this was about have changed." and only **Reject**. One in a
  piece that left the book shows "This piece is no longer in the book." and only **Reject**.
- At the bottom, **Decided** (folded): the latest 50 decided ones with their decision and time, each rejected or
  withdrawn one with **Bring back**. This is the undo for a rejection.
- Empty: "No suggestions waiting. When you ask Claude for edits, notes, index terms or citations, they wait here
  until you accept or reject them."
- **Ruling:** keys in the panel: arrows move, Enter goes to the place in the text, A accepts and R rejects the
  focused suggestion (only when a row has focus, never in the text), and right-click on a row gives Go to, Accept,
  Reject — *cost if wrong:* single letters only act on a focused row.
- Accepting: `guarded(openPieces(files), () => api decide)`. Part 1's reload after a guarded change keeps the text it
  replaced as a "wasn't saved — Put it back" copy; after an accept it doesn't (**ruling:** the text before is a
  snapshot in History, and the bar would say something untrue — *cost if wrong:* none; Find and replace and Restore
  keep part 1's behaviour). The toast says "Accepted. Ctrl+Z in the text takes it
  back" (for one) or "Accepted 14 in 6 pieces. The text before is in each piece's History". A changed one is said
  ("2 couldn't be applied: their words have changed").
- **Ruling:** Ctrl+Z after an accept takes the text back; the suggestion stays accepted (Bring back is for rejected
  and withdrawn ones, see "The shared service") — *cost if wrong:* an author who undid an accept and wants it back
  asks Claude again.

### In the text, while the panel is open

- The words of every open suggestion in the piece get a faint dotted underline in the window's accent (`--red`, as
  Find's current match and comments use).
- The current suggestion (the row with focus, or the one under the cursor) previews its change in place: an edit's
  words struck through with the new text after them, underlined; a note as a faint note number; a citation as its
  faint label; an index term with its term shown in a tooltip; a comment highlighted as comments are, with the remark
  in a tooltip.
- Right-click on underlined words: **Accept suggestion**, **Reject suggestion**, **Show in Suggestions**.
- Closing the panel removes every mark; nothing shows while writing.
- Clicking a row opens its piece (in the pane it's open in, or the main pane), selects the words and scrolls them to
  a third of the height, as Find does.

### Elsewhere

- The command palette has *Suggestions* (the rail lists its panels there already).
- The Info page's list of tools and the README's Claude section get the book tools.
- **Ruling:** the shelf shows nothing about suggestions — *cost if wrong:* none; the writing window is where they
  are decided.

## Server endpoints

In `routes_books.py`, thin wrappers over `suggestions.py`:

| Endpoint | |
|---|---|
| `GET /api/book/suggestions?b=&status=open\|decided\|all` | `listing`, plus the group labels |
| `POST /api/book/suggestions/decide` `{b, ids, decision}` | `decide`; `decision` is `accept`, `reject` or `reopen` (not `withdraw`, which is Claude's) |

`GET /api/book` gains `suggestions: {"open", "any"}`.

## Testing

- `tests/test_suggestions.py`: the file (missing, unreadable kept, unknown keys kept, the decided cap); `add`
  (each kind, each refusal, duplicates, a rejected one, features off, piece by title and stem); `locate` (one, many
  with context, changed, notes, poems' lines); `apply` for each kind (marks kept on an edit, mark order on an index
  term, a note and a citation after the words, an existing comment joined); `decide` (accept writes the file once
  per piece and keeps a snapshot, changed ones stay open, reject, reopen, withdraw only open); the lock across two
  processes.
- `tests/test_mcp_books.py`: each tool's reply on a throwaway library, and the guard that no tool changes a file in
  `manuscript/`.
- `tests/test_books_web.py`: the two endpoints and `suggestions` in `GET /api/book`.
- `tests/js/book_suggest.js` (run from a Python test in node, like `book_tools.js`): `locate` on the shared fixture,
  the row's text for each kind.
- `tests/e2e_mcp.py`: the book tools on its throwaway library over stdio.
- In the browser with a throwaway library: the panel, each kind's row and preview, accept with the piece open (one
  undo step), accept all across pieces, a changed suggestion, Bring back, the status bar line, the icon hidden in a
  book without suggestions; screenshots for the morning summary.

## Left to the builder

- The exact copy of rows and messages within the rules above (plain, sentence case, no badges).
- The caret icon's drawing, in the rail's 18 px stroke style.
- Joining an existing comment's note (" · ") or another rule that keeps both.
- The numbers: 200 items a call, 1000 open, 1000 decided kept, 500 entries in `read_book`'s lists, 32 characters of
  context.
- Where the JavaScript lives: a new `book-suggest.js` (panel, preview, `locate`) registered with the rail and the
  text's plugins is expected; folding it into `book-rail.js` is acceptable if it stays readable.

## Risks

- **Two processes, one file:** the lock file serializes writes to `suggestions.json` and `sources.json`; tested with
  a second process.
- **Locating the same words twice (Python and JavaScript):** the shared fixture; the server always decides.
- **A long batch accepted at once:** one write per piece, one snapshot per piece, one reload per open piece.
- **Parts 2 and 3 not ready:** their tools wait; everything else stands alone.
