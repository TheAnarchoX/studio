# Updater, styles, home and first run — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Studio 1.1: update itself from inside the app, and let anyone choose and edit looks, palettes, fonts and
rules (globally, per series, per poem), with a Home page, a light theme and a welcome for new installs.

**Architecture:** New Python modules beside the existing ones (`updater.py`, `fonts.py`, `styles.py`, `home.py`,
`examples.py`), each owning one concern and exposing plain functions or one class; HTTP endpoints move into route
tables (`routes.py` + `routes_*.py`) so `web.py` stays plumbing. The front end stays classic scripts without a
build: new pages in `styles.js`, `home.js`, `welcome.js` use the globals of `app.js`. Fonts become data: one
registry (server) describes every family's files and axes, and the editor, renderer, metrics and CSS all read it.

**Tech Stack:** Python 3.11+ stdlib HTTP server, fontTools (+ brotli for .woff2), Pillow, unittest; plain JS/CSS.

**Specs:** `docs/superpowers/specs/2026-11-12-styles-home-design.md`; the updater was agreed in the design
conversation and is specified in Tasks 2–3 below.

## Global constraints

- Run tests with `python -m unittest discover tests` (from the repo root, the repo's `.venv`); every task ends green.
- No front-end build step: classic `<script>` files; shared helpers `$`, `$$`, `api`, `toast`, `esc`, `md`,
  `openDialog`, `setNav`, `route` are globals defined in `studio/static/app.js`.
- Every new endpoint goes through the route tables of Task 1, so it keeps `Handler._guard` (localhost Host check)
  and, for POST, the Origin and JSON checks of `Handler._post`.
- Files are the database: write with `studio.store.write_text` (atomic); never rewrite a user's file on read.
- Network only for: the update check (`https://api.github.com/repos/TheAnarchoX/studio/releases/latest`),
  update downloads, Google Fonts browsing and adding. Requests carry `User-Agent: Studio/<version>` and nothing
  about the user.
- Nothing personal in the repo: no real names, poem or book titles, or paths in code, tests, fixtures or examples.
- Interface copy: sentence case, plain, no badges or decorative flourishes; right-click menus where lists exist.
- 1.0 libraries keep working untouched: `series.json` with palette lists and `{"family", "role": "voice"|"command"}`
  fonts, designs using `"font": "Newsreader"`/`"Archivo"`, no `Styles/` folder.
- Commits: repo-local identity is already `TheAnarchoX <theanarchox@proton.me>`; end messages with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.

## Review focus

1. **No network, rate limits, no release yet:** the update check fails silently (no toast, nothing blocks start)
   and tries again the next day. Pinned in Task 2 (`test_check_survives_network_errors`).
2. **A source checkout that can't fast-forward** (local changes, local commits, detached HEAD, no git on PATH):
   the update refuses with a clear sentence and leaves HEAD where it was. Pinned in Task 3.
3. **1.0 libraries:** series and designs from 1.0 render exactly as before and no file is rewritten on read.
   Pinned in Task 7 (`test_legacy_series_unchanged_on_read`) and Task 5 (`test_metrics_key_format_unchanged`).
4. **Odd font files:** static families spread over files, .woff2, .ttc collections, missing `sCapHeight`,
   restricted embedding, the same family name from two sources (own file wins over Google over bundled over
   system). Pinned in Tasks 5–6.
5. **A fresh install:** no `Poems/`, `Styles/` or config file; Home, Styles, Settings and the welcome all load
   without errors. Pinned in Task 12 (`test_home_empty_library`) and Task 8 (`test_styles_empty_library`).

---

### Task 1: Route tables and a live test server

**Files:**
- Create: `studio/routes.py`, `tests/support.py`, `tests/test_web.py`
- Modify: `studio/web.py` (`Handler._get` before the final 404, `Handler._post` after body parsing)

**Interfaces:**
- Produces: `routes.GET: dict[str, Callable[[Handler, dict], None]]`, `routes.POST: dict[str, Callable[[Handler, dict], None]]`;
  decorators `@routes.get(path)` / `@routes.post(path)`; `routes.PREFIX_GET: list[tuple[str, Callable[[Handler, str, dict], None]]]`
  with `@routes.get_prefix("/fonts/")` (handler receives the rest of the path). Handlers reply with
  `h._send(code, body, ctype=...)` and raise `StoreError` for 400s.
- Produces: `tests.support.temp_studio()` context manager yielding an object with `.root: Path` (the library),
  `.url: str`, `.get(path) -> (status, json_or_bytes)`, `.post(path, body) -> (status, json)`; it sets
  `STUDIO_ART`, `STUDIO_CONFIG`, `STUDIO_CACHE` to temp paths, calls `config.refresh()`, serves
  `StudioServer(("127.0.0.1", 0), Handler)` in a daemon thread with `Handler.store = Store()`, and restores
  everything on exit. POSTs send `Origin: <url>` and `Content-Type: application/json`.

- [ ] **Step 1: Write the failing tests** in `tests/test_web.py`:
  `test_registered_get_and_post_routes` (register `@routes.get("/api/_t")` returning `{"x": q.get("x")}` and
  `@routes.post("/api/_t")` echoing the body; assert `get("/api/_t?x=1") == (200, {"x": "1"})` and the echo),
  `test_prefix_route` (`/_p/a/b` gives the handler `"a/b"`), `test_unknown_path_is_404`,
  `test_post_from_another_origin_is_403` (raw request with `Origin: http://evil.test`).
- [ ] **Step 2:** Run `python -m unittest tests.test_web -v` → FAIL (`studio.routes` missing).
- [ ] **Step 3:** Implement `studio/routes.py` and the two lookups in `web.py` (exact-path tables first, then
  prefixes, then the existing if-chain). `web.py` imports route modules for registration at the bottom
  (`from . import routes_update  # noqa: F401` etc., added by later tasks).
- [ ] **Step 4:** Run the whole suite → PASS.
- [ ] **Step 5:** Commit `Route tables for the web API; live test server`.

### Task 2: Update check

**Files:**
- Create: `studio/updater.py`, `studio/routes_update.py`, `tests/test_updater.py`
- Modify: `studio/config.py` (`DEFAULTS["update_check"] = True`; `save()` coerces it to bool from
  `True/False/"true"/"false"/"1"/"0"/"on"/"off"`; `refresh()` sets `UPDATE_CHECK`), `studio/web.py` (`serve()`
  starts `threading.Thread(target=updater.check, daemon=True)` after binding)

**Interfaces:**
- Produces: `updater.LATEST_URL = "https://api.github.com/repos/TheAnarchoX/studio/releases/latest"`,
  `updater.ASSET = "Studio-windows-x64.zip"`, `updater.parse_version(s: str) -> tuple[int, ...]`,
  `updater.install_kind() -> Literal["frozen", "source", "package"]` (frozen: `sys.frozen`; source:
  `Path(studio.__file__).parent.parent / ".git"` exists; else package),
  `updater.check(force: bool = False, now: float | None = None, fetch: Callable[[str], bytes] | None = None) -> dict`
  returning `{"current", "latest", "available": bool, "url", "notes", "asset", "checked", "kind", "error"?}`.
  Cache file `config.CACHE / "update.json"`; fetches only when `force` or (`config.UPDATE_CHECK` and the last
  check is ≥ 24 h old). Headers `User-Agent: Studio/<version>`, `Accept: application/vnd.github+json`, timeout 5 s.
  `notes` is the release body cut to 2000 characters; `asset` is the `browser_download_url` of the asset named
  `ASSET` or `None`.
- Produces endpoints: `GET /api/update` → `check()`; `POST /api/update/check` → `check(force=True)`.

- [ ] **Step 1: Write the failing tests** (fake `fetch` returning a recorded release JSON):
  `test_parse_version` (`"v1.2.0" → (1, 2, 0)`, `"1.10" > "1.9"`, `"nonsense" → (0,)`),
  `test_newer_release_is_available` (tag `v9.0.0` → `available` True, `latest == "9.0.0"`, `asset` ends with
  `Studio-windows-x64.zip`), `test_same_version_is_not_available`, `test_check_is_cached_for_a_day` (second call
  within 24 h doesn't call `fetch`; at +25 h it does), `test_check_respects_the_setting` (`UPDATE_CHECK` False:
  no fetch unless `force`), `test_check_survives_network_errors` (fetch raising `URLError`, an `HTTPError` 403
  and returning `b"not json"` each give `available` False with an `error` string and no exception).
- [ ] **Step 2:** Run `python -m unittest tests.test_updater -v` → FAIL.
- [ ] **Step 3:** Implement `updater.py` (check part), the config key and `routes_update.py` (GET, POST check).
- [ ] **Step 4:** Run the suite → PASS.
- [ ] **Step 5:** Commit `Updater: daily release check`.

### Task 3: Apply an update and restart

**Files:**
- Modify: `studio/updater.py`, `studio/routes_update.py`, `studio/desktop.py` (register a quit hook),
  `studio/static/app.js` (Settings and Info pages), `studio/static/app.css`
- Test: `tests/test_updater.py`

**Interfaces:**
- Produces: `updater.UpdateError(Exception)`;
  `updater.apply_source(root: Path, run: Callable = subprocess.run) -> list[str]` (log lines): refuses with
  `UpdateError` when `git status --porcelain` is non-empty ("Studio's folder has changes that aren't committed.
  Commit or stash them, then update."), when there's no upstream (`git rev-parse --abbrev-ref @{u}` fails: "This
  checkout doesn't track a remote branch."), when git is missing (`FileNotFoundError`: "Git isn't installed or
  not on the PATH."), or when `git pull --ff-only` fails (its stderr, first line). Then runs
  `[sys.executable, "-m", "pip", "install", "--quiet", "-e", ".[app]"]` in `root`; a pip failure raises
  `UpdateError` with pip's last stderr line (the pulled code stays; the message says to run the command by hand).
- Produces: `updater.prepare_frozen(zip_path: Path, dest: Path) -> Path` (extracts; requires `Studio/Studio.exe`
  in the zip, else `UpdateError("The download isn't a Studio release.")`; returns the extracted `Studio` folder);
  `updater.helper_script(pid: int, src: Path, dst: Path, exe: Path) -> str` (PowerShell: `Wait-Process -Id <pid>`
  with a 60 s timeout, `Copy-Item -Path "<src>\*" -Destination "<dst>" -Recurse -Force`, `Start-Process "<exe>"`);
  `updater.apply() -> dict` (`{"ok": True, "restart": True, "log": [...]}`; frozen on Windows downloads `asset`
  to `config.CACHE / "update" / f"{latest}.zip"`; frozen elsewhere and `package` raise `UpdateError` whose message
  names the release page or the exact pip command `python -m pip install --upgrade "studio-poems[app] @
  git+https://github.com/TheAnarchoX/studio"`).
- Produces: `updater.restart() -> None`: spawns a detached helper that waits for this PID and starts
  `[sys.executable, "-m", "studio", *sys.argv[1:]]` (source/package) or `[sys.executable, *sys.argv[1:]]`
  (frozen; for frozen Windows the PowerShell helper from `helper_script` does the relaunch), then calls
  `updater.on_quit()`; default `on_quit` is `os._exit(0)` after 0.5 s; `desktop.run_app` sets
  `updater.on_quit = lambda: window.destroy()`.
- Produces endpoints: `POST /api/update/apply` → `apply()` (`UpdateError` → 400 with its message);
  `POST /api/restart` → replies `{"ok": True}` then calls `restart()` on a 0.5 s timer.

- [ ] **Step 1: Write the failing tests** on real temporary git repos (a bare "remote" plus a clone; skip the
  class when `git` isn't on PATH): `test_source_update_pulls_and_installs` (fake `run` wrapper records the pip
  command and passes git through; the clone ends at the remote's new commit), `test_dirty_checkout_is_refused`
  (HEAD unchanged), `test_no_upstream_is_refused`, `test_diverged_checkout_is_refused` (local commit + remote
  commit → `UpdateError`, HEAD unchanged), `test_missing_git_is_refused` (`run` raising `FileNotFoundError`),
  `test_prepare_frozen_rejects_other_zips`, `test_prepare_frozen_extracts`, `test_helper_script_waits_copies_and_starts`
  (contains `Wait-Process -Id 1234`, `Copy-Item`, `Start-Process`).
- [ ] **Step 2:** Run `python -m unittest tests.test_updater -v` → FAIL.
- [ ] **Step 3:** Implement the functions and endpoints. Settings gets an **Updates** section: a switch *Check
  for updates* (`update_check`), a line `Studio 1.0.0 · up to date · checked today` or `Studio 1.1.0 is available`
  with **Update** and *What's new* (the release page), and *Check now*. Info shows the same line under its
  heading when an update is available. **Update** asks first ("Studio will close, update and open again."),
  then calls apply, then restart, shows "Updating…" and polls `/api/about` every second until its `version`
  changes, then reloads; an `UpdateError` shows as a toast with its sentence.
- [ ] **Step 4:** Run the suite → PASS. In the browser (a test server on another port): the Updates section shows,
  *Check now* works offline without a toast, and an Update on a dirty checkout shows the refusal.
- [ ] **Step 5:** Commit `Updater: update from the app and restart`.

### Task 4: Bundled font families

**Files:**
- Create: `tools/fetch_fonts.py`, `studio/static/fonts/families.json`, the font files and `OFL-<Family>.txt`
  licences in `studio/static/fonts/`
- Modify: `pyproject.toml` (`dependencies` add `"brotli>=1.1"`), `README.md` (licence line lists the families)

**Interfaces:**
- Produces: `studio/static/fonts/families.json`:
  `[{"family": "Literata", "category": "serif", "license": "OFL-1.1", "license_file": "OFL-Literata.txt",
  "files": [{"file": "Literata[opsz,wght].ttf", "italic": false}, {"file": "Literata-Italic[opsz,wght].ttf", "italic": true}]}, ...]`,
  including the existing Newsreader (serif) and Archivo (sans).

The families and their files from `https://raw.githubusercontent.com/google/fonts/main/ofl/<dir>/` (each dir has
`OFL.txt`); the script downloads them, verifies each opens with fontTools, writes `families.json`, and fails
loudly on any 404:

| Family | Category | Files |
|---|---|---|
| Literata | serif | `literata/Literata[opsz,wght].ttf`, `literata/Literata-Italic[opsz,wght].ttf` |
| EB Garamond | serif | `ebgaramond/EBGaramond[wght].ttf`, `ebgaramond/EBGaramond-Italic[wght].ttf` |
| Source Serif 4 | serif | `sourceserif4/SourceSerif4[opsz,wght].ttf`, `sourceserif4/SourceSerif4-Italic[opsz,wght].ttf` |
| Inter | sans | `inter/Inter[opsz,wght].ttf`, `inter/Inter-Italic[opsz,wght].ttf` |
| Work Sans | sans | `worksans/WorkSans[wght].ttf`, `worksans/WorkSans-Italic[wght].ttf` |
| Fraunces | display | `fraunces/Fraunces[SOFT,WONK,opsz,wght].ttf`, `fraunces/Fraunces-Italic[SOFT,WONK,opsz,wght].ttf` |
| Bebas Neue | display | `bebasneue/BebasNeue-Regular.ttf` |
| IBM Plex Mono | mono | `ibmplexmono/IBMPlexMono-{Regular,Italic,Bold,BoldItalic}.ttf` |
| Caveat | hand | `caveat/Caveat[wght].ttf` |
| Atkinson Hyperlegible | sans | `atkinsonhyperlegible/AtkinsonHyperlegible-{Regular,Italic,Bold,BoldItalic}.ttf` |

Budget: `studio/static/fonts` ≤ 14 MB in total. If it's over, drop the Fraunces italic first, then the Inter
italic, and note it in `families.json` (`"italic": false` only files).

- [ ] **Step 1:** Write `tools/fetch_fonts.py` (stdlib `urllib`; `--check` re-verifies without downloading).
- [ ] **Step 2:** Run `python tools/fetch_fonts.py` → files and `families.json` written; `du -sh studio/static/fonts` ≤ 14 MB.
- [ ] **Step 3:** `pip install -e ".[app]"` (brotli), run the suite → PASS.
- [ ] **Step 4:** Commit `Bundle twelve open-licence font families`.

### Task 5: Font registry, metrics and the renderer read it

**Files:**
- Create: `studio/fonts.py`, `tests/test_fonts.py`
- Modify: `studio/metrics.py` (drop `FILES`; `key()`/`instance()`/`many()` use the registry),
  `studio/static/design-core.js` (lines 17–60, 94–97, 415–423, 591–593), `studio/static/editor.js` (lines 62,
  1544–1606, 1662–1685), `studio/static/render.html`, `studio/static/index.html`
- Create: `studio/routes_styles.py` (font routes only in this task; later tasks add to it)

**Interfaces:**
- Produces: `fonts.FontFile` (dataclass: `path: Path`, `family: str`, `italic: bool`, `weight: int`,
  `axes: dict[str, tuple[float, float, float]]` as (min, default, max), `cap: float` (em), `embeddable: bool`,
  `source: str`, `id: str`); `fonts.Family` (`name`, `category`, `source`, `license`, `files: list[FontFile]`,
  properties `italic: bool`, `wght: tuple[float, float]`, `wdth: tuple[float, float] | None`,
  `opsz: tuple[float, float] | None`, `cap: float`, `embeddable: bool`).
- Produces: `fonts.read_font(path: Path, source: str) -> list[FontFile]` (a `.ttc` gives one per face; unreadable
  → `[]`). Family = name ID 16, else 1; italic = `OS/2.fsSelection` bit 0 or `head.macStyle` bit 1;
  `cap` = `OS/2.sCapHeight / unitsPerEm` when OS/2 version ≥ 2 and > 0, else the `H` glyph's yMax / upm, else 0.7;
  `embeddable` = `OS/2.fsType & 0x0002 == 0`.
- Produces: `fonts.Registry(bundled: Path, library: Path, system_dirs: list[Path] | None = None)` with
  `families(include_system: bool = False) -> list[Family]`, `get(name) -> Family | None`,
  `file_for(name, italic: bool, weight: float) -> FontFile` (variable first; static: nearest `weight` with the
  same italic, else nearest roman), `to_json(include_system=False) -> list[dict]` (family, category, source,
  license, italic, wght, wdth, opsz, cap, embeddable, files `[{url, italic, weight, axes}]`), `css() -> str`
  (`@font-face` per file: quoted family, `font-style`, weight range or value, `font-stretch` range when `wdth`,
  `src:url(<url>) format(...)`), `refresh()`. Precedence for one family name: own file > google > bundled > system;
  a family appears once. URLs: `/fonts/bundled/<file>`, `/fonts/library/<Family>/<file>`, `/fonts/system/<id>`.
  `fonts.registry() -> Registry` returns the process-wide instance for `config.ART / "Styles" / "fonts"`
  (rebuilt when `config.ART` changes).
- Produces endpoints: `GET /api/fonts` → `to_json()`; `GET /api/fonts.css` (`text/css`); prefix `GET /fonts/` →
  the file (system ids only when indexed; anything else 404).
- Produces in JS: `Design.setFonts(list)` (the `/api/fonts` JSON), `Design.family(name) -> object|null`,
  `Design.weightsOf(name) -> [min, max]`, `Design.widthsOf(name) -> [[value, label]]` (the existing `WIDTHS`
  entries inside the family's `wdth` range; `[]` without one), `Design.fontNames() -> string[]`.
- Consumes: `metrics.key(font, italic, weight, width, size)` keeps its string format
  `f"{family}|{int(italic)}|{weight}|{width:g}|{opsz}"`: unknown family → `"Newsreader"`; italic only when the
  family has italics; width only with a `wdth` axis (else 100); `opsz` = the `OPSZ` bucket nearest the size,
  clamped to the family's `opsz` range, or 0 without one.

- [ ] **Step 1: Write the failing tests** in `tests/test_fonts.py` (fixtures are copies of bundled files made
  in a temp dir): `test_reads_a_variable_family` (Newsreader: `wght == (200, 800)`, has `opsz`, roman and italic
  files), `test_archivo_has_widths` (`wdth` min ≈ 62, max ≈ 125), `test_static_family_picks_nearest_weight`
  (IBM Plex Mono, weight 650 → the Bold file; italic 400 → Italic), `test_missing_italic_falls_back_to_roman`
  (Bebas Neue), `test_ttc_gives_one_entry_per_face` (two bundled fonts saved as a `TTCollection`),
  `test_woff2_is_read` (convert a bundled file with fontTools `flavor="woff2"`),
  `test_restricted_embedding_is_flagged` (set `fsType = 2` on a copy), `test_missing_cap_height_uses_H`
  (OS/2 version set to 1), `test_own_file_wins_over_bundled` (a copy of Inter in the library's fonts folder:
  one "Inter", source "file"), `test_css_lists_every_file`, `test_metrics_key_format_unchanged`
  (`key("Newsreader", False, 500, 100, 120) == "Newsreader|0|500|100|72"`, `key("Archivo", True, 700, 87.5, 40)
  == "Archivo|0|700|87.5|0"`, `key("Inter", False, 400, 100, 20)` ends with `|20`), `test_metrics_for_a_new_family`
  (`metrics.instance` for Literata has `cap` > 0.6 and glyphs for `"é"`).
- [ ] **Step 2:** Run `python -m unittest tests.test_fonts -v` → FAIL.
- [ ] **Step 3:** Implement `fonts.py`, the metrics changes and the routes.
- [ ] **Step 4:** Front end: `index.html` and `render.html` load `/api/fonts.css`; `app.js` fetches
  `/api/fonts` once at start (and `render.html` before rendering) and calls `Design.setFonts`; `design-core.js`
  replaces `WEIGHTS`/`CAP0`/the `Archivo`/`Newsreader` conditions with `Design.family(...)` lookups (italic only
  if the family has it, `font-stretch` only with `wdth`, opsz per family); `editor.js` shows *Width* when
  `widthsOf(font).length`, *Italic* when the family has italics, clamps weight to `weightsOf`. `app.css` keeps
  its own `@font-face` for the interface.
- [ ] **Step 5:** Run the suite and `tests/e2e_mcp.py` → PASS. In the browser: an existing 1.0 design renders
  pixel-identically (export it before and after, compare with Pillow `ImageChops.difference(...).getbbox() is None`);
  a text layer set to Literata italic renders and exports.
- [ ] **Step 6:** Commit `Font registry: every family's files and axes, used by metrics, renderer and editor`.

### Task 6: Adding fonts: own files, Google Fonts, the computer's fonts

**Files:**
- Modify: `studio/fonts.py`, `studio/routes_styles.py`
- Test: `tests/test_fonts.py`, fixtures `tests/fixtures/google-metadata.json`, `tests/fixtures/google-download-list.json`
  (recorded once from the live endpoints, cut to three families)

**Interfaces:**
- Produces: `fonts.add_files(items: list[tuple[str, bytes]]) -> dict` → `{"added": [family names],
  "warnings": [sentences]}`; files go to `Styles/fonts/<Family>/<original name>` next to a `family.json`
  (`{"family", "category", "source", "license"}`; category from the Google catalogue when known, else from PANOSE:
  family type 3 → `hand`, serif style 11–13 → `sans`, other text faces → `serif`, otherwise `display`); non-font data raises
  `StoreError("<name> isn't a font file.")`; warnings for `license == "unknown"` ("No licence found in <Family>;
  check it allows use in print.") and not embeddable ("<Family> doesn't allow embedding in PDFs.").
- Produces: `fonts.google_catalog(fetch=None) -> list[dict]` (`{"family", "category", "axes", "italic"}`) from
  `https://fonts.google.com/metadata/fonts` (strip a leading `)]}'` line if present), cached in
  `config.CACHE / "google-fonts.json"` for 7 days; `fonts.google_files(family, fetch=None) -> list[tuple[str, str]]`
  (file name, URL) from `https://fonts.google.com/download/list?family=<family>` (same prefix rule; its
  `manifest.fileRefs`), keeping `.ttf` files and, when variable files exist, only those;
  `fonts.add_google(family, fetch=None) -> dict` (like `add_files`, licence from the catalogue, `source` "google").
- Produces: `fonts.system_dirs() -> list[Path]` (Windows: `%WINDIR%\Fonts`, `%LOCALAPPDATA%\Microsoft\Windows\Fonts`;
  macOS: `/System/Library/Fonts`, `/Library/Fonts`, `~/Library/Fonts`; Linux: `/usr/share/fonts`,
  `/usr/local/share/fonts`, `~/.local/share/fonts`, `~/.fonts`); the system index is built in a background thread
  on first request and cached in `config.CACHE / "system-fonts.json"` keyed by path, size and mtime.
- Produces endpoints: `POST /api/fonts/add` (`{"files": [{"name", "data": base64}]}`), `GET /api/fonts/google?q=&category=`
  (≤ 60 results), `POST /api/fonts/google/add` (`{"family"}`), `GET /api/fonts/system` (`{"indexing": true}` while
  building, else the families).

- [ ] **Step 1: Write the failing tests:** `test_add_files_groups_a_family`, `test_add_rejects_non_fonts`,
  `test_add_warns_about_restricted_fonts`, `test_google_catalog_with_and_without_prefix`, `test_google_files_prefers_variable`,
  `test_add_google_downloads_into_the_library` (fake fetch serving fixture bytes), `test_system_index_lists_a_temp_dir`
  (`system_dirs` patched to a temp dir with one copied font; listed with source "system"),
  `test_system_font_served_only_by_id` (live server: indexed id → 200, a made-up id or a path → 404).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run the suite → PASS.
- [ ] **Step 5:** Commit `Fonts: add your own files, from Google Fonts, or from this computer`.

### Task 7: Palettes, looks, house rules and inheritance

**Files:**
- Create: `studio/styles.py`, `studio/static/styles/palettes/*.json`, `studio/static/styles/looks/*.json`,
  `tests/test_styles.py`
- Modify: `studio/store.py` (remove `PALETTES` and `FONTS`; `series_meta`, `create_series`, `update_series`,
  `_palette`, `read`), `studio/config.py` (`DEFAULTS["default_look"] = "Editorial light"`; `refresh()` sets
  `DEFAULT_LOOK`), `tests/test_store.py` (`test_series_entity` passes `"Blood"` as before)

**Interfaces:**
- Produces: `styles.ROLES = ("background", "text", "accent", "muted")`, `styles.FONT_ROLES = ("display", "text", "label")`;
  `styles.Styles(library: Path, bundled: Path = STATIC / "styles")` with `palettes() -> list[dict]` (each with
  `"source": "bundled" | "own"`, `"edited": bool` when an own copy shadows a bundled one), `palette(name) -> dict`,
  `save_palette(p) -> dict`, `delete_palette(name)`, `looks()`, `look(name)`, `save_look(l)`, `delete_look(name)`,
  `rules() -> str`, `save_rules(text)`, `resolve(levels: list[tuple[str, dict]]) -> dict`,
  `detach(meta: dict, resolved: dict) -> dict`, `link(meta: dict, look: str) -> dict`.
  Files: `Styles/palettes/<name>.json`, `Styles/looks/<name>.json`, `Styles/rules.md`.
- Validation (`StoreError` messages): palette name 1–60 characters; 1–16 swatches; `hex` matches `^#[0-9A-Fa-f]{6}$`;
  `role` one of `ROLES` or absent, each role at most once; a look names an existing palette and gives `display`,
  `text` and `label` as `{"family", "weight", "width"?}`. Deleting a bundled palette or look raises ("Built-in
  palettes can't be deleted. Editing one saves your own copy."); deleting an own copy of a bundled name brings the
  bundled one back.
- `resolve(levels)`: `levels` is ordered from global to most specific, e.g.
  `[("global", {"look": config.DEFAULT_LOOK}), ("series", series_json), ("poem", poem_json)]`. Each level may set
  `look` (string: palette and fonts follow that look), `palette` (string: linked; list or `{"swatches"}`: own copy)
  and `fonts` (roles dict, or the 1.0 list where `voice → text` and `command → display` and `label`). Returns
  `{"look": name|None, "palette": {"name", "swatches", "from": level, "linked": bool}, "fonts": {role: {"family",
  "weight", "width", "from": level}}}`. An unknown look or palette name falls back to the level above.
- Produces: `styles.contrast(a: str, b: str) -> float` (WCAG 2 ratio), `styles.palette_warnings(p) -> list[str]`
  (text-on-background and accent-on-background pairs under 4.5:1), `styles.palette_from_image(data: bytes, n: int = 6) -> list[str]`
  (Pillow median-cut to `2n` colours, by frequency, dropping colours within RGB distance 24 of a kept one).
- Store: `series_meta()` returns the resolved `palette` (list of swatches, as before) plus `look`, `palette_from`,
  `palette_linked`, `font_roles` (resolved roles) and `fonts` as the list of distinct families
  `[{"family": f}, ...]` (display, text, label order) so the editor keeps working; it never writes. `create_series(name,
  tagline="", palette=None, description="", look=None)` writes `"look": look or config.DEFAULT_LOOK` (or the
  palette name when `palette` is given, as 1.0 did) and a README whose *Type* line names the look's display and
  text families. `update_series` accepts `look`, `palette` (name or swatches), `fonts` (roles), `checks` (Task 11)
  and `detach: true` / `link: "<look>"`. `read()` adds `style` = `resolve([global, series, poem])`.

Bundled palettes: the five 1.0 presets (Signal, Ink and paper, Blood, Ultramarine, Ochre, with roles added: first
dark = background on dark palettes, etc.) plus the palettes of the looks below. Bundled looks:

| Look | Palette (role: name hex) | Display / text / label |
|---|---|---|
| Signal | background Night #0C0E11, text Paper #EEEAE2, accent Signal red #DA291C, muted Fog #959AA2, Fog ink #77726B | Archivo 900 w87.5 / Newsreader 400 / Archivo 700 |
| Editorial light | background Paper #F7F5F0, text Ink #1A1A1A, accent Editorial red #C8102E, muted Stone #8A857C | Fraunces 500 / Source Serif 4 400 / Inter 600 |
| Warm linen | background Linen #F0E9DC, text Soot #16130F, accent Ochre #C98A1B, muted Clay #8E5B3C | EB Garamond 500 / EB Garamond 400 / Work Sans 600 |
| Pastel | background Cream #FBF6EE, text Plum ink #3B2E3A, accent Peach #F2A28B, muted Sage #A9C5B4, Lilac #C9B6E4 | Fraunces 400 / Literata 400 / Work Sans 500 |
| Monochrome | background Paper #F2EFE8, text Ink #141414, accent Graphite #6E6B66, muted Pencil #A9A59E | Inter 800 / Inter 400 / Inter 600 |
| High contrast | background Black #000000, text White #FFFFFF, accent Yellow #FFD400, muted Grey #9A9A9A | Bebas Neue 400 / Atkinson Hyperlegible 400 / Atkinson Hyperlegible 700 |
| Academic | background Ivory #FAF8F2, text Ink #1C1C1C, accent Oxford blue #1F3A5F, muted Slate #6B7280 | Source Serif 4 600 / Source Serif 4 400 / Inter 500 |
| Botanical | background Moss paper #EEF0E6, text Forest #1E3A2B, accent Fern #4F7942, muted Lichen #9AA58C, Berry #8E3B46 | Fraunces 600 / Literata 400 / Work Sans 600 |
| Riso | background Paper #F5F1E8, text Riso blue #0078BF, accent Fluorescent pink #FF48B0, muted Blue tint #7FB6DF, Yellow #FFE800 | Bebas Neue 400 / Work Sans 400 / IBM Plex Mono 500 |
| Children's book | background Cream #FFF8E7, text Night blue #1D3557, accent Tomato #E63946, muted Sky #A8DADC, Sun #F4A261 | Caveat 700 / Atkinson Hyperlegible 400 / Atkinson Hyperlegible 700 |

- [ ] **Step 1: Write the failing tests:** `test_bundled_looks_and_palettes` (10 looks; Signal, Blood present),
  `test_editing_a_bundled_palette_makes_an_own_copy` and `..._deleting_it_restores_the_bundled_one`,
  `test_palette_validation` (bad hex, two backgrounds, empty name, 17 swatches), `test_look_validation`,
  `test_resolve_global_only`, `test_resolve_series_look`, `test_resolve_own_palette`, `test_resolve_poem_override`,
  `test_resolve_unknown_name_falls_back`, `test_legacy_series_unchanged_on_read` (a 1.0-style `series.json` with
  a palette list and voice/command fonts: `font_roles["text"]["family"] == "Newsreader"`,
  `font_roles["display"]["family"] == "Archivo"`, the file's bytes identical after `series_meta` and `read`),
  `test_detach_and_link`, `test_contrast` (`contrast("#000000", "#FFFFFF") == 21.0`, `contrast("#777777",
  "#FFFFFF")` ≈ 4.48), `test_palette_from_image` (a Pillow image of four colour blocks → those four within ±3 per
  channel), `test_create_series_uses_the_default_look` (series.json `look` == config default; README names
  Fraunces and Source Serif 4 for Editorial light), `test_house_rules_round_trip`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `styles.py`, the bundled JSON files and the store changes.
- [ ] **Step 4:** Run the suite (including the old store tests) and `tests/e2e_mcp.py` → PASS.
- [ ] **Step 5:** Commit `Styles: palettes, looks and house rules, inherited from global to poem`.

### Task 8: Styles API

**Files:**
- Modify: `studio/routes_styles.py`, `studio/web.py` (`/api/home` returns `looks`, `palettes` from `Styles`
  instead of `PALETTES`/`FONTS`; `/api/settings` adds `default_look`)
- Test: `tests/test_web.py`

**Interfaces:**
- Produces endpoints: `GET /api/styles` → `{"looks", "palettes", "rules", "default_look", "used": {"palettes":
  {name: [series...]}, "looks": {...}, "fonts": {family: [series...]}}}`; `POST /api/styles/palette` (`{"palette"}`),
  `/api/styles/palette/delete` (`{"name"}`), `/api/styles/look`, `/api/styles/look/delete`, `/api/styles/rules`
  (`{"text"}`), `/api/palette/from-image` (`{"data": base64}` → `{"swatches": [hex]}`), `/api/series/style`
  (`{"name", "look"? , "palette"?, "fonts"?, "detach"?, "link"?}` → the series), `/api/poem/style`
  (`{"id", "look"?, "palette"?, "fonts"?, "clear"?: true}` → the poem).

- [ ] **Step 1: Write the failing tests** (live server): `test_styles_empty_library` (fresh temp library, no
  `Styles/`: 200, 10 looks), `test_save_and_delete_palette_over_http`, `test_series_style_detach_over_http`,
  `test_poem_style_override_and_clear`, `test_palette_from_image_over_http`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run the suite → PASS.
- [ ] **Step 5:** Commit `Styles API`.

### Task 9: The Styles pages

**Files:**
- Create: `studio/static/styles.js`
- Modify: `studio/static/index.html` (right nav: *Styles* · *Info* · *Settings*; load `styles.js` after `app.js`),
  `studio/static/app.js` (`route()`: `#/styles` and `#/styles/(looks|palettes|fonts|rules)`), `studio/static/app.css`

**Interfaces:**
- Consumes: Task 8 endpoints, Task 5–6 font endpoints, `Design.render`/`Design.starter` for look previews.
- Produces: `showStyles(tab)`; reusable `palettePicker(current, onPick)` and `fontPicker(current, onPick, {pinned: string[]})`
  used by Tasks 10 and 14.

Pages (editorial layout like Settings; right-click on cards and rows):
- **Looks:** preview cards, each with a 4:5 sample slide (`Design.starter("page", "45", …)` with the look's fonts and
  palette, generic sample text) and a sample book page (HTML, text font, 10 lines of generic text); actions: *Use as
  default*, *Edit* (palette and the three font roles with `fontPicker`), *Duplicate*, *Delete* (own only).
- **Palettes:** swatch strips with *Edit*, *Duplicate* and *Delete* (own only); the editor dialog: per swatch name, hex field plus colour input, role select, remove;
  *Add swatch*, *Paste colours* (any text; every `#rrggbb` found becomes a swatch), *From an image* (file input →
  `/api/palette/from-image` → swatches to keep), contrast warnings under the strip.
- **Fonts:** a sample-text field (kept in `localStorage`), filters for category and source, one specimen row per
  family (name, category, source, licence, weights and widths, *Used in*); *Add fonts* opens a dialog with tabs
  *Google Fonts* (search, category, results previewed with a `fonts.googleapis.com/css2` link for the visible
  results only, *Add*), *Files* (drop zone and file input), *On this computer* (the system list, with the
  portability note: "Fonts from this computer won't travel with your files.").
- **House rules:** a Markdown editor with preview and *Save*; one line explaining that everything new and Claude
  read them first.
- **Settings** gets a *Default look* row (a select of looks, saved as `default_look`).

- [ ] **Step 1:** Implement the pages.
- [ ] **Step 2:** Browser check on a test server with a scratch library, at 1440×900 and 900×700: every tab
  loads; a palette made from an image saves; a Google font is added (live network) and appears in Fonts; a dropped
  font file is added; *Use as default* changes Settings' default look; no console errors.
- [ ] **Step 3:** Commit `Styles pages: looks, palettes, fonts and house rules`.

### Task 10: Series look, rules and concepts editing; poem style override

**Files:**
- Modify: `studio/static/app.js` (`renderSeries()` Look, Rules and Concepts tabs; poem header ••• menu), `studio/static/app.css`
- Modify: `studio/static/editor.js` (line 62 `fonts()`: the poem's resolved font roles first, then
  `Design.fontNames()`; the font select groups *This series* then categories then *On this computer*)

**Interfaces:**
- Consumes: `POST /api/series/style`, `POST /api/series/update` (`fields.rules`, `fields.concepts` added to
  `update_series`: they write `README.md` and `CONCEPTS.md`), `POST /api/poem/style`, `palettePicker`, `fontPicker`.

- [ ] **Step 1: Write the failing test** in `tests/test_store.py`: `test_update_series_writes_rules_and_concepts`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Extend `update_series`; run → PASS.
- [ ] **Step 4:** Front end. **Look** tab: the resolved look with its source line ("Editorial light · from
  Studio's default" / "own"), look cards to choose, palette (linked name or own swatches, edit), the three font
  roles, *Detach* / *Link to a look…*. **Rules** and **Concepts** tabs: Markdown editor with preview and *Save*.
  Poem ••• menu: *Style…* opens a dialog (look, palette, fonts, or *Use the series' style*).
- [ ] **Step 5:** Browser check: change a series' look, detach it, edit its own palette, link it back; a poem
  override shows in the Design tab's fonts and swatches; the 1.0 series renders unchanged.
- [ ] **Step 6:** Commit `Series look, rules and concepts editable in the app; poem style override`.

### Task 11: Design checks per series

**Files:**
- Modify: `studio/qa.py` (constants become `DEFAULT_CHECKS`; thresholds passed through), `studio/store.py`
  (`update_series` validates `checks`; `series_meta` returns resolved `checks`), `studio/static/design-core.js`
  (`SAFE["916"]` from the poem's checks), `studio/static/app.js` (Rules tab: *Design checks* form)
- Test: `tests/test_qa.py`, `tests/test_store.py`

**Interfaces:**
- Produces: `qa.DEFAULT_CHECKS = {"align": 1.0, "near": 10.0, "phone": 430, "min_phone": 7.0, "story_top": 280,
  "story_bottom": 330}`; `qa.measure(signed, unsigned, size, scale, story=False, checks=None)`; `_columns`,
  `_analyse`, `_legibility` take `checks`; `qa.run()` reads the series' resolved `checks`.
- Validation ranges (`StoreError` naming the field): `align` 0–20, `near` > `align` and ≤ 100, `phone` 200–1200,
  `min_phone` 1–40, `story_top` and `story_bottom` 0–600.
- `INK` stays a module constant (it is a measuring detail, not a design rule).

- [ ] **Step 1: Write the failing tests:** `test_near_miss_threshold_is_per_series` (the existing 3-px near miss
  is flagged with defaults and not with `near=2`), `test_story_safe_zone_is_per_series`, `test_checks_validation`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; the form shows each field with its default beside it and a
  *Reset* per field.
- [ ] **Step 4:** Run the suite → PASS. Browser: the 9:16 guides in the Design tab follow the series' story zone.
- [ ] **Step 5:** Commit `Design checks per series`.

### Task 12: Home

**Files:**
- Create: `studio/home.py`, `studio/static/home.js`, `tests/test_home.py`
- Modify: `studio/web.py` (`/api/home` adds `continue` and `recent`), `studio/static/app.js` (`route()`: `"/"` →
  `showHomePage()`; `"/poems"` → the current `showHome()` renamed `showPoems()`; `setNav("home")`),
  `studio/static/index.html` (nav: *Home* `#/` `data-nav="home"`, *Poems* `#/poems` `data-nav="poems"`; the
  *Series* link moves into the Poems page header; *New poem* button becomes a *New* menu: Poem, Series),
  `studio/static/app.css`

**Interfaces:**
- Produces: `home.SOURCES: list[Callable[[], list[dict]]]` (Plan B appends books); `home.recent(limit=10) -> list[dict]`
  items `{"kind": "poem" | "design" | "series", "title", "where", "when": iso, "href": "#/…", "excerpt"?}` sorted by
  `when` descending, from poem folders' `poem.json`, `drafts/`, `designs/` mtimes; `home.continue_item() -> dict | None`
  (the newest item whose kind is writing (`poem`, later `piece`) or `design`, with `excerpt` = last non-empty line).
- Consumes: `Store.list()`, `Store.designs()`.

- [ ] **Step 1: Write the failing tests:** `test_recent_orders_across_poems_and_designs` (`os.utime` to set times),
  `test_continue_is_the_newest_writing`, `test_home_empty_library` (no `Poems/` folder: `recent() == []`,
  `continue_item() is None`, `GET /api/home` → 200).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `home.py` and the endpoint changes.
- [ ] **Step 4:** Front end `home.js`: *Continue* card (excerpt in the serif, where and when, *Continue*), the
  *New* buttons (Poem, Series; Book and Import arrive with Plan B through `home.SOURCES`-like front-end hooks:
  `window.homeSections = []` that `home.js` renders after the built-in sections), Series rows, Recent list.
  Old `#/` bookmarks now land on Home; `#/poems` is the poems page.
- [ ] **Step 5:** Run the suite → PASS. Browser: Home with the scratch library and with an empty one.
- [ ] **Step 6:** Commit `Home: continue, create, series and recent work`.

### Task 13: Light theme

**Files:**
- Modify: `studio/config.py` (`DEFAULTS["theme"] = "system"`, validated to `system|light|dark`; `refresh()` sets
  `THEME`), `studio/web.py` (`GET /` serves `index.html` with `data-theme="<THEME>"` on `<html>`),
  `studio/static/app.css`, `studio/static/editor.css` (every literal colour becomes a variable),
  `studio/static/app.js` (Settings → *Appearance*: System / Light / Dark, applied immediately),
  `studio/desktop.py` (window `background_color` from the theme: `#F4F2EE` for light, `#141619` otherwise)
- Test: `tests/test_web.py`

**Interfaces:**
- Produces CSS: the existing variables (`--night`, `--room`, `--panel`, `--panel-2`, `--line`, `--line-soft`,
  `--paper`, `--paper-dim`, `--fog`, `--red`, `--red-deep`) plus any new ones needed for the 58 literal colours now
  in `app.css` and `editor.css`; light values under `:root[data-theme="light"]` and
  `@media (prefers-color-scheme: light) { :root[data-theme="system"] {…} }`, with `color-scheme` set to match.
  The design board's pasteboard follows the theme; the artboard shows the design's own colours.

- [ ] **Step 1: Write the failing test** `test_index_carries_the_theme` (config theme `light` → the served page
  contains `data-theme="light"`).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; `grep -cE "#[0-9A-Fa-f]{3,8}\b"` on both CSS files reports
  only the variable definitions.
- [ ] **Step 4:** Run the suite → PASS. Browser: every page (Home, Poems, a poem's Write/Art/Design, Series,
  Styles, Settings, Info, the viewer, menus, dialogs) in light and dark; no unreadable text (spot-check contrast
  of body text ≥ 4.5:1 with the devtools picker).
- [ ] **Step 5:** Commit `Light theme`.

### Task 14: Welcome and examples

**Files:**
- Create: `studio/examples.py`, `studio/static/welcome.js`, `tests/test_examples.py`
- Modify: `studio/web.py` (`/api/settings` adds `"first_run": not config.CONFIG_FILE.exists()` and `"has_examples"`),
  `studio/routes_styles.py` (`POST /api/examples`, `POST /api/examples/remove`), `studio/static/app.js`
  (start: when `first_run`, show the welcome before routing; Settings: *Add examples* / *Remove examples*),
  `studio/static/index.html` (load `welcome.js`)

**Interfaces:**
- Produces: `examples.add(store, styles) -> list[Path]` (idempotent: returns `[]` when the *Examples* series exists);
  `examples.remove(store) -> list[Path]` (moves every series whose `series.json` has `"example": true` to
  `Poems/.trash/`); `examples.EXTRA: list[Callable[[], list[Path]]]` and `examples.EXTRA_REMOVE` (Plan B adds the
  example book).
- The *Examples* series: look *Editorial light*, `"example": true`, tagline "Two short poems to try Studio with.",
  a README with three generic rules, and two poems written for Studio (below), each with one design made with
  `Design`'s *page* starter equivalent on the server (a text layer with the poem and a name layer).

```
Morning, Unfinished
The kettle starts before I do.
The window holds a grey it hasn't named.
I write one line and leave it open,
like a door for the day to come through.

What the River Keeps
Stones, mostly. A shoe.
The shape of every bridge, upside down.
Whatever you tell it,
it carries a little further.
```

- Welcome (3 steps in one overlay, *Skip* on each): **Where your work lives** (folder field, *Choose…* via
  `pywebview.api.pick_folder` when available, default `~/Studio`); **Your name** (signature, optional);
  **A starting look** (look cards from Task 9). *Finish* posts `/api/settings` with `library`, `signature`,
  `default_look`, `create: true`, then `/api/examples` when *Add examples* (checked by default) is on.

- [ ] **Step 1: Write the failing tests:** `test_add_examples` (series, 2 poems, a design each, flag set),
  `test_add_examples_twice_adds_nothing`, `test_remove_examples_moves_them_to_the_trash`,
  `test_first_run_flag` (live server without a config file → `first_run` true; after `POST /api/settings` → false).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run the suite → PASS.
- [ ] **Step 5:** Browser check with `STUDIO_CONFIG` pointing at a missing file and an empty library: the
  welcome appears, *Finish* creates the library and examples, Home shows them; *Remove examples* empties it again;
  *Skip* everywhere still lands on a working Home.
- [ ] **Step 6:** Commit `Welcome and examples for a fresh install`.

### Task 15: Claude's tools follow the styles

**Files:**
- Modify: `studio/mcp_server.py` (`read_poem` includes `"style"`; `get_rules` starts with `# House rules` when
  `Styles/rules.md` has text; `save_design` rejects unknown fonts; `DESIGN_DOC` lists how fonts are chosen),
  `tests/e2e_mcp.py`
- Test: `tests/test_mcp_tools.py`

**Interfaces:**
- Produces: `mcp_server.unknown_fonts(design: dict) -> list[str]` (families of text layers not in `fonts.registry()`);
  `save_design` raises `ToolError("Unknown fonts: X. Available: <comma list>")`.

- [ ] **Step 1: Write the failing tests:** `test_unknown_fonts`, `test_get_rules_starts_with_house_rules`
  (call the tool function through `anyio.run` with a temp library).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; extend `e2e_mcp.py` to save a design with an unknown font and
  expect the error. **Step 4:** Run the suite and `python tests/e2e_mcp.py` → PASS.
- [ ] **Step 5:** Commit `MCP tools use the styles and house rules`.

### Task 16: Release 1.1.0

**Files:**
- Modify: `studio/__init__.py` (`__version__ = "1.1.0"`), `pyproject.toml` (version), `README.md` (Styles,
  fonts, updates, light theme, welcome), `docs/DESIGN.md` (styles, fonts registry, updater, route tables),
  `studio/static/app.js` Info page (Styles and Updates sections), `packaging/studio.spec` (hidden imports
  `studio.routes_update`, `studio.routes_styles`, `brotli`)

- [ ] **Step 1:** Update the docs and version.
- [ ] **Step 2:** Run the suite, `python tests/e2e_mcp.py`, and `pyinstaller packaging/studio.spec --noconfirm`;
  then `dist/Studio/studio-cli.exe version` prints `1.1.0` and the frozen MCP renders a design in Literata.
- [ ] **Step 3:** Commit `Studio 1.1.0`. Do not tag or push; the release is the author's call.
