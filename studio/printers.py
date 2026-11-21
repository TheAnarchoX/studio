"""Print-on-demand printers: what each one prints and what it asks of a book's pages.

Spec: docs/superpowers/specs/2026-11-13-books-part-2-design.md ("Printers"). The print checks (preflight.py) hold a
book's page count, trim size and margins against its printer's profile, and the design panel lists the printers. The
numbers are the services' own, read from their pages on the date in `checked`; a number that couldn't be confirmed
there says so beside it.

Each profile:
  name      the printer as the author knows it
  url       the service's own specification page
  checked   when the numbers were read from it
  trims     the sizes it prints, (width, height) in mm, or None for any size
  bleed     mm added to the trimmed edges when the art runs off the page (the cover's concern for now)
  min       the smallest outside, top and bottom margins in mm, for a book without bleed
  inside    the smallest inside margin by page count: [(up to this many pages, mm), …]; None for "and more"
  pages     (fewest, most, multiple) pages; None where there is no limit
  paper     the thickness of one page in mm (for the spine), per paper; None where the service gives no figure
Optional:
  pages_by_paper   a narrower page range on one paper
  custom           sizes the service prints to order: per paper, ((narrowest, widest), (shortest, tallest)) in mm
  margins_advised  True when the margins are the service's recommendation, not a rule it enforces: the print checks
                   then warn about narrower ones instead of failing them
"""
from __future__ import annotations

import math

TOLERANCE = 0.6         # mm either way that still counts as the printer's size (a trim set in inches, rounded in mm)
_IN = 25.4


def _inches(*sizes) -> list:
    """Trim sizes given in inches (as the services list them), in mm."""
    return [(w * _IN, h * _IN) for w, h in sizes]


PRINTERS = {
    # Amazon KDP, read on 2026-11-13 (black ink, US marketplace):
    #   trim sizes, bleed, margins and page counts: https://kdp.amazon.com/en_US/help/topic/GVBQ3CMEQW3W2VL6
    #   paper thickness for the spine (cover):      https://kdp.amazon.com/en_US/help/topic/G201953020
    # KDP's large trims print fewer pages (8.25 × 6 and 8.25 × 8.25 in: 800 on white; 8.5 × 8.5 and 8.5 × 11 in: 590;
    # 8.27 × 11.69 in: 780); the profile keeps the range of the book sizes. The kdp.amazon.co.jp sizes are left out.
    "kdp": {
        "name": "Amazon KDP",
        "url": "https://kdp.amazon.com/en_US/help/topic/GVBQ3CMEQW3W2VL6",
        "checked": "2026-11-13",
        "trims": _inches((5, 8), (5.06, 7.81), (5.25, 8), (5.5, 8.5), (6, 9), (6.14, 9.21), (6.69, 9.61), (7, 10),
                         (7.44, 9.69), (7.5, 9.25), (8, 10), (8.25, 6), (8.25, 8.25), (8.5, 8.5), (8.5, 11),
                         (8.27, 11.69)),
        "bleed": 3.2,                                               # 0.125 in
        "min": {"outside": 6.4, "top": 6.4, "bottom": 6.4},         # 0.25 in without bleed (0.375 in with it)
        "inside": [(150, 9.6), (300, 12.7), (500, 15.9), (700, 19.1), (828, 22.3)],   # 0.375 to 0.875 in
        # 24 to 828 pages on white paper. KDP's page doesn't ask for an even count (it isn't confirmed there);
        # Studio makes every book's total even anyway.
        "pages": (24, 828, 2),
        "pages_by_paper": {"cream": (24, 776, 2)},
        "paper": {"white": 0.0572, "cream": 0.0635},                # 0.002252 and 0.0025 in a page
    },
    # IngramSpark, read on 2026-11-13: its File Creation Guide (dated 24 August 2026), black and white text,
    #   https://www.ingramspark.com/hubfs/downloads/file-creation-guide.pdf
    # The guide recommends a margin of at least 0.5 in on every side (a recommendation: `margins_advised`) and has no
    # inside margin by page count, so the inside minimum is that 0.5 in at any length. Pages: 18 to 1,200 on 50 lb
    # white, 18 to 1,050 on creme, stored divisible by two. Trim sizes: its US bleed chart and trim size matrix
    # (perfect bound); other sizes are printed to order within `custom`. 5.5 × 8.38 in is not confirmed: it is read
    # from the matrix, whose text comes out garbled, and the bleed chart doesn't list it. Paper thickness: not
    # confirmed (the guide gives none; IngramSpark's spine comes from its cover template generator), so it is left
    # empty rather than guessed.
    "ingramspark": {
        "name": "IngramSpark",
        "url": "https://www.ingramspark.com/hubfs/downloads/file-creation-guide.pdf",
        "checked": "2026-11-13",
        "trims": _inches((4, 6), (4, 7), (4.25, 7), (4.37, 7), (4.72, 7.48), (5, 7), (5, 8), (5.06, 7.81), (5.25, 8),
                         (5.5, 7.5), (5.5, 8.25), (5.5, 8.38),          # 5.5 × 8.38 in: not confirmed (above)
                         (5.5, 8.5), (5.83, 8.27), (6, 9), (6.14, 9.21),
                         (6.5, 6.5), (6.625, 10.25), (6.69, 9.61), (7, 10), (7.44, 9.69), (7.5, 9.25), (8, 8), (8, 10),
                         (8, 10.88), (8.25, 10.75), (8.25, 11), (8.268, 11.693), (8.5, 8.5), (8.5, 9), (8.5, 11),
                         (11, 8.5)),
        "bleed": 3.2,                                               # 0.125 in (the guide: 3 mm)
        "min": {"outside": 12.7, "top": 12.7, "bottom": 12.7},      # 0.5 in (the guide: 13 mm)
        "inside": [(None, 12.7)],
        "margins_advised": True,
        "pages": (18, 1200, 2),
        "pages_by_paper": {"cream": (18, 1050, 2)},
        "paper": {"white": None, "cream": None},
        "custom": {"white": ((4 * _IN, 8.5 * _IN), (6 * _IN, 11 * _IN)),
                   "cream": ((4 * _IN, 6.14 * _IN), (6 * _IN, 9.252 * _IN))},
    },
    # Any other printer: only what can't be assumed (spec, "Printers"): margins of at least 10 mm and an even page
    # count. The printer's own specification decides the rest. The 10 mm is Studio's guess, not a printer's rule, so
    # it is advice (`margins_advised`).
    "other": {
        "name": "Other printer",
        "url": None,
        "checked": "2026-11-13",
        "trims": None,
        "bleed": 3.0,
        "min": {"outside": 10, "top": 10, "bottom": 10},
        "inside": [(None, 10)],
        "margins_advised": True,
        "pages": (None, None, 2),
        "paper": {"white": None, "cream": None},
    },
}


