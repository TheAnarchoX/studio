"""Poems on disk. The Art folder is the database: every read goes to the files, every write is a file.

A series is a folder in Poems/ with a series.json or a render engine (_kit/build.py). A poem is a folder in a series
with a poem.json. Poems are named by id ("<Series>/<Poem folder>"), or loosely by folder, title or slug.
"""
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config
from .kit import FORMAT_LABEL, Kit, KitError, poem_on_page

STATUSES = ["draft", "ready", "in review", "approved", "exported"]
DRAFT_STAMP = "%Y-%m-%dT%H%M"
WRITING_NOTES = "writing-notes.md"   # not notes.md: on Windows that is the same file as NOTES.md
KEY_ORDER = ["number", "title", "slug", "author", "status", "lines", "slides"]
SERIES_FILE = "series.json"
SERIES_KEYS = ["name", "tagline", "description", "signature", "look", "palette", "fonts", "formats", "created", "checks", "example"]
# The design checks (qa.py measures with them): defaults and the range each may take, (low, high).
CHECK_DEFAULTS = {"align": 1.0, "near": 10.0, "phone": 430, "min_phone": 7.0, "story_top": 280, "story_bottom": 330}
CHECK_RANGES = {"align": (0, 20), "near": (0, 100), "phone": (200, 1200), "min_phone": (1, 40),
                "story_top": (0, 600), "story_bottom": (0, 600)}


DESIGN_FORMATS = {"11": (1080, 1080, "1x1"), "45": (1080, 1350, "4x5"), "916": (1080, 1920, "9x16")}
SERIES_FORMATS = {"1:1": "11", "4:5": "45", "9:16": "916"}    # a series' formats, as the designs name them
DESIGN_TYPES = {"text", "rect", "ellipse", "line", "shape", "path"}
RENDERS = "Design renders"   # not "Designs": on Windows that is the same folder as designs/


class StoreError(Exception):
    pass


