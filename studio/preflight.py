"""The print checks: what to look at, and what to fix, before a book goes to the printer.

Spec: docs/superpowers/specs/2026-11-13-books-part-2-design.md ("Print checks", "Hooks for part 4"). `run` compiles the
book (compose.compile_book, the same compile the preview uses), runs the checks in CHECKS order and keeps the report in
the book's .studio/preflight.json; `last` reads it back. Compose's *Check*, the export dialog and Claude's tools all
come here. Each check is a function of the Compiled, the resolved design and `Facts` (the book's contents, its pieces
and its pages as pixels, each read once and only when a check asks), and returns items:

    {"check", "level": "fail" | "warn" | "info", "message", "page": 1-based | None, "file": str | None,
     "block": int | None}

fail: the printer would refuse it or it would print wrong; warn: worth a look; info: for the record. `page` is the
physical page (Compose opens it), `file` and `block` the paragraph the writing window opens, where there is one.

Measuring. Positions are Typst's, in pt from the page's top left (Compiled.markers); the pages are drawn at 72 ppi, so
a pixel is a point. Lines sit on a grid: the text area's top, then one line pitch (`text.line`) per line, each line
`text.size` deep (the template fixes the text's edges to 1 em). Two things about the markers matter:
  - A marker at the start or the end of a paragraph sits outside its lines: Typst places it where the next thing
    starts. A paragraph's `<blk>` is the top of its first line. Its `<blkend>` is the top of whatever follows it,
    after the space between them, or the next page's top when the paragraph filled its own page; so how many of its
    lines are on its last page is read from the page itself where the space could hold a line.
  - In poems the markers sit inside the lines and report a baseline, and poems keep their stanzas whole by their own
    rule: poem pieces are left out of the widow check.
"""
from __future__ import annotations

import io
import json
import math
import posixpath
from datetime import datetime

import numpy as np
from PIL import Image

from . import compose, printers, typeset, typeset_book, typeset_fonts
from .books import BooksError
from .store import write_text

REPORT = "preflight.json"       # in the book's .studio folder
SHORT_LINES = 4                 # a piece's last page with fewer lines is short (book.json `checks.shortLines`)
# Ink past the text block's edge that makes a line too long: the larger of OVERFULL mm and OVERFULL_EM of the text
# size. Italic and script glyphs reach past their advance width (measured on justified italic text, the worst an f at
# a line's end: about 0.22 em in Newsreader and Caveat, 0.8 mm at 10.5 pt; 0.7 mm in EB Garamond), so a normal line
# may print that far out; a line that doesn't fit runs several millimetres.
OVERFULL = 1.2
OVERFULL_EM = 0.3
INK = 128                       # a pixel darker than this (in L) is ink
PPI = 72                        # the pages are drawn at 72 ppi to be measured: a pixel is a point
LOW, GOOD = 200, 300            # an image's resolution as printed: below LOW it prints soft, below GOOD it may
COLOUR = 12                     # the spread of a pixel's channels that makes it coloured (JPEG noise stays under)
_MM = 72 / 25.4                 # pt per mm
_EPS = 0.5                      # pt: positions are exact to far less; this only absorbs rounding


def _item(check, level, message, page=None, file=None, block=None) -> dict:
    return {"check": check, "level": level, "message": message, "page": int(page) if page is not None else None,
            "file": file, "block": int(block) if block is not None else None}


def _plural(n, one, many=None) -> str:
    return f"{n:,} {one if n == 1 else many or one + 's'}"


# Kind names the list of pieces shows for an untitled piece (book.js, BOOK_PIECE_NAME and pieceKindName); other kinds
# are their id, capitalised.
_KIND_NAMES = {"content-note": "Content note", "about-author": "About the author"}
_KIND_IN_SENTENCE = {"about-author": "the piece about the author"}


def piece_name(entry: dict, sentence=False) -> str:
    """A piece as the writing window names it, never by its file: its title in quotes (“The Harbour”), or for an
    untitled piece its kind ("Dedication" in a list, "the dedication" inside a sentence)."""
    e = entry if isinstance(entry, dict) else {}
    if e.get("title"):
        return f"“{e['title']}”"
    kind = str(e.get("kind") or "")
    if sentence:
        return _KIND_IN_SENTENCE.get(kind) or f"the {_KIND_NAMES.get(kind, kind or 'piece').lower()}"
    return _KIND_NAMES.get(kind) or (kind[:1].upper() + kind[1:] if kind else "Piece")


