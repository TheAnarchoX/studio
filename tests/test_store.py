"""Store tests: the library folder as the database. Run: python -m unittest discover tests

Set STUDIO_TEST_KIT to a series' _kit folder to run them against a real kit's build.py."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from studio.store import Store, StoreError, dump_poem, slugify, write_text

KIT = Path(os.environ["STUDIO_TEST_KIT"]) if os.environ.get("STUDIO_TEST_KIT") else None


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-test-"))
        self.root = self.tmp / "Poems"
        kit = self.root / "Calls" / "_kit"
        (kit / "concepts").mkdir(parents=True)
        if KIT and (KIT / "build.py").exists():
            shutil.copy(KIT / "build.py", kit / "build.py")
        else:
            (kit / "build.py").write_text("RATIOS = {}\nVARIANTS = []\n", encoding="utf-8")
        for c in ("flare", "plain", "outside", "cast"):
            (kit / "concepts" / f"{c}.js").write_text(f'/* {c.upper()} — test */\nconcept("{c}",{{name:"{c.title()}"}});\n', encoding="utf-8")
        self.s = Store(self.root, self.tmp / "cache")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dump_matches_the_hand_made_style(self):
        text = ('{\n  "number": 1,\n  "title": "Hold the Line",\n  "slug": "hold-the-line",\n  "author": "A. Poet",\n'
                '  "lines": ["Hold the line", "when they push"],\n  "slides": [\n    {"concept": "flare"},\n    {"concept": "outside", "key": "out"}\n  ]\n}\n')
        self.assertEqual(dump_poem(json.loads(text)), text)

    def test_slugs_and_titles(self):
        self.assertEqual(slugify("All That's Left of Me"), "all-thats-left-of-me")

    def test_create_numbers_and_resolves(self):
        a = self.s.create("Hold the Line")
        b = self.s.create("Second One")
        self.assertEqual((a["number"], b["number"]), (1, 2))
        self.assertEqual(a["status"], "draft")
        self.assertEqual(self.s.read("hold-the-line")["id"], "Calls/Hold the Line")   # by slug
        self.assertEqual(self.s.read("second one")["id"], "Calls/Second One")         # by title, any case
        with self.assertRaises(StoreError):
            self.s.create("Hold the Line")

    def test_drafts_are_dated_files_and_snapshot_the_old_text(self):
        p = self.s.create("Hold the Line")
        folder = Path(p["path"])
        poem = json.loads((folder / "poem.json").read_text(encoding="utf-8"))
        poem["lines"] = ["written before Studio"]
        (folder / "poem.json").write_text(dump_poem(poem), encoding="utf-8")
        old = time.time() - 3600
        os.utime(folder / "poem.json", (old, old))
        r = self.s.save_text(p["id"], "Hold the Line", "Hold the line\nwhen they push.\n\n")
        self.assertEqual(r["lines"], ["Hold the line", "when they push."])
        self.assertEqual(len(r["drafts"]), 2)                         # the snapshot + this save
        self.assertEqual(r["drafts"][-1]["lines"], ["written before Studio"])
        r = self.s.save_text(p["id"], "Hold the Line", "Hold the line\nwhen they push.")
        self.assertEqual(len(r["drafts"]), 2)                         # unchanged text: no new draft

    def test_status_and_slides(self):
        p = self.s.create("Hold the Line")
        self.assertEqual(self.s.set_status(p["id"], "ready")["status"], "ready")
        with self.assertRaises(StoreError):
            self.s.set_status(p["id"], "done")
        self.assertEqual(self.s.set_slides(p["id"], [{"concept": "flare"}, {"concept": "outside", "key": "out"}])[1]["key"], "out")
        with self.assertRaises(StoreError):
            self.s.set_slides(p["id"], [{"concept": "nope"}])

    def test_writing_notes_are_not_posting_notes(self):
        p = self.s.create("Hold the Line")
        self.s.save_notes(p["id"], "why this poem")
        folder = Path(p["path"])
        self.assertTrue((folder / "writing-notes.md").exists())
        self.assertFalse((folder / "NOTES.md").exists())

    def test_series_entity(self):
        s = self.s.create_series("Night Letters", "Letters written at night.", "Blood")
        self.assertEqual(s["name"], "Night Letters")
        self.assertEqual(s["palette"][2]["hex"], "#7A0019")
        self.assertTrue((self.root / "Night Letters" / "series.json").exists())
        self.assertFalse(s["has_kit"])
        p = self.s.create("First", "Night Letters")
        self.assertTrue(self.s.read(p["id"])["art"].get("no_kit"))
        self.assertEqual(self.s.update_series("Night Letters", {"tagline": "New."})["tagline"], "New.")
        with self.assertRaises(StoreError):
            self.s.update_series("Night Letters", {"palette": [{"name": "x", "hex": "red"}]})

    def test_checks_validation(self):
        self.s.create_series("Night Letters")
        self.assertEqual(self.s.series_read("Night Letters")["checks"]["near"], 10.0)
        r = self.s.update_series("Night Letters", {"checks": {"near": 4, "story_top": 200}})
        self.assertEqual((r["checks"]["near"], r["checks"]["story_top"], r["checks"]["align"]), (4, 200, 1.0))
        self.assertEqual(self.s.read(self.s.create("P", "Night Letters")["id"])["series_info"]["checks"]["near"], 4)
        r = self.s.update_series("Night Letters", {"checks": {"near": None}})     # reset one field
        self.assertEqual((r["checks"]["near"], r["checks"]["story_top"]), (10.0, 200))
        for bad in ({"align": 21}, {"align": -1}, {"near": 101}, {"align": 5, "near": 5}, {"phone": 100},
                    {"phone": 1300}, {"min_phone": 0}, {"min_phone": 41}, {"story_top": 601}, {"story_bottom": -1},
                    {"story_top": "x"}, {"bogus": 1}):
            with self.assertRaises(StoreError, msg=str(bad)):
                self.s.update_series("Night Letters", {"checks": bad})
        with self.assertRaises(StoreError) as ctx:
            self.s.update_series("Night Letters", {"checks": {"align": 12}})
        self.assertEqual(str(ctx.exception), "Near misses (10 px) must be larger than the alignment tolerance "
                         "(12 px); near can be up to 100.")
        self.assertEqual(self.s.series_read("Night Letters")["checks"]["story_top"], 200)

    def test_update_poem_author(self):
        p = self.s.create("Hold the Line")
        out = self.s.update_poem_details(p["id"], {"author": "  A. Poet  "})
        self.assertEqual(out["author"], "A. Poet")
        self.s.update_poem_details(p["id"], {"author": "B. Poet"})
        path = self.root / "Calls" / "Hold the Line" / "poem.json"
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["author"], "B. Poet")
        self.assertEqual(path.read_text(encoding="utf-8"), dump_poem(saved))      # compact style kept
        out = self.s.update_poem_details(p["id"], {"author": ""})
        self.assertIsNone(out["author"])
        self.assertNotIn("author", json.loads(path.read_text(encoding="utf-8")))
        with self.assertRaisesRegex(StoreError, "120"):
            self.s.update_poem_details(p["id"], {"author": "x" * 121})
        with self.assertRaises(StoreError):
            self.s.update_poem_details(p["id"], {"author": 5})

    def test_read_gives_the_editor_the_series_formats(self):
        p = self.s.create("Hold the Line")
        self.assertEqual(self.s.read(p["id"])["series_info"]["formats"], ["1:1", "4:5", "9:16"])
        self.s.update_series("Calls", {"formats": ["9:16"]})
        self.assertEqual(self.s.read(p["id"])["series_info"]["formats"], ["9:16"])

    def test_update_series_formats(self):
        self.s.create_series("Night Letters", "Letters written at night.")
        s = self.s.update_series("Night Letters", {"formats": ["4:5", "1:1"]})
        self.assertEqual(s["formats"], ["1:1", "4:5"])
        saved = json.loads((self.root / "Night Letters" / "series.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["formats"], ["1:1", "4:5"])
        for bad in ([], ["2:3"], ["1:1", "2:3"], "1:1", None):
            with self.assertRaisesRegex(StoreError, "Formats are 1:1, 4:5 and 9:16."):
                self.s.update_series("Night Letters", {"formats": bad})
        self.assertEqual(self.s.series_read("Night Letters")["formats"], ["1:1", "4:5"])

    def test_update_series_writes_rules_and_concepts(self):
        self.s.create_series("Night Letters", "Letters written at night.")
        d = self.root / "Night Letters"
        meta = (d / "series.json").read_bytes()
        s = self.s.update_series("Night Letters", {"rules": "# Rules\r\n\r\n- Night only.\r\n", "concepts": "# Concepts\n\n## Lamp\n"})
        self.assertEqual((d / "README.md").read_text(encoding="utf-8"), "# Rules\n\n- Night only.\n")
        self.assertEqual((d / "CONCEPTS.md").read_text(encoding="utf-8"), "# Concepts\n\n## Lamp\n")
        self.assertEqual((s["rules"], s["concepts"]), ("# Rules\n\n- Night only.\n", "# Concepts\n\n## Lamp\n"))
        self.assertTrue(s["has_concepts"])
        self.assertEqual((s["style"]["look"], s["style"]["look_from"]), (s["look"], "series"))   # the series page's style
        self.assertEqual((d / "series.json").read_bytes(), meta)          # only the Markdown files change
        s = self.s.update_series("Night Letters", {"concepts": ""})       # emptied, not deleted
        self.assertEqual(((d / "CONCEPTS.md").read_text(encoding="utf-8"), s["concepts"]), ("", ""))
        self.s.update_series("Calls", {"concepts": ""})                     # nothing to write: no file made
        self.assertFalse((self.root / "Calls" / "CONCEPTS.md").exists())
        self.assertFalse((self.root / "Calls" / "series.json").exists())

    def test_own_palette_keeps_the_look_and_fonts(self):
        """Add to palette's "own copy" of a library palette: only the palette becomes the series' own."""
        self.s.create_series("Night Letters", look="Signal")
        d = self.root / "Night Letters"
        self.s.update_series("Night Letters", {"fonts": {"label": {"family": "Inter", "weight": 600}}})
        before = json.loads((d / "series.json").read_text(encoding="utf-8"))
        swatches = self.s.styles.palette("Signal")["swatches"] + [{"name": "#570000", "hex": "#570000"}]
        s = self.s.update_series("Night Letters", {"palette": {"name": "Signal", "swatches": swatches}})
        after = json.loads((d / "series.json").read_text(encoding="utf-8"))
        self.assertEqual((after["look"], after["fonts"]), (before["look"], before["fonts"]))   # look and fonts as they were
        self.assertEqual(after["palette"], {"name": "Signal", "swatches": swatches})
        self.assertEqual((s["look"], s["palette_linked"], s["palette_from"]), ("Signal", False, "series"))
        self.assertEqual([c["hex"] for c in s["palette"]][-1], "#570000")
        self.assertEqual((s["font_roles"]["display"]["family"], s["font_roles"]["label"]["family"]), ("Archivo", "Inter"))
        self.assertEqual(self.s.styles.palette("Signal")["source"], "bundled")                # the library is untouched
        self.assertFalse((self.tmp / "Poems" / "Styles").exists() or (self.root.parent / "Styles" / "palettes").exists())

    def test_designs_stamps_and_trash(self):
        p = self.s.create("Hold the Line")
        d = {"name": "Wall", "format": "45", "background": "#DA291C", "elements": [{"type": "rect", "x": 0, "y": 0, "w": 10, "h": 10}]}
        slug = self.s.save_design(p["id"], d)
        self.assertEqual(slug, "wall")
        self.assertEqual(self.s.save_design(p["id"], d), "wall-2")
        with self.assertRaises(StoreError):
            self.s.save_design(p["id"], {"name": "x", "elements": [{"type": "blob"}]})
        self.s.delete_design(p["id"], "wall")
        self.assertEqual([x["slug"] for x in self.s.read(p["id"])["designs"]], ["wall-2"])
        st = self.s.save_stamp("Calls", "Red star", [{"type": "shape", "kind": "star", "x": 0, "y": 0, "w": 50, "h": 50}], 50, 50)
        self.assertEqual([x["slug"] for x in self.s.stamps("Calls")], [st])
        dest = self.s.delete_poem(p["id"])
        self.assertTrue(dest.exists() and ".trash" in dest.parts)
        self.assertEqual(self.s.list(), [])

    def test_files_stay_inside_poems(self):
        with self.assertRaises(StoreError):
            self.s.file("../../secret.txt")


class WriteTextTest(unittest.TestCase):
    def test_threads_writing_one_file_do_not_collide(self):
        """The server answers requests on threads, so two can write one file at once: each write has its own temp file,
        none fails, and the file ends up holding one whole write."""
        tmp = Path(tempfile.mkdtemp(prefix="studio-write-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = tmp / "poem.json"
        texts = [f"{i}\n" + str(i % 10) * 50000 + "\n" for i in range(12)]
        start, errors = threading.Barrier(len(texts)), []

        def write(text):
            try:
                start.wait()
                for _ in range(10):
                    write_text(path, text)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
        threads = [threading.Thread(target=write, args=(t,)) for t in texts]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertIn(path.read_text(encoding="utf-8"), texts)
        self.assertEqual([p.name for p in tmp.iterdir()], ["poem.json"])      # no temp file left behind


if __name__ == "__main__":
    unittest.main()
