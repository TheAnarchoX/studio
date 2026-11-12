"""Palettes, looks and house rules, and how a poem inherits them.

A palette is named swatches, some with a role (background, text, accent, muted). A look is a palette, by name,
and a font for each role (display, text, label). Studio bundles starters (static/styles); the library keeps its own
in Styles/palettes/<name>.json, Styles/looks/<name>.json and Styles/rules.md (the house rules). An own file with a
starter's name takes its place, so editing a starter saves an own copy, and deleting that copy brings the starter back.

Style is resolved through levels, from global to most specific (global, series, poem). Each level may set a look,
a palette (a name links to the library; a list of swatches or {"swatches": [...]} is an own copy) and fonts per
role (Studio 1.0's [{"family", "role": "voice"|"command"}] list still reads). What a level doesn't set, or names
but the library doesn't have, comes from the level above.
"""
import copy
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path

from . import config
from .store import StoreError, read_text, write_text

ROLES = ("background", "text", "accent", "muted")
FONT_ROLES = ("display", "text", "label")
BUNDLED = Path(__file__).parent / "static" / "styles"
MIN_CONTRAST = 4.5          # WCAG AA for body text
HEX = re.compile(r"#[0-9A-Fa-f]{6}")
UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')       # not allowed in a file name
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
LEGACY_ROLES = {"voice": ("text",), "command": ("display", "label")}      # Studio 1.0's font roles
LEGACY_WEIGHTS = {"text": 400, "display": 900, "label": 700}

_bundled_cache = {}


# ——— values ———
def _key(name):
    return " ".join(name.split()).lower() if isinstance(name, str) and name.strip() else None


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            return None
    if not isinstance(v, (int, float)) or v != v:
        return None
    return int(v) if float(v).is_integer() else float(v)


def _name(name, what):
    """A palette or look name: 1-60 characters that also make a file name."""
    name = " ".join(name.split()) if isinstance(name, str) else ""
    if not 1 <= len(name) <= 60:
        raise StoreError(f"Give the {what} a name of 1 to 60 characters.")
    if UNSAFE.search(name):
        raise StoreError(f'A {what} name can\'t contain < > : " / \\ | ? or *.')
    stem = name.rstrip(". ")
    if not stem or stem.split(".")[0].upper() in RESERVED:
        raise StoreError(f"{name} can't be used as a {what} name; choose another.")
    return name


def swatches(items) -> list[dict]:
    """The usable swatches of a palette as stored (dicts with a #RRGGBB hex, or [name, hex] pairs), as they are."""
    out = []
    for c in items if isinstance(items, list) else []:
        if isinstance(c, (list, tuple)) and len(c) == 2:
            c = {"name": c[0], "hex": c[1]}
        if isinstance(c, dict) and isinstance(c.get("hex"), str) and HEX.fullmatch(c["hex"].strip()):
            out.append(dict(c))
    return out


COLOURS = {"background": "#0C0E11", "text": "#EEEAE2", "accent": "#DA291C", "muted": "#959AA2"}


def colours(items) -> dict:
    """A palette's background, text, accent and muted colours: each by its role, else the swatch in that place (first to
    fourth, the order of a palette without roles) when that swatch has no role of its own, else Studio's own.
    The same rule as Design.colours in design-core.js."""
    sw = swatches(items.get("swatches") if isinstance(items, dict) else items)
    out = {}
    for i, role in enumerate(COLOURS):
        by = next((s["hex"] for s in sw if s.get("role") == role), None)
        at = sw[i]["hex"] if i < len(sw) and not sw[i].get("role") else None
        out[role] = by or at or COLOURS[role]
    return out


