"""A series' render engine: wraps Poems/<Series>/_kit/build.py without changing it.

build.py stays the single source of truth for the page, the PNG names and folders, the Chrome
screenshot and the contact sheet. Studio imports it (fresh whenever the file changes) and adds
parallel shooting, partial renders and text-hidden "plates" for QA.
"""
import contextlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue

FORMAT_ALIASES = {
    "11": "11", "1:1": "11", "1x1": "11", "x": "11", "square": "11",
    "45": "45", "4:5": "45", "4x5": "45", "feed": "45", "instagram feed": "45",
    "916": "916", "9:16": "916", "9x16": "916", "story": "916", "instagram story": "916",
}
FORMAT_LABEL = {"11": "1:1", "45": "4:5", "916": "9:16"}

# QA plate: the same page with every letter made invisible. Fields, bars, rules and lines stay.
PLATE_CSS = ("<style>.slide,.slide *{color:transparent!important;-webkit-text-fill-color:transparent!important;"
             "text-shadow:none!important;text-decoration-color:transparent!important}</style>")


class KitError(Exception):
    pass


def format_key(value):
    if value is None:
        return None
    key = FORMAT_ALIASES.get(str(value).strip().lower())
    if not key:
        raise KitError(f"unknown format {value!r}; use 1:1, 4:5 or 9:16")
    return key


_modules = {}
_lock = threading.Lock()


def _load(build_py: Path):
    mtime = build_py.stat().st_mtime
    with _lock:
        hit = _modules.get(build_py)
        if hit and hit[0] == mtime:
            return hit[1]
        spec = importlib.util.spec_from_file_location(f"studio_kit_{len(_modules)}_{int(mtime)}", build_py)
        mod = importlib.util.module_from_spec(spec)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                spec.loader.exec_module(mod)
        except BaseException as e:  # noqa: BLE001 — a broken kit must not take Studio down
            raise KitError(f"could not load {build_py}: {e}") from None
        _modules[build_py] = (mtime, mod)
        return mod


def poem_on_page(page: Path):
    """The poem a built preview page was made from (build.py inlines it as `const POEM=`)."""
    if not page.exists():
        return None
    text = page.read_text(encoding="utf-8")
    i = text.find("const POEM=")
    if i < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(text, i + len("const POEM="))[0]
    except ValueError:
        return None


