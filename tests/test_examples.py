"""The Examples series a fresh install can add, and the first-run flag."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio import config, examples, manuscript, store
from studio.books import Books
from studio.store import Store, StoreError
from tests.support import temp_studio


class ExamplesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-examples-"))
        self.root = self.tmp / "Poems"
        self.root.mkdir()
        self.store = Store(self.root, self.tmp / "cache")
        self.books = Books(self.tmp / "Books")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_examples(self):
        made = examples.add(self.store, self.store.styles, signature="")
        self.assertTrue(made)
        series = self.root / "Examples"
        meta = json.loads((series / "series.json").read_text(encoding="utf-8"))
        self.assertIs(meta["example"], True)
        self.assertEqual(meta["look"], "Editorial light")
        self.assertEqual(meta["tagline"], "Two short poems to try Studio with.")
        self.assertTrue((series / "README.md").read_text(encoding="utf-8").count("\n- ") >= 3)
        poems = self.store.list("Examples")
        self.assertEqual(sorted(p["title"] for p in poems), ["Morning, Unfinished", "What the River Keeps"])
        for p in poems:
            designs = self.store.designs(self.store.resolve(p["id"]))
            self.assertEqual(len(designs), 1)
            d = self.store.read_design(p["id"], designs[0]["slug"])
            self.assertEqual(d["format"], "45")
            self.assertEqual(d["background"], "#F7F5F0")
            text = [e for e in d["elements"] if e["type"] == "text"]
            self.assertEqual("\n".join(self.store.load(self.store.resolve(p["id"]))["lines"]), text[0]["text"])
            self.assertEqual([e for e in text if e.get("role") == "name"][0]["text"], "Your name")
        self.assertIn("Examples", [s["name"] for s in self.store.series_list()])

    def test_examples_follow_the_librarys_own_palette_without_roles(self):
        """The library's own Editorial light palette may lack roles: the colours are then taken by their place."""
        self.store.styles.save_palette({"name": "Editorial light", "swatches": [
            {"name": "Paper", "hex": "#FAFAFA", "role": "background"}, {"name": "Ink", "hex": "#111111"},
            {"name": "Red", "hex": "#CC0000"}, {"name": "Grey", "hex": "#777777"}]})
        self.assertTrue(examples.add(self.store, self.store.styles, signature=""))
        p = self.store.list("Examples")[0]
        d = self.store.read_design(p["id"], self.store.designs(self.store.resolve(p["id"]))[0]["slug"])
        poem, name = d["elements"]
        self.assertEqual((d["background"], poem["color"], name["color"]), ("#FAFAFA", "#111111", "#777777"))

    def test_a_failed_add_leaves_no_half_made_series(self):
        with mock.patch.object(self.store, "save_design", side_effect=StoreError("The disk is full.")):
            with self.assertRaisesRegex(StoreError, "disk is full"):
                examples.add(self.store, self.store.styles)
        self.assertFalse((self.root / "Examples").exists())
        self.assertEqual(len(examples.add(self.store, self.store.styles)), 4)      # and it can be added again

    def test_a_series_another_add_is_making_is_left_alone(self):
        """Two "Add examples" at once: when this call's create_series fails because the other call has just made the
        folder, the other call's series is not taken away from under it."""
        d = self.root / "Examples"

        def made_by_the_other_call(*a, **kw):
            d.mkdir()
            (d / "series.json").write_text('{"name": "Examples"}', encoding="utf-8")
            raise StoreError("A series called Examples already exists.")
        with mock.patch.object(self.store, "create_series", side_effect=made_by_the_other_call):
            with self.assertRaises(StoreError):
                examples.add(self.store, self.store.styles)
        self.assertTrue((d / "series.json").exists())

    def test_the_other_add_wins_the_race_for_the_folder(self):
        """The same race through the real create_series: the other call makes the folder after this one looked."""
        d, palette = self.root / "Examples", self.store._palette

        def other_call_makes_it(p):
            d.mkdir()
            (d / "series.json").write_text('{"name": "Examples"}', encoding="utf-8")
            return palette(p)
        with mock.patch.object(self.store, "_palette", side_effect=other_call_makes_it):
            with self.assertRaisesRegex(StoreError, "already exists"):
                examples.add(self.store, self.store.styles)
        self.assertTrue((d / "series.json").exists())

    def test_a_series_that_fails_while_it_is_made_is_taken_away(self):
        with mock.patch.object(Store, "series_meta", side_effect=StoreError("The disk is full.")):
            with self.assertRaisesRegex(StoreError, "disk is full"):
                examples.add(self.store, self.store.styles)
        self.assertFalse((self.root / "Examples").exists())

    def test_add_examples_twice_adds_nothing(self):
        examples.add(self.store, self.store.styles)
        self.assertEqual(examples.add(self.store, self.store.styles), [])
        self.assertEqual(len(self.store.list("Examples")), 2)

    def test_remove_examples_moves_them_to_the_trash(self):
        examples.add(self.store, self.store.styles)
        (self.root / "Mine").mkdir()
        (self.root / "Mine" / "series.json").write_text('{"name": "Mine"}', encoding="utf-8")
        moved = examples.remove(self.store)
        self.assertEqual(len(moved), 2)      # the series and the example book
        moved = [m for m in moved if m.parent == self.root / ".trash"]
        self.assertEqual(len(moved), 1)
        self.assertFalse((self.root / "Examples").exists())
        self.assertTrue((self.root / "Mine").exists())
        self.assertEqual(moved[0].parent, self.root / ".trash")
        self.assertTrue((moved[0] / "series.json").exists())
        self.assertEqual(examples.remove(self.store), [])

    def test_remove_keeps_a_users_own_series_named_examples(self):
        (self.root / "Examples").mkdir()
        (self.root / "Examples" / "series.json").write_text('{"name": "Examples"}', encoding="utf-8")
        self.assertEqual(examples.remove(self.store), [])
        self.assertTrue((self.root / "Examples").exists())

    def test_signature_is_used(self):
        examples.add(self.store, self.store.styles, signature="A. Poet")
        p = self.store.list("Examples")[0]
        d = self.store.read_design(p["id"], self.store.designs(self.store.resolve(p["id"]))[0]["slug"])
        self.assertIn("A. Poet", [e["text"] for e in d["elements"] if e.get("role") == "name"])

    def test_examples_add_a_book(self):
        made = examples.add(self.store, self.store.styles)
        self.assertIn(self.books.root / "A Year of Small Things", made)
        book = self.books.read("A Year of Small Things")
        self.assertEqual((book["kind"], book["language"], book["look"], book["author"]), ("memoir", "en", "Warm linen", "Studio"))
        self.assertIs(book["example"], True)
        self.assertEqual([s["id"] for s in self.books.sources(book["id"])], ["field-notes"])
        pieces = [e for e in book["contents"] if e.get("file")]
        self.assertEqual([(e["kind"], e["form"]) for e in pieces],
                         [("dedication", "prose"), ("foreword", "prose"), ("chapter", "prose"), ("chapter", "prose"),
                          ("chapter", "poem")])
        self.assertEqual(pieces[0]["words"], 5)
        for e in pieces[1:]:
            self.assertTrue(80 <= e["words"] <= 200, (e["file"], e["words"]))
        self.assertEqual([e["auto"] for e in book["contents"] if e.get("auto")],
                         ["half-title", "title-page", "copyright", "toc", "notes", "bibliography"])
        foreword = self.books.piece(book["id"], pieces[1]["file"])
        self.assertEqual(foreword["notes"], 1)
        self.assertIn("[@field-notes", foreword["md"])
        self.assertEqual(self.books.piece(book["id"], pieces[2]["file"])["md"].count("\n***\n"), 1)
        self.assertIn("]{.idx}", self.books.piece(book["id"], pieces[2]["file"])["md"])
        self.assertEqual(self.books.piece(book["id"], pieces[4]["file"])["doc"]["attrs"], {"form": "poem"})

    def test_the_books_pieces_are_canonical(self):
        examples.add_book(self.books)
        book = self.books.read("A Year of Small Things")
        for e in book["contents"]:
            if e.get("file"):
                md = (self.books.dir(book["id"]) / "manuscript" / e["file"]).read_text(encoding="utf-8")
                self.assertEqual(manuscript.serialize(manuscript.parse(md, e.get("form", "prose")), e.get("form", "prose")), md)
        self.assertEqual(self.books.read(book["id"])["example"], True)
        self.assertTrue(json.loads((self.books.dir(book["id"]) / "sources.json").read_text(encoding="utf-8"))[0]["issued"])

    def test_adding_the_book_twice_adds_nothing(self):
        self.assertEqual(len(examples.add_book(self.books)), 1)
        self.assertEqual(examples.add_book(self.books), [])
        self.assertEqual(len(self.books.list()), 1)

    def test_a_failed_book_leaves_no_half_made_folder(self):
        with mock.patch.object(Books, "save_sources", side_effect=StoreError("The disk is full.")):
            with self.assertRaisesRegex(StoreError, "disk is full"):
                examples.add_book(self.books)
        self.assertEqual(self.books.dirs(), [])
        self.assertEqual(len(examples.add_book(self.books)), 1)

    def test_examples_remove_the_book(self):
        examples.add(self.store, self.store.styles)
        self.books.create("My Own Book", start=False)
        moved = examples.remove(self.store)
        trash = self.books.root / ".trash"
        self.assertTrue([m for m in moved if m.parent == trash and (m / "book.json").exists()])
        self.assertEqual([d.name for d in self.books.dirs()], ["My Own Book"])
        self.assertEqual(examples.remove_books(self.books), [])

    def test_the_book_goes_to_the_stores_own_library(self):
        """A temp Store never reaches the configured library: the Books folder is the one next to its Poems."""
        with mock.patch.object(config, "BOOKS", self.tmp / "Elsewhere" / "Books"):
            made = examples.add(self.store, self.store.styles)
        self.assertIn(self.tmp / "Books" / "A Year of Small Things", made)
        self.assertFalse((self.tmp / "Elsewhere").exists())
        with mock.patch.object(config, "BOOKS", self.tmp / "Elsewhere" / "Books"):
            examples.remove(self.store)
        self.assertEqual(self.books.dirs(), [])

    def test_a_book_with_the_examples_title_is_left_alone(self):
        """The poet's own book of that title is not touched and the examples still add: the example book is skipped."""
        self.books.create("A Year of Small Things", author="Me", start=False)
        made = examples.add(self.store, self.store.styles)
        self.assertEqual(len(made), 3)
        self.assertEqual(self.books.read("A Year of Small Things")["author"], "Me")
        self.assertEqual(len(examples.remove(self.store)), 1)      # the series only
        self.assertTrue((self.tmp / "Books" / "A Year of Small Things").exists())

    def test_a_failing_hook_takes_the_whole_add_away(self):
        """A hook that fails after the series and the book were made leaves neither: add() can be run again."""
        def broken():
            raise StoreError("The disk is full.")
        examples.EXTRA.append(broken)
        try:
            with self.assertRaisesRegex(StoreError, "disk is full"):
                examples.add(self.store, self.store.styles)
        finally:
            examples.EXTRA.pop()
        self.assertFalse((self.root / "Examples").exists())
        self.assertEqual(self.books.dirs(), [])
        self.assertEqual(len(examples.add(self.store, self.store.styles)), 4)

    def test_extra_hooks_run(self):
        calls = []
        examples.EXTRA.append(lambda: calls.append("add") or [])
        examples.EXTRA_REMOVE.append(lambda: calls.append("remove") or [])
        try:
            examples.add(self.store, self.store.styles)
            examples.remove(self.store)
        finally:
            examples.EXTRA.pop()
            examples.EXTRA_REMOVE.pop()
        self.assertEqual(calls, ["add", "remove"])