def _walk(n):
    """A node and every node inside it."""
    if isinstance(n, dict):
        yield n
        for x in n.get("content") if isinstance(n.get("content"), list) else []:
            yield from _walk(x)


class Facts:
    """What the checks read besides the compile: the book's contents and checks settings, its pieces (read when a
    check first asks) and its pages drawn at PPI (drawn when a check first asks; Typst draws every page at once).
    `undrawn` says why there are no pages to measure, when there are none."""

    def __init__(self, books, book, meta: dict, c: compose.Compiled):
        self.books, self.book, self.meta, self.c = books, book, meta, c
        self.contents = [e if isinstance(e, dict) else {} for e in meta.get("contents") or []]
        self.checks = meta.get("checks") if isinstance(meta.get("checks"), dict) else {}
        self.features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
        self.undrawn = None
        self._docs = None
        self._pngs = None

    def entry(self, i) -> dict:
        return self.contents[i] if isinstance(i, int) and 0 <= i < len(self.contents) else {}

    def name(self, i, sentence=False) -> str:
        """Contents entry i as the author knows it (`piece_name`)."""
        return piece_name(self.entry(i), sentence)

    def where(self, i, block=None):
        """(file, block) of contents entry i's block, as the writing window opens it; (None, None) for an auto page."""
        file = self.entry(i).get("file")
        return (file, block) if file else (None, None)

    def page(self, i, block) -> int | None:
        """The page (1-based) entry i's top-level block is on."""
        pages = self.c.blocks.get(self.entry(i).get("file")) or []
        return pages[block] + 1 if isinstance(block, int) and 0 <= block < len(pages) else None

    def docs(self) -> dict:
        """{contents index: document} of the pieces, in contents order."""
        if self._docs is None:
            self._docs = {}
            for i, e in enumerate(self.contents):
                if e.get("auto") is not None or not e.get("file") or e.get("missing") or e.get("unreadable"):
                    continue
                try:
                    self._docs[i] = self.books.piece(self.book, e["file"])["doc"]
                except BooksError:
                    continue            # gone since the book was set
        return self._docs

    def find(self, test, piece=None):
        """(contents index, block) of the first top-level block holding a node that passes `test`."""
        for i, doc in self.docs().items():
            if piece is not None and i != piece:
                continue
            for k, block in enumerate(doc.get("content") or []):
                if any(test(n) for n in _walk(block)):
                    return i, k
        return piece, None

    def draw(self) -> bool:
        """Draws the pages once. Drawing compiles the book again when it changed since the checks' compile, and the
        markers would then belong to other pages: pages of another compile aren't measured, and neither are pages that
        can't be drawn (a Typst error, the book busy in another window). Either way `undrawn` says so."""
        if self._pngs is None:
            self._pngs = []
            try:
                pngs = compose.render_pages(self.books, self.book, ppi=PPI)
                now = compose.compile_book(self.books, self.book, "check").signature
            except BooksError as e:
                self.undrawn = (f"The pages couldn't be drawn to be measured, so lines running into the margins "
                                f"weren't looked for: {_sentence(e)}")
                return False
            if now != self.c.signature:
                self.undrawn = ("The book changed while it was being checked, so lines running into the margins "
                                "weren't looked for. Check again.")
                return False
            self._pngs = pngs
        return bool(self._pngs)

    def ink(self, page: int):
        """Page `page` (1-based) as a mask of ink (True where a pixel is darker than INK), or None when there is no
        such page drawn."""
        if not self.draw() or not 1 <= page <= len(self._pngs):
            return None
        with Image.open(io.BytesIO(self._pngs[page - 1])) as im:
            im = im.convert("RGBA")
            flat = Image.alpha_composite(Image.new("RGBA", im.size, "white"), im).convert("L")
        return np.asarray(flat) < INK


