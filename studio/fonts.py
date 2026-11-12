"""Every font family Studio can set type in, read from the font files themselves.

Families come from four places; for one family name the first of these wins, and a family appears once:
your own files and the Google Fonts you added (both in the library's Styles/fonts/<Family>/, next to an
optional family.json), the families bundled with Studio (static/fonts, described by families.json), and,
when indexed, the fonts installed on this computer.

For each family the registry knows its files and their axes (weight, width, optical size), the cap height,
the licence and whether the files may be embedded. It writes the @font-face rules every page uses
(/api/fonts.css), serves the files (/fonts/...), and tells metrics.py which file a piece of text is set in.
"""
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTCollection, TTFont

from . import __version__, config
from .store import StoreError, write_text

BUNDLED = Path(__file__).parent / "static" / "fonts"
EXTENSIONS = (".ttf", ".otf", ".woff", ".woff2", ".ttc", ".otc")
PRECEDENCE = ("file", "google", "bundled", "system")
FORMATS = {".ttf": "truetype", ".otf": "opentype", ".woff": "woff", ".woff2": "woff2"}
MIME = {".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2"}
DISPLAYS = ("auto", "block", "swap", "fallback", "optional")


@dataclass
class FontFile:
    path: Path
    family: str
    italic: bool
    weight: int
    axes: dict          # tag -> (min, default, max)
    cap: float          # cap height, in em
    embeddable: bool
    source: str         # "file" | "google" | "bundled" | "system"
    id: str
    index: int = 0              # the face inside a collection (.ttc, .otc)
    collection: bool = False
    license: str = "unknown"    # read from the name table; family.json and families.json know better
    category: str = "display"   # guessed from PANOSE; family.json and families.json know better
    cff: bool = False           # PostScript outlines
    url: str = ""               # where the browser fetches it; set by the registry

    @property
    def weights(self):
        """The weights this file covers: its wght axis, or its one weight."""
        a = self.axes.get("wght")
        return (a[0], a[2]) if a else (self.weight, self.weight)


@dataclass
class Family:
    name: str
    category: str
    source: str
    license: str
    files: list = field(default_factory=list)

    @property
    def italic(self) -> bool:
        return any(f.italic for f in self.files)

    @property
    def wght(self):
        return (min(f.weights[0] for f in self.files), max(f.weights[1] for f in self.files))

    def _axis(self, tag):
        found = [f.axes[tag] for f in self.files if tag in f.axes]
        return (min(a[0] for a in found), max(a[2] for a in found)) if found else None

    @property
    def wdth(self):
        return self._axis("wdth")

    @property
    def opsz(self):
        return self._axis("opsz")

    @property
    def cap(self) -> float:
        return self.file_for(False, 400).cap

    @property
    def embeddable(self) -> bool:
        return all(f.embeddable for f in self.files)

    def file_for(self, italic, weight) -> FontFile:
        """The file the browser sets this style in: the same style if the family has it (else roman),
        variable files first, then the weight CSS font matching picks."""
        for group in ([f for f in self.files if f.italic == bool(italic)], [f for f in self.files if not f.italic], self.files):
            if group:
                return _match_weight(sorted(group, key=lambda f: not f.axes), float(weight))
        raise KeyError(self.name)


def _match_weight(files, w):
    """CSS Fonts 4 font-weight matching over weight ranges (a static file is a range of one)."""
    inside = [f for f in files if f.weights[0] <= w <= f.weights[1]]
    if inside:
        return inside[0]
    below = sorted((f for f in files if f.weights[1] < w), key=lambda f: -f.weights[1])
    above = sorted((f for f in files if f.weights[0] > w), key=lambda f: f.weights[0])
    if 400 <= w <= 500:
        order = [f for f in above if f.weights[0] <= 500] + below + [f for f in above if f.weights[0] > 500]
    elif w < 400:
        order = below + above
    else:
        order = above + below
    return order[0]


# ——— reading font files ———

def num(v):
    v = float(v)
    return int(v) if v.is_integer() else v


