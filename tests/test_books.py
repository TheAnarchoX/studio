"""Books store tests. Run: python -m unittest discover tests"""
import json
import os
import random
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from studio import books as books_module, manuscript
from studio.books import AUTO, KINDS, PIECE_KINDS, Books, BooksError


def paragraph(*nodes):
    return {"type": "paragraph", "content": list(nodes)}


def text(s, *marks):
    return {"type": "text", "text": s, **({"marks": [{"type": m} for m in marks]} if marks else {})}


def doc(*blocks):
    return {"type": "doc", "attrs": {"form": "prose"}, "content": list(blocks)}


class BooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-books-"))
        self.lib = self.tmp / "lib"
        self.b = Books(self.lib / "Books")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def book(self, kind="memoir", title="The Long Road"):
        return self.b.create(title, "A. Writer", "en", kind)

    def write_md(self, book, file, md):
        (self.lib / "Books" / book / "manuscript" / file).write_text(md, encoding="utf-8", newline="\n")

    # ——— creating ———
    def test_file_serves_only_images_of_real_books(self):
        self.book()
        self.b.save_image("The Long Road", "a.png", b"\x89PNG")
        self.assertTrue(self.b.file("The Long Road/images/a.png").is_file())        # the path after /bookfiles/
        (self.lib / "Books" / "stray" / "images").mkdir(parents=True)
        (self.lib / "Books" / "stray" / "images" / "a.png").write_bytes(b"x")       # a folder with no book.json
        for rel in ("stray/images/a.png", "The Long Road/book.json", "The Long Road/images/missing.png",
                    "Books/The Long Road/images/a.png", "../Books/The Long Road/images/a.png"):
            with self.assertRaises(BooksError) as cm:
                self.b.file(rel)
            self.assertEqual(cm.exception.code, 404)

    def test_create_each_kind(self):
        for kind, spec in KINDS.items():
            with self.subTest(kind=kind):
                r = self.b.create(f"Book {kind}", "A. Writer", "nl", kind)
                self.assertEqual(r["features"], spec["features"])
                titles = [e["title"] for e in r["contents"] if e.get("file")]
                self.assertEqual([e["auto"] for e in r["contents"][:3]], ["half-title", "title-page", "copyright"])
                self.assertEqual([e["auto"] for e in r["contents"] if e.get("auto")][3:],
                                 [i["auto"] for i in spec["contents"] if "auto" in i] + spec["back"])
                self.assertEqual([e["kind"] for e in r["contents"] if e.get("file")],
                                 [i["kind"] for i in spec["contents"] if "kind" in i])
                self.assertEqual(titles, [i.get("title", "") for i in spec["contents"] if "kind" in i])
                self.assertEqual(r["version"], 1)
                self.assertEqual(r["language"], "nl")
                self.assertEqual(r["goals"], {"daily": 0})
                self.assertTrue(all(a in AUTO for a in (e["auto"] for e in r["contents"] if e.get("auto"))))
                self.assertTrue(r["style"]["look"])
        poetry = self.b.read("Book poetry")
        self.assertEqual(poetry["features"]["index"], "first-lines")
        self.assertEqual([(e["kind"], e["form"]) for e in poetry["contents"] if e.get("file")], [("chapter", "poem")])
        self.assertIn("chapter", PIECE_KINDS)

    def test_create_without_starting_pieces_and_with_a_look(self):
        r = self.b.create("Bare", kind="nonfiction", start=False)
        self.assertEqual([e.get("auto") for e in r["contents"]],
                         ["half-title", "title-page", "copyright", "notes", "bibliography", "index"])
        self.assertEqual(list((self.lib / "Books" / "Bare" / "manuscript").iterdir()), [])
        self.assertNotIn("look", json.loads((self.lib / "Books" / "Bare" / "book.json").read_text(encoding="utf-8")))
        with self.assertRaises(BooksError):
            self.b.create("Bare")                       # exists
        with self.assertRaises(BooksError):
            self.b.create("  ")
        with self.assertRaises(BooksError) as e:
            self.b.create("Looks", look="No such look")
        self.assertEqual(e.exception.code, 400)
        self.assertEqual(self.b.list()[0]["id"], "Bare")

    def test_list_counts_pieces_words_and_statuses(self):
        self.book()
        self.write_md("The Long Road", "chapter-1.md", "# Chapter 1\n\nOne two three.\n")
        [item] = self.b.list()
        self.assertEqual((item["id"], item["title"], item["author"], item["kind"], item["pieces"], item["words"]),
                         ("The Long Road", "The Long Road", "A. Writer", "memoir", 2, 3))     # titles are not counted
        self.assertEqual(item["by_status"], {"idea": 1})
        self.assertTrue(item["updated"] > 0 and item["style"]["look"])

    def test_unknown_book_and_piece_are_404(self):
        self.book()
        for call in (lambda: self.b.read("Nope"), lambda: self.b.read("../x"),
                     lambda: self.b.piece("The Long Road", "ghost.md"),
                     lambda: self.b.piece("The Long Road", "../book.json")):
            with self.assertRaises(BooksError) as e:
                call()
            self.assertEqual(e.exception.code, 404)

    # ——— the book's details ———
    def test_reorder_and_unknown_keys_kept(self):
        self.book()
        path = self.lib / "Books" / "The Long Road" / "book.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["publisherNotes"] = {"keep": True}
        data["contents"][3]["custom"] = "x"
        path.write_text(json.dumps(data), encoding="utf-8")
        a = self.b.new_piece("The Long Road", "epilogue", title="Afterwards")
        order = [e for e in self.b.read("The Long Road")["contents"]]
        order = [next(e for e in order if e.get("file") == a["file"]), *[e for e in order if e.get("file") != a["file"]]]
        r = self.b.update("The Long Road", {"contents": order, "title": "The Longer Road", "author": "B. Writer",
                                            "details": {"isbn": "123", "year": "2027"},
                                            "features": {"notes": "both"}, "goals": {"daily": 300}})
        self.assertEqual(r["title"], "The Longer Road")
        self.assertEqual(r["details"]["year"], 2027)
        self.assertEqual(r["features"]["notes"], "both")
        self.assertEqual(r["goals"]["daily"], 300)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["publisherNotes"], {"keep": True})
        self.assertEqual(saved["contents"][0]["file"], a["file"])
        self.assertTrue(any(e.get("custom") == "x" for e in saved["contents"]))
        self.assertNotIn("words", saved["contents"][0])               # computed values are not stored
        self.assertTrue((self.lib / "Books" / "The Long Road").exists())    # the folder keeps its name
        r = self.b.update("The Long Road", {"kind": "poetry", "apply_kind_defaults": True})
        self.assertEqual(r["features"], KINDS["poetry"]["features"])
        r = self.b.update("The Long Road", {"kind": "fiction"})
        self.assertEqual(r["features"], KINDS["poetry"]["features"])  # a kind change alone keeps the features
        with self.assertRaises(BooksError):
            self.b.update("The Long Road", {"contents": [{"file": "ghost.md", "kind": "chapter"}]})
        with self.assertRaises(BooksError):
            self.b.update("The Long Road", {"features": {"notes": "sideways"}})
        with self.assertRaises(BooksError):
            self.b.update("The Long Road", {"kind": "cookbook"})

    def test_look_palette_and_fonts_follow_the_series_rules(self):
        self.book()
        r = self.b.update("The Long Road", {"palette": [{"name": "Ink", "hex": "#101010", "role": "background"},
                                                       {"name": "Paper", "hex": "#F0F0F0", "role": "text"}]})
        self.assertEqual(r["style"]["palette"]["from"], "book")
        self.assertFalse(r["style"]["palette"]["linked"])
        r = self.b.update("The Long Road", {"palette": None})
        self.assertNotEqual(r["style"]["palette"]["from"], "book")
        with self.assertRaises(BooksError):
            self.b.update("The Long Road", {"palette": [{"name": "x", "hex": "red"}]})

    # ——— pieces ———
    def test_new_piece_names(self):
        self.book(kind="fiction")
        names = [self.b.new_piece("The Long Road", "chapter", title=t)["file"]
                 for t in ("Één week", "Één week", "Con", "Con", "", "")]
        self.assertEqual(names, ["een-week.md", "een-week-2.md", "con-1.md", "con-2.md", "chapter.md", "chapter-2.md"])
        self.assertEqual(self.b.new_piece("The Long Road", "dedication")["file"], "dedication.md")
        self.assertEqual(self.b.new_piece("The Long Road", "chapter", title="Lpt3")["file"], "lpt3-1.md")
        self.assertEqual(self.b.new_piece("The Long Road", "chapter", title="Vrouw 's avonds")["file"], "vrouw-s-avonds.md")
        with self.assertRaises(BooksError):
            self.b.new_piece("The Long Road", "saga")

    def test_new_piece_goes_after_the_given_piece_or_before_the_back_pages(self):
        self.book()
        first = self.b.new_piece("The Long Road", "epigraph", title="")
        second = self.b.new_piece("The Long Road", "chapter", title="Two", after="chapter-1.md")
        files = [e.get("file") or e.get("auto") for e in self.b.read("The Long Road")["contents"]]
        self.assertEqual(files[-1], "notes")
        self.assertEqual(files[files.index("chapter-1.md") + 1], second["file"])
        self.assertEqual(files[-2], first["file"])
        with self.assertRaises(BooksError) as e:
            self.b.new_piece("The Long Road", "chapter", after="ghost.md")
        self.assertEqual(e.exception.code, 404)

    def test_save_and_reload_piece(self):
        self.book()
        p = self.b.piece("The Long Road", "chapter-1.md")
        self.assertEqual((p["title"], p["kind"], p["form"], p["status"], p["words"]), ("Chapter 1", "chapter", "prose", "idea", 0))
        d = doc({"type": "title", "content": [text("Chapter 1")]},
                paragraph(text("It was "), text("quiet", "em"), text(".")),
                paragraph(text("Een"), {"type": "note", "content": [text("zie noot")]}, text(" week.")))
        saved = self.b.save_piece("The Long Road", "chapter-1.md", doc=d)
        self.assertEqual(saved["md"], "# Chapter 1\n\nIt was *quiet*.\n\nEen^[zie noot] week.\n")
        self.assertEqual((saved["words"], saved["notes"], saved["note_words"]), (5, 1, 2))
        self.assertEqual(saved["snapshot"], self.b.history("The Long Road", "chapter-1.md")[0]["when"])
        quiet = self.b.save_piece("The Long Road", "chapter-1.md", doc=d)       # unchanged: no new snapshot
        self.assertIsNone(quiet["snapshot"])
        again = self.b.piece("The Long Road", "chapter-1.md")
        self.assertEqual(again["doc"], saved["doc"])
        self.assertEqual(manuscript.serialize(again["doc"], "prose"), saved["md"])
        r = self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\r\n\r\n_Plain_ text\r\n")
        self.assertEqual(r["md"], "# Chapter 1\n\n*Plain* text\n")
        with self.assertRaises(BooksError) as e:
            self.b.save_piece("The Long Road", "chapter-1.md", doc=doc({"type": "bogus"}))
        self.assertEqual(e.exception.code, 400)
        with self.assertRaises(BooksError):
            self.b.save_piece("The Long Road", "chapter-1.md")
        c = self.b.read("The Long Road")
        entry = next(e for e in c["contents"] if e.get("file") == "chapter-1.md")
        self.assertEqual((entry["title"], entry["words"], entry["notes"]), ("Chapter 1", 2, 0))

    def test_read_gives_counts_and_mtime_per_entry(self):
        self.book()
        self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nOne^[two three] four.\n")
        e = next(e for e in self.b.read("The Long Road")["contents"] if e.get("file") == "chapter-1.md")
        self.assertEqual((e["words"], e["note_words"], e["notes"]), (2, 2, 1))
        self.assertGreater(e["mtime"], 0)

    def test_stale_save_raises_409_and_force_saves(self):
        self.book()
        mine = self.b.piece("The Long Road", "chapter-1.md")
        path = self.lib / "Books" / "The Long Road" / "manuscript" / "chapter-1.md"
        path.write_text("# Chapter 1\n\nOther window.\n", encoding="utf-8")
        later = mine["mtime"] + 5
        os.utime(path, (later, later))
        with self.assertRaises(BooksError) as e:
            self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nMine.\n", base_mtime=mine["mtime"])
        self.assertEqual(e.exception.code, 409)
        self.assertIn("Other window", e.exception.details["current"]["md"])
        self.assertIn("Other window", path.read_text(encoding="utf-8"))
        r = self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nMine.\n", base_mtime=mine["mtime"], force=True)
        self.assertIn("Mine", r["md"])
        self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nAgain.\n", base_mtime=r["mtime"])

    # ——— snapshots ———
    def snaps(self, file="chapter-1"):
        folder = self.lib / "Books" / "The Long Road" / "drafts" / file
        return sorted(p.stem for p in folder.glob("*.md")) if folder.exists() else []

    def test_snapshots_on_leaving_and_every_30_minutes(self):
        self.book()
        t = datetime(2026, 11, 12, 9, 0)
        save = lambda s, **kw: self.b.save_piece("The Long Road", "chapter-1.md", md=f"# Chapter 1\n\n{s}\n", **kw)
        save("one", now=t)                                              # no snapshot yet: the first save makes one
        self.assertEqual(self.snaps(), ["2026-11-12T0900"])
        save("two", now=t + timedelta(minutes=10))                      # too soon, not leaving
        save("three", now=t + timedelta(minutes=29))
        self.assertEqual(self.snaps(), ["2026-11-12T0900"])
        save("four", now=t + timedelta(minutes=30))                     # 30 minutes since the newest
        self.assertEqual(self.snaps(), ["2026-11-12T0900", "2026-11-12T0930"])
        save("five", now=t + timedelta(minutes=35), leaving=True)       # leaving
        self.assertEqual(self.snaps()[-1], "2026-11-12T0935")
        shot = self.b.snapshot_text("The Long Road", "chapter-1.md", "2026-11-12T0935")
        self.assertEqual(shot, "# Chapter 1\n\nfive\n")                  # the text as saved at that moment
        hist = self.b.history("The Long Road", "chapter-1.md")
        self.assertEqual([h["when"] for h in hist], ["2026-11-12T0935", "2026-11-12T0930", "2026-11-12T0900"])
        self.assertEqual(hist[0]["words"], 1)

    def test_no_snapshot_for_identical_text(self):
        self.book()
        t = datetime(2026, 11, 12, 9, 0)
        save = lambda s, **kw: self.b.save_piece("The Long Road", "chapter-1.md", md=f"# Chapter 1\n\n{s}\n", **kw)
        save("same", now=t, leaving=True)
        save("same", now=t + timedelta(hours=2), leaving=True)
        save("same", now=t + timedelta(hours=3))
        self.assertEqual(self.snaps(), ["2026-11-12T0900"])

    def test_restore_snapshots_current_first(self):
        self.book()
        t = datetime(2026, 11, 12, 9, 0)
        self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nold text\n", now=t)
        self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nnewer text\n", now=t + timedelta(minutes=5))
        before = len(self.snaps())
        r = self.b.restore("The Long Road", "chapter-1.md", "2026-11-12T0900")
        self.assertIn("old text", r["md"])
        self.assertEqual(len(self.snaps()), before + 1)
        texts = [(self.lib / "Books" / "The Long Road" / "drafts" / "chapter-1" / f"{s}.md").read_text(encoding="utf-8") for s in self.snaps()]
        self.assertIn("# Chapter 1\n\nnewer text\n", texts)             # the text that was replaced is kept
        with self.assertRaises(BooksError) as e:
            self.b.restore("The Long Road", "chapter-1.md", "1999-01-01T0000")
        self.assertEqual(e.exception.code, 404)
        with self.assertRaises(BooksError):
            self.b.snapshot_text("The Long Road", "chapter-1.md", "../../book")

    # ——— deleting ———
    def test_delete_piece_goes_to_trash_and_leaves_contents(self):
        self.book()
        path = self.b.delete_piece("The Long Road", "chapter-1.md")
        self.assertEqual(path.parent.name, ".trash")
        self.assertEqual(path.read_text(encoding="utf-8"), "# Chapter 1\n")
        self.assertFalse(any(e.get("file") == "chapter-1.md" for e in self.b.read("The Long Road")["contents"]))
        self.assertFalse((self.lib / "Books" / "The Long Road" / "manuscript" / "chapter-1.md").exists())
        with self.assertRaises(BooksError):
            self.b.delete_piece("The Long Road", "chapter-1.md")
        gone = self.b.delete_book("The Long Road")
        self.assertTrue((gone / "book.json").exists())
        self.assertEqual(self.b.list(), [])

    # ——— editions ———
    def test_editions_are_listed_newest_first(self):
        self.book()
        self.assertEqual(self.b.editions("The Long Road"), [])
        self.b.edition("The Long Road", "Proof one", now=datetime(2026, 11, 12, 10, 0))
        self.b.edition("The Long Road", "Final", now=datetime(2026, 12, 1, 10, 0))
        self.b.edition("The Long Road", "Early", now=datetime(2026, 3, 4, 10, 0))
        root = self.lib / "Books" / "The Long Road" / "editions"
        (root / "stray.txt").write_text("x", encoding="utf-8")          # not an edition
        (root / "no date here").mkdir()
        got = self.b.editions("The Long Road")
        self.assertEqual([(e["name"], e["date"]) for e in got],
                         [("Final", "2026-12-01"), ("Proof one", "2026-11-12"), ("Early", "2026-03-04")])
        self.assertEqual(got[0]["path"], str(root / "2026-12-01 Final"))
        with self.assertRaises(BooksError):
            self.b.editions("Nope")

    def test_editions_of_one_day_are_newest_first_by_folder_time(self):
        self.book()
        for i, name in enumerate(("Zeta", "Alpha", "Mid")):
            self.b.edition("The Long Road", name, now=datetime(2026, 11, 12, 10, 0))
            p = self.lib / "Books" / "The Long Road" / "editions" / f"2026-11-12 {name}"
            os.utime(p, (1_800_000_000 + i * 60, 1_800_000_000 + i * 60))
        self.assertEqual([e["name"] for e in self.b.editions("The Long Road")], ["Mid", "Alpha", "Zeta"])

    def test_editions_skip_links_out_of_the_folder(self):
        self.book()
        self.b.edition("The Long Road", "Real", now=datetime(2026, 11, 12))
        root = self.lib / "Books" / "The Long Road" / "editions"
        outside = self.lib / "Outside"
        outside.mkdir()
        link = root / "2026-11-13 Linked"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                self.skipTest("no symlinks here")
            import subprocess
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
        self.assertTrue(link.exists())
        self.assertEqual([e["name"] for e in self.b.editions("The Long Road")], ["Real"])

    def test_edition_copies_the_book(self):
        self.book()
        root = self.lib / "Books" / "The Long Road"
        (root / "cover").mkdir()
        (root / "cover" / "front.txt").write_text("cover", encoding="utf-8")
        self.b.save_sources("The Long Road", [{"id": "smith2020", "type": "book", "title": "A Book"}])
        self.b.save_image("The Long Road", "pic.png", b"\x89PNGdata")
        self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nText.\n", now=datetime(2026, 11, 12, 9, 0))
        ed = self.b.edition("The Long Road", "Proof one", now=datetime(2026, 11, 12, 10, 0))
        self.assertEqual(ed, root / "editions" / "2026-11-12 Proof one")
        for item in ("book.json", "manuscript/chapter-1.md", "images/pic.png", "sources.json", "cover/front.txt"):
            self.assertTrue((ed / item).exists(), item)
        self.assertFalse((ed / "drafts").exists() or (ed / ".studio").exists())
        with self.assertRaises(BooksError):
            self.b.edition("The Long Road", "Proof one", now=datetime(2026, 11, 12, 11, 0))
        ed2 = self.b.edition("The Long Road", "Proof two", now=datetime(2026, 11, 12, 11, 0))      # editions don't nest
        self.assertFalse((ed2 / "editions").exists())

    # ——— search and replace ———
    def test_search_and_replace(self):
        self.book(kind="essays")
        self.write_md("The Long Road", "essay-1.md",
                      "# Essay 1\n\nThe cat and the Cat sat. Concatenate *the cat* too.\n\nA line^[the cat in a note].\n\n"
                      "![the cat photo](../images/a.png)\n")
        hits = self.b.search("The Long Road", "cat")
        self.assertEqual(len(hits), 6)
        self.assertEqual([h["in"] for h in hits], ["text"] * 4 + ["note", "caption"])
        self.assertEqual(self.b.search("The Long Road", "cat", whole=True, case=True)[0]["before"], "The ")
        whole = self.b.search("The Long Road", "cat", whole=True)
        self.assertEqual([h["match"] for h in whole], ["cat", "Cat", "cat", "cat", "cat"])
        self.assertEqual(len(self.b.search("The Long Road", "Cat", case=True)), 1)
        h = self.b.search("The Long Road", "Cat", case=True)[0]
        self.assertEqual((h["file"], h["title"], h["index"], h["match"]), ("essay-1.md", "Essay 1", 0, "Cat"))
        self.assertEqual(h["after"], " sat. Concatenate the cat too.")
        self.assertEqual(self.b.search("The Long Road", ""), [])
        # one match, by its index
        self.assertEqual(self.b.replace("The Long Road", "Cat", "dog", whole=True, case=True, file="essay-1.md", index=0), {"replaced": 1})
        md = (self.lib / "Books" / "The Long Road" / "manuscript" / "essay-1.md").read_text(encoding="utf-8")
        self.assertIn("The cat and the dog sat.", md)
        # all whole-word, any case: italics, the note and the caption keep their place
        r = self.b.replace("The Long Road", "cat", "fox", whole=True)
        self.assertEqual(r, {"replaced": 4})
        md = (self.lib / "Books" / "The Long Road" / "manuscript" / "essay-1.md").read_text(encoding="utf-8")
        self.assertIn("Concatenate *the fox* too.", md)
        self.assertIn("^[the fox in a note]", md)
        self.assertIn("![the fox photo]", md)
        self.assertIn("Concatenate", md)
        # a match across a mark boundary keeps the marks of the text it started in
        self.write_md("The Long Road", "essay-1.md", "# Essay 1\n\nThe ho*use* is old.\n")
        self.b.replace("The Long Road", "house", "home")
        md = (self.lib / "Books" / "The Long Road" / "manuscript" / "essay-1.md").read_text(encoding="utf-8")
        self.assertEqual(md, "# Essay 1\n\nThe home is old.\n")
        self.assertTrue(self.snaps("essay-1"))                           # a replace can be undone
        with self.assertRaises(BooksError):
            self.b.replace("The Long Road", "", "x")
        with self.assertRaises(BooksError):
            self.b.replace("The Long Road", "a", "b", index=0)

    def test_replace_within_italics_keeps_the_italics(self):
        self.book()
        self.write_md("The Long Road", "chapter-1.md", "# Chapter 1\n\nA *quiet street* here.\n")
        self.b.replace("The Long Road", "quiet", "silent")
        self.assertIn("*silent street*", (self.lib / "Books" / "The Long Road" / "manuscript" / "chapter-1.md").read_text(encoding="utf-8"))

    # ——— words written ———
    def test_words_today(self):
        self.book()
        t = datetime.now()
        save = lambda s: self.b.save_piece("The Long Road", "chapter-1.md", md=f"# Chapter 1\n\n{s}\n", now=t)
        save("one two three")
        save("one two")                                                 # fewer words: nothing is taken away
        save("one two three four five six")
        days = self.b.read("The Long Road")["days"]
        self.assertEqual(days, {t.date().isoformat(): 3 + 4})
        old = (t - timedelta(days=45)).date().isoformat()
        f = self.lib / "Books" / "The Long Road" / ".studio" / "days.json"
        f.write_text(json.dumps({**json.loads(f.read_text()), old: 99}), encoding="utf-8")
        self.assertNotIn(old, self.b.read("The Long Road")["days"])

    # ——— sources and images ———
    def test_sources_validation(self):
        self.book()
        self.assertEqual(self.b.sources("The Long Road"), [])
        items = [{"id": "smith2020", "type": "book", "title": "A Book"}, {"id": "doe-2019", "type": "webpage"}]
        self.assertEqual(self.b.save_sources("The Long Road", items), items)
        self.assertEqual(self.b.sources("The Long Road"), items)
        for bad in ([{"type": "book"}], [{"id": "a b", "type": "book"}], [{"id": "a"}], [{"id": "a", "type": "book"}] * 2,
                    ["x"], {"id": "a"}):
            with self.assertRaises(BooksError, msg=str(bad)):
                self.b.save_sources("The Long Road", bad)
        self.assertEqual(self.b.sources("The Long Road"), items)

    def test_save_image_names_are_unique_and_safe(self):
        self.book()
        self.assertEqual(self.b.save_image("The Long Road", "My Photo.JPG", b"x"), "../images/My-Photo.jpg")
        self.assertEqual(self.b.save_image("The Long Road", "My Photo.JPG", b"y"), "../images/My-Photo-2.jpg")
        self.assertEqual(self.b.save_image("The Long Road", "..\\..\\evil.png", b"z"), "../images/evil.png")
        with self.assertRaises(BooksError):
            self.b.save_image("The Long Road", "notes.txt", b"z")
        with self.assertRaises(BooksError):
            self.b.save_image("The Long Road", "a.png", b"")

    # ——— linked poems ———
    def test_linked_poem(self):
        self.book(kind="poetry")
        poem = self.lib / "Poems" / "Quiet" / "Hold the Line"
        poem.mkdir(parents=True)
        (poem / "poem.json").write_text(json.dumps({"title": "Hold the Line", "lines": ["Hold the line", "when they push"]}), encoding="utf-8")
        self.write_md("The Long Road", "untitled.md",
                      '# Untitled\n\n::: {.poem src="Quiet/Hold the Line"}\n:::\n\n::: {.poem src="Quiet/Gone"}\n:::\n\n'
                      '::: {.poem src="../../x"}\n:::\n')
        p = self.b.piece("The Long Road", "untitled.md")
        self.assertEqual(p["linked"]["Quiet/Hold the Line"], {"title": "Hold the Line", "lines": ["Hold the line", "when they push"]})
        self.assertEqual(p["linked"]["Quiet/Gone"], {"missing": True})
        self.assertEqual(p["linked"]["../../x"], {"missing": True})

    # ——— stamp ———
    def test_stamp_moves_when_a_piece_is_saved(self):
        self.assertEqual(self.b.stamp(), 0.0)
        self.book()
        a = self.b.stamp()
        self.assertGreater(a, 0)
        time.sleep(0.05)
        self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nMore.\n")
        self.assertGreater(self.b.stamp(), a)

    def test_kinds_pinned_literally(self):
        self.assertEqual(KINDS["memoir"]["features"], {"notes": "endnotes", "noteNumbering": "chapter", "sources": False,
                                                       "index": False, "figures": False, "contentNote": False})
        self.assertEqual(KINDS["memoir"]["contents"], [{"kind": "dedication"}, {"auto": "toc"},
                                                       {"kind": "chapter", "title": "Chapter 1", "form": "prose"}])
        self.assertEqual(KINDS["memoir"]["back"], ["notes"])
        self.assertEqual(KINDS["poetry"]["features"], {"notes": "off", "noteNumbering": "chapter", "sources": False,
                                                       "index": "first-lines", "figures": False, "contentNote": False})
        self.assertEqual(KINDS["poetry"]["contents"], [{"auto": "toc"}, {"kind": "chapter", "title": "Untitled", "form": "poem"}])
        self.assertEqual(KINDS["poetry"]["back"], ["index"])

    # ——— review round 1 ———
    def test_leaving_snapshots_text_already_on_disk(self):
        self.book()
        t = datetime(2026, 11, 12, 9, 0)
        save = lambda s, **kw: self.b.save_piece("The Long Road", "chapter-1.md", md=f"# Chapter 1\n\n{s}\n", **kw)
        save("one", now=t)
        save("two", now=t + timedelta(minutes=10))                      # autosave: no snapshot
        self.assertEqual(self.snaps(), ["2026-11-12T0900"])
        before = (self.lib / "Books" / "The Long Road" / "manuscript" / "chapter-1.md").stat().st_mtime
        save("two", now=t + timedelta(minutes=11), leaving=True)        # identical to disk, leaving
        self.assertEqual(self.snaps(), ["2026-11-12T0900", "2026-11-12T0911"])
        self.assertEqual((self.lib / "Books" / "The Long Road" / "manuscript" / "chapter-1.md").stat().st_mtime, before)

    def test_same_minute_snapshots_never_overwrite(self):
        self.book()
        t = datetime(2026, 11, 12, 9, 0)
        save = lambda s, **kw: self.b.save_piece("The Long Road", "chapter-1.md", md=f"# Chapter 1\n\n{s}\n", **kw)
        save("one", now=t, leaving=True)
        save("two", now=t + timedelta(seconds=5), leaving=True)
        save("three", now=t + timedelta(seconds=10), leaving=True)
        hist = self.b.history("The Long Road", "chapter-1.md")
        self.assertEqual([h["when"] for h in hist], ["2026-11-12T0900-3", "2026-11-12T0900-2", "2026-11-12T0900"])
        self.assertEqual([self.b.snapshot_text("The Long Road", "chapter-1.md", h["when"]).split()[-1] for h in hist],
                         ["three", "two", "one"])
        r = self.b.restore("The Long Road", "chapter-1.md", "2026-11-12T0900")
        self.assertIn("one", r["md"])
        self.assertEqual(len(self.b.history("The Long Road", "chapter-1.md")), 3)     # current ("three") was already newest

    def test_bad_base_mtime_is_400(self):
        self.book()
        with self.assertRaises(BooksError) as e:
            self.b.save_piece("The Long Road", "chapter-1.md", md="x", base_mtime="soon")
        self.assertEqual(e.exception.code, 400)

    def test_titles_the_shelf_would_hide_are_refused(self):
        for title in ("_draft", ".hidden"):
            with self.assertRaises(BooksError) as e:
                self.b.create(title)
            self.assertEqual(e.exception.code, 400)
        self.assertFalse((self.lib / "Books" / "_draft").exists())

    def test_replace_in_an_unknown_file_is_404(self):
        self.book()
        with self.assertRaises(BooksError) as e:
            self.b.replace("The Long Road", "a", "b", file="nope.md")
        self.assertEqual(e.exception.code, 404)

    def test_file_names_transliterate_nordic_letters(self):
        self.book(kind="fiction")
        names = [self.b.new_piece("The Long Road", "chapter", title=t)["file"]
                 for t in ("Søren", "Straße Æble", "Łódź", "Þing Œuvre Đ")]
        self.assertEqual(names, ["soren.md", "strasse-aeble.md", "lodz.md", "thing-oeuvre-d.md"])

    def test_failed_edition_leaves_nothing(self):
        self.book()
        from unittest import mock
        with mock.patch("studio.books.shutil.copytree", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.b.edition("The Long Road", "Proof", now=datetime(2026, 11, 12))
        self.assertFalse((self.lib / "Books" / "The Long Road" / "editions" / "2026-11-12 Proof").exists())

    def test_stamp_ignores_editions_drafts_and_vanishing_files(self):
        self.book()
        root = self.lib / "Books" / "The Long Road"
        base = self.b.stamp()
        time.sleep(0.05)
        self.b.edition("The Long Road", "Proof")
        (root / "exports").mkdir()
        (root / "exports" / "a.pdf").write_text("x", encoding="utf-8")
        self.assertEqual(self.b.stamp(), base)
        from unittest import mock
        real = os.stat
        def flaky(path, *a, **k):
            if str(path).endswith("chapter-1.md"):
                raise FileNotFoundError(path)
            return real(path, *a, **k)
        with mock.patch("studio.books.os.stat", side_effect=flaky):
            self.assertGreater(self.b.stamp(), 0)

    def test_citation_key_pattern_is_public(self):
        self.assertTrue(manuscript.CITE_KEY.fullmatch("smith2020"))

    def test_images_refuse_svg(self):
        self.book()
        with self.assertRaises(BooksError) as e:
            self.b.save_image("The Long Road", "logo.svg", b"<svg/>")
        self.assertEqual(e.exception.code, 400)

    # ——— Task 6 round 1: the style sheet, a book's style, plain messages, counts, stamp ———
    def test_style_sheet_reads_back_and_keeps_unknown_keys(self):
        self.book()
        r = self.b.read("The Long Road")
        self.assertEqual(r["style_sheet"], {"quotes": "“…”", "numbers": "words to ten", "terms": [], "notes": ""})
        self.assertIn("fonts", r["style"])                              # `style` stays the resolved look
        path = self.lib / "Books" / "The Long Road" / "book.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta["style"]["house"] = "kept"
        path.write_text(json.dumps(meta), encoding="utf-8")
        sheet = {"quotes": "„…”", "numbers": "digits", "notes": "Dialogue in words.",
                 "terms": [{"use": "e-mail", "not": ["email", "E-mail"], "note": "house style"}, "OK", {"use": "grey"}]}
        want = {"quotes": "„…”", "numbers": "digits", "notes": "Dialogue in words.",
                "terms": [{"use": "e-mail", "not": ["email", "E-mail"], "note": "house style"},
                          {"use": "OK", "not": [], "note": ""}, {"use": "grey", "not": [], "note": ""}]}
        self.assertEqual(self.b.update("The Long Road", {"style_sheet": sheet})["style_sheet"], want)
        self.assertEqual(self.b.read("The Long Road")["style_sheet"], want)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["style"]["house"], "kept")
        self.assertEqual(saved["style"]["terms"], want["terms"])
        r = self.b.update("The Long Road", {"style": {"numbers": "words to hundred"}})      # the plan's name for it
        self.assertEqual((r["style_sheet"]["numbers"], r["style_sheet"]["quotes"]), ("words to hundred", "„…”"))
        self.assertIn("fonts", r["style"])
        saved["style"] = {"terms": ["colour", {"use": "grey", "not": "gray, Gray"}, 7]}      # by hand
        path.write_text(json.dumps(saved), encoding="utf-8")
        self.assertEqual(self.b.read("The Long Road")["style_sheet"],
                         {"quotes": "“…”", "numbers": "words to ten", "notes": "",
                          "terms": [{"use": "colour", "not": [], "note": ""}, {"use": "grey", "not": ["gray", "Gray"], "note": ""}]})

    def test_switches_are_on_or_off(self):
        self.book()
        for key, says in (("sources", "Sources are on or off."), ("figures", "Figures are on or off."),
                          ("contentNote", "The content note is on or off.")):
            with self.assertRaises(BooksError) as e:
                self.b.update("The Long Road", {"features": {key: "yes"}})
            self.assertEqual((e.exception.code, str(e.exception)), (400, says))

    def test_terms_are_a_word_its_wrong_forms_and_a_note(self):
        self.book()
        for bad in ("e-mail", [{"use": 3}], [{"use": "x", "not": "y"}], [{"use": "x", "not": [1]}], [{"use": "x", "note": 4}], [7]):
            with self.assertRaises(BooksError) as e:
                self.b.update("The Long Road", {"style_sheet": {"terms": bad}})
            self.assertEqual(str(e.exception), "Each term is a word to use, the forms not to use and a note.", bad)
        with self.assertRaises(BooksError) as e:
            self.b.update("The Long Road", {"style_sheet": {"terms": [{"use": " ", "not": ["email"]}]}})
        self.assertEqual(str(e.exception), "Each term needs the word to use.")
        with self.assertRaises(BooksError):
            self.b.update("The Long Road", {"style_sheet": {"quotes": 3}})

    def test_style_of_a_book(self):
        self.book()
        self.assertEqual(self.b.style("The Long Road"), self.b.read("The Long Road")["style"])
        self.b.update("The Long Road", {"link": "Riso"})
        self.assertEqual(self.b.style("The Long Road")["look"], "Riso")
        with self.assertRaises(BooksError) as e:
            self.b.style("Nope")
        self.assertEqual(e.exception.code, 404)

    def test_not_found_messages_are_plain(self):
        self.book()
        for call, says in ((lambda: self.b.read("Nope"), "There's no book called Nope in Books."),
                           (lambda: self.b.read(""), "Say which book."),
                           (lambda: self.b.piece("The Long Road", "ghost.md"), "There's no piece ghost.md in this book."),
                           (lambda: self.b.new_piece("The Long Road", "chapter", after="ghost.md"), "There's no piece ghost.md in this book."),
                           (lambda: self.b.snapshot_text("The Long Road", "chapter-1.md", "2020-01-01T0000"),
                            "There's no snapshot 2020-01-01T0000 of chapter-1.md."),
                           (lambda: self.b.create(" "), "Give the book a title."),
                           (lambda: self.b.update("The Long Road", {"title": ""}), "Give the book a title."),
                           (lambda: self.b.edition("The Long Road", ""), "Give the edition a name.")):
            with self.assertRaises(BooksError) as e:
                call()
            self.assertEqual(str(e.exception), says)

    def test_unchanged_pieces_are_not_parsed_again(self):
        self.book()
        p = self.lib / "Books" / "The Long Road" / "manuscript" / "chapter-1.md"
        books_module._COUNTS.clear()
        with mock.patch.object(manuscript, "counts", wraps=manuscript.counts) as counts:
            self.b.list()
            self.b.list()
            self.b.read("The Long Road")
            self.assertEqual(counts.call_count, 2)                     # the dedication and the chapter, once each
            self.write_md("The Long Road", "chapter-1.md", "# Chapter 1\n\nNew words here.\n")
            later = p.stat().st_mtime + 5
            os.utime(p, (later, later))
            [item] = self.b.list()
            self.assertEqual(counts.call_count, 3)                     # only the edited piece again
            self.assertEqual(item["words"], 3)
            self.assertEqual(self.b.read("The Long Road")["contents"][5]["title"], "Chapter 1")
            self.assertEqual(counts.call_count, 3)

    def test_stamp_moves_when_the_styles_change(self):
        self.book()
        a = self.b.stamp()
        pal = self.lib / "Styles" / "palettes" / "dusk.json"
        pal.parent.mkdir(parents=True, exist_ok=True)
        pal.write_text('{"name": "Dusk", "swatches": [{"hex": "#101820"}]}', encoding="utf-8")
        os.utime(pal, (a + 100, a + 100))
        self.assertGreaterEqual(self.b.stamp(), a + 100)               # a book's look can change without its files

    # ——— the final review ———
    def test_a_file_replaced_with_an_older_mtime_is_a_stale_save(self):
        """OneDrive, Dropbox and rsync -t carry the source machine's time: an older mtime is also another version."""
        self.book()
        mine = self.b.piece("The Long Road", "chapter-1.md")
        path = self.lib / "Books" / "The Long Road" / "manuscript" / "chapter-1.md"
        path.write_text("# Chapter 1\n\nFrom the other computer.\n", encoding="utf-8")
        earlier = mine["mtime"] - 3600
        os.utime(path, (earlier, earlier))
        with self.assertRaises(BooksError) as e:
            self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nMine.\n", base_mtime=mine["mtime"])
        self.assertEqual(e.exception.code, 409)
        self.assertIn("other computer", path.read_text(encoding="utf-8"))
        same = self.b.piece("The Long Road", "chapter-1.md")["mtime"]
        self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nMine.\n", base_mtime=same)     # its own time: fine

    def test_a_stale_list_of_pieces_never_drops_a_piece(self):
        """A binder that read the book before another window added a piece sends a list without it: the piece stays,
        at the end of the body. Only delete_piece takes a piece out."""
        self.book()
        stale = self.b.read("The Long Road")["contents"]
        added = self.b.new_piece("The Long Road", "chapter", title="Added elsewhere")["file"]
        moved = [stale[0], stale[1], stale[2], stale[5], stale[3], stale[4], *stale[6:]]        # the binder moves a piece
        r = self.b.update("The Long Road", {"contents": moved})
        order = [e.get("file") or e.get("auto") for e in r["contents"]]
        self.assertEqual(order, ["half-title", "title-page", "copyright", "chapter-1.md", "dedication.md", "toc",
                                 added, "notes"])
        saved = json.loads((self.lib / "Books" / "The Long Road" / "book.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["contents"][6], {"file": added, "kind": "chapter", "form": "prose", "status": "idea"})
        r = self.b.update("The Long Road", {"contents": [e for e in r["contents"] if e.get("auto") != "toc"]})
        self.assertNotIn("toc", [e.get("auto") for e in r["contents"]])      # an auto page can still be taken out

    def test_a_piece_that_is_not_utf8_is_marked_and_never_rewritten(self):
        self.book()
        path = self.lib / "Books" / "The Long Road" / "manuscript" / "chapter-1.md"
        raw = "# Hoofdstuk één\n\nCafé.\n".encode("cp1252")
        path.write_bytes(raw)
        [item] = self.b.list()
        self.assertEqual(item["words"], 0)
        entry = next(e for e in self.b.read("The Long Road")["contents"] if e.get("file") == "chapter-1.md")
        self.assertTrue(entry["unreadable"])
        self.assertEqual((entry["words"], entry["notes"]), (0, 0))
        for call in (lambda: self.b.piece("The Long Road", "chapter-1.md"),
                     lambda: self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nNew.\n"),
                     lambda: self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nNew.\n", force=True)):
            with self.assertRaises(BooksError) as e:
                call()
            self.assertEqual(e.exception.code, 400)
            self.assertIn("isn't readable text", str(e.exception))
        self.assertEqual(self.b.search("The Long Road", "Café"), [])
        self.assertEqual(self.b.replace("The Long Road", "Caf", "Bar"), {"replaced": 0})
        self.assertEqual(path.read_bytes(), raw)                         # never rewritten

    def test_a_failed_write_of_the_daily_counts_keeps_the_save(self):
        self.book()
        days = self.lib / "Books" / "The Long Road" / ".studio" / "days.json"
        days.mkdir(parents=True)                                         # a folder where the file goes: the write fails
        r = self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nThree new words.\n")
        self.assertEqual(r["words"], 3)
        self.assertIn("Three new words", self.b.piece("The Long Road", "chapter-1.md")["md"])

    def test_file_names_from_book_json_are_checked(self):
        self.book()
        outside = self.lib / "Books" / "x.md"
        outside.write_text("# Outside\n\nSecret words outside the book.\n", encoding="utf-8")
        path = self.lib / "Books" / "The Long Road" / "book.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        bad = [{"file": n, "kind": "chapter"} for n in ("../../x.md", "..\\..\\x.md", "C:x.md", ".hidden.md", "a/b.md")]
        data["contents"] += bad
        path.write_text(json.dumps(data), encoding="utf-8")
        files = [e.get("file") for e in self.b.read("The Long Road")["contents"] if e.get("file")]
        self.assertEqual(files, ["dedication.md", "chapter-1.md"])
        self.assertEqual(self.b.list()[0]["pieces"], 2)
        self.assertEqual(self.b.search("The Long Road", "Secret"), [])
        for e in bad:
            for call in (lambda: self.b.piece("The Long Road", e["file"]),
                         lambda: self.b.save_piece("The Long Road", e["file"], md="# Overwritten\n"),
                         lambda: self.b.delete_piece("The Long Road", e["file"]),
                         lambda: self.b.history("The Long Road", e["file"])):
                with self.assertRaises(BooksError) as err:
                    call()
                self.assertEqual(err.exception.code, 404)
        self.assertIn("Secret words", outside.read_text(encoding="utf-8"))
        with self.assertRaises(BooksError):
            self.b.update("The Long Road", {"contents": [{"file": "../../x.md", "kind": "chapter"}]})

    def test_a_new_piece_never_takes_a_trashed_pieces_history(self):
        self.book(kind="fiction")
        self.b.save_piece("The Long Road", "chapter-1.md", md="# Chapter 1\n\nOld words.\n", leaving=True)
        self.assertTrue((self.lib / "Books" / "The Long Road" / "drafts" / "chapter-1").is_dir())
        self.b.delete_piece("The Long Road", "chapter-1.md")
        fresh = self.b.new_piece("The Long Road", "chapter", title="Chapter 1")
        self.assertNotEqual(fresh["file"], "chapter-1.md")
        self.assertEqual(self.b.history("The Long Road", fresh["file"]), [])

    # ——— big books ———
    def test_search_is_fast(self):
        self.book(kind="nonfiction")
        rnd = random.Random(7)
        words = "de een het huis straat avonds wij zijn lopen langs the river quiet world and said".split()
        for i in range(100):
            paras = [" ".join(rnd.choice(words) for _ in range(30)) + "." for _ in range(100)]
            self.b.new_piece("The Long Road", "chapter", title=f"P{i}")
            self.write_md("The Long Road", f"p{i}.md", f"# P{i}\n\n" + "\n\n".join(paras) + "\n")
        for f in (self.lib / "Books" / "The Long Road" / "manuscript").glob("*.md"):
            f.read_bytes()          # first reads of fresh files can be slow under a virus scanner; time the search itself
        start = time.perf_counter()
        hits = self.b.search("The Long Road", "river", whole=True)
        self.assertLess(time.perf_counter() - start, 2.0)
        self.assertGreater(len(hits), 1000)


if __name__ == "__main__":
    unittest.main()
