# Library tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatic backups with restore, a writing log, and one search across the library, in Studio.

**Architecture:** Three new Python modules (`backup.py`, `writing_log.py`, `search.py`) behind one new route table file
(`routes_library.py`), and three new classic scripts (`backups.js`, `writing.js`, `search.js`) with one stylesheet
(`library.css`). Shared files get small additive hooks only. Backups are verified zips renamed into place; the writing
log reads per-book and per-poem `.studio/days.json`; search is an in-memory index checked against file times.

**Tech Stack:** Python 3.11+ standard library (zipfile, threading, ctypes on Windows), `unittest`; plain JavaScript (no
build step); node for the JS helper tests when installed.

**Spec:** `docs/superpowers/specs/2026-11-13-library-tools-design.md` (read it first; rulings are referenced as B1–B16,
W1–W6, S1–S8).

## Global Constraints

- Work only in `<worktree>` (`<repo>\.worktrees\library-tools`, branch `library-tools`).
- Never touch the author's real library and their Studio config (`%APPDATA%\Studio\config.json`), or any real
  backup folder. Tests and scratch servers use temp `STUDIO_CONFIG`, `STUDIO_ART`, `STUDIO_CACHE` and `STUDIO_BACKUPS`.
  Scratch servers only on ports 4748–4766, after checking the port is free; stop every process you start.
- Python: `<repo>\.venv\Scripts\python.exe` (no venv in the worktree). Run tests from the worktree root:
  `<repo>\.venv\Scripts\python.exe -m unittest discover tests` (380 OK before this work). One module:
  `... -m unittest tests.test_backup -v`.