class Kit:
    def __init__(self, series_dir: Path):
        self.series_dir = Path(series_dir)
        self.dir = self.series_dir / "_kit"
        self.build_py = self.dir / "build.py"

    # ——— the engine ———
    @property
    def mod(self):
        if not self.build_py.exists():
            raise KitError(f"{self.series_dir.name} has no render engine ({self.build_py})")
        return _load(self.build_py)

    def formats(self):
        return list(self.mod.RATIOS)  # build.py's order: 4:5, 1:1, 9:16

    def size(self, r):
        _, w, h, _, _ = self.mod.RATIOS[r]
        return w, h

    def scale(self):
        return self.mod.SCALE

    # ——— concepts ———
    def concept_ids(self):
        return sorted(p.stem for p in (self.dir / "concepts").glob("*.js"))

    def concepts(self):
        out = []
        for f in sorted((self.dir / "concepts").glob("*.js")):
            text = f.read_text(encoding="utf-8")
            doc = re.match(r"\s*/\*(.*?)\*/", text, re.S)
            name = re.search(r'name\s*:\s*"([^"]+)"', text)
            out.append({"id": f.stem, "name": name.group(1) if name else f.stem,
                        "doc": " ".join(doc.group(1).split()) if doc else ""})
        return out

    def slide_names(self, poem):
        return self.mod.concept_names(poem)

    # ——— files (named exactly as build.py names them) ———
    def page(self, folder: Path, poem):
        return Path(folder) / f"{poem['slug']}.html"

    def sheet_path(self, folder: Path, poem):
        return Path(folder) / f"{poem['slug']}-carousel-preview.png"

    def png(self, folder: Path, poem, n, r, signed=True):
        tag, _, _, sub_r, _ = self.mod.RATIOS[r]
        _, sub_v, suffix = next(v for v in self.mod.VARIANTS if (v[0] == "1") == bool(signed))
        concept = poem["slides"][n - 1]["concept"]
        return Path(folder) / sub_r / sub_v / f"{poem['slug']}-{tag}-{n}-{concept}{suffix}.png"

    def tag(self, r):
        return self.mod.RATIOS[r][0]

    # ——— rendering ———
    def check(self, poem):
        slides = poem.get("slides") or []
        if not slides:
            raise KitError("this poem has no slides yet; set them with set_slides first")
        if not poem.get("lines"):
            raise KitError("this poem has no text yet")
        known = set(self.concept_ids())
        unknown = sorted({s.get("concept") for s in slides} - known)
        if unknown:
            raise KitError(f"unknown concept(s): {', '.join(map(str, unknown))}; built: {', '.join(sorted(known))}")

    def build_page(self, folder: Path, poem):
        self.check(poem)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                return self.mod.build_html(poem, self.page(folder, poem))
        except BaseException as e:  # noqa: BLE001 — build.py exits on errors
            raise KitError(f"building the page failed: {e}") from None

    def shoot_all(self, jobs, workers=4):
        """jobs: [(page, n, r, sig '1'|'0', out)] -> shot in parallel, one Chrome profile per worker."""
        if not jobs:
            return []
        mod, pool = self.mod, Queue()
        from . import config
        if config.CHROME and (config.SETTINGS.get("chrome") or not Path(str(getattr(mod, "CHROME", ""))).exists()):
            mod.CHROME = config.CHROME
        if not Path(str(getattr(mod, "CHROME", ""))).exists():
            raise KitError("no Chrome, Chromium or Edge found to render with; set one in Studio's settings")
        dirs = [Path(tempfile.mkdtemp(prefix="studio-chrome-")) for _ in range(max(1, min(workers, len(jobs))))]
        for d in dirs:
            pool.put(d)

        def run(job):
            page, n, r, sig, out = job
            profile = pool.get()
            try:
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                with contextlib.redirect_stdout(sys.stderr):
                    mod.shoot(Path(page), n, r, sig, Path(out), profile)
                return out
            except BaseException as e:  # noqa: BLE001 — build.py exits on errors
                raise KitError(f"{Path(out).name}: {e}") from None
            finally:
                pool.put(profile)

        done, errors = [], []
        try:
            with ThreadPoolExecutor(len(dirs)) as ex:
                for fut in [ex.submit(run, j) for j in jobs]:
                    try:
                        done.append(fut.result())
                    except Exception as e:  # noqa: BLE001
                        errors.append(str(e))
        finally:
            for d in dirs:
                shutil.rmtree(d, ignore_errors=True)
        if errors:
            raise KitError("; ".join(errors))
        return done

    def render(self, folder: Path, poem, slides=None, formats=None, signed=None, workers=4):
        """Render the chosen slides (1-based numbers), formats (keys) and name variants.

        Rebuilds the preview page every time, then the contact sheet from every signed PNG that exists.
        """
        folder = Path(folder)
        n_all = list(range(1, len(poem.get("slides") or []) + 1))
        ns = [n for n in n_all if not slides or n in slides]
        rs = [r for r in self.formats() if not formats or r in formats]
        sigs = [v[0] for v in self.mod.VARIANTS if signed is None or (v[0] == "1") == bool(signed)]
        if slides and not ns:
            raise KitError(f"slide must be 1–{len(n_all)}")
        page = self.build_page(folder, poem)
        jobs = [(page, n, r, sig, self.png(folder, poem, n, r, sig == "1")) for r in rs for sig in sigs for n in ns]
        shot = self.shoot_all(jobs, workers)
        return {"page": page, "images": shot, "sheet": self.contact_sheet(folder, poem)}

    def contact_sheet(self, folder: Path, poem):
        rows, names = {}, self.slide_names(poem)
        for r in self.formats():
            paths = [self.png(folder, poem, n, r, True) for n in range(1, len(poem["slides"]) + 1)]
            if paths and all(p.exists() for p in paths):
                rows[r] = list(zip(names, paths))
        if not rows:
            return None
        with contextlib.redirect_stdout(sys.stderr):
            return self.mod.contact_sheet(f"{poem['title']} — carousel", rows, self.sheet_path(folder, poem))

    # ——— QA plates ———
    def plates(self, folder: Path, poem, wanted, cache: Path, workers=4):
        """Text-hidden twins of slides: {(n, r, signed): png}. Re-shot when the preview page changes.

        Each name variant gets its own plate: concepts may lay out differently without the name."""
        page = self.page(folder, poem)
        if not page.exists():
            raise KitError("not rendered yet")
        cache.mkdir(parents=True, exist_ok=True)
        plate_page = cache / f"{poem['slug']}-plate.html"
        if not plate_page.exists() or plate_page.stat().st_mtime < page.stat().st_mtime:
            html = page.read_text(encoding="utf-8").replace("</head>", PLATE_CSS + "</head>", 1)
            plate_page.write_text(html, encoding="utf-8")
        out, jobs = {}, []
        for n, r, signed in wanted:
            png = cache / f"plate-{self.tag(r)}-{n}{'' if signed else '-noname'}.png"
            out[(n, r, signed)] = png
            if not png.exists() or png.stat().st_mtime < plate_page.stat().st_mtime:
                jobs.append((plate_page, n, r, "1" if signed else "0", png))
        self.shoot_all(jobs, workers)
        return out