def _clean(name):
    return " ".join(re.sub(r"[\x00-\x1f\x7f|]", " ", str(name or "")).split())[:100]   # "|" separates the metrics key


def _glyph_top(tt, ch):
    name = (tt.getBestCmap() or {}).get(ord(ch))
    if not name:
        return 0
    glyphs = tt.getGlyphSet()
    pen = BoundsPen(glyphs)
    glyphs[name].draw(pen)
    return pen.bounds[3] if pen.bounds else 0


def cap_height(tt):
    """Cap height in em: OS/2 sCapHeight when the table has one, else the top of the H, else 0.7."""
    os2, upm = tt["OS/2"] if "OS/2" in tt else None, tt["head"].unitsPerEm or 1000
    if os2 is not None and os2.version >= 2 and getattr(os2, "sCapHeight", 0) > 0:
        return os2.sCapHeight / upm
    return (_glyph_top(tt, "H") / upm) or 0.7


def _license(name_table):
    text = " ".join(filter(None, (name_table.getDebugName(13), name_table.getDebugName(14)))).lower()
    if "open font license" in text or "openfontlicense" in text or "scripts.sil.org/ofl" in text:
        return "OFL-1.1"
    if "apache" in text:
        return "Apache-2.0"
    if "ubuntu font licen" in text:
        return "UFL-1.0"
    return "unknown"


def _category(os2):
    """From PANOSE: hand-written faces are hand, sans-serif text faces sans, other text faces serif."""
    p = getattr(os2, "panose", None)
    family_type = getattr(p, "bFamilyType", 0)
    if family_type == 3:
        return "hand"
    if family_type == 2:
        return "sans" if getattr(p, "bSerifStyle", 0) in (11, 12, 13) else "serif"
    return "display"


def _face(tt, path: Path, source: str, index: int, collection: bool) -> FontFile:
    name = tt["name"]
    head = tt["head"]
    os2 = tt["OS/2"] if "OS/2" in tt else None
    axes = {a.axisTag: (num(a.minValue), num(a.defaultValue), num(a.maxValue)) for a in tt["fvar"].axes} if "fvar" in tt else {}
    if "wght" in axes:
        weight = int(round(axes["wght"][1]))
    else:
        weight = os2.usWeightClass if os2 is not None else 400
        weight = min(1000, max(1, weight * 100 if 1 <= weight <= 9 else weight))
    return FontFile(
        path=path, family=_clean(name.getDebugName(16) or name.getDebugName(1)) or _clean(path.stem), index=index, collection=collection,
        italic=bool(os2 is not None and os2.fsSelection & 1) or bool(head.macStyle & 2), weight=weight, axes=axes,
        cap=round(cap_height(tt), 5), embeddable=os2 is None or (os2.fsType & 0x0002) == 0, source=source,
        id=hashlib.sha1(f"{source}\0{path}\0{index}".encode("utf-8")).hexdigest()[:16],
        license=_license(name), category=_category(os2), cff="CFF " in tt or "CFF2" in tt)


def _face_to_json(f: FontFile) -> dict:
    return {"family": f.family, "italic": f.italic, "weight": f.weight, "axes": {t: list(a) for t, a in f.axes.items()},
            "cap": f.cap, "embeddable": f.embeddable, "id": f.id, "index": f.index, "collection": f.collection,
            "license": f.license, "category": f.category, "cff": f.cff}


def _face_from_json(path: Path, d: dict) -> FontFile:
    return FontFile(path=path, family=d["family"], italic=d["italic"], weight=d["weight"],
                    axes={t: tuple(a) for t, a in d["axes"].items()}, cap=d["cap"], embeddable=d["embeddable"],
                    source="system", id=d["id"], index=d["index"], collection=d["collection"], license=d["license"],
                    category=d["category"], cff=d["cff"])