class _Area:
    """The text block of the design's pages, in pt from the page's top left."""

    def __init__(self, design):
        m = design["margins"]
        self.width = design["width"] * _MM
        self.top, self.foot = m["top"] * _MM, (design["height"] - m["bottom"]) * _MM
        self.inside, self.outside = m["inside"] * _MM, m["outside"] * _MM
        self.size, self.pitch = float(design["text"]["size"]), float(design["text"]["line"])
        self.leading = self.pitch - self.size

    def edges(self, page):
        """The text block's left and right edges: a recto (odd page) has its inside margin on the left."""
        if page % 2:
            return self.inside, self.width - self.outside
        return self.outside, self.width - self.inside

    def holds_ink(self, facts, page, y0, y1):
        """Whether the line slot from y0 to y1 holds ink across the text block (a pixel in from each end, so the
        lines above and below don't count). None when the page can't be drawn."""
        mask = facts.ink(page)
        if mask is None:
            return None
        s = PPI / 72
        left, right = self.edges(page)
        r0, r1 = math.ceil(y0 * s) + 1, math.floor(y1 * s) - 1
        return bool(r1 > r0 and mask[r0:r1, int(left * s):math.ceil(right * s)].any())


# ---------------------------------------------------------------------------------------------------------
# The checks

def widows_orphans(c, design, facts) -> list:
    """A paragraph that leaves its first line alone at the foot of a page (an orphan) or carries its last line alone
    to the top of the next (a widow)."""
    a = _Area(design)
    poems = {i for i, e in enumerate(facts.contents) if e.get("form") == "poem"}
    ends = {(m["p"], m["b"]): m for m in c.markers.get("blkend") or []}
    out = []
    for m in c.markers.get("blk") or []:
        end = ends.get((m["p"], m["b"]))
        if end is None or m["p"] in poems:
            continue                    # not a paragraph (only paragraphs have an end marker), or a poem's stanzas
        first, last = m["page"], end["page"]
        # What follows starts at the top of the next page: the paragraph ended at the foot of the page before.
        full = last > first and end["y"] - a.top < a.size / 2
        if full:
            last -= 1
        if last == first:
            continue
        file, block = facts.where(m["p"], m["b"])
        if _alone_at_foot(facts, a, first, m["y"]):
            out.append(_item("widows_orphans", "warn", "A paragraph leaves its first line alone at the foot of this "
                                                       "page (an orphan).", first, file, block))
        if not full and _alone_at_top(facts, a, last, end["y"]):
            out.append(_item("widows_orphans", "warn", "A paragraph carries its last line alone to the top of this "
                                                       "page (a widow).", last, file, block))
    return out


def _alone_at_foot(facts, a, page, y) -> bool:
    """The paragraph's first line, its top at y, is its only line on the page: there is no room for a second one, or
    the slot under it is empty (footnotes took the foot of the page)."""
    second = y + a.pitch
    if second + a.size > a.foot + _EPS:
        return True
    return a.holds_ink(facts, page, second, second + a.size) is False


def _alone_at_top(facts, a, page, end) -> bool:
    """The paragraph's last line is the first on the page: what follows (at `end`) starts before a second line would
    end, or the second line's slot is only the space before what follows."""
    second = a.top + a.pitch
    if second + a.size > end + _EPS:
        return True
    return a.holds_ink(facts, page, second, second + a.size) is False


def short_last_pages(c, design, facts) -> list:
    """A piece that runs onto a last page holding fewer than `checks.shortLines` lines (default SHORT_LINES)."""
    a = _Area(design)
    least = facts.checks.get("shortLines")
    if isinstance(least, bool) or not isinstance(least, (int, float)) or least < 0:
        least = SHORT_LINES
    starts = {m["i"]: m["page"] for m in c.markers.get("piece-start") or []}
    out = []
    for m in c.markers.get("piece-end") or []:
        i, last, y = m["i"], m["page"], m["y"]
        file = facts.entry(i).get("file")
        if not file or facts.entry(i).get("auto") is not None or i not in starts or last == starts[i]:
            continue
        if y - a.top < a.size / 2:
            continue                    # its end marker went over with nothing after it: it filled its last page
        lines = round((y - a.top + a.leading) / a.pitch)
        if 0 < lines < least:
            blocks = c.blocks.get(file) or []
            out.append(_item("short_last_pages", "warn", f"The last page of {facts.name(i, sentence=True)} holds "
                                                         f"only {_plural(lines, 'line')}.",
                             last, file, len(blocks) - 1 if blocks else None))
    return out


