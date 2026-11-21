# Home as a desk — design

Status: approved in conversation with the author on 2026-11-21; to be built after 1.3.0, for 1.3.1.

## Why

Every other part of Studio shows the work itself: poems set in type, pages, designs. Home shows lists about the
work: a large "Home" heading that says nothing, four equal buttons, one Continue card that leaves half the width
empty, and rows of names with small swatches. It reads as a generic dashboard, not a studio.

## What Home is for

Home is a **desk**: it gets you back into the work, and it shows the work as itself. The author chose this over a
view of the whole body of work, a daily companion, and a near-empty start page.

Decisions (the author's answers):

1. One thing large, a few smaller: the last thing you worked on, shown as itself, and below it a short pile of other
   open work.
2. Besides the desk, Home keeps: **today's writing**, **what's waiting for you**, and **your series and books as
   objects**. It drops the New / New series / New book / Import book buttons (the top bar's **+ New** menu starts
   things) and the plain Recent list.
3. Direction A, "the page": the text as you left it, with the day in a narrow column beside it (over B, set pages and
   designs as the main objects, and C, one line as a headline over a contents page).
4. Clicking anywhere in the page opens the writing window with the cursor at that spot; **Continue writing** puts
   you exactly where you stopped. Home itself is not an editor.
5. When the last thing was a poem, the desk shows its lines as in the notebook **and** its latest design beside them.
6. The pile holds the four most recently touched things that aren't done yet.

## Layout (wide window)

From the top, under the app bar:

- **Date line:** a small kicker with today's date in the interface's locale ("Saturday 21 November").
- **One plain sentence:** "You stopped in *The Kitchen Table*." (the title in italics, the piece's or poem's own
  title). Under it, quiet metadata: where it lives and when ("A Year of Small Things · chapter 3 · two hours ago").
- **The page and the day**, side by side: the page takes the width, the day is a fixed narrow column (about 290 px)
  to its right, top-aligned with the page.
- **Also open:** a row of four objects.
- **The shelf:** your series, then your books.
- Whatever other areas add to Home through `window.homeSections` that the new Home doesn't place itself goes after
  the shelf, unchanged.

### The page (the desk)

- **A piece of a book:** a panel the width of a comfortable reading column, holding the piece's title and the few
  paragraphs (about 120 words) up to and including the paragraph where you stopped, in the same type the writing
  window uses for that book. Earlier paragraphs are dimmer; the paragraph you stopped in is full strength, with a
  red caret at the exact place. Under the text, one button: **Continue writing**.
- **A poem:** its lines as the notebook shows them (title, stanzas, the notebook's type), with the caret where you
  stopped, and to the right its latest design at thumbnail size in its own colours, or a quiet "No design yet" in
  the same space. **Continue writing** opens the Write tab; clicking the design opens it in the Design tab.
- **A design, when that was the last thing touched:** its poem's lines with the design beside them, as above;
  **Continue** opens the Design tab.
- Clicking a word in the page opens the writing window (or the notebook) with the cursor at that word, scrolled into
  view. The whole page is one link target for the keyboard: Enter continues where you stopped.

### The day (the narrow column)

- **Today:** words written today across the library, large; under it the daily goal of the book you're writing, when
  it has one ("of 500 a day for this book"); seven thin bars for the last seven days, today's in red; "This week"
  and the total. The heading links to the Writing log. Before anything is written today: "Nothing written yet
  today", with the week still shown.
- **Waiting for you:** only things that need you, each one line that goes straight to the place, most urgent first:
  - a backup that failed or stopped (the line Home shows in 1.3.0 moves here);
  - Claude's suggestions still to decide, per book ("4 suggestions in A Year of Small Things"), opening the writing
    window with the Suggestions panel;
  - print notes, per book, from the last print check ("2 print notes in …"), opening Compose's checks;
  - poems ready for art ("3 poems ready for art"), opening Poems filtered to Ready.
  When nothing is waiting: "Nothing waiting".

### Also open (the pile)

- The four most recently touched things that aren't done, not counting the one on the desk:
  - poems whose status is draft, ready or in review;
  - pieces not marked final;
  - designs not exported since they last changed.
- Each is shown as itself at the same size (about 4:5):
  - a poem: its first lines in its series' display type on its series' colours;
  - a piece: a few lines from where you stopped, in the book's type, on a panel;
  - a design: its thumbnail.
- Under each object, its name and what it is ("Morning, Unfinished · poem"). Clicking opens it where you stopped.
- Fewer than four: the row is shorter; none: the row is left out.

### The shelf

- **Series** as small covers in their own look (palette and display font, the series name), then **Books** as the
  covers the Books page shows. Each row has its "All series →" / "All books →" link.

## Where you stopped

Studio doesn't remember this across sessions today: the writing window keeps the cursor per piece in memory only,
and Home's Continue shows a piece's last paragraph. New, and small:

- **Pieces:** every save of a piece also sends the cursor's place (the top-level block index and the character offset
  in it). Studio keeps the latest per piece in the book's `.studio/places.json` (`{"<file>": {"block", "offset",
  "when"}}`), written with the book's existing locking, never in the Markdown.
- **Poems:** the notebook's save sends the caret's line and column; kept in the poem's `.studio/place.json`.
- A place that no longer fits the text (the piece got shorter elsewhere) falls back to the end of the piece.
- The writing window and the notebook accept a place in their link and open with the cursor there and scrolled into
  view; without one they behave as now.

## Data

`GET /api/home` gains, next to what it returns now:

- `desk`: `{kind, title, where, when, href, label, place, blocks}` for the last thing worked on (any status), where
  `blocks` is the short run of text for the page (`[{text, kind}]`, inline italics kept as marks) and `place` points
  into it; for a poem, its lines and its latest design's id (or null).
- `open`: up to four items like `desk`, with a shorter excerpt.
- `waiting`: `[{kind, count, book?, href}]`, built from the backup brief, each book's open suggestions, each book's
  last print check and the poems' statuses.
- The writing log's figures come from `GET /api/writing`, as the Writing log page reads them.

Home must stay fast: excerpts are computed only for the desk and the pile, reusing the mtime-keyed reads Home already
does, and one unreadable book or poem never takes Home down (its item is left out).

## Edges

- **Empty library:** instead of an empty desk, one short invitation with **Start a poem** and **Start a book**.
- **Nothing on the desk** (a library with only finished work): the desk shows the last thing you touched anyway.
- **Narrow windows:** under about 1100 px the day column moves below the page; under about 800 px the pile shows
  two objects a row.
- **Themes:** light and dark both, from the app's tokens. No animation beyond what Studio already does.
- **Examples:** the example series and book count like any other work on the desk and the pile, but stay out of the
  writing figures, as the Writing log already does.

## Not in this

Editing on Home itself; a greeting ("Good morning"); rearranging Home; badges, counters in circles or other
decoration; new statuses.

## Testing

- Python: `/api/home`'s `desk`, `open` and `waiting` for libraries with books, poems, designs, suggestions, print
  checks and a failed backup; place saving and the fallback; nothing personal in fixtures.
- Node: the pure helpers (place mapping from a click, the pile's choice, the waiting order).
- Browser, on a scratch library: light and dark at four window widths; a click in the page lands the cursor at that
  word; Continue lands exactly where you stopped, for a piece and for a poem.