- No new dependencies. New modules use the standard library (plus Studio's own modules).
- Files are the database: never rewrite a user's file on read; never overwrite a file Studio can't read; atomic writes
  through `store.write_text` (text) or `books._write_bytes` pattern (bytes); deletes go to `.trash`.
- Every endpoint through `studio/routes.py` tables (`@routes.get`, `@routes.post`), in `studio/routes_library.py`.
  Handlers reply with `h._send(code, body)` and raise `StoreError` (or a subclass with `code`) for errors.
- Every view escapes user text with `esc()`; marks from the server are applied to escaped text by index.
- Interface copy: plain, sentence case, no badges, streaks, flourishes, exclamation marks; right-click menus on lists
  (`StudioMenu.open(event, items)`); confirmations through `openDialog` or `confirm` in plain words.
- Nothing personal in the repo: no real names, poem or book titles, personal paths or emails; invented names in tests
  and docs.
- Commits: author is the repo-local `TheAnarchoX <theanarchox@proton.me>` (already configured); plain `git commit`
  (signing is configured and works; never pass flags that skip signing or hooks; if signing fails, stop and report);
  every message ends with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No push, tag,
  merge or version change; no release notes.
- Shared files are edited only where this plan says, additively (siblings edit them tonight): `config.py`, `web.py`,
  `store.py`, `index.html`, `app.js`, `book-tools.js`, `tests/support.py`, `README.md`, `docs/DESIGN.md`.
  Never edit `book-text.js`, `book-editor.js`, `manuscript.py`, `book-rail.js`.
- Front end: classic scripts sharing globals (`$`, `$$`, `esc`, `api`, `toast`, `pref`, `state`, `plural`, `day`,
  `when`, `openDialog`, `StudioMenu`, `route`); colours only through `app.css` tokens (`--paper`, `--paper-dim`, `--fog`,
  `--line-soft`, `--panel`, `--panel-2`, `--night`, `--danger`, `--ok`, …) so light and dark both work.

## Review Focus

1. **Names with accents, dashes and spaces** (a library at `…/Gedichten – één`, a poem folder `Café, ’s nachts`): zip
   member names, restore paths and search marks must round-trip exactly. Tests in Tasks 3, 5 and 2.
2. **File times zip can't store** (before 1980 or far future): the backup must still be made (dates clamped). Test in
   Task 3.
3. **A file the backup can't read** (locked exclusively, permission denied): the backup completes, the manifest and
   Settings say which file was left out. Test in Task 3.
4. **Search queries that are only punctuation, unbalanced quotes, or very long**: no error, empty or literal results.
   Test in Task 2.
5. **The library setting changes while Studio runs**: search answers from the new library; backups fingerprint and prune
   the new library's backups only. Tests in Tasks 2 and 4.

---

### Task 1: The writing log's store and endpoint

**Files:**
- Create: `studio/writing_log.py`, `studio/routes_library.py`
- Modify: `studio/store.py` (`save_text`, and one import at the bottom), `studio/web.py` (the last import line)
- Test: `tests/test_writing_log.py`

**Interfaces:**
- Produces:
  - `writing_log.DAYS_FILE = Path(".studio") / "days.json"`
  - `writing_log.words(text: str) -> int` — whitespace-separated tokens containing a letter or digit (`[^\W_]`).
  - `writing_log.read_days(folder: Path) -> dict[str, int]` — `{iso date: int ≥ 0}` from `folder/.studio/days.json`;
    `{}` when missing or unreadable; drops keys that aren't `YYYY-MM-DD` and values that aren't non-negative ints
    (bools excluded).
  - `writing_log.add(folder: Path, n: int, when: datetime | None = None) -> None` — adds `n` (if `n > 0`) to the local
    date of `when` (default now); atomic write (`store.write_text`, JSON `indent=2, sort_keys=True` + newline, same
    shape as `books._add_words`); a module lock; when the file exists but can't be parsed as a JSON object, writes
    nothing.
  - `writing_log.poem_gain(old_lines: list[str], new_lines: list[str]) -> int` — `max(0, words(new) - words(old))`
    over the lines joined with `\n`.
  - `writing_log.gather(store: Store, books_root: Path, today: date | None = None) -> dict` — exactly:
    `{"today": iso, "week_start": iso (Monday of today's week), "days": {iso: {"poems": {pid: n}, "books": {book_id: n}}},
    "books": [{"id", "title", "goal": int, "first_day": iso | None}], "poems": {pid: {"title", "series"}}}`.
    `books` lists every book folder (`Books(books_root).dirs()`), title from `book.json` (folder name when
    unreadable), `goal` = `goals.daily` when a non-negative int, else 0. `poems` lists only poems with a recorded day.
    `days` holds only non-zero entries.
  - `GET /api/writing` → `gather(h.store, h.store.root.parent / "Books")`.

- [ ] **Step 1: Write the failing tests** in `tests/test_writing_log.py` (temp library helpers: copy the pattern from
  `tests/test_home.py` / `tests/test_store.py`):

```python
def test_words(self):
    self.assertEqual(writing_log.words("Two words"), 2)
    self.assertEqual(writing_log.words("— … !"), 0)
    self.assertEqual(writing_log.words("l'eau 12 ok\nnext"), 4)

def test_add_accumulates_and_ignores_non_gains(self):
    t = datetime(2026, 11, 13, 9, 0)
    writing_log.add(self.poem, 5, t); writing_log.add(self.poem, 7, t)
    writing_log.add(self.poem, 0, t); writing_log.add(self.poem, -3, t)
    self.assertEqual(writing_log.read_days(self.poem), {"2026-11-13": 12})

def test_add_never_overwrites_an_unreadable_log(self):
    f = self.poem / ".studio" / "days.json"; f.parent.mkdir(); f.write_text("{bad", encoding="utf-8")
    writing_log.add(self.poem, 5)
    self.assertEqual(f.read_text(encoding="utf-8"), "{bad")

def test_save_text_records_the_words_a_save_adds(self):
    pid = <create series "Sea" and poem "Harbour" through Store>
    store.save_text(pid, "Harbour", "one two three")       # 3
    store.save_text(pid, "Harbour", "one two")             # a loss: nothing
    store.save_text(pid, "A longer title", "one two three four five")   # +3 (title words never count)
    self.assertEqual(sum(writing_log.read_days(folder).values()), 6)

def test_gather(self):
    # poem with {"2026-11-12": 40}, book "Field Notes" with goals {"daily": 500} and days {"2026-11-10": 600,
    # "2026-11-13": 120, "bad": 3, "2026-11-11": -4}, a second book without goals and no days
    g = writing_log.gather(store, books_root, today=date(2026, 11, 13))
    self.assertEqual(g["today"], "2026-11-13"); self.assertEqual(g["week_start"], "2026-11-09")
    self.assertEqual(g["days"]["2026-11-10"], {"poems": {}, "books": {"Field Notes": 600}})
    self.assertEqual(g["days"]["2026-11-12"]["poems"], {"Sea/Harbour": 40})
    self.assertNotIn("2026-11-11", g["days"])
    self.assertEqual([b["goal"] for b in g["books"]], [500, 0])
    self.assertEqual(g["books"][0]["first_day"], "2026-11-10")
    self.assertEqual(g["poems"]["Sea/Harbour"], {"title": "Harbour", "series": "Sea"})

def test_endpoint(self):
    with temp_studio() as t:
        code, body = t.get("/api/writing")
        self.assertEqual(code, 200)
        self.assertEqual(set(body), {"today", "week_start", "days", "books", "poems"})
```

  (`2026-11-13` is a Friday; its week starts Monday `2026-11-09`.)

- [ ] **Step 2: Run them to see them fail**
  Run: `...python.exe -m unittest tests.test_writing_log -v` — Expected: errors, `writing_log` missing.

- [ ] **Step 3: Implement `studio/writing_log.py`, `studio/routes_library.py` (module docstring; `@routes.get
  ("/api/writing")`), the `save_text` hook and the imports.** In `Store.save_text`, after `self.update(folder, change)`:
  `gained = writing_log.poem_gain(old_lines, lines)`, and when `gained`, `writing_log.add(folder, gained)` inside
  `try/except OSError: pass` (a log failure never fails the save). Add `writing_log` to the bottom import of
  `store.py` (next to `styles`); `writing_log.add` imports `write_text` from `.store` inside the function. In `web.py`
  add `routes_library` to the last import line.

- [ ] **Step 4: Run the module, then the whole suite**
  Expected: the new tests pass; full suite OK (380 + new).

- [ ] **Step 5: Commit** `Writing log: count poem words on save, and /api/writing`.

---

### Task 2: Search: the index and its endpoints

**Files:**
- Create: `studio/search.py`
- Modify: `studio/routes_library.py`
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: `Store` (series_dirs, poem_dirs, pid), `Books(root).dirs()`, `books.valid_file`, `books.BOOK_FILE`,
  `manuscript.parse(md, form)`, `manuscript.title_of(md)`, `config.ART`.
- Produces:
  - `search.fold_map(s: str) -> tuple[str, list[int]]` — NFKD, combining marks dropped, `casefold()` per character;
    `back[i]` is the index in `s` of folded character `i`. `search.fold(s) -> str` is `fold_map(s)[0]`.
  - `search.parse_query(q: str) -> list[str]` — quoted phrases (closing quote optional) keep their inner spaces
    (collapsed); the rest split on whitespace; each folded; empty and duplicate terms dropped; at most 12 terms; terms
    longer than 200 characters cut to 200.
  - `search.KINDS = [("poem", "Poems"), ("piece", "Pieces"), ("book", "Books"), ("series", "Series"),
    ("design", "Designs"), ("research", "Research")]` (group order and labels).
  - `search.FRESH = 3.0` (seconds), `search.WAIT = 0.15`.
  - `class Index(library: Path)` with `check() -> None` (synchronous walk), `ensure(wait: float = WAIT) -> None`
    (starts a background check when none runs and the last one ended more than `FRESH` seconds ago or never ran, then
    waits up to `wait`), `search(q: str, kinds: list[str] | None = None, limit: int = 8) -> dict`, `state() -> dict`.
  - `search.index() -> Index` — one per `config.ART`; a new one when `config.ART` changes.
  - Reply of `search()` and `GET /api/search?q=&kind=&limit=`:
    `{"q", "groups": [{"kind", "label", "total", "items": [Result]}], "counts": {"poems", "series", "designs", "books",
    "pieces"}, "checked": iso | None, "checking": bool, "building": {"done", "total"} | None, "errors": [str]}`.
    `Result = {"kind", "title", "title_marks": [[a, b]], "where", "href", "field", "field_label",
    "snippet": {"text", "marks": [[a, b]]} | None, "jump": {...}}`.
    `field` is one of `title, text, notes, posting, name, tagline, subtitle, note`; `field_label` is the words shown
    for non-text fields ("Writing notes", "Posting notes", "In a note", "Tagline", "Subtitle"; "" for title and text).
  - `jump` per kind: poem `{"type": "poem", "id", "field": "title"|"text"|"notes"|"posting", "start", "end",
    "match"}` (offsets in the field's text as the editor shows it: `"\n".join(lines)`, the notes files as read with
    universal newlines; `match` is the original substring); design `{"type": "design", "id", "slug"}`; piece
    `{"type": "piece", "book", "file", "match"}`; series/book/research `{"type": kind}`.
  - `href` per kind: poem `#/poem/<pid>/write` (field posting: `/art`), design `#/poem/<pid>/design`, series
    `#/series/<name>`, book `#/book/<id>`, piece `#/book/<id>/write/<file>`, research `#/research` (shared board) or
    `#/book/<id>/board`; components through `urllib.parse.quote(x, safe="")`.
  - `POST /api/search/warm` → `index().ensure(wait=0)`, replies `index().state()` (`{"checked", "checking",
    "building", "counts"}`).

What each source indexes (S1): poems (title; text = lines joined with `\n`; `writing-notes.md`; `NOTES.md`; files
`poem.json`, both notes files), designs (`designs/*.json` name or stem; not `.trash`), series (folder name; tagline
from `series.json`), books (title, subtitle from `book.json`), pieces (book.json `contents` entries with
`valid_file`; title = `title_of` or the kind's name; body text and note text by walking `manuscript.parse` output:
text nodes inside `note` nodes go to `note`, all other text to `text`, blocks separated by `\n`, the `title` block
excluded). An item is re-read only when one of its files' `(st_mtime_ns, st_size)` changed. A file that can't be read
(unreadable JSON, not UTF-8) leaves its item out without failing the check. Trash folders and dot-folders are never
walked. Research (S1): when `importlib.util.find_spec("studio.research")` finds part 3's module, `search()` calls
`research.Research(library).search(q, every=True)` (items `{board, board_title, id, type, title, snippet}`) and turns
them into results (title = title or the snippet's first 60 characters; where = board_title; marks computed on the
snippet with `fold_map`); any exception becomes a sentence in `errors` and no research group.

Matching and ranking (S2): an item matches when every term occurs (as a substring of the folded text) in at least one
of its fields. Score: 600 title equals the whole query; 500 title starts with it; 400 every term in the title; else 300
when the best field is text/name/tagline/subtitle, 200 for notes/posting/note; +50 when the whole query (terms joined
by a space) occurs in that field. The best field is the one containing the most distinct terms (ties: title, text,
name, tagline, subtitle, notes, posting, note). Sort by score, then newest file time, then title. Snippet (S8): from the
best non-title field that contains a term, around the first occurrence of the first term found, about 40 characters
each side, widened to word boundaries, `…` where cut, newlines shown as spaces (same length), every term occurrence in
it marked, overlapping marks merged. `title_marks` mark every term in the title.

Freshness (S3): `check()` builds a new items dict, reusing unchanged items, then swaps it in one assignment;
`searches read the current dict`. During the first build `search()` returns no groups and `building` progress
(`done` counts items read, `total` the poem folders and piece files found by the directory walk). The check runs on a
daemon thread; `ensure()` never starts a second one.

- [ ] **Step 1: Write the failing tests** (`tests/test_search.py`, temp library built in `setUp`, `config` pointed at
  it like `tests/test_home.py` does):

```python
def test_fold_and_marks(self):
    self.assertEqual(search.fold("Café ÉLAN"), "cafe elan")
    folded, back = search.fold_map("Straße")
    self.assertEqual(folded, "strasse"); self.assertEqual(back[4:6], [4, 4])

def test_parse_query(self):
    self.assertEqual(search.parse_query('light "the  sea"  '), ["light", "the sea"])
    self.assertEqual(search.parse_query('"open quote'), ["open quote"])
    self.assertEqual(search.parse_query('" ( * '), ["( *"])         # an unclosed quote runs to the end
    self.assertEqual(search.parse_query('( * '), ["(", "*"])
    self.assertEqual(len(search.parse_query("a" * 500)[0]), 200)

def test_every_word_anywhere_and_inside_words(self):
    # poem "Lighthouse" with notes "a house by the sea"; poem "Light" without "house"
    r = self.idx.search("light house")
    self.assertEqual([i["title"] for i in group(r, "poem")], ["Lighthouse"])

def test_ranking(self):
    # titles "Harbour", "Harbour lights", "The harbour", text-only "harbour", notes-only "harbour"
    self.assertEqual([i["title"] for i in group(self.idx.search("harbour"), "poem")],
                     ["Harbour", "Harbour lights", "The harbour", <text-only>, <notes-only>])

def test_sources_and_jumps(self):
    # series "Sea" tagline "salt and stone"; design name "Night version"; book "Field Notes" piece with a note
    # containing "ferry"; Poems/.trash poem with "ferry"; designs/.trash/x.json named "ferry"
    r = self.idx.search("ferry")
    piece = group(r, "piece")[0]
    self.assertEqual(piece["field"], "note"); self.assertEqual(piece["field_label"], "In a note")
    self.assertEqual(piece["jump"], {"type": "piece", "book": "Field Notes", "file": <file>, "match": "ferry"})
    self.assertEqual(group(r, "poem"), []); self.assertEqual(group(r, "design"), [])
    self.assertEqual(group(self.idx.search("salt"), "series")[0]["href"], "#/series/Sea")
    self.assertEqual(group(self.idx.search("night version"), "design")[0]["jump"]["slug"], <slug>)

def test_accented_text_marks_point_into_the_original(self):
    # poem text "Het café ’s nachts"
    it = group(self.idx.search("cafe"), "poem")[0]
    a, b = it["snippet"]["marks"][0]
    self.assertEqual(it["snippet"]["text"][a:b], "café")
    self.assertEqual(it["jump"]["match"], "café")

def test_odd_queries_never_fail(self):
    for q in ['"', "(a", "*", "a" * 500, "   "]:
        self.assertIsInstance(self.idx.search(q)["groups"], list)

def test_unreadable_files_are_left_out(self):
    # one poem.json "{bad", one piece file in cp1252 bytes
    self.idx.check()      # no exception
    self.assertTrue(self.idx.search("harbour")["groups"])

def test_freshness(self):
    self.idx.check()
    notes = self.poem / "writing-notes.md"; notes.write_text("gannet", encoding="utf-8")
    os.utime(notes, ns=(time.time_ns() + 5_000_000_000,) * 2)
    self.idx.check()
    self.assertTrue(group(self.idx.search("gannet"), "poem"))
    shutil.rmtree(self.poem); self.idx.check()
    self.assertFalse(group(self.idx.search("gannet"), "poem"))

def test_index_follows_the_library_setting(self):
    a = search.index(); <point config at a second temp library and config.refresh()>
    self.assertIsNot(search.index(), a); self.assertEqual(search.index().library, <second library>)

def test_research_source(self):
    fake = types.ModuleType("studio.research")
    fake.Research = lambda lib: SimpleNamespace(search=lambda q, every=False: [
        {"board": None, "board_title": "Shared board", "id": "n1", "type": "note", "title": "", "snippet": "a ferry at dawn"}])
    with mock.patch.dict(sys.modules, {"studio.research": fake}), mock.patch("importlib.util.find_spec", return_value=object()):
        r = self.idx.search("ferry")
    self.assertEqual(group(r, "research")[0]["href"], "#/research")
    # and a Research whose search raises: no research group, one sentence in r["errors"]

def test_endpoints(self):
    with temp_studio() as t:
        self.assertEqual(t.post("/api/search/warm")[0], 200)
        code, body = t.get("/api/search?q=harbour")
        self.assertEqual(code, 200); self.assertIn("groups", body); self.assertIn("checked", body)
```

  And a speed class, skipped when `STUDIO_SKIP_SLOW=1`: generate 5,000 poem folders (12 lines of 6 words each, files
  written directly) and 3 books of 100 pieces of about 3,000 words of plain paragraphs; `check()` once (print the
  time); then assert the median of 10 `search()` calls for different two-word queries is under 0.15 s, and a second
  `check()` with nothing changed is under 2.0 s (the spec's 1 s target with a margin for slow machines; print both).

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement `studio/search.py` and the two routes** (`GET /api/search` calls `index().ensure()` then
  `index().search(q, kinds=[kind] if kind else None, limit=int(limit or 8), clamped 1..200)`).
- [ ] **Step 4: Run the module (with and without `STUDIO_SKIP_SLOW=1`), then the whole suite.** Record the measured
  times in the commit message body.
- [ ] **Step 5: Commit** `Search: one index across poems, series, designs, books and pieces`.

---

### Task 3: Backups: settings and the backup writer

**Files:**
- Create: `studio/backup.py`
- Modify: `studio/config.py` (DEFAULTS, save validation, refresh, docstring), `studio/routes_library.py`,
  `tests/support.py` (`STUDIO_BACKUPS`)
- Test: `tests/test_backup.py`

**Interfaces:**
- Produces in `config`: `DEFAULTS["backups"] = True`, `DEFAULTS["backup_folder"] = ""`; `save()` validates `backups`
  exactly like `update_check`, and `backup_folder` as `""` or an expanded path that is neither inside the library being
  saved nor around it (`ValueError("Choose a backup folder outside your library.")` /
  `ValueError("Your library is inside that folder. Choose a folder outside it.")`); `refresh()` sets `BACKUPS_ON:
  bool`, `BACKUPS: Path` (`STUDIO_BACKUPS`, else the setting, else `default_backups()`), and
  `config.default_backups() -> Path` (`~/Documents/Studio backups` when `~/Documents` is a folder, else
  `~/Studio backups`; when that is inside the library, `<library parent>/<library name> backups`).
- Produces in `backup`:
  - `BackupError(StoreError)` with `.code` (400 default; 409 busy; 404 no such backup).
  - Constants: `FOLDERS = ("Poems", "Books", "Styles", "Research")`; `SKIP_DIRS = {"Design renders", ".trash",
    "__pycache__", "node_modules"}`; `MANIFEST = "studio-backup.json"`; `FORMAT = 1`;
    `NAME = re.compile(r"Studio backup (\d{4})-(\d{2})-(\d{2}) (\d{2})(\d{2})(?:-(\d+))?\.zip")`;
    `STORED = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".woff", ".woff2", ".zip", ".docx", ".epub"}`;
    `LOCK = ".studio-backup.lock"`; `LOCK_STALE = 2 * 3600`.
  - `included(library: Path) -> list[tuple[Path, str]]` — sorted `(file, arcname)` for B1/B2: only the `FOLDERS` that
    exist; skip `SKIP_DIRS` at any depth, reparse points (links, junctions), files named `.*.tmp` and `*.partial`; in a
    poem folder (`Poems/<Series>/<Poem>/` with a readable `poem.json` that has a string `slug`): `<slug>.html` in the
    poem folder and `*.png` files at any depth below it whose name starts with `<slug>-`.
  - `fingerprint(files: list[tuple[Path, str]]) -> str` — sha256 hex of `f"{arcname}\0{size}\0{mtime_ns}\n"` lines.
  - `outside(library: Path) -> dict` — `{"folders": [names], "files": int, "bytes": int}`: top-level non-dot folders
    not in `FOLDERS`, and top-level files; cached 10 minutes per library.
  - `open_shared(path: Path) -> BinaryIO` — on Windows `CreateFileW` with `FILE_SHARE_READ | FILE_SHARE_WRITE |
    FILE_SHARE_DELETE`, `OPEN_EXISTING`, `FILE_FLAG_SEQUENTIAL_SCAN`, then `msvcrt.open_osfhandle` → `os.fdopen(fd, "rb")`;
    elsewhere `open(path, "rb")`. Raises `FileNotFoundError`/`PermissionError` like `open`.
  - `read_stable(path: Path) -> tuple[bytes, os.stat_result, bool]` — up to 3 reads until size and `st_mtime_ns` are
    the same before and after; the bool says whether it ended stable.
  - `check_folder(path: Path, library: Path) -> str | None` — the sentences of `config.save`, plus
    `"That's a file, not a folder: {path}."`.
  - `run(reason: str = "manual", progress: Callable[[int, int], None] | None = None, now: datetime | None = None) ->
    dict` — `{"result": "made" | "unchanged", "name", "bytes", "files", "warnings": [str]}`; records state; raises
    `BackupError` (after recording the failure).
  - `list_backups(folder: Path | None = None) -> list[dict]` — newest first: `{"name", "when" (iso, from the
    manifest's `created`, else from the name), "bytes", "files", "library", "computer", "same_library", "readable",
    "fingerprint"}`; `same_library` is true only for the same library path (compared with `os.path.normcase`) *and*
    the same computer (`platform.node()`) (spec B12); manifests cached by `(name, size, mtime_ns)`.
  - `newest(now=None) -> dict | None` — the newest readable backup with `same_library`.
  - `same_disk(folder: Path, library: Path) -> bool` — `st_dev` of the folder (or its nearest existing parent) equals
    the library's; `False` when either can't be read.
  - `manifest(name: str) -> dict` — `BackupError(404)` unless `name` fullmatches `NAME` and exists.
  - `status() -> dict` — `{"on", "folder", "default_folder", "folder_problem", "same_disk", "state", "running"}`;
    `state` is the state file's dict; `running` is `{"reason", "done", "total"}` or `None`.
  - Routes: `GET /api/backups` → `{**status(), "backups": list_backups(), "outside": outside(config.ART)}` (a folder
    that can't be listed gives `"backups": []` and its sentence in `folder_problem`); `POST /api/backups/run` → starts
    `run("manual")` on a daemon thread and replies `status()`, or 409 when one runs; `POST /api/backups/reveal`
    `{name?, path?}` → shows the folder, a backup (`name`), or a folder `restore_all` made (`path` listed in state
    `"restored"`) in the file manager (same commands as `/api/reveal` in `web.py`); anything else 404.

`run()` in order (B4–B7, B11, B13): take the module lock without waiting (else `BackupError(409, "A backup is already
running.")`); background I/O priority on Windows for the duration (`SetThreadPriority(GetCurrentThread(),
0x00010000)` / `0x00020000`, failures ignored); resolve `config.BACKUPS` and `check_folder`; create the folder when its
parent exists, else fail "The backup folder {folder} isn't there. Is the drive connected?"; take the folder lock file
(`os.open(O_CREAT | O_EXCL)`, `{"pid", "when"}`; an older-than-`LOCK_STALE` lock is replaced; else 409 "Another Studio
is backing up into this folder. Try again in a moment."); delete leftover `Studio backup *.zip.partial` files;
`included()` and `fingerprint()`; for reasons other than `"manual"`, when `newest()` has the same fingerprint, record
`last_check` and return `"unchanged"`; check free space (`shutil.disk_usage`) against `1.2 ×` the newest backup's
size, or the uncompressed total when there is none; write `<name>.zip.partial` with `zipfile` (one `ZipInfo` per file,
`date_time` from the file's mtime clamped to 1980-01-01..2107-12-31, `ZIP_STORED` for `STORED` suffixes else
`ZIP_DEFLATED` level 6, data from `read_stable`; a file that vanished is left out; a file that can't be read is left
out with a warning "{arcname} couldn't be read ({reason})."; an unstable one is taken with "{arcname} changed while it
was copied."), manifest last (`json`, `ensure_ascii=False`, `indent=1`); flush, `os.fsync`; reopen, `testzip()` is
`None` and the manifest's `files` equals the member count minus one; `os.replace` to the final name; record success
(state `last_ok`, `last_check`, `last_result`, clears `last_error`); release both locks. On `OSError` with
`errno.ENOSPC` or `winerror` 112: the disk-full sentence (B13); `PermissionError`: "Studio can't write in {folder}.
Choose another folder."; others: "The backup didn't finish: {error}." The partial file is always removed on failure.
Sizes in sentences as "12 MB", "940 KB". The manifest's `items` (B11) come from the `poem.json` and `book.json` bytes
already read (titles; a piece's title from `manuscript.title_of` on its text, or its kind), no extra reads. State file:
`config.CACHE / "backups" / "state.json"` via `store.write_text`.

- [ ] **Step 1: Write the failing tests** (`tests/test_backup.py`; `setUp` makes a temp library and a temp backup
  folder, sets `STUDIO_ART`, `STUDIO_CONFIG`, `STUDIO_CACHE`, `STUDIO_BACKUPS` and calls `config.refresh()`; `tearDown`
  restores them; a `NOW = datetime(2026, 11, 13, 3, 0)`):

```python
def test_included_follows_the_skip_rules(self):
    # Poems/Sea/series.json, Poems/Sea/_kit/build.py, Poems/Sea/_kit/__pycache__/b.pyc,
    # Poems/Sea/Harbour/{poem.json (slug "harbour"), drafts/2026-11-12T0310.md, writing-notes.md, .studio/days.json,
    #   designs/night.json, designs/.trash/old.json, Design renders/night/x.png, harbour.html,
    #   Carousel 4x5/Signed/harbour-45-1-flare.png, harbour-carousel-preview.png, my-photo.png,
    #   .poem.json.12.34.tmp}, Poems/.trash/Sea/Old/poem.json,
    # Books/Field Notes/{book.json, manuscript/one.md, exports/Field Notes 2026-11-12 1405.docx, .studio/days.json},
    # Styles/rules.md, Research/n.md, Research/.trash/x.md, Other/big.bin, top.txt
    self.assertEqual([a for _, a in backup.included(self.lib)], sorted([
        "Books/Field Notes/.studio/days.json", "Books/Field Notes/book.json",
        "Books/Field Notes/exports/Field Notes 2026-11-12 1405.docx", "Books/Field Notes/manuscript/one.md",
        "Poems/Sea/Harbour/.studio/days.json", "Poems/Sea/Harbour/designs/night.json",
        "Poems/Sea/Harbour/drafts/2026-11-12T0310.md", "Poems/Sea/Harbour/my-photo.png",
        "Poems/Sea/Harbour/poem.json", "Poems/Sea/Harbour/writing-notes.md", "Poems/Sea/_kit/build.py",
        "Poems/Sea/series.json", "Research/n.md", "Styles/rules.md"]))

def test_outside(self):
    self.assertEqual(backup.outside(self.lib)["folders"], ["Other"]); self.assertEqual(backup.outside(self.lib)["files"], 1)

def test_run_makes_a_verified_zip(self):
    r = backup.run(now=NOW)
    self.assertEqual(r["name"], "Studio backup 2026-11-13 0300.zip"); self.assertEqual(r["result"], "made")
    with zipfile.ZipFile(self.dest / r["name"]) as z:
        m = json.loads(z.read("studio-backup.json"))
        self.assertEqual(sorted(n for n in z.namelist() if n != "studio-backup.json"), [a for _, a in backup.included(self.lib)])
        self.assertEqual(z.read("Poems/Sea/Harbour/writing-notes.md"), (self.poem / "writing-notes.md").read_bytes())
    self.assertEqual((m["format"], m["library"], m["files"]), (1, str(self.lib), 14))
    self.assertEqual(m["items"]["poems"], [{"id": "Sea/Harbour", "title": "Harbour", "series": "Sea"}])
    self.assertEqual(m["items"]["books"][0]["pieces"][0]["file"], "one.md")
    self.assertEqual(list(self.dest.glob("*.partial")), [])

def test_same_minute_gets_a_number(self):
    backup.run(now=NOW); self.assertEqual(backup.run(now=NOW)["name"], "Studio backup 2026-11-13 0300-2.zip")

def test_unchanged_makes_no_zip_unless_asked(self):
    backup.run(now=NOW)
    self.assertEqual(backup.run("daily", now=NOW + timedelta(days=2))["result"], "unchanged")
    self.assertEqual(len(list(self.dest.glob("*.zip"))), 1)
    self.assertEqual(backup.run("manual", now=NOW + timedelta(days=2))["result"], "made")

def test_leftovers_are_cleaned_and_foreign_files_left_alone(self):
    (self.dest / "Studio backup 2026-11-12 0100.zip.partial").write_bytes(b"x")
    (self.dest / "notes.txt").write_text("mine"); (self.dest / "Studio backup final.zip").write_bytes(b"y")
    backup.run(now=NOW)
    self.assertFalse((self.dest / "Studio backup 2026-11-12 0100.zip.partial").exists())
    self.assertTrue((self.dest / "notes.txt").exists()); self.assertTrue((self.dest / "Studio backup final.zip").exists())

@unittest.skipUnless(sys.platform == "win32", "Windows sharing modes")
def test_a_save_never_waits_on_the_backup(self):
    f = self.poem / "writing-notes.md"; tmp = f.with_name("new.tmp"); tmp.write_text("new", encoding="utf-8")
    with backup.open_shared(f):
        os.replace(tmp, f)          # would raise PermissionError with a plain open()
    self.assertEqual(f.read_text(encoding="utf-8"), "new")

def test_changed_while_read_is_retried_then_noted(self):
    # patch backup.open_shared so every read also bumps the file's mtime: three tries, then a warning
    self.assertIn("Poems/Sea/Harbour/writing-notes.md changed while it was copied.", backup.run(now=NOW)["warnings"])

def test_unreadable_file_is_left_out_with_a_warning(self):           # Review Focus 3
    # patch open_shared to raise PermissionError for writing-notes.md only
    r = backup.run(now=NOW)
    self.assertEqual(r["result"], "made"); self.assertTrue(any("writing-notes.md couldn't be read" in w for w in r["warnings"]))

def test_old_and_future_file_times(self):                            # Review Focus 2
    os.utime(self.poem / "poem.json", (0, 0)); os.utime(self.poem / "writing-notes.md", (5e9, 5e9))
    self.assertEqual(backup.run(now=NOW)["result"], "made")

def test_names_with_accents_round_trip(self):                         # Review Focus 1
    # a poem folder "Café, ’s nachts" in series "Zee – één"
    r = backup.run(now=NOW)
    with zipfile.ZipFile(self.dest / r["name"]) as z:
        self.assertIn("Poems/Zee – één/Café, ’s nachts/poem.json", z.namelist())

def test_failures_are_sentences_in_the_state(self):
    # 1) STUDIO_BACKUPS = <tmp>/missing-drive/Backups → "isn't there. Is the drive connected?"
    # 2) STUDIO_BACKUPS inside the library → "outside your library"
    # 3) shutil.disk_usage patched to 1 KB free → "is full" and "Free some space or choose another folder."
    # 4) ZipFile.writestr patched to raise OSError(errno.ENOSPC, "No space") → "is full"; no .partial left
    # each: assertRaises(backup.BackupError) and backup.status()["state"]["last_error"]["message"] equals the text

def test_locks(self):
    # module lock held → BackupError code 409; a fresh folder lock file → 409 "Another Studio"; a lock file with
    # mtime 3 h ago → the run succeeds and the lock file is gone afterwards

def test_list_backups(self):
    # two runs; a zip whose manifest names another library; one with this library's path and "computer": "OTHER-PC";
    # a garbage file named "Studio backup 2026-01-01 0000.zip"
    names = [(b["name"], b["same_library"], b["readable"]) for b in backup.list_backups()]
    # newest first; other library and other computer same_library False; garbage readable False;
    # backup.newest() is the second run (never the other computer's, even when it is newer)

def test_same_disk(self):
    self.assertTrue(backup.same_disk(self.dest, self.lib))          # both in the temp folder
    self.assertTrue(backup.same_disk(self.dest / "not" / "yet", self.lib))   # nearest existing parent

def test_config_validates_the_backup_settings(self):
    with self.assertRaisesRegex(ValueError, "outside your library"): config.save({"backup_folder": str(self.lib / "x")})
    self.assertFalse(config.save({"backups": "off"})["backups"])
    self.assertEqual(config.BACKUPS, self.dest)          # STUDIO_BACKUPS wins

def test_endpoints(self):
    # temp_studio(): GET /api/backups 200 with "backups", "outside", "on"; POST /api/backups/run 200, then poll
    # GET /api/backups until running is None (max 10 s): one backup listed; POST /api/backups/reveal {"name": "../x"}
    # → 404 (subprocess.Popen patched); POST /api/backups/run with Origin http://evil → 403
```

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** the config keys and validation, `tests/support.py` (`"STUDIO_BACKUPS"` in `_ENV`, set to
  `tmp / "backups"`), `studio/backup.py` as above, and the three routes.
- [ ] **Step 4: Run the module, then the whole suite.**
- [ ] **Step 5: Commit** `Backups: verified zips of the library's Studio folders, and their settings`.

---

### Task 4: Backups: when they run, and what they keep

**Files:**
- Modify: `studio/backup.py`, `studio/web.py` (`serve()`), `studio/routes_library.py`
- Test: `tests/test_backup.py`

**Interfaces:**
- Consumes: Task 3's `run`, `list_backups`, `newest`, `status`, state file.
- Produces:
  - `prune(now: datetime | None = None) -> list[str]` — names deleted. Among readable backups with `same_library`:
    keep every one whose `when` is within 24 hours of `now`, plus the newest of each of the 7 most recent calendar days
    that have one, of the 4 most recent ISO weeks (Monday–Sunday) that have one, and of the 12 most recent months that
    have one (restic's `--keep-daily/weekly/monthly` semantics); delete the rest. Never touches unreadable zips, other
    libraries' backups or files not matching `NAME`. Called by `run()` after a made backup; a prune error becomes a
    warning, never a failure.
  - `due(now: datetime, at_start: bool, newest: dict | None) -> bool` — `True` when `newest` is `None`, else when
    `now - newest.when >= (1 h if at_start else 24 h)`.
  - `auto(at_start: bool, now: datetime | None = None) -> dict | None` — `None` when `config.BACKUPS_ON` is false or
    not `due`; else `run("start" if at_start else "daily", now=now)`; a `BackupError` is swallowed (it is in the state).
  - `start_scheduler(first_delay: float = 60, every: float = 900) -> bool` — once per process (returns `False` when
    already started); a daemon thread named `"studio-backups"`: wait `first_delay`, `auto(True)`, then `auto(False)`
    every `every` seconds; `stop_scheduler()` for tests.
  - `brief(now=None) -> dict` — `{"problem": sentence | None}`: the last failure's message when it is newer than
    `last_ok` and `last_check`; else, when backups are on and the newest of `last_ok`/`last_check` is older than 3 days,
    `"Studio hasn't been able to back up since {date}."`; else `None` (also `None` before any run).
  - `GET /api/backups/brief` → `brief()`.
  - `web.serve()`: `backup.start_scheduler()` right after the updater thread starts.

- [ ] **Step 1: Write the failing tests**

```python
def test_prune_keeps_24_hours_7_days_4_weeks_12_months(self):
    # make_fake(name_time, library=self.lib) writes a minimal zip with a manifest (created = that time).
    # One backup each day at 20:00 from 2025-10-09 to 2026-11-12, and one at 2026-11-13 09:00;
    # plus another library's backup at 2025-01-01 00:00, an unreadable "Studio backup 2025-02-02 0000.zip", "notes.txt".
    backup.prune(now=datetime(2026, 11, 13, 12, 0))
    kept = sorted(p.name for p in self.dest.glob("Studio backup *.zip"))
    expected = {"2026-11-13 0900", "2026-11-12 2000",                                   # last 24 hours
                "2026-11-11 2000", "2026-11-10 2000", "2026-11-09 2000", "2026-11-08 2000", "2026-11-07 2000",  # days
                "2026-11-01 2000", "2026-10-25 2000",                                   # weeks (Sundays)
                "2026-10-31 2000", "2026-09-30 2000", "2026-08-31 2000", "2026-07-31 2000", "2026-06-30 2000",
                "2026-05-31 2000", "2026-04-30 2000", "2026-03-31 2000", "2026-02-28 2000", "2026-01-31 2000",
                "2025-12-31 2000",                                                      # months
                "2025-01-01 0000", "2025-02-02 0000"}                                   # other library, unreadable
    self.assertEqual(kept, sorted(f"Studio backup {x}.zip" for x in expected))
    self.assertTrue((self.dest / "notes.txt").exists())

def test_due(self):
    t = datetime(2026, 11, 13, 12)
    self.assertTrue(backup.due(t, False, None))
    self.assertFalse(backup.due(t, True, {"when": "2026-11-13T11:30:00"}))
    self.assertTrue(backup.due(t, True, {"when": "2026-11-13T10:30:00"}))
    self.assertFalse(backup.due(t, False, {"when": "2026-11-12T13:00:00"}))
    self.assertTrue(backup.due(t, False, {"when": "2026-11-12T12:00:00"}))

def test_auto(self):
    # off → None and no zip; on, nothing yet → made; on, 2 h later at start, unchanged → "unchanged";
    # a changed file 2 h later at start → made; 2 h later not at start → None (not due)

def test_scheduler_runs_once_per_process(self):
    with mock.patch.object(backup, "auto") as a:
        self.assertTrue(backup.start_scheduler(first_delay=0, every=0.05)); self.assertFalse(backup.start_scheduler())
        <wait until a.call_count >= 2>; backup.stop_scheduler()
    self.assertEqual(a.call_args_list[0], mock.call(True))

def test_test_servers_never_back_up(self):
    with temp_studio():
        self.assertNotIn("studio-backups", [t.name for t in threading.enumerate()])

def test_the_library_changes(self):                                   # Review Focus 5
    # a backup of library A, then config pointed at library B: newest() is None, run() names B in its manifest,
    # prune() leaves A's backup alone

def test_brief(self):
    # no state → None; a failure → its sentence; a success after it → None;
    # last_ok 4 days old and no check since → "Studio hasn't been able to back up since 9 Nov 2026."
```

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `prune`, `due`, `auto`, `start_scheduler`, `stop_scheduler`, `brief`, the route, the
  `run()` call to `prune()`, and the `serve()` line.
- [ ] **Step 4: Run the module, then the whole suite.**
- [ ] **Step 5: Commit** `Backups: on start and daily, with 7 daily, 4 weekly and 12 monthly kept`.

---

### Task 5: Restore

**Files:**
- Modify: `studio/backup.py`, `studio/routes_library.py`
- Test: `tests/test_backup.py` (or `tests/test_restore.py` if `test_backup.py` passes 600 lines)

**Interfaces:**
- Consumes: Task 3's `manifest`, module lock; `Store.delete_poem(pid)` (trash), `Books.delete_book(id)`,
  `Books._trash(path, name, suffix)`, `Books._meta(d)`, `Books._save_meta(d, meta)`, `books._LOCK`, `books.BACK_MATTER`,
  `store.write_text`, `store.dump_poem`.
- Produces:
  - `items(name: str) -> dict` — `{"name", "when", "library", "same_library", "poems": [{"id", "title", "series",
    "exists"}], "books": [{"id", "title", "exists", "pieces": [{"file", "title", "kind", "form", "exists"}]}]}`;
    a piece exists when its book exists now and its file is in that book's `book.json` contents and on disk.
  - `restore_item(name: str, kind: str, ref: str | dict, mode: str, now: datetime | None = None) -> dict` — `kind` in
    `poem` (ref: poem id `"<Series>/<Folder>"`), `book` (ref: book folder name), `piece` (ref: `{"book", "file"}`);
    `mode` in `copy`, `replace` (both need the item to exist now, else `BackupError(409, "“{title}” isn't in the library
    now. Restore it instead.")`) and `restore` (needs it to be missing, else `BackupError(409, "“{title}” is in the
    library now. Restore a copy or replace it.")`). Returns `{"kind", "title", "href", "path", "trash": str | None}`.
  - `restore_all(name: str, now: datetime | None = None) -> Path` — the new folder; appended to state `"restored"`.
  - `POST /api/backups/restore` `{name, kind, ref, mode}` → `restore_item(...)`; `{name, all: true}` →
    `{"path": str(restore_all(name))}`. Takes the module lock waiting up to 30 s, else `BackupError(409, "A backup is
    running. Try again in a minute.")`.
  - `GET /api/backups/items?name=` → `items(name)`.

Rules (B14): the suffix is `f" (restored {d.day} {d:%b %Y})"` of the backup's date; names that exist get `" 2"`,
`" 3"` before the extension or at the end. Copy of a poem: `Poems/<Series>/<Folder> (restored 13 Nov 2026)`, its
`poem.json` title suffixed (written with `dump_poem`), no `.studio/days.json`. Copy of a book: `Books/<id> (restored 13 Nov
2026)`, `book.json` title suffixed (same JSON style as `books._dump`), no `.studio/days.json`. Copy of a piece:
`manuscript/<stem> restored 2026-11-13.md` in the current book, the first line suffixed when it starts with `# `, a
`book.json` entry copied from the original's current entry with the new `file`, inserted right after it (under
`books._LOCK`). Replace of a poem or book: trash the current one (`delete_poem` / `delete_book`), unpack the backup's
copy into its place (without the backup's `.studio/days.json`), then copy the current `.studio/days.json` from the
trashed folder into it, and for a poem move the files `included()` would skip (its kit renders, `<slug>.html`,
`Design renders/`) from the trashed folder into it, keeping their relative paths (spec B14); a failure after trashing
moves the current one back. Replace of a
piece: the current file to `Books/.trash` through `Books._trash(p, f"{book} {stem}", ".md")`, the backup's text
written in its place (its entry stays). Restore of a missing poem: when the series folder is gone too, also its files
directly in the series folder and its `_kit/` and `stamps/`; a missing book: the whole book folder; a missing piece:
its book must exist (`BackupError(409, "Restore the book “{title}” first.")`), the file is written and an entry
(kind, form, status from the backup's `book.json`) inserted after the entry that preceded it in the backup when that
file is still in the book, else before the first back-matter entry (`books.BACK_MATTER` kinds), else at the end.
Unpacking always goes into a dot-named temporary folder next to the destination, then one `os.replace`; the temporary
folder is removed on failure. Every member is checked before anything is written: names with a leading `/`, a drive
(`:`), a backslash, `..` or empty parts, or symlink modes (`external_attr >> 16` is `S_IFLNK`) raise
`BackupError("This backup holds a file Studio won't unpack: {name}.")`. `restore_all`: everything but the manifest
into `<library parent>/<library name> restored 2026-11-13 0300` (`" 2"` when taken).

- [ ] **Step 1: Write the failing tests**

```python
def test_items_say_what_exists_now(self): ...      # backup, then delete_poem → that poem's exists False
def test_copy_of_a_poem(self):
    r = backup.restore_item(self.name, "poem", "Sea/Harbour", "copy")
    copy = self.lib / "Poems/Sea/Harbour (restored 13 Nov 2026)"
    self.assertEqual(json.loads((copy / "poem.json").read_text("utf-8"))["title"], "Harbour (restored 13 Nov 2026)")
    self.assertFalse((copy / ".studio" / "days.json").exists())
    self.assertEqual((self.poem / "writing-notes.md").read_text("utf-8"), <current text, unchanged>)
    self.assertEqual(backup.restore_item(self.name, "poem", "Sea/Harbour", "copy")["path"], str(copy) + " 2")
def test_replace_a_poem_trashes_the_current_one_and_keeps_its_log(self):
    # after the backup: more days in the current days.json, a kit render "harbour-45-1-flare.png" and harbour.html
    r = backup.restore_item(self.name, "poem", "Sea/Harbour", "replace")
    # the poem folder has the backup's text, the CURRENT days.json, the render and harbour.html;
    # r["trash"] is under Poems/.trash/Sea/ and holds the current text
def test_restore_a_missing_poem_and_its_series(self): ...
def test_copy_replace_and_restore_a_piece(self): ...     # entry order in book.json as the rules say
def test_restore_a_missing_book_and_refuse_a_piece_without_its_book(self): ...
def test_modes_need_the_right_state(self): ...           # copy of a missing poem → 409; restore of an existing → 409
def test_a_failed_replace_puts_the_current_one_back(self):
    # patch os.replace to fail when moving the unpacked folder into place → BackupError, current folder back, no temp
def test_unsafe_members_are_refused(self):
    # a zip with "Poems/Sea/Harbour/../../evil.txt", one with "C:/x", one with a symlink entry → BackupError,
    # nothing new in the library
def test_restore_all(self):
    p = backup.restore_all(self.name)
    self.assertEqual(p.name, f"{self.lib.name} restored 2026-11-13 0300")
    self.assertTrue((p / "Poems/Sea/Harbour/poem.json").exists()); self.assertFalse((p / "studio-backup.json").exists())
def test_accented_names_restore_exactly(self): ...       # Review Focus 1: "Zee – één/Café, ’s nachts" copy and restore
def test_restore_endpoints(self): ...                    # items and restore through temp_studio()
```

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `items`, `restore_item`, `restore_all`, member checking, the two routes.
- [ ] **Step 4: Run the module, then the whole suite.**
- [ ] **Step 5: Commit** `Backups: restore a poem, book, piece or the whole backup, never over what is there`.

---

### Task 6: Settings → Backups and the Home line (front end)

**Files:**
- Create: `studio/static/backups.js`, `studio/static/library.css`
- Modify: `studio/static/index.html` (stylesheet after `book-tools.css`; script after `welcome.js`),
  `studio/static/app.js` (`showSettings` hook), `README.md`, `docs/DESIGN.md`
- Test: create `tests/test_library_static.py` (each new static file is served, 200, with its content type; later tasks
  add their files), plus the browser check below.

**Interfaces:**
- Consumes: `GET /api/backups`, `POST /api/backups/run`, `GET /api/backups/items`, `POST /api/backups/restore`,
  `POST /api/backups/reveal`, `GET /api/backups/brief`, `POST /api/settings` (`backups`, `backup_folder`, `library`),
  `window.pywebview.api.pick_folder(start)`.
- Produces: `window.settingsSections` (array of `{id, html(settings, info) -> string, bind(root, settings, info)}`),
  rendered by `showSettings` as `<section class="set" data-setsec="{id}">…</section>` just before the Updates section
  and bound after the page's own handlers; `backups.js` pushes `{id: "backups", …}` and a Home section
  `{id: "backups", render: () => "", bind}` onto `window.homeSections`.

The Settings section follows the spec's sketch (B9, B13, B15): heading "Backups" with the description; switch
"Back up automatically (when Studio starts, then once a day)" saving `{backups}`; "Backup folder" input with *Choose…*
(only in the app window) saving `{backup_folder}` on change, showing `config.save`'s sentence when refused and the
default folder as placeholder; when `same_disk`, the quiet line from spec B8; the status line (last backup date,
size, "checked 14:20, nothing changed since", or the failure sentence in `--danger` with *Try again*); *Back up now*
and *Show in folder*; the "Not backed up" line when `outside.folders` or `outside.files`; while `running`, "Backing up…
120 of 400 files" polled every second only while `state.view === "settings"`; the list (date with `when()`, size,
files, "From another library (path)" / "From another computer (name)" / "Not readable"),
each row a *Restore…* button (opens *Choose what to restore…*) and a right-click menu (*Choose what to restore…*,
*Restore the whole backup…*, *Show in folder*). The restore dialog (`openDialog`): a filter field, poems grouped by
series and books with their pieces (nested), one row selected at a time with the arrow keys or a click; below, the
selected item's line ("“Harbour” · Sea · in the library now" / "not in the library now") and its buttons: *Restore a
copy* and *Replace…*, or *Restore*. *Replace…* asks: "“Harbour” as it is now goes to the trash (Poems/.trash), and the
copy from 13 Nov 2026, 03:00 takes its place." (Books: `Books/.trash`.) After a restore: the dialog closes, a toast
says what happened ("Restored a copy of “Harbour”"), and the section shows a line with an *Open* link to `href`.
*Restore the whole backup…* asks "Unpack the backup from 13 Nov 2026, 03:00 into a new folder next to your library?
Nothing in your library changes." and then shows "Unpacked into {path}" with *Use it as the library* (confirm:
"Studio will switch to {path}. Your current library stays where it is; switch back in Settings → Library." → `POST
/api/settings {library: path}` → `location.reload()`) and *Show in folder*. The Home line: only when `brief.problem`,
`<p class="lt-home-warn">{problem} <a href="#/settings">Settings → Backups</a></p>` in `--danger`, hairline above.

- [ ] **Step 1:** Add the `settingsSections` hook to `showSettings` (two additive lines: the template insertion and the
  bind loop) and the `index.html` lines; write `tests/test_library_static.py` asserting `GET /static/backups.js`,
  `/static/library.css` are 200 (and, in later tasks, the others); run it (fails: files missing).
- [ ] **Step 2:** Write `backups.js` and the `.lb-*` / `.lt-home-warn` rules in `library.css` (dark and light through
  tokens only).
- [ ] **Step 3: Browser check.** Start a scratch server on a free port in 4748–4766 with temp `STUDIO_ART` (copy a few
  poems and a book made by `studio/examples.py`'s `add_examples` or by hand), `STUDIO_CONFIG`, `STUDIO_CACHE`,
  `STUDIO_BACKUPS`; open Settings in the browser pane; *Back up now*; see the list; restore a copy of a poem and of a
  piece, replace a poem (confirm text), restore the whole backup (check the new folder, then don't switch); make the
  backup folder fail (point it at `Z:\nothere`) and see the sentence in Settings and on Home. Check light and dark.
  Stop the server.
- [ ] **Step 4:** README ("What's in it": **Backups**; "On disk": the backup folder and what it holds) and DESIGN.md
  (a "Backups" section: what, when, where, retention, restore rules, the endpoints). Run the whole suite.
- [ ] **Step 5: Commit** `Settings: backups, with restore, and a line on Home when they fail`.

---

### Task 7: The writing log page and Home section (front end)

**Files:**
- Create: `studio/static/writing.js`, `tests/js/writing.js`, `tests/test_writing_js.py`
- Modify: `studio/static/library.css`, `studio/static/index.html` (script), `studio/static/app.js` (one `route()`
  line), `tests/test_library_static.py`, `README.md`, `docs/DESIGN.md`

**Interfaces:**
- Consumes: `GET /api/writing` (Task 1's shape).
- Produces: `window.WritingLog = {weekStart(iso) -> iso, addDays(iso, n) -> iso, totals(data, iso) -> {poems, books:
  {id: n}, total}, periods(data, mode: "days"|"weeks"|"months", count) -> [{label, start, end, poems, books, total}],
  goalStats(days: {iso: n}, goal: number, today: iso, span = 30) -> {met, of, since: iso | null}, summary(data) ->
  {today, week, month, year}}` (pure, no DOM, usable in node: same wrapper pattern as `book-tools.js`); `showWritingLog()`
  (global); the route line in `app.js`: `if (h === "/writing") return showWritingLog();` before the Home fallback.
  Dates are `YYYY-MM-DD` strings computed with UTC arithmetic (no DST drift); weeks start Monday.
  `goalStats`: `first` = earliest key with a value; `start` = later of `today - (span - 1)` and `first`; `of` = days
  from `start` to `today` inclusive; `met` = days in that range whose words ≥ goal; `since` = `first` when it is after
  `today - (span - 1)`, else `null`. No days at all → `{met: 0, of: 0, since: null}`.

The page and the Home section follow the spec's sketch (W3–W6): kicker "Studio", display "Writing log"; the summary
line; the *Days | Weeks | Months* segmented control (`.seg`, remembered with `pref` key `writing.period`); the table
(30 days / 12 weeks / 12 months, newest first; labels "Thu 13 Nov", "10–16 Nov", "Nov 2026"; columns Poems (when any
poem has days), each book with days in range or a goal, Total, and a thin bar scaled to the largest total shown);
numbers `toLocaleString("en-GB")` in tabular figures; "—" for nothing; in the Days view a book cell that met its goal
reads "610" followed by muted "goal met"; the Books list (title linking to the book; "Daily goal 500 words · met on 9
of the last 30 days" or "met on 4 of 6 days since 8 Nov"; "No daily goal"; "12,400 words this month") and the Poems
line ("1,020 words this month, in 7 poems"). Nothing written yet: "Nothing written yet. Words you add to poems and
books are counted here, day by day." Home section (`window.homeSections`, id `writing`): hidden until there is a
recorded day; `<h2 class="h2">Writing</h2>` with *Writing log →* (`btn quiet`, like *All series →*); "Today 320
words · this week 1,240"; the last 14 days as thin bars with `title` and `aria-label` ("Thu 13 Nov: 660 words").

- [ ] **Step 1: Write the failing node test** `tests/js/writing.js` (loads `studio/static/writing.js` in a `vm`
  context with `globalThis` as `window`) and `tests/test_writing_js.py` (skips without node, like
  `tests/test_book_tools.py`):

```js
const W = window.WritingLog;
eq(W.weekStart("2026-11-13"), "2026-11-09");
eq(W.weekStart("2026-11-09"), "2026-11-09");
eq(W.addDays("2026-03-28", 2), "2026-03-30");                      // across the DST change
const data = {today: "2026-11-13", days: {"2026-11-13": {poems: {"Sea/Harbour": 120}, books: {"Field Notes": 540}},
  "2026-11-09": {poems: {}, books: {"Field Notes": 610}}, "2026-10-31": {poems: {}, books: {"Field Notes": 100}}}};
eq(W.periods(data, "weeks", 3).map(p => p.total), [1270, 0, 100]);   // 9–15 Nov, 2–8 Nov, 26 Oct–1 Nov
eq(W.periods(data, "months", 2).map(p => [p.label, p.total]), [["Nov 2026", 1270], ["Oct 2026", 100]]);
eq(W.summary(data), {today: 660, week: 1270, month: 1270, year: 1370});
eq(W.goalStats({"2026-11-09": 610, "2026-11-13": 540}, 500, "2026-11-13"), {met: 2, of: 5, since: "2026-11-09"});
eq(W.goalStats({"2026-09-01": 900, "2026-11-13": 540}, 500, "2026-11-13"), {met: 1, of: 30, since: null});
eq(W.goalStats({}, 500, "2026-11-13"), {met: 0, of: 0, since: null});
```

- [ ] **Step 2: Run** `...python.exe -m unittest tests.test_writing_js -v` — fails (no `writing.js`).
- [ ] **Step 3: Implement** `writing.js` (helpers, page, Home section), the route line, the `index.html` script, the
  `.wl-*` rules in `library.css`; extend `tests/test_library_static.py` with `writing.js`.
- [ ] **Step 4: Browser check** on a scratch server whose temp library has `.studio/days.json` files spread over two
  months for two books (one with a goal) and three poems: Home section, the page in all three views, light and dark,
  numbers right-aligned on one edge (measure in the page: the right edges of the number cells in a column are equal).
  Stop the server. Docs: README ("What's in it": **Writing log**; "On disk": `.studio/days.json` in a poem folder) and
  DESIGN.md ("Writing log"). Run the whole suite.
- [ ] **Step 5: Commit** `Writing log: words per day, week and month, on Home and its own page`.

---

### Task 8: The search panel, Ctrl+K and the jumps (front end)

**Files:**
- Create: `studio/static/search.js`
- Modify: `studio/static/library.css`, `studio/static/index.html` (script; the *Search* button), `studio/static/app.js`
  (one line in Info), `studio/static/book-tools.js` (one action), `tests/test_library_static.py`, `README.md`,
  `docs/DESIGN.md`

**Interfaces:**
- Consumes: `GET /api/search`, `POST /api/search/warm` (Task 2's shapes); `window.BookTools.state` (`W`, `rail`),
  `BookTools.activePiece()`, the global `PM` (`PM.TextSelection`); `pref`, `state`, `route`.
- Produces: `window.LibrarySearch = {open(q = ""), close(), go(result)}`.

Panel (S5, S6): `<div class="ls-wrap"><div class="ls" role="dialog" aria-modal="true" aria-label="Search the
library">`, a combobox input (placeholder "Search poems, books and designs"), a listbox with group headings ("Poems ·
23"), rows (`.ls-i`: title with marks in `<mark>`; `where` and `field_label` muted on the right; the snippet below in
the body face with marks), a *Show all 23 poems* row (`.ls-more`) per truncated group that fetches `kind=…&limit=200`
and replaces that group, and a footer (`.ls-f`): counts ("312 poems · 2 books · 41 designs"), freshness ("Checked just
now" under 10 s, "Checked 2 min ago", "Checking for changes…", "Reading the library… 1,200 of 5,000"), errors in
`--danger`, and "↑↓ to move · Enter to open · Esc to close". Input debounced 120 ms; replies older than the newest
request are dropped; when a reply says `checking` or `building`, the same query is asked again after 400 ms (at most
20 times). Opening calls `/api/search/warm`. The last query and results are kept while Studio runs, so reopening shows
them with the text selected. Keys inside the panel: ↓/Tab next, ↑/Shift+Tab previous, PageDown/PageUp by 8, Enter
opens (or expands on a *Show all* row), Esc and Ctrl+K close; every keydown in the panel calls `stopPropagation()` so
the design editor's and the book's shortcuts never see it. Hover marks a row, click opens. Closing returns focus to
where it was. The nothing-found line: "Nothing in the library matches “q”."

Ctrl+K (S5): one `keydown` listener on `window`, added by `search.js` (after `book-tools.js`, so the book palette's
listener runs first): ignore when `e.defaultPrevented`, when `state.view === "book" && window.BookTools?.state?.W`, or
when `$("#dlg").open`; otherwise `preventDefault()` and open (or close) the panel. The top bar button
`<button class="btn quiet" id="search" type="button" title="Search the library (Ctrl+K)">Search</button>` sits before
`#new` in `index.html`; `search.js` wires it. In `book-tools.js`'s `actions()`, one entry first in the returned list:
`...(root.LibrarySearch ? [act(q ? \`Search the library for “${q}”\` : "Search the library…", "Library", () =>
root.LibrarySearch.open(q))] : [])` with `const q = R.pal?.input.value.trim() || ""` at the top of `actions()`. Info:
in the "Writing window keys" list change the Ctrl+K line to "command palette: jump to a piece, run an action, or search
the library", and add a first line `["Ctrl+K", "search the library"]` to a new "Keys" list in Info's general part if
there is none (one `<section class="set">`, same markup as the others).

Jumps (S7), `LibrarySearch.go(result)`: close the panel; for a design, `pref.set("last." + jump.id, jump.slug)` first;
set `location.hash = result.href` (when it is already the current hash, call `route()`); then, for 3 s at most, on
each animation frame check that the page is ready and apply:
- poem: ready when `state.view === "poem" && state.poem?.id === jump.id` and the field exists: `#title`, `#text`,
  `#notes`, or `#ad-notes .ad-text` (click `#ad-notes [data-mode=write]` first when it is in preview). Find the range:
  `jump.match` at `jump.start` when the text there equals it, else the first case-insensitive occurrence of
  `jump.match`, else stop. Then `focus()`, `setSelectionRange(a, b)`, and scroll: a textarea's own `scrollTop` to put
  the line about a third down (line index × computed line height), and `scrollIntoView({block: "center"})` for the page.
- piece: ready when `window.BookTools?.state?.W?.piece?.file === jump.file && BookTools.activePiece()?.text`; then
  `BookTools.state.rail?.open("find", {query: jump.match})`; then in `BookTools.activePiece().text.view`, find the first
  text occurrence of `jump.match` (case-insensitive) with `doc.descendants`, and dispatch
  `tr.setSelection(PM.TextSelection.create(doc, from, to)).scrollIntoView()` and focus the view. If anything here is
  missing, stop after the rail (the Find panel already lights every match).
- everything else: navigating is the jump.

- [ ] **Step 1:** Extend `tests/test_library_static.py` with `search.js` (fails).
- [ ] **Step 2: Implement** `search.js`, the `.ls-*` rules in `library.css` (the palette's geometry from
  `book-tools.css` `.bt-pal*`: top `min(14vh, 128px)`, width `min(640px, calc(100vw - 32px))`, 56 px field), the
  `index.html` lines, the `book-tools.js` action and the Info lines.
- [ ] **Step 3: Browser check** on a scratch server with a temp library (poems with notes, a design, a book with a
  note): Ctrl+K from Home, Poems, a poem's Write and Design tabs, Settings; a query that hits each kind; Enter on a
  poem text match (selected in the poem), on a writing-notes match, on a design, on a piece (the piece opens, the
  Find panel shows the query, the match is selected); *Show all*; Esc; Ctrl+K inside a book opens the book palette,
  whose first action searches the library; typing in the panel over the Design tab moves no layer. Light and dark;
  the panel's left edges line up (measure). Stop the server.
- [ ] **Step 4:** README ("What's in it": **Search**, Ctrl+K) and DESIGN.md ("Search": the index, freshness, the
  endpoints). Run the whole suite and `tests/e2e_mcp.py`.
- [ ] **Step 5: Commit** `Search: Ctrl+K across the library, grouped, jumping to the match`.
