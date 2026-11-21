"""The writing log: words counted per day for poems and books."""
import json
import shutil
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from studio import writing_log
from studio.store import Store
from tests.support import temp_studio


class WritingLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-log-"))
        self.poem = self.tmp / "poem"
        self.poem.mkdir()
        self.root = self.tmp / "Poems"
        self.store = Store(self.root, self.tmp / "cache")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_words(self):
        self.assertEqual(writing_log.words("Two words"), 2)
        self.assertEqual(writing_log.words("— … !"), 0)
        self.assertEqual(writing_log.words("l'eau 12 ok\nnext"), 4)

    def test_add_accumulates_and_ignores_non_gains(self):
        t = datetime(2026, 11, 13, 9, 0)
        writing_log.add(self.poem, 5, t)
        writing_log.add(self.poem, 7, t)
        writing_log.add(self.poem, 0, t)
        writing_log.add(self.poem, -3, t)
        self.assertEqual(writing_log.read_days(self.poem), {"2026-11-13": 12})

    def test_read_days_drops_bad_entries(self):
        f = self.poem / ".studio" / "days.json"
        f.parent.mkdir()
        f.write_text(json.dumps({"2026-11-10": 4, "bad": 3, "2026-11-11": -4, "2026-11-12": True, "2026-11-09": 1.5}),
                     encoding="utf-8")
        self.assertEqual(writing_log.read_days(self.poem), {"2026-11-10": 4})
        self.assertEqual(writing_log.read_days(self.tmp / "nowhere"), {})

    def test_add_never_overwrites_an_unreadable_log(self):
        f = self.poem / ".studio" / "days.json"
        f.parent.mkdir()
        f.write_text("{bad", encoding="utf-8")
        writing_log.add(self.poem, 5)
        self.assertEqual(f.read_text(encoding="utf-8"), "{bad")

    def test_save_text_records_the_words_a_save_adds(self):
        self.store.create_series("Sea")
        pid = self.store.create("Harbour", "Sea")["id"]
        folder = self.store.resolve(pid)
        self.store.save_text(pid, "Harbour", "one two three")
        self.store.save_text(pid, "Harbour", "one two")
        self.store.save_text(pid, "A longer title", "one two three four five")
        self.assertEqual(sum(writing_log.read_days(folder).values()), 6)

    def test_gather(self):
        self.store.create_series("Sea")
        pid = self.store.create("Harbour", "Sea")["id"]
        folder = self.store.resolve(pid)
        (folder / ".studio").mkdir()
        (folder / ".studio" / "days.json").write_text(json.dumps({"2026-11-12": 40}), encoding="utf-8")
        books = self.tmp / "Books"
        a = books / "Field Notes"
        (a / ".studio").mkdir(parents=True)
        (a / "book.json").write_text(json.dumps({"title": "Field Notes", "goals": {"daily": 500}}), encoding="utf-8")
        (a / ".studio" / "days.json").write_text(json.dumps(
            {"2026-11-10": 600, "2026-11-13": 120, "bad": 3, "2026-11-11": -4}), encoding="utf-8")
        b = books / "Second"
        b.mkdir()
        (b / "book.json").write_text(json.dumps({"title": "Second"}), encoding="utf-8")
        g = writing_log.gather(self.store, books, today=date(2026, 11, 13))
        self.assertEqual(g["today"], "2026-11-13")
        self.assertEqual(g["week_start"], "2026-11-09")
        self.assertEqual(g["days"]["2026-11-10"], {"poems": {}, "books": {"Field Notes": 600}})
        self.assertEqual(g["days"]["2026-11-12"]["poems"], {"Sea/Harbour": 40})
        self.assertNotIn("2026-11-11", g["days"])
        self.assertEqual([x["goal"] for x in g["books"]], [500, 0])
        self.assertEqual(g["books"][0]["first_day"], "2026-11-10")
        self.assertIsNone(g["books"][1]["first_day"])
        self.assertEqual(g["poems"]["Sea/Harbour"], {"title": "Harbour", "series": "Sea"})

    def test_the_examples_are_not_writing(self):
        """Adding the examples saves their poems and the example book's pieces as any save does, which records words;
        those aren't the author's writing, so the log leaves out what is marked as an example."""
        from studio import examples
        self.root.mkdir()
        self.assertTrue(examples.add(self.store, self.store.styles, signature=""))
        logged = [d for d in [*self.store.poem_dirs(), *(self.tmp / "Books").iterdir()] if writing_log.read_days(d)]
        self.assertTrue(logged)                     # the examples did record words: the test means something
        g = writing_log.gather(self.store, self.tmp / "Books")
        self.assertEqual((g["days"], g["poems"], g["books"]), ({}, {}, []))
        self.store.create_series("Sea")             # the author's own writing still counts
        pid = self.store.create("Harbour", "Sea")["id"]
        self.store.save_text(pid, "Harbour", "salt on the rope")
        g = writing_log.gather(self.store, self.tmp / "Books")
        self.assertEqual(list(g["poems"]), ["Sea/Harbour"])
        self.assertEqual(list(g["days"].values()), [{"poems": {"Sea/Harbour": 4}, "books": {}}])

    def test_endpoint(self):
        with temp_studio() as t:
            code, body = t.get("/api/writing")
            self.assertEqual(code, 200)
            self.assertEqual(set(body), {"today", "week_start", "days", "books", "poems"})


if __name__ == "__main__":
    unittest.main()
