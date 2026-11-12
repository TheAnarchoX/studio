"""Letter-edge metrics from the font files, so the editor aligns type to its ink, the way a series kit does.

For a font instance (family, italic, weight, width, optical size) this returns each glyph's left and
right sidebearing in em, and the cap height. Instances are cut with fontTools and cached in memory
and on disk; the editor asks for the ones its text uses.
"""
import json
import threading
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

from . import config

FONTS = Path(__file__).parent / "static" / "fonts"
FILES = {("Newsreader", False): "Newsreader-VF.ttf", ("Newsreader", True): "Newsreader-Italic-VF.ttf",
         ("Archivo", False): "Archivo-VF.ttf", ("Archivo", True): "Archivo-VF.ttf"}
CHARS = [chr(c) for c in range(0x21, 0x7F)] + ["’", "‘", "“", "”", "–", "—", "…", "é", "ë", "ï", "ö", "ü"]
OPSZ = [6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40, 48, 56, 64, 72]   # Newsreader's optical sizes, bucketed
_lock = threading.Lock()


def key(font, italic, weight, width, size):
    """The instance a piece of text uses, rounded so that nearby settings share metrics."""
    font = font if font in ("Newsreader", "Archivo") else "Newsreader"
    italic = bool(italic) and font == "Newsreader"
    weight = int(round(float(weight or 400) / 10) * 10)
    width = round(float(width or 100) * 2) / 2 if font == "Archivo" else 100
    opsz = min(OPSZ, key=lambda o: abs(o - min(72, max(6, float(size or 72))))) if font == "Newsreader" else 0
    return f"{font}|{int(italic)}|{weight}|{width:g}|{opsz}"


@lru_cache(maxsize=512)
def instance(k):
    font, italic, weight, width, opsz = k.split("|")
    disk = config.CACHE / "metrics" / (k.replace("|", "_") + ".json")
    if disk.exists():
        try:
            return json.loads(disk.read_text(encoding="utf-8"))
        except ValueError:
            pass
    with _lock:
        f = TTFont(FONTS / FILES[(font, italic == "1")])
        axes = {a.axisTag: a for a in f["fvar"].axes}
        want = {"wght": float(weight), "wdth": float(width), "opsz": float(opsz)}
        loc = {t: min(max(want.get(t, a.defaultValue) if t in want else a.defaultValue, a.minValue), a.maxValue)
               for t, a in axes.items()}
        inst = instancer.instantiateVariableFont(f, loc)
    upm, cmap, glyf, hmtx = inst["head"].unitsPerEm, inst.getBestCmap(), inst["glyf"], inst["hmtx"]
    g = {}
    for ch in CHARS:
        name = cmap.get(ord(ch))
        if name is None or glyf[name].numberOfContours == 0:
            continue
        gl = glyf[name]
        gl.recalcBounds(glyf)
        g[ch] = [round(gl.xMin / upm, 5), round((hmtx[name][0] - gl.xMax) / upm, 5)]
    out = {"cap": round(inst["OS/2"].sCapHeight / upm, 5), "g": g}
    disk.parent.mkdir(parents=True, exist_ok=True)
    disk.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return out


def many(keys):
    out = {}
    for k in keys[:64]:
        try:
            font, *_ = k.split("|")
            if font not in ("Newsreader", "Archivo"):
                continue
            out[k] = instance(k)
        except (ValueError, KeyError):
            continue
    return out
