"""Research store tests. Run: python -m unittest discover tests"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from studio import clip, frontmatter, research
from studio.books import Books
from studio.research import Research, ResearchError, _board_lock

ROOT = Path(__file__).resolve().parent.parent


class FrontMatterTest(unittest.TestCase):
    def test_front_matter_round_trip(self):
        fields = {"type": "quote", "tags": ["a b", "ç"], "csl": {"id": "x1", "type": "book"}, "zzz": 1}
        text = frontmatter.dump(fields, "Body *it*.\n")
        self.assertTrue(text.startswith('---\ntype: "quote"\ntags: ["a b", "ç"]\n'))
        self.assertLess(text.index("csl:"), text.index("zzz: 1"))
        self.assertEqual(frontmatter.parse(text), (fields, "Body *it*.\n", True))
        self.assertEqual(frontmatter.dump({"type": "note"}, ""), '---\ntype: "note"\n---\n')

    def test_hand_written_files(self):
        text = "﻿---\r\ntitle: A letter\r\ntags:\r\n  - one\r\n  - 'two'\r\n# c\r\n---\r\nText\r\n"
        self.assertEqual(frontmatter.parse(text), ({"title": "A letter", "tags": ["one", "two"], "#1": "# c"}, "Text\n", True))
        self.assertEqual(frontmatter.parse("No front matter\n"), ({}, "No front matter\n", False))
        self.assertEqual(frontmatter.parse("---\ntitle: x\n"), ({}, "---\ntitle: x\n", False))
        self.assertEqual(frontmatter.parse("---\nt: 'it''s'\n---\n")[0], {"t": "it's"})

    def test_hand_written_lists_scalars_and_stray_lines(self):
        # part 3: what a person types by hand is read as YAML reads it and nothing of it is dropped
        fields = frontmatter.parse("---\ntags: [childhood, 1987, 'a, b', \"c\"]\nmap: {a: b}\nodd: [a: b]\n"
                                   "title: [Draft] a letter\n---\n")[0]
        self.assertEqual(fields["tags"], ["childhood", 1987, "a, b", "c"])
        self.assertEqual((fields["map"], fields["odd"]), (" {a: b}", " [a: b]"))
        self.assertIsInstance(fields["map"], frontmatter.RawYaml)
        self.assertIsInstance(fields["odd"], frontmatter.RawYaml)
        self.assertEqual(fields["title"], "[Draft] a letter")
        fields = frontmatter.parse("---\nsummary: |\n  one\n\n  two\n\ntitle: T\n---\n")[0]
        self.assertEqual(fields, {"summary": " |\n  one\n\n  two", "title": "T"})
        fields = frontmatter.parse("---\ntags:\n- a\n# c\n\n- b\ntitle: T\n---\n")[0]
        self.assertEqual(fields, {"tags": ["a", "b"], "title": "T"})
        fields = frontmatter.parse("---\n# top\ntitle: T\njust words\n:odd\n---\n")[0]
        self.assertEqual(fields, {"#1": "# top", "title": "T", "#2": "just words\n:odd"})


class ResearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.r = Research(self.tmp)
        self.book = Books(self.tmp / "Books").create("Test Book")["id"]

    def hand(self, board, name, text, raw=None):
        d = self.r.board_dir(board)
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(raw if raw is not None else text.encode("utf-8"))
        return d / name

    def test_hand_file_without_front_matter_is_a_note_and_untouched(self):
        p = self.hand(None, "loose.md", "Just words.\r\n")
        before = p.read_bytes()
        s = self.r.read(None)["items"][0]
        self.assertEqual((s["id"], s["type"]), ("loose", "note"))
        self.assertEqual(self.r.item(None, "loose")["text"], "Just words.\n")
        self.assertEqual(p.read_bytes(), before)

    def test_ids(self):
        a = self.r.add(None, {"type": "note", "title": "Één brief"})
        b = self.r.add(None, {"type": "note", "title": "Één brief"})
        self.assertEqual((a["id"], b["id"]), ("een-brief", "een-brief-2"))
        self.assertEqual(self.r.add(None, {"type": "note", "title": "CON"})["id"], "con-1")
        words = "Het was een koude winter in het noorden van het land"
        self.assertEqual(self.r.add(None, {"type": "note", "text": words})["id"], "het-was-een-koude-winter-in")
        self.assertEqual(self.r.add(None, {"type": "quote"})["id"], "quote")
        # a source without a title of its own is named by its work's title, else its key; never its text
        s = self.r.add(None, {"type": "source", "text": "Notes on it", "csl": {"type": "book", "title": "Een boek"}})
        self.assertEqual(s["id"], "een-boek")
        s = self.r.add(None, {"type": "source", "text": "Notes on it", "csl": {"type": "book", "author": [
            {"family": "Example", "given": "An"}], "issued": {"date-parts": [[2001]]}}})
        self.assertEqual((s["id"], s["csl"]["id"]), ("example2001", "example2001"))
        self.assertEqual(self.r.add(None, {"type": "source", "title": "Mine", "csl": {"type": "book", "title": "T"}})["id"], "mine")

    def test_add_read_item(self):
        self.r.add(self.book, {"type": "note", "title": "N", "text": "Some *it*."}, at={"x": 10, "y": 20})
        self.r.add(self.book, {"type": "quote", "text": "Words", "source": "vandijk1998", "locator": "p. 12"})
        src = self.r.add(self.book, {"type": "source", "csl": {
            "type": "book", "title": "Kind", "issued": {"date-parts": [[1998]]},
            "author": [{"family": "Dijk", "non-dropping-particle": "van"}]}})
        self.assertEqual(src["csl"]["id"], "vandijk1998")
        board = self.r.read(self.book)
        self.assertEqual(len(board["items"]), 3)
        self.assertEqual(board["kinds"], {"note": 1, "quote": 1, "source": 1})
        self.assertEqual(board["title"], "Test Book")
        note = next(s for s in board["items"] if s["type"] == "note")
        self.assertEqual((note["pos"]["x"], note["pos"]["y"], note["pos"]["placed"]), (10, 20, True))
        quote = next(s for s in board["items"] if s["type"] == "quote")
        self.assertEqual((quote["source"], quote["locator"], quote["source_label"]), ("vandijk1998", "p. 12", "van Dijk 1998, p. 12"))
        self.assertIn("<em>it</em>", self.r.item(self.book, "n")["html"])
        evil = self.r.add(self.book, {"type": "note", "text": "<script>alert(1)</script> [x](http://a.b)"})
        self.assertNotIn("<script>", evil["html"])
        self.assertIn("&lt;script&gt;", evil["html"])
        self.assertIn('target="_blank" rel="noopener noreferrer"', evil["html"])
        again = self.r.add(self.book, {"type": "source", "csl": {"type": "book", "title": "Other",
                                                                   "issued": {"date-parts": [[1998]]},
                                                                   "author": [{"family": "Dijk", "non-dropping-particle": "van"}]}})
        self.assertEqual(again["csl"]["id"], "vandijk1998b")

    def test_add_refuses(self):
        for bad in ({"type": "clip"}, {"type": "image"}, {"type": "nope"}, {}):
            with self.assertRaises(ResearchError) as e:
                self.r.add(None, bad)
            self.assertEqual(e.exception.code, 400)
        with self.assertRaises(ResearchError):
            self.r.add(None, {"type": "quote", "source": "not a key"})
        with self.assertRaises(ResearchError):
            self.r.add(None, {"type": "source", "csl": {"id": "x"}})
        with self.assertRaises(ResearchError) as e:
            self.r.add("No Such Book", {"type": "note"})
        self.assertEqual(e.exception.code, 404)

    def test_unplaced_items_placed_on_read_without_a_write(self):
        self.r.add(None, {"type": "note", "title": "Placed"}, at={"x": 0, "y": 0})
        self.hand(None, "b.md", '---\ncreated: "2026-01-02T00:00:00"\n---\nB\n')
        self.hand(None, "a.md", '---\ncreated: "2026-01-01T00:00:00"\n---\nA\n')
        layout = self.r.board_dir(None) / "board.json"
        before = layout.stat().st_mtime_ns
        items = {s["id"]: s["pos"] for s in self.r.read(None)["items"]}
        self.assertEqual((items["a"]["placed"], items["a"]["x"], items["a"]["y"]), (False, 320, 0))
        self.assertEqual((items["b"]["placed"], items["b"]["x"], items["b"]["y"]), (False, 320, 160 + 24))
        self.assertTrue(items["placed"]["placed"])
        self.assertEqual(layout.stat().st_mtime_ns, before)

    def test_update_and_stale_409(self):
        it = self.r.add(None, {"type": "note", "title": "N", "text": "one"})
        newer = self.r.update(None, "n", {"text": "two"}, base_mtime=it["mtime"])
        self.assertEqual(newer["text"], "two\n")
        with self.assertRaises(ResearchError) as e:
            self.r.update(None, "n", {"text": "three"}, base_mtime=it["mtime"] - 5)
        self.assertEqual(e.exception.code, 409)
        self.assertEqual(e.exception.details["current"]["text"], newer["text"])
        self.assertEqual(self.r.update(None, "n", {"text": "three"}, base_mtime=it["mtime"] - 5, force=True)["text"].strip(), "three")
        for bad in ({"type": "note"}, {"url": "x"}, {"book": "x"}):
            with self.assertRaises(ResearchError) as e:
                self.r.update(None, "n", bad)
            self.assertEqual(e.exception.code, 400)
        self.assertIn("can't be changed here", str(e.exception))

    def test_hand_written_nested_yaml_survives_update(self):
        raw = ("---\ntitle: A letter\nfoo:\n  a: 1\n  b:\n    - x\nnote: |\n  line one\n  line two\n"
               "csl:\n  id: k1\n  type: book\ntags:\n  - one\n---\nOld\n")
        p = self.hand(None, "letter.md", raw)
        out = self.r.update(None, "letter", {"text": "New text"})
        text = p.read_text(encoding="utf-8")
        for part in ("foo:\n  a: 1\n  b:\n    - x\n", "note: |\n  line one\n  line two\n", "csl:\n  id: k1\n  type: book\n"):
            self.assertIn(part, text)
        self.assertTrue(text.endswith("---\nNew text\n"))
        self.assertEqual(out["tags"], ["one"])
        self.assertNotIn("csl", out)

    def test_hand_written_yaml_kept_on_update(self):
        # part 3: the first save from Studio keeps the author's own lines
        cases = {                       # name: (the author's lines, the tags read, what the saved file holds)
            "flow": ("tags: [childhood, 1987]\nmap: {a: b}\n", ["childhood", "1987"], None),
            "scalar": ("summary: |\n  one\n\n  two\n\n  three\n", [], None),
            "listed": ("tags:\n- a\n# c\n- b\n", ["a", "b"], None),
            "stray": ("# top\njust words\n:odd\n", [], None),
            "letter": ("type: letter\n", [], 'type: "letter"\n'),
        }
        for name, (lines, tags, kept) in cases.items():
            with self.subTest(name):
                p = self.hand(None, f"{name}.md", f"---\ntitle: T\n{lines}---\nOld\n")
                s = next(s for s in self.r.read(None)["items"] if s["id"] == name)
                self.assertEqual((s["type"], s["title"], s["tags"]), ("note", "T", tags))
                self.r.update(None, name, {"text": "New text"})
                text = p.read_text(encoding="utf-8")
                self.assertIn(kept or lines, text)
                self.assertTrue(text.endswith("---\nNew text\n"))
                self.assertEqual(self.r.item(None, name)["type"], "note")
        self.r.update(None, "flow", {"tags": ["childhood", "1987", "x"]})
        self.assertIn('tags: ["childhood", "1987", "x"]\n', (self.r.board_dir(None) / "flow.md").read_text(encoding="utf-8"))
        p = self.hand(None, "q.md", "---\ntype: quote\n---\nQ\n")
        self.r.update(None, "q", {"text": "Q2"})
        self.assertIn('type: "quote"\n', p.read_text(encoding="utf-8"))
        p = self.hand(None, "bare.md", "---\ntitle: B\n---\nB\n")
        self.r.update(None, "bare", {"text": "B2"})
        self.assertIn('type: "note"\n', p.read_text(encoding="utf-8"))

    def test_delete_with_a_repeated_id(self):
        self.r.add(None, {"type": "note", "title": "N"})
        self.assertEqual(len(self.r.delete(None, ["n", "n"])), 1)

    def test_remote_images_are_not_rendered(self):
        it = self.r.add(None, {"type": "note", "text": "![a cat](https://example.com/c.png)"})
        self.assertNotIn("<img", it["html"])
        self.assertIn("[image: a cat]", it["html"])

    def test_update_keeps_unknown_keys_and_a_sources_key(self):
        p = self.hand(None, "q.md", '---\ntype: "quote"\nzzz: 1\n---\nQ\n')
        self.r.update(None, "q", {"locator": "p. 3", "source": "dijk1"})
        self.assertIn("zzz: 1", p.read_text(encoding="utf-8"))
        self.assertEqual(self.r.item(None, "q")["extra"], {"zzz": 1})
        s = self.r.add(None, {"type": "source", "csl": {"type": "book", "id": "k1", "title": "T"}})
        out = self.r.update(None, s["id"], {"csl": {"type": "book", "title": "T2"}})
        self.assertEqual(out["csl"]["id"], "k1")

    def test_tags_are_cleaned(self):
        it = self.r.add(None, {"type": "note", "title": "T", "tags": ["  a   b ", "A B", "", "x" * 40]})
        self.assertEqual(it["tags"], ["a b", "x" * 40])
        with self.assertRaises(ResearchError) as e:
            self.r.update(None, "t", {"tags": ["a b", "x" * 50]})
        self.assertEqual(e.exception.code, 400)

    def test_delete_goes_to_trash_with_files(self):
        d = self.r.board_dir(None)
        (d / "files").mkdir(parents=True)
        (d / "files" / "n.jpg").write_bytes(b"jpg")
        self.hand(None, "n.md", '---\ntype: "clip"\nshot: "files/n.jpg"\n---\nx\n')
        self.r.add(None, {"type": "note", "title": "Keep"}, at={"x": 5, "y": 5})
        layout = d / "board.json"
        data = json.loads(layout.read_text(encoding="utf-8"))
        data["items"]["n"] = {"x": 1, "y": 2}
        layout.write_text(json.dumps(data), encoding="utf-8")
        trashed = self.r.delete(None, ["n"])
        names = sorted(p.name for p in (d / ".trash").iterdir())
        self.assertEqual(len(names), 2)
        self.assertTrue(any(n.endswith(" n.md") for n in names) and any(n.endswith(" n n.jpg") for n in names))
        self.assertTrue(Path(trashed[0]).is_file())
        self.assertFalse((d / "n.md").exists() or (d / "files" / "n.jpg").exists())
        self.assertEqual([s["id"] for s in self.r.read(None)["items"]], ["keep"])
        self.assertNotIn("n", json.loads(layout.read_text(encoding="utf-8"))["items"])
        with self.assertRaises(ResearchError) as e:
            self.r.delete(None, ["n"])
        self.assertEqual(e.exception.code, 404)

    def test_unreadable_item(self):
        p = self.hand(None, "old.md", None, raw="caf\xe9\n".encode("latin-1"))
        s = self.r.read(None)["items"][0]
        self.assertEqual((s["id"], s["type"]), ("old", "note"))
        self.assertIn("error", s)
        with self.assertRaises(ResearchError) as e:
            self.r.update(None, "old", {"text": "new"})
        self.assertEqual(e.exception.code, 400)
        self.assertEqual(p.read_bytes(), "caf\xe9\n".encode("latin-1"))

    def test_broken_board_json_reads_empty_and_is_kept(self):
        self.hand(None, "a.md", "A\n")
        (self.r.board_dir(None) / "board.json").write_text('{"items": [', encoding="utf-8")
        board = self.r.read(None)
        self.assertEqual([s["pos"]["placed"] for s in board["items"]], [False])
        self.assertEqual((self.r.board_dir(None) / "board.json").read_text(encoding="utf-8"), '{"items": [')

    def test_thumb_of_a_hand_made_image(self):
        d = self.r.board_dir(self.book)
        (d / "files").mkdir(parents=True)
        (d / "files" / "a b.png").write_bytes(b"png")
        self.hand(self.book, "pic.md", '---\ntype: "image"\nfile: "files/a b.png"\n---\n')
        thumb = self.r.read(self.book)["items"][0]["thumb"]
        self.assertTrue(thumb.startswith(f"/researchfiles/{quote(self.book, safe='')}/a%20b.png?w=640&v="))

    def test_file_confinement(self):
        d = self.r.board_dir(None)
        (d / "files").mkdir(parents=True)
        (d / "files" / "x.png").write_bytes(b"png")
        (d / "files" / "x.txt").write_bytes(b"t")
        (d / "board.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.r.file("_shared/x.png"), (d / "files" / "x.png").resolve())
        for bad in ("_shared/../board.json", "_shared/.trash/x.png", "_shared/x.txt", "Nope/x.png", "_shared/y.png"):
            with self.assertRaises(ResearchError) as e:
                self.r.file(bad)
            self.assertEqual(e.exception.code, 404, bad)

    def test_shared_board_needs_no_folder(self):
        board = self.r.read(None)
        self.assertEqual((board["items"], board["title"]), ([], "Shared board"))
        self.assertFalse((self.tmp / "Research").exists())
        self.r.add(None, {"type": "note", "title": "First"})
        self.assertTrue((self.tmp / "Research").is_dir())
        listed = self.r.boards()
        self.assertEqual([(b["board"], b["items"]) for b in listed], [(None, 1), (self.book, 0)])

    def test_stamp_follows_the_board_not_the_trash(self):
        self.r.add(None, {"type": "note", "title": "A"})
        s1 = self.r.stamp(None)
        time.sleep(0.02)
        self.r.add(None, {"type": "note", "title": "B"})
        s2 = self.r.stamp(None)
        self.assertGreater(s2, s1)
        self.assertEqual(self.r.stamp(None, every=True), s2)
        self.r.delete(None, ["b"])
        s3 = self.r.stamp(None)
        trashed = next((self.r.board_dir(None) / ".trash").iterdir())
        time.sleep(0.02)
        trashed.touch()
        self.assertEqual(self.r.stamp(None), s3)

    def test_research_does_not_move_the_books_stamp(self):
        books = Books(self.tmp / "Books")
        before = books.stamp()
        time.sleep(0.02)
        self.r.add(self.book, {"type": "note", "title": "Hello"}, at={"x": 1, "y": 2})
        self.assertEqual(books.stamp(), before)

    def test_read_is_fast(self):
        text = " ".join(f"word{i}" for i in range(120))
        for i in range(500):
            self.hand(None, f"n{i}.md", f"---\ntype: \"note\"\ntags: [\"t{i % 7}\"]\n---\n{text}\n")
        self.r.read(None)
        t = time.perf_counter()
        board = self.r.read(None)
        self.assertLess(time.perf_counter() - t, 0.5)
        self.assertEqual(len(board["items"]), 500)

    # ——— Task 2: layout, frames, links, moving, sources and search ———
    def source(self, board, people, year=None, title="Kind", key=None, **more):
        csl = {"type": "book", "title": title, "author": people, **more}
        if year is not None:
            csl["issued"] = {"date-parts": [[year]]}
        if key:
            csl["id"] = key
        return self.r.add(board, {"type": "source", "csl": csl})

    def positions(self, board):
        return {s["id"]: s["pos"] for s in self.r.read(board)["items"]}

    def board_json(self, board):
        return json.loads((self.r.board_dir(board) / "board.json").read_text(encoding="utf-8"))

    @contextmanager
    def busy(self, board):
        """The board's .lock held through a handle of its own, as the other process would; waits cut to 0.2 s."""
        d = self.r.board_dir(board)
        d.mkdir(parents=True, exist_ok=True)
        fd = research._lock_fd(d / ".lock", 1)
        try:
            with mock.patch.object(research, "LOCK_WAIT", 0.2):
                yield
        finally:
            research._unlock_fd(fd)

    def test_layout_merges_two_writers(self):
        self.r.add(self.book, {"type": "note", "title": "A"})
        self.r.add(self.book, {"type": "note", "title": "B"})
        one, two = Research(self.tmp), Research(self.tmp)
        one.layout(self.book, items={"a": {"x": 500, "y": 40}})
        two.layout(self.book, items={"b": {"x": 900, "y": 60, "w": 300, "h": None}, "nope": {"x": 1, "y": 1}},
                   frames=[{"title": "Childhood", "x": 0, "y": 0, "w": 400, "h": 300}])
        board = self.r.read(self.book)
        pos = {s["id"]: s["pos"] for s in board["items"]}
        self.assertEqual((pos["a"]["x"], pos["a"]["y"]), (500, 40))
        self.assertEqual((pos["b"]["x"], pos["b"]["y"], pos["b"]["w"], pos["b"]["h"]), (900, 60, 300, None))
        self.assertEqual([f["id"] for f in board["frames"]], ["f-childhood"])
        self.assertEqual(board["frames"][0]["title"], "Childhood")
        self.assertNotIn("nope", self.board_json(self.book)["items"])
        layout_file = self.r.board_dir(self.book) / "board.json"
        before = layout_file.stat().st_mtime_ns
        one.layout(self.book, items={"nope": {"x": 1, "y": 1}})            # nothing to change: nothing written
        self.assertEqual(layout_file.stat().st_mtime_ns, before)
        for bad in ({"x": 0, "y": 0, "w": 90}, {"x": float("inf"), "y": 0}, {"x": 2e6, "y": 0}, {"x": True, "y": 0},
                    {"x": 0, "y": 0, "h": 10}, {"x": 0, "y": 0, "frame": "f-none"}, "here"):
            with self.assertRaises(ResearchError) as e:
                one.layout(self.book, items={"a": bad})
            self.assertEqual(e.exception.code, 400, bad)
        self.assertEqual((self.positions(self.book)["a"]["x"], self.positions(self.book)["a"]["w"]), (500, 240))

    def test_layout_from_two_threads_keeps_every_write(self):
        for i in range(60):
            self.hand(None, f"n{i}.md", f"Note {i}\n")
        errors = []

        def write(start):
            r = Research(self.tmp)
            try:
                for i in range(start, start + 30):
                    r.layout(None, items={f"n{i}": {"x": i * 10, "y": i}})
            except Exception as e:      # noqa: BLE001 — reported below
                errors.append(e)
        threads = [threading.Thread(target=write, args=(s,)) for s in (0, 30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        items = self.board_json(None)["items"]
        self.assertEqual({k: (v["x"], v["y"]) for k, v in items.items()}, {f"n{i}": (i * 10, i) for i in range(60)})

    def test_board_lock_holds_across_processes(self):
        d = self.r.board_dir(self.book)
        code = ("import sys\nfrom pathlib import Path\nfrom studio.research import _board_lock\n"
                "with _board_lock(Path(sys.argv[1])):\n    print('held', flush=True)\n    sys.stdin.read()\n")
        child = subprocess.Popen([sys.executable, "-c", code, str(d)], cwd=ROOT, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "held")
            with self.assertRaises(ResearchError) as e:
                with _board_lock(d, timeout=0.2):
                    pass
            self.assertEqual((e.exception.code, str(e.exception)), (409, "The board is busy; try again."))
        finally:
            child.communicate(timeout=10)
        with _board_lock(d, timeout=5):         # free again once the other process let go
            self.assertTrue((d / ".lock").is_file())
        self.assertEqual(self.r.read(self.book)["items"], [])      # the lock file isn't an item

    def test_board_lock_waits_for_another_thread(self):
        d = self.r.board_dir(None)
        held, done = threading.Event(), threading.Event()

        def hold():
            with _board_lock(d):
                held.set()
                done.wait(10)
        t = threading.Thread(target=hold)
        t.start()
        try:
            held.wait(10)
            with self.assertRaises(ResearchError) as e:
                with _board_lock(d, timeout=0.2):
                    pass
            self.assertEqual(e.exception.code, 409)
        finally:
            done.set()
            t.join()
        with _board_lock(d, timeout=5):
            with _board_lock(d, timeout=0.2):       # the same thread may take it again
                pass

    def test_add_without_a_place_is_placed_at_once(self):
        a = self.r.add(None, {"type": "note", "title": "A"})
        b = self.r.add(None, {"type": "quote", "text": "Q"})
        self.assertEqual((a["pos"]["placed"], a["pos"]["x"], a["pos"]["y"], a["pos"]["z"]), (True, 0, 0, 0))
        self.assertEqual((b["pos"]["placed"], b["pos"]["x"], b["pos"]["y"], b["pos"]["z"]), (True, 0, 160 + 24, 1))
        self.r.layout(None, items={"a": {"x": 1000, "y": 500}})     # no column any more: a new one right of everything
        c = self.r.add(None, {"type": "note", "title": "C"})
        self.assertEqual((c["pos"]["x"], c["pos"]["y"]), (1000 + 240 + 80, 184))
        d = self.r.add(None, {"type": "note", "title": "D"})
        self.assertEqual((d["pos"]["x"], d["pos"]["y"], d["pos"]["z"]), (1320, 184 + 160 + 24, 3))

    def test_frames_and_membership(self):
        self.r.layout(self.book, frames=[{"title": "Childhood", "x": 100, "y": 50, "w": 400, "h": 300}])
        a = self.r.add(self.book, {"type": "note", "title": "A"}, frame="f-childhood")
        b = self.r.add(self.book, {"type": "note", "title": "B"}, frame="f-childhood")
        self.assertEqual((a["pos"]["x"], a["pos"]["y"], a["pos"]["frame"]), (124, 106, "f-childhood"))
        self.assertEqual((b["pos"]["x"], b["pos"]["y"], b["pos"]["frame"]), (124, 106 + 160 + 24, "f-childhood"))
        frame = self.r.read(self.book)["frames"][0]
        self.assertEqual((frame["y"], frame["h"]), (50, 290 + 160 + 24 - 50))       # grown to hold b
        c = self.r.add(self.book, {"type": "note", "title": "C"}, at={"x": 700, "y": 10}, frame="f-childhood")
        self.assertEqual((c["pos"]["x"], c["pos"]["y"], c["pos"]["frame"]), (700, 10, "f-childhood"))
        self.assertEqual(self.r.read(self.book)["frames"][0]["h"], 424)
        for at in ({"x": 0, "y": 0}, None):
            with self.assertRaises(ResearchError) as e:
                self.r.add(self.book, {"type": "note", "title": "X"}, at=at, frame="f-none")
            self.assertEqual((e.exception.code, str(e.exception)), (400, "There's no such frame."))
        self.assertFalse((self.r.board_dir(self.book) / "x.md").exists())
        board = self.r.layout(self.book, remove_frames=["f-childhood"])
        self.assertEqual(board["frames"], [])
        pos = {s["id"]: s["pos"] for s in board["items"]}
        self.assertEqual((pos["a"]["x"], pos["a"]["y"], pos["a"]["frame"]), (124, 106, None))
        self.assertEqual((pos["b"]["frame"], pos["c"]["frame"]), (None, None))
        frames = self.r.layout(self.book, frames=[{"title": " Twee  zeeën ", "x": 0, "y": 0, "w": 200, "h": 200},
                                                  {"title": "Twee zeeën", "x": 0, "y": 0, "w": 200, "h": 200},
                                                  {"x": 5, "y": 5, "w": 160, "h": 160}])["frames"]
        self.assertEqual([(f["id"], f["title"]) for f in frames],
                         [("f-twee-zeeen", "Twee zeeën"), ("f-twee-zeeen-2", "Twee zeeën"), ("f-frame", "Frame")])
        self.assertEqual([f["z"] for f in frames], [0, 1, 2])
        frames = self.r.layout(self.book, frames=[{"id": "f-frame", "title": "Renamed", "w": 500}])["frames"]
        self.assertEqual((frames[2]["title"], frames[2]["w"], frames[2]["x"]), ("Renamed", 500, 5))
        for bad in ({"title": "x" * 81, "x": 0, "y": 0, "w": 200, "h": 200}, {"title": "T", "x": 0, "y": 0, "w": 100, "h": 200},
                    {"title": "T", "x": 0, "y": 0}, {"id": "Not An Id", "title": "T", "x": 0, "y": 0, "w": 200, "h": 200}):
            with self.assertRaises(ResearchError) as e:
                self.r.layout(self.book, frames=[bad])
            self.assertEqual(e.exception.code, 400, bad)

    def test_link_shows_and_edits_the_original(self):
        self.r.add(None, {"type": "note", "title": "Winter", "text": "Het was koud.", "tags": ["weer"]})
        link = self.r.add(self.book, {"type": "link", "board": None, "item": "winter"})
        self.assertEqual(link["id"], "winter")
        s = next(s for s in self.r.read(self.book)["items"] if s["id"] == link["id"])
        self.assertEqual((s["type"], s["title"], s["excerpt"], s["tags"]), ("note", "Winter", "Het was koud.", ["weer"]))
        self.assertEqual(s["link"], {"board": None, "board_title": "Shared board", "item": "winter", "missing": False})
        full = self.r.item(self.book, link["id"])
        self.assertEqual((full["text"], full["mtime"]), ("Het was koud.\n", self.r.item(None, "winter")["mtime"]))
        out = self.r.update(self.book, link["id"], {"text": "Het vroor."}, base_mtime=full["mtime"])
        self.assertEqual((out["id"], out["text"]), (link["id"], "Het vroor.\n"))
        self.assertEqual((self.r.board_dir(None) / "winter.md").read_text(encoding="utf-8").split("---\n")[-1], "Het vroor.\n")
        with self.assertRaises(ResearchError) as e:
            self.r.update(self.book, link["id"], {"text": "x"}, base_mtime=full["mtime"] - 5)
        self.assertEqual((e.exception.code, e.exception.details["current"]["id"]), (409, link["id"]))
        for bad in ({"type": "link", "board": None, "item": "nope"}, {"type": "link", "board": self.book, "item": "winter"},
                    {"type": "link", "board": "No Such Book", "item": "winter"}):
            with self.assertRaises(ResearchError) as e:
                self.r.add(self.book, bad)
            self.assertEqual(e.exception.code, 400, bad)
        self.r.delete(None, ["winter"])
        s = next(s for s in self.r.read(self.book)["items"] if s["id"] == link["id"])
        self.assertEqual((s["type"], s["link"]["missing"], s["link"]["item"]), ("link", True, "winter"))
        self.assertEqual(self.r.item(self.book, link["id"])["link"]["missing"], True)

    def test_move_rewrites_links_and_keeps_sources(self):
        other = Books(self.tmp / "Books").create("Second Book")["id"]
        src = self.source(self.book, [{"family": "Dijk", "non-dropping-particle": "van"}], 1998)
        q = self.r.add(self.book, {"type": "quote", "text": "Het was koud.", "source": "vandijk1998", "locator": "p. 12"})
        shared = self.r.add(None, {"type": "link", "board": self.book, "item": q["id"]})
        self.r.add(other, {"type": "note", "text": "Het was koud."})        # takes the quote's id there
        d, d2 = self.r.board_dir(self.book), self.r.board_dir(other)
        (d / "files").mkdir()
        (d / "files" / "pic.png").write_bytes(b"one")
        (d2 / "files").mkdir()
        (d2 / "files" / "pic.png").write_bytes(b"two")
        self.hand(self.book, "pic.md", '---\ntype: "image"\nfile: "files/pic.png"\n---\n')
        moved = self.r.move(self.book, [q["id"], "pic"], other)
        self.assertEqual([m["id"] for m in moved], ["het-was-koud-2", "pic"])
        self.assertEqual((moved[0]["type"], moved[0]["source_label"], moved[0]["pos"]["placed"]), ("quote", "van Dijk 1998, p. 12", True))
        self.assertFalse((d / f"{q['id']}.md").exists())
        self.assertTrue((d2 / "het-was-koud-2.md").is_file())
        self.assertNotIn(q["id"], self.board_json(self.book)["items"])
        self.assertEqual(((d2 / "files" / "pic-2.png").read_bytes(), (d2 / "files" / "pic.png").read_bytes()), (b"one", b"two"))
        self.assertIn('file: "files/pic-2.png"', (d2 / "pic.md").read_text(encoding="utf-8"))
        s = next(s for s in self.r.read(None)["items"] if s["id"] == shared["id"])
        self.assertEqual((s["link"]["board"], s["link"]["item"], s["link"]["missing"]), (other, "het-was-koud-2", False))
        links = [s["link"] for s in self.r.read(other)["items"] if "link" in s]
        self.assertEqual([(x["board"], x["item"]) for x in links], [(self.book, src["id"])])
        with self.assertRaises(ResearchError) as e:
            self.r.move(other, ["het-was-koud-2"], other)
        self.assertEqual(e.exception.code, 400)
        with self.assertRaises(ResearchError) as e:
            self.r.move(other, ["nope"], None)
        self.assertEqual(e.exception.code, 404)

    def test_move_link_home_removes_it(self):
        self.r.add(None, {"type": "note", "title": "Home"})
        link = self.r.add(self.book, {"type": "link", "board": None, "item": "home"})
        out = self.r.move(self.book, [link["id"]], None)
        self.assertEqual([(o["id"], o["type"]) for o in out], [("home", "note")])
        self.assertEqual(self.r.read(self.book)["items"], [])
        self.assertEqual([s["id"] for s in self.r.read(None)["items"]], ["home"])
        first = self.r.move(None, ["home"], self.book, link=True)
        again = self.r.move(None, ["home"], self.book, link=True)
        self.assertEqual((first[0]["id"], again[0]["id"], len(self.r.read(self.book)["items"])), ("home", "home", 1))
        self.assertTrue(first[0]["pos"]["placed"])
        other = Books(self.tmp / "Books").create("Second Book")["id"]
        linked = self.r.move(self.book, [first[0]["id"]], other, link=True)        # a link of a link links the original
        self.assertEqual((linked[0]["link"]["board"], linked[0]["link"]["item"]), (None, "home"))
        self.assertEqual(self.r.move(other, [linked[0]["id"]], None, link=True)[0]["id"], "home")
        self.assertEqual(len(self.r.read(other)["items"]), 1)

    def test_sources_follow_moves(self):
        books = Books(self.tmp / "Books")
        a, b = self.book, books.create("Book B")["id"]
        books.save_sources(a, [{"id": "field-notes", "type": "manuscript", "title": "Field notes", "issued": {"date-parts": [[2001]]}}])
        q = self.r.add(a, {"type": "quote", "text": "Q one", "source": "field-notes"})
        out = self.r.move(a, [q["id"]], None)
        sources = [s for s in self.r.read(None)["items"] if s["type"] == "source"]
        self.assertEqual([(s["id"], s["csl"]["id"], s["csl"]["title"]) for s in sources], [("field-notes", "field-notes", "Field notes")])
        self.assertEqual(out[0]["source_label"], "Field notes 2001")
        src = self.source(a, [{"family": "Dijk", "non-dropping-particle": "van"}], 1998)
        q2 = self.r.add(a, {"type": "quote", "text": "Q two", "source": "vandijk1998"})
        moved = self.r.move(a, [src["id"]], b)
        left = [s for s in self.r.read(a)["items"] if "link" in s]
        self.assertEqual([(s["type"], s["link"]["board"], s["link"]["item"]) for s in left], [("source", b, moved[0]["id"])])
        label = {s["id"]: s.get("source_label") for s in self.r.read(a)["items"]}
        self.assertEqual(label[q2["id"]], "van Dijk 1998")
        self.r.delete(b, [moved[0]["id"]])
        label = {s["id"]: s.get("source_label") for s in self.r.read(a)["items"]}
        self.assertEqual(label[q2["id"]], "vandijk1998")
        file = books.dir(a) / "sources.json"
        before = file.read_bytes()
        used = self.r.use(a, a, q2["id"])
        self.assertEqual((used["kind"], used["key"], used["added"], used["warning"]),
                         ("quote", "vandijk1998", False, "This quote's source isn't on its board any more."))
        self.assertEqual(file.read_bytes(), before)
        books.save_sources(b, [{"id": "vos2001", "type": "book", "title": "Zee", "issued": {"date-parts": [[2001]]}}])
        sq = self.r.add(None, {"type": "quote", "text": "Zee", "source": "vos2001"})
        used = self.r.use(b, None, sq["id"])
        self.assertEqual((used["key"], used["added"], "warning" in used), ("vos2001", False, False))

    def test_delete_and_restore(self):
        d = self.r.board_dir(None)
        (d / "files").mkdir(parents=True)
        (d / "files" / "pic.png").write_bytes(b"png")
        self.hand(None, "pic.md", '---\ntype: "image"\nfile: "files/pic.png"\n---\nA caption\n')
        self.r.add(None, {"type": "note", "title": "N"})
        names = [Path(p).name for p in self.r.delete(None, ["pic", "n"])]
        self.assertEqual(self.r.read(None)["items"], [])
        back = self.r.restore(None, names)
        self.assertEqual(sorted((b["id"], b["pos"]["placed"]) for b in back), [("n", False), ("pic", False)])
        self.assertEqual((d / "files" / "pic.png").read_bytes(), b"png")
        self.assertEqual(os.listdir(d / ".trash"), [])
        self.assertEqual(sorted(s["id"] for s in self.r.read(None)["items"]), ["n", "pic"])
        names = [Path(p).name for p in self.r.delete(None, ["n", "pic"])]
        self.r.add(None, {"type": "note", "title": "N"})
        (d / "files" / "pic.png").write_bytes(b"new")
        back = self.r.restore(None, names)
        self.assertEqual([b["id"] for b in back], ["n-2", "pic"])
        self.assertEqual((d / "files" / "pic-2.png").read_bytes(), b"png")
        self.assertIn('file: "files/pic-2.png"', (d / "pic.md").read_text(encoding="utf-8"))
        for bad in (["20260101T000000 nope.md"], ["../board.json"], [".lock"], names):
            with self.assertRaises(ResearchError) as e:
                self.r.restore(None, bad)
            self.assertEqual(e.exception.code, 404, bad)
        board = self.r.layout(None, frames=[{"id": "f-old", "title": "Old", "x": 0, "y": 0, "w": 400, "h": 300}])
        self.assertEqual([(f["id"], f["title"]) for f in board["frames"]], [("f-old", "Old")])

    def test_citable_order_and_labels(self):
        books = Books(self.tmp / "Books")
        van = [{"family": "Dijk", "non-dropping-particle": "van"}]
        self.source(None, van, 1998, title="Shared copy", key="vandijk1998")
        self.source(self.book, van, 1998, title="Book copy", key="vandijk1998")
        two = self.source(self.book, [{"family": "Dijk", "given": "A."}, {"family": "Vos"}], 2001)
        three = self.source(self.book, [{"family": "Dijk"}, {"family": "Vos"}, {"literal": "Groep"}], 2003)
        title = "Notes on a winter in the north, part one"
        self.assertEqual(len(title), 40)
        untitled = self.source(self.book, [], title=title)
        books.save_sources(self.book, [{"id": "zeeman2010", "type": "book", "title": "Zee", "author": [{"family": "Zeeman"}],
                                        "issued": {"date-parts": [[2010]]}},
                                       {"id": "vandijk1998", "type": "book", "title": "Sources copy"}])
        cit = self.r.citable(self.book)
        keys = [c["key"] for c in cit]
        self.assertEqual((keys.count("vandijk1998"), keys[-1]), (1, "zeeman2010"))
        vd = next(c for c in cit if c["key"] == "vandijk1998")
        self.assertEqual((vd["title"], vd["board"], vd["label"]), ("Book copy", self.book, "van Dijk 1998"))
        labels = {c["key"]: c["label"] for c in cit}
        self.assertEqual(labels[two["csl"]["id"]], "Dijk & Vos 2001")
        self.assertEqual(labels[three["csl"]["id"]], "Dijk et al. 2003")
        self.assertEqual(labels[untitled["csl"]["id"]], title[:31] + "…")
        self.assertEqual({k: v for k, v in cit[-1].items() if k != "csl"},
                         {"key": "zeeman2010", "label": "Zeeman 2010", "title": "Zee", "board": None, "id": None})
        self.assertEqual([c["title"] for c in self.r.citable(None)], ["Shared copy"])
        # "in the book" says what use would do: sources.json's vandijk1998 is another work (no author, no year), so
        # this one would be added under the next key
        in_book = {s["csl"]["id"]: s["in_book"] for s in self.r.read(self.book)["items"]}
        self.assertEqual((in_book["vandijk1998"], in_book[two["csl"]["id"]]), (False, False))
        self.assertNotIn("in_book", self.r.read(None)["items"][0])
        # a new source's key avoids every key in reach, the shared board's and the book's sources too, unless it is
        # the same work: then it takes that one's key
        self.assertEqual(self.source(self.book, [{"family": "Zeeman"}], 2010)["csl"]["id"], "zeeman2010b")
        self.assertEqual(self.source(self.book, [{"family": "Zeeman"}], 2010, title="Zee")["csl"]["id"], "zeeman2010")
        self.assertEqual(self.source(None, [{"family": "Zeeman"}], 2010, title="Kind")["csl"]["id"], "zeeman2010")

    def test_search(self):
        self.r.add(None, {"type": "note", "title": "Één brief", "text": "Over de zee."})
        self.r.add(None, {"type": "note", "title": "Tagged", "tags": ["Winterreis"]})
        body = " ".join(["woord"] * 30) + " ijsvogel " + " ".join(["woord"] * 30)
        self.hand(None, "clip.md", f'---\ntype: "clip"\ntitle: "A page"\nurl: "https://example.org/a"\nsite: "example.org"\n---\n{body}\n')
        self.r.add(self.book, {"type": "note", "title": "Elders", "text": "Een ijsvogel bij de sloot."})
        self.r.add(self.book, {"type": "link", "board": None, "item": "een-brief"})
        self.assertEqual([(h["id"], h["snippet"]) for h in self.r.search("EEN")], [("een-brief", "Één brief")])
        self.assertEqual([h["id"] for h in self.r.search("winterreis")], ["tagged"])
        self.assertEqual([h["id"] for h in self.r.search("example.org/a")], ["clip"])
        hit = self.r.search("IJSVOGEL")
        self.assertEqual([(h["board"], h["board_title"], h["id"], h["type"], h["title"]) for h in hit],
                         [(None, "Shared board", "clip", "clip", "A page")])
        snippet = hit[0]["snippet"]
        self.assertTrue(snippet.startswith("…") and snippet.endswith("…"), snippet)
        self.assertEqual(snippet, "…" + body[body.index("ijsvogel") - 40:body.index("ijsvogel") + 48].strip() + "…")
        every = self.r.search("ijsvogel", every=True)
        self.assertEqual([(h["board"], h["id"]) for h in every], [(None, "clip"), (self.book, "elders")])
        self.assertEqual(every[1]["board_title"], "Test Book")
        self.assertEqual(self.r.search("brief", board=self.book), [])          # links are left out
        self.assertEqual([h["board"] for h in self.r.search("brief", every=True)], [None])
        self.assertEqual(self.r.search("e"), [])
        self.assertEqual(self.r.search(" z "), [])

    def test_search_names_untitled_items(self):
        # an item without a title is found under its work's title, its piece's title, its first words or its kind
        books = Books(self.tmp / "Books")
        piece = books.new_piece(self.book, "chapter", title="De zee")
        self.r.add(self.book, {"type": "source", "csl": {"type": "book", "id": "zee1", "title": "Een boek over de zee"}})
        self.r.add(self.book, {"type": "piece", "book": self.book, "file": piece["file"], "text": "Waarom de zee hier staat."})
        self.r.add(self.book, {"type": "note", "text": "De zee was " + "heel " * 20 + "koud."})
        self.hand(self.book, "bare.md", "---\ntype: quote\ntags: [zee]\n---\n")
        hits = {h["id"]: h for h in self.r.search("zee", board=self.book)}
        self.assertEqual(hits["een-boek-over-de-zee"]["title"], "Een boek over de zee")
        self.assertEqual(hits["waarom-de-zee-hier-staat"]["title"], "De zee")
        note = next(h for k, h in hits.items() if k.startswith("de-zee-was"))
        self.assertEqual(note["title"], "De zee was" + " heel" * 10 + "…")
        self.assertEqual(hits["bare"]["title"], "Quote")
        self.assertEqual([hits[k].get("untitled", False) for k in ("een-boek-over-de-zee", "waarom-de-zee-hier-staat", note["id"], "bare")],
                         [False, False, True, True])

    def test_piece_link_summary(self):
        books = Books(self.tmp / "Books")
        piece = books.new_piece(self.book, "chapter", title="De zee")
        books.save_piece(self.book, piece["file"], md="# De zee\n\nEen twee drie vier.\n")
        other = books.create("Ander boek")["id"]
        self.r.add(self.book, {"type": "piece", "book": self.book, "file": piece["file"]})
        self.r.add(None, {"type": "piece", "title": "Mine", "book": self.book, "file": piece["file"]})
        self.r.add(None, {"type": "piece", "book": other, "file": "gone.md"})
        self.r.add(None, {"type": "piece", "book": "no-such-book", "file": "a.md"})
        meta = self.tmp / "Books" / self.book / "book.json"
        before = (meta.stat().st_mtime_ns, meta.read_bytes())
        here = self.r.read(self.book)["items"][0]
        self.assertEqual(here["piece"], {"book": self.book, "file": piece["file"], "title": "De zee", "kind": "chapter",
                                         "status": "idea", "words": 4, "missing": False, "book_title": "Test Book"})
        shared = {s["piece"]["book"]: s for s in self.r.read(None)["items"]}
        self.assertEqual((shared[self.book]["title"], shared[self.book]["piece"]["title"]), ("Mine", "De zee"))
        self.assertTrue(shared[other]["piece"]["missing"])
        self.assertEqual(shared[other]["piece"]["book_title"], "Ander boek")
        self.assertTrue(shared["no-such-book"]["piece"]["missing"])
        self.assertEqual(shared["no-such-book"]["piece"]["title"], "")
        self.assertEqual((meta.stat().st_mtime_ns, meta.read_bytes()), before)       # read, never written

    def test_use_quote_adds_source_once(self):
        books = Books(self.tmp / "Books")
        src = self.source(self.book, [{"family": "Dijk", "non-dropping-particle": "van"}], 1998)
        q = self.r.add(self.book, {"type": "quote", "text": "Het was *koud*.", "source": "vandijk1998", "locator": "p. 12"})
        out = self.r.use(self.book, self.book, q["id"])
        self.assertEqual(out["kind"], "quote")
        self.assertEqual(out["paragraphs"][0][1], {"type": "text", "marks": [{"type": "em"}], "text": "koud"})
        self.assertEqual((out["key"], out["locator"], out["added"], out["words"]), ("vandijk1998", "p. 12", True, 3))
        self.assertNotIn("warning", out)
        self.assertEqual([(s["id"], s["title"]) for s in books.sources(self.book)], [("vandijk1998", "Kind")])
        file = books.dir(self.book) / "sources.json"
        before = (file.read_bytes(), file.stat().st_mtime_ns)
        time.sleep(0.02)
        again = self.r.use(self.book, self.book, q["id"])
        self.assertEqual((again["key"], again["added"]), ("vandijk1998", False))
        self.assertEqual((file.read_bytes(), file.stat().st_mtime_ns), before)
        self.assertEqual(self.r.use(self.book, self.book, src["id"]), {"kind": "cite", "key": "vandijk1998", "added": False})
        self.assertTrue(next(s for s in self.r.read(self.book)["items"] if s["id"] == src["id"])["in_book"])
        long = self.r.add(None, {"type": "quote", "text": "One.\n\n> Two\n> *three*.\n\n## Four", "source": "vandijk1998"})
        out = self.r.use(self.book, None, long["id"])
        self.assertEqual(out["paragraphs"], [[{"type": "text", "text": "One."}], [{"type": "text", "text": "Two three."}],
                                             [{"type": "text", "text": "Four"}]])
        self.assertEqual((out["key"], out["added"]), ("vandijk1998", False))      # found in the book's sources

    def test_use_conflicting_key(self):
        books = Books(self.tmp / "Books")
        books.save_sources(self.book, [{"id": "vandijk1998", "type": "book", "title": "Something else", "issued": {"date-parts": [[1998]]}},
                                       {"id": "field-notes", "type": "manuscript", "title": "Other notes"},
                                       {"id": "page2020", "type": "webpage", "title": "Old title", "URL": "https://Example.ORG/a/"}])
        self.source(None, [{"family": "Dijk", "non-dropping-particle": "van"}], 1998)
        q = self.r.add(None, {"type": "quote", "text": "Q", "source": "vandijk1998"})
        out = self.r.use(self.book, None, q["id"])
        self.assertEqual((out["key"], out["added"]), ("vandijk1998b", True))
        entry = next(s for s in books.sources(self.book) if s["id"] == "vandijk1998b")
        self.assertEqual(entry["title"], "Kind")
        self.assertEqual((self.r.use(self.book, None, q["id"])["key"], len(books.sources(self.book))), ("vandijk1998b", 4))
        notes = self.r.add(None, {"type": "source", "csl": {"id": "field-notes", "type": "manuscript", "title": "My notes"}})
        self.assertEqual(self.r.use(self.book, None, notes["id"]), {"kind": "cite", "key": "field-notes-2", "added": True})
        page = self.r.add(None, {"type": "source", "csl": {"id": "page2020", "type": "webpage", "title": "New title",
                                                            "URL": "https://example.org/a"}})
        self.assertEqual(self.r.use(self.book, None, page["id"]), {"kind": "cite", "key": "page2020", "added": False})
        same = self.r.add(None, {"type": "source", "csl": {"id": "vandijk1998", "type": "book", "title": "  something   ELSE",
                                                            "issued": {"date-parts": [[1998, 5]]}}})
        self.assertEqual(self.r.use(self.book, None, same["id"]), {"kind": "cite", "key": "vandijk1998", "added": False})
        self.assertEqual(len(books.sources(self.book)), 5)

    def test_use_image_and_refusals(self):
        d = self.r.board_dir(self.book)
        (d / "files").mkdir(parents=True)
        (d / "files" / "photo.png").write_bytes(b"png")
        self.hand(self.book, "photo.md", '---\ntype: "image"\ntitle: "The harbour"\nfile: "files/photo.png"\n---\n')
        out = self.r.use(self.book, self.book, "photo")
        self.assertEqual(out, {"kind": "image", "src": "../images/photo.png", "alt": "The harbour"})
        self.assertEqual((self.r.books.dir(self.book) / "images" / "photo.png").read_bytes(), b"png")
        self.r.add(self.book, {"type": "note", "title": "A note"})
        self.r.add(self.book, {"type": "piece", "book": self.book, "file": "a.md"})
        for id in ("a-note", "piece"):
            with self.assertRaises(ResearchError) as e:
                self.r.use(self.book, self.book, id)
            self.assertEqual((e.exception.code, str(e.exception)), (400, "Notes and links to pieces don't go into the text."))
        q = self.r.add(self.book, {"type": "quote", "text": "No source here."})
        out = self.r.use(self.book, self.book, q["id"])
        self.assertEqual((out["key"], out["added"], out["locator"], "warning" in out), (None, False, "", False))
        with self.assertRaises(ResearchError) as e:
            self.r.use("No Such Book", self.book, q["id"])
        self.assertEqual(e.exception.code, 404)


    # ——— Task 2, fix round 1 ———
    def test_use_same_source_without_title_or_url(self):
        books = Books(self.tmp / "Books")
        src = self.r.add(self.book, {"type": "source", "csl": {"type": "book", "author": [{"family": "Dijk"}],
                                                                "issued": {"date-parts": [[1998]]}}})
        self.assertEqual(src["csl"]["id"], "dijk1998")
        used = [self.r.use(self.book, self.book, src["id"]) for _ in range(3)]
        self.assertEqual([(u["key"], u["added"]) for u in used], [("dijk1998", True), ("dijk1998", False), ("dijk1998", False)])
        self.assertEqual([s["id"] for s in books.sources(self.book)], ["dijk1998"])
        books.save_sources(self.book, [{"id": "untitled", "type": "manuscript"}])     # the book's own entry, no title
        q = self.r.add(self.book, {"type": "quote", "text": "Q", "source": "untitled"})
        file = books.dir(self.book) / "sources.json"
        before = file.read_bytes()
        for _ in range(2):
            out = self.r.use(self.book, self.book, q["id"])
            self.assertEqual((out["key"], out["added"], "warning" in out), ("untitled", False, False))
        self.assertEqual(file.read_bytes(), before)

    def test_use_finds_the_same_source_under_another_key(self):
        books = Books(self.tmp / "Books")
        books.save_sources(self.book, [{"id": "zee-book", "type": "book", "title": "Zee", "author": [{"family": "Zeeman"}],
                                        "issued": {"date-parts": [[2010]]}}])
        src = self.source(None, [{"family": "Zeeman"}], 2010, title="Zee", key="zeeman2010")
        q = self.r.add(None, {"type": "quote", "text": "Q", "source": "zeeman2010"})
        self.assertEqual(self.r.use(self.book, None, src["id"]), {"kind": "cite", "key": "zee-book", "added": False})
        out = self.r.use(self.book, None, q["id"])
        self.assertEqual((out["key"], out["added"]), ("zee-book", False))
        self.assertEqual([s["id"] for s in books.sources(self.book)], ["zee-book"])

    def test_use_a_source_whose_title_the_book_corrected(self):
        # the same key, type, first author and year: the same work, cited as the book has it; "in the book" agrees
        books = Books(self.tmp / "Books")
        books.save_sources(self.book, [{"id": "example2001", "type": "book", "title": "The corrected title",
                                        "author": [{"family": "Éxample", "given": "An"}], "issued": {"date-parts": [[2001]]}},
                                       {"id": "zee-book", "type": "book", "title": "Zee", "issued": {"date-parts": [[2010]]}}])
        file = books.dir(self.book) / "sources.json"
        before = file.read_bytes()
        same = self.source(self.book, [{"family": "Example", "given": "An"}], 2001, title="A first title", key="example2001")
        later = self.source(self.book, [{"family": "Example", "given": "An"}], 2002, title="A first title", key="example2002")
        other = self.r.add(self.book, {"type": "source", "csl": {"id": "example2001", "type": "article-journal",
                                                                 "title": "Else", "author": [{"family": "Example"}],
                                                                 "issued": {"date-parts": [[2001]]}}})
        moved = self.r.add(self.book, {"type": "source", "csl": {"id": "zee2010", "type": "book", "title": " zee ",
                                                                 "issued": {"date-parts": [[2010]]}}})
        shown = {s["id"]: s["in_book"] for s in self.r.read(self.book)["items"]}
        self.assertEqual([shown[x["id"]] for x in (same, later, other, moved)], [True, False, False, True])
        self.assertEqual(self.r.use(self.book, self.book, same["id"]), {"kind": "cite", "key": "example2001", "added": False})
        self.assertEqual(self.r.use(self.book, self.book, moved["id"]), {"kind": "cite", "key": "zee-book", "added": False})
        self.assertEqual(file.read_bytes(), before)
        self.assertEqual(self.r.use(self.book, self.book, other["id"]), {"kind": "cite", "key": "example2001b", "added": True})
        self.assertTrue(next(s for s in self.r.read(self.book)["items"] if s["id"] == other["id"])["in_book"])
        self.assertEqual(self.r.use(self.book, self.book, other["id"]), {"kind": "cite", "key": "example2001b", "added": False})

    def test_move_that_fails_partway_keeps_items_whole(self):
        other = Books(self.tmp / "Books").create("Second Book")["id"]
        d, d2 = self.r.board_dir(self.book), self.r.board_dir(other)
        self.r.add(self.book, {"type": "note", "title": "First"})
        shared = self.r.add(None, {"type": "link", "board": self.book, "item": "first"})
        (d / "files").mkdir()
        (d / "files" / "pic.png").write_bytes(b"png")
        self.hand(self.book, "second.md", '---\ntype: "image"\nfile: "files/pic.png"\n---\n')
        self.r.layout(self.book, items={"second": {"x": 700, "y": 70}})
        real = os.replace

        def replace(src, dst, *a, **k):
            if Path(src) == d / "second.md":
                raise PermissionError("in use")
            return real(src, dst, *a, **k)
        with mock.patch("os.replace", replace):
            with self.assertRaises(PermissionError):
                self.r.move(self.book, ["first", "second"], other)
        self.assertEqual(((d2 / "first.md").is_file(), (d / "first.md").exists()), (True, False))
        self.assertIn("first", self.board_json(other)["items"])
        self.assertNotIn("first", self.board_json(self.book)["items"])
        s = next(s for s in self.r.read(None)["items"] if s["id"] == shared["id"])
        self.assertEqual((s["link"]["board"], s["link"]["item"], s["link"]["missing"]), (other, "first", False))
        self.assertEqual(((d / "second.md").is_file(), (d / "files" / "pic.png").read_bytes()), (True, b"png"))
        self.assertFalse((d2 / "second.md").exists() or (d2 / "files" / "pic.png").exists())
        self.assertEqual(self.positions(self.book)["second"]["x"], 700)

    def test_move_with_a_busy_board_warns(self):
        other = Books(self.tmp / "Books").create("Second Book")["id"]
        self.r.add(self.book, {"type": "note", "title": "First"})
        shared = self.r.add(None, {"type": "link", "board": self.book, "item": "first"})
        with self.busy(None):
            out = self.r.move(self.book, ["first"], other)
        self.assertEqual([o["id"] for o in out], ["first"])
        self.assertEqual(len(out[0]["warnings"]), 1)
        self.assertIn("Shared board", out[0]["warnings"][0])
        self.assertTrue((self.r.board_dir(other) / "first.md").is_file())
        s = next(s for s in self.r.read(None)["items"] if s["id"] == shared["id"])
        self.assertEqual((s["link"]["board"], s["link"]["missing"]), (self.book, True))
        self.assertNotIn("warnings", self.r.move(other, ["first"], self.book)[0])

    def test_update_through_a_link_on_a_busy_board(self):
        self.r.add(None, {"type": "note", "title": "Winter", "text": "Koud."})
        link = self.r.add(self.book, {"type": "link", "board": None, "item": "winter"})
        with self.busy(None):
            with self.assertRaises(ResearchError) as e:
                self.r.update(self.book, link["id"], {"text": "Vorst."})
        self.assertEqual((e.exception.code, str(e.exception), e.exception.details), (409, "The board is busy; try again.", {}))
        self.assertEqual(self.r.item(None, "winter")["text"], "Koud.\n")



def _picture(fmt, size=(40, 30)):
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", size, (200, 40, 40)).save(out, fmt)
    return out.getvalue()


class AddImageTest(unittest.TestCase):
    setUp = ResearchTest.setUp
    def test_add_image_checks_bytes(self):
        with self.assertRaises(ResearchError) as e:
            self.r.add_image(None, "photo.JPG", _picture("PNG"))
        self.assertEqual((e.exception.code, str(e.exception)), (400, "Images are .jpg, .jpeg, .png, .gif or .webp."))
        with self.assertRaises(ResearchError):
            self.r.add_image(None, "notes.txt", _picture("PNG"))
        with self.assertRaises(ResearchError):
            self.r.add_image(None, "photo.png", b"")
        jpeg = _picture("JPEG")
        a = self.r.add_image(self.book, "photo.JPG", jpeg)
        b = self.r.add_image(self.book, "PHOTO.jpg", jpeg)
        self.assertEqual((a["type"], a["file"], a["title"]), ("image", "files/photo.JPG", "photo"))
        self.assertEqual(b["file"], "files/PHOTO-2.jpg")
        files = sorted(p.name for p in (self.r.board_dir(self.book) / "files").iterdir())
        self.assertEqual(files, ["PHOTO-2.jpg", "photo.JPG"])

    def test_add_image_summary_thumb_and_placement(self):
        item = self.r.add_image(None, "con.png", _picture("PNG"), fields={"title": "Pier", "tags": ["sea"]},
                                at={"x": 5, "y": 6})
        self.assertEqual(item["file"], "files/con-1.png")
        self.assertEqual(item["title"], "Pier")
        self.assertEqual(item["tags"], ["sea"])
        read = self.r.read(None)
        s = read["items"][0]
        ns = (self.r.board_dir(None) / "files" / "con-1.png").stat().st_mtime_ns
        self.assertEqual(s["thumb"], f"/researchfiles/_shared/con-1.png?w=640&v={ns}")
        self.assertEqual((s["pos"]["x"], s["pos"]["y"]), (5, 6))


ARTICLE = ROOT / "tests" / "fixtures" / "clip" / "article.html"
ARTICLE_URL = "https://example.org/2025/03/lighthouse-year"


class ClipStoreTest(unittest.TestCase):
    """Research.clip with the network taken out: `fetch` and `shoot` are injected."""
    setUp = ResearchTest.setUp

    def fetcher(self, ctype, data, charset=None, final=None):
        """A fake fetch answering every address with `data`; checks no board lock is held while it runs."""
        def fetch(url):
            self.assertEqual(research._HELD, {})
            self.asked.append(url)
            return clip.Fetched(url, final or url, 200, ctype, charset, data)
        self.asked = []
        return fetch

    def shooter(self, why=""):
        """A fake picture: a JPEG at `out`, or (None, why) when `why` is given."""
        def shoot(html, url, out):
            self.assertEqual(research._HELD, {})
            self.shot_urls.append(url)
            if why:
                return None, why
            out.write_bytes(_picture("JPEG"))
            return out, ""
        self.shot_urls = []
        return shoot

    def test_clip_with_injected_fetch_and_shoot(self):
        html = ARTICLE.read_bytes()
        item = self.r.clip(self.book, "example.org/2025/03/lighthouse-year", at={"x": 7, "y": 8},
                           fetch=self.fetcher("text/html", html, "utf-8"), shoot=self.shooter())
        self.assertEqual(self.asked, [ARTICLE_URL])                 # https:// added
        self.assertEqual(self.shot_urls, [ARTICLE_URL])
        self.assertEqual((item["type"], item["id"], item["title"]), ("clip", "the-lighthouse-keepers-year",
                                                                     "The Lighthouse Keeper's Year"))
        self.assertEqual((item["url"], item["site"], item["author"], item["published"]),
                         (ARTICLE_URL, "Example Times", "An Example", "2025-03-04"))
        self.assertRegex(item["fetched"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertEqual(item["created"], item["fetched"])
        self.assertEqual(item["text"], clip.readable(html.decode("utf-8"), ARTICLE_URL)["markdown"] + "\n")
        self.assertEqual(item["shot"], "files/the-lighthouse-keepers-year.jpg")
        self.assertTrue((self.r.board_dir(self.book) / item["shot"]).is_file())
        self.assertTrue(item["thumb"].startswith(f"/researchfiles/{quote(self.book)}/the-lighthouse-keepers-year.jpg?w=640"))
        self.assertEqual(item["csl"]["id"], "example2025")
        self.assertEqual((item["csl"]["type"], item["csl"]["URL"]), ("webpage", ARTICLE_URL))
        self.assertNotIn("warning", item)
        self.assertEqual((item["pos"]["x"], item["pos"]["y"]), (7, 8))
        self.assertIn("example2025", [c["key"] for c in self.r.citable(self.book)])
        # no picture: the clip is kept, says why, and the next key is free
        second = self.r.clip(self.book, ARTICLE_URL, fetch=self.fetcher("text/html", html, "utf-8"),
                             shoot=self.shooter("Studio found no Chrome or Edge to take the picture with."))
        self.assertEqual(second["id"], "the-lighthouse-keepers-year-2")
        self.assertNotIn("shot", second)
        self.assertNotIn("thumb", second)
        self.assertEqual(second["warning"], "Studio found no Chrome or Edge to take the picture with.")
        self.assertEqual(second["csl"]["id"], "example2025b")
        self.assertNotIn("warning", self.r.item(self.book, second["id"]))

    def test_clip_images_pdfs_and_other_types(self):
        png = _picture("PNG")
        image = self.r.clip(None, "https://example.org/img/pier%20view.png?size=2",
                            fetch=self.fetcher("image/png", png), shoot=self.shooter())
        self.assertEqual(self.shot_urls, [])
        self.assertEqual((image["type"], image["file"], image["title"]), ("image", "files/pier view.png", "pier view"))
        self.assertEqual((image["csl"]["type"], image["csl"]["URL"]), ("webpage", "https://example.org/img/pier%20view.png?size=2"))
        self.assertEqual(image["csl"]["container-title"], "example.org")
        jpeg = self.r.clip(None, "https://example.org/photo", fetch=self.fetcher("image/jpeg", _picture("JPEG")))
        self.assertEqual(jpeg["file"], "files/photo.jpg")
        pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        pdf = self.r.clip(None, "https://www.example.org/docs/Tide%20Report.pdf",
                          fetch=self.fetcher("application/pdf", pdf_bytes), shoot=self.shooter())
        self.assertEqual(self.shot_urls, [])
        self.assertEqual((pdf["type"], pdf["title"], pdf["text"], pdf["site"]), ("clip", "Tide Report", "", "example.org"))
        self.assertEqual(pdf["file"], f"files/{pdf['id']}.pdf")
        self.assertEqual((self.r.board_dir(None) / pdf["file"]).read_bytes(), pdf_bytes)
        self.assertNotIn("shot", pdf)
        self.assertNotIn("warning", pdf)
        self.assertEqual(pdf["csl"]["title"], "Tide Report")
        for ctype, data, why in (("text/plain", b"plain words", "Studio can't clip text/plain."),
                                 ("application/pdf", b"<html>not a pdf</html>", "The site's PDF couldn't be read."),
                                 ("image/png", b"not a png", "The site's image isn't a PNG, JPEG, GIF or WebP file.")):
            before = sorted(p.name for p in self.r.board_dir(None).rglob("*"))
            with self.assertRaises(clip.ClipError) as cm:
                self.r.clip(None, "https://example.org/x", fetch=self.fetcher(ctype, data), shoot=self.shooter())
            self.assertEqual((cm.exception.code, str(cm.exception)), (400, why))
            self.assertEqual(sorted(p.name for p in self.r.board_dir(None).rglob("*")), before)

    def test_clip_again_keeps_title_tags_and_key(self):
        html = ARTICLE.read_text(encoding="utf-8")
        first = self.r.clip(self.book, ARTICLE_URL, fetch=self.fetcher("text/html", html.encode()), shoot=self.shooter())
        self.r.update(self.book, first["id"], {"title": "Keeper", "tags": ["sea"]})
        quote = self.r.add(self.book, {"type": "quote", "text": "Fog.", "source": "example2025"})
        changed = html.replace("Two gulls", "Three gulls").replace("2025-03-04", "2025-03-05")
        again = self.r.clip(self.book, None, id=first["id"], fetch=self.fetcher("text/html", changed.encode()),
                            shoot=self.shooter())
        self.assertEqual(self.asked, [ARTICLE_URL])                 # the clip's own address
        self.assertEqual((again["id"], again["title"], again["tags"]), (first["id"], "Keeper", ["sea"]))
        self.assertIn("Three gulls", again["text"])
        self.assertEqual((again["published"], again["created"]), ("2025-03-05", first["created"]))
        self.assertEqual(again["csl"]["id"], "example2025")          # quotes keep citing it
        self.assertEqual(again["csl"]["issued"], {"date-parts": [[2025, 3, 5]]})
        self.assertEqual(again["shot"], first["shot"])
        self.assertEqual(len(self.r.read(self.book)["items"]), 2)
        self.assertEqual(self.r.item(self.book, quote["id"])["source_label"], "Example 2025")
        # a new picture that can't be taken keeps the old one, and says so
        kept = self.r.clip(self.book, None, id=first["id"], fetch=self.fetcher("text/html", html.encode()),
                           shoot=self.shooter("The picture couldn't be taken."))
        self.assertEqual((kept["shot"], kept["warning"]), (first["shot"], "The picture couldn't be taken."))
        # a link stands for its original (the board shows a link to a clip as that clip)
        link = self.r.add(None, {"type": "link", "board": self.book, "item": first["id"]})
        via = self.r.clip(None, None, id=link["id"], fetch=self.fetcher("text/html", changed.replace("Three", "Four").encode()),
                          shoot=self.shooter())
        self.assertEqual((via["id"], via["type"], via["link"]["item"]), (link["id"], "clip", first["id"]))
        self.assertIn("Four gulls", self.r.item(self.book, first["id"])["text"])
        self.assertEqual(self.r.item(self.book, first["id"])["csl"]["id"], "example2025")
        self.assertEqual(len(self.r.read(None)["items"]), 1)
        with self.assertRaises(ResearchError) as cm:
            self.r.clip(self.book, None, id=quote["id"], fetch=self.fetcher("text/html", html.encode()))
        self.assertEqual(str(cm.exception), "Only clips can be clipped again.")
        with self.assertRaises(ResearchError) as cm:
            self.r.clip(self.book, None, id="nothing", fetch=self.fetcher("text/html", html.encode()))
        self.assertEqual(cm.exception.code, 404)

    def test_clip_checks_before_fetching_and_leaves_no_half_item(self):
        fetch = self.fetcher("text/html", ARTICLE.read_bytes())
        for board, kw, code in (("nobook", {}, 404), (self.book, {"frame": "f-none"}, 400),
                                (self.book, {"at": {"x": "left"}}, 400)):
            with self.assertRaises(ResearchError) as cm:
                self.r.clip(board, ARTICLE_URL, fetch=fetch, shoot=self.shooter(), **kw)
            self.assertEqual(cm.exception.code, code)
        with self.assertRaises(clip.ClipError):
            self.r.clip(self.book, "  ", fetch=fetch)
        self.assertEqual(self.asked, [])
        d = self.r.board_dir(self.book)
        with mock.patch.object(research, "write_text", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.r.clip(self.book, ARTICLE_URL, fetch=fetch, shoot=self.shooter())
        self.assertEqual([p.name for p in d.rglob("*") if p.is_file() and p.name != ".lock"], [])

    def test_clip_again_leaves_other_items_files_alone(self):
        """A hand-edited `shot` or `file` naming another item's file: clipping again neither writes over it nor
        deletes it; the clip gets a file of its own (<id>.jpg, <id>-2.jpg …)."""
        html = ARTICLE.read_bytes()
        pier = self.r.add_image(self.book, "pier.jpg", _picture("JPEG"))
        report = self.r.clip(self.book, "https://example.org/report.pdf", fetch=self.fetcher("application/pdf", b"%PDF-1.4\n"))
        page = self.r.clip(self.book, ARTICLE_URL, fetch=self.fetcher("text/html", html), shoot=self.shooter())
        d = self.r.board_dir(self.book)
        theirs = {name: (d / "files" / name).read_bytes() for name in ("pier.jpg", f"{report['id']}.pdf")}
        p = d / f"{page['id']}.md"
        fields, body, _ = frontmatter.parse(p.read_text(encoding="utf-8"))
        fields["shot"], fields["file"] = "files/pier.jpg", f"files/{report['id']}.pdf"
        p.write_text(frontmatter.dump(fields, body), encoding="utf-8")
        again = self.r.clip(self.book, None, id=page["id"], fetch=self.fetcher("text/html", html), shoot=self.shooter())
        self.assertEqual(again["shot"], f"files/{page['id']}-2.jpg")     # a name of its own (<id>.jpg is taken)
        self.assertNotIn("file", again)
        for name, data in theirs.items():                                # pier.jpg not written over, the PDF not deleted
            self.assertEqual((d / "files" / name).read_bytes(), data, name)
        self.assertEqual(self.r.item(self.book, pier["id"])["file"], "files/pier.jpg")
        # a name of its own (<id>-n.jpg) is used again
        before = sorted(x.name for x in (d / "files").iterdir())
        self.assertEqual(self.r.clip(self.book, None, id=page["id"], fetch=self.fetcher("text/html", html),
                                     shoot=self.shooter())["shot"], f"files/{page['id']}-2.jpg")
        self.assertEqual(sorted(x.name for x in (d / "files").iterdir()), before)

    def test_excerpts_are_plain_text(self):
        note = self.r.add(None, {"type": "note", "text": "A marker \\[1\\] and \\*stars\\*, **bold**, `code` and C:\\\\path\\\nnext"})
        self.assertEqual(note["excerpt"], "A marker [1] and *stars*, bold, code and C:\\path next")
        self.assertEqual(self.r.search("[1]")[0]["id"], note["id"])
        clipped = self.r.clip(None, ARTICLE_URL, fetch=self.fetcher("text/html", ARTICLE.read_bytes()), shoot=self.shooter())
        self.assertNotIn("\\", clipped["excerpt"])
        self.assertTrue(clipped["excerpt"].startswith("The Lighthouse Keeper's Year For twelve months"))

    def hand_edit(self, board, id, **fields):
        p = self.r.board_dir(board) / f"{id}.md"
        old, body, _ = frontmatter.parse(p.read_text(encoding="utf-8"))
        p.write_text(frontmatter.dump({**old, **fields}, body), encoding="utf-8")

    def test_a_name_like_mine_can_be_another_items(self):
        """<id>-2.jpg is also how the item <id>-2 names its picture: clipping <id> again never takes it."""
        html = ARTICLE.read_bytes()
        first = self.r.clip(self.book, ARTICLE_URL, fetch=self.fetcher("text/html", html), shoot=self.shooter())
        second = self.r.clip(self.book, ARTICLE_URL, fetch=self.fetcher("text/html", html), shoot=self.shooter())
        self.assertEqual((first["id"] + "-2", second["shot"]), (second["id"], f"files/{second['id']}.jpg"))
        d = self.r.board_dir(self.book)
        theirs = (d / second["shot"]).read_bytes()
        self.hand_edit(self.book, first["id"], shot=second["shot"])
        again = self.r.clip(self.book, None, id=first["id"], fetch=self.fetcher("text/html", html),
                            shoot=lambda page, url, out: (out.write_bytes(_picture("JPEG", (50, 50))), (out, ""))[1])
        self.assertNotEqual(again["shot"], second["shot"])
        self.assertNotRegex(again["shot"], rf"^files/{second['id']}(-\d+)?\.jpg$")    # nor <id>-2-n.jpg, its pattern
        self.assertEqual((d / second["shot"]).read_bytes(), theirs)

    def test_delete_and_move_leave_other_items_files(self):
        """A hand-edited `shot` or `file` naming another item's file: deleting or moving the item leaves that file."""
        html = ARTICLE.read_bytes()
        pier = self.r.add_image(self.book, "pier.jpg", _picture("JPEG"))
        d = self.r.board_dir(self.book)
        a = self.r.clip(self.book, ARTICLE_URL, fetch=self.fetcher("text/html", html), shoot=self.shooter())
        self.hand_edit(self.book, a["id"], shot="files/pier.jpg")
        self.r.delete(self.book, [a["id"]])
        self.assertTrue((d / "files" / "pier.jpg").is_file())
        self.assertFalse(any("pier.jpg" in x.name for x in (d / ".trash").iterdir()))
        b = self.r.clip(self.book, ARTICLE_URL, fetch=self.fetcher("text/html", html), shoot=self.shooter())
        self.hand_edit(self.book, b["id"], file="files/pier.jpg")
        moved = self.r.move(self.book, [b["id"]], None)[0]
        self.assertTrue((d / "files" / "pier.jpg").is_file())
        self.assertEqual(self.r.item(self.book, pier["id"])["file"], "files/pier.jpg")
        shared = self.r.board_dir(None) / "files"
        self.assertTrue((shared / Path(moved["shot"]).name).is_file())     # its own picture went with it
        self.assertFalse((shared / "pier.jpg").exists())
        # its own files still go: deleting the image moves pier.jpg to the trash
        self.r.delete(self.book, [pier["id"]])
        self.assertFalse((d / "files" / "pier.jpg").exists())


if __name__ == "__main__":
    unittest.main()
