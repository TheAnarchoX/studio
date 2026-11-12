"""A test kit: the kit contract of docs/KITS.md, drawn with Pillow instead of a browser.

Each line of the poem is a filled rectangle (its "ink"), the name a thin bar under the poem. The concept "bars"
lays a red field behind the lines it marks; fields stay on the QA plate, the ink does not.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SCALE = 1
RATIOS = {"45": ("4x5", 1080, 1350, "Carousel 4x5", "Feed · 4:5")}
VARIANTS = [("1", "With name", ""), ("0", "Without name", "-noname")]
CHROME = sys.executable          # Studio checks that the browser exists; this kit never starts one

NIGHT, PAPER, RED = (12, 14, 17), (238, 234, 226), (218, 41, 28)
LEFT, TOP, ROW, GAP = 120, 200, 72, 40


def build_html(poem, out):
    out = Path(out)
    out.write_text("<!doctype html><html><head><meta charset=\"utf-8\"><title>carousel</title></head><body>"
                   f"<script>const POEM={json.dumps(poem, ensure_ascii=False)};</script></body></html>", encoding="utf-8")
    return out


def _poem(page_text):
    at = page_text.index("const POEM=") + len("const POEM=")
    return json.JSONDecoder().raw_decode(page_text, at)[0]


def shoot(page, n, r, sig, out, profile):
    text = Path(page).read_text(encoding="utf-8")
    plate = "color:transparent" in text.split("</head>", 1)[0]     # QA's plate: every letter invisible
    poem, (_, w, h, _, _) = _poem(text), RATIOS[r]
    slide = poem["slides"][n - 1]
    paper = slide.get("ground") == "paper"
    ground, ink = (PAPER, NIGHT) if paper else (NIGHT, PAPER)
    marked = slide.get("mark", list(range(len(poem["lines"])))) if slide["concept"] == "bars" else []
    im = Image.new("RGB", (w * SCALE, h * SCALE), ground)
    d = ImageDraw.Draw(im)
    s = SCALE
    for i, line in enumerate(poem["lines"]):
        top, width = TOP + i * (ROW + GAP), min(w - 2 * LEFT, 60 + 26 * len(line))
        if i in marked:
            d.rectangle((s * (LEFT - 20), s * (top - 14), s * (LEFT + width + 20) - 1, s * (top + ROW + 14) - 1), fill=RED)
        if not plate:
            d.rectangle((s * LEFT, s * top, s * (LEFT + width) - 1, s * (top + ROW) - 1), fill=ink)
    if sig == "1" and not plate:
        d.rectangle((s * LEFT, s * (h - 180), s * (LEFT + 320) - 1, s * (h - 150) - 1), fill=ink)
    im.save(out)


def contact_sheet(title, rows, out):
    th, gut = 260, 24
    widest = max(len(items) for items in rows.values())
    sheet = Image.new("RGB", (gut + widest * (th * 4 // 5 + gut), gut + len(rows) * (th + gut)), NIGHT)
    for y, items in enumerate(rows.values()):
        for x, (_, png) in enumerate(items):
            with Image.open(png) as im:
                sheet.paste(im.convert("RGB").resize((th * 4 // 5, th)), (gut + x * (th * 4 // 5 + gut), gut + y * (th + gut)))
    sheet.save(out)
    return out


def concept_names(poem):
    return [s.get("label") or s["concept"].replace("-", " ").title() for s in poem["slides"]]