def overfull(c, design, facts) -> list:
    """Ink further past the text block's left or right edge than a glyph's own overhang (OVERFULL), between the top and
    bottom margins: images and poems stay inside the measure by construction (and Typst's hanging punctuation is
    off), so anything there is a line too long."""
    a = _Area(design)
    s = PPI / 72
    margin = max(OVERFULL * _MM, OVERFULL_EM * a.size)
    top = int(a.top * s)
    if not facts.draw():
        return [_item("overfull", "info", facts.undrawn)] if facts.undrawn else []
    out = []
    for n, page in enumerate(c.pages, 1):
        if page.get("blank"):
            continue
        mask = facts.ink(n)
        if mask is None:
            continue
        band = mask[top:math.ceil(a.foot * s)]
        cols = np.flatnonzero(band.any(axis=0))
        if not len(cols):
            continue
        left, right = a.edges(n)
        past_left, past_right = left - cols[0] / s, (cols[-1] + 1) / s - right       # pt beyond each edge
        if max(past_left, past_right) <= margin:
            continue
        if past_right >= past_left:
            side, past, far = "right", past_right, cols[(cols + 1) / s - right > margin]
        else:
            side, past, far = "left", past_left, cols[left - cols / s > margin]
        # the first row with ink that far out, half a line down: the line's middle, to find its paragraph by
        y = (top + int(np.flatnonzero(band[:, far].any(axis=1))[0])) / s + a.size / 2
        file, block = _block_at(c, facts, n, y)
        out.append(_item("overfull", "fail", f"A line runs {past / _MM:.1f} mm into the {side} margin: a word or web "
                                             f"address too long for the line.", n, file, block))
    return out


def _block_at(c, facts, page, y):
    """(file, block) of the paragraph at (page, y): the last block that starts at or before it, when it belongs to the
    piece on that page (generated pages have no blocks)."""
    best = None
    for m in c.markers.get("blk") or []:
        if (m["page"], m["y"]) <= (page, y):
            best = m
    if best is None or c.pages[page - 1].get("entry") != best["p"]:
        return None, None
    return facts.where(best["p"], best["b"])


def fonts(c, design, facts) -> list:
    """The font problems found while cutting the faces (a family not found, one that may not be embedded, no italic
    or bold); every character in the face that sets it; real small capitals where small caps are used.

    The text's face sets every character of the book somewhere (titles too: in the running heads and the contents);
    a headings face of its own sets only the titles, numbers and title pages (`_heading_text`), so it is held only
    against those."""
    cut = c.fonts or {}
    faces = cut.get("faces") or []
    out = [_item("fonts", "warn", _sentence(p)) for p in cut.get("problems") or []]
    family = {f.role: f.family for f in faces}
    chars = "".join(sorted(c.ctx.chars)) if c.ctx is not None else ""
    for role, text in (("text", chars), ("heading", _heading_text(design, facts) if "heading" in family else "")):
        for ch in sorted(typeset_fonts.covers([f for f in faces if f.role == role], text)):
            out.append(_item("fonts", "fail", f"“{ch}” isn't in {family[role]}: it would print in another font."))
    for role in _smallcaps_roles(design, facts, family):
        face = next((f for f in faces if f.role == role and f.style == "regular"), None)
        if face is not None and not typeset_fonts.has_smallcaps(face):
            out.append(_item("fonts", "warn", f"{face.family} has no real small capitals, so the small capitals in "
                                              f"this book print as ordinary letters."))
    return out


def _sentence(s) -> str:
    s = str(s).strip()
    return s[:1].upper() + s[1:] + ("" if s.endswith(".") else ".")


def _heading_text(design, facts) -> str:
    """The text the template sets in the headings' face: the half-title and title page (title, subtitle, author,
    publisher), every piece's and generated page's title, chapter and part numbers, and the part label. Titles and
    numbers come from typeset_book's own plan of the book, so the check reads what the pages print."""
    meta, docs = facts.meta, facts.docs()
    pieces = [(i, e, docs.get(i)) for i, e in enumerate(facts.contents) if e.get("auto") is not None or i in docs]
    plan = typeset_book._Book(meta, pieces, design, {}, typeset.Context(design=design,
                                                                        lang=str(meta.get("language") or "en")))
    plan._plan()
    for i in facts.c.left_out or {}:            # a page left out prints nothing
        plan.info.pop(i, None)
    autos = {e.get("auto") for e in facts.contents}
    details = meta.get("details") if isinstance(meta.get("details"), dict) else {}
    out = []
    if autos & {"half-title", "title-page"}:
        out.append(meta.get("title"))
    if "title-page" in autos:
        out += [meta.get("subtitle"), meta.get("author"), details.get("publisher")]
    for p in plan.info.values():
        out += [p["title"] if p["labelled"] else "", p["number"]]
        if p["kind"] == "part":
            out.append(plan.labels.get("part"))
    return "".join(str(x) for x in out if isinstance(x, (str, int)) and not isinstance(x, bool))


