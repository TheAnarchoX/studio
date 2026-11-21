"""Suggestions file and book lock tests. Run: python -m unittest discover tests"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from studio import books as books_module, manuscript, suggestions
from studio.books import Books, BooksError, file_lock, lock_path

ROOT = Path(__file__).resolve().parent.parent
HOLD = ("import sys, time; from pathlib import Path; from studio.books import file_lock\n"
        "with file_lock(Path(sys.argv[1])):\n    print('held', flush=True); time.sleep(float(sys.argv[2]))\n")


def entry(i, status="open", **more):
    return {"id": f"s{i}", "file": "the-pier.md", "kind": "note", "quote": "q", "status": status, **more}


class SuggestionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-sugg-"))
        self.b = Books(self.tmp / "Books")
        made = self.b.create("Harbour-Lights", "A. Writer", "en", "fiction")
        self.book = made["title"]
        self.d = self.b._dir(self.book)
        self.file = self.d / suggestions.FILE

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def holder(self, path, seconds):
        p = subprocess.Popen([sys.executable, "-c", HOLD, str(path), str(seconds)], cwd=ROOT,
                             stdout=subprocess.PIPE, text=True)
        self.addCleanup(p.stdout.close)
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        self.assertEqual(p.stdout.readline().strip(), "held")
        return p

    def test_missing_file_reads_empty(self):
        self.assertEqual(suggestions.read(self.b, self.book), {"version": 1, "suggestions": []})
        self.assertFalse(self.file.exists())

    def test_unreadable_file_is_kept(self):
        self.file.write_bytes(b"{not json")
        with self.assertRaises(BooksError) as cm:
            suggestions.read(self.b, self.book)
        self.assertEqual(cm.exception.code, 400)
        self.assertTrue(str(cm.exception).startswith("suggestions.json can't be read"))
        self.assertEqual(self.file.read_bytes(), b"{not json")

    def test_non_utf8_file_is_kept(self):
        self.file.write_bytes(b'{"suggestions": ["caf\xe9"]}')
        with self.assertRaises(BooksError) as cm:
            suggestions.read(self.b, self.book)
        self.assertEqual(cm.exception.code, 400)
        self.assertTrue(str(cm.exception).startswith("suggestions.json can't be read"))
        self.assertEqual(self.file.read_bytes(), b'{"suggestions": ["caf\xe9"]}')

    def test_locked_file_is_not_read_as_empty(self):
        self.file.write_text(json.dumps({"version": 1, "suggestions": [entry(1)]}))
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("in use")):
            with self.assertRaises(BooksError) as cm:
                suggestions.read(self.b, self.book)
        self.assertEqual(cm.exception.code, 400)
        self.assertTrue(str(cm.exception).startswith("suggestions.json can't be read"))

    def test_unknown_keys_survive_a_save(self):
        self.file.write_text(json.dumps({"version": 1, "x": 1, "suggestions": [entry(1, extra=True)]}))
        data = suggestions.read(self.b, self.book)
        suggestions._save(self.b, self.d, data)
        again = suggestions.read(self.b, self.book)
        self.assertEqual(again["x"], 1)
        self.assertIs(again["suggestions"][0]["extra"], True)

    def test_malformed_entries_are_kept_and_skipped(self):
        bad = {"id": "s2", "file": "f.md", "kind": "note", "status": "open"}
        typed = [entry(10 + i, **{k: 5}) for i, k in enumerate(("before", "after", "in", "text", "term", "source",
                                                                   "locator", "made", "decided"))]
        self.file.write_text(json.dumps({"version": 1, "suggestions": ["nonsense", bad, entry(1), *typed]}))
        data = suggestions.read(self.b, self.book)
        self.assertEqual([s["id"] for s in suggestions.entries(data)], ["s1"])
        suggestions._save(self.b, self.d, data)
        self.assertEqual(json.loads(self.file.read_text())["suggestions"][:2], ["nonsense", bad])
        self.assertEqual(len(json.loads(self.file.read_text())["suggestions"]), 3 + len(typed))

    def test_decided_are_capped(self):
        items = [entry(i, "accepted", decided=f"2026-01-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}")
                 for i in range(1003)]
        items.append(entry("open"))
        suggestions._save(self.b, self.d, {"version": 1, "suggestions": items})
        ids = [s["id"] for s in json.loads(self.file.read_text())["suggestions"]]
        self.assertEqual(len(ids), 1001)
        for gone in ("s0", "s1", "s2"):
            self.assertNotIn(gone, ids)
        self.assertIn("s3", ids)
        self.assertIn("sopen", ids)

    def test_lock_across_processes(self):
        p = self.d / ".studio" / "x.lock"
        self.holder(p, 1.0)
        t = time.monotonic()
        with file_lock(p):
            self.assertGreaterEqual(time.monotonic() - t, 0.8)
        self.assertFalse(p.exists())
        p.write_text("")
        os.utime(p, (time.time() - 60, time.time() - 60))
        t = time.monotonic()
        with file_lock(p):
            self.assertLess(time.monotonic() - t, 0.5)
        self.holder(p, 1.0)
        with self.assertRaises(BooksError) as cm:
            with file_lock(p, wait=0.2):
                pass
        self.assertEqual(cm.exception.code, 409)

    def test_lock_is_reentrant_in_one_thread(self):
        p = self.d / ".studio" / "y.lock"
        t = time.monotonic()
        with file_lock(p):
            with file_lock(p):
                self.assertTrue(p.exists())
            self.assertTrue(p.exists())
        self.assertLess(time.monotonic() - t, 0.5)
        self.assertFalse(p.exists())

    def test_save_sources_takes_the_lock(self):
        self.holder(lock_path(self.d), 1.0)
        t = time.monotonic()
        self.b.save_sources(self.book, [])
        self.assertGreaterEqual(time.monotonic() - t, 0.8)



FIXTURES = ROOT / "tests" / "fixtures"


def doc_of(md, form="prose"):
    return manuscript.parse(md, form)


def sugg(quote, **more):
    return {"quote": quote, "before": "", "after": "", **more}


class LocateTest(unittest.TestCase):
    def test_locate_fixture(self):
        cases = json.loads((FIXTURES / "suggest-locate.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 8)
        for c in cases:
            with self.subTest(c["name"]):
                got = suggestions.locate(doc_of(c["md"], c["form"]), c["s"])
                if c["want"] is None:
                    self.assertIsNone(got)
                else:
                    self.assertEqual({k: got[k] for k in ("index", "start", "end", "kind")}, c["want"])

    def test_locate_picks_by_context(self):
        text = "He said no. Then he said yes. He said no again."
        got = suggestions.locate(doc_of(text), sugg("He said no", after=" again"))
        self.assertEqual(got["start"], text.rindex("He said no"))

    def test_locate_dutch_typography(self):
        quote = "„Kom je ’t halen?”"
        got = suggestions.locate(doc_of(f"Hij riep: {quote} en ging."), sugg(quote))
        self.assertEqual((got["start"], got["end"]), (10, 10 + len(quote)))

    def test_score_and_context(self):
        self.assertEqual(suggestions.score("abcXYZQQ123", 6, 8, "zzXYZ", "123456"), 3 + 3)
        text = "x" * 40 + "WORD" + "y" * 40
        self.assertEqual(suggestions.context(text, 40, 44), ("x" * 32, "y" * 32))
        self.assertEqual(suggestions.context("ab", 0, 1), ("", "b"))


class ApplyTest(unittest.TestCase):
    def run_apply(self, md, s, sources=(), form="prose"):
        doc = doc_of(md, form)
        ok = suggestions.apply(doc, s, list(sources))
        return ok, manuscript.serialize(doc)

    def test_apply_edit_keeps_marks(self):
        ok, md = self.run_apply("*the old house*", sugg("old", kind="edit", text="new"))
        self.assertTrue(ok)
        self.assertEqual(md, "*the new house*\n")

    def test_apply_index_term_and_mark_order(self):
        ok, md = self.run_apply("A *word* here.", sugg("word", kind="index", term="t"))
        self.assertTrue(ok)
        self.assertEqual(md, 'A [*word*]{.idx term="t"} here.\n')
        self.assertEqual(manuscript.serialize(doc_of(md)), md)
        ok, md = self.run_apply("A *word* here.", sugg("word", kind="index", term="word"))
        self.assertEqual(md, "A [*word*]{.idx} here.\n")
        ok, md = self.run_apply("A *word* here.", sugg("word", kind="index"))
        self.assertEqual(md, "A [*word*]{.idx} here.\n")

    def test_apply_index_splits_inside_a_word(self):
        ok, md = self.run_apply("The harbour wall.", sugg("harbour", kind="index", term="port"))
        self.assertEqual(md, 'The [harbour]{.idx term="port"} wall.\n')

    def test_apply_index_replaces_existing_term(self):
        ok, md = self.run_apply('The [harbour]{.idx term="a"} wall.', sugg("harbour", kind="index", term="b"))
        self.assertEqual(md, 'The [harbour]{.idx term="b"} wall.\n')

    def test_apply_comment_joins_existing(self):
        ok, md = self.run_apply('See [this]{.comment note="a"} now.', sugg("this", kind="comment", text="b"))
        self.assertTrue(ok)
        self.assertEqual(md, 'See [this]{.comment note="a · b"} now.\n')
        ok, md = self.run_apply("See this now.", sugg("this", kind="comment", text="b"))
        self.assertEqual(md, 'See [this]{.comment note="b"} now.\n')

    def test_apply_note_and_cite_after_the_words(self):
        ok, md = self.run_apply("*Past* the harbour. Then home.", sugg("the harbour.", kind="note", text="text"))
        self.assertTrue(ok)
        self.assertEqual(md, "*Past* the harbour.^[text] Then home.\n")
        cite = sugg("the harbour.", kind="cite", source="key", locator="p. 3")
        ok, md = self.run_apply("*Past* the harbour. Then home.", cite, [{"id": "key"}])
        self.assertTrue(ok)
        self.assertEqual(manuscript.serialize(doc_of("*Past* the harbour.[@key, p. 3] Then home.")), md)
        self.assertIn("the harbour.[@key, p. 3] Then home.", md)

    def test_apply_note_inside_a_marked_run_keeps_the_run(self):
        for md, quote, kind, extra, form in (
                ("*Past the harbour. Then home.*", "harbour.", "note", {"text": "text"}, "prose"),
                ("*Past the harbour. Then home.*", "harbour.", "cite", {"source": "key"}, "prose"),
                ('[the harbour. Then home]{.comment note="c"}', "harbour.", "note", {"text": "text"}, "prose"),
                ("**Past *the harbour.* Then home.**", "harbour.", "note", {"text": "text"}, "prose"),
                ('[Past the harbour.\nThen home]{.comment note="c"}', "harbour.", "note", {"text": "n"}, "poem"),
                ("*Past the harbour.\nThen home.*", "harbour.", "note", {"text": "n"}, "poem"),
                ("*Past the harbour.^[a] Then home.*", "harbour.", "note", {"text": "n"}, "prose"),
                ("*Past the harbour.[@key] Then home.*", "harbour.", "note", {"text": "n"}, "prose")):
            with self.subTest(md=md, kind=kind):
                doc = doc_of(md, form)
                self.assertTrue(suggestions.apply(doc, sugg(quote, kind=kind, **extra), [{"id": "key"}]))
                out = manuscript.serialize(doc, form)
                self.assertEqual(manuscript.serialize(doc_of(out, form), form), out)
                self.assertEqual(doc_of(out, form), doc)
                self.assertEqual(out.count("{.comment"), md.count("{.comment"))
                self.assertEqual(out.count("*"), md.count("*"))

    def test_apply_refuses_changed_and_unknown_source(self):
        doc = doc_of("The harbour.")
        before = json.dumps(doc)
        self.assertFalse(suggestions.apply(doc, sugg("the quay", kind="edit", text="x"), []))
        cite = sugg("harbour", kind="cite", source="nope")
        self.assertFalse(suggestions.apply(doc, cite, [{"id": "key"}]))
        self.assertEqual(json.dumps(doc), before)



PIER = "# The Pier\n\nThe harbour wall was cold. We walked the pier at dusk.\n\nThe tide came in. The tide went out.\n"


class AddTest(unittest.TestCase):
    """Making suggestions: the checks, the stored fields, the order they list in."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-sugg-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.b = Books(self.tmp / "Books")
        self.book = self.b.create("Harbour-Lights", "A. Writer", "en", "fiction")["title"]
        self.d = self.b._dir(self.book)
        self.file = self.d / suggestions.FILE
        self.b.update(self.book, {"features": {"notes": "endnotes", "sources": True, "index": True}})
        self.b.save_sources(self.book, [{"id": "key2019", "type": "book", "title": "Harbours"}])
        self.pier = self.b.new_piece(self.book, "chapter", title="The Pier")["file"]
        self.b.save_piece(self.book, self.pier, md=PIER)
        self.path = self.d / "manuscript" / self.pier

    def item(self, quote, **more):
        return {"piece": "The Pier", "kind": "comment", "quote": quote, "text": "Check this.", **more}

    def reasons(self, *items, **kw):
        got = suggestions.add(self.b, self.book, list(items), **kw)
        return got, [r["reason"] for r in got["refused"]]

    def test_add_each_kind(self):
        before = self.path.read_bytes()
        now = suggestions.datetime(2026, 11, 13, 9, 30, 5)
        got = suggestions.add(self.b, self.book, [
            self.item("harbour wall", kind="edit", text="quay", why="Plainer."),
            self.item("was cold.", kind="note", text="Ask her."),
            self.item("pier", kind="index", term="piers"),
            self.item("We walked", kind="cite", source="key2019", locator="p. 4"),
            self.item("dusk", kind="comment", text="Too\nsoft?"),
        ], label="First pass", now=now)
        self.assertEqual(got["refused"], [])
        self.assertEqual([s["kind"] for s in got["added"]], ["edit", "note", "index", "cite", "comment"])
        self.assertRegex(got["group"], r"^g-2026-11-13T0930-[0-9a-f]{4}$")
        first = got["added"][0]
        self.assertRegex(first["id"], r"^s-[0-9a-f]{8}$")
        self.assertEqual({k: first[k] for k in ("file", "quote", "before", "after", "in", "text", "why", "group",
                                                 "label", "by", "made", "status")},
                         {"file": self.pier, "quote": "harbour wall", "before": "The ",
                          "after": " was cold. We walked the pier at", "in": "text", "text": "quay",
                          "why": "Plainer.", "group": got["group"], "label": "First pass", "by": "Claude",
                          "made": "2026-11-13T09:30:05", "status": "open"})
        self.assertEqual(len({s["id"] for s in got["added"]}), 5)
        self.assertEqual({s["group"] for s in got["added"]}, {got["group"]})
        self.assertEqual(got["added"][2]["term"], "piers")
        self.assertEqual((got["added"][3]["source"], got["added"][3]["locator"]), ("key2019", "p. 4"))
        self.assertEqual(got["added"][4]["text"], "Too soft?")
        self.assertEqual(len(suggestions.read(self.b, self.book)["suggestions"]), 5)
        self.assertEqual(self.path.read_bytes(), before)

    def test_single_item_has_no_group(self):
        got, _ = self.reasons(self.item("dusk"))
        self.assertIsNone(got["group"])
        self.assertNotIn("group", got["added"][0])
        self.assertNotIn("label", got["added"][0])

    def test_single_item_keeps_its_label(self):
        got, _ = self.reasons(self.item("harbour"), label="  Tide   words ")
        self.assertIsNone(got["group"])
        self.assertNotIn("group", got["added"][0])
        self.assertEqual(got["added"][0]["label"], "Tide words")
        self.assertEqual(suggestions.read(self.b, self.book)["suggestions"][0]["label"], "Tide words")

    def test_add_refusals(self):
        self.b.save_piece(self.book, self.pier, md=PIER.replace("dusk.", "dusk.^[A note about gulls.]"))
        cases = [
            ("unknown piece", self.item("dusk", piece="Nowhere"), "no piece Nowhere"),
            ("unknown kind", self.item("dusk", kind="praise"), "kind"),
            ("empty quote", self.item(""), "quote"),
            ("not found", self.item("the quay"), "Quote the words exactly as they read"),
            ("several", self.item("The tide"), "occurs 2 times"),
            ("same edit", self.item("dusk", kind="edit", text="dusk"), "different"),
            ("note without text", self.item("dusk", kind="note", text=" "), "text"),
            ("unknown source", self.item("dusk", kind="cite", source="nope"), "nope"),
            ("long term", self.item("dusk", kind="index", term="t" * 201), "200"),
            ("note in a note", self.item("gulls", kind="note", text="x"), "note"),
        ]
        for name, it, word in cases:
            with self.subTest(name):
                got, reasons = self.reasons(it, self.item("harbour", text=name))
                self.assertEqual([r["item"] for r in got["refused"]], [1])
                self.assertIn(word, reasons[0])
                self.assertEqual(len(got["added"]), 1)
        got, reasons = self.reasons(self.item("not there"))
        self.assertIn(self.pier, reasons[0])

    def test_edit_inside_a_note(self):
        self.b.save_piece(self.book, self.pier, md=PIER.replace("dusk.", "dusk.^[A note about gulls.]"))
        got, _ = self.reasons(self.item("gulls", kind="edit", text="terns"))
        self.assertEqual(got["added"][0]["in"], "note")

    def test_only_edits_go_inside_a_note(self):
        self.b.save_piece(self.book, self.pier, md=PIER.replace("dusk.", "dusk.^[A note about gulls.]"))
        for kind, extra in (("index", {}), ("comment", {"text": "x"}), ("note", {"text": "x"}),
                            ("cite", {"source": "key2019"})):
            with self.subTest(kind):
                got, reasons = self.reasons(self.item("gulls", kind=kind, **extra))
                self.assertEqual(got["added"], [])
                self.assertIn("inside a note", reasons[0])

    def test_malformed_values_refuse_only_their_item(self):
        for bad in (["key2019"], {"a": 1}, None, 5):
            with self.subTest(source=bad):
                got, reasons = self.reasons(self.item("dusk", kind="cite", source=bad), self.item("harbour", text=repr(bad)))
                self.assertEqual(len(got["added"]), 1)
                self.assertIn("no source", reasons[0])

    def test_hand_edited_file_does_not_break_add(self):
        data = {"version": 1, "suggestions": [entry(1, text=["x"], term={"a": 1}, id=["s1"]), entry(2, id={"x": 1})]}
        self.file.write_text(json.dumps(data), encoding="utf-8")
        self.b.save_sources(self.book, [{"id": "key2019", "type": "book"}])
        raw = json.loads((self.d / "sources.json").read_text(encoding="utf-8"))
        raw += [{"id": ["a"], "type": "book"}, {"type": "book"}]
        (self.d / "sources.json").write_text(json.dumps(raw), encoding="utf-8")
        got, reasons = self.reasons(self.item("dusk"), self.item("harbour", kind="cite"))
        self.assertEqual(len(got["added"]), 1)
        self.assertIn("no source", reasons[0])
        self.assertNotIn("source", got["added"][0])

    def test_unreadable_sources_refuse_only_citations(self):
        (self.d / "sources.json").write_text("{broken", encoding="utf-8")
        got, reasons = self.reasons(self.item("dusk", kind="edit", text="evening"),
                                    self.item("harbour", kind="cite", source="key2019"))
        self.assertEqual(len(got["added"]), 1)
        self.assertIn("sources.json", reasons[0])

    def test_not_found_hints(self):
        got, reasons = self.reasons(self.item("*dusk*"))
        self.assertIn("Couldn't find \"*dusk*\" in the-pier.md. Quote the words exactly as they read, without Markdown "
                      "(no `*`, `^[…]` or `[@…]`)", reasons[0])
        self.assertIn("no-break spaces and curly quotes („…”, ‘…’, ’)", reasons[0])
        self.b.save_piece(self.book, self.pier, md=PIER + "\n![A grey lighthouse](x.png)\n")
        got, reasons = self.reasons(self.item("lighthouse"))
        self.assertIn("caption", reasons[0])
        self.assertNotIn("inside a note", reasons[0])

    def test_unreadable_piece_refuses_its_item(self):
        def flaky(book, file):
            raise OSError("disk went away")
        self.b.piece = flaky
        got, reasons = self.reasons(self.item("dusk"))
        self.assertIn("can't be read", reasons[0])

    def test_line_breaks_in_note_and_edit_text(self):
        got, _ = self.reasons(self.item("dusk", kind="note", text="One\n\nTwo"),
                              self.item("harbour", kind="edit", text="quay\r\nwall"))
        self.assertEqual([s["text"] for s in got["added"]], ["One Two", "quay wall"])

    def test_book_id_blank(self):
        for name in ("", "  ", None):
            with self.assertRaises(BooksError) as cm:
                self.b.book_id(name)
            self.assertEqual((cm.exception.code, str(cm.exception)), (404, "Say which book."))

    def test_add_features_off(self):
        self.b.update(self.book, {"features": {"notes": "off", "sources": False, "index": "first-lines"}})
        for kind, extra, word in (("index", {}, "index"), ("cite", {"source": "key2019"}, "sources"),
                                  ("note", {"text": "x"}, "notes")):
            with self.subTest(kind):
                got, reasons = self.reasons(self.item("dusk", kind=kind, **extra), self.item("harbour", text=kind))
                self.assertIn(word, reasons[0])
                self.assertEqual(len(got["added"]), 1)

    def test_context_picks_among_several(self):
        got, reasons = self.reasons(self.item("The tide", after=" went"), self.item("The tide", before="zzz"),
                                    self.item("The tide", before="in. ", after=" went out."))
        self.assertEqual(len(got["added"]), 1)
        self.assertTrue(got["added"][0]["before"].endswith("in. "))
        self.assertEqual([r["item"] for r in got["refused"]], [2, 3])
        self.assertIn("already waiting", reasons[1])

    def test_own_context_needs_no_space_at_the_join(self):
        text = "He said no. Then he said yes. And he said nothing."
        other = self.b.new_piece(self.book, "chapter", title="Said")["file"]
        self.b.save_piece(self.book, other, md=f"# Said\n\n{text}\n")
        said = {"piece": other, "kind": "comment", "quote": "he said"}
        got, reasons = self.reasons({**said, "before": "Then", "text": "a"}, {**said, "after": "nothing", "text": "b"},
                                    {**said, "before": " ", "text": "c"})
        self.assertEqual([s["text"] for s in got["added"]], ["a", "b"])
        at = [text.index("he said"), text.rindex("he said")]
        self.assertEqual([(s["before"], s["after"]) for s in got["added"]],
                         [suggestions.context(text, i, i + len("he said")) for i in at])
        self.assertIn("add `before` or `after`", reasons[0])
        doc = self.b.piece(self.book, other)["doc"]
        self.assertEqual([suggestions.locate(doc, s)["start"] for s in got["added"]], at)

    def test_add_duplicates_and_rejected(self):
        got, _ = self.reasons(self.item("dusk"))
        first = got["added"][0]
        got, reasons = self.reasons(self.item("dusk"))
        self.assertEqual(got["added"], [])
        self.assertIn(f"already waiting as {first['id']}", reasons[0])
        data = suggestions.read(self.b, self.book)
        data["suggestions"][0].update(status="rejected", decided="2026-11-13T10:00:00")
        self.file.write_text(json.dumps(data), encoding="utf-8")
        got, reasons = self.reasons(self.item("dusk"))
        self.assertIn("the author rejected this on 13 Nov 2026", reasons[0])

    def test_add_too_many(self):
        with self.assertRaises(BooksError) as cm:
            suggestions.add(self.b, self.book, [self.item("dusk")] * 201)
        self.assertEqual(cm.exception.code, 400)
        self.assertFalse(self.file.exists())

    def test_add_stops_at_the_open_limit(self):
        data = {"version": 1, "suggestions": [entry(i) for i in range(suggestions.MAX_OPEN - 1)]}
        self.file.write_text(json.dumps(data), encoding="utf-8")
        got, reasons = self.reasons(self.item("dusk"), self.item("harbour"))
        self.assertEqual(len(got["added"]), 1)
        self.assertIn("the book has 1000 suggestions waiting", reasons[0])

    def test_nothing_written_when_all_refused(self):
        self.reasons(self.item("nope"))
        self.assertFalse(self.file.exists())

    def test_piece_by_title_and_stem(self):
        for name in ("The Pier", "the pier", "the-pier", "the-pier.md", "THE-PIER.MD"):
            self.assertEqual(self.b.find_piece(self.book, name), "the-pier.md")
        with self.assertRaises(BooksError) as cm:
            self.b.find_piece(self.book, "Elsewhere")
        self.assertEqual((cm.exception.code, str(cm.exception)), (404, "There's no piece Elsewhere in this book."))
        a = self.b.new_piece(self.book, "chapter", title="Same")["file"]
        c = self.b.new_piece(self.book, "chapter", title="Same")["file"]
        with self.assertRaises(BooksError) as cm:
            self.b.find_piece(self.book, "Same")
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(str(cm.exception), f"Same is the title of {a} and {c}: name the file.")
        self.assertEqual(self.b.find_piece(self.book, c), c)

    def test_book_id(self):
        self.assertEqual(self.b.book_id("harbour-lights"), self.d.name)
        self.assertEqual(self.b.book_id(self.d.name), self.d.name)
        with self.assertRaises(BooksError) as cm:
            self.b.book_id("Nope")
        self.assertEqual(cm.exception.code, 404)

    def test_listing_order_and_found(self):
        two = self.b.new_piece(self.book, "chapter", title="Second")["file"]
        self.b.save_piece(self.book, two, md="# Second\n\nA lantern burned.\n")
        suggestions.add(self.b, self.book, [{"piece": two, "kind": "comment", "quote": "lantern", "text": "a"}])
        suggestions.add(self.b, self.book, [self.item("tide went"), self.item("harbour")])
        got = suggestions.listing(self.b, self.book)
        self.assertEqual([(s["file"], s["quote"]) for s in got],
                         [(self.pier, "harbour"), (self.pier, "tide went"), (two, "lantern")])
        self.assertEqual([s["piece"] for s in got], ["The Pier", "The Pier", "Second"])
        self.assertTrue(all(s["found"] and not s["missing"] for s in got))
        self.assertEqual([s["index"] for s in got], [0, 0, 0])
        self.assertEqual([s["quote"] for s in suggestions.listing(self.b, self.book, file=two)], ["lantern"])
        self.b.save_piece(self.book, self.pier, md=PIER.replace("harbour", "quay"))
        got = suggestions.listing(self.b, self.book)
        self.assertEqual([(s["quote"], s["found"]) for s in got],
                         [("tide went", True), ("harbour", False), ("lantern", True)])
        self.assertIsNone(got[1]["index"])
        self.b.delete_piece(self.book, two)
        got = suggestions.listing(self.b, self.book, file=two)
        self.assertEqual((got[0]["missing"], got[0]["found"], got[0]["piece"]), (True, False, ""))

    def test_wrongly_typed_entry_is_skipped_by_the_list(self):
        got, _ = self.reasons(self.item("dusk"))
        a = got["added"][0]["id"]
        data = suggestions.read(self.b, self.book)
        bad = {**entry(9), "quote": "The tide", "before": 5}          # a hand edit; "The tide" occurs twice
        data["suggestions"].append(bad)
        self.file.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual([s["id"] for s in suggestions.listing(self.b, self.book)], [a])
        self.assertEqual(suggestions.decide(self.b, self.book, [a, "s9"], "reject")["unknown"], ["s9"])
        self.assertIn(bad, json.loads(self.file.read_text(encoding="utf-8"))["suggestions"])

    def test_listing_status_filters(self):
        suggestions.add(self.b, self.book, [self.item("dusk"), self.item("harbour"), self.item("cold")])
        data = suggestions.read(self.b, self.book)
        data["suggestions"][0].update(status="accepted", decided="2026-11-12T10:00:00")
        data["suggestions"][1].update(status="rejected", decided="2026-11-13T10:00:00")
        self.file.write_text(json.dumps(data), encoding="utf-8")

        def quotes(status):
            return [s["quote"] for s in suggestions.listing(self.b, self.book, status=status)]
        self.assertEqual(quotes("open"), ["cold"])
        self.assertEqual(quotes("decided"), ["harbour", "dusk"])
        self.assertEqual(sorted(quotes("all")), ["cold", "dusk", "harbour"])
        with self.assertRaises(BooksError):
            quotes("bogus")

    def test_summary_in_read(self):
        self.assertEqual(self.b.read(self.book)["suggestions"], {"open": 0, "any": False})
        suggestions.add(self.b, self.book, [self.item("dusk"), self.item("harbour")])
        self.assertEqual(self.b.read(self.book)["suggestions"], {"open": 2, "any": True})
        self.file.write_bytes(b"{broken")
        got = self.b.read(self.book)["suggestions"]
        self.assertEqual((got["open"], got["any"]), (0, True))
        self.assertIn("can't be read", got["error"])


