"""One search across the library: folding, the query, the index, ranking, sources, freshness and the endpoints."""
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import quote

from studio import config, search
from studio.books import Books
from tests.support import temp_studio

_ENV = ("STUDIO_ART", "STUDIO_CONFIG", "STUDIO_CACHE")


def group(reply, kind):
    """The items of one group of a search reply ([] when the group isn't there)."""
    return next((g["items"] for g in reply["groups"] if g["kind"] == kind), [])


def make_poem(poems, series, folder, title, lines, notes=None, posting=None, mtime=None):
    d = poems / series / folder
    d.mkdir(parents=True)
    (d / "poem.json").write_text(json.dumps({"title": title, "lines": lines}, ensure_ascii=False), encoding="utf-8")
    if notes is not None:
        (d / "writing-notes.md").write_text(notes, encoding="utf-8")
    if posting is not None:
        (d / "NOTES.md").write_text(posting, encoding="utf-8")
    if mtime is not None:
        for f in d.iterdir():
            os.utime(f, (mtime, mtime))
    return d


def utf16(text, a, b):
    """text[a:b] counted in UTF-16 code units, as the browser slices it."""
    return text.encode("utf-16-le")[2 * a:2 * b].decode("utf-16-le")


class PointedAtTempLibrary(unittest.TestCase):
    """config pointed at a temp library (never the author's), restored afterwards."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-search-"))
        self.lib = self.tmp / "lib"
        self.poems = self.lib / "Poems"
        self.poems.mkdir(parents=True)
        self._env = {k: os.environ.get(k) for k in _ENV}
        self._cfg = config.CONFIG_FILE
        os.environ["STUDIO_ART"] = str(self.lib)
        os.environ["STUDIO_CONFIG"] = str(self.tmp / "config.json")
        os.environ["STUDIO_CACHE"] = str(self.tmp / "cache")
        config.CONFIG_FILE = self.tmp / "config.json"
        config.refresh()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.CONFIG_FILE = self._cfg
        config.refresh()
        shutil.rmtree(self.tmp, ignore_errors=True)


class FoldAndQueryTest(unittest.TestCase):
    def test_fold_and_marks(self):
        self.assertEqual(search.fold("Café ÉLAN"), "cafe elan")
        folded, back = search.fold_map("Straße")
        self.assertEqual(folded, "strasse")
        self.assertEqual(back[4:6], [4, 4])
        folded, back = search.fold_map("cafe\u0301 au")              # decomposed: the accent is a mark of its own
        self.assertEqual(folded, "cafe au")
        self.assertEqual(back, [0, 1, 2, 3, 5, 6, 7])
        self.assertEqual(search.fold("\u01c4 \ufb01"), "dz fi")                # compatibility forms and ligatures
        self.assertEqual(search.fold("plain ascii"), search.fold_map("plain ascii")[0])

    def test_parse_query(self):
        self.assertEqual(search.parse_query('light "the  sea"  '), ["light", "the sea"])
        self.assertEqual(search.parse_query('"open quote'), ["open quote"])
        self.assertEqual(search.parse_query('" ( * '), ["( *"])         # an unclosed quote runs to the end
        self.assertEqual(search.parse_query('( * '), ["(", "*"])
        self.assertEqual(len(search.parse_query("a" * 500)[0]), 200)
        self.assertEqual(search.parse_query("Sea sea SÉA"), ["sea"])     # folded, then duplicates dropped
        self.assertEqual(search.parse_query(" ".join(f"w{n}" for n in range(20))), [f"w{n}" for n in range(12)])
        self.assertEqual(search.parse_query('"" ¨  '), [])                 # nothing left once folded
        self.assertEqual(search.parse_query("“curly quotes” too"), ["curly quotes", "too"])


class SearchTest(PointedAtTempLibrary):
    def setUp(self):
        super().setUp()
        p = self.poems
        (p / "Sea").mkdir()
        (p / "Sea" / "series.json").write_text(json.dumps({"tagline": "salt and stone"}), encoding="utf-8")
        make_poem(p, "Sea", "Lighthouse", "Lighthouse", ["The lamp turns"], notes="a house by the sea")
        self.poem = make_poem(p, "Sea", "Light", "Light", ["morning light on water"])
        make_poem(p, "Sea", "Harbour", "Harbour", ["x"], mtime=1_700_000_000)
        make_poem(p, "Sea", "Harbour lights", "Harbour lights", ["y"], mtime=1_700_000_100)
        make_poem(p, "Sea", "The harbour", "The harbour", ["z"], mtime=1_700_000_200)
        make_poem(p, "Sea", "Quay", "Quay", ["boats in the harbour"], mtime=1_700_000_300)
        make_poem(p, "Sea", "Pier", "Pier", ["wood"], notes="the old harbour wall", mtime=1_700_000_400)
        make_poem(p, "Sea", "Café, ’s nachts", "Late hours", ["Het café ’s nachts", "en dan"])
        make_poem(p, "Sea", "Gulls", "Gulls", ["white"], posting="🌊 gull at dawn\nPost on Friday")
        walk = make_poem(p, "Sea", "Night walk", "Night walk", ["a road"])
        (walk / "designs" / ".trash").mkdir(parents=True)
        (walk / "designs" / "night-version.json").write_text(json.dumps({"name": "Night version"}), encoding="utf-8")
        (walk / "designs" / ".trash" / "x.json").write_text(json.dumps({"name": "ferry"}), encoding="utf-8")
        make_poem(p, ".trash/Sea", "Old ferry", "Old ferry", ["the ferry"])
        book = Books(self.lib / "Books").create("Field Notes", kind="fiction")
        self.book = Path(book["path"])
        meta = json.loads((self.book / "book.json").read_text(encoding="utf-8"))
        meta["subtitle"] = "A year on the coast"
        (self.book / "book.json").write_text(json.dumps(meta), encoding="utf-8")
        self.piece = "chapter-1.md"
        (self.book / "manuscript" / self.piece).write_text(
            "# Crossing\n\nWe took the boat at noon.^[The ferry left late.]\n\n![A grey quay](images/q.png)\n",
            encoding="utf-8")
        self.idx = search.Index(self.lib)
        self.idx.check()

    def test_every_word_anywhere_and_inside_words(self):
        r = self.idx.search("light house")
        self.assertEqual([i["title"] for i in group(r, "poem")], ["Lighthouse"])
        self.assertEqual(r["q"], "light house")
        self.assertEqual([i["title"] for i in group(self.idx.search('"house by"'), "poem")], ["Lighthouse"])
        self.assertEqual(group(self.idx.search('"by house"'), "poem"), [])           # a phrase keeps its order

    def test_ranking(self):
        r = self.idx.search("harbour")
        self.assertEqual([i["title"] for i in group(r, "poem")],
                         ["Harbour", "Harbour lights", "The harbour", "Quay", "Pier"])
        quay, pier = group(r, "poem")[3:]
        self.assertEqual((quay["field"], quay["field_label"]), ("text", ""))
        self.assertEqual((pier["field"], pier["field_label"]), ("notes", "Writing notes"))
        self.assertEqual(group(r, "poem")[0]["title_marks"], [[0, 7]])
        self.assertEqual(group(r, "poem")[2]["title_marks"], [[4, 11]])

    def test_ties_go_to_the_newest(self):
        make_poem(self.poems, "Sea", "Dune one", "Dune one", ["sand"], mtime=1_700_000_000)
        make_poem(self.poems, "Sea", "Dune two", "Dune two", ["sand"], mtime=1_700_009_000)
        self.idx.check()
        self.assertEqual([i["title"] for i in group(self.idx.search("dune"), "poem")], ["Dune two", "Dune one"])

    def test_groups_order_totals_and_limit(self):
        r = self.idx.search("harbour", limit=2)
        g = next(g for g in r["groups"] if g["kind"] == "poem")
        self.assertEqual((g["label"], g["total"], len(g["items"])), ("Poems", 5, 2))
        self.assertEqual(len(group(self.idx.search("harbour", limit=0), "poem")), 1)        # clamped to 1..200
        kinds = [g["kind"] for g in self.idx.search("a")["groups"]]
        order = [k for k, _ in search.KINDS]
        self.assertEqual(kinds, sorted(kinds, key=order.index))
        only = self.idx.search("harbour", kinds=["series"])
        self.assertEqual(only["groups"], [])
        self.assertEqual(only["counts"], {"poems": 10, "series": 1, "designs": 1, "books": 1, "pieces": 1})

    def test_sources_and_jumps(self):
        r = self.idx.search("ferry")
        piece = group(r, "piece")[0]
        self.assertEqual(piece["field"], "note")
        self.assertEqual(piece["field_label"], "In a note")
        self.assertEqual(piece["jump"], {"type": "piece", "book": "Field Notes", "file": self.piece, "match": "ferry"})
        self.assertEqual((piece["title"], piece["where"]), ("Crossing", "Field Notes"))
        self.assertEqual(piece["href"], "#/book/Field%20Notes/write/chapter-1.md")
        self.assertEqual(piece["snippet"]["text"], "The ferry left late.")
        self.assertEqual(piece["snippet"]["marks"], [[4, 9]])
        self.assertEqual(group(r, "poem"), [])
        self.assertEqual(group(r, "design"), [])
        self.assertEqual(group(self.idx.search("quay"), "piece")[0]["field"], "text")       # a caption is text

        series = group(self.idx.search("salt"), "series")[0]
        self.assertEqual(series["href"], "#/series/Sea")
        self.assertEqual((series["title"], series["where"], series["field"], series["field_label"]),
                         ("Sea", "Series", "tagline", "Tagline"))
        self.assertEqual(series["jump"], {"type": "series"})

        design = group(self.idx.search("night version"), "design")[0]
        self.assertEqual(design["jump"], {"type": "design", "id": "Sea/Night walk", "slug": "night-version"})
        self.assertEqual((design["title"], design["where"]), ("Night version", "Night walk · Sea"))
        self.assertEqual(design["href"], "#/poem/Sea%2FNight%20walk/design")

        book = group(self.idx.search("coast"), "book")[0]
        self.assertEqual((book["title"], book["where"], book["field"], book["field_label"]),
                         ("Field Notes", "Books", "subtitle", "Subtitle"))
        self.assertEqual((book["href"], book["jump"]), ("#/book/Field%20Notes", {"type": "book"}))

        notes = group(self.idx.search("by the sea"), "poem")[0]         # the whole query is there: it is selected
        self.assertEqual(notes["jump"], {"type": "poem", "id": "Sea/Lighthouse", "field": "notes",
                                         "start": 8, "end": 18, "match": "by the sea"})
        self.assertEqual(notes["href"], "#/poem/Sea%2FLighthouse/write")
        apart = group(self.idx.search("sea house"), "poem")[0]          # else the first word found
        self.assertEqual((apart["jump"]["start"], apart["jump"]["end"], apart["jump"]["match"]), (15, 18, "sea"))

    def test_posting_notes_open_the_art_tab_and_count_like_the_browser(self):
        it = group(self.idx.search("gull dawn"), "poem")[0]
        self.assertEqual((it["field"], it["field_label"]), ("posting", "Posting notes"))
        self.assertEqual(it["href"], "#/poem/Sea%2FGulls/art")
        text = it["snippet"]["text"]
        self.assertEqual(text, "🌊 gull at dawn Post on Friday")                   # the newline shown as a space
        self.assertEqual([utf16(text, a, b) for a, b in it["snippet"]["marks"]], ["gull", "dawn"])
        self.assertEqual(it["snippet"]["marks"][0], [3, 7])                         # the wave is two code units
        self.assertEqual((it["jump"]["start"], it["jump"]["end"], it["jump"]["match"]), (3, 7, "gull"))

    def test_accented_text_marks_point_into_the_original(self):
        it = group(self.idx.search("cafe"), "poem")[0]
        a, b = it["snippet"]["marks"][0]
        self.assertEqual(it["snippet"]["text"][a:b], "café")
        self.assertEqual(it["jump"]["match"], "café")
        self.assertEqual((it["jump"]["field"], it["jump"]["start"], it["jump"]["end"]), ("text", 4, 8))
        self.assertEqual(it["jump"]["id"], "Sea/Café, ’s nachts")
        self.assertEqual(it["href"], "#/poem/" + quote("Sea/Café, ’s nachts", safe="") + "/write")
        self.assertEqual(it["where"], "Sea")
        make_poem(self.poems, "Sea", "Decomposed", "Decomposed", ["een cafe\u0301 hier"])
        self.idx.check()
        it = group(self.idx.search("CAFÉ hier"), "poem")[0]
        text = it["snippet"]["text"]
        self.assertEqual([text[a:b] for a, b in it["snippet"]["marks"]], ["cafe\u0301", "hier"])

    def test_snippets_are_cut_at_words_and_marked(self):
        before, after = (" ".join(f"word{n}" for n in r) for r in (range(20), range(20, 40)))
        make_poem(self.poems, "Sea", "Long", "Long", [before + " kestrel " + after])
        self.idx.check()
        it = group(self.idx.search("kestrel"), "poem")[0]
        text = it["snippet"]["text"]
        self.assertTrue(text.startswith("…word") and text.endswith("…"), text)
        self.assertLessEqual(len(text), 2 + 40 + len("kestrel") + 40 + 2 * 12)
        inner = text[1:-1]
        self.assertEqual(inner, inner.strip())
        for w in inner.split():
            self.assertRegex(w, r"^(word\d+|kestrel)$")                          # never half a word
        self.assertEqual([text[a:b] for a, b in it["snippet"]["marks"]], ["kestrel"])
        it = group(self.idx.search("word1 word"), "poem")[0]
        marks = it["snippet"]["marks"]
        self.assertTrue(all(b < c for (_, b), (c, _) in zip(marks, marks[1:])), marks)      # merged, in order
        self.assertIsNone(group(self.idx.search("lighthouse"), "poem")[0]["snippet"])     # only the title holds it

    def test_odd_queries_never_fail(self):
        for q in ['"', "(a", "*", "a" * 500, "   ", "\x00", "“", '""', "[", "\\", "a" * 100_000,
                  " ".join(["harbour"] * 50), "%", "?*+.^$"]:
            r = self.idx.search(q)
            self.assertIsInstance(r["groups"], list, q[:20])
        self.assertEqual(self.idx.search("   ")["groups"], [])
        self.assertEqual(self.idx.search("(")["groups"], [])

    def test_unreadable_files_are_left_out(self):
        make_poem(self.poems, "Sea", "Broken", "Broken", ["harbour"])
        (self.poems / "Sea" / "Broken" / "poem.json").write_text("{bad", encoding="utf-8")
        make_poem(self.poems, "Sea", "Not a poem", "x", [])
        (self.poems / "Sea" / "Not a poem" / "poem.json").write_text("[1, 2]", encoding="utf-8")
        make_poem(self.poems, "Sea", "Old notes", "Old notes", ["harbour"])
        (self.poems / "Sea" / "Old notes" / "writing-notes.md").write_bytes("café".encode("cp1252"))
        piece = Books(self.lib / "Books").new_piece("Field Notes", "chapter", title="Harbour")["file"]
        (self.book / "manuscript" / piece).write_bytes("# Harbour\n\ncafé harbour".encode("cp1252"))
        self.idx.check()      # no exception
        r = self.idx.search("harbour")
        self.assertTrue(r["groups"])
        self.assertEqual([i["title"] for i in group(r, "poem")],
                         ["Harbour", "Harbour lights", "The harbour", "Quay", "Pier"])
        self.assertEqual(group(r, "piece"), [])

    def test_a_check_reads_only_what_changed(self):
        reads = []
        real = search._read

        def spy(path):
            reads.append(Path(path).resolve().relative_to(self.lib.resolve()).as_posix())
            return real(path)

        with mock.patch.object(search, "_read", spy):
            self.idx.check()
            self.assertEqual(reads, [])
            notes = self.poem / "writing-notes.md"
            notes.write_text("gannet", encoding="utf-8")
            self.idx.check()
        self.assertEqual(sorted(reads), ["Poems/Sea/Light/poem.json", "Poems/Sea/Light/writing-notes.md"])

    def test_freshness(self):
        self.idx.check()
        notes = self.poem / "writing-notes.md"
        notes.write_text("gannet", encoding="utf-8")
        os.utime(notes, ns=(time.time_ns() + 5_000_000_000,) * 2)
        self.idx.check()
        self.assertTrue(group(self.idx.search("gannet"), "poem"))
        shutil.rmtree(self.poem)
        self.idx.check()
        self.assertFalse(group(self.idx.search("gannet"), "poem"))
        st = self.idx.state()
        self.assertEqual(set(st), {"checked", "checking", "building", "counts"})
        self.assertFalse(st["checking"])
        self.assertIsNone(st["building"])
        self.assertEqual(st["counts"]["poems"], 9)

    def test_a_large_library_is_listed_by_threads_with_the_same_result(self):
        with mock.patch.object(search, "SCAN_THREADS_FROM", 1), mock.patch.object(search, "SCAN_THREADS", 3):
            idx = search.Index(self.lib)
            idx.check()
        self.assertEqual(idx.state()["counts"], self.idx.state()["counts"])
        for q in ("harbour", "night version", "cafe", "gull"):
            self.assertEqual(idx.search(q)["groups"], self.idx.search(q)["groups"], q)

    def test_a_poem_retitled_renames_its_designs_where(self):
        walk = self.poems / "Sea" / "Night walk"
        (walk / "poem.json").write_text(json.dumps({"title": "Night road", "lines": []}), encoding="utf-8")
        os.utime(walk / "poem.json", ns=(time.time_ns() + 5_000_000_000,) * 2)
        self.idx.check()
        self.assertEqual(group(self.idx.search("night version"), "design")[0]["where"], "Night road · Sea")

    def test_the_first_build_reports_progress(self):
        idx = search.Index(self.lib)
        gate, real = threading.Event(), search._read

        def slow(path):
            if Path(path).name == "poem.json":
                gate.wait(5)
            return real(path)

        searching = lambda: sum(t.name == "studio-search" for t in threading.enumerate())
        running = searching()
        with mock.patch.object(search, "_read", slow):
            idx.ensure(wait=0)
            deadline = time.monotonic() + 5
            while idx.state()["building"]["total"] == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            r = idx.search("harbour")
            self.assertEqual(r["groups"], [])
            self.assertEqual(r["building"], {"done": 0, "total": 11})      # 10 poem folders and 1 piece
            self.assertTrue(r["checking"])
            self.assertIsNone(r["checked"])
            idx.ensure(wait=0)                                           # never a second check
            self.assertEqual(searching(), running + 1)
            gate.set()
            idx.ensure(wait=5)
        r = idx.search("harbour")
        self.assertIsNone(r["building"])
        self.assertFalse(r["checking"])
        self.assertIsNotNone(r["checked"])
        self.assertTrue(group(r, "poem"))

    def test_ensure_checks_again_only_after_fresh(self):
        idx = search.Index(self.lib)
        idx.ensure(wait=5)
        self.assertIsNotNone(idx.state()["checked"])
        with mock.patch.object(search.Index, "_walk") as walk:
            idx.ensure(wait=1)
            self.assertEqual(walk.call_count, 0)          # the last check ended a moment ago
            idx._ended -= search.FRESH + 1                # ... and now more than FRESH ago
            idx.ensure(wait=1)
            self.assertEqual(walk.call_count, 1)

    def test_index_follows_the_library_setting(self):
        a = search.index()
        self.assertIs(search.index(), a)
        self.assertEqual(a.library, config.ART)
        other = self.tmp / "other"
        make_poem(other / "Poems", "Inland", "Gannet", "Gannet", ["harbour"])
        (other / "Poems" / "Inland" / "series.json").write_text("{}", encoding="utf-8")
        os.environ["STUDIO_ART"] = str(other)
        config.refresh()
        self.assertIsNot(search.index(), a)
        self.assertEqual(search.index().library, other.resolve())
        search.index().check()
        self.assertEqual([i["title"] for i in group(search.index().search("harbour"), "poem")], ["Gannet"])

    def test_research_source(self):
        fake = types.ModuleType("studio.research")
        fake.Research = lambda lib: SimpleNamespace(search=lambda q, every=False: [
            {"board": None, "board_title": "Shared board", "id": "n1", "type": "note", "title": "",
             "snippet": "a ferry at dawn"},
            {"board": "Field Notes", "board_title": "Field Notes", "id": "n2", "type": "link", "title": "Ferry times",
             "snippet": "timetable"}])
        with mock.patch.dict(sys.modules, {"studio.research": fake}), \
                mock.patch("importlib.util.find_spec", return_value=object()):
            r = self.idx.search("ferry")
        items = group(r, "research")
        self.assertEqual(items[0]["href"], "#/research")
        self.assertEqual((items[0]["title"], items[0]["where"]), ("a ferry at dawn", "Shared board"))
        self.assertEqual(items[0]["snippet"], {"text": "a ferry at dawn", "marks": [[2, 7]]})
        self.assertEqual(items[0]["jump"], {"type": "research", "board": None, "id": "n1"})
        self.assertEqual(items[1]["jump"], {"type": "research", "board": "Field Notes", "id": "n2"})
        self.assertEqual((items[1]["href"], items[1]["title_marks"]), ("#/book/Field%20Notes/board", [[0, 5]]))
        self.assertEqual(r["errors"], [])
        self.assertEqual([g["kind"] for g in r["groups"]][-1], "research")

        def broken(q, every=False):
            raise RuntimeError("the board file can't be read")

        fake.Research = lambda lib: SimpleNamespace(search=broken)
        with mock.patch.dict(sys.modules, {"studio.research": fake}), \
                mock.patch("importlib.util.find_spec", return_value=object()):
            r = self.idx.search("ferry")
        self.assertEqual(group(r, "research"), [])
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("the board file can't be read", r["errors"][0])
        self.assertTrue(group(r, "piece"))

        with mock.patch("importlib.util.find_spec", return_value=None):          # part 3 not there: no group
            r = self.idx.search("ferry")
        self.assertEqual((group(r, "research"), r["errors"]), ([], []))

    def test_reply_shape(self):
        r = self.idx.search("harbour")
        self.assertEqual(set(r), {"q", "groups", "counts", "checked", "checking", "building", "errors"})
        it = group(r, "poem")[0]
        self.assertEqual(set(it), {"kind", "title", "title_marks", "where", "href", "field", "field_label",
                                   "snippet", "jump"})
        self.assertEqual(it["kind"], "poem")
        json.dumps(r)


class SearchEndpointTest(unittest.TestCase):
    def test_endpoints(self):
        with temp_studio() as t:
            make_poem(t.root, "Sea", "Harbour", "Harbour", ["the harbour at night"])
            (t.root / "Sea" / "series.json").write_text("{}", encoding="utf-8")
            code, body = t.post("/api/search/warm")
            self.assertEqual(code, 200)
            self.assertEqual(set(body), {"checked", "checking", "building", "counts"})
            deadline = time.monotonic() + 10
            while True:
                code, body = t.get("/api/search?q=harbour")
                self.assertEqual(code, 200)
                if not body["building"] or time.monotonic() > deadline:
                    break
                time.sleep(0.05)
            self.assertIn("groups", body)
            self.assertIn("checked", body)
            self.assertEqual([i["title"] for i in group(body, "poem")], ["Harbour"])
            code, body = t.get("/api/search?q=harbour&kind=series&limit=500")
            self.assertEqual((code, body["groups"]), (200, []))
            code, body = t.get("/api/search")
            self.assertEqual((code, body["groups"], body["q"]), (200, [], ""))
            self.assertEqual(t.get("/api/search?q=x&limit=lots")[0], 400)
            self.assertEqual(t.get("/api/search?q=x&kind=drafts")[0], 400)
            self.assertEqual(t.get("/api/search?q=harbour&limit=0")[0], 200)


@unittest.skipIf(os.environ.get("STUDIO_SKIP_SLOW") == "1", "STUDIO_SKIP_SLOW=1")
class SearchSpeedTest(unittest.TestCase):
    """S4: 5,000 poems and 3 books of 100 pieces (about 1.3 million words): a warm search under 150 ms, a check with
    nothing changed under 2 s (the spec's 1 s, with a margin for slow machines)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-search-speed-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_speed(self):
        rnd = random.Random(7)
        sounds = [c + v for c in "bdfgklmnprstvz" for v in "aeiou"]
        vocab = sorted({"".join(rnd.choice(sounds) for _ in range(rnd.choice((2, 3)))) for _ in range(6000)})
        poems = self.tmp / "Poems"
        for s in range(10):
            sd = poems / f"Series {s}"
            sd.mkdir(parents=True)
            (sd / "series.json").write_text('{"tagline": "generated"}', encoding="utf-8")
            for n in range(500):
                d = sd / f"Poem {n}"
                d.mkdir()
                lines = [" ".join(rnd.choice(vocab) for _ in range(6)) for _ in range(12)]
                title = " ".join(rnd.choice(vocab) for _ in range(2)).capitalize()
                (d / "poem.json").write_text(json.dumps({"title": title, "lines": lines}), encoding="utf-8")
        for b in range(3):
            bd = self.tmp / "Books" / f"Book {b}"
            (bd / "manuscript").mkdir(parents=True)
            contents = []
            for n in range(100):
                name = f"chapter-{n + 1}.md"
                paras = [" ".join(rnd.choice(vocab) for _ in range(100)) + "." for _ in range(30)]
                (bd / "manuscript" / name).write_text(f"# Chapter {n + 1}\n\n" + "\n\n".join(paras) + "\n",
                                                      encoding="utf-8")
                contents.append({"file": name, "kind": "chapter", "form": "prose"})
            (bd / "book.json").write_text(json.dumps({"title": f"Book {b}", "contents": contents}), encoding="utf-8")

        idx = search.Index(self.tmp)
        t = time.perf_counter()
        idx.check()
        build = time.perf_counter() - t
        self.assertEqual(idx.state()["counts"]["poems"], 5000)
        self.assertEqual(idx.state()["counts"]["pieces"], 300)
        times = []
        for _ in range(10):
            q = f"{rnd.choice(vocab)} {rnd.choice(vocab)[:4]}"
            t = time.perf_counter()
            idx.search(q)
            times.append(time.perf_counter() - t)
        median = statistics.median(times)
        t = time.perf_counter()
        idx.check()
        again = time.perf_counter() - t
        t = time.perf_counter()
        search.Index(self.tmp).check()      # files just written are slow to open the first time (a virus scanner)
        cold = time.perf_counter() - t
        print(f"\nsearch timing: build {build:.2f} s (new files), {cold:.2f} s (files read before); "
              f"median search {median * 1000:.1f} ms; check with nothing changed {again:.2f} s", file=sys.stderr)
        self.assertLess(median, 0.15)
        self.assertLess(again, 2.0)


if __name__ == "__main__":
    unittest.main()