def _smallcaps_roles(design, facts, family) -> list:
    """The faces that set small capitals in this book: the text's for small-capital running heads, chapter openings
    and the author's own small caps; the headings' face for headings in small capitals."""
    heads, headings = design.get("heads") or {}, design.get("headings") or {}
    roles = []
    text = heads.get("style") == "smallcaps" and (heads.get("verso") != "none" or heads.get("recto") != "none")
    if not text:
        for doc in facts.docs().values():
            nodes = list(_walk(doc))
            if any(m.get("type") == "smallcaps" for n in nodes for m in n.get("marks") or [] if isinstance(m, dict)) \
                    or (headings.get("opening") == "smallcaps" and any(n.get("type") == "title" for n in nodes)):
                text = True
                break
    if text:
        roles.append("text")
    if headings.get("case") == "smallcaps":
        role = "heading" if "heading" in family else "text"
        if role not in roles:
            roles.append(role)
    return roles


def images(c, design, facts) -> list:
    """Each image's resolution at its printed width (its share of the measure): below LOW ppi a failure, below GOOD a
    warning; a colour image in a grey interior noted; a missing image a failure."""
    out = []
    if c.ctx is None:
        return out
    m = design["margins"]
    measure = design["width"] - m["inside"] - m["outside"]          # mm
    grey = design.get("interior") != "colour"
    folder = facts.books.dir(facts.book) / "images"
    seen, noted = set(), set()
    for i, doc in facts.docs().items():
        for k, block in enumerate(doc.get("content") or []):
            for node in _walk(block):
                attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
                src = str(attrs.get("src") or "")
                staged = c.ctx.images.get(src) if node.get("type") == "image" else None
                if not staged:
                    continue
                file, page, name = facts.where(i)[0], facts.page(i, k), posixpath.basename(src)
                share = float(typeset._width(attrs.get("width"))[:-1]) / 100
                px = _pixel_width(c.staging / staged) if (src, share) not in seen else None
                seen.add((src, share))
                if px:
                    inches = measure * share / 25.4
                    ppi = px / inches
                    said = f"{name} prints at {ppi:.0f} ppi ({px:,} pixels across {inches:.1f} in)"
                    if ppi < LOW:
                        out.append(_item("images", "fail", f"{said}: below {LOW} ppi it looks soft in print. Use a "
                                                           f"larger image or set it smaller.", page, file, k))
                    elif ppi < GOOD:
                        out.append(_item("images", "warn", f"{said}; {GOOD} ppi is the usual minimum for print.",
                                         page, file, k))
                local = compose._image_name(src)
                if grey and src not in noted and local and _in_colour(folder / local):
                    noted.add(src)
                    out.append(_item("images", "info", f"{name} is in colour; the interior is grey, so it prints in "
                                                       f"grey.", page, file, k))
    for i, src in dict.fromkeys(c.ctx.missing_images):         # once per piece, at its first use there
        _, k = facts.find(lambda n: n.get("type") == "image" and str((n.get("attrs") or {}).get("src") or "") == src,
                          piece=i)
        file = facts.where(i)[0]
        what = f"The image {posixpath.basename(src)}" if src else "An image"
        out.append(_item("images", "fail", f"{what} isn't in the book's images folder, so its page shows an empty "
                                           f"frame.", facts.page(i, k), file, k if file else None))
    return out


def _pixel_width(path) -> int | None:
    """An image's width in pixels as it is printed (turned by its EXIF orientation)."""
    try:
        with Image.open(path) as im:
            w, h = im.size
            turned = im.getexif().get(0x0112) in (5, 6, 7, 8)
    except Exception:       # noqa: BLE001 — not an image Pillow can read: the composer sets it as missing
        return None
    return h if turned else w


def _in_colour(path) -> bool:
    """Whether an image has colour in it, not just grey (a small copy is enough to tell)."""
    try:
        with Image.open(path) as im:
            if im.mode in ("1", "L", "LA", "I", "I;16", "F"):
                return False
            im.draft("RGB", (256, 256))
            rgb = im.convert("RGB")
        rgb.thumbnail((256, 256))
    except Exception:       # noqa: BLE001 — unreadable: the images check says what matters about it
        return False
    a = np.asarray(rgb, dtype=np.int16)
    return bool(((a.max(axis=2) - a.min(axis=2)) > COLOUR).any())


