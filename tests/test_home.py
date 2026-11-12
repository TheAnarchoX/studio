"""Home: what you were last working on, and recent work across the library."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio import home
from studio.books import Books
from studio.store import Store
from tests.support import temp_studio


def make_poem(root, series, folder, title, lines, mtime):
    d = root / series / folder
    d.mkdir(parents=True)
    (root / series / "series.json").write_text("{}", encoding="utf-8")
    os.utime(root / series / "series.json", (mtime - 10, mtime - 10))
    (d / "poem.json").write_text(json.dumps({"title": title, "slug": folder, "lines": lines}), encoding="utf-8")
    os.utime(d / "poem.json", (mtime, mtime))
    return d


def make_design(poem_dir, slug, mtime):
    (poem_dir / "designs").mkdir(exist_ok=True)
    f = poem_dir / "designs" / f"{slug}.json"
    f.write_text(json.dumps({"name": slug.title(), "elements": []}), encoding="utf-8")
    os.utime(f, (mtime, mtime))


class HomeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-home-"))
        self.root = self.tmp / "Poems"
        self.store = Store(self.root, self.tmp / "cache")
        home.use(self.store)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_recent_orders_across_poems_and_designs(self):
        a = make_poem(self.root, "One", "alpha", "Alpha", ["first", "last of alpha"], 1_700_000_000)
        b = make_poem(self.root, "One", "beta", "Beta", ["x"], 1_700_001_000)
        make_design(a, "cover", 1_700_002_000)
        items = home.recent()
        self.assertEqual([(i["kind"], i["title"]) for i in items if i["kind"] != "series"],
                         [("design", "Cover"), ("poem", "Beta"), ("poem", "Alpha")])
        whens = [i["when"] for i in items]
        self.assertEqual(whens, sorted(whens, reverse=True))
        self.assertTrue(items[0]["href"].startswith("#/poem/"))
        self.assertEqual(len(home.recent(limit=2)), 2)

    def test_continue_is_the_newest_writing(self):
        a = make_poem(self.root, "One", "alpha", "Alpha", ["first", "", "last of alpha"], 1_700_000_000)
        make_poem(self.root, "One", "beta", "Beta", ["x"], 1_700_001_000)
        c = home.continue_item()
        self.assertEqual((c["kind"], c["title"], c["excerpt"]), ("poem", "Beta", "x"))
        make_design(a, "cover", 1_700_002_000)
        c = home.continue_item()
        self.assertEqual(c["kind"], "design")
        self.assertEqual(c["excerpt"], "last of alpha")

    def test_home_empty_library(self):
        self.assertEqual(home.recent(), [])
        self.assertIsNone(home.continue_item())

    def test_api_home_empty_library(self):
        with temp_studio() as st:
            shutil.rmtree(st.root)
            code, data = st.get("/api/home")
            self.assertEqual(code, 200)
            self.assertEqual((data["recent"], data["continue"]), ([], None))

    def test_api_home_keeps_its_keys(self):
        with temp_studio() as st:
            make_poem(st.root, "One", "alpha", "Alpha", ["a"], 1_700_000_000)
            code, data = st.get("/api/home")
            self.assertEqual(code, 200)
            for k in ("series", "poems", "statuses", "signature", "stamp", "root", "continue", "recent"):
                self.assertIn(k, data)
            self.assertEqual(data["continue"]["title"], "Alpha")

    def test_overview_reads_each_file_once_and_only_shown_designs(self):
        a = make_poem(self.root, "One", "alpha", "Alpha", ["a"], 1_700_000_000)
        make_poem(self.root, "One", "beta", "Beta", ["b"], 1_700_001_000)
        for n in range(4):
            make_design(a, f"d{n}", 1_700_002_000 + n)
        reads = []
        real = Path.read_text

        def spy(self, *args, **kw):
            reads.append(self.name if self.name == "poem.json" else self.parent.name + "/" + self.name)
            return real(self, *args, **kw)

        with mock.patch.object(Path, "read_text", spy):
            out = home.overview(limit=2)
        self.assertEqual(reads.count("poem.json"), 2)                        # each poem once
        self.assertEqual(sorted(r for r in reads if r != "poem.json"), ["designs/d2.json", "designs/d3.json"])
        self.assertEqual([i["title"] for i in out["recent"]], ["D3", "D2"])
        self.assertEqual(out["continue"]["title"], "D3")
        self.assertFalse(any(k.startswith("_") for i in out["recent"] for k in i))
        self.assertEqual(len(home.recent(limit=None)), 7)

    def test_api_home_walks_the_library_once_for_home(self):
        with temp_studio() as st:
            make_poem(st.root, "One", "alpha", "Alpha", ["a"], 1_700_000_000)
            with mock.patch.object(home, "_items", wraps=home._items) as m:
                self.assertEqual(st.get("/api/home")[0], 200)
            self.assertEqual(m.call_count, 1)

    def test_designs_that_are_not_objects_keep_their_stem(self):
        a = make_poem(self.root, "One", "alpha", "Alpha", ["a"], 1_700_000_000)
        (a / "designs").mkdir()
        for stem, text in (("arr", "[]"), ("nul", "null"), ("str", '"x"')):
            f = a / "designs" / f"{stem}.json"
            f.write_text(text, encoding="utf-8")
            os.utime(f, (1_700_002_000, 1_700_002_000))
        titles = {i["title"] for i in home.recent() if i["kind"] == "design"}
        self.assertEqual(titles, {"arr", "nul", "str"})
        self.assertIsNotNone(home.continue_item())
        with temp_studio() as st:
            p = make_poem(st.root, "One", "alpha", "Alpha", ["a"], 1_700_000_000)
            (p / "designs").mkdir()
            (p / "designs" / "arr.json").write_text("[]", encoding="utf-8")
            code, data = st.get("/api/home")
            self.assertEqual(code, 200)
            self.assertIn("arr", [i["title"] for i in data["recent"]])

    def test_continue_beyond_the_shown_limit_is_still_named(self):
        a = make_poem(self.root, "One", "alpha", "Alpha", ["a"], 1_700_000_000)
        make_design(a, "cover", 1_700_000_500)
        (self.root / "Two").mkdir()
        (self.root / "Two" / "series.json").write_text("{}", encoding="utf-8")   # newer non-writing items fill the limit
        for n in range(3):
            d = self.root / f"S{n}"
            d.mkdir()
            f = d / "series.json"
            f.write_text("{}", encoding="utf-8")
            os.utime(f, (1_700_009_000 + n, 1_700_009_000 + n))
        os.utime(self.root / "Two" / "series.json", (1_700_009_100, 1_700_009_100))
        out = home.overview(limit=2)
        self.assertEqual([i["kind"] for i in out["recent"]], ["series", "series"])
        self.assertEqual((out["continue"]["kind"], out["continue"]["title"]), ("design", "Cover"))

    def test_continue_includes_book_pieces(self):
        make_poem(self.root, "One", "alpha", "Alpha", ["a"], 1_700_000_000)
        book = Books(self.tmp / "Books").create("The Quiet Year", kind="fiction")
        d = Path(book["path"])
        os.utime(d / "book.json", (1_700_000_500, 1_700_000_500))
        piece = d / "manuscript" / "chapter-1.md"
        piece.write_text("# Chapter 1\n\nThe snow came early that year.\n\nNobody minded the quiet.\n", encoding="utf-8")
        os.utime(piece, (1_700_001_000, 1_700_001_000))
        c = home.continue_item()
        self.assertEqual((c["kind"], c["title"], c["where"]), ("piece", "Chapter 1", "The Quiet Year"))
        self.assertEqual(c["label"], "Chapter")                     # what Home calls it: the piece's own kind
        self.assertEqual(c["href"], "#/book/The%20Quiet%20Year/write/chapter-1.md")
        self.assertEqual(c["excerpt"], "Nobody minded the quiet.")
        kinds = [(i["kind"], i["title"]) for i in home.recent()]
        self.assertEqual(kinds[:3], [("piece", "Chapter 1"), ("book", "The Quiet Year"), ("poem", "Alpha")])
        self.assertEqual(home.recent()[1]["href"], "#/book/The%20Quiet%20Year")
        self.assertFalse(any(k.startswith("_") for i in home.recent() for k in i))

    def test_book_pieces_without_a_title_show_their_kind(self):
        book = Books(self.tmp / "Books").create("Small Hours", kind="memoir")
        dedication = Path(book["path"]) / "manuscript" / "dedication.md"
        dedication.write_text("For the neighbours.\n", encoding="utf-8")
        os.utime(dedication, (1_800_000_000, 1_800_000_000))
        c = home.continue_item()
        self.assertEqual((c["kind"], c["title"], c["excerpt"], c["label"]), ("piece", "Dedication", "For the neighbours.", "Dedication"))
        self.assertEqual({i.get("label") for i in home.recent() if i["kind"] == "piece"}, {"Dedication", "Chapter"})
        (Path(book["path"]) / "book.json").write_text("not json", encoding="utf-8")       # a broken book is left out
        self.assertEqual([i for i in home.recent() if i["kind"] in ("book", "piece")], [])

    def test_a_file_name_outside_manuscript_is_never_read(self):
        book = Books(self.tmp / "Books").create("Small Hours", kind="fiction")
        outside = self.tmp / "Books" / "x.md"
        outside.write_text("# Outside\n\nWords from elsewhere.\n", encoding="utf-8")
        os.utime(outside, (1_900_000_000, 1_900_000_000))
        path = Path(book["path"]) / "book.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta["contents"].append({"file": "../../x.md", "kind": "chapter"})
        path.write_text(json.dumps(meta), encoding="utf-8")
        self.assertNotIn("Outside", [i["title"] for i in home.recent()])
        self.assertNotEqual(home.continue_item().get("title"), "Outside")

    def test_a_poem_piece_continues_from_its_last_line_and_long_prose_from_a_word(self):
        poems = Books(self.tmp / "Books").create("Low Tide", kind="poetry")
        p = Path(poems["path"]) / "manuscript" / "untitled.md"
        p.write_text("# Low Tide\n\nThe water goes out\nand takes the light with it.\n", encoding="utf-8")
        os.utime(p, (1_800_000_000, 1_800_000_000))
        self.assertEqual(home.continue_item()["excerpt"], "and takes the light with it.")
        prose = Books(self.tmp / "Books").create("Long Days", kind="fiction")
        q = Path(prose["path"]) / "manuscript" / "chapter-1.md"
        q.write_text("# Chapter 1\n\n" + " ".join(f"word{n}" for n in range(60)) + "\n", encoding="utf-8")
        os.utime(q, (1_800_000_100, 1_800_000_100))
        tail = home.continue_item()["excerpt"]
        self.assertTrue(tail.startswith("…word") and tail.endswith("word59") and len(tail) <= home.EXCERPT + 1, tail)


if __name__ == "__main__":
    unittest.main()
