"""Poems on disk. The Art folder is the database: every read goes to the files, every write is a file.

A series is a folder in Poems/ with a series.json or a render engine (_kit/build.py). A poem is a folder in a series
with a poem.json. Poems are named by id ("<Series>/<Poem folder>"), or loosely by folder, title or slug.
"""
import json
import os
import re
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
SERIES_KEYS = ["name", "tagline", "description", "signature", "palette", "fonts", "formats", "created"]
FONTS = ["Newsreader", "Archivo"]   # the typefaces Studio ships (static/fonts)
PALETTES = {  # starting points for a new series
    "Signal": [["Night", "#0C0E11"], ["Paper", "#EEEAE2"], ["Signal red", "#DA291C"], ["Fog", "#959AA2"],
               ["Fog ink", "#77726B"]],
    "Ink and paper": [["Ink", "#141414"], ["Paper", "#F2EFE8"], ["Graphite", "#6E6B66"], ["Pencil", "#A9A59E"]],
    "Blood": [["Black", "#0B0B0C"], ["Bone", "#E9E4DA"], ["Blood", "#7A0019"], ["Ash", "#8C8A87"]],
    "Ultramarine": [["Night", "#0B0E1A"], ["Paper", "#F1EEE6"], ["Ultramarine", "#1F3DD1"], ["Fog", "#9AA0AE"]],
    "Ochre": [["Soot", "#16130F"], ["Linen", "#F0E9DC"], ["Ochre", "#C98A1B"], ["Clay", "#8E5B3C"]],
}


DESIGN_FORMATS = {"11": (1080, 1080, "1x1"), "45": (1080, 1350, "4x5"), "916": (1080, 1920, "9x16")}
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
    """Atomic write; retries briefly because Windows refuses to replace a file someone is reading."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
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
        return {"id": self.pid(folder), "series": folder.parent.name, "folder": folder.name,
                "path": str(folder), "title": poem.get("title") or folder.name, "slug": poem.get("slug"),
                "number": poem.get("number"), "author": poem.get("author"),
                "status": self.status(folder, poem), "status_set": poem.get("status") in STATUSES,
                "lines": poem.get("lines") or [], "slides": poem.get("slides") or [],
                "drafts": self.drafts(folder), "writing_notes": read_text(folder / WRITING_NOTES) or "",
                "brief": read_text(folder / "BRIEF.md"), "notes": read_text(folder / "NOTES.md"),
                "art": art, "qa": json.loads(qa) if qa else None, "designs": self.designs(folder),
                "series_info": {k: v for k, v in self.series_meta(folder.parent).items()
                                if k in ("name", "tagline", "palette", "fonts", "signature", "has_kit")},
                "stamp": self.stamp(folder)}

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
    def designs(self, folder: Path):
        out = []
        d = folder / "designs"
        for f in sorted(d.glob("*.json")) if d.exists() else []:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            fmt = data.get("format", "45")
            exports = {}
            for k, (_, _, tag) in DESIGN_FORMATS.items():
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
    def series_meta(self, d: Path):
        meta = {}
        f = d / SERIES_FILE
        if f.exists():
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
            except ValueError as e:
                raise StoreError(f"{d.name}/{SERIES_FILE} can't be read: {e}") from None
        palette = meta.get("palette") or [{"name": n, "hex": h} for n, h in PALETTES["Signal"]]
        return {"name": d.name, "tagline": meta.get("tagline", ""), "description": meta.get("description", ""),
                "signature": meta.get("signature", config.SIGNATURE), "palette": palette,
                "fonts": meta.get("fonts") or [{"family": "Newsreader", "role": "voice"},
                                                {"family": "Archivo", "role": "command"}],
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

    def create_series(self, name, tagline="", palette=None, description=""):
        name = " ".join(str(name or "").split())
        folder = folder_name(name)
        if not folder:
            raise StoreError("give the series a name")
        d = self.root / folder
        if d.exists():
            raise StoreError(f"{folder} already exists in Poems")
        pal = self._palette(palette)
        tagline = str(tagline or "").strip()
        d.mkdir(parents=True)
        self.write_series(d, {"tagline": tagline, "description": str(description or "").strip(),
                              "signature": config.SIGNATURE, "palette": pal,
                              "fonts": [{"family": "Newsreader", "role": "voice"},
                                        {"family": "Archivo", "role": "command"}],
                              "formats": ["1:1", "4:5", "9:16"], "created": datetime.now().date().isoformat()})
        colours = ", ".join(f"{c['name']} `{c['hex']}`" for c in pal)
        write_text(d / "README.md", f"# {folder}\n\n{tagline or 'A new series of poems.'}\n\n"
                   "## The rules\n\n"
                   f"- **Palette:** {colours}.\n"
                   "- **Type:** Newsreader and Archivo.\n"
                   "- **Words:** only the poem's own words and the name.\n"
                   + (f"- **Signature:** \"{config.SIGNATURE}\". " if config.SIGNATURE else "- **Signature:** the poet's name. ")
                   + "Every image also exists unsigned, with an identical layout.\n"
                   "- **Formats:** 1:1 for X, 4:5 for the Instagram feed, 9:16 for stories, rendered at 2x.\n")
        return self.series_read(folder)

    def update_series(self, name, fields):
        d = self.series_dir(name)
        meta = self.series_meta(d)
        for k in ("tagline", "description", "signature"):
            if k in fields:
                meta[k] = str(fields[k] or "").strip()
        if "palette" in fields:
            meta["palette"] = self._palette(fields["palette"])
        self.write_series(d, meta)
        return self.series_read(d.name)

    @staticmethod
    def _palette(palette):
        if isinstance(palette, str):
            if palette not in PALETTES:
                raise StoreError(f"palette must be one of: {', '.join(PALETTES)}")
            return [{"name": n, "hex": h} for n, h in PALETTES[palette]]
        if not palette:
            return [{"name": n, "hex": h} for n, h in PALETTES["Signal"]]
        out = []
        for c in palette:
            hexv = str(c.get("hex", "")).strip()
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", hexv):
                raise StoreError(f"not a colour: {hexv!r} (use #RRGGBB)")
            out.append({"name": str(c.get("name") or hexv).strip()[:40], "hex": hexv.upper()})
        if not 2 <= len(out) <= 8:
            raise StoreError("a palette has 2 to 8 colours")
        return out

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
