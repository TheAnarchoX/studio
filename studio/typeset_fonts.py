"""Static font faces for Typst. Typst sets a variable font only at its default instance, so for each role in a
book's design (text, heading) this module cuts real regular, bold, italic and bold italic faces at the weight and
optical size the design asks for, renames them to a family of their own ("Literata Text"), and gathers exactly those
files in one folder for the compiler. Cutting a face takes seconds, so every face is cached on disk."""
import hashlib
import os
import shutil
import threading
import time
import unicodedata
from collections import namedtuple
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

from . import fonts

FALLBACK = "Literata"   # bundled and OFL, so it is always there and may always be embedded

Face = namedtuple("Face", "role family internal style weight path problems")

STYLES = ("regular", "bold", "italic", "bold italic")
SUBFAMILY = {"regular": "Regular", "bold": "Bold", "italic": "Italic", "bold italic": "Bold Italic"}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _resolve(role, spec, reg):
    """The family a role is set in: the one asked for, or FALLBACK with a problem saying why."""
    name = str(spec.get("family") or FALLBACK)
    fam = reg.get(name)
    problem = None
    if fam is None:
        problem = f"{name} was not found: {role} is set in {FALLBACK}"
    elif not fam.embeddable:
        problem = f"{name} may not be embedded: {role} is set in {FALLBACK}"
    if problem:
        fam = reg.get(FALLBACK)
        return fam, problem
    return fam, None


def _weights(fam, regular):
    """The regular and bold weights: the role's weight, and 700 or the nearest the family has."""
    lo, hi = fam.wght
    reg_w = int(_clamp(regular, lo, hi))
    bold_w = int(_clamp(700, lo, hi))
    if fam.wght[0] == fam.wght[1] or all(not f.axes.get("wght") for f in fam.files):
        have = sorted({f.weight for f in fam.files})
        reg_w = min(have, key=lambda w: abs(w - regular))
        bold_w = min(have, key=lambda w: abs(w - 700))
    return reg_w, bold_w


# Cutting an instance takes seconds, so a design tweak must not cut a new one each time. The optical size
# changes a face only subtly, so it snaps to the nearest of a few sizes (the larger on a tie) and ordinary size
# changes reuse the faces already cut.
OPSZ_BUCKETS = (7, 9, 11, 14, 18, 24, 36, 60)


def _bucket(opsz):
    return min(OPSZ_BUCKETS, key=lambda b: (abs(b - opsz), -b))


def _location(src, weight, opsz):
    loc = {tag: default for tag, (_, default, _) in src.axes.items()}
    if "wght" in src.axes:
        lo, _, hi = src.axes["wght"]
        loc["wght"] = _clamp(weight, lo, hi)
    if "opsz" in src.axes:
        lo, _, hi = src.axes["opsz"]
        loc["opsz"] = _clamp(_bucket(opsz), lo, hi)
    return loc


def _rename(tt, internal, style, weight):
    sub = SUBFAMILY[style]
    bold, italic = "bold" in style, "italic" in style
    name = tt["name"]
    for nid in (1, 2, 4, 6, 16, 17, 25):
        name.removeNames(nameID=nid)
    name.setName(internal, 1, 3, 1, 0x409)
    name.setName(sub, 2, 3, 1, 0x409)
    name.setName(f"{internal} {sub}", 4, 3, 1, 0x409)
    name.setName(f"{internal}-{sub}".replace(" ", ""), 6, 3, 1, 0x409)
    os2 = tt["OS/2"]
    os2.usWeightClass = int(weight)
    sel = os2.fsSelection & ~((1 << 0) | (1 << 5) | (1 << 6))
    if italic:
        sel |= 1 << 0
    if bold:
        sel |= 1 << 5
    if not italic and not bold:
        sel |= 1 << 6
    os2.fsSelection = sel
    tt["head"].macStyle = (1 if bold else 0) | (2 if italic else 0)