def clean_swatches(items) -> list[dict]:
    """Swatches to save: 1-16 colours, #RRGGBB, each role at most once."""
    if not isinstance(items, list) or not 1 <= len(items) <= 16:
        raise StoreError("A palette has 1 to 16 colours.")
    out, seen = [], set()
    for c in items:
        if isinstance(c, (list, tuple)) and len(c) == 2:
            c = {"name": c[0], "hex": c[1]}
        if not isinstance(c, dict):
            raise StoreError("Each colour is a name and a hex code.")
        hexv = str(c.get("hex") or "").strip()
        if not HEX.fullmatch(hexv):
            raise StoreError(f"Not a colour: {hexv!r} (use #RRGGBB).")
        swatch = {"name": " ".join(str(c.get("name") or hexv).split())[:40] or hexv.upper(), "hex": hexv.upper()}
        role = c.get("role")
        if role not in (None, ""):
            if role not in ROLES:
                raise StoreError("A colour's role is background, text, accent or muted.")
            if role in seen:
                raise StoreError(f"Only one colour can be the {role}.")
            seen.add(role)
            swatch["role"] = role
        out.append(swatch)
    return out


def _font(f, weight=400):
    """A font role as stored, read leniently: {"family", "weight", "width"} or None."""
    if not isinstance(f, dict) or not isinstance(f.get("family"), str) or not f["family"].strip():
        return None
    w, wd = _number(f.get("weight")), _number(f.get("width"))
    return {"family": " ".join(f["family"].split()), "weight": w if w is not None and 1 <= w <= 1000 else weight,
            "width": wd if wd is not None and 50 <= wd <= 200 else None}


def _legacy_fonts(items):
    """Studio 1.0's font list as roles: the voice sets the text, the command sets display and label."""
    out = {}
    for f in items:
        if not isinstance(f, dict):
            continue
        for role in LEGACY_ROLES.get(f.get("role"), (f.get("role"),) if f.get("role") in FONT_ROLES else ()):
            out[role] = {"weight": LEGACY_WEIGHTS[role], **f}
    return out


def clean_font(role, f) -> dict:
    if not isinstance(f, dict) or not isinstance(f.get("family"), str) or not f["family"].strip():
        raise StoreError(f"The {role} font needs a family.")
    weight = _number(f.get("weight"))
    if weight is None or not 1 <= weight <= 1000:
        raise StoreError(f"The {role} font's weight is a number from 1 to 1000.")
    out = {"family": " ".join(f["family"].split())[:100], "weight": weight}
    if f.get("width") not in (None, ""):
        width = _number(f["width"])
        if width is None or not 50 <= width <= 200:
            raise StoreError(f"The {role} font's width is a percentage from 50 to 200.")
        out["width"] = width
    return out


def clean_fonts(fonts, every=True) -> dict:
    """Fonts per role to save. A look gives every role; a series or poem may give some."""
    if not isinstance(fonts, dict) or set(fonts) - set(FONT_ROLES):
        raise StoreError("Fonts are given per role: display, text and label.")
    if every and any(r not in fonts for r in FONT_ROLES):
        raise StoreError("A look needs a display, a text and a label font.")
    return {r: clean_font(r, fonts[r]) for r in FONT_ROLES if r in fonts}


# ——— colour ———
def _luminance(hexv):
    if not isinstance(hexv, str) or not HEX.fullmatch(hexv.strip()):
        raise StoreError(f"Not a colour: {hexv!r} (use #RRGGBB).")
    hexv = hexv.strip()

    def channel(i):
        c = int(hexv[i:i + 2], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)