def read_font(path: Path, source: str) -> list[FontFile]:
    """One entry per face in a font file (a collection has several); [] when it can't be read as a font.
    The file is read into memory first, so it is never held open."""
    path = Path(path)
    try:
        data = path.read_bytes()
        collection = data[:4] == b"ttcf"
        faces = TTCollection(io.BytesIO(data), lazy=True).fonts if collection else [TTFont(io.BytesIO(data), lazy=True)]
    except Exception:  # noqa: BLE001 — anything that isn't a readable font
        return []
    out = []
    for i, tt in enumerate(faces):
        try:
            out.append(_face(tt, path, source, i, collection))
        except Exception:  # noqa: BLE001
            continue
    return out


def face_bytes(f: FontFile):
    """The bytes of one font file, or of one face cut out of a collection; with its media type."""
    data = f.path.read_bytes()
    if not f.collection:
        return data, MIME.get(f.path.suffix.lower(), "application/octet-stream")
    buf = io.BytesIO()
    TTCollection(io.BytesIO(data)).fonts[f.index].save(buf)
    return buf.getvalue(), "font/otf" if f.cff else "font/ttf"


def _format(f: FontFile):
    if f.collection:
        return "opentype" if f.cff else "truetype"
    return FORMATS.get(f.path.suffix.lower(), "opentype" if f.cff else "truetype")


def _css_name(name):
    return name.replace("\\", "\\\\").replace('"', '\\"')


# ——— the registry ———

