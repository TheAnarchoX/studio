"""The print checks and the printer profiles.

Books are built with `Books` in a temp library (STUDIO_ART, STUDIO_CACHE, STUDIO_CONFIG point at temp folders) and
compiled through `compose.compile_book`, set in Literata, which typeset_fonts cuts once for the whole module: the cache
folder is shared by every test, because cutting a family takes seconds."""
import dataclasses
import io
import itertools
import json
import os
import random
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import typst
from PIL import Image

from studio import book_design, books, compose, config, preflight, printers
from studio.books import BooksError
from studio.store import write_text

_ENV = ("STUDIO_ART", "STUDIO_CACHE", "STUDIO_CONFIG")
TMP = None
_SAVED = {}
_COUNT = itertools.count()
BR = "\\\n"             # a hard line break in the manuscript dialect

_WORDS = ("the grey sea came in over the low dunes where we walked each morning and the wind kept the gulls high above "
          "the water while my mother counted the boats that went out past the harbour wall before the light was "
          "full").split()


def prose(n, start=0):
    """About `n` invented words in paragraphs of ninety."""
    paras = []
    for p in range(0, n, 90):
        words = [_WORDS[(start + p + k) % len(_WORDS)] for k in range(min(90, n - p))]
        paras.append(" ".join(words).capitalize() + ".")
    return "\n\n".join(paras)


def png(mode="L", size=(60, 40), colour=128):
    out = io.BytesIO()
    Image.new(mode, size, colour).save(out, "PNG")
    return out.getvalue()


def setUpModule():
    global TMP
    TMP = Path(tempfile.mkdtemp(prefix="studio-preflight-"))
    _SAVED.update({k: os.environ.get(k) for k in _ENV})
    _SAVED["cfg"] = config.CONFIG_FILE
    os.environ["STUDIO_ART"] = str(TMP / "lib")
    os.environ["STUDIO_CACHE"] = str(TMP / "cache")
    os.environ["STUDIO_CONFIG"] = str(TMP / "config.json")
    config.CONFIG_FILE = TMP / "config.json"
    config.refresh()


def tearDownModule():
    for k in _ENV:
        if _SAVED.get(k) is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = _SAVED[k]
    config.CONFIG_FILE = _SAVED["cfg"]
    config.refresh()
    shutil.rmtree(TMP, ignore_errors=True)


def make_book(chapters, design=None, autos=("toc",), back=(), features=None, checks=None, kind="memoir"):
    """A book in a library of its own: the three title pages, `autos`, a chapter per markdown text, then `back`.
    Set in Literata unless `design` says otherwise. `checks` is written into book.json as the author would (Studio
    keeps the key). Returns (Books, book id, the chapters' files)."""
    n = next(_COUNT)
    lib = books.Books(TMP / f"lib{n}" / "Books")
    bid = lib.create(f"The Grey Sea {n}", "Anna Example", "en", kind, start=False)["id"]
    contents = [{"auto": a} for a in ("half-title", "title-page", "copyright", *autos)]
    files = []
    for md in chapters:
        p = lib.new_piece(bid, "chapter", "prose")
        lib.save_piece(bid, p["file"], md=md)
        contents.append({"file": p["file"], "kind": "chapter", "form": "prose"})
        files.append(p["file"])
    contents += [{"auto": a} for a in back]
    fields = {"contents": contents, "design": {"text": {"font": "Literata"}, **(design or {})}}
    if features:
        fields["features"] = features
    lib.update(bid, fields)
    if checks is not None:
        set_checks(lib, bid, checks)
    return lib, bid, files