def contrast(a: str, b: str) -> float:
    """The WCAG 2 contrast ratio of two colours, 1 to 21, to two decimals."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return round((hi + 0.05) / (lo + 0.05), 2)


def palette_warnings(p) -> list[str]:
    """Text and accent on the background, where they are under 4.5:1."""
    by_role = {}
    for s in swatches(p.get("swatches") if isinstance(p, dict) else p):
        by_role.setdefault(s.get("role"), s)
    bg, out = by_role.get("background"), []
    for role in ("text", "accent"):
        s = by_role.get(role)
        if bg is None or s is None:
            continue
        ratio = contrast(s["hex"], bg["hex"])
        if ratio < MIN_CONTRAST:
            out.append(f"{role.capitalize()} on background ({s.get('name') or s['hex']} on {bg.get('name') or bg['hex']}) "
                       f"is {ratio:g}:1; small text needs {MIN_CONTRAST:g}:1.")
    return out


def palette_from_image(data: bytes, n: int = 6) -> list[str]:
    """The image's main colours, most used first: a median cut to 2n colours, without near-duplicates (RGB distance
    24 or less from a colour already kept), at most n."""
    from PIL import Image
    n = max(1, min(int(n), 16))
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img.thumbnail((400, 400), Image.Resampling.NEAREST)   # nearest: no blended edge colours
        if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
            flat = Image.new("RGBA", img.size, (255, 255, 255, 255))
            flat.alpha_composite(img.convert("RGBA"))
            img = flat
        q = img.convert("RGB").quantize(colors=2 * n, method=Image.Quantize.MEDIANCUT)
    except Exception:  # noqa: BLE001 — anything Pillow can't open is not an image Studio can read
        raise StoreError("Studio can't read that image. Try a PNG or JPEG.") from None
    pal = q.getpalette() or []
    kept = []
    for count, i in sorted(q.getcolors(2 * n) or [], key=lambda c: -c[0]):
        rgb = tuple(pal[3 * i:3 * i + 3])
        if len(rgb) == 3 and all(sum((a - b) ** 2 for a, b in zip(rgb, k)) > 24 ** 2 for k in kept):
            kept.append(rgb)
    return ["#{:02X}{:02X}{:02X}".format(*rgb) for rgb in kept[:n]]


# ——— the library ———
def _read_dir(d: Path):
    """[(path, data)] for the readable .json files in a folder, data with a "name"."""
    out = []
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        if p.name.startswith("."):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data["name"] = " ".join(data["name"].split()) if isinstance(data.get("name"), str) and data["name"].strip() else p.stem
            out.append((p, data))
    return out


def _bundled(d: Path):
    """The starters in a folder of Studio's own (read once: they only change when Studio is updated)."""
    if d not in _bundled_cache:
        _bundled_cache[d] = {_key(data["name"]): data for _, data in _read_dir(d)}
    return copy.deepcopy(_bundled_cache[d])