class Registry:
    def __init__(self, bundled: Path, library: Path, system_dirs: list[Path] | None = None, cache: Path | None = None):
        self.bundled = Path(bundled)
        self.library = Path(library)
        self.system_dirs = [Path(p) for p in system_dirs or []]
        self.cache = Path(cache) if cache else None     # where the system index is kept between runs
        self._lock = threading.RLock()
        self._main = None       # {lower name: Family}: library and bundled, in display order
        self._system = None     # {lower name: Family}: families only on this computer, once indexed
        self._sysfaces = None   # every face found on this computer; survives library refreshes
        self._gen = 0           # bumped by rescan_system: an index started before it must not be published
        self._indexing = False
        self._urls = {}         # url path -> [FontFile]
        self._faces = {}        # (path, index, mtime) -> one face cut out of a collection
        self._stamp = None
        self._checked = 0.0

    # loading
    def refresh(self):
        """Forget the library's families; the computer's fonts stay indexed (re-registered on the next load)."""
        with self._lock:
            self._main = self._system = None
            self._urls, self._faces = {}, {}

    def _library_stamp(self):
        out = []
        if self.library.is_dir():
            for p in self.library.rglob("*"):
                if p.suffix.lower() in EXTENSIONS or p.name == "family.json":
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    out.append((p.as_posix(), st.st_size, st.st_mtime_ns))
        return tuple(sorted(out))

    def check(self, every=1.0):
        """Reload when files in the library's font folder were added, removed or changed (checked at most every `every` s)."""
        now = time.monotonic()
        if now - self._checked < every:
            return
        self._checked = now
        with self._lock:
            if self._main is not None and self._library_stamp() != self._stamp:
                self.refresh()

    def _load(self):
        with self._lock:
            if self._main is not None:
                return self._main
            self._stamp = self._library_stamp()
            groups, order = {}, []
            for fam in self._read_bundled():
                groups[("bundled", fam.name.lower())] = fam
                order.append(fam.name.lower())
            own = sorted(self._read_library(), key=lambda fam: fam.name.lower())
            for fam in own:
                groups.setdefault((fam.source, fam.name.lower()), fam)
            order += sorted({fam.name.lower() for fam in own} - set(order))
            main = {}
            for key in order:
                fam = next((groups[(src, key)] for src in PRECEDENCE if (src, key) in groups), None)
                if fam:
                    main[key] = fam
            self._urls = self._index(main.values())
            self._main = main
            if self._sysfaces is not None:
                self._apply_system(main)
            return main

    @staticmethod
    def _index(families):
        urls = {}
        for fam in families:
            for f in fam.files:
                urls.setdefault(unquote(f.url.split("?")[0]), []).append(f)
        return urls

    def _read_bundled(self):
        try:
            entries = json.loads((self.bundled / "families.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for entry in entries:
            files = []
            for desc in entry.get("files") or []:
                for face in read_font(self.bundled / desc["file"], "bundled"):
                    face.family = entry["family"]
                    face.url = "/fonts/bundled/" + quote(desc["file"])
                    files.append(face)
            if files:
                out.append(Family(entry["family"], entry.get("category") or files[0].category, "bundled",
                                  entry.get("license") or files[0].license, files))
        return out

    def _read_library(self):
        if not self.library.is_dir():
            return []
        metas, groups = {}, {}
        for p in sorted(self.library.rglob("*")):
            rel = p.relative_to(self.library)
            if p.suffix.lower() not in EXTENSIONS or any(part.startswith(".") for part in rel.parts) or not p.is_file():
                continue
            if p.parent not in metas:
                try:
                    meta = json.loads((p.parent / "family.json").read_text(encoding="utf-8"))
                    metas[p.parent] = meta if isinstance(meta, dict) else {}
                except (OSError, ValueError):
                    metas[p.parent] = {}
            meta = metas[p.parent]
            source = meta.get("source") if meta.get("source") in ("file", "google") else "file"
            for face in read_font(p, source):
                if isinstance(meta.get("family"), str) and _clean(meta["family"]):
                    face.family = _clean(meta["family"])
                face.url = "/fonts/library/" + quote(rel.as_posix()) + (f"?face={face.index}" if face.collection else "")
                key = (source, face.family.lower())
                if key not in groups:
                    groups[key] = Family(face.family, meta.get("category") or face.category, source,
                                         meta.get("license") or face.license, [])
                groups[key].files.append(face)
        return list(groups.values())

    # the computer's own fonts
    def _scan_system(self):
        """Every face in the system font folders; files unchanged since the cached index (path, size, mtime) aren't opened."""
        old = self._read_system_cache()
        files, faces = {}, []
        for d in self.system_dirs:
            for root, dirs, names in os.walk(d):
                dirs.sort()
                for name in sorted(names):
                    p = Path(root) / name
                    if p.suffix.lower() not in EXTENSIONS:
                        continue
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    hit = old.get(str(p))
                    found = None
                    if isinstance(hit, dict) and hit.get("size") == st.st_size and hit.get("mtime") == st.st_mtime_ns:
                        try:
                            found = [_face_from_json(p, x) for x in hit.get("faces") or []]
                        except (KeyError, TypeError, ValueError, AttributeError):
                            found = None     # a broken cache entry is a miss: read the file again
                    if found is None:
                        found = read_font(p, "system")
                    for f in found:
                        f.url = "/fonts/system/" + f.id
                    files[str(p)] = {"size": st.st_size, "mtime": st.st_mtime_ns, "faces": [_face_to_json(f) for f in found]}
                    faces += found
        if self.cache and files != old:
            try:
                write_text(self.cache, json.dumps({"version": 1, "files": files}))
            except OSError:
                pass
        return faces

    def _read_system_cache(self):
        try:
            data = json.loads(self.cache.read_text(encoding="utf-8")) if self.cache else {}
            files = data.get("files") if data.get("version") == 1 else {}
            return files if isinstance(files, dict) else {}
        except (OSError, ValueError, AttributeError):
            return {}

    def _apply_system(self, main):
        groups = {}
        for face in self._sysfaces:
            key = face.family.lower()
            if key in main:
                continue
            if key not in groups:
                groups[key] = Family(face.family, face.category, "system", face.license, [])
            groups[key].files.append(face)
        self._system = dict(sorted(groups.items()))
        self._urls.update(self._index(self._system.values()))

    def _load_system(self):
        with self._lock:
            main = self._load()
            if self._sysfaces is None:
                self._sysfaces = self._scan_system()
            if self._system is None:
                self._apply_system(main)
            return self._system

    def start_system_index(self):
        """Build the index of this computer's fonts in a background thread (once); system_ready() says when it is done."""
        with self._lock:
            if self._sysfaces is not None or self._indexing:
                return
            self._indexing = True
            gen = self._gen
        threading.Thread(target=self._index_system, args=(gen,), daemon=True, name="font-index").start()

    def _index_system(self, gen):
        try:
            faces = self._scan_system()
        except Exception as e:  # noqa: BLE001 — an unreadable folder shouldn't leave the index stuck on "indexing"
            print(f"studio: indexing the system fonts failed: {e}", file=sys.stderr)
            faces = []
        with self._lock:
            if gen != self._gen:        # a rescan was asked for while this ran: its result is stale, scan again
                threading.Thread(target=self._index_system, args=(self._gen,), daemon=True, name="font-index").start()
                return
            self._sysfaces = faces
            self._indexing = False
            self._system = None
            self._apply_system(self._load())

    def system_ready(self) -> bool:
        with self._lock:
            return self._sysfaces is not None

    def rescan_system(self):
        """Forget the system index; the next request builds it again."""
        with self._lock:
            self._gen += 1
            self._sysfaces = self._system = None
            self._main = None
            self._urls, self._faces = {}, {}

    def wait_system(self, timeout: float = 10.0) -> bool:
        """Wait up to `timeout` seconds for a running system index; True once the index is there."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if self._sysfaces is not None:
                    return True
                if not self._indexing:
                    return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def resolve_missing(self, names, timeout: float = 10.0) -> list[str]:
        """The `names` no family answers to. A process that never started the system index (the MCP server) would
        wrongly miss the computer's fonts, so when something is missing the index is started (cached on disk) and waited for."""
        names = list(dict.fromkeys(str(n) for n in names if n))
        missing = [n for n in names if self.get(n) is None]
        if missing:
            self.start_system_index()
            if self.wait_system(timeout):
                missing = [n for n in missing if self.get(n) is None]
        return missing

    def system_used(self, names) -> list["Family"]:
        """The computer's families among `names` (lower-cased); none until the system index is loaded."""
        with self._lock:
            if self._sysfaces is None:
                return []
            wanted = {str(n).lower() for n in names}
            return [fam for key, fam in self._load_system().items() if key in wanted]

    def system_json(self) -> list[dict]:
        self._load_system()
        return self._json(self._system.values())

    # questions
    def families(self, include_system: bool = False) -> list[Family]:
        out = list(self._load().values())
        return out + list(self._load_system().values()) if include_system else out

    def get(self, name) -> Family | None:
        key = str(name or "").lower()
        with self._lock:
            fam = self._load().get(key)
            if fam is None and self._sysfaces is not None:
                fam = self._load_system().get(key)
            return fam

    def file_for(self, name, italic: bool, weight: float) -> FontFile:
        fam = self.get(name)
        if fam is None:
            raise KeyError(name)
        return fam.file_for(italic, weight)

    def to_json(self, include_system: bool = False, extra=()) -> list[dict]:
        return self._json(self.families(include_system) + list(extra))

    @staticmethod
    def _json(families) -> list[dict]:
        pair = lambda r: None if r is None else [r[0], r[1]]   # noqa: E731
        return [{"family": fam.name, "category": fam.category, "source": fam.source, "license": fam.license,
                 "italic": fam.italic, "wght": pair(fam.wght), "wdth": pair(fam.wdth), "opsz": pair(fam.opsz),
                 "cap": round(fam.cap, 4), "embeddable": fam.embeddable,
                 "files": [{"url": f.url, "italic": f.italic, "weight": f.weight, "axes": {t: list(a) for t, a in f.axes.items()}}
                           for f in fam.files]}
                for fam in families]

    def css(self, display: str = "block", extra=()) -> str:
        """@font-face rules for every file of every family, and of the `extra` ones (the computer's families the
        designs use; the browser has no others)."""
        display = display if display in DISPLAYS else "block"
        rules = []
        for fam in self.families() + list(extra):
            for f in fam.files:
                w, wd = f.axes.get("wght"), f.axes.get("wdth")
                parts = [f'font-family:"{_css_name(fam.name)}"', f"font-style:{'italic' if f.italic else 'normal'}",
                         f"font-weight:{w[0]} {w[2]}" if w else f"font-weight:{f.weight}"]
                if wd:
                    parts.append(f"font-stretch:{wd[0]}% {wd[2]}%")
                parts += [f"font-display:{display}", f'src:url("{f.url}") format("{_format(f)}")']
                rules.append("@font-face{" + ";".join(parts) + "}")
        return "\n".join(rules) + "\n"

    def open(self, path: str, face=None):
        """The bytes and media type of an indexed file, by its url path; None for anything else."""
        with self._lock:
            self._load()
            files = self._urls.get(path) or []
        f = next((x for x in files if face in (None, "") or str(x.index) == str(face)), None)
        if f is None:
            return None
        try:
            if not f.collection:
                return face_bytes(f)
            key = (f.path, f.index, f.path.stat().st_mtime_ns)
            with self._lock:
                if key not in self._faces:
                    self._faces = {key: face_bytes(f)}   # keep only the last face cut out of a collection
                return self._faces[key]
        except Exception:  # noqa: BLE001 — gone or no longer a font since it was indexed
            return None


_registry = None
_registry_lock = threading.Lock()


def registry() -> Registry:
    """The process-wide registry for the current library (rebuilt when the library changes)."""
    global _registry
    lib = config.ART / "Styles" / "fonts"
    with _registry_lock:
        if _registry is None or _registry.library != lib:
            _registry = Registry(BUNDLED, lib, system_dirs(), config.CACHE / "system-fonts.json")
        reg = _registry
    reg.check()
    return reg


# ——— the computer's font folders ———

def system_dirs() -> list[Path]:
    """Where this computer keeps its fonts."""
    home = Path.home()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"] + (
            [Path(local) / "Microsoft" / "Windows" / "Fonts"] if local else [])
    if sys.platform == "darwin":
        return [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library" / "Fonts"]
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".local" / "share" / "fonts", home / ".fonts"]


# ——— adding fonts ———

GOOGLE_CATALOG = "https://fonts.google.com/metadata/fonts"
GOOGLE_LIST = "https://fonts.google.com/download/list?family="
GOOGLE_CATEGORIES = {"sans serif": "sans", "serif": "serif", "display": "display", "handwriting": "hand", "monospace": "mono"}
CATALOG_DAYS = 7


MAX_FONT_BYTES = 20_000_000
MAX_META_BYTES = 30_000_000


def _allowed(url: str) -> bool:
    """Only the two Google Fonts metadata endpoints and font files on Google's static host, over https."""
    u = urlsplit(str(url))
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
        return False
    return u.hostname == "fonts.gstatic.com" or (u.hostname == "fonts.google.com" and str(url).startswith((GOOGLE_CATALOG, GOOGLE_LIST)))


def _limit(url: str) -> int:
    return MAX_FONT_BYTES if urlsplit(str(url)).hostname == "fonts.gstatic.com" else MAX_META_BYTES


def _too_big():
    return StoreError("Google Fonts sent a file that is too large.")


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"Studio/{__version__}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if not _allowed(r.geturl()):     # a redirect somewhere else
            raise StoreError("Google Fonts sent Studio somewhere unexpected.")
        data = r.read(_limit(url) + 1)
    if len(data) > _limit(url):
        raise _too_big()
    return data


def _get(url, fetch):
    if not _allowed(url):
        raise StoreError("Studio only downloads fonts from Google Fonts over https.")
    try:
        data = (fetch or _fetch)(url)
    except StoreError:
        raise
    except Exception:  # noqa: BLE001 — offline, blocked, a bad status
        raise StoreError("Couldn't reach Google Fonts. Check your connection and try again.") from None
    if len(data) > _limit(url):
        raise _too_big()
    return data


def _google_json(raw: bytes):
    text = raw.decode("utf-8-sig", "replace")
    if text.startswith(")]}'"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    try:
        return json.loads(text)
    except ValueError:
        raise StoreError("Google Fonts sent something Studio can't read.") from None


def google_catalog(fetch=None) -> list[dict]:
    """The Google Fonts catalogue: {"family", "category", "axes", "italic"}; kept for a week in the cache folder."""
    path = config.CACHE / "google-fonts.json"
    stale = None
    try:
        stale = json.loads(path.read_text(encoding="utf-8"))["families"]
        if time.time() - path.stat().st_mtime < CATALOG_DAYS * 86400:
            return stale
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        data = _google_json(_get(GOOGLE_CATALOG, fetch))
        out = []
        for f in data["familyMetadataList"]:
            name = _clean(f.get("family"))
            if not name:
                continue
            out.append({"family": name, "category": GOOGLE_CATEGORIES.get(str(f.get("category", "")).lower(), "display"),
                        "axes": [{"tag": a["tag"], "min": num(a["min"]), "default": num(a.get("defaultValue", a["min"])), "max": num(a["max"])}
                                 for a in f.get("axes") or []],
                        "italic": any(str(k).endswith("i") for k in f.get("fonts") or {})})
    except (StoreError, KeyError, TypeError):
        if stale is not None:
            return stale
        raise
    try:
        write_text(path, json.dumps({"families": out}, ensure_ascii=False))
    except OSError:
        pass
    return out


def _google_list(family, fetch):
    """(file name, url) of the .ttf files Google offers for a family, and the licence its download names."""
    manifest = _google_json(_get(GOOGLE_LIST + quote(family), fetch)).get("manifest") or {}
    refs = [(str(r["filename"]).replace("\\", "/").rsplit("/", 1)[-1], r["url"]) for r in manifest.get("fileRefs") or []
            if str(r.get("filename", "")).lower().endswith(".ttf") and r.get("url")]
    variable = [r for r in refs if "VariableFont" in r[0] or re.search(r"\[.*\]", r[0])]
    notes = [(str(f.get("filename", "")).lower(), str(f.get("contents", "")).lower()) for f in manifest.get("files") or []]
    if any("ofl" in n or "open font license" in c for n, c in notes):
        licence = "OFL-1.1"
    elif any("apache" in c for n, c in notes):
        licence = "Apache-2.0"
    elif any("ufl" in n or "ubuntu font licen" in c for n, c in notes):
        licence = "UFL-1.0"
    else:
        licence = None
    return variable or refs, licence


def google_files(family, fetch=None) -> list[tuple[str, str]]:
    """(file name, url) of a family's .ttf files; only the variable ones when Google has them."""
    return _google_list(family, fetch)[0]


def add_google(family, fetch=None) -> dict:
    """Download a Google Fonts family into the library."""
    entry = next((f for f in google_catalog(fetch) if f["family"].lower() == str(family or "").strip().lower()), None)
    if entry is None:
        raise StoreError(f"{_clean(family) or 'That family'} isn't on Google Fonts.")
    files, licence = _google_list(entry["family"], fetch)
    if not files:
        raise StoreError(f"Google Fonts has no font files for {entry['family']}.")
    items = [(name, _get(url, fetch)) for name, url in files]
    return _store(items, "google", family=entry["family"], category=entry["category"], licence=licence)


def add_files(items: list[tuple[str, bytes]]) -> dict:
    """Add font files to the library, grouped by family: {"added": [families], "warnings": [sentences]}."""
    return _store(items, "file")


def _safe(name, fallback="Font"):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name)).strip(" .") or fallback