def set_checks(lib, bid, checks):
    path = lib.dir(bid) / "book.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["checks"] = checks
    write_text(path, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")


def items(report, check, level=None):
    return [x for x in report["items"] if x["check"] == check and (level is None or x["level"] == level)]


def index_of(lib, bid, file):
    return next(k for k, e in enumerate(lib.read(bid)["contents"]) if e.get("file") == file)


def hard_lines(n, word="Line"):
    """One paragraph of `n` lines, each ended by a hard break, so its line count is known."""
    return BR.join(f"{word} {k} of the long paragraph" for k in range(n))


class PrinterTest(unittest.TestCase):
    def test_printer_profiles(self):
        self.assertEqual(list(printers.PRINTERS), ["kdp", "ingramspark", "other"])
        for pid, p in printers.PRINTERS.items():
            self.assertEqual(book_design._SCALARS["printer"](pid), pid)          # the design accepts each one
            self.assertTrue({"name", "url", "checked", "trims", "bleed", "min", "inside", "pages", "paper"} <= set(p))
            self.assertEqual(p["checked"], "2026-11-13")
            self.assertEqual(set(p["min"]), {"outside", "top", "bottom"})
            self.assertEqual(set(p["paper"]), {"white", "cream"})
        self.assertEqual(printers.inside_min("kdp", 24), 9.6)
        self.assertEqual(printers.inside_min("kdp", 150), 9.6)
        self.assertEqual(printers.inside_min("kdp", 151), 12.7)
        self.assertEqual(printers.inside_min("kdp", 500), 15.9)
        self.assertEqual(printers.inside_min("kdp", 828), 22.3)
        self.assertEqual(printers.inside_min("kdp", 900), 22.3)
        self.assertEqual(printers.inside_min("ingramspark", 300), 12.7)
        self.assertEqual(printers.inside_min("other", 300), 10)
        self.assertTrue(printers.offers("kdp", 139.7, 215.9))           # 5.5 × 8.5 in
        self.assertTrue(printers.offers("kdp", 140.2, 216.4))           # within 0.6 mm
        self.assertFalse(printers.offers("kdp", 140.4, 215.9))
        self.assertFalse(printers.offers("kdp", 135, 210))
        self.assertTrue(printers.offers("other", 135, 210))             # any size
        self.assertTrue(printers.offers("ingramspark", 148, 210))       # A5 (5.83 × 8.27 in)
        self.assertEqual(printers.nearest("kdp", 135, 210), ["5.25 × 8 in", "5.5 × 8.5 in"])
        self.assertEqual(printers.nearest("other", 135, 210), [])
        self.assertEqual(printers.trim_name(135, 210), "135 × 210 mm")
        self.assertEqual(printers.trim_name(152.4, 228.6), "6 × 9 in")
        self.assertEqual(printers.page_range("kdp", "cream"), (24, 776, 2))
        self.assertEqual(printers.page_range("kdp", "white"), (24, 828, 2))


class PreflightTest(unittest.TestCase):
    _capacity = None

    @classmethod
    def opening_capacity(cls):
        """How many lines a chapter's opening page holds, counted with one-line paragraphs (their markers' pages, not
        their positions), so the widow tests build their pages from Typst's own line count."""
        if cls._capacity is None:
            ones = "\n\n".join(f"Line {k} of the text here." for k in range(80))
            lib, bid, files = make_book(["# The Harbour\n\n" + ones + "\n"])
            c = compose.compile_book(lib, bid)
            i = index_of(lib, bid, files[0])
            pages = Counter(m["page"] for m in c.markers["blk"] if m["p"] == i and m["b"] >= 1)
            first = min(pages)
            cls._capacity = (first, pages[first], pages[first + 1])
        return cls._capacity

    def test_overfull_line_found(self):
        url = "https://example.org/" + "abcdefghijklmnopqrstuvwxyz" * 4 + "abcdefghijklmnop"       # 120 letters
        lib, bid, files = make_book(["# The Harbour\n\n" + prose(200) + "\n\nSee " + url + " for more.\n\n"
                                     + prose(200, 4)])
        self.assertEqual(compose.get_design(lib, bid)["design"]["text"]["align"], "justify")
        r = preflight.run(lib, bid)
        over = items(r, "overfull")
        self.assertEqual(len(over), 1, over)
        self.assertEqual(over[0]["level"], "fail")
        doc = lib.piece(bid, files[0])["doc"]
        k = next(k for k, n in enumerate(doc["content"]) if "example.org" in json.dumps(n))
        c = compose.compile_book(lib, bid)
        i = index_of(lib, bid, files[0])
        blk = next(m for m in c.markers["blk"] if (m["p"], m["b"]) == (i, k))
        self.assertEqual(over[0]["page"], blk["page"])
        self.assertEqual((over[0]["file"], over[0]["block"]), (files[0], k))
        self.assertIn("mm", over[0]["message"])

        # a book with the usual furniture (notes, quotation, scene break, list, table, index, bibliography) has none
        md = ("# The Harbour\n\n" + prose(500) + "^[A note about the harbour.]\n\n> A quotation from someone, set "
              "apart from the text and long enough to wrap onto a second line of the block.\n\n* * *\n\n"
              + prose(300, 5) + "\n\n- one item in a list\n- another item that is long enough to wrap onto a second "
              "line in the list of things\n\n| Year | Boats | Notes |\n|---|---|---|\n| 1951 | 12 | A good year for "
              "the fleet and the harbour |\n| 1952 | 9 | Fewer |\n\nText with [an index term]{.idx} and more text.\n")
        lib, bid, _ = make_book([md, "# The Dunes\n\n" + prose(900, 3)], back=("notes", "bibliography", "index"),
                                features={"notes": "endnotes", "index": True})
        r = preflight.run(lib, bid)
        self.assertEqual(items(r, "overfull"), [])
        self.assertEqual(items(r, "widows_orphans"), [])            # Typst's own prevention is on

    def test_italic_overhang_is_not_overfull(self):
        """Italic glyphs reach past their advance width (an f at a line's end, a line starting with "for"): in EB
        Garamond about 0.7 mm at 10.5 pt. That is a normal line, not an overfull one."""
        rnd = random.Random(7)
        ends = "if staff of cliff off chief leaf half proof roof self wolf gulf scarf beef reef serif stuff".split()
        starts = "for from first far few fine fold ferry fell fog field".split()
        paras = ["*" + " ".join(rnd.choice(ends + starts + ["the", "sea", "and", "a", "harbour"]) for _ in range(70))
                 + ".*" for _ in range(40)]
        lib, bid, _ = make_book(["# The Harbour\n\n" + "\n\n".join(paras) + "\n"],
                                design={"text": {"font": "EB Garamond"}})
        self.assertEqual(compose.get_design(lib, bid)["design"]["text"]["size"], 10.5)
        with mock.patch.object(preflight, "OVERFULL", 0.6), mock.patch.object(preflight, "OVERFULL_EM", 0):
            self.assertTrue(items(preflight.run(lib, bid), "overfull", "fail"))    # the glyphs do reach 0.6 mm out
        self.assertEqual(items(preflight.run(lib, bid), "overfull"), [])

    def test_pages_that_cant_be_measured(self):
        lib, bid, files = make_book(["# The Harbour\n\n" + prose(200)])

        def busy(*args, **kwargs):
            raise BooksError("The Grey Sea is being set in another window; try again in a moment.", 409)

        with mock.patch.object(compose, "render_pages", busy):
            r = preflight.run(lib, bid)
        over = items(r, "overfull")
        self.assertEqual([x["level"] for x in over], ["info"])
        self.assertIn("couldn't be drawn", over[0]["message"])
        self.assertIn("another window", over[0]["message"])
        # the book saved between the checks' compile and the drawing: those pages aren't the checked ones
        draw = compose.render_pages

        def saved_first(*args, **kwargs):
            lib.save_piece(bid, files[0], md="# The Harbour\n\nA new opening.\n\n" + prose(200))
            return draw(*args, **kwargs)

        with mock.patch.object(compose, "render_pages", saved_first):
            r = preflight.run(lib, bid)
        over = items(r, "overfull")
        self.assertEqual([x["level"] for x in over], ["info"])
        self.assertIn("changed while it was being checked", over[0]["message"])
        self.assertEqual(items(preflight.run(lib, bid), "overfull"), [])          # and the next check measures

    def test_widow_found(self):
        first, holds, _ = self.opening_capacity()
        # one line more than the opening page holds: with widows allowed the last line goes over alone
        text = "# The Harbour\n\n" + hard_lines(holds + 1) + "\n\nThe next paragraph.\n"
        lib, bid, files = make_book([text], checks={"allowWidows": True})
        found = items(preflight.run(lib, bid), "widows_orphans")
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["level"], "warn")
        self.assertEqual(found[0]["page"], first + 1)                   # the page with the single line
        self.assertEqual((found[0]["file"], found[0]["block"]), (files[0], 1))
        self.assertIn("top", found[0]["message"])
        # Typst's own prevention (the default) moves a second line over: nothing to report
        lib, bid, _ = make_book([text])
        self.assertEqual(items(preflight.run(lib, bid), "widows_orphans"), [])
        # a section heading after the widow: the space above it doesn't count as a line
        text = "# The Harbour\n\n" + hard_lines(holds + 1) + "\n\n## A section\n\nAfter it.\n"
        lib, bid, _ = make_book([text], checks={"allowWidows": True})
        self.assertEqual([x["page"] for x in items(preflight.run(lib, bid), "widows_orphans")], [first + 1])
        # an orphan: the opening page full but for one line, then a paragraph of five
        ones = "\n\n".join(f"One {k}." for k in range(holds - 1))
        text = "# The Harbour\n\n" + ones + "\n\n" + hard_lines(5) + "\n\nAfter it.\n"
        lib, bid, files = make_book([text], checks={"allowWidows": True})
        found = items(preflight.run(lib, bid), "widows_orphans")
        self.assertEqual([(x["page"], x["block"]) for x in found], [(first, holds)])
        self.assertIn("foot", found[0]["message"])
        # a paragraph that ends on the last line of its page is neither
        ones = "\n\n".join(f"One {k}." for k in range(holds))
        lib, bid, _ = make_book(["# The Harbour\n\n" + ones + "\n\n## A section\n\nAfter it.\n"],
                                checks={"allowWidows": True})
        self.assertEqual(items(preflight.run(lib, bid), "widows_orphans"), [])

    def test_short_last_page(self):
        first, holds, _ = self.opening_capacity()
        ones = "\n\n".join(f"Line {k} of the text here." for k in range(holds + 2))
        lib, bid, files = make_book(["# The Harbour\n\n" + ones + "\n", "# The Dunes\n\n" + prose(100)])
        found = items(preflight.run(lib, bid), "short_last_pages")
        self.assertEqual(len(found), 1, found)
        self.assertEqual((found[0]["level"], found[0]["page"], found[0]["file"]), ("warn", first + 1, files[0]))
        self.assertIn("2 lines", found[0]["message"])
        set_checks(lib, bid, {"shortLines": 2})
        self.assertEqual(items(preflight.run(lib, bid), "short_last_pages"), [])

    def test_low_resolution_image(self):
        lib, bid, files = make_book(["# The Harbour\n\nText.\n"])
        low = lib.save_image(bid, "low.png", png(size=(300, 200)))
        fine = lib.save_image(bid, "fine.png", png(size=(3000, 2000)))
        middle = lib.save_image(bid, "middle.png", png(size=(1000, 600)))
        colour = lib.save_image(bid, "colour.png", png("RGB", (3000, 2000), (200, 40, 40)))
        lib.save_piece(bid, files[0], md=f"# The Harbour\n\nText.\n\n![Low]({low}){{width=100%}}\n\n"
                                         f"![Fine]({fine}){{width=100%}}\n\n![Middle]({middle}){{width=100%}}\n\n"
                                         f"![Colour]({colour}){{width=50%}}\n\n![Gone](../images/gone.png)\n")
        r = preflight.run(lib, bid)
        fails = items(r, "images", "fail")
        self.assertEqual(len(fails), 2, fails)
        self.assertIn("low.png", fails[0]["message"])
        self.assertIn("ppi", fails[0]["message"])
        doc = lib.piece(bid, files[0])["doc"]
        k = next(k for k, n in enumerate(doc["content"]) if "low.png" in json.dumps(n))
        self.assertEqual(doc["content"][k]["type"], "image")
        self.assertEqual((fails[0]["file"], fails[0]["block"]), (files[0], k))
        self.assertIsNotNone(fails[0]["page"])
        self.assertIn("gone.png", fails[1]["message"])
        warns = items(r, "images", "warn")
        self.assertEqual([("middle.png" in w["message"], "ppi" in w["message"]) for w in warns], [(True, True)])
        self.assertFalse(any("fine.png" in x["message"] for x in items(r, "images")))
        notes = items(r, "images", "info")
        self.assertEqual(len(notes), 1)
        self.assertIn("colour.png", notes[0]["message"])

    def test_missing_glyph(self):
        lib, bid, files = make_book(["# The Harbour\n\nA rune on the harbour wall: ᚠ, and an omega: Ω.\n"])
        r = preflight.run(lib, bid)
        fails = items(r, "fonts", "fail")
        self.assertEqual([x["message"] for x in fails], ["“ᚠ” isn't in Literata: it would print in another font."])
        lib, bid, _ = make_book(["# The Harbour\n\n" + prose(200)])
        self.assertEqual(items(preflight.run(lib, bid), "fonts"), [])

    def test_heading_font_checked_against_its_own_text(self):
        """A headings face of its own sets the titles, not the body: a character only in the body is the text face's
        to cover. Bebas Neue has neither "ﬁ" nor "Ж"; Literata has both."""
        lib, bid, _ = make_book(["# The Harbour of Ж\n\nA body with a ligature ﬁ and a Ж in it.\n"],
                                design={"headings": {"font": "Bebas Neue"}})
        c = compose.compile_book(lib, bid)
        self.assertEqual({f.family for f in c.fonts["faces"] if f.role == "heading"}, {"Bebas Neue"})
        fails = items(preflight.run(lib, bid), "fonts", "fail")
        self.assertEqual([x["message"] for x in fails], ["“Ж” isn't in Bebas Neue: it would print in another font."])

    def test_kdp_page_count_and_trim(self):
        lib, bid, _ = make_book(["# The Harbour\n\n" + prose(200)], design={"printer": "kdp", "trim": "135x210"})
        r = preflight.run(lib, bid)
        self.assertLess(r["pages"], 24)
        fails = items(r, "page_count", "fail")
        self.assertEqual(len(fails), 1, fails)
        self.assertIn("24", fails[0]["message"])
        self.assertIn(str(r["pages"]), fails[0]["message"])
        warns = items(r, "page_count", "warn")
        self.assertEqual(len(warns), 1)
        self.assertIn("135 × 210 mm", warns[0]["message"])
        self.assertIn("5.25 × 8 in", warns[0]["message"])
        self.assertIn("5.5 × 8.5 in", warns[0]["message"])
        # margins below the printer's minimums
        compose.set_design(lib, bid, changes={"trim": "5.5x8.5in", "margins": {"inside": 8, "top": 6}})
        r = preflight.run(lib, bid)
        messages = [x["message"] for x in items(r, "page_count", "fail")]
        self.assertEqual(len(messages), 3, messages)
        self.assertTrue(any("inside margin" in m and "9.6 mm" in m for m in messages))
        self.assertTrue(any("top margin" in m and "6.4 mm" in m for m in messages))
        self.assertEqual(items(r, "page_count", "warn"), [])
        # IngramSpark's 0.5 in margins are a recommendation in its guide: narrower ones are a warning, not a failure
        compose.set_design(lib, bid, changes={"printer": "ingramspark"})
        r = preflight.run(lib, bid)
        self.assertFalse(any("margin" in x["message"] for x in items(r, "page_count", "fail")))
        warns = [x["message"] for x in items(r, "page_count", "warn")]
        self.assertEqual(len(warns), 2, warns)
        self.assertTrue(any("inside margin" in m and "recommends at least 12.7 mm" in m for m in warns))
        self.assertTrue(any("top margin" in m and "recommends at least 12.7 mm" in m for m in warns))
        # the other printer's 10 mm is Studio's guess, not a printer's rule: a warning too
        compose.set_design(lib, bid, changes={"printer": "other"})
        r = preflight.run(lib, bid)
        self.assertEqual(items(r, "page_count", "fail"), [])
        self.assertEqual([x["message"] for x in items(r, "page_count", "warn")],
                         ["The inside margin is 8 mm; printers usually ask for at least 10 mm.",
                          "The top margin is 6 mm; printers usually ask for at least 10 mm."])

    def test_generated_pages_checks(self):
        lib, bid, files = make_book(["# The Harbour\n\nThe boats came in.^[At dawn.] As one writer said [@nope].\n\n"
                                     "A [harbour wall]{.idx} too.\n"],
                                    features={"notes": "endnotes", "index": True})
        r = preflight.run(lib, bid)
        fails = items(r, "generated", "fail")
        self.assertEqual(len(fails), 1, fails)
        self.assertIn("Notes", fails[0]["message"])
        warns = items(r, "generated", "warn")
        self.assertEqual(len(warns), 2, warns)
        self.assertIn("nope", warns[0]["message"])
        self.assertIn("Sources", warns[0]["message"])
        self.assertNotIn("sources.json", warns[0]["message"])           # the author's words, not a file name
        self.assertEqual((warns[0]["file"], warns[0]["block"]), (files[0], 1))
        self.assertIn("Index", warns[1]["message"])
        # with the pages in the book there is nothing to say
        meta = lib.read(bid)
        lib.update(bid, {"contents": [{k: v for k, v in e.items()} for e in meta["contents"]]
                         + [{"auto": "notes"}, {"auto": "index"}]})
        lib.save_sources(bid, [{"id": "nope", "type": "book", "title": "A Book", "issued": {"date-parts": [[2001]]}}])
        self.assertEqual(items(preflight.run(lib, bid), "generated"), [])
        # a contents page with nothing after it to list (a notes page with no notes isn't in the pages to list)
        for back in ((), ("notes",)):
            lib, bid, _ = make_book(["Just text, no title.\n"], back=back)
            warns = items(preflight.run(lib, bid), "generated", "warn")
            self.assertEqual(len(warns), 1)
            self.assertIn("contents", warns[0]["message"].lower())

    def test_pages_left_out_are_said(self):
        """Each generated page left out of the pages gets a line for the record, saying why; it counts as nothing
        to fix."""
        lib, bid, _ = make_book(["# The Harbour\n\nThe boats came in.^[At dawn.]\n"],
                                back=("notes", "bibliography", "index"),
                                features={"notes": "footnotes", "sources": True, "index": True})
        r = preflight.run(lib, bid)
        self.assertEqual([x["message"] for x in items(r, "generated", "info")],
                         ["The notes page is left out: the notes are footnotes.",
                          "The bibliography is left out: nothing in the book cites a source yet.",
                          "The index is left out: no index terms are marked yet."])
        self.assertEqual(items(r, "generated", "warn") + items(r, "generated", "fail"), [])
        # a new memoir: endnotes on, none written yet
        lib, bid, _ = make_book(["# The Harbour\n\nText.\n"], back=("notes",))
        self.assertEqual([(x["level"], x["message"]) for x in items(preflight.run(lib, bid), "generated")],
                         [("info", "The notes page is left out: the book has no endnotes yet.")])
        # the index of first lines, in a book without poems
        lib, bid, _ = make_book(["# The Harbour\n\nText.\n"], back=("index",), features={"index": "first-lines"})
        self.assertEqual([x["message"] for x in items(preflight.run(lib, bid), "generated", "info")],
                         ["The index of first lines is left out: the book has no poems yet."])

    def test_typst_math_and_not_final(self):
        lib, bid, files = make_book(["# The Harbour\n\nText.\n", "# The Dunes\n\nText.\n"])
        meta = lib.read(bid)
        status = {files[0]: "draft", files[1]: "final"}
        lib.update(bid, {"contents": [dict(e, status=status[e["file"]]) if e.get("file") else e
                                      for e in meta["contents"]]})
        r = preflight.run(lib, bid)
        self.assertEqual(items(r, "typst"), [])
        # Typst's warnings and the math count, as a compile with them would carry them
        c = compose.compile_book(lib, bid)
        c = dataclasses.replace(c, warnings=["unknown font family: nowhere"],
                                ctx=dataclasses.replace(c.ctx, math=2))
        typ = preflight.typst(c, c.design, None)
        self.assertEqual([(x["level"], x["message"]) for x in typ],
                         [("info", "Typst noted: unknown font family: nowhere."),
                          ("info", "Math is printed as its TeX source for now (2 formulas).")])
        nf = items(r, "not_final")
        self.assertEqual(len(nf), 1)
        self.assertEqual(nf[0]["level"], "info")
        self.assertIn("The Harbour", nf[0]["message"])
        self.assertNotIn("The Dunes", nf[0]["message"])

    def test_untitled_pieces_named_by_kind(self):
        """A piece without a title is named by its kind, as the list of pieces names it, never by its file."""
        self.assertEqual(preflight.piece_name({"title": "The Harbour", "kind": "chapter"}), "“The Harbour”")
        self.assertEqual(preflight.piece_name({"title": "", "kind": "dedication", "file": "dedication.md"}),
                         "Dedication")
        self.assertEqual(preflight.piece_name({"kind": "content-note"}), "Content note")
        self.assertEqual(preflight.piece_name({"kind": "dedication"}, sentence=True), "the dedication")
        self.assertEqual(preflight.piece_name({"kind": "about-author"}, sentence=True), "the piece about the author")
        # an untitled chapter running onto a short last page, an untitled dedication, a titled chapter that is final
        ones = "\n\n".join(f"Line {k} of the text here." for k in range(80))
        lib, bid, files = make_book([ones + "\n", "# The Dunes\n\nText.\n"])
        c = compose.compile_book(lib, bid)
        i = index_of(lib, bid, files[0])
        pages = Counter(m["page"] for m in c.markers["blk"] if m["p"] == i)
        holds = pages[min(pages)]                       # an untitled chapter's first page, counted by Typst
        lib.save_piece(bid, files[0], md="\n\n".join(f"Line {k} of the text here." for k in range(holds + 2)) + "\n")
        dedication = lib.new_piece(bid, "dedication", "prose")["file"]
        lib.save_piece(bid, dedication, md="For the harbour master.\n")
        status = {files[0]: "draft", files[1]: "final", dedication: "idea"}
        lib.update(bid, {"contents": [dict(e, status=status[e["file"]]) if e.get("file") else e
                                      for e in lib.read(bid)["contents"]]})
        r = preflight.run(lib, bid)
        self.assertEqual([x["message"] for x in items(r, "short_last_pages")],
                         ["The last page of the chapter holds only 2 lines."])
        self.assertEqual([x["message"] for x in items(r, "not_final")],
                         ["2 pieces aren't marked final yet: Chapter, Dedication."])     # in contents order
        self.assertFalse(any(".md" in x["message"] for x in r["items"]))

    def test_report_saved(self):
        lib, bid, _ = make_book(["# The Harbour\n\n" + prose(200)], design={"printer": "kdp"})
        self.assertIsNone(preflight.last(lib, bid))
        calls = []
        r = preflight.run(lib, bid, progress=lambda done, total: calls.append((done, total)))
        self.assertEqual(set(r), {"summary", "items", "pages", "at", "signature"})
        self.assertEqual(calls[0], (0, len(preflight.CHECKS)))
        self.assertEqual(calls[-1], (len(preflight.CHECKS), len(preflight.CHECKS)))
        self.assertEqual(preflight.last(lib, bid), r)
        self.assertTrue((lib.dir(bid) / ".studio" / "preflight.json").is_file())
        for x in r["items"]:
            self.assertEqual(set(x), {"check", "level", "message", "page", "file", "block"})
            self.assertIn(x["level"], ("fail", "warn", "info"))
        fails = sum(x["level"] == "fail" for x in r["items"])
        warns = sum(x["level"] == "warn" for x in r["items"])
        self.assertGreater(fails, 0)                                     # too few pages for KDP
        want = ", ".join([f"{fails} to fix"] + ([f"{warns} to look at"] if warns else []))       # failures first
        self.assertEqual(r["summary"], want)
        order = [preflight.CHECKS.index(x["check"]) for x in r["items"]]
        self.assertEqual(order, sorted(order))

    def test_typst_error_reported(self):
        lib, bid, files = make_book(["# The Harbour\n\nText.\n"])

        def broken(self, *args, **kwargs):
            raise typst.TypstError("unknown variable: x")

        with mock.patch.object(typst.Compiler, "compile_with_warnings", broken):
            r = preflight.run(lib, bid)
        self.assertEqual([(x["check"], x["level"]) for x in r["items"]], [("typst", "fail")])
        self.assertIn("unknown variable: x", r["items"][0]["message"])
        self.assertEqual(r["summary"], "1 to fix")


if __name__ == "__main__":
    unittest.main()