class Styles:
    def __init__(self, library: Path, bundled: Path = BUNDLED):
        self.library = Path(library)
        self.bundled = Path(bundled)
        self.dir = self.library / "Styles"
        self._fonts = None

    # reading
    def _items(self, kind):
        """{name key: (data, source, edited)}: the starters, then the library's own files over them."""
        starters = _bundled(self.bundled / kind)
        out = {k: (data, "bundled", False) for k, data in starters.items()}
        for _, data in _read_dir(self.dir / kind):
            k = _key(data["name"])
            out[k] = (data, "own", k in starters)
        return out

    @staticmethod
    def _palette_out(data, source, edited):
        p = {"name": data["name"], "swatches": swatches(data.get("swatches"))}
        return {**p, "source": source, "edited": edited, "warnings": palette_warnings(p)}

    @staticmethod
    def _look_out(data, source, edited):
        fonts = data.get("fonts") if isinstance(data.get("fonts"), dict) else {}
        return {"name": data["name"], "palette": data.get("palette") if isinstance(data.get("palette"), str) else None,
                "fonts": {r: fonts[r] for r in FONT_ROLES if isinstance(fonts.get(r), dict)}, "source": source, "edited": edited}

    def _get(self, kind, name):
        found = self._items(kind).get(_key(name))
        if found is None:
            raise StoreError(f"No {kind[:-1]} called {' '.join(str(name or '').split()) or 'that'}.")
        return found

    def palettes(self) -> list[dict]:
        return [self._palette_out(*v) for _, v in sorted(self._items("palettes").items())]

    def palette(self, name) -> dict:
        return self._palette_out(*self._get("palettes", name))

    def looks(self) -> list[dict]:
        return [self._look_out(*v) for _, v in sorted(self._items("looks").items())]

    def look(self, name) -> dict:
        return self._look_out(*self._get("looks", name))

    # writing
    def _write(self, kind, name, data):
        k = _key(name)
        path = self.dir / kind / f"{name.rstrip('. ')}.json"
        old = [p for p, d in _read_dir(self.dir / kind) if _key(d["name"]) == k and p != path]
        write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        for p in old:      # the same name in another spelling (a case-sensitive file system)
            p.unlink(missing_ok=True)

    def _delete(self, kind, name):
        k = _key(name)
        own = [p for p, d in _read_dir(self.dir / kind) if _key(d["name"]) == k]
        if not own:
            self._get(kind, name)       # no such thing at all
            raise StoreError(f"Built-in {kind} can't be deleted. Editing one saves your own copy.")
        trash = self.dir / kind / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        for p in own:
            os.replace(p, trash / f"{p.stem} {datetime.now().strftime('%Y-%m-%d %H%M%S')}.json")

    def save_palette(self, p) -> dict:
        if not isinstance(p, dict):
            raise StoreError("A palette is a name and its colours.")
        name = _name(p.get("name"), "palette")
        self._write("palettes", name, {"name": name, "swatches": clean_swatches(p.get("swatches"))})
        return self.palette(name)

    def delete_palette(self, name):
        self._delete("palettes", name)

    def save_look(self, look) -> dict:
        """Saves a look; an unknown font family is saved too, with a warning."""
        if not isinstance(look, dict):
            raise StoreError("A look is a name, a palette and its fonts.")
        name = _name(look.get("name"), "look")
        if not isinstance(look.get("palette"), str) or not look["palette"].strip():
            raise StoreError("A look uses a palette from the library; choose one.")
        palette = self._get("palettes", look["palette"])[0]["name"]
        fonts = clean_fonts(look.get("fonts"))
        self._write("looks", name, {"name": name, "palette": palette, "fonts": fonts})
        return {**self.look(name), "warnings": self._font_warnings(fonts)}

    def delete_look(self, name):
        self._delete("looks", name)

    def _font_warnings(self, fonts):
        from . import fonts as font_registry
        if self._fonts is None:
            lib = self.library / "Styles" / "fonts"
            same = self.library.resolve() == Path(config.ART).resolve()
            self._fonts = font_registry.registry() if same else font_registry.Registry(font_registry.BUNDLED, lib)
        missing = dict.fromkeys(f["family"] for f in fonts.values() if self._fonts.get(f["family"]) is None)
        return [f"{family} isn't one of Studio's fonts, so it shows in a fallback font until you add it." for family in missing]

    def rules(self) -> str:
        return read_text(self.dir / "rules.md") or ""

    def save_rules(self, text) -> str:
        text = str(text or "").replace("\r\n", "\n")
        if text or (self.dir / "rules.md").exists():
            write_text(self.dir / "rules.md", text)
        return text

    # inheritance
    def resolve(self, levels: list[tuple[str, dict]]) -> dict:
        """The style in effect after `levels` (global first): {"look", "look_from", "palette": {"name", "swatches", "from",
        "linked"}, "fonts": {role: {"family", "weight", "width", "from"}}}. "look" (and "look_from", the level that set
        it) is None once nothing of it is left."""
        palettes, looks = self._items("palettes"), self._items("looks")
        first = levels[0][0] if levels else "global"
        out = {"look": None, "look_from": None, "palette": None, "fonts": {}}
        via = {}       # palette and each font role: True while it is the look's

        def use_look(data, pals, level):
            out["look"], out["look_from"] = data["name"], level
            fonts = data.get("fonts") if isinstance(data.get("fonts"), dict) else {}
            pal = pals.get(_key(data.get("palette")))
            if pal and swatches(pal[0].get("swatches")):
                out["palette"] = {"name": pal[0]["name"], "swatches": swatches(pal[0].get("swatches")), "from": level, "linked": True}
                via["palette"] = True
            for role in FONT_ROLES:
                f = _font(fonts.get(role))
                if f:
                    out["fonts"][role], via[role] = {**f, "from": level}, True

        # a floor under everything, should even the global look be gone: the default starter, as bundled
        starters = {k: (d, "bundled", False) for k, d in _bundled(self.bundled / "palettes").items()}
        default = _bundled(self.bundled / "looks").get(_key(config.DEFAULTS["default_look"]))
        if default:
            use_look(default, starters, first)
        for level, data in levels:
            data = data if isinstance(data, dict) else {}
            found = looks.get(_key(data.get("look")))
            if found:
                use_look(found[0], palettes, level)
            p = data.get("palette")
            if isinstance(p, str):
                found = palettes.get(_key(p))
                sw = swatches(found[0].get("swatches")) if found else []
                if sw:
                    out["palette"], via["palette"] = {"name": found[0]["name"], "swatches": sw, "from": level, "linked": True}, False
            elif isinstance(p, (list, dict)):
                sw = swatches(p.get("swatches") if isinstance(p, dict) else p)
                name = p.get("name") if isinstance(p, dict) and isinstance(p.get("name"), str) else None
                if sw:
                    out["palette"], via["palette"] = {"name": name, "swatches": sw, "from": level, "linked": False}, False
            fonts = data.get("fonts")
            fonts = _legacy_fonts(fonts) if isinstance(fonts, list) else fonts
            for role in FONT_ROLES if isinstance(fonts, dict) else ():
                f = _font(fonts.get(role))
                if f:
                    out["fonts"][role], via[role] = {**f, "from": level}, False
        if not any(via.values()):
            out["look"] = out["look_from"] = None
        if out["palette"] is None:
            out["palette"] = {"name": None, "swatches": [], "from": first, "linked": False}
        out["fonts"] = {r: out["fonts"][r] for r in FONT_ROLES if r in out["fonts"]}
        return out

    def detach(self, meta: dict, resolved: dict) -> dict:
        """`meta` with the style it resolves to as its own copy: the palette's swatches and every font, no look."""
        out = {k: v for k, v in meta.items() if k != "look"}
        pal = resolved["palette"]
        out["palette"] = {**({"name": pal["name"]} if pal.get("name") else {}), "swatches": copy.deepcopy(pal["swatches"])}
        out["fonts"] = {r: {"family": f["family"], "weight": f["weight"], **({"width": f["width"]} if f.get("width") is not None else {})}
                        for r, f in resolved["fonts"].items()}
        return out

    def link(self, meta: dict, look: str) -> dict:
        """`meta` following a look from the library again, without its own palette and fonts."""
        name = self.look(look)["name"]
        return {**{k: v for k, v in meta.items() if k not in ("look", "palette", "fonts")}, "look": name}


# ——— colours in designs ———
def _design_colours(design):
    """Every colour a design uses, once per use: background, and each element's fill, stroke, text colour and accent
    (a fill, stroke or background may be a gradient with stops). Values that aren't colours are skipped."""
    def colour(v):
        if isinstance(v, str):
            m = re.fullmatch(r"#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})", v.strip())
            if m:
                h = m.group(1)
                yield "#" + (h if len(h) == 6 else "".join(c * 2 for c in h)).upper()
        elif isinstance(v, dict):
            for stop in v.get("stops") if isinstance(v.get("stops"), list) else []:
                yield from colour(stop.get("c") if isinstance(stop, dict) else None)

    items = [design] + [e for e in design.get("elements") or [] if isinstance(e, dict)]
    for item in items:
        for key in ("background", "fill", "stroke", "color", "accent"):
            yield from colour(item.get(key))


def colours_used(design_files) -> list[dict]:
    """[{"hex", "count"}] for every colour in the given design files, most used first (ties by hex)."""
    counts = {}
    for f in design_files:
        try:
            design = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(design, dict):
            for hexv in _design_colours(design):
                counts[hexv] = counts.get(hexv, 0) + 1
    return [{"hex": h, "count": n} for h, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