# ——— helpers ———
def slugify(title):
    s = re.sub(r"['’]", "", title.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "untitled"


def folder_name(title):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip().rstrip(". ")


def dump_poem(poem):
    """poem.json in the hand-made style: one key per line, one slide per line."""
    keys = [k for k in KEY_ORDER if k in poem] + [k for k in poem if k not in KEY_ORDER]
    rows = []
    for k in keys:
        v = poem[k]
        if k == "slides" and isinstance(v, list) and v:
            val = "[\n" + ",\n".join("    " + json.dumps(s, ensure_ascii=False) for s in v) + "\n  ]"
        else:
            val = json.dumps(v, ensure_ascii=False)
        rows.append(f"  {json.dumps(k)}: {val}")
    return "{\n" + ",\n".join(rows) + "\n}\n"


def write_text(path: Path, text: str):
    """Atomic write; retries briefly because Windows refuses to replace a file someone is reading. The temp file is
    this call's own (process and thread), so two requests writing one file at once don't share it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            if attempt == 19:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


def read_text(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def draft_text(title, lines):
    return f"# {title}\n\n" + "\n".join(lines) + "\n"


def parse_draft(text):
    rows = text.replace("\r\n", "\n").split("\n")
    title = None
    if rows and rows[0].startswith("# "):
        title, rows = rows[0][2:].strip(), rows[1:]
    return title, clean_lines("\n".join(rows))


def clean_lines(text):
    rows = [r.rstrip() for r in text.replace("\r\n", "\n").split("\n")]
    while rows and not rows[0]:
        rows.pop(0)
    while rows and not rows[-1]:
        rows.pop()
    return rows


def iso(ts):
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


class Store:
    def __init__(self, root=None, cache=None):
        self.root = Path(root or config.POEMS).resolve()
        self.cache = Path(cache or config.CACHE)
        self._fonts_seen = None     # (signature of the design files, fonts they use), see fonts_in_designs
        self.styles = styles.Styles(self.root.parent)   # the library: Poems/ and Styles/ side by side

    # ——— finding things ———
    def series_dirs(self):
        """A series is a folder in Poems/ with a series.json or a render engine (_kit/build.py)."""
        if not self.root.exists():
            return []
        return [d for d in sorted(self.root.iterdir()) if d.is_dir() and not d.name.startswith((".", "_"))
                and ((d / SERIES_FILE).exists() or (d / "_kit" / "build.py").exists())]

    def series_dir(self, name=None):
        dirs = self.series_dirs()
        if name is None:
            if len(dirs) == 1:
                return dirs[0]
            raise StoreError("which series? " + ", ".join(d.name for d in dirs))
        for d in dirs:
            if d.name.lower() == str(name).strip().lower():
                return d
        raise StoreError(f"no series {name!r}; series: " + ", ".join(d.name for d in dirs))

    def poem_dirs(self, series=None):
        for s in self.series_dirs():
            if series and s.name.lower() != series.lower():
                continue
            for d in sorted(s.iterdir()):
                if d.is_dir() and not d.name.startswith(("_", ".")) and (d / "poem.json").exists():
                    yield d

    def pid(self, folder: Path):
        return f"{folder.parent.name}/{folder.name}"

    def resolve(self, ref) -> Path:
        if isinstance(ref, Path):
            ref = ref.resolve()
            if ref.parent.parent == self.root and (ref / "poem.json").exists():
                return ref
            raise StoreError(f"not a poem folder: {ref}")
        ref = str(ref or "").strip().replace("\\", "/").strip("/")
        if not ref:
            raise StoreError("name a poem")
        dirs = list(self.poem_dirs())
        for d in dirs:
            if self.pid(d).lower() == ref.lower():
                return d
        key = ref.split("/")[-1].lower()
        hits = []
        for d in dirs:
            try:
                meta = self.load(d)
            except StoreError:
                meta = {}
            names = {d.name.lower(), str(meta.get("title", "")).lower(), str(meta.get("slug", "")).lower()}
            if key in names:
                hits.append(d)
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise StoreError(f"{ref!r} matches several poems: " + ", ".join(self.pid(d) for d in hits))
        raise StoreError(f"no poem {ref!r}; poems: " + (", ".join(self.pid(d) for d in dirs) or "none yet"))

    def kit(self, folder: Path):
        return Kit(folder.parent)

    # ——— poem.json ———
    def load(self, folder: Path):
        try:
            return json.loads((folder / "poem.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise StoreError(f"{self.pid(folder)}/poem.json can't be read: {e}") from None

    def save(self, folder: Path, poem):
        write_text(folder / "poem.json", dump_poem(poem))

    def update(self, folder: Path, change):
        poem = self.load(folder)
        change(poem)
        self.save(folder, poem)
        return poem

    def status(self, folder: Path, poem):
        s = poem.get("status")
        if s in STATUSES:
            return s
        return "in review" if (folder / f"{poem.get('slug', '')}.html").exists() else "draft"

    # ——— reading ———
    def summary(self, folder: Path):
        poem = self.load(folder)
        lines = poem.get("lines") or []
        thumb = None
        try:
            kit = self.kit(folder)
            if poem.get("slides") and kit.build_py.exists():
                p = kit.png(folder, poem, 1, "45", True)
                thumb = self.rel(p) if p.exists() else None
        except (KitError, KeyError, IndexError):
            pass
        return {"id": self.pid(folder), "series": folder.parent.name, "folder": folder.name,
                "title": poem.get("title") or folder.name, "number": poem.get("number"),
                "status": self.status(folder, poem), "first_line": lines[0] if lines else "",
                "line_count": len(lines), "lines": lines[:12], "slides": [s.get("concept") for s in poem.get("slides") or []],
                "updated": iso(self.stamp(folder)), "thumb": thumb}

    def list(self, series=None, status=None):
        out = []
        for d in self.poem_dirs(series):
            try:
                s = self.summary(d)
            except StoreError as e:
                s = {"id": self.pid(d), "series": d.parent.name, "folder": d.name, "title": d.name,
                     "status": "draft", "error": str(e)}
            if status and s["status"] != status:
                continue
            out.append(s)
        out.sort(key=lambda s: (s["series"], s.get("number") is None, s.get("number") or 0, s["title"]))
        return out

    def drafts(self, folder: Path):
        out = []
        d = folder / "drafts"
        for f in sorted(d.glob("*.md"), reverse=True) if d.exists() else []:
            try:
                when = datetime.strptime(f.stem, DRAFT_STAMP)
            except ValueError:
                when = datetime.fromtimestamp(f.stat().st_mtime)
            title, lines = parse_draft(f.read_text(encoding="utf-8"))
            out.append({"name": f.name, "when": when.isoformat(timespec="minutes"),
                        "title": title, "lines": lines})
        return out

    def art(self, folder: Path, poem):
        """What's been rendered, in posting order, per format: signed and unsigned image paths."""
        kit = self.kit(folder)
        slides = poem.get("slides") or []
        page = kit.page(folder, poem) if poem.get("slug") else None
        made = poem_on_page(page) if page else None
        fields = ("title", "author", "lines", "slides")
        stale = bool(made) and any(made.get(k) != poem.get(k) for k in fields)
        names = kit.slide_names(poem) if slides else []
        formats = {}
        for r in kit.formats():
            row = []
            for n in range(1, len(slides) + 1):
                cell = {"n": n, "concept": slides[n - 1].get("concept"), "name": names[n - 1]}
                for key, signed in (("signed", True), ("unsigned", False)):
                    p = kit.png(folder, poem, n, r, signed)
                    cell[key] = self.rel(p) if p.exists() else None
                    cell[key + "_v"] = int(p.stat().st_mtime) if p.exists() else None
                row.append(cell)
            w, h = kit.size(r)
            formats[r] = {"label": FORMAT_LABEL.get(r, r), "w": w, "h": h, "slides": row}
        sheet = kit.sheet_path(folder, poem) if poem.get("slug") else None
        return {"formats": formats, "order": kit.formats(),
                "page": self.rel(page) if page and page.exists() else None,
                "sheet": self.rel(sheet) if sheet and sheet.exists() else None,
                "rendered": bool(made), "stale": stale}

    def read(self, ref):
        folder = self.resolve(ref)
        poem = self.load(folder)
        try:
            art = self.art(folder, poem) if self.kit(folder).build_py.exists() else {"no_kit": True}
        except (KitError, KeyError, IndexError) as e:
            art = {"error": str(e)}
        qa = read_text(folder / "qa.json")
        style = self.styles.resolve(self.style_levels(self.series_json(folder.parent), poem))
        return {"id": self.pid(folder), "series": folder.parent.name, "folder": folder.name,
                "path": str(folder), "title": poem.get("title") or folder.name, "slug": poem.get("slug"),
                "number": poem.get("number"), "author": poem.get("author"),
                "status": self.status(folder, poem), "status_set": poem.get("status") in STATUSES,
                "lines": poem.get("lines") or [], "slides": poem.get("slides") or [],
                "drafts": self.drafts(folder), "writing_notes": read_text(folder / WRITING_NOTES) or "",
                "brief": read_text(folder / "BRIEF.md"), "notes": read_text(folder / "NOTES.md"),
                "art": art, "qa": json.loads(qa) if qa else None, "designs": self.designs(folder),
                "series_info": {k: v for k, v in self.series_meta(folder.parent).items()
                                if k in ("name", "tagline", "palette", "fonts", "signature", "has_kit",
                                         "look", "palette_from", "palette_linked", "font_roles", "checks", "formats")},
                "style": style, "stamp": self.stamp(folder)}

    def stamp(self, folder: Path = None):
        """A change marker: the newest modification time in a poem folder (or across all poems)."""
        newest = 0.0
        if folder is None:
            for d in self.poem_dirs():
                newest = max(newest, d.stat().st_mtime, (d / "poem.json").stat().st_mtime)
            return newest
        for base, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            newest = max([newest, os.stat(base).st_mtime] + [os.stat(os.path.join(base, f)).st_mtime
                                                            for f in files if not f.startswith(".")])
        return newest

    def rel(self, path: Path):
        return Path(path).resolve().relative_to(self.root).as_posix()

    def file(self, rel):
        """A file inside Poems/, for the web view. Refuses anything outside."""
        p = (self.root / rel).resolve()
        if self.root not in p.parents or not p.is_file():
            raise StoreError("not found")
        return p

    # ——— designs (the visual editor's files) ———
    def design_formats(self, folder: Path):
        """The design formats ("11", "45", "916") the poem's series shows and exports, in the usual order."""
        want = self.series_json(folder.parent).get("formats")
        keys = [SERIES_FORMATS[f] for f in want if f in SERIES_FORMATS] if isinstance(want, list) else []
        return [k for k in DESIGN_FORMATS if k in keys] or list(DESIGN_FORMATS)

    def designs(self, folder: Path):
        out = []
        d = folder / "designs"
        allowed = self.design_formats(folder)
        for f in sorted(d.glob("*.json")) if d.exists() else []:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            fmt = data.get("format", "45")
            exports = {}
            for k, (_, _, tag) in DESIGN_FORMATS.items():
                if k not in allowed:
                    continue
                row = {}
                for key, suffix in (("signed", ""), ("unsigned", "-noname")):
                    png = folder / RENDERS / f.stem / f"{f.stem}-{tag}{suffix}.png"
                    if png.exists():
                        row[key], row[key + "_v"] = self.rel(png), int(png.stat().st_mtime)
                if row:
                    exports[k] = row
            out.append({"slug": f.stem, "name": data.get("name") or f.stem, "format": fmt,
                        "updated": iso(f.stat().st_mtime), "elements": len(data.get("elements") or []),
                        "exports": exports})
        return out

    def read_design(self, ref, slug):
        folder = self.resolve(ref)
        f = folder / "designs" / f"{slugify(str(slug))}.json"
        if not f.exists():
            raise StoreError(f"no design {slug!r}; designs: " + (", ".join(x["slug"] for x in self.designs(folder))
                                                                  or "none yet"))
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            raise StoreError(f"design {slug!r} can't be read: {e}") from None

    def save_design(self, ref, design, slug=None):
        """Write designs/<slug>.json. A new design (no slug) gets one from its name, made unique."""
        folder = self.resolve(ref)
        if not isinstance(design, dict) or not isinstance(design.get("elements"), list):
            raise StoreError("a design is {\"name\", \"format\", \"background\", \"elements\": [...]}")
        if str(design.get("format", "45")) not in DESIGN_FORMATS:
            raise StoreError("format must be 11, 45 or 916 (1:1, 4:5, 9:16)")
        for i, e in enumerate(design["elements"], 1):
            if not isinstance(e, dict) or e.get("type") not in DESIGN_TYPES:
                raise StoreError(f"element {i}: type must be one of {', '.join(sorted(DESIGN_TYPES))}")
        design = {**design, "format": str(design.get("format", "45")), "name": str(design.get("name") or "Untitled")}
        seen = set()
        for i, e in enumerate(design["elements"]):   # every layer needs its own id (Claude may leave them out)
            if not e.get("id") or e["id"] in seen:
                e["id"] = f"e{int(time.time() * 1000):x}{i}"
            seen.add(e["id"])
        ddir = folder / "designs"
        if slug:
            slug = slugify(str(slug))
        else:
            base = slugify(design["name"])
            slug, n = base, 2
            while (ddir / f"{slug}.json").exists():
                slug, n = f"{base}-{n}", n + 1
        write_text(ddir / f"{slug}.json", json.dumps(design, ensure_ascii=False, indent=1) + "\n")
        return slug

    def delete_design(self, ref, slug):
        """Moves the design to designs/.trash (nothing is destroyed)."""
        folder = self.resolve(ref)
        f = folder / "designs" / f"{slugify(str(slug))}.json"
        if not f.exists():
            raise StoreError(f"no design {slug!r}")
        trash = folder / "designs" / ".trash"
        trash.mkdir(exist_ok=True)
        os.replace(f, trash / f"{f.stem}-{datetime.now().strftime('%Y%m%dT%H%M%S')}.json")

    def save_export(self, ref, slug, fmt, signed, png: bytes):
        folder = self.resolve(ref)
        slug = slugify(str(slug))
        if fmt not in DESIGN_FORMATS:
            raise StoreError("unknown format")
        if not png.startswith(b"\x89PNG"):
            raise StoreError("not a PNG")
        out = folder / RENDERS / slug / f"{slug}-{DESIGN_FORMATS[fmt][2]}{'' if signed else '-noname'}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f".{out.name}.tmp")
        tmp.write_bytes(png)
        os.replace(tmp, out)
        return out

    # ——— stamps: reusable pieces per series (Poems/<Series>/stamps/<slug>.json) ———
    def stamps(self, series):
        d = self.series_dir(series) / "stamps"
        out = []
        for f in sorted(d.glob("*.json")) if d.exists() else []:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            out.append({"slug": f.stem, "name": data.get("name") or f.stem, "w": data.get("w", 0), "h": data.get("h", 0),
                        "elements": data.get("elements") or []})
        return out

    def save_stamp(self, series, name, elements, w, h):
        if not isinstance(elements, list) or not elements:
            raise StoreError("a stamp needs at least one layer")
        for i, e in enumerate(elements, 1):
            if not isinstance(e, dict) or e.get("type") not in DESIGN_TYPES:
                raise StoreError(f"layer {i} isn't something a stamp can hold")
        d = self.series_dir(series) / "stamps"
        base, n = slugify(str(name or "stamp")), 2
        slug = base
        while (d / f"{slug}.json").exists():
            slug, n = f"{base}-{n}", n + 1
        write_text(d / f"{slug}.json", json.dumps({"name": str(name or "Stamp").strip()[:60], "w": float(w or 0), "h": float(h or 0),
                                                   "elements": elements}, ensure_ascii=False, indent=1) + "\n")
        return slug

    def delete_stamp(self, series, slug):
        d = self.series_dir(series) / "stamps"
        f = d / f"{slugify(str(slug))}.json"
        if not f.exists():
            raise StoreError("no such stamp")
        (d / ".trash").mkdir(exist_ok=True)
        os.replace(f, d / ".trash" / f"{f.stem}-{datetime.now().strftime('%Y%m%dT%H%M%S')}.json")

    # ——— series ———
    def series_json(self, d: Path):
        """series.json as it is on disk ({} when there is none). Reading never rewrites it."""
        f = d / SERIES_FILE
        if not f.exists():
            return {}
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            raise StoreError(f"{d.name}/{SERIES_FILE} can't be read: {e}") from None
        return meta if isinstance(meta, dict) else {}

    @staticmethod
    def style_levels(series: dict, poem: dict = None):
        """The levels a work's style is resolved through, global first."""
        levels = [("global", {"look": config.DEFAULT_LOOK}), ("series", series)]
        return levels + [("poem", poem)] if poem is not None else levels

    @staticmethod
    def series_checks(meta):
        """The series' own design checks from series.json (known keys with numbers only)."""
        own = meta.get("checks")
        return {k: v for k, v in own.items() if k in CHECK_DEFAULTS and isinstance(v, (int, float))
                and not isinstance(v, bool)} if isinstance(own, dict) else {}

    def _checks(self, meta, given):
        """The series' checks after applying `given` (a number sets one, None resets it); validated."""
        if not isinstance(given, dict):
            raise StoreError("checks must be an object")
        own = self.series_checks(meta)
        for k, v in given.items():
            if k not in CHECK_DEFAULTS:
                raise StoreError(f"unknown check {k!r}; checks: " + ", ".join(CHECK_DEFAULTS))
            if v is None:
                own.pop(k, None)
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
                raise StoreError(f"check {k} must be a number")
            lo, hi = CHECK_RANGES[k]
            if not lo <= v <= hi:
                raise StoreError(f"check {k} must be between {lo} and {hi}")
            own[k] = v
        both = {**CHECK_DEFAULTS, **own}
        if both["near"] <= both["align"]:
            raise StoreError(f"Near misses ({both['near']:g} px) must be larger than the alignment tolerance "
                             f"({both['align']:g} px); near can be up to {CHECK_RANGES['near'][1]}.")
        return own or None

    def series_meta(self, d: Path):
        meta = self.series_json(d)
        f = d / SERIES_FILE
        style = self.styles.resolve(self.style_levels(meta))
        roles = style["fonts"]
        families = dict.fromkeys(roles[r]["family"] for r in styles.FONT_ROLES if r in roles)
        return {"name": d.name, "tagline": meta.get("tagline", ""), "description": meta.get("description", ""),
                "signature": meta.get("signature", config.SIGNATURE), "look": style["look"],
                "palette": style["palette"]["swatches"], "palette_from": style["palette"]["from"],
                "palette_linked": style["palette"]["linked"], "font_roles": roles,
                "checks": {**CHECK_DEFAULTS, **self.series_checks(meta)},
                "fonts": [{"family": fam} for fam in families],
                "formats": meta.get("formats") or ["1:1", "4:5", "9:16"], "created": meta.get("created"),
                "has_file": f.exists(), "has_kit": (d / "_kit" / "build.py").exists(),
                "has_rules": (d / "README.md").exists(), "has_concepts": (d / "CONCEPTS.md").exists()}

    def series_list(self, poems=None):
        out = []
        poems = self.list() if poems is None else poems
        for d in self.series_dirs():
            m = self.series_meta(d)
            mine = [p for p in poems if p["series"] == d.name]
            counts = {}
            for p in mine:
                counts[p["status"]] = counts.get(p["status"], 0) + 1
            m.update({"poems": len(mine), "by_status": counts,
                      "covers": [p["thumb"] for p in mine if p.get("thumb")][:4],
                      "updated": max([p["updated"] for p in mine if p.get("updated")], default=None)})
            out.append(m)
        return out

    def series_read(self, name):
        d = self.series_dir(name)
        m = self.series_meta(d)
        poems = self.list(d.name)
        m.update({"rules": read_text(d / "README.md"), "concepts": read_text(d / "CONCEPTS.md"),
                  "style": self.styles.resolve(self.style_levels(self.series_json(d))),
                  "poems": poems, "stamp": self.stamp_series(d)})
        return m

    def stamp_series(self, d: Path):
        newest = [d.stat().st_mtime] + [(d / f).stat().st_mtime for f in (SERIES_FILE, "README.md", "CONCEPTS.md")
                                        if (d / f).exists()]
        return max(newest + [self.stamp(p) for p in self.poem_dirs(d.name)])

    def write_series(self, d: Path, meta):
        keep = {k: meta[k] for k in SERIES_KEYS if meta.get(k) not in (None, "")}
        keep["name"] = d.name
        write_text(d / SERIES_FILE, json.dumps(keep, ensure_ascii=False, indent=2) + "\n")

    def create_series(self, name, tagline="", palette=None, description="", look=None):
        """A new series following a look (the default look unless one is named); a palette, when given, is linked
        by name (or kept as the series' own when it is a list of swatches)."""
        name = " ".join(str(name or "").split())
        folder = folder_name(name)
        if not folder:
            raise StoreError("give the series a name")
        d = self.root / folder
        if d.exists():
            raise StoreError(f"{folder} already exists in Poems")
        look = self.styles.look(look)["name"] if look else config.DEFAULT_LOOK
        pal = self._palette(palette)
        tagline = str(tagline or "").strip()
        try:
            d.mkdir(parents=True)          # not exist_ok: when another call has just made it, this one stops here
        except FileExistsError:
            raise StoreError(f"{folder} already exists in Poems") from None
        try:
            self.write_series(d, {"tagline": tagline, "description": str(description or "").strip(),
                                  "signature": config.SIGNATURE, "look": look, "palette": pal,
                                  "formats": ["1:1", "4:5", "9:16"], "created": datetime.now().date().isoformat()})
            meta = self.series_meta(d)
            colours = ", ".join(f"{c.get('name') or c['hex']} `{c['hex']}`" for c in meta["palette"])
            roles = meta["font_roles"]
            families = " and ".join(dict.fromkeys(roles[r]["family"] for r in ("display", "text") if r in roles))
            house = self.styles.rules().strip()        # the library's house rules come first, as Claude reads them
            write_text(d / "README.md", f"# {folder}\n\n{tagline or 'A new series of poems.'}\n\n"
                       + (f"## House rules\n\n{house}\n\n" if house else "")
                       + "## The rules\n\n"
                       f"- **Palette:** {colours}.\n"
                       f"- **Type:** {families}.\n"
                       "- **Words:** only the poem's own words and the name.\n"
                       + (f"- **Signature:** \"{config.SIGNATURE}\". " if config.SIGNATURE else "- **Signature:** the poet's name. ")
                       + "Every image also exists unsigned, with an identical layout.\n"
                       "- **Formats:** 1:1 for X, 4:5 for the Instagram feed, 9:16 for stories, rendered at 2x.\n")
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)       # this call made the folder a moment ago: nothing of anyone's is in it
            raise
        return self.series_read(folder)

    def update_series(self, name, fields):
        """Changes series.json: tagline, description, signature, formats (a non-empty subset of 1:1, 4:5, 9:16); look, palette (a name or swatches) and fonts (per
        role), each None to follow the level above again; detach (the style in effect becomes the series' own) or
        link ("<look>": follow that look, dropping the own palette and fonts). "rules" and "concepts" are the
        Markdown of README.md and CONCEPTS.md; series.json is only written when one of its own fields is given."""
        d = self.series_dir(name)
        meta = self.series_json(d)
        fields = fields if isinstance(fields, dict) else {}
        docs = {f: str(fields[k] or "").replace("\r\n", "\n") for k, f in (("rules", "README.md"), ("concepts", "CONCEPTS.md"))
                if k in fields}
        own = any(k in fields for k in ("tagline", "description", "signature", "formats", "look", "palette", "fonts", "checks")) \
            or bool(fields.get("detach") or fields.get("link"))
        for k in ("tagline", "description", "signature"):
            if k in fields:
                meta[k] = str(fields[k] or "").strip()
        if "formats" in fields:
            want, ok = fields["formats"], ("1:1", "4:5", "9:16")
            if not isinstance(want, list) or not want or any(f not in ok for f in want):
                raise StoreError("Formats are 1:1, 4:5 and 9:16.")
            meta["formats"] = [f for f in ok if f in want]
        if fields.get("detach"):
            meta = self.styles.detach(meta, self.styles.resolve(self.style_levels(meta)))
        if fields.get("link"):
            meta = self.styles.link(meta, fields["link"])
        changes = {}
        if "look" in fields:
            changes["look"] = self.styles.look(fields["look"])["name"] if fields["look"] else None
        if "palette" in fields:
            changes["palette"] = self._palette(fields["palette"])
        if "fonts" in fields:
            changes["fonts"] = styles.clean_fonts(fields["fonts"], every=False) if fields["fonts"] else None
        if "checks" in fields:
            changes["checks"] = self._checks(meta, fields["checks"])
        for k, v in changes.items():
            if v is None:
                meta.pop(k, None)
            else:
                meta[k] = v
        for f, text in docs.items():
            if text or (d / f).exists():      # an empty text doesn't make a file; it empties one
                write_text(d / f, text)
        if own:
            self.write_series(d, meta)
        return self.series_read(d.name)

    def update_poem_details(self, ref, fields):
        """The poem's own details in poem.json: author (trimmed, up to 120 characters; empty removes it)."""
        folder = self.resolve(ref)
        fields = fields if isinstance(fields, dict) else {}
        changes = {}
        if "author" in fields:
            if fields["author"] is not None and not isinstance(fields["author"], str):
                raise StoreError("The author is text.")
            author = (fields["author"] or "").strip()
            if len(author) > 120:
                raise StoreError("The author can be up to 120 characters.")
            changes["author"] = author or None

        def change(poem):
            for k, v in changes.items():
                if v is None:
                    poem.pop(k, None)
                else:
                    poem[k] = v
        self.update(folder, change)
        return self.read(self.pid(folder))

    def update_poem_style(self, ref, fields):
        """The poem's own look, palette and fonts in poem.json (each None or empty to follow the series again);
        "clear" removes all three."""
        folder = self.resolve(ref)
        fields = fields if isinstance(fields, dict) else {}
        changes = {}
        if "look" in fields:
            changes["look"] = self.styles.look(fields["look"])["name"] if fields["look"] else None
        if "palette" in fields:
            changes["palette"] = self._palette(fields["palette"])
        if "fonts" in fields:
            changes["fonts"] = styles.clean_fonts(fields["fonts"], every=False) if fields["fonts"] else None
        if fields.get("clear"):
            changes = dict.fromkeys(("look", "palette", "fonts"))

        def change(poem):
            for k, v in changes.items():
                if v is None:
                    poem.pop(k, None)
                else:
                    poem[k] = v
        self.update(folder, change)
        return self.read(self.pid(folder))

    def series_design_files(self, name):
        """Every designs/*.json of every poem in a series."""
        d = self.series_dir(name)
        return [f for p in self.poem_dirs(d.name) for f in sorted((p / "designs").glob("*.json"))]

    def designs_using_font(self, family):
        """The design files (any poem) that set text in the family."""
        key, out = str(family).lower(), []
        for p in self.poem_dirs():
            for f in sorted((p / "designs").glob("*.json")):
                try:
                    els = json.loads(f.read_text(encoding="utf-8")).get("elements") or []
                except (OSError, ValueError, AttributeError):
                    continue
                if any(isinstance(e, dict) and str(e.get("font") or "").lower() == key for e in els):
                    out.append(f)
        return out

    def styles_using_font(self, family):
        """The series, the poems with a look or fonts of their own, and the books ("Books/<folder>") whose type roles
        (own or through a look) use the family."""
        key, out = str(family).lower(), []
        has = lambda style: any(str(f.get("family", "")).lower() == key for f in style["fonts"].values())   # noqa: E731
        for d in self.series_dirs():
            meta = self.series_json(d)
            if has(self.styles.resolve(self.style_levels(meta))):
                out.append(d.name)
            for p in self.poem_dirs(d.name):
                try:
                    poem = self.load(p)
                except StoreError:
                    continue
                if (poem.get("look") or poem.get("fonts")) and has(self.styles.resolve(self.style_levels(meta, poem))):
                    out.append(self.pid(p))
        out += [f"Books/{b['id']}" for b in self.book_styles() if has(b["style"])]
        return out

    def book_styles(self):
        """{"id", "title", "style"} for each book in Books/ (next to Poems/) whose book.json can be read."""
        from .books import Books       # here, not at the top: books imports this module
        return Books(self.root.parent / "Books").shelf_styles()

    def fonts_in_designs(self):
        """Lower-cased names of the fonts any design in the library sets text in. Design files are only read again
        when one was added, removed or changed (path, size and mtime of every designs/*.json)."""
        files = []
        for p in self.poem_dirs():
            for f in (p / "designs").glob("*.json"):
                try:
                    st = f.stat()
                except OSError:
                    continue
                files.append((str(f), st.st_mtime_ns, st.st_size))
        sig = tuple(sorted(files))
        if self._fonts_seen is not None and self._fonts_seen[0] == sig:
            return set(self._fonts_seen[1])
        out = set()
        for path, _, _ in sig:
            try:
                els = json.loads(Path(path).read_text(encoding="utf-8")).get("elements") or []
            except (OSError, ValueError, AttributeError):
                continue
            out.update(str(e["font"]).lower() for e in els if isinstance(e, dict) and e.get("font"))
        self._fonts_seen = (sig, frozenset(out))
        return out

    def styles_used(self):
        """Which series, then which books (by title), follow each library palette, look and font:
        {"palettes": {name: [series or book]}, "looks", "fonts"}."""
        used = {"palettes": {}, "looks": {}, "fonts": {}}
        works = [(d.name, self.styles.resolve(self.style_levels(self.series_json(d)))) for d in self.series_dirs()]
        works += [(b["title"], b["style"]) for b in self.book_styles()]
        for name, style in works:
            if style["look"]:
                used["looks"].setdefault(style["look"], []).append(name)
            if style["palette"]["linked"] and style["palette"]["name"]:
                used["palettes"].setdefault(style["palette"]["name"], []).append(name)
            for fam in dict.fromkeys(f["family"] for f in style["fonts"].values()):
                used["fonts"].setdefault(fam, []).append(name)
        return used

    def _palette(self, palette):
        """What series.json keeps for a palette: a library name (linked), or swatches (its own copy); None for none."""
        if palette in (None, "", []):
            return None
        if isinstance(palette, str):
            return self.styles.palette(palette)["name"]
        if isinstance(palette, dict):
            name = " ".join(palette["name"].split())[:60] if isinstance(palette.get("name"), str) else ""
            return {**({"name": name} if name else {}), "swatches": styles.clean_swatches(palette.get("swatches"))}
        return styles.clean_swatches(palette)

    # ——— writing ———
    def create(self, title, series=None):
        title = " ".join(str(title or "").split())
        name = folder_name(title)
        if not name:
            raise StoreError("give the poem a title")
        sdir = self.series_dir(series)
        folder = sdir / name
        if folder.exists():
            raise StoreError(f"{sdir.name}/{name} already exists")
        numbers = [self.load(d).get("number") for d in self.poem_dirs(sdir.name)]
        number = max([n for n in numbers if isinstance(n, int)], default=0) + 1
        author = self.series_meta(sdir).get("signature") or config.SIGNATURE
        template = sdir / "_kit" / "poem-template.json"
        if template.exists():
            try:
                author = json.loads(template.read_text(encoding="utf-8")).get("author", author)
            except ValueError:
                pass
        folder.mkdir(parents=True)
        self.save(folder, {"number": number, "title": title, "slug": slugify(title), "author": author,
                           "status": "draft", "lines": [], "slides": []})
        return self.read(folder)

    def save_text(self, ref, title, text):
        """Save the poem's current text and keep it as a dated draft."""
        folder = self.resolve(ref)
        poem = self.load(folder)
        title = " ".join(str(title or poem.get("title") or folder.name).split())
        lines = clean_lines(str(text or ""))
        drafts = folder / "drafts"
        now = datetime.now().strftime(DRAFT_STAMP)
        old_title, old_lines = poem.get("title") or folder.name, poem.get("lines") or []
        existing = sorted(drafts.glob("*.md")) if drafts.exists() else []
        if not existing and old_lines and (old_title, old_lines) != (title, lines):
            # first draft of a poem written before Studio: keep the text it had
            snap = datetime.fromtimestamp((folder / "poem.json").stat().st_mtime).strftime(DRAFT_STAMP)
            if snap != now:
                write_text(drafts / f"{snap}.md", draft_text(old_title, old_lines))
        latest = existing[-1].read_text(encoding="utf-8") if existing else None
        if lines and latest != draft_text(title, lines):
            write_text(drafts / f"{now}.md", draft_text(title, lines))

        def change(p):
            p["title"], p["lines"] = title, lines
            if not (folder / f"{p.get('slug', '')}.html").exists():
                p["slug"] = slugify(title)  # the slug names the renders, so it's fixed once there are any
        self.update(folder, change)
        return self.read(folder)

    def delete_poem(self, ref):
        """Moves the poem's folder to Poems/.trash/<Series>/ (nothing is destroyed; move it back to restore)."""
        folder = self.resolve(ref)
        trash = self.root / ".trash" / folder.parent.name
        trash.mkdir(parents=True, exist_ok=True)
        dest = trash / f"{folder.name} {datetime.now().strftime('%Y-%m-%d %H%M%S')}"
        for attempt in range(10):
            try:
                os.replace(folder, dest)
                return dest
            except PermissionError:
                if attempt == 9:
                    raise StoreError("Windows won't let go of a file in that folder (is it open somewhere?). Try again.")
                time.sleep(.2)

    def save_notes(self, ref, text):
        folder = self.resolve(ref)
        path = folder / WRITING_NOTES
        if text or path.exists():
            write_text(path, str(text or "").replace("\r\n", "\n"))
        return self.read(folder)

    def save_posting_notes(self, ref, text):
        """NOTES.md: how and where the carousel is posted (read() returns it as "notes")."""
        folder = self.resolve(ref)
        path = folder / "NOTES.md"
        if text or path.exists():
            write_text(path, str(text or "").replace("\r\n", "\n"))
        return self.read(folder)

    def set_status(self, ref, status):
        if status not in STATUSES:
            raise StoreError(f"status must be one of: {', '.join(STATUSES)}")
        folder = self.resolve(ref)
        self.update(folder, lambda p: p.__setitem__("status", status))
        return self.read(folder)

    def write_brief(self, ref, brief):
        folder = self.resolve(ref)
        return write_text(folder / "BRIEF.md", str(brief).replace("\r\n", "\n").rstrip() + "\n")

    def set_slides(self, ref, slides):
        folder = self.resolve(ref)
        if not isinstance(slides, list) or not slides:
            raise StoreError("slides must be a non-empty list like [{\"concept\": \"flare\"}, ...]")
        known = set(self.kit(folder).concept_ids())
        clean = []
        for i, s in enumerate(slides, 1):
            if not isinstance(s, dict) or not isinstance(s.get("concept"), str):
                raise StoreError(f"slide {i} needs a \"concept\"")
            if s["concept"] not in known:
                raise StoreError(f"slide {i}: unknown concept {s['concept']!r}; built: {', '.join(sorted(known))}")
            clean.append({"concept": s["concept"], **{k: v for k, v in s.items() if k != "concept"}})
        self.update(folder, lambda p: p.__setitem__("slides", clean))
        return clean


from . import styles  # noqa: E402  (last: styles imports StoreError and write_text from this module)