class DecideTest(unittest.TestCase):
    """Deciding: the only place an accepted suggestion changes a piece."""
    setUp = AddTest.setUp
    item = AddTest.item

    def make(self, *items, file=None):
        got = suggestions.add(self.b, self.book, list(items))
        self.assertEqual(got["refused"], [])
        return [s["id"] for s in got["added"]]

    def status(self):
        return {s["id"]: s for s in suggestions.read(self.b, self.book)["suggestions"]}

    def test_accept_writes_once_with_a_snapshot(self):
        ids = self.make(self.item("harbour wall", kind="edit", text="quay"),
                        self.item("pier", kind="index", term="piers"),
                        self.item("was cold.", kind="note", text="Ask her."))
        self.path.write_text(PIER + "\nA last line.\n", encoding="utf-8")     # typed since the last snapshot
        before = self.path.read_text(encoding="utf-8")
        shots = len(self.b.history(self.book, self.pier))
        real, writes = suggestions.write_text, []

        def counting(path, text):
            writes.append(Path(path))
            return real(path, text)
        with mock.patch.object(suggestions, "write_text", counting), \
                mock.patch.object(books_module, "write_text", counting):
            got = suggestions.decide(self.b, self.book, ids, "accept")
        self.assertEqual(got["accepted"], ids)
        self.assertEqual([got[k] for k in ("rejected", "reopened", "withdrawn", "changed", "unknown")], [[]] * 5)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("The quay was cold.^[Ask her.]", text)
        self.assertIn("[pier]{.idx term=\"piers\"}", text)
        self.assertEqual(writes.count(self.path), 1)
        history = self.b.history(self.book, self.pier)
        self.assertEqual(len(history), shots + 1)
        snap = self.d / "drafts" / Path(self.pier).stem / f"{history[0]['when']}.md"
        self.assertEqual(snap.read_text(encoding="utf-8"), before)
        data = self.status()
        for i in ids:
            self.assertEqual(data[i]["status"], "accepted")
            self.assertRegex(data[i]["decided"], r"^\d{4}-\d\d-\d\dT")

    def test_accept_reports_changed(self):
        a, b = self.make(self.item("dusk", kind="comment", text="soft"),
                         self.item("harbour wall", kind="edit", text="quay"))
        self.b.save_piece(self.book, self.pier, md=PIER.replace("dusk", "night"))
        got = suggestions.decide(self.b, self.book, [a, b], "accept")
        self.assertEqual((got["accepted"], got["changed"]), ([b], [a]))
        self.assertEqual(self.status()[a]["status"], "open")
        x, y = self.make(self.item("tide came", kind="edit", text="water rose"),
                         self.item("came in", kind="comment", text="c"))
        got = suggestions.decide(self.b, self.book, [x, y], "accept")
        self.assertEqual((got["accepted"], got["changed"]), ([x], [y]))
        self.assertEqual(self.status()[y]["status"], "open")

    def test_accept_missing_piece_is_changed(self):
        two = self.b.new_piece(self.book, "chapter", title="Second")["file"]
        self.b.save_piece(self.book, two, md="# Second\n\nA lantern burned.\n")
        a, = self.make({"piece": two, "kind": "comment", "quote": "lantern", "text": "a"})
        (self.d / "manuscript" / two).unlink()
        got = suggestions.decide(self.b, self.book, [a], "accept")
        self.assertEqual((got["accepted"], got["changed"]), ([], [a]))

    def test_unstable_round_trip_is_not_written(self):
        a, b = self.make(self.item("dusk", kind="comment", text="soft"),
                         self.item("harbour wall", kind="edit", text="quay"))
        before = self.path.read_bytes()
        real, calls = manuscript.parse, []

        def unstable(md, form="prose"):
            calls.append(md)
            return real(md if len(calls) == 1 else md + "\n\nextra", form)     # the parse-back differs
        with mock.patch.object(manuscript, "parse", unstable):
            got = suggestions.decide(self.b, self.book, [a, b], "accept")
        self.assertEqual((got["accepted"], sorted(got["changed"])), ([], sorted([a, b])))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.status()[a]["status"], "open")

    def test_reject_reopen_withdraw(self):
        a, b, c = self.make(self.item("dusk"), self.item("harbour"), self.item("cold"))
        got = suggestions.decide(self.b, self.book, [a, "nope"], "reject")
        self.assertEqual((got["rejected"], got["unknown"]), ([a], ["nope"]))
        self.assertIn("decided", self.status()[a])
        got = suggestions.decide(self.b, self.book, [a], "reopen")
        self.assertEqual(got["reopened"], [a])
        self.assertEqual(self.status()[a]["status"], "open")
        self.assertNotIn("decided", self.status()[a])
        got = suggestions.decide(self.b, self.book, [b], "withdraw")
        self.assertEqual(got["withdrawn"], [b])
        self.assertEqual(self.status()[b]["status"], "withdrawn")
        self.assertIn("decided", self.status()[b])
        suggestions.decide(self.b, self.book, [a], "reject")
        got = suggestions.decide(self.b, self.book, [a], "withdraw")
        self.assertEqual((got["withdrawn"], got["unknown"]), ([], [a]))
        got = suggestions.decide(self.b, self.book, [a, b], "reopen")      # rejected and withdrawn come back
        self.assertEqual(got["reopened"], [a, b])
        suggestions.decide(self.b, self.book, [c], "accept")
        got = suggestions.decide(self.b, self.book, [c], "reopen")
        self.assertEqual((got["reopened"], got["unknown"]), ([], [c]))
        self.assertEqual(self.status()[c]["status"], "accepted")
        got = suggestions.decide(self.b, self.book, [c], "accept")          # already decided
        self.assertEqual((got["accepted"], got["unknown"]), ([], [c]))

    def test_accept_across_pieces(self):
        two = self.b.new_piece(self.book, "chapter", title="Second")["file"]
        self.b.save_piece(self.book, two, md="# Second\n\nA lantern burned.\n")
        a, b = self.make(self.item("dusk", kind="edit", text="night"),
                         {"piece": two, "kind": "edit", "quote": "lantern", "text": "candle"})
        before = {}
        for f in (self.pier, two):          # typed since the last snapshot
            p = self.d / "manuscript" / f
            p.write_text(p.read_text(encoding="utf-8") + "\nA last line.\n", encoding="utf-8")
            before[f] = p.read_text(encoding="utf-8")
        shots = {f: len(self.b.history(self.book, f)) for f in before}
        got = suggestions.decide(self.b, self.book, [b, a], "accept")
        self.assertEqual(sorted(got["accepted"]), sorted([a, b]))
        self.assertIn("night.", self.path.read_text(encoding="utf-8"))
        self.assertIn("candle", (self.d / "manuscript" / two).read_text(encoding="utf-8"))
        for f in before:
            history = self.b.history(self.book, f)
            self.assertEqual(len(history), shots[f] + 1)
            snap = self.d / "drafts" / Path(f).stem / f"{history[0]['when']}.md"
            self.assertEqual(snap.read_text(encoding="utf-8"), before[f])

    def test_non_utf8_piece_is_changed(self):
        a, = self.make(self.item("dusk", kind="edit", text="night"))
        self.path.write_bytes(b"The caf\xe9 at dusk.\n")
        got = suggestions.decide(self.b, self.book, [a], "accept")
        self.assertEqual((got["accepted"], got["changed"]), ([], [a]))
        self.assertEqual(self.path.read_bytes(), b"The caf\xe9 at dusk.\n")
        self.assertEqual(self.status()[a]["status"], "open")

    def test_cite_whose_source_left_is_changed(self):
        a, b = self.make(self.item("dusk", kind="cite", source="key2019"),
                         self.item("harbour wall", kind="edit", text="quay"))
        self.b.save_sources(self.book, [])
        got = suggestions.decide(self.b, self.book, [a, b], "accept")
        self.assertEqual((got["accepted"], got["changed"]), ([b], [a]))
        self.assertEqual(self.status()[a]["status"], "open")

    def test_unreadable_sources_only_stop_citations(self):
        a, b = self.make(self.item("dusk", kind="cite", source="key2019"),
                         self.item("harbour wall", kind="edit", text="quay"))
        (self.d / "sources.json").write_text("{broken", encoding="utf-8")
        got = suggestions.decide(self.b, self.book, [a, b], "accept")
        self.assertEqual((got["accepted"], got["changed"]), ([b], [a]))

    def test_failed_write_keeps_earlier_pieces_decided(self):
        two = self.b.new_piece(self.book, "chapter", title="Second")["file"]
        self.b.save_piece(self.book, two, md="# Second\n\nA lantern burned.\n")
        a, b = self.make(self.item("dusk", kind="note", text="n"),
                         {"piece": two, "kind": "edit", "quote": "lantern", "text": "candle"})
        real = suggestions.write_text

        def failing(path, text):
            if Path(path).name == two:
                raise OSError("disk full")
            return real(path, text)
        with mock.patch.object(suggestions, "write_text", failing):
            got = suggestions.decide(self.b, self.book, [a, b], "accept")
        self.assertEqual((got["accepted"], got["changed"]), ([a], [b]))
        self.assertEqual(self.status()[a]["status"], "accepted")
        self.assertEqual(self.status()[b]["status"], "open")

    def test_unreadable_snapshot_stops_only_its_piece(self):
        two = self.b.new_piece(self.book, "chapter", title="Second")["file"]
        self.b.save_piece(self.book, two, md="# Second\n\nA lantern burned.\n")
        a, b = self.make(self.item("dusk", kind="note", text="n"),
                         {"piece": two, "kind": "edit", "quote": "lantern", "text": "candle"})
        shots = self.d / "drafts" / Path(two).stem
        shots.mkdir(parents=True, exist_ok=True)
        (shots / "2099-01-01T0000.md").write_bytes(b"The caf\xe9.\n")      # the newest snapshot isn't UTF-8
        before = (self.d / "manuscript" / two).read_bytes()
        got = suggestions.decide(self.b, self.book, [a, b], "accept")
        self.assertEqual((got["accepted"], got["changed"]), ([a], [b]))
        self.assertEqual((self.status()[a]["status"], self.status()[b]["status"]), ("accepted", "open"))
        self.assertEqual((self.d / "manuscript" / two).read_bytes(), before)
        self.assertIn("dusk^[n].", self.path.read_text(encoding="utf-8"))

    def test_lock_that_will_not_go_keeps_the_decision(self):
        a, = self.make(self.item("dusk"))
        real = Path.unlink

        def stuck(path, *args, **kw):
            if path.name == "books.lock":
                raise PermissionError("in use")
            return real(path, *args, **kw)
        with mock.patch.object(Path, "unlink", stuck):
            got = suggestions.decide(self.b, self.book, [a], "reject")
        self.assertEqual(got["rejected"], [a])
        self.assertEqual(self.status()[a]["status"], "rejected")
        self.assertTrue(lock_path(self.d).exists())         # left behind: it goes stale after 30 s

    def test_bring_back_never_makes_a_twin(self):
        a, = self.make(self.item("dusk", kind="note", text="Really?"))
        suggestions.decide(self.b, self.book, [a], "withdraw")
        b, = self.make(self.item("dusk", kind="note", text="Really?"))       # the same again: allowed
        got = suggestions.decide(self.b, self.book, [a], "reopen")
        self.assertEqual((got["reopened"], got["unknown"]), ([], [a]))
        self.assertEqual(self.status()[a]["status"], "withdrawn")
        got = suggestions.decide(self.b, self.book, [a, b], "accept")
        self.assertEqual((got["accepted"], got["unknown"]), ([b], [a]))
        self.assertEqual(self.path.read_text(encoding="utf-8").count("^[Really?]"), 1)
        c, = self.make(self.item("cold", kind="comment", text="c"))       # two withdrawn twins, brought back at once
        suggestions.decide(self.b, self.book, [c], "withdraw")
        d, = self.make(self.item("cold", kind="comment", text="c"))
        suggestions.decide(self.b, self.book, [d], "withdraw")
        got = suggestions.decide(self.b, self.book, [c, d], "reopen")
        self.assertEqual((got["reopened"], got["unknown"]), ([c], [d]))

    def test_piece_names_outside_the_manuscript_are_never_read(self):
        meta_path = self.d / "book.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["contents"].append({"file": "../book.json", "kind": "chapter"})
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        out = {"id": "s-out", "file": "../book.json", "kind": "edit", "quote": "Harbour", "text": "X", "before": "",
               "after": "", "in": "text", "status": "open"}
        self.file.write_text(json.dumps({"version": 1, "suggestions": [out]}), encoding="utf-8")
        before = meta_path.read_bytes()
        got = suggestions.listing(self.b, self.book)
        self.assertEqual([(s["id"], s["found"], s["missing"], s["piece"]) for s in got], [("s-out", False, True, "")])
        got = suggestions.decide(self.b, self.book, ["s-out"], "accept")
        self.assertEqual((got["accepted"], got["changed"]), ([], ["s-out"]))
        self.assertEqual(meta_path.read_bytes(), before)
        self.assertFalse((self.d / "drafts" / "book").exists())

    def test_hand_edited_suggestion_is_changed(self):
        a, b = self.make(self.item("dusk", kind="note", text="n"),
                         self.item("harbour wall", kind="edit", text="quay"))
        data = suggestions.read(self.b, self.book)
        del data["suggestions"][0]["text"]
        self.file.write_text(json.dumps(data), encoding="utf-8")
        got = suggestions.decide(self.b, self.book, [a, b], "accept")
        self.assertEqual((got["accepted"], got["changed"]), ([b], [a]))

    def test_bad_decision(self):
        with self.assertRaises(BooksError) as cm:
            suggestions.decide(self.b, self.book, ["s1"], "maybe")
        self.assertEqual(cm.exception.code, 400)

    def test_no_file_no_write(self):
        got = suggestions.decide(self.b, self.book, ["s-nope"], "reject")
        self.assertEqual(got["unknown"], ["s-nope"])
        self.assertFalse(self.file.exists())


if __name__ == "__main__":
    unittest.main()
