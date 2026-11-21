"""The composer service: staging, compiling, pages, the page map, the PDF and the design calls.

Books are built with `Books` in a temp library (STUDIO_ART, STUDIO_CACHE, STUDIO_CONFIG point at temp folders) and set
in Literata, which typeset_fonts cuts once for the whole module: the cache folder is shared by every test, because
cutting a family takes seconds."""
import hashlib
import json
import io
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import typst
from PIL import Image

from studio import book_export, books, compose, config, typeset_fonts
from studio.books import BooksError

_ENV = ("STUDIO_ART", "STUDIO_CACHE", "STUDIO_CONFIG")
TMP = None
_SAVED = {}
_COUNT = itertools.count()

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


def png(mode="RGB", size=(60, 40), colour=(200, 40, 40)):
    out = io.BytesIO()
    Image.new(mode, size, colour).save(out, "PNG")
    return out.getvalue()


def encoded(im, fmt, **options) -> bytes:
    out = io.BytesIO()
    im.save(out, fmt, **options)
    return out.getvalue()


def stripes(mode, values, height=10, width=10):
    """An image of vertical stripes, `width` pixels each, one per value: a tone ramp to check a conversion by."""
    im = Image.new(mode, (width * len(values), height))
    im.putdata([values[x // width] for _ in range(height) for x in range(width * len(values))])
    return im


def tones(path, at=(5, 15, 25, 35), y=5) -> list:
    with Image.open(path) as im:
        return [im.getpixel((x, y)) for x in at]


def colour_channels(pdf: bytes) -> set:
    """The channel counts of the PDF's ICC colour profiles: Typst writes every colour space as one (1 for grey, 3 for
    RGB), never as /DeviceRGB, so this is how a colour image shows."""
    return {int(n) for n in re.findall(rb"/N\s+(\d+)", pdf)}


def setUpModule():
    global TMP
    TMP = Path(tempfile.mkdtemp(prefix="studio-compose-"))
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


def make_book(chapters, kind="memoir", title=None, design=None, autos=("toc",), back=("notes",)):
    """A book in a library of its own: the three title pages, `autos`, a chapter per markdown text, then `back`.
    Set in Literata unless `design` says otherwise. Returns (Books, book id, the chapters' files)."""
    n = next(_COUNT)
    lib = books.Books(TMP / f"lib{n}" / "Books")
    bid = lib.create(title or f"The Grey Sea {n}", "Anna Example", "en", kind, start=False)["id"]
    contents = [{"auto": a} for a in ("half-title", "title-page", "copyright", *autos)]
    files = []
    for md in chapters:
        p = lib.new_piece(bid, "chapter", "prose")
        lib.save_piece(bid, p["file"], md=md)
        contents.append({"file": p["file"], "kind": "chapter", "form": "prose"})
        files.append(p["file"])
    contents += [{"auto": a} for a in back]
    lib.update(bid, {"contents": contents, "design": {"text": {"font": "Literata"}, **(design or {})}})
    return lib, bid, files


class ComposeTest(unittest.TestCase):
    def test_pages_and_blocks(self):
        lib, bid, files = make_book(["# The Harbour\n\n" + prose(1200) + "\n\nThe boats came in.\n\n::: pagebreak\n:::"
                                     "\n\n## Low tide\n\n" + prose(400), "# The Dunes\n\n" + prose(300)])
        r = compose.pages(lib, bid)
        self.assertIsNone(r["error"])
        self.assertEqual(r["count"], len(r["pages"]))
        self.assertEqual(r["count"] % 2, 0)
        self.assertEqual((r["width"], r["height"], r["paper"]), (139.7, 215.9, "cream"))   # what the pages were set at
        for p in r["pages"]:
            self.assertRegex(p["hash"], r"^[0-9a-f]{40}$")
            self.assertIn(p["side"], ("recto", "verso"))
        self.assertEqual([p["side"] for p in r["pages"][:2]], ["recto", "verso"])
        doc = lib.piece(bid, files[0])["doc"]
        first = r["blocks"][files[0]]
        self.assertEqual(len(first), len(doc["content"]))
        self.assertEqual(first, sorted(first))
        self.assertGreater(first[-1], first[0])                     # the chapter runs over several pages
        low = next(k for k, n in enumerate(doc["content"]) if n["type"] == "heading")
        self.assertEqual(doc["content"][low - 1]["type"], "page_break")
        self.assertEqual(first[low], first[low - 2] + 1)            # the page break puts the section on the next page
        meta = lib.read(bid)
        i = next(k for k, e in enumerate(meta["contents"]) if e.get("file") == files[0])
        self.assertEqual(r["pages"][first[0]]["entry"], i)          # its first block is on its own first page
        self.assertEqual(r["pages"][first[-1]]["entry"], i)
        self.assertEqual(r["pages"][0]["entry"], 0)                 # the half-title
        svg = compose.page_svg(r["pages"][0]["hash"])
        self.assertTrue(svg.lstrip().startswith(b"<svg"))
        self.assertEqual(hashlib.sha1(svg).hexdigest(), r["pages"][0]["hash"])
        self.assertIsNone(compose.page_svg("0" * 40))
        self.assertIsNone(compose.page_svg("../x"))
        with mock.patch.object(compose, "PAGE_CACHE", 3):              # the oldest pages go first
            compose.pages(lib, bid)
            self.assertIsNone(compose.page_svg(r["pages"][0]["hash"]))
            self.assertIsNotNone(compose.page_svg(r["pages"][-1]["hash"]))
        c = compose.compile_book(lib, bid)
        notes = len(meta["contents"]) - 1               # the notes page: the chapters have no notes, so it isn't set
        self.assertEqual(meta["contents"][notes], {"auto": "notes"})
        self.assertEqual([m["i"] for m in c.markers["piece-start"]], list(range(notes)))
        self.assertEqual(c.left_out, {notes: "the book has no endnotes yet"})
        self.assertEqual(r["left"], [{"entry": notes, "why": "the book has no endnotes yet"}])
        self.assertNotIn(notes, {p["entry"] for p in r["pages"]})
        blk = c.markers["blk"][0]
        self.assertEqual(set(blk), {"p", "b", "page", "y"})
        self.assertGreater(blk["y"], 0)
        for m in c.markers["blk"]:
            if m["p"] == i:
                self.assertEqual(first[m["b"]], m["page"] - 1)

    def test_recompile_only_when_changed(self):
        lib, bid, files = make_book(["# One\n\n" + prose(900), "# Two\n\n" + prose(900, 7), "# Three\n\n" + prose(300)])
        first = compose.pages(lib, bid)
        t = time.perf_counter()
        again = compose.pages(lib, bid)
        self.assertLess(time.perf_counter() - t, 0.05)
        self.assertEqual(again["signature"], first["signature"])
        md = lib.piece(bid, files[1])["md"]
        lib.save_piece(bid, files[1], md=md.replace("the grey sea", "the grey and restless sea", 1))
        changed = compose.pages(lib, bid)
        self.assertNotEqual(changed["signature"], first["signature"])
        meta = lib.read(bid)
        two = next(k for k, e in enumerate(meta["contents"]) if e.get("file") == files[1])
        start = next(n for n, p in enumerate(first["pages"]) if p["entry"] == two)
        self.assertGreater(start, 4)
        self.assertEqual([p["hash"] for p in changed["pages"][:start]], [p["hash"] for p in first["pages"][:start]])
        self.assertNotEqual([p["hash"] for p in changed["pages"]], [p["hash"] for p in first["pages"]])

    def test_fonts_being_cut_are_said(self):
        """While a compile waits for faces to be cut, `cutting` names their families (asked from another request, so
        it never waits for the book's lock); once the compile is done it names none."""
        lib, bid, _ = make_book(["# One\n\nText.\n"])
        seen, real = [], typeset_fonts.prepare

        def prepare(roles, cache, on_cut=None):
            on_cut("Literata")
            asked = []
            t = threading.Thread(target=lambda: asked.append(compose.cutting(lib, bid)))
            t.start()
            t.join(5)
            seen.append(asked)
            return real(roles, cache)

        self.assertEqual(compose.cutting(lib, bid), [])
        with mock.patch.object(typeset_fonts, "prepare", prepare):
            compose.compile_book(lib, bid)
        self.assertEqual(seen, [[["Literata"]]])
        self.assertEqual(compose.cutting(lib, bid), [])
        with self.assertRaises(BooksError):
            compose.cutting(lib, "nope")

    def test_concurrent_requests_compile_once(self):
        lib, bid, _ = make_book(["# One\n\n" + prose(400)])
        calls = []
        original = typst.Compiler.compile_with_warnings

        def counting(self, *args, **kwargs):
            calls.append(1)
            time.sleep(0.3)             # long enough for the second request to arrive while this one compiles
            return original(self, *args, **kwargs)

        results, barrier = [], threading.Barrier(2)

        def request():
            barrier.wait()
            results.append(compose.compile_book(lib, bid))

        with mock.patch.object(typst.Compiler, "compile_with_warnings", counting):
            threads = [threading.Thread(target=request) for _ in range(2)]
            for th in threads:
                th.start()
            for th in threads:
                th.join(120)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 2)
        self.assertIs(results[0], results[1])
        self.assertIsNone(results[0].error)

    def test_broken_material_still_sets(self):
        n = next(_COUNT)
        lib = books.Books(TMP / f"lib{n}" / "Books")
        bid = lib.create("Broken Things", "Anna Example", "en", "memoir", start=False)["id"]
        (lib.root / "outside.png").write_bytes(png())             # beside the book, not in it
        (lib.root / "pier.png").write_bytes(png())                # and one named like an image the book has
        lib.save_image(bid, "pier.png", png())
        texts = ["# Pictures\n\n![Gone](../images/gone.png)\n\n![Out](../../outside.png)\n\n![Pier](../../pier.png)\n\n"
                 "![Pier](../images/pier.png)\n\nText after.\n",
                 '# Poems\n\n::: {.poem src="Series/gone"}\n:::\n\nText after the poem.\n',
                 "",
                 "Just text, and no title.\n"]
        contents = [{"auto": "half-title"}, {"auto": "title-page"}, {"auto": "copyright"}, {"auto": "toc"}]
        for md in texts:
            p = lib.new_piece(bid, "chapter", "prose")
            if md:
                lib.save_piece(bid, p["file"], md=md)
            contents.append({"file": p["file"], "kind": "chapter", "form": "prose"})
        lib.update(bid, {"contents": contents, "design": {"text": {"font": "Literata"}}})
        c = compose.compile_book(lib, bid)
        self.assertIsNone(c.error)
        self.assertGreater(len(c.pages), 4)
        self.assertEqual(sorted(src for _, src in c.ctx.missing_images),
                         ["../../outside.png", "../../pier.png", "../images/gone.png"])
        self.assertEqual(c.ctx.images, {"../images/pier.png": "images/pier.png"})
        staged = [p.name for p in c.staging.rglob("*")]
        self.assertNotIn("outside.png", staged)
        self.assertNotIn("outside.png", (c.staging / "main.typ").read_text(encoding="utf-8"))

    def test_unreadable_piece_is_named(self):
        lib, bid, files = make_book(["# One\n\nText."])
        (lib.dir(bid) / "manuscript" / files[0]).write_bytes("# Café\n".encode("cp1252"))
        with self.assertRaises(BooksError) as e:
            compose.compile_book(lib, bid)
        self.assertIn(files[0], str(e.exception))
        self.assertIn("isn't readable text", str(e.exception))

    def test_grey_interior_stages_grey_images(self):
        lib, bid, files = make_book(["# One\n\nText."])
        src = lib.save_image(bid, "harbour.png", png())
        lib.save_piece(bid, files[0], md=f"# One\n\n![The harbour]({src}){{width=50%}}\n\nText.\n")
        c = compose.compile_book(lib, bid)
        self.assertIsNone(c.error)
        self.assertEqual(c.ctx.missing_images, [])
        staged = c.staging / "images" / "harbour.png"
        with Image.open(staged) as im:
            self.assertEqual(im.mode, "L")
        self.assertEqual(colour_channels(compose.pdf(lib, bid)), {1})
        compose.set_design(lib, bid, changes={"interior": "colour"})
        c = compose.compile_book(lib, bid)
        with Image.open(staged) as im:
            self.assertEqual(im.mode, "RGB")
        self.assertEqual(colour_channels(compose.pdf(lib, bid)), {1, 3})        # the image is in colour
        compose.set_design(lib, bid, changes={"interior": "grey"})
        c = compose.compile_book(lib, bid)
        with Image.open(staged) as im:
            self.assertEqual(im.mode, "L")
        self.assertEqual(colour_channels(compose.pdf(lib, bid)), {1})           # and the compiler read it again

    def test_pdf_is_print_ready(self):
        lib, bid, files = make_book(["# One\n\n" + prose(600) + "^[A note.]", "# Two\n\n" + prose(300)])
        src = lib.save_image(bid, "dunes.png", png(size=(300, 200)))
        lib.save_piece(bid, files[1], md=f"# Two\n\n{prose(300)}\n\n![The dunes]({src}){{width=60%}}\n")
        count = compose.pages(lib, bid)["count"]
        data = compose.pdf(lib, bid)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", data)), count)
        design = compose.get_design(lib, bid)["design"]
        want = (0, 0, design["width"] * 72 / 25.4, design["height"] * 72 / 25.4)
        boxes = re.findall(rb"/MediaBox\s*\[([^\]]*)\]", data)
        self.assertEqual(len(boxes), count)
        for box in boxes:
            for got, w in zip((float(x) for x in box.split()), want):
                self.assertAlmostEqual(got, w, delta=0.01)
        self.assertTrue(b"/FontFile2" in data or b"/FontFile3" in data)
        self.assertNotIn(b"/DeviceRGB", data)
        self.assertEqual(colour_channels(data), {1})        # black is one-channel grey, the image a grey copy
        self.assertIn(b"/Outlines", data)                   # bookmarks for the pieces
        self.assertRegex(data, rb"/Lang\s*\(en\)")
        self.assertIn(lib.read(bid)["title"].encode(), data)

    def test_export_pdf_keeps_a_dated_copy(self):
        lib, bid, _ = make_book(["# One\n\n" + prose(300)], title="Salt and Light")
        name, data, ctype = book_export.export(lib, bid, "pdf", now=datetime(2026, 11, 13, 14, 5))
        self.assertEqual((name, ctype), ("Salt and Light.pdf", "application/pdf"))
        kept = lib.dir(bid) / "exports" / "Salt and Light 2026-11-13 1405.pdf"
        self.assertTrue(kept.is_file())
        self.assertEqual(kept.read_bytes(), data)
        r = compose.export_pdf(lib, bid, now=datetime(2026, 11, 13, 14, 5))
        self.assertEqual(r["name"], "Salt and Light.pdf")
        self.assertEqual(Path(r["path"]).name, "Salt and Light 2026-11-13 1405-2.pdf")       # never over the first
        self.assertEqual(r["size"], Path(r["path"]).stat().st_size)
        self.assertEqual(r["pages"], compose.pages(lib, bid)["count"])

    def test_render_pages(self):
        lib, bid, _ = make_book(["# One\n\n" + prose(300)])
        count = compose.pages(lib, bid)["count"]
        out = compose.render_pages(lib, bid, pages=[1, count], ppi=36)
        self.assertEqual(len(out), 2)
        for data in out:
            self.assertTrue(data.startswith(b"\x89PNG"))
        with Image.open(io.BytesIO(out[0])) as im:
            design = compose.get_design(lib, bid)["design"]
            self.assertAlmostEqual(im.width, design["width"] / 25.4 * 36, delta=1.5)
        self.assertEqual(len(compose.render_pages(lib, bid, ppi=24)), count)
        svgs = compose.render_pages(lib, bid, pages=[2], fmt="svg")
        self.assertEqual(hashlib.sha1(svgs[0]).hexdigest(), compose.pages(lib, bid)["pages"][1]["hash"])
        for bad in ([0], [count + 1], ["1"]):
            with self.assertRaises(BooksError):
                compose.render_pages(lib, bid, pages=bad)

    def test_render_limits(self):
        lib, bid, _ = make_book(["# One\n\n" + prose(200)])
        compose.pages(lib, bid)
        for ppi in (0, 301, 600, True, "96"):
            with self.assertRaises(BooksError) as e:
                compose.render_pages(lib, bid, pages=[1], ppi=ppi)
            self.assertIn("1 to 300", str(e.exception))
        drawn = []
        original = typst.Compiler.compile

        def counting(self, *args, **kwargs):
            drawn.append(kwargs.get("format"))
            return original(self, *args, **kwargs)

        with mock.patch.object(typst.Compiler, "compile", counting):
            self.assertEqual(compose.render_pages(lib, bid, pages=[]), [])
            self.assertEqual(drawn, [])                                 # nothing asked, nothing drawn
            self.assertEqual(len(compose.render_pages(lib, bid, pages=[1], ppi=300)), 1)
        self.assertEqual(drawn, ["png"])

    def test_waiting_in_one_process_is_limited(self):
        lib, bid, _ = make_book(["# One\n\nText."])
        _, job = compose._job(lib, bid)
        calls = {"compile": lambda: compose.compile_book(lib, bid), "pdf": lambda: compose.pdf(lib, bid),
                 "render": lambda: compose.render_pages(lib, bid, pages=[1])}
        got = {}

        def run(name, call):
            try:
                call()
                got[name] = None
            except BooksError as e:
                got[name] = (e.code, str(e))

        self.assertTrue(job.lock.acquire(timeout=5))            # another request of this process is setting the book
        try:
            with mock.patch.object(compose, "LOCK_WAIT", 0.3):
                threads = [threading.Thread(target=run, args=item, daemon=True) for item in calls.items()]
                for th in threads:
                    th.start()
                for th in threads:
                    th.join(10)
                self.assertFalse(any(th.is_alive() for th in threads), "a call waited without a limit")
        finally:
            job.lock.release()
        title = lib.read(bid)["title"]
        for name in calls:
            self.assertEqual(got[name], (409, f"{title} is being set in another window; try again in a moment."))
        self.assertIsNone(compose.compile_book(lib, bid).error)

    def test_grey_copies_keep_their_tones(self):
        """Every kind of image the book takes comes out as 8-bit grey with its tones: 16-bit grey scaled, not clipped
        to white; grey images that need no change copied as they are."""
        lib, bid, files = make_book(["# One\n\nText."])
        d = lib.dir(bid) / "images"
        sixteen = stripes("I;16", [0, 20000, 40000, 65535])
        (d / "ramp16.png").write_bytes(encoded(sixteen, "PNG"))
        (d / "veil.png").write_bytes(encoded(Image.new("LA", (40, 10), (100, 128)), "PNG"))
        (d / "photo.jpg").write_bytes(encoded(Image.new("RGB", (40, 10), (200, 40, 40)), "JPEG", quality=95))
        (d / "grey.jpg").write_bytes(encoded(Image.new("L", (40, 10), 120), "JPEG", quality=90))
        flag = Image.new("RGB", (40, 10), (200, 40, 40)).convert("P", palette=Image.Palette.ADAPTIVE)  # keeps the red
        (d / "flag.gif").write_bytes(encoded(flag, "GIF"))
        (d / "sky.webp").write_bytes(encoded(Image.new("RGB", (40, 10), (40, 80, 200)), "WEBP", lossless=True))
        names = ("ramp16.png", "veil.png", "photo.jpg", "grey.jpg", "flag.gif", "sky.webp")
        lib.save_piece(bid, files[0], md="# One\n\n" + "\n\n".join(f"![{n}](../images/{n})" for n in names) + "\n")
        c = compose.compile_book(lib, bid)
        self.assertIsNone(c.error)
        self.assertEqual(c.ctx.missing_images, [])
        staged = {n: c.staging / c.ctx.images[f"../images/{n}"] for n in names}
        self.assertEqual(staged["flag.gif"].name, "flag.gif.png")
        self.assertEqual(staged["sky.webp"].name, "sky.webp.png")
        modes = {}
        for n, path in staged.items():
            with Image.open(path) as im:
                modes[n] = im.mode
        self.assertEqual(modes, {"ramp16.png": "L", "veil.png": "LA", "photo.jpg": "L", "grey.jpg": "L",
                                 "flag.gif": "L", "sky.webp": "L"})
        for got, want in zip(tones(staged["ramp16.png"]), (0, 78, 156, 255)):
            self.assertAlmostEqual(got, want, delta=1)
        self.assertEqual(tones(staged["veil.png"])[0], (100, 128))
        red = round(0.299 * 200 + 0.587 * 40 + 0.114 * 40)        # the luminance of (200, 40, 40): 88
        self.assertAlmostEqual(tones(staged["photo.jpg"])[0], red, delta=3)
        self.assertAlmostEqual(tones(staged["flag.gif"])[0], red, delta=3)
        self.assertAlmostEqual(tones(staged["sky.webp"])[0], round(0.299 * 40 + 0.587 * 80 + 0.114 * 200), delta=2)
        self.assertEqual(staged["grey.jpg"].read_bytes(), (d / "grey.jpg").read_bytes())     # not encoded again
        self.assertEqual(colour_channels(compose.pdf(lib, bid)), {1})

    def test_an_image_replaced_while_it_is_copied_is_copied_again(self):
        """The copy is dated by the source as it was before it was read: an image replaced during the copy differs from
        its copy's date, so the next compile copies it again."""
        lib, bid, files = make_book(["# One\n\nText."])
        src = lib.dir(bid) / "images" / "tide.png"
        src.write_bytes(png(colour=(10, 10, 10)))
        lib.save_piece(bid, files[0], md="# One\n\n![Tide](../images/tide.png)\n")
        original = compose.Image.open

        def replacing(path, *args, **kwargs):
            im = original(path, *args, **kwargs)
            if Path(path) == src:
                im.load()
                src.write_bytes(png(colour=(250, 250, 250)))          # the author saves a new version meanwhile
                later = src.stat().st_mtime_ns + 5_000_000_000
                os.utime(src, ns=(later, later))
            return im

        with mock.patch.object(compose.Image, "open", replacing):
            c = compose.compile_book(lib, bid)
        staged = c.staging / "images" / "tide.png"
        self.assertLess(tones(staged, at=(5,))[0], 50)                 # the copy holds the old picture
        self.assertNotEqual(staged.stat().st_mtime_ns, src.stat().st_mtime_ns)
        compose.compile_book(lib, bid)
        self.assertGreater(tones(staged, at=(5,))[0], 200)             # and is made again from the new one
        self.assertEqual(staged.stat().st_mtime_ns, src.stat().st_mtime_ns)

    def test_set_design_round_trip(self):
        lib = books.Books(TMP / f"lib{next(_COUNT)}" / "Books")
        bid = lib.create("Plain Design", "Anna Example", "nl", "memoir", start=False)["id"]
        r = compose.set_design(lib, bid, changes={"text": {"size": 11}})
        self.assertEqual(r["design"]["text"]["size"], 11)
        self.assertEqual(r["stored"], {"text": {"size": 11}})
        self.assertEqual(r["design"]["template"], "literary")
        self.assertEqual({t["id"] for t in r["templates"]}, {"literary", "nonfiction", "academic", "poetry"})
        self.assertIn({"id": "135x210", "name": "135 × 210 mm", "width": 135, "height": 210}, r["trims"])
        self.assertIn("other", [p["id"] for p in r["printers"]])
        kdp = next(p for p in r["printers"] if p["id"] == "kdp")
        self.assertEqual(kdp["inside"][0], [150, 9.6])                  # the inside margin by page count, for the panel
        self.assertEqual(kdp["min"]["outside"], 6.4)
        self.assertEqual(json.loads(json.dumps(r)), r)                  # all of it travels as JSON
        self.assertIn("Literata", r["fonts"])
        categories = [compose.fonts.registry().get(f).category for f in r["fonts"]]
        self.assertEqual(categories[0], "serif")
        self.assertEqual(categories, sorted(categories, key=lambda c: {"serif": 0, "sans": 1}.get(c, 2)))
        r = compose.set_design(lib, bid, template="poetry")
        self.assertEqual(r["stored"], {"text": {"size": 11}, "template": "poetry"})
        self.assertEqual(r["design"]["heads"]["recto"], "none")
        r = compose.set_design(lib, bid, reset=["text"])
        self.assertEqual(r["stored"], {"template": "poetry"})
        self.assertEqual(r["design"]["text"]["size"], 10.5)
        self.assertEqual(compose.get_design(lib, bid)["stored"], {"template": "poetry"})
        with self.assertRaises(BooksError) as e:
            compose.set_design(lib, bid, changes={"text": {"size": 99}})
        self.assertIn("text size", str(e.exception))

    def test_typst_error_keeps_last_pages(self):
        lib, bid, files = make_book(["# One\n\n" + prose(300)])
        good = compose.pages(lib, bid)
        self.assertIsNone(good["error"])

        def broken(self, *args, **kwargs):
            raise typst.TypstError("unknown variable: x")

        lib.save_piece(bid, files[0], md="# One\n\nA new start.\n\n" + prose(300))
        with mock.patch.object(typst.Compiler, "compile_with_warnings", broken):
            failed = compose.pages(lib, bid)
        self.assertIn("unknown variable: x", failed["error"])
        self.assertEqual(failed["pages"], good["pages"])
        self.assertNotEqual(failed["signature"], good["signature"])
        with self.assertRaises(BooksError):
            compose.pdf(lib, bid)
        lib.save_piece(bid, files[0], md="# One\n\nAnother start.\n\n" + prose(300))
        fixed = compose.pages(lib, bid)
        self.assertIsNone(fixed["error"])
        self.assertNotEqual(fixed["pages"], good["pages"])

    def test_another_process_holds_the_book(self):
        lib, bid, _ = make_book(["# One\n\nText."])
        staging = compose.staging_dir(lib.dir(bid))
        staging.mkdir(parents=True, exist_ok=True)
        holder = ("import sys, time, os\n"
                  "f = open(sys.argv[1], 'a+b')\n"
                  "if os.name == 'nt':\n"
                  "    import msvcrt; f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)\n"
                  "else:\n"
                  "    import fcntl; fcntl.flock(f.fileno(), fcntl.LOCK_EX)\n"
                  "print('locked', flush=True)\n"
                  "sys.stdin.read()\n")
        proc = subprocess.Popen([sys.executable, "-c", holder, str(staging / ".lock")], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "locked")
            with mock.patch.object(compose, "LOCK_WAIT", 0.5):
                with self.assertRaises(BooksError) as e:
                    compose.compile_book(lib, bid)
            self.assertEqual(e.exception.code, 409)
            self.assertEqual(str(e.exception), f"{lib.read(bid)['title']} is being set in another window; try "
                                               f"again in a moment.")
        finally:
            proc.stdin.close()
            proc.wait(10)
        self.assertIsNone(compose.compile_book(lib, bid).error)        # free again once that process lets go


if __name__ == "__main__":
    unittest.main()
