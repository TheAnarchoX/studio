"""Pixel QA on the rendered slides: measure the ink, not the font boxes.

For every slide x format, a "plate" is shot: the same page with all text transparent, so the plate
holds the fields, bars, rules and lines but no letters. Ink is whatever differs from the plate.
From that mask: rows of text, their left and right ink edges, which edges share a column, which
miss one by a few pixels, margins, story safe zones, phone-size legibility, and whether the unsigned
version differs from the signed one only in the name. All measures are in slide pixels (1080 wide).
"""
import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from .kit import FORMAT_LABEL
from .store import CHECK_DEFAULTS, write_text

INK = 56            # max channel difference from the plate that counts as ink (about half coverage)
DEFAULT_CHECKS = CHECK_DEFAULTS   # align / near px, phone width, smallest text at phone width, story top / bottom px


def _ck(checks):
    return {**DEFAULT_CHECKS, **(checks or {})}


def _load(path):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.int16)


def _diff(a, b):
    return np.abs(a - b).max(axis=2) > INK


def _runs(flags):
    d = np.diff(np.concatenate(([0], flags.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def _rows(mask):
    """Horizontal bands of ink; specks (i-dots, accents) join the band they belong to."""
    rows = [list(r) for r in _runs(mask.any(axis=1))]
    changed = True
    while changed and len(rows) > 1:
        changed = False
        for i, (y0, y1) in enumerate(rows):
            h = y1 - y0
            cands = []
            if i > 0:
                cands.append((y0 - rows[i - 1][1], i - 1))
            if i + 1 < len(rows):
                cands.append((rows[i + 1][0] - y1, i + 1))
            gap, j = min(cands)
            hj = rows[j][1] - rows[j][0]
            if h < 0.35 * hj and gap < 0.5 * hj:
                rows[j] = [min(rows[j][0], y0), max(rows[j][1], y1)]
                del rows[i]
                changed = True
                break
    return [tuple(r) for r in rows]


def _segments(mask, plate, y0, y1):
    """Runs of ink along a row, split at wide gaps and wherever the field underneath changes."""
    h = y1 - y0
    runs = _runs(mask[y0:y1].any(axis=0))
    if not runs:
        return []
    ym = (y0 + y1) // 2
    segs = [list(runs[0])]
    for x0, x1 in runs[1:]:
        g0, g1 = segs[-1][1], x0
        field_changes = np.abs(plate[ym, g0] - plate[ym, g1 - 1]).max() > INK
        if g1 - g0 >= 0.6 * h or field_changes:
            segs.append([x0, x1])
        else:
            segs[-1][1] = x1
    out = []
    for x0, x1 in segs:
        ys = np.flatnonzero(mask[y0:y1, x0:x1].any(axis=1))
        out.append((x0, x1, y0 + int(ys[0]), y0 + int(ys[-1]) + 1))
    return out


def _columns(edges, s, checks=None):
    """edges: [(x_slide_px, row_no)] -> columns (2+ edges within ALIGN of each other) and near misses."""
    ALIGN, NEAR = _ck(checks)["align"], _ck(checks)["near"]
    cols, cur = [], []
    for x, row in sorted(edges):
        if cur and x - cur[-1][0] > ALIGN:
            cols.append(cur)
            cur = []
        cur.append((x, row))
    if cur:
        cols.append(cur)
    columns = [{"x": round(sum(x for x, _ in c) / len(c), 1), "rows": sorted({r for _, r in c}),
                "spread": round(c[-1][0] - c[0][0], 1)} for c in cols if len(c) >= 2]
    near = []
    for x, row in edges:
        best = None
        for c in columns:
            off = abs(x - c["x"])
            if row not in c["rows"] and ALIGN < off <= NEAR and (best is None or off < best[1]):
                best = (c["x"], off)
        if best:
            near.append({"row": row, "x": x, "column": best[0], "off": round(best[1], 1)})
    return columns, near


def _analyse(img, plate, size, scale, story, checks=None):
    """Rows, segments, margins and columns of one image measured against its plate."""
    W, H = size
    ck = _ck(checks)
    ALIGN = ck["align"]
    if img.shape != plate.shape:
        return {"issues": [{"level": "fail", "text": "image and plate sizes differ"}]}, None
    mask = _diff(img, plate)
    if not mask.any():
        return {"rows": [], "issues": [{"level": "fail", "text": "no text found on the slide"}]}, mask
    px = lambda v: round(v / scale, 1)  # noqa: E731
    issues, rows = [], []
    for i, (y0, y1) in enumerate(_rows(mask), 1):
        segs = [{"left": px(x0), "right": px(x1), "top": px(t), "bottom": px(b), "_box": (x0, x1, t, b)}
                for x0, x1, t, b in _segments(mask, plate, y0, y1)]
        rows.append({"row": i, "top": px(y0), "bottom": px(y1), "segments": segs})
        if story:
            over_top, over_bot = ck["story_top"] - y0 / scale, y1 / scale - (H - ck["story_bottom"])
            for over, where in ((over_top, f"top {ck['story_top']:g}"), (over_bot, f"bottom {ck['story_bottom']:g}")):
                if over > 6:
                    issues.append({"level": "fail", "text": f"row {i} reaches {round(over, 1)} px into the story's "
                                   f"{where} px (the story UI covers it)"})
                elif over > 1:
                    issues.append({"level": "warn", "text": f"row {i} crosses the story's {where} px line by "
                                   f"{round(over, 1)} px (round letters overshooting?)"})
    yy, xx = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    margins = {"left": px(xx[0]), "right": round(W - (xx[-1] + 1) / scale, 1),
               "top": px(yy[0]), "bottom": round(H - (yy[-1] + 1) / scale, 1)}
    for side, m in margins.items():
        if m < 0.5:
            issues.append({"level": "warn", "text": f"text touches the {side} edge of the frame "
                           "(cut off, or meant to bleed?)"})
    edges = {"left": [(s["left"], r["row"]) for r in rows for s in r["segments"]],
             "right": [(s["right"], r["row"]) for r in rows for s in r["segments"]]}
    columns = {}
    for side, e in edges.items():
        cols, near = _columns(e, scale, ck)
        columns[side] = cols
        for n in near:
            issues.append({"level": "warn", "text": f"row {n['row']} {side} edge at {n['x']} is {n['off']} px "
                           f"off the {side} column at {n['column']}"})
        for c in cols:
            if c["spread"] > ALIGN:
                issues.append({"level": "warn", "text": f"{side} column at {c['x']} spreads {c['spread']} px"})
    return {"margins": margins, "centre_offset": round((xx[0] + xx[-1] + 1) / 2 / scale - W / 2, 1),
            "rows": rows, "columns": columns, "issues": issues}, mask


def _legibility(m, size, scale, checks=None):
    PHONE, MIN_PHONE = _ck(checks)["phone"], _ck(checks)["min_phone"]
    smallest = None
    for r in m.get("rows", []):
        for s in r["segments"]:
            x0, x1, t, b = s["_box"]
            h = (b - t) / scale * PHONE / size[0]
            if smallest is None or h < smallest[0]:
                smallest = (round(h, 1), r["row"], s.get("name", False))
    m["smallest_at_phone"] = smallest[0] if smallest else None
    if smallest and smallest[0] < MIN_PHONE:
        what = "the name" if smallest[2] else f"row {smallest[1]}"
        m["issues"].append({"level": "warn", "text": f"{what} is {smallest[0]} px tall at phone width ({PHONE} px)"})


def measure(signed, unsigned, size, scale, story=False, checks=None):
    """signed / unsigned: (image path, plate path) or None. Returns {True: measures, False: measures}."""
    out, masks = {}, {}
    for key, pair in ((True, signed), (False, unsigned)):
        if pair and Path(pair[0]).exists():
            out[key], masks[key] = _analyse(_load(pair[0]), _load(pair[1]), size, scale, story, checks)
    if True in out and False in out and masks[True] is not None and masks[False] is not None:
        a, ma, mb = out[True], masks[True], masks[False]
        boxes = []
        for r in a.get("rows", []):
            for s in r["segments"]:
                x0, x1, t, b = s["_box"]
                ink = int(ma[t:b, x0:x1].sum())
                if ink and mb[t:b, x0:x1].sum() < 0.05 * ink:
                    s["name"] = True
                    boxes.append(s["_box"])
        rest = np.ones(ma.shape, bool)
        for x0, x1, t, b in boxes:
            rest[t:b, x0:x1] = False
        moved = (ma ^ mb) & rest
        if not moved.any() and not boxes:
            a["issues"].append({"level": "warn", "text": "signed and unsigned versions look the same (no name?)"})
        crowded, shifted = [], []
        for r in a.get("rows", []):
            t, b = round(r["top"] * scale), round(r["bottom"] * scale)
            band = moved[t:b]
            if band.sum() <= 0.01 * max(1, int(ma[t:b].sum())):
                continue
            removed = int((ma[t:b] & ~mb[t:b] & rest[t:b]).sum())
            pad = (b - t) // 2   # a row that moved lands just outside its own band
            t2, b2 = max(0, t - pad), b + pad
            added = int((mb[t2:b2] & ~ma[t2:b2] & rest[t2:b2]).sum())
            stays = (ma[t:b] & mb[t:b] & rest[t:b]).any()
            # ink that only disappears, inside a row whose text stays: the name, too close to the poem
            (crowded if added <= 0.02 * removed and stays else shifted).append(r["row"])
        for row in crowded:
            a["issues"].append({"level": "fail", "text": f"the name runs into the text of row {row} "
                                "(they touch or nearly touch)"})
        if shifted or (not crowded and moved.sum() > 0.005 * max(1, int((ma & rest).sum()))):
            what = f"rows {_span(shifted)} move or resize" if shifted else "the text moves or resizes"
            a["issues"].append({"level": "warn", "text": f"the layout isn't identical without the name: {what} "
                                "in the unsigned version"})
    for key, m in out.items():
        _legibility(m, size, scale, checks)
        for r in m.get("rows", []):
            for s in r["segments"]:
                s.pop("_box", None)
    return out


def _span(nums):
    nums = sorted(nums)
    if not nums:
        return "?"
    parts, start = [], nums[0]
    for a, b in zip(nums, nums[1:] + [None]):
        if b != a + 1:
            parts.append(f"{start}" if start == a else f"{start}-{a}")
            start = b
    return ", ".join(parts)


def run(store, ref, slides=None, formats=None, workers=4):
    """Measure every rendered image of a poem (or the chosen slides/formats). Saves qa.json."""
    folder = store.resolve(ref)
    poem = store.load(folder)
    kit = store.kit(folder)
    scale = kit.scale()
    checks = store.series_meta(folder.parent)["checks"]
    n_all = range(1, len(poem.get("slides") or []) + 1)
    pairs = [(n, r) for r in kit.formats() if not formats or r in formats
             for n in n_all if not slides or n in slides]
    pairs = [(n, r) for n, r in pairs if kit.png(folder, poem, n, r, True).exists()
             or kit.png(folder, poem, n, r, False).exists()]
    if not pairs:
        raise ValueError("nothing rendered to check yet; render first")
    cache = store.cache / "plates" / re.sub(r"[^\w.-]+", "_", store.pid(folder))
    wanted = [(n, r, sg) for n, r in pairs for sg in (True, False) if kit.png(folder, poem, n, r, sg).exists()]
    plates = kit.plates(folder, poem, wanted, cache, workers)
    names = kit.slide_names(poem)

    old = folder / "qa.json"
    report = {"poem": store.pid(folder), "when": datetime.now().isoformat(timespec="seconds"), "images": {}}
    if old.exists():
        try:
            report["images"] = {k: v for k, v in json.loads(old.read_text(encoding="utf-8")).get("images", {}).items()
                                if (folder / v.get("file", "")).exists()}
        except (ValueError, AttributeError):
            pass
    for n, r in pairs:
        imgs = {sg: kit.png(folder, poem, n, r, sg) for sg in (True, False)}
        got = measure(*[(imgs[sg], plates[(n, r, sg)]) if (n, r, sg) in plates else None for sg in (True, False)],
                      kit.size(r), scale, story=(r == "916"), checks=checks)
        for sg, m in got.items():
            img = imgs[sg]
            report["images"][img.stem] = {"file": img.relative_to(folder).as_posix(), "v": int(img.stat().st_mtime),
                                          "slide": n, "concept": poem["slides"][n - 1]["concept"],
                                          "name": names[n - 1], "format": FORMAT_LABEL.get(r, r), "signed": sg, **m}
    write_text(folder / "qa.json", json.dumps(report, ensure_ascii=False, indent=1))
    report["checked"] = [kit.png(folder, poem, n, r, s).stem for n, r in pairs for s in (True, False)
                         if kit.png(folder, poem, n, r, s).exists()]
    return report


def summary(report):
    """The report as short text for Claude: one line per image, issues indented below."""
    out, fails, warns = [], 0, 0
    for key in report.get("checked", report["images"]):
        im = report["images"][key]
        variant = "signed" if im["signed"] else "unsigned"
        head = f"{im['format']} slide {im['slide']} {im['name']} ({variant})"
        if "margins" in im:
            m = im["margins"]
            cols = []
            for side in ("left", "right"):
                for c in im["columns"][side]:
                    cols.append(f"{side} column x={c['x']} rows {','.join(map(str, c['rows']))}")
            head += (f": margins L{m['left']} R{m['right']} T{m['top']} B{m['bottom']}, {len(im['rows'])} rows, "
                     f"smallest {im['smallest_at_phone']} px at phone width"
                     + (f", {'; '.join(cols)}" if cols else ""))
        issues = im.get("issues", [])
        head += "  OK" if not issues else ""
        out.append(head)
        for i in issues:
            fails += i["level"] == "fail"
            warns += i["level"] == "warn"
            out.append(f"    {i['level'].upper()}: {i['text']}")
    out.insert(0, f"QA {report['poem']}: {len(report.get('checked', []))} images, {fails} fail, {warns} warn. "
                  "Measures are slide px (1080 wide), on the ink. Full detail in qa.json.")
    return "\n".join(out)