def page_count(c, design, facts) -> list:
    """The page count within the printer's limits and multiple; the trim size one it prints; the inside margin at
    least the printer's minimum for this page count, and the other margins at least its minimums."""
    pid, paper = design.get("printer"), design.get("paper")
    p = printers.profile(pid)
    name, n, out = p["name"], len(c.pages), []
    lo, hi, multiple = printers.page_range(pid, paper)
    if (lo and n < lo) or (hi and n > hi):
        limits = f"{lo:,} to {hi:,} pages" if lo and hi else f"at least {lo:,} pages" if lo else f"up to {hi:,} pages"
        out.append(_item("page_count", "fail", f"The book has {_plural(n, 'page')}; {name} prints {limits} on "
                                               f"{paper} paper."))
    if multiple and n % multiple:
        out.append(_item("page_count", "fail", f"{name} takes a page count divisible by {multiple}; the book has "
                                               f"{_plural(n, 'page')}."))
    w, h = design["width"], design["height"]
    if not printers.offers(pid, w, h):
        size, near = printers.trim_name(w, h), printers.nearest(pid, w, h)
        nearest = " and ".join(near)
        if printers.custom(pid, w, h, paper):
            message = (f"{size} isn't one of {name}'s standard sizes (the nearest are {nearest}); it can be ordered "
                       f"as a custom size.")
        else:
            message = f"{size} isn't a size {name} prints; the nearest are {nearest}."
        out.append(_item("page_count", "warn", message))
    # A printer's rule is a failure (it would refuse the file); a printer's advice, or Studio's guess for a printer it
    # doesn't know (no specification page), is a warning.
    margins = design["margins"]
    if not p.get("margins_advised"):
        level, asks = "fail", f"{name} asks for"
    elif p.get("url"):
        level, asks = "warn", f"{name} recommends"
    else:
        level, asks = "warn", "printers usually ask for"
    need = printers.inside_min(pid, n)
    by_length = f" in a book of {_plural(n, 'page')}" if len(p["inside"]) > 1 else ""
    if margins["inside"] < need - 1e-9:
        out.append(_item("page_count", level, f"The inside margin is {margins['inside']:g} mm; {asks} at least "
                                              f"{need:g} mm{by_length}."))
    for side in ("outside", "top", "bottom"):
        least = p["min"][side]
        if margins[side] < least - 1e-9:
            out.append(_item("page_count", level, f"The {side} margin is {margins[side]:g} mm; {asks} at least "
                                                  f"{least:g} mm."))
    return out


def generated(c, design, facts) -> list:
    """The generated pages the book needs: a Notes page for endnotes, sources for every citation, an Index page for
    marked terms (or first lines), and something after the contents page for it to list; and, for the record, each
    generated page left out of the pages (typeset_book.left_out: its feature is off, or it has nothing to list)."""
    out, ctx = [], c.ctx
    if ctx is None:
        return out
    autos = [e.get("auto") for e in facts.contents if e.get("auto") is not None]
    notes = facts.features.get("notes")
    if notes in ("endnotes", "both") and ctx.endnotes and "notes" not in autos:
        i, k = facts.find(lambda n: n.get("type") == "note", piece=ctx.endnotes[0].get("piece"))
        file = facts.where(i)[0]
        lost = "so they aren't printed" if notes == "endnotes" else "so they print only as footnotes"
        out.append(_item("generated", "fail", f"The notes are collected for a Notes page, but the book has none, "
                                              f"{lost}. Add Notes to the book's pieces.", facts.page(i, k), file,
                         k if file else None))
    known = {s.get("id") for s in ctx.sources if isinstance(s, dict)}
    for key in ctx.cited:
        if key in known:
            continue
        i, k = facts.find(lambda n, key=key: n.get("type") == "cite" and any(
            isinstance(it, dict) and it.get("key") == key for it in (n.get("attrs") or {}).get("items") or []))
        file = facts.where(i)[0]
        out.append(_item("generated", "warn", f"No source has the key “{key}” (add it under Sources in the rail), so "
                                              f"its citation prints the key itself.", facts.page(i, k), file,
                         k if file else None))
    if "index" not in autos:
        index = facts.features.get("index")
        if index is True and ctx.terms:
            out.append(_item("generated", "warn", "Index terms are marked, but the book has no Index page. Add Index "
                                                  "to the book's pieces."))
        elif index == "first-lines" and ctx.first_lines:
            out.append(_item("generated", "warn", "The index of first lines is on, but the book has no Index page. "
                                                  "Add Index to the book's pieces."))
    starts = {m["i"]: m["page"] for m in c.markers.get("piece-start") or []}
    left = c.left_out or {}
    for at, e in enumerate(facts.contents):
        if e.get("auto") == "toc" and at not in left and not any(
                _listed(x) for k, x in enumerate(facts.contents) if k > at and k not in left):
            out.append(_item("generated", "warn", "The contents page lists nothing: no piece after it has a title.",
                             starts.get(at)))
    for i, why in sorted(left.items()):
        out.append(_item("generated", "info", f"{typeset_book.left_out_name(facts.meta, i)} is left out: {why}."))
    return out