def _store(items, source, family=None, category=None, licence=None) -> dict:
    if not items:
        raise StoreError("Choose one or more font files.")
    groups = {}
    with tempfile.TemporaryDirectory(prefix="studio-font-") as tmp:     # read everything before keeping anything
        for i, (name, data) in enumerate(items):
            shown = str(name).replace("\\", "/").rsplit("/", 1)[-1] or "file"
            fname = _safe(shown, "font")
            probe = Path(tmp) / f"{i}{Path(fname).suffix}"
            probe.write_bytes(data)
            faces = read_font(probe, source) if Path(fname).suffix.lower() in EXTENSIONS else []
            if not faces:
                raise StoreError(f"{shown} isn't a font file.")
            group = _clean(family) if family else faces[0].family
            groups.setdefault(group, []).append((fname, data, faces))
    lib = config.ART / "Styles" / "fonts"
    added, warnings = [], []
    for fam, files in groups.items():
        faces = [f for _, _, fs in files for f in fs]
        known = next((f.license for f in faces if f.license != "unknown"), "unknown")
        meta = {"family": fam, "category": category or faces[0].category, "source": source, "license": licence or known}
        folder = lib / _safe(fam)
        folder.mkdir(parents=True, exist_ok=True)
        for fname, data, _ in files:
            tmp = folder / f".{fname}.{os.getpid()}.tmp"
            tmp.write_bytes(data)
            os.replace(tmp, folder / fname)
        write_text(folder / "family.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        added.append(fam)
        if meta["license"] == "unknown":
            warnings.append(f"No licence found in {fam}; check it allows use in print.")
        if not all(f.embeddable for f in faces):
            warnings.append(f"{fam} doesn't allow embedding in PDFs.")
    registry().refresh()
    return {"added": added, "warnings": warnings}


# ——— fonts you added: correct them or take them away ———

CATEGORIES = ("serif", "sans", "display", "mono", "hand")


def _own(name, what):
    """The family and its folder, when the family is one you added (a file or a Google font)."""
    reg = registry()
    fam = reg.get(name) if isinstance(name, str) else None
    if fam is None or fam.source not in ("file", "google") or not fam.files:
        raise StoreError(f"Only fonts you added can be {what}.")
    folder = fam.files[0].path.parent
    if folder == reg.library or reg.library not in folder.parents:
        raise StoreError(f"Only fonts you added can be {what}.")
    return fam, folder


def update_family(name, fields) -> dict:
    """Correct the category (serif, sans, display, mono, hand) and licence (up to 60 characters) of a font you added."""
    fam, folder = _own(name, "edited")
    fields = fields if isinstance(fields, dict) else {}
    try:
        meta = json.loads((folder / "family.json").read_text(encoding="utf-8"))
        meta = meta if isinstance(meta, dict) else {}
    except (OSError, ValueError):
        meta = {}
    meta = {"family": fam.name, "category": fam.category, "source": fam.source, "license": fam.license, **meta}
    if "category" in fields:
        if fields["category"] not in CATEGORIES:
            raise StoreError("The category is serif, sans, display, mono or hand.")
        meta["category"] = fields["category"]
    if "license" in fields:
        licence = str(fields["license"] or "").strip()
        if len(licence) > 60:
            raise StoreError("The licence can be up to 60 characters.")
        meta["license"] = licence or "unknown"
    write_text(folder / "family.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    reg = registry()
    reg.refresh()
    return reg._json([reg.get(fam.name)])[0]


def remove_family(name, used=0, force=False, styled=0) -> Path:
    """Move a font you added to Styles/.trash/fonts/<Family> <timestamp>/. A family that `used` designs set text in
    stays unless `force`; so does one that `styled` series, poems or books use."""
    fam, folder = _own(name, "removed")
    if (used or styled) and not force:
        where = [f"{n} {w}" for n, w in ((used, "design" + ("" if used == 1 else "s")),
                                         (styled, "series, poem or book" if styled == 1 else "series, poems or books")) if n]
        err = StoreError(f"{fam.name} is used in {' and '.join(where)}; change them first.")
        err.details = {"designs": used, "styled": styled}      # in the reply too, for the app's "Remove anyway?"
        raise err
    trash = registry().library.parent / ".trash" / "fonts"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{folder.name} {time.strftime('%Y-%m-%d %H%M%S')}"
    n = 1
    while dest.exists():
        n += 1
        dest = trash / f"{folder.name} {time.strftime('%Y-%m-%d %H%M%S')} {n}"
    os.replace(folder, dest)
    registry().refresh()
    return dest
