# Library tools: backups, a writing log, and one search — design

*13 November 2026. Written overnight while the author slept. The author asked for these three features ("add those
too") and handed over every decision, so each choice below is a ruling written as "Ruling: … — cost if wrong: …". The
author can overturn any of them in the morning; the cost line says how much that would take.*

## Why

The library is plain files, and for many authors it is the only copy of years of poems and of books in progress. Three
things are missing from a studio that holds a life's work:

1. **A safety net.** Nothing in Studio keeps a second copy. A bad sync, a deleted folder or a dead disk would take
   everything. Backups must run by themselves, be honest when they can't, and give work back without ever overwriting
   what is there now.
2. **A record of the writing.** Books already count words per day for the daily goal (`.studio/days.json`), but the
   numbers are only visible as a goal line inside the writing window. A writer who wants to know how the month went has
   no place to look.
3. **A way to find things.** The Poems page filters by title and the book window searches one book. A line half
   remembered ("the one with the lighthouse") can't be found across the library.

## Goals, non-goals, anti-goals

**Goals**

- Rolling backups of the library's Studio folders, automatically on start and daily, plus *Back up now*; a folder the
  author chooses; bounded retention; restore of a whole backup or one poem, book or piece, inside Studio, never over
  what exists.
- A writing log: words per day, week and month, per book and for poems, the daily goal and how often it was met.
- One search across poems, series, designs, books and their pieces (and research items once part 3 lands), from Ctrl+K
  anywhere, grouped, keyboard first, jumping to the match.

**Non-goals (this round)**

- Backing up folders in the library that aren't Studio's (see B1), incremental or deduplicated backups, encryption,
  cloud upload (choose a synced folder instead).
- Restoring a series, a style or a research item on its own (a whole-backup restore covers them).
- MCP tools for search, the log or backups (part 4 owns Claude's tools; these modules are ready to be wrapped).
- Searching old drafts, briefs, kits or bibliographies.
- A goal for poems.

**Anti-goals: failures even if it "works"**

- A backup that can lock, slow or corrupt the library while the author writes, or that deletes anything in the library.
- A restore that overwrites the author's current text without a plain-words confirmation.
- A backup failure that only shows in a log file.
- Streaks, badges, flames, coloured "good day / bad day" marks, or congratulations in the writing log.
- A search that silently shows stale results, or freezes the window on a large library.

## Constraints (from the project)

- Files are the database; never rewrite a user's file on read; never lose a file; deletes go to `.trash`.
- Every endpoint through the route tables (`routes.py`): Host check; Origin and JSON checks on POST.
- Every view escapes user text. Interface copy plain, sentence case, no badges; right-click menus on lists.
- Every setting has a control in the app (Settings edits every key of `config.DEFAULTS`).
- Studio works equally well with AI as without.
- Tonight's siblings own other files: `book-text.js`, `book-editor.js` and `manuscript.py` (book-editor-power), the
  composer (part 2), the research board (part 3), Claude's tools (part 4). So this work lives in new modules and touches
  `app.js`, `home.js`, `index.html`, `web.py`, `store.py`, `config.py` and `book-tools.js` only in small, additive
  places (listed at the end).
- Nothing personal in the repo.

## What a library looks like (measured, read-only)

On a real library measured while designing this, Studio's own folders were a few MB of text once renders were left out
(most of `Poems/` was design exports and carousel PNGs, both rebuildable), and the library folder also held over a
gigabyte of other art that Studio doesn't manage. Imported poems can share one draft date: poems imported together each
have one draft, stamped on the day of the import.

These two facts drive two rulings: backups cover Studio's folders, not the whole library folder (B1), and the writing
log records poem words from now on instead of deriving them from drafts (W2).

---

## 1. Backups

### Approaches considered

1. **A zip per backup, written beside, verified, renamed into place (chosen).** One file per backup; any drive works
   (NTFS, exFAT and FAT32 sticks, network shares, cloud-synced folders upload one file); a backup can be opened in
   Explorer without Studio; atomic by rename. Each backup is a full copy, which is fine at a poetry library's size
   (a few MB once renders are skipped) and kept bounded by retention and by skipping unchanged days.
2. **Folder snapshots with hard links for unchanged files** (Time Machine style). Space-efficient and browsable, but
   hard links need one NTFS volume (no exFAT sticks), cloud sync clients upload every linked file again, and editing a
   file inside one snapshot changes it in all of them.
3. **A mirror (one folder kept in sync).** Cheapest, but it copies a mistake over the only good copy within a day:
   not a backup.

### Rulings

- **B1. What is backed up.** Studio's folders in the library: `Poems/`, `Books/`, `Styles/` and `Research/` (part 3's
  shared board), whichever exist. Other folders and files in the library folder are not, and Settings says so with
  their names and size ("Not backed up: 3 other folders in the library, 1.2 GB"). — cost if wrong: the author assumed
  their other art was in the backup; the Settings line says it isn't, and adding a folder list is a setting and a few
  lines.
- **B2. What is skipped inside them** (rebuildable or deliberately discarded): `Design renders/` folders; a kit's
  renders: in a poem folder, PNG files whose name starts with the poem's slug and a hyphen (anywhere below it) and the
  preview page `<slug>.html`; `.trash` folders everywhere (including research boards'); `__pycache__` and
  `node_modules` folders; Studio's temp files (`.<name>.<pid>.<thread>.tmp`) and `*.partial`. Kept: `drafts/`,
  `editions/`, `exports/` (a dated export is a record of what was sent, not rebuildable once the text moves on),
  `.studio/` (the writing log), `_kit/`, `stamps/`, fonts, images, `qa.json`, research `files/`. — cost if wrong: after
  a disaster, carousels and design exports must be rendered again (minutes), and they can differ if a kit changed since.
- **B3. Format.** One zip per backup: Deflate for text and JSON, stored (no compression) for PNG, JPEG, WebP, GIF, PDF,
  WOFF/WOFF2 and ZIP. Paths in the zip are relative to the library, so unzipping gives a library folder. — cost if
  wrong: a library of many GB of images makes each backup large; switching to hard-link snapshots is a rewrite of
  `backup.py`'s writer only.
- **B4. Atomic finalisation.** Written as `<name>.zip.partial` in the backup folder; flushed and fsynced; reopened and
  verified (every member's CRC, and the manifest reads back); then `os.replace` to `<name>.zip`. A leftover `.partial`
  (crash, power cut) is deleted at the start of the next run; only files matching Studio's backup name pattern are ever
  touched. — cost if wrong: none known; verification doubles the read of a small zip.
- **B5. Reading the library safely.** The backup only reads the library, never writes it. On Windows a rename over a
  file (an atomic save) fails while any handle to that file is open, even one opened with delete sharing, so the backup
  opens each file with read, write and delete sharing (`CreateFileW` through `ctypes`), reads it whole and closes it at
  once; Studio's saves retry for a second, so one that meets the backup's read in that moment still lands. A file
  whose size or modification time changed while it was read is read again (up to 3 tries) and otherwise taken as read,
  with a warning in the manifest; a file that disappeared is left out; a file that can't be read is left out with a
  warning and tried again by the next scheduled run (the manifest's fingerprint is of the files the backup holds); a
  file whose name a zip can't hold (not valid UTF-16) is left out with a warning naming its folder. On Windows the
  backup thread runs in background mode (`THREAD_MODE_BACKGROUND_BEGIN`: low I/O priority). — cost if wrong:
  cross-file consistency is per file, not per library (a `book.json` and a piece saved a moment apart may be from
  either side of a save); the next backup catches up.
- **B6. When.** A first run 60 seconds after Studio starts, then a check every 15 minutes. A run backs up when the
  library changed since the newest backup of this library and that backup is at least 24 hours old, or, for the first
  run after a start, at least 1 hour old. "Changed" compares a fingerprint (a hash of every included file's path, size
  and modification time) with the one in the newest backup's manifest. Unchanged means no new zip, only a "checked"
  time. *Back up now* always makes a backup. — cost if wrong: the author restarts Studio often and wanted one per
  start; the 1-hour floor is one constant.
- **B7. Who runs them.** Only the app's own server (`web.serve`, used by `studio`, `studio app` and `studio web`). Never
  the MCP server, the tests' servers or a second Studio that found the port taken. A lock file
  (`.studio-backup.lock`, holding the computer's name, the process id and the time) keeps two Studios from writing into
  one backup folder at once. It is let go when Studio exits, and stale (replaced) when it is from this computer and its
  process isn't running (the app's server is a daemon thread: closing the window can end a backup before it lets go),
  or after 2 hours. — cost if wrong: none known.
- **B8. Where.** A new setting, `backup_folder`. Empty means the default: `Documents/Studio backups` in the author's home
  folder, or `Studio backups` in the home folder when there is no `Documents`. It must be outside the library, and the
  library outside it; Settings refuses otherwise in a sentence. A missing folder is created when its parent exists; when
  the parent is missing too (a drive that isn't connected), the run fails and says "The backup folder E:\Studio backups
  isn't there. Is the drive connected?". `STUDIO_BACKUPS` in the environment overrides the setting (tests use it).
  When the backup folder is on the same disk as the library (the default usually is), Settings says so in a quiet line:
  "This folder is on the same disk as your library. It protects against mistakes, not against a failing disk: choose
  a folder on another drive, or one your cloud service syncs, for that." Not on Home (it isn't a failure). — cost if
  wrong: the author wanted backups on another disk from day one and missed the line; making it a Home line is one
  condition in `brief()`.
- **B9. On or off.** A new setting, `backups` (on by default). Off stops the automatic runs; *Back up now* and restore
  still work, and Settings says "Automatic backups are off." — cost if wrong: none.
- **B10. Retention.** After every successful backup: keep every backup of this library from the last 24 hours, plus the
  newest one of each of the last 7 days, 4 weeks (Monday to Sunday) and 12 months that have one; move nothing, delete
  the rest of this library's backups. Never delete to make room, never before a new backup succeeded, never a backup of
  another library, never a file that isn't a Studio backup. Not a setting. At most about 24 + 7 + 4 + 12 files. — cost
  if wrong: the author wanted longer history; the numbers are constants, a setting later.
- **B11. Names and the manifest.** `Studio backup 2026-11-13 0300.zip` (local time; `-2`, `-3` when one exists for that
  minute). Inside, `studio-backup.json`: format version 1, Studio's version, the library path, the computer's name
  (`platform.node()`), created (ISO), file count, bytes before compression, fingerprint, the skip rules, warnings, and
  an item list made while backing up —
  series (name), poems (id, title, series), books (id, title, and pieces as file, title, kind) — so the restore list
  needs no scan of the zip. — cost if wrong: none.
- **B12. Other libraries and other computers.** "This library" is the library path on this computer. Backups whose
  manifest names another path are listed as "From another library (path)"; those from the same path on another
  computer (one synced backup folder shared by two computers) as "From another computer (name)". Both can be restored,
  are never pruned, and never count as the newest backup for the "changed" and "due" rules. A zip without a readable
  manifest is listed as "Not readable" with its size, and can only be shown in its folder. — cost if wrong: after moving
  the library or changing computers, old backups stop being pruned until the author deletes them by hand; they stay
  restorable.
- **B13. Honest about failures.** Each run's outcome is kept in memory and in `<cache>/backups/state.json` (the last
  success, the last failure as a plain sentence with its time, the last check). Before writing, free space is checked
  against 1.2 × the newest backup's size (or the uncompressed size when there is none); during writing, "no space"
  removes the partial file. The sentences name the folder and what to do: "The disk with E:\Studio backups is full
  (12 MB free; a backup needs about 9 MB). Free some space or choose another folder." Settings shows the state; Home
  shows one quiet line, while backups are on, only when the last run failed, or when no backup or check succeeded in
  the last 3 days; the second counts only once this Studio's scheduler has made its first check, so a Studio that was
  closed for days doesn't call that a failure. Dates in these sentences are English ("9 Nov 2026") whatever the
  computer's locale. — cost if wrong: the Home line is unwanted; it's one section in `backups.js`.
- **B14. Restoring never overwrites.**
  - *A whole backup* is unpacked into a new folder next to the library, `<library folder name> restored 2026-11-13
    0300`, never into the library. Then Settings offers *Use it as the library* (sets the library setting, after a
    confirmation) and *Show in folder*. This is the new-computer path too. — cost if wrong: an author on a new computer
    wanted it unpacked straight into an empty library; they can rename the folder or point Settings at it.
  - *One poem, book or piece* that still exists can be restored as **a copy next to it** (the default) or can
    **replace** it. A copy: the poem folder `<Poem> (restored 13 Nov 2026)` with the same suffix on the title in its
    `poem.json` and a slug made from that title (so a lookup by slug finds the original, not two poems); a book
    folder `<Book> (restored 13 Nov 2026)` with the suffix on its `book.json` title; a piece as a new piece right after
    the current one, file `<stem> restored 2026-11-13.md`, its `# ` title line (when it has one) suffixed, and an entry
    in `book.json` after the original's with the same kind and form. Replace: the current one goes
    to the trash first, the way a delete does (`Poems/.trash/<Series>/…`, `Books/.trash/…`), then the backup's copy
    takes its place, after a confirmation that says it in plain words: "“Harbour” as it is now goes to the trash
    (Poems/.trash), and the copy from 13 Nov 2026, 03:00 takes its place."
  - *An item that no longer exists* is restored where it was, under its own name (a piece also gets its `book.json`
    entry back, at the end of the body when the original position is gone; a piece of a book that is gone needs the book
    restored). A poem whose series folder is gone (trashed, or renamed outside Studio) brings the series' own files back
    with it — the files directly in the series folder, `_kit/` and `stamps/` — so the series shows again; never other
    poems.
  - The writing log follows the writing, not the version: a copy leaves the backup's `.studio/days.json` out (the log
    would count those days twice); a replace keeps the current one (the days written since the backup stay); a restore
    of a missing item brings the backup's back.
  - A replace also carries over what the backup left out of the current poem: its kit renders, its preview page and its
    `Design renders/`, so the Art tab keeps its images (marked out of date by the Art tab when the text differs, as it
    already does) and the slug stays fixed. They move from the trashed version into the restored one.
  - Files are unpacked into a hidden temporary folder next to the destination, then renamed into place; a failure
    removes the temporary folder, and a failed replace moves the current one back out of the trash.
  - Every path in a zip is checked: no absolute paths, no `..`, no drive letters, nothing outside the item; no links.
  - The poem or piece editor isn't open during a restore (restore lives in Settings); a book piece open in another
    window meets the existing stale-save check.
- **B15. The restore interface.** Settings → Backups lists the backups, newest first: date and time, size, number of
  files, and "From another library" where it applies. Each row has a *Restore…* button and a right-click menu: *Choose
  what to restore…*, *Restore the whole backup…*, *Show in folder*. *Choose what to restore…* opens a dialog with the
  backup's poems (by series) and books (with their pieces) from the manifest, a filter field, and for the selected item
  whether it exists now and its buttons (*Restore a copy*, *Replace…*, or *Restore*); its footer also has *Restore the
  whole backup…* next to *Cancel*, the new-computer path, with the same confirmation as the menu's. — cost if wrong:
  none.
- **B16. One at a time.** One backup or restore runs at a time (a module lock). Settings shows progress while one runs
  ("Backing up… 120 of 400 files"); a restore asked for during a backup waits up to 30 seconds for it, then says "A
  backup is running. Try again in a minute." — cost if wrong: none.

### Settings → Backups (what the author sees)

```
Backups                        Studio keeps copies of your poems, books and styles in a folder you choose:
                               every backup from the last day, then one a day for a week, one a week for a month
                               and one a month for a year.

                               [✓] Back up automatically (when Studio starts, then once a day)
                               Backup folder  [C:\Users\…\Documents\Studio backups      ] [Choose…]
                               Last backup 13 Nov 2026, 03:00 · 2.1 MB · checked 14:20, nothing changed since
                               [Back up now]  [Show in folder]
                               Not backed up: 3 other folders in the library (1.2 GB).

                               13 Nov 2026, 03:00    2.1 MB   412 files      Restore…
                               12 Nov 2026, 22:10    2.0 MB   405 files      Restore…
                               …
```

A failure replaces the "Last backup" line with the sentence in the error colour, keeps the date of the last good one,
and adds *Try again*.

### `studio/backup.py`

```python
FORMAT = 1
NAME = re.compile(r"Studio backup (\d{4}-\d{2}-\d{2}) (\d{4})(?:-(\d+))?\.zip")
class BackupError(StoreError)                 # 400 with a plain sentence; 409 when one is running
def folder() -> Path                          # STUDIO_BACKUPS, the setting, or the default
def check_folder(path) -> str | None          # None, or the sentence why it can't be used (inside the library, …)
def included(library) -> Iterator[(Path, str)]  # (file, path in the zip), with the skip rules
def fingerprint(library) -> str
def outside(library) -> dict                  # {"folders": [names], "files": n, "bytes": n}: what isn't backed up
def run(reason="manual"|"start"|"daily", progress=None) -> dict   # makes a backup (or says "unchanged"); prunes
def due(now, at_start) -> bool
def list_backups() -> list[dict]              # {"name", "when", "bytes", "files", "library", "same_library", "readable"}
def manifest(name) -> dict
def prune(now=None) -> list[str]              # names deleted
def restore_item(name, kind, ref, mode) -> dict   # kind: poem|book|piece; mode: copy|replace|restore (a missing one)
def restore_all(name) -> Path
def status() -> dict                          # settings, folder (env_folder: STUDIO_BACKUPS sets it), state (last ok,
                                              # last error, last check), running, progress
def start_scheduler()                         # the 60 s / 15 min thread; once per process
```

### Endpoints (`studio/routes_library.py`)

| | |
|---|---|
| `GET /api/backups` | `status()` plus `list_backups()` and `outside()` |
| `POST /api/backups/run` | back up now (answers when started; progress through `GET /api/backups`) |
| `GET /api/backups/items?name=` | the manifest's items, each with `exists` now |
| `POST /api/backups/restore` `{name, kind, ref, mode}` | one item; `{name, all: true}` for the whole backup |
| `POST /api/backups/reveal` `{name?, path?}` | show the folder, one backup, or a folder `restore_all` made |
| `GET /api/backups/brief` | `{"problem"}`: the Home line |

`backups` and `backup_folder` are saved through the existing `POST /api/settings`; `config.save` validates them (a bool;
a folder outside the library, or empty). *Use it as the library* after a whole restore is the same `POST
/api/settings {library}` the Library field uses.

---

## 2. The writing log

### Approaches considered

1. **Read the per-book `days.json` and a new per-poem `days.json`, sum on request (chosen).** Same shape for both,
   recorded at save time, travels with the poem or book (rename, trash, restore).
2. **Derive poem words from drafts.** History for free, but a poem's first draft can't be told apart: imported poems can
   share one draft date (each has one draft, stamped on the day of the import), so the log would report the whole import
   as one day's writing.
3. **One library-wide log file.** One place to read, but it breaks when a poem is renamed or moved, and it is a
   hot spot every save writes to.

### Rulings

- **W1. Books** keep counting as they do: `Books/<Book>/.studio/days.json`, `{"2026-11-13": 640}`, the words a save
  added (gains only; deleting doesn't subtract). — cost if wrong: none (existing).
- **W2. Poems count from now on** in `Poems/<Series>/<Poem>/.studio/days.json`, the same shape, written by
  `Store.save_text` (the only place Studio saves a poem's text): the words the save added, gains only, title excluded.
  A word is a run of non-space characters with a letter or digit in it. No derivation from drafts. A failure to write
  the log never fails the save. — cost if wrong: no poem history before this version; a one-off derivation can be added
  later.
  "Added" means the new count minus the old one, when positive, exactly as books count, so a number in the log means the
  same thing for a poem and a chapter. A day of reworking lines without lengthening the poem logs little. — cost if
  wrong: revision days look quiet; counting the words a diff adds is one function (`poem_gain`) for poems, and books
  would need the same change in `books.py` to stay comparable.
- **W3. Days are local dates; weeks run Monday to Sunday** (the week starts on Monday, as in most of Europe; en-GB
  dates). — cost if wrong: one constant.
- **W4. Goals are per book**, as they exist (`goals.daily`). For each book with a goal: "Daily goal 500 words · met on 9
  of the last 30 days", where days before the book's first recorded writing day don't count ("met on 4 of 6 days since
  8 Nov"). A day meets the goal when that book's words that day reach it. No goal for poems. — cost if wrong: one
  sentence.
- **W5. Calm and editorial.** Numbers in tabular figures; thin neutral bars; no colours for good or bad days, no
  streaks, no "best day", no badges, no celebration. A met goal shows as plain muted text, never a mark in colour. —
  cost if wrong: none.
- **W6. Where.** A quiet section on Home, *Writing*, after the series: today and this week in words, the last 14 days as
  thin bars, and *Writing log →*. The section doesn't show until there is at least one recorded day. The page
  `#/writing` (title "Writing log") holds the rest. — cost if wrong: the author wanted it in the top bar; one link.

### The page

```
Studio
Writing log                                                     [ Days | Weeks | Months ]

Today 320 words · this week 1,240 · this month 8,310 · this year 41,200

                 Poems    The Long Year    Field Notes    Total
Thu 13 Nov         120         540              —           660   ▆▆▆▆▆▆▆▆
Wed 12 Nov           —         610 goal met     —           610   ▆▆▆▆▆▆▆
…                                                                  (30 days; 12 weeks; 12 months)

Books
The Long Year    Daily goal 500 words · met on 9 of the last 30 days · 12,400 words this month
Field Notes      No daily goal · 3,100 words this month
Poems            1,020 words this month, in 7 poems
```

Days with nothing written show as a dash, not as zero. Weeks and months show sums. The log reads the books and poems
that exist now: a trashed book's or poem's days leave with it (ruling — cost if wrong: past totals drop when work is
trashed; keeping them would need a library-wide log, approach 3). It leaves out the examples (a series or book marked
`"example": true`): adding them saves their poems and pieces as any save does, and that isn't writing.

### `studio/writing_log.py`

```python
def words(text: str) -> int
def add(folder: Path, n: int, when: datetime | None = None)     # adds to <folder>/.studio/days.json; atomic
def poem_gain(old_lines, new_lines) -> int
def gather(store, books) -> dict
#  {"today": "2026-11-13", "week_start": "2026-11-10",
#   "days": {"2026-11-13": {"poems": {"<pid>": 120}, "books": {"<book id>": 540}}},
#   "books": [{"id", "title", "goal", "first_day"}], "poems": {"<pid>": {"title", "series"}}}
```

`GET /api/writing` returns `gather()`. The browser sums weeks and months and works out goal lines from it (one rule, in
`writing.js`).

---

## 3. One search across the library

### Approaches considered

1. **An in-memory index, checked against file times on use (chosen).** Each item keeps its text folded for matching
   and the (modification time, size) of its files. A search scans it (substring search in C, fast on millions of
   words) and a check re-reads only what changed. Nothing written to disk, nothing to go stale on disk.
2. **A persistent index in the cache (SQLite FTS).** Fast on any size, but a second copy of the library that can
   disagree with the files, needs migrations, and word-based matching misses "light" in "lighthouse".
3. **Walk and read the files on every search.** Always fresh and simplest, but reads the whole library per keystroke.

### Rulings

- **S1. What is searched.** Poems: title, text, writing notes (`writing-notes.md`), posting notes (`NOTES.md`). Series:
  name and tagline. Designs: their names. Books: title and subtitle. Pieces: title, text (captions included), and the
  text of notes (labelled "In a note"). Research items (part 3): through `research.Research(library).search(q, every=True)`
  when `studio/research.py` exists, so it works as soon as part 3 merges. Not searched: drafts, briefs, kits,
  bibliographies, trash. — cost if wrong: a line cut from a poem can't be found (drafts); adding drafts is a field.
- **S2. Matching.** Case and accents don't matter ("Café" finds "cafe"). Every word of the query must appear somewhere
  in the item; a word matches inside longer words ("light" finds "lighthouse"); text in quotes must appear as typed
  (folded). Ranking inside a group: the title is the query, the title starts with it, the title contains every word,
  then the text, then notes; ties go to the item changed most recently. — cost if wrong: one function.
- **S3. Freshness, honestly.** The index is built on first use (opening the search starts it) and kept in memory for
  the running Studio. Each search answers from the index; when the last check of the files is older than 3 seconds,
  a check starts in the background (a walk comparing modification times and sizes, re-reading only changed files), and
  the search waits up to 150 ms for it, so a small library is always answered fresh. The reply says when the files were
  last checked and whether a check is still running; the search panel shows that in its footer ("Checked just now",
  "Checking for changes…") and asks again when the check ends, so results settle by themselves. While the first build
  runs, the panel says "Reading the library… 1,200 of 5,000". — cost if wrong: a huge library waits a few seconds for
  its first search of a session; a persistent cache would fix that inside `search.py`.
- **S4. Speed targets.** On this machine, with a generated library of 5,000 poems and 3 books of 100 pieces
  (1.5 million words): a search answers in under 150 ms from a warm index, and a check finishes in under 1 second. A
  library of a few dozen poems and a book: under 20 ms each. A test asserts the warm-search target (with a margin for
  slow CI).
- **S5. Where it opens.** Ctrl+K anywhere in Studio outside a book's writing window opens the library search; a quiet
  *Search* button in the top bar opens it too. Inside a book, Ctrl+K stays the book's command palette, which gets one
  more action, *Search the library for "…"*, carrying what was typed (one line in `book-tools.js`); its label holds the
  query, so the palette's own filtering always keeps it. — cost if wrong: the author wanted Ctrl+K to search the library
  in the book too; the palette action is two keystrokes away (type, Enter).
- **S6. The panel.** Centred like the book palette (its own classes, the same look): a field, results grouped (Poems,
  Pieces, Books, Series, Designs, Research), each row a title, where it is (series; book; poem for a design) and a
  snippet with the matches marked; up to 8 per group with a *Show all 23* row that expands the group in place. ↑/↓ and
  Tab move, Enter opens, Esc closes, Ctrl+K closes; hover and click work as in the palette. The query and the panel's
  results stay while Studio is open, so Ctrl+K, Enter, Ctrl+K returns to the list. Footer: counts ("312 poems, 2 books,
  41 designs") and freshness.
- **S7. Jumping to the match.**
  - Poem text, title, writing notes: the poem's Write tab opens with the match selected in its field and scrolled into
    view (the field is focused, so the selection shows).
  - Posting notes: the Art tab opens with the match selected in its notes field.
  - A design: the Design tab opens on that design (through the editor's remembered design for the poem).
  - A series or a book: its page.
  - A piece: the piece opens in the writing window and the book's Find panel opens with the query, every match lit;
    the first match in that piece is selected and scrolled to when the window's public `BookTools` API allows it.
  - A research item: where part 3's search says it lives (its board).
  The jump waits for the page to finish drawing (up to 3 s), then selects; if the text changed so the match isn't there
  any more, the page simply opens.
- **S8. Snippets.** About 40 characters either side of the first match in the best field, cut at word boundaries, with
  every query word marked; the server sends text and ranges, the browser escapes and marks. — cost if wrong: none.

### `studio/search.py`

```python
def fold(s) -> str                           # lower case, accents removed, same length as s where possible (for marks)
def parse_query(q) -> list[str]              # words and quoted phrases, folded
class Index:
    def __init__(self, library: Path)
    def check(self) -> None                  # walk; re-read changed files; drop gone items
    def search(self, q, kinds=None, limit=8) -> dict
    def state(self) -> dict                  # {"checked", "checking", "building", "counts"}
def index() -> Index                         # the current library's (a new one when the library setting changes)
SOURCES = [...]                              # poems, series, designs, books, pieces; research when present
```

`GET /api/search?q=&kind=&limit=` returns `{"q", "groups": [{"kind", "label", "total", "items": [{"title", "where",
"href", "field", "snippet": {"text", "marks": [[a, b]]}, "jump": {...}}]}], "checked", "checking", "building",
"counts"}`. `POST /api/search/warm` starts the build or a check (the panel calls it when it opens).

---

## Front end

- `static/backups.js` paints Settings → Backups (through a small hook in `showSettings`) and the Home line.
- `static/writing.js` registers the Home section (through `window.homeSections`) and draws `#/writing`.
- `static/search.js` is the search panel, its keys, the top bar button and the jumps; it sets `window.LibrarySearch =
  {open(q), search(q)}`.
- `static/library.css` styles all three, with the tokens `app.css` defines for light and dark.

## Small edits to shared files (all additive)

| File | Change |
|---|---|
| `config.py` | `backups: True`, `backup_folder: ""` in `DEFAULTS`; their validation in `save`; `BACKUPS` resolved in `refresh` (with `STUDIO_BACKUPS`) |
| `web.py` | import `routes_library`; start the backup scheduler in `serve()` |
| `store.py` | `save_text` records the words it added (`writing_log`) |
| `index.html` | `library.css`, the three scripts, the *Search* button in the top bar |
| `app.js` | the `#/writing` route; a `window.settingsSections` hook in `showSettings`; one line in Info's keys |
| `book-tools.js` | one action in the palette: *Search the library for "…"* |
| `tests/support.py` | `STUDIO_BACKUPS` pointed at the temp folder |
| `README.md`, `docs/DESIGN.md` | the three features; `.studio/days.json` in poem folders |

No version change and no release notes.

## Testing

- `tests/test_backup.py`: skip rules; fingerprint; a backup's zip and manifest; atomic finalisation (no `.zip` without
  a verified one; `.partial` cleaned); a file replaced while the backup reads it (Windows sharing); changed-while-read
  retry; retention on a synthetic calendar; never pruning another library's or a foreign file; the due rule; failures
  (folder missing, parent missing, disk full simulated) recorded as sentences; restore copy/replace/missing for poem,
  book and piece; path traversal refused; restore all into a new folder; the lock.
- `tests/test_writing_log.py`: words; gains only; `save_text` records; gather across poems and books.
- `tests/test_search.py`: folding and marks; AND and phrases; ranking; each source; freshness (a changed file is seen
  after a check; a deleted one goes); the 5,000-poem timing; research source absent and present (a stub module).
- `tests/test_library_web.py`: the endpoints through `temp_studio()` (Host, Origin, JSON checks come from the tables).
- Screenshots of Settings → Backups, the restore dialog, the writing log page, the Home section and the search panel,
  light and dark, measured for alignment.
- The full suite stays green (380 at v1.2.0) and `tests/e2e_mcp.py` passes.

## Left to the builder

- Exact CSS within the existing tokens; the bar geometry of the log; wording beyond the sentences above, in the same
  voice.
- How the piece jump selects its first match through `BookTools` (S7), falling back to the Find panel alone.
- Thread and timer plumbing of the scheduler, as long as nothing blocks a request.
