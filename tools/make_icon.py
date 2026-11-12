"""Studio's icon: the S of the wordmark (Newsreader 600) with its red dot, on the app's background.

Run from the repo: .venv\\Scripts\\python tools\\make_icon.py
Writes studio/static/icons/: studio.ico (16-256) and PNGs for the web app.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "studio" / "static" / "fonts" / "Newsreader-VF.ttf"
OUT = ROOT / "studio" / "static" / "icons"
BG, PAPER, RED = "#141619", "#EEEAE2", "#DA291C"


def draw(n, dot_ratio=.36, radius=.2):
    """One icon at n x n px, drawn 8x larger and scaled down. dot_ratio = red dot diameter / S ink height."""
    k = 8
    N = n * k
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, N - 1, N - 1], radius=round(N * radius), fill=BG)
    # small icons get a larger letter so it stays readable
    ink_h = N * (0.62 if n >= 48 else 0.66 if n >= 24 else 0.70)
    font = ImageFont.truetype(str(FONT), 1000)
    font.set_variation_by_axes([600, 24])           # weight 600, optical size 24 (as the wordmark renders)
    x0, y0, x1, y1 = font.getbbox("S", anchor="ls")  # ink box relative to the baseline origin
    size = 1000 * ink_h / (y1 - y0)
    font = ImageFont.truetype(str(FONT), round(size))
    font.set_variation_by_axes([600, 24])
    x0, y0, x1, y1 = font.getbbox("S", anchor="ls")
    s_w, s_h = x1 - x0, y1 - y0
    dot = s_h * dot_ratio
    if n <= 24:
        dot = max(dot, N * 0.16)                     # at taskbar sizes the square must not vanish
    gap = s_h * 0.09
    total = s_w + gap + dot
    left = (N - total) / 2                           # centred on the ink, not the font box
    top = (N - s_h) / 2 - N * 0.01                   # optical centre, a touch high
    d.text((left - x0, top - y0), "S", font=font, fill=PAPER, anchor="ls")
    dx = left + s_w + gap
    d.ellipse([dx, top + s_h - dot, dx + dot, top + s_h], fill=RED)     # a round dot, its bottom on the S's ink bottom
    return im.resize((n, n), Image.LANCZOS)


def main(dot_ratio=.36):
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    frames = {n: draw(n, dot_ratio) for n in sizes}
    frames[256].save(OUT / "studio.ico", sizes=[(n, n) for n in sizes], append_images=[frames[n] for n in sizes[:-1]])
    for n in (16, 32, 48, 180, 192, 512):
        (frames.get(n) or draw(n, dot_ratio)).save(OUT / f"icon-{n}.png")
    draw(1024, dot_ratio).save(OUT / "studio.icns", sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)])
    print("wrote", OUT)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else .36)
