"""Letter-edge metrics from the font files, so the editor aligns type to its ink, the way a series kit does.

For a font instance (family, italic, weight, width, optical size) this returns each glyph's left and
right sidebearing in em, and the cap height. The file comes from the font registry (fonts.py), so any
family Studio knows can be measured. Instances are cut with fontTools and cached in memory and on disk;
the editor asks for the ones its text uses.

Cutting an instance takes seconds, so each one is cut once however many requests ask for it at the same
time, and the instances a fresh install uses first (the bundled looks, the starters, the examples) ship
measured in static/fonts/metrics-seed.json (written by tools/seed_metrics.py with this module's own
measuring, in the disk cache's shape).
"""
import hashlib
import io
import json
import math
import re
import threading
from collections import OrderedDict
from concurrent.futures import Future
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTCollection, TTFont
from fontTools.varLib import instancer

from . import config, fonts

CHARS = [chr(c) for c in range(0x21, 0x7F)] + ["’", "‘", "“", "”", "–", "—", "…", "é", "ë", "ï", "ö", "ü"]
OPSZ = [6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40, 48, 56, 64, 72]   # optical sizes, bucketed
DEFAULT = "Newsreader"   # text in a family Studio doesn't know is measured in this one
SEED = Path(__file__).parent / "static" / "fonts" / "metrics-seed.json"
MEMORY = 512             # instances kept in memory
_lock = threading.Lock()            # one instancer at a time: cutting a variable font takes a lot of memory
_state = threading.Lock()           # guards _memory and _flights
_memory = OrderedDict()             # instance -> metrics, most recently used last
_flights = {}                       # instance -> Future, while it is being measured
_seed = None


def _round(v):
    """Rounding as JavaScript's Math.round does it (halves up), so keys match the editor's."""
    return math.floor(v + 0.5)


def key(font, italic, weight, width, size):
    """The instance a piece of text uses, rounded so that nearby settings share metrics (Design.mkey in design-core.js)."""
    reg = fonts.registry()
    fam = reg.get(font) if font else None
    if fam is None:
        font, fam = DEFAULT, reg.get(DEFAULT)
    italic = bool(italic) and fam is not None and fam.italic
    weight = int(_round(float(weight or 400) / 10) * 10)
    width = _round(float(width or 100) * 2) / 2 if fam is not None and fam.wdth else 100
    opsz = 0
    if fam is not None and fam.opsz:
        lo, hi = fam.opsz
        s = min(hi, max(lo, float(size or 72)))
        opsz = fonts.num(min(hi, max(lo, min(OPSZ, key=lambda o: abs(o - s)))))
    return f"{font}|{int(italic)}|{weight}|{width:g}|{opsz}"


def instance(k):
    font, italic, weight, width, opsz = k.split("|")
    f = fonts.registry().file_for(font, italic == "1", float(weight))
    st = f.path.stat()
    return _instance(k, f.path, f.index, f.source, (st.st_size, st.st_mtime_ns))


def _cache_file(k, path, index, source, stamp):
    """Bundled fonts keep the plain key as the file name; other files add which file they are, so a replaced one isn't read back."""
    name = k.replace("|", "_")
    if source != "bundled":
        name += "_" + hashlib.sha1(f"{path}|{index}|{stamp}".encode("utf-8")).hexdigest()[:10]
    return config.CACHE / "metrics" / (re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name) + ".json")


def seeded(k):
    """The shipped measurements of a bundled instance, or None."""
    global _seed
    if _seed is None:
        try:
            data = json.loads(SEED.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        _seed = data if isinstance(data, dict) else {}
    return _seed.get(k)


def _instance(k, path, index, source, stamp):
    """Metrics of one instance, measured once: a request for an instance that is being measured waits for that."""
    ident = (k, path, index, source, stamp)
    with _state:
        hit = _memory.get(ident)
        if hit is not None:
            _memory.move_to_end(ident)
            return hit
        flight = _flights.get(ident)
        mine = flight is None
        if mine:
            flight = _flights[ident] = Future()
    if not mine:
        return flight.result()
    try:
        out = _load(k, path, index, source, stamp)
    except BaseException as e:
        with _state:
            _flights.pop(ident, None)
        flight.set_exception(e)
        raise
    with _state:
        _memory[ident] = out
        while len(_memory) > MEMORY:
            _memory.popitem(last=False)
        _flights.pop(ident, None)
    flight.set_result(out)
    return out


def _load(k, path, index, source, stamp):
    """The seed (bundled fonts), else the disk cache, else measured now and written to the disk cache."""
    if source == "bundled":
        hit = seeded(k)
        if hit is not None:
            return hit
    disk = _cache_file(k, path, index, source, stamp)
    if disk.exists():
        try:
            return json.loads(disk.read_text(encoding="utf-8"))
        except ValueError:
            pass
    out = measure(k, path, index)
    disk.parent.mkdir(parents=True, exist_ok=True)
    disk.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return out


def measure(k, path, index=0):
    """Cut the instance `k` from the font file and measure it (no caches)."""
    font, italic, weight, width, opsz = k.split("|")
    with _lock:
        raw = path.read_bytes()
        f = TTCollection(io.BytesIO(raw)).fonts[index] if raw[:4] == b"ttcf" else TTFont(io.BytesIO(raw))
        if "fvar" in f:
            axes = {a.axisTag: a for a in f["fvar"].axes}
            want = {"wght": float(weight), "wdth": float(width), "opsz": float(opsz)}
            loc = {t: min(max(want[t] if t in want else a.defaultValue, a.minValue), a.maxValue) for t, a in axes.items()}
            inst = instancer.instantiateVariableFont(f, loc)
        else:
            inst = f
    upm, cmap = inst["head"].unitsPerEm, inst.getBestCmap()
    g = {}
    if "glyf" in inst:
        glyf, hmtx = inst["glyf"], inst["hmtx"]
        for ch in CHARS:
            name = cmap.get(ord(ch))
            if name is None or glyf[name].numberOfContours == 0:
                continue
            gl = glyf[name]
            gl.recalcBounds(glyf)
            g[ch] = [round(gl.xMin / upm, 5), round((hmtx[name][0] - gl.xMax) / upm, 5)]
    else:   # PostScript outlines
        glyphs = inst.getGlyphSet()
        for ch in CHARS:
            name = cmap.get(ord(ch))
            if name is None:
                continue
            pen = BoundsPen(glyphs)
            glyphs[name].draw(pen)
            if pen.bounds:
                g[ch] = [round(pen.bounds[0] / upm, 5), round((glyphs[name].width - pen.bounds[2]) / upm, 5)]
    return {"cap": round(fonts.cap_height(inst), 5), "g": g}


def many(keys):
    out = {}
    reg = fonts.registry()
    for k in keys[:64]:
        try:
            if reg.get(k.split("|")[0]) is None:
                continue
            out[k] = instance(k)
        except Exception:  # noqa: BLE001 — a key we can't read, or a font that won't measure: the editor estimates
            continue
    return out
