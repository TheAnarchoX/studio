"""Store tests: the library folder as the database. Run: python -m unittest discover tests

Set STUDIO_TEST_KIT to a series' _kit folder to run them against a real kit's build.py."""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from studio.store import Store, StoreError, dump_poem, slugify

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


if __name__ == "__main__":
    unittest.main()