def _settle(tmp, dest, tries=8):
    """Move a finished temp file onto its final name. Files only ever appear under their final name whole, so if
    Windows refuses because another prepare has the destination open, a destination that exists is the winner's
    complete face: ours is dropped. Otherwise wait a moment and try again."""
    for attempt in range(tries):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if dest.exists():
                return
            if attempt == tries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def _cut(src, loc, internal, style, weight, dest):
    tt = TTFont(src.path, fontNumber=src.index if src.collection else -1, lazy=False)
    if "fvar" in tt:
        tt = instancer.instantiateVariableFont(tt, loc, updateFontNames=False)
    _rename(tt, internal, style, weight)
    # A name of its own per call, so two prepares cutting the same face never share a half-written file.
    tmp = dest.with_name(f"{dest.stem}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        tt.save(tmp)
        _settle(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def _key(src, loc, internal, style):
    st = src.path.stat()
    raw = repr((str(src.path), st.st_mtime_ns, st.st_size, src.index, sorted(loc.items()), internal, style))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def prepare(roles: dict, cache: Path, on_cut=None) -> dict:
    """Cut (or find cached) the four faces of every role and gather them in a folder of their own. `on_cut(family)`,
    when given, is called before a family's first face that isn't cached yet is cut: cutting takes seconds a face, so
    the caller can say what it waits for."""
    reg = fonts.registry()
    store = Path(cache) / "typeset-fonts"
    store.mkdir(parents=True, exist_ok=True)
    names, faces, problems = {}, [], []
    for role, spec in roles.items():
        fam, problem = _resolve(role, spec, reg)
        if problem:
            problems.append(problem)
        internal = f"{fam.name} {role.capitalize()}"
        names[role] = internal
        reg_w, bold_w = _weights(fam, float(spec.get("weight", 400)))
        opsz = float(spec.get("opsz", 0) or 0)
        if not fam.italic:
            problems.append(f"{fam.name} has no italic: italics are set upright")
        if bold_w < 600:
            problems.append(f"{fam.name} has no bold: bold is set at {bold_w}")
        for style in STYLES:
            weight = bold_w if "bold" in style else reg_w
            src = fam.file_for("italic" in style, weight)
            loc = _location(src, weight, opsz)
            if not src.axes:
                weight = src.weight
            path = store / (_key(src, loc, internal, style) + ".ttf")
            if not path.exists():
                if on_cut is not None:
                    on_cut(fam.name)
                _cut(src, loc, internal, style, weight, path)
            faces.append(Face(role, fam.name, internal, style, weight, path, []))
    sets = store / "sets"
    folder = sets / hashlib.sha1("\n".join(sorted(f.path.name for f in faces)).encode()).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    for f in faces:
        link = folder / f.path.name
        if link.exists():
            continue
        try:
            os.link(f.path, link)
        except FileExistsError:
            pass    # another prepare linked it between our check and our link
        except OSError:
            # No hard links here: copy through a file of its own, so a half-copied face is never seen as present.
            tmp = link.with_name(f"{link.stem}.{os.getpid()}.{threading.get_ident()}.part")
            try:
                for attempt in range(8):
                    try:
                        shutil.copy2(f.path, tmp)
                        break
                    except PermissionError:     # the source is being replaced by another prepare
                        if attempt == 7:
                            raise
                        time.sleep(0.05 * (attempt + 1))
                _settle(tmp, link)
            finally:
                tmp.unlink(missing_ok=True)
    return {"folder": folder, "names": names, "faces": faces, "problems": problems}


def _cmap(face):
    with TTFont(face.path, lazy=True) as tt:
        return set(tt.getBestCmap() or {})


def covers(faces: list, text: str) -> dict:
    """Characters of the text that a role's regular face has no glyph for, as {char: role}."""
    have = {f.role: _cmap(f) for f in faces if f.style == "regular"}
    missing = {}
    for ch in text:
        if ch in missing or unicodedata.category(ch)[0] in "CZ":
            continue
        for role, cmap in have.items():
            if ord(ch) not in cmap:
                missing[ch] = role
                break
    return missing


def has_smallcaps(face: Face) -> bool:
    """Whether the face's GSUB offers the smcp feature."""
    with TTFont(face.path, lazy=True) as tt:
        gsub = tt["GSUB"].table if "GSUB" in tt else None
        if gsub is None or gsub.FeatureList is None:
            return False
        return any(r.FeatureTag == "smcp" for r in gsub.FeatureList.FeatureRecord)