class ExamplesRouteTest(unittest.TestCase):
    def test_first_run_flag(self):
        with temp_studio() as st:
            code, info = st.get("/api/settings")
            self.assertTrue(info["first_run"])
            self.assertFalse(info["has_examples"])
            st.post("/api/settings", {"signature": "Someone"})
            self.assertFalse(st.get("/api/settings")[1]["first_run"])

    def test_a_library_with_series_skips_the_welcome(self):
        """A library from before 1.1 (series, but no settings file): its settings are written and there is no welcome."""
        with temp_studio() as st, mock.patch.dict(os.environ):
            os.environ.pop("STUDIO_ART")      # the library as Studio's own default, not an environment override
            (st.root / "Mine").mkdir()
            (st.root / "Mine" / "series.json").write_text('{"name": "Mine"}', encoding="utf-8")
            info = st.get("/api/settings")[1]
            self.assertFalse(info["first_run"])
            self.assertEqual(Path(json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))["library"]), config.ART)
            self.assertFalse(info["has_examples"])

    def test_a_library_from_the_environment_is_not_written_as_a_setting(self):
        """STUDIO_ART chooses the library for this run only: it isn't written to the settings file (still no welcome)."""
        with temp_studio() as st:
            (st.root / "Mine").mkdir()
            (st.root / "Mine" / "series.json").write_text('{"name": "Mine"}', encoding="utf-8")
            code, info = st.get("/api/settings")
            self.assertEqual(code, 200)
            self.assertFalse(config.CONFIG_FILE.exists())
            self.assertFalse(info["first_run"])

    def test_settings_load_when_the_settings_file_cannot_be_written(self):
        with temp_studio() as st, mock.patch.dict(os.environ):
            os.environ.pop("STUDIO_ART")
            (st.root / "Mine").mkdir()
            (st.root / "Mine" / "series.json").write_text('{"name": "Mine"}', encoding="utf-8")
            blocker = config.CONFIG_FILE.parent / "afile"
            blocker.write_text("x", encoding="utf-8")
            with mock.patch.object(config, "CONFIG_FILE", blocker / "config.json"):      # its folder can't be made
                code, info = st.get("/api/settings")
            self.assertEqual(code, 200)
            self.assertEqual(info["series"], 1)
            self.assertFalse(info["first_run"])

    def test_settings_are_written_atomically(self):
        with temp_studio():
            with mock.patch("studio.store.write_text", wraps=store.write_text) as w:
                config.save({"signature": "Someone"})
            w.assert_called_once()
            self.assertEqual(w.call_args.args[0], config.CONFIG_FILE)
            self.assertEqual(config.load()["signature"], "Someone")

    def test_examples_endpoints(self):
        with temp_studio() as st:
            st.post("/api/settings", {"signature": "Someone"})
            code, r = st.post("/api/examples", {})
            self.assertEqual(code, 200)
            self.assertTrue(r["added"])
            self.assertTrue(st.get("/api/settings")[1]["has_examples"])
            self.assertEqual(st.post("/api/examples", {})[1]["added"], 0)
            code, r = st.post("/api/examples/remove", {})
            self.assertEqual((code, r["removed"]), (200, 2))
            self.assertFalse(st.get("/api/settings")[1]["has_examples"])


class BadLibraryTest(unittest.TestCase):
    def test_unusable_path_leaves_no_config(self):
        with temp_studio() as st, mock.patch.dict(os.environ):
            os.environ.pop("STUDIO_ART")    # the environment would otherwise override the library
            cfg = config.CONFIG_FILE
            blocker = cfg.parent / "afile"
            blocker.write_text("x", encoding="utf-8")
            code, r = st.post("/api/settings", {"library": str(blocker / "sub"), "create": True})
            self.assertEqual(code, 400)
            self.assertIn("can't create a folder", r["error"])
            self.assertFalse(cfg.exists())
            self.assertTrue(st.get("/api/settings")[1]["first_run"])

    def test_empty_library_is_refused(self):
        with temp_studio() as st:
            for v in ("", "   "):
                self.assertEqual(st.post("/api/settings", {"library": v, "create": True})[0], 400)
            self.assertFalse(config.CONFIG_FILE.exists())