def _listed(e) -> bool:
    """Whether the contents page lists this entry (one in the pages): a generated back page, or a piece with a title
    of its own."""
    if e.get("auto") is not None:
        return e["auto"] in ("notes", "bibliography", "index")
    return bool(e.get("file") and not e.get("missing") and e.get("title")
                and e.get("kind") not in typeset_book.UNTITLED)


def typst(c, design, facts) -> list:
    """Typst's warnings in a sentence of their own, and the math that is printed as source."""
    out = [_item("typst", "info", f"Typst noted: {str(w).strip()}" + ("" if str(w).strip().endswith(".") else "."))
           for w in c.warnings or []]
    if c.ctx is not None and c.ctx.math:
        out.append(_item("typst", "info", f"Math is printed as its TeX source for now "
                                          f"({_plural(c.ctx.math, 'formula')})."))
    return out


def not_final(c, design, facts) -> list:
    """The pieces whose status isn't final yet, in one line."""
    names = [facts.name(i) for i, e in enumerate(facts.contents)
             if e.get("file") and e.get("auto") is None and not e.get("missing") and e.get("status") != "final"]
    if not names:
        return []
    verb = "isn't" if len(names) == 1 else "aren't"
    return [_item("not_final", "info", f"{_plural(len(names), 'piece')} {verb} marked final yet: {', '.join(names)}.")]


_RUN = (widows_orphans, short_last_pages, overfull, fonts, images, page_count, generated, typst, not_final)
CHECKS = tuple(f.__name__ for f in _RUN)


# ---------------------------------------------------------------------------------------------------------
# The report

def summary(items) -> str:
    """"1 to fix, 3 to look at": failures, then warnings (the order Compose shows them in everywhere); notes for the
    record aren't counted."""
    warns = sum(x["level"] == "warn" for x in items)
    fails = sum(x["level"] == "fail" for x in items)
    parts = ([f"{fails} to fix"] if fails else []) + ([f"{warns} to look at"] if warns else [])
    return ", ".join(parts) or "Nothing to fix"


def _path(books, book):
    return books.dir(book) / ".studio" / REPORT


def run(books, book, progress=None) -> dict:
    """Compiles the book (or takes the compile that is current), runs the checks and keeps the report in the book's
    .studio/preflight.json. `progress(done, total)`, when given, is called before the first check and after each.
    A book that can't be set gets one failure saying why, instead of checks on its last good pages."""
    c = compose.compile_book(books, book, "check")
    meta = books.read(book)
    facts = Facts(books, book, meta, c)
    tick = progress if callable(progress) else (lambda done, total: None)
    total = len(_RUN)
    tick(0, total)
    if c.error:
        items = [_item("typst", "fail", f"The book can't be set, so it can't be checked: {c.error}")]
        tick(total, total)
    else:
        items = []
        for k, check in enumerate(_RUN, 1):
            items += check(c, c.design, facts)
            tick(k, total)
    report = {"summary": summary(items), "items": items, "pages": len(c.pages),
              "at": datetime.now().isoformat(timespec="seconds"), "signature": c.signature}
    try:
        write_text(_path(books, book), json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    except OSError:
        pass                            # a book folder that can't be written still gets its report
    return report


def last(books, book) -> dict | None:
    """The report `run` last kept for this book, or None when it has none (or it can't be read)."""
    try:
        data = json.loads(_path(books, book).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("items"), list) else None