def profile(printer: str) -> dict:
    """The printer's profile; a name Studio doesn't know reads as another printer."""
    return PRINTERS.get(printer) or PRINTERS["other"]


def inside_min(printer: str, pages: int) -> float:
    """The smallest inside margin (mm) the printer takes for a book of this many pages; past its last row, that
    row's."""
    rows = profile(printer)["inside"]
    for most, mm in rows:
        if most is None or pages <= most:
            return mm
    return rows[-1][1]


def page_range(printer: str, paper: str | None = None) -> tuple:
    """(fewest, most, multiple) pages on this paper; None where there is no limit."""
    p = profile(printer)
    return tuple((p.get("pages_by_paper") or {}).get(paper) or p["pages"])


def offers(printer: str, w: float, h: float) -> bool:
    """Whether the printer prints this trim size (within TOLERANCE mm either way)."""
    trims = profile(printer)["trims"]
    return trims is None or any(abs(w - tw) <= TOLERANCE and abs(h - th) <= TOLERANCE for tw, th in trims)


def custom(printer: str, w: float, h: float, paper: str | None = None) -> bool:
    """Whether the printer prints this size to order on this paper (outside its list of sizes)."""
    ranges = (profile(printer).get("custom") or {}).get(paper or "white")
    if not ranges:
        return False
    (w0, w1), (h0, h1) = ranges
    return w0 - TOLERANCE <= w <= w1 + TOLERANCE and h0 - TOLERANCE <= h <= h1 + TOLERANCE


def trim_name(w: float, h: float) -> str:
    """A trim size the way it is sold: in millimetres when both sides are whole millimetres (135 × 210 mm, A4),
    otherwise in inches (5.5 × 8.5 in)."""
    if all(abs(x - round(x)) < 0.05 for x in (w, h)):
        return f"{round(w):g} × {round(h):g} mm"
    return f"{round(w / _IN, 3):g} × {round(h / _IN, 3):g} in"


def nearest(printer: str, w: float, h: float) -> list[str]:
    """The two sizes the printer offers closest to this one, by name; none for a printer that prints any size."""
    trims = profile(printer)["trims"] or []
    ranked = sorted(trims, key=lambda t: math.hypot(t[0] - w, t[1] - h))
    return [trim_name(tw, th) for tw, th in ranked[:2]]
