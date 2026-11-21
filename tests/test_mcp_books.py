"""The MCP tools that read books: list_books, read_book, read_piece, search_book, list_sources."""
import hashlib
import io
import json
import types
import unittest
from unittest import mock
from datetime import datetime

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image

from studio import compose, config, mcp_books, preflight as print_checks, mcp_server, research, suggestions
from studio.books import Books
from tests.test_mcp_tools import temp_library


def call(tool, *args, **kw):
    return anyio.run(lambda: tool(*args, **kw))


def png_bytes(n):
    out = io.BytesIO()
    Image.new("RGB", (60 + n, 80), (240, 240, 230)).save(out, "PNG")
    return out.getvalue()


class fake_compile:
    """Typst cuts fonts on a cold cache (seconds a family); these tests check the tools, not the typesetting
    (tests/test_compose.py does that), so compile_book and render_pages are stood in for."""
    def __init__(self, pages=6):
        self.pages, self.asked = pages, []

    def render(self, books, book, pages=None, fmt="png", ppi=96):
        self.asked.append((pages, ppi))
        return [png_bytes(n) for n in (pages or range(1, self.pages + 1))]

    def __enter__(self):
        self.patches = [mock.patch.object(compose, "compile_book",
                                          return_value=types.SimpleNamespace(pages=[0] * self.pages, error=None)),
                        mock.patch.object(compose, "render_pages", side_effect=self.render)]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


FAKE_PDF = {"name": "The Quiet Harbour 2026-11-13.pdf", "path": "C:/x/exports/the.pdf", "pages": 12, "size": 34567}


def fake_checks(items=None):
    """Stands in for studio.preflight.run (patched on the real module, so the import order can't bypass it)."""
    items = items if items is not None else [
        {"check": "widow", "level": "warn", "message": "A line is left alone.", "page": 5, "file": "01-low-tide.md", "block": 2},
        {"check": "fonts", "level": "info", "message": "Fonts are embedded.", "page": None, "file": None, "block": None}]
    return mock.patch.object(print_checks, "run", return_value={"summary": "1 warning", "items": items, "pages": 12, "at": "now"})


def make_book():
    books = Books(config.BOOKS)
    books.create("The Quiet Harbour", author="A. Writer", kind="nonfiction")
    book = "The Quiet Harbour"
    chapter = next(e["file"] for e in books.read(book)["contents"] if e.get("kind") == "chapter")
    books.save_piece(book, chapter, md="# Low Tide\n\nThe boats lean in the mud.\n",
                     now=datetime(2026, 1, 1, 9, 0))
    books.save_piece(book, chapter, md="# Low Tide\n\nThe boats lean in the mud and wait for [water]{.idx term=\"sea\"}.^[A note on mud.]\n",
                     now=datetime(2026, 1, 2, 9, 0))
    (books.dir(book) / "sources.json").write_text(json.dumps(
        [{"id": "vandijk2019", "type": "book", "title": "Tides", "author": [{"family": "Dijk",
          "non-dropping-particle": "van", "given": "Sam"}], "issued": {"date-parts": [[2019]]}},
         {"id": "agency", "type": "report", "title": "Report", "author": [{"literal": "Harbour Agency"}]}]),
        encoding="utf-8")
    return books, book, chapter


class McpBooksTest(unittest.TestCase):
    def test_list_and_read_book(self):
        with temp_library():
            books, book, chapter = make_book()
            shelf = json.loads(call(mcp_books.list_books))
            self.assertEqual(shelf[0]["id"], "The Quiet Harbour")
            for k in ("title", "author", "kind", "language", "words", "pieces", "by_status", "suggestions_waiting"):
                self.assertIn(k, shelf[0])
            self.assertEqual(shelf[0]["suggestions_waiting"], 0)
            b = json.loads(call(mcp_books.read_book, "the quiet harbour"))      # named by title, either case
            for k in ("id", "title", "subtitle", "author", "language", "kind", "features", "details", "style_sheet",
                      "contents", "sources", "index_terms", "editions", "suggestions_waiting"):
                self.assertIn(k, b)
            low = next(c for c in b["contents"] if c.get("file") == chapter)
            self.assertEqual(low["title"], "Low Tide")
            self.assertGreater(low["words"], 5)
            self.assertEqual(low["notes"], 1)
            self.assertEqual(b["sources"], [{"id": "vandijk2019", "label": "van Dijk 2019"},
                                            {"id": "agency", "label": "Harbour Agency"}])
            self.assertEqual([t["term"] for t in b["index_terms"]], ["sea"])
            self.assertEqual(b["suggestions_waiting"], {})

    def test_read_piece_and_a_version(self):
        with temp_library():
            books, book, chapter = make_book()
            text = call(mcp_books.read_piece, "The Quiet Harbour", "Low Tide")      # a piece named by title
            head, md = text.split("\n---\n", 1)
            h = json.loads(head)
            self.assertEqual(h["file"], chapter)
            self.assertEqual(h["title"], "Low Tide")
            self.assertEqual(len(h["versions"]), 2)
            self.assertIn("suggestions_waiting", h)
            self.assertIn("wait for [water]{.idx", md)
            old = h["versions"][-1]["when"]
            _, md2 = call(mcp_books.read_piece, "The Quiet Harbour", chapter, version=old).split("\n---\n", 1)
            self.assertIn("boats lean", md2)
            self.assertNotIn("water", md2)
            self.assertIn("A note on mud", md)
            h2 = json.loads(call(mcp_books.read_piece, "The Quiet Harbour", chapter, version=old).split("\n---\n")[0])
            self.assertEqual((h2["notes"], h2["note_words"]), (0, 0))       # counts are the snapshot's own
            self.assertEqual(h["notes"], 1)
            with self.assertRaises(ToolError):
                call(mcp_books.read_piece, "The Quiet Harbour", chapter, version="1999-01-01")

    def test_search_book(self):
        with temp_library():
            make_book()
            hits = json.loads(call(mcp_books.search_book, "The Quiet Harbour", "boats"))
            self.assertEqual(hits[0]["match"], "boats")
            self.assertIn("The ", hits[0]["before"])
            self.assertIn("lean", hits[0]["after"])
            self.assertEqual(json.loads(call(mcp_books.search_book, "The Quiet Harbour", "BOATS", match_case=True)), [])

    def test_list_sources(self):
        with temp_library():
            make_book()
            items = json.loads(call(mcp_books.list_sources, "The Quiet Harbour"))
            self.assertEqual([i["id"] for i in items], ["vandijk2019", "agency"])

    def test_unknown_book_is_a_tool_error(self):
        with temp_library():
            make_book()
            for tool, args in ((mcp_books.read_book, ("Nowhere",)), (mcp_books.list_sources, ("Nowhere",)),
                               (mcp_books.read_piece, ("Nowhere", "x")), (mcp_books.search_book, ("Nowhere", "x"))):
                with self.assertRaises(ToolError) as cm:
                    call(tool, *args)
                self.assertIn("Nowhere", str(cm.exception))

    def test_tools_registered_and_instructions(self):
        names = {t.name for t in anyio.run(mcp_server.server.list_tools)}
        self.assertTrue({"list_books", "read_book", "read_piece", "search_book", "list_sources"} <= names)
        self.assertIn("Books are in Books/<Book>/", mcp_server.INSTRUCTIONS)

    def test_add_source_tool(self):
        with temp_library():
            books, book, _ = make_book()
            out = call(mcp_books.add_source, "The Quiet Harbour", {"title": "Salt Marsh", "author": [{"family": "Reed"}],
                                                                   "issued": {"date-parts": [[2021]]}})
            self.assertEqual(out, "Added reed2021: Reed 2021")
            self.assertIn("reed2021", [i["id"] for i in books.sources(book)])
            with self.assertRaises(ToolError) as cm:
                call(mcp_books.add_source, "The Quiet Harbour", {"title": "Salt Marsh", "issued": {"date-parts": [[2021]]}})
            self.assertIn("same source", str(cm.exception))
            with self.assertRaises(ToolError):
                call(mcp_books.add_source, "The Quiet Harbour", {"title": ""})

    def test_suggest_reports_each_refusal(self):
        with temp_library():
            books, book, chapter = make_book()
            out = call(mcp_books.suggest, "The Quiet Harbour", [
                {"piece": chapter, "kind": "edit", "quote": "boats lean", "text": "boats sag"},
                {"piece": chapter, "kind": "edit", "quote": "no such words", "text": "x"}])
            lines = out.split("\n")
            self.assertEqual(lines[0], "Added 1 suggestion.")
            self.assertTrue(lines[1].startswith("Not added: item 2 \u2014 "), out)
            self.assertEqual(lines[-1], "The author sees them in the writing window's Suggestions panel.")
            out = call(mcp_books.suggest, "The Quiet Harbour", [
                {"piece": chapter, "kind": "comment", "quote": "mud", "text": "Which mud?"},
                {"piece": chapter, "kind": "index", "quote": "boats"}], label="Round one")
            self.assertTrue(out.startswith('Added 2 suggestions (group "Round one").'), out)
            with self.assertRaises(ToolError):
                call(mcp_books.suggest, "The Quiet Harbour", [])
            self.assertIn("Not added: item 1", call(mcp_books.suggest, "The Quiet Harbour", ["junk"]))

    def test_list_and_withdraw(self):
        with temp_library():
            books, book, chapter = make_book()
            call(mcp_books.suggest, "The Quiet Harbour", [
                {"piece": "Low Tide", "kind": "edit", "quote": "boats lean", "text": "boats sag"},
                {"piece": chapter, "kind": "comment", "quote": "mud", "text": "Which mud?"}])
            items = json.loads(call(mcp_books.list_suggestions, "The Quiet Harbour"))
            self.assertEqual(len(items), 2)
            fields = {"id", "file", "piece", "kind", "quote", "text", "term", "source", "locator", "why", "label",
                      "status", "found", "missing", "made", "decided"}
            self.assertTrue(set(items[0]) <= fields)
            for k in ("id", "file", "piece", "kind", "quote", "text", "status", "found", "missing", "made"):
                self.assertIn(k, items[0])
            self.assertTrue(all(i["found"] and i["status"] == "open" for i in items))
            self.assertEqual(len(json.loads(call(mcp_books.list_suggestions, "The Quiet Harbour", piece="Low Tide"))), 2)
            ids = [i["id"] for i in items]
            self.assertEqual(call(mcp_books.withdraw_suggestions, "The Quiet Harbour", ids[:1]), "Withdrew 1.")
            out = call(mcp_books.withdraw_suggestions, "The Quiet Harbour", [ids[0], ids[1], "s-nope"])
            self.assertEqual(out, f"Withdrew 1.\nNot open: {ids[0]}, s-nope")
            self.assertEqual(json.loads(call(mcp_books.list_suggestions, "The Quiet Harbour")), [])
            self.assertEqual(len(json.loads(call(mcp_books.list_suggestions, "The Quiet Harbour", status="decided"))), 2)
            with self.assertRaises(ToolError):
                call(mcp_books.list_suggestions, "The Quiet Harbour", status="bogus")

    def test_no_tool_changes_the_manuscript(self):
        with temp_library():
            books, book, chapter = make_book()
            d = books.dir(book)
            self.assertTrue(books.read(book)["features"]["sources"] and books.read(book)["features"]["index"])

            def digest():
                files = sorted(p for p in (d / "manuscript").rglob("*") if p.is_file())
                out = {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
                meta = json.loads((d / "book.json").read_text(encoding="utf-8"))
                meta.pop("design", None)          # set_book_design writes the design and nothing else
                out["book.json"] = hashlib.sha256(json.dumps(meta, sort_keys=True).encode()).hexdigest()
                return out
            before = digest()
            self.assertGreater(len(before), 1)
            q = "The Quiet Harbour"
            called = set()

            def run(tool, *args, **kw):
                called.add(tool.__name__)
                return call(tool, *args, **kw)
            run(mcp_books.list_books)
            run(mcp_books.read_book, q)
            run(mcp_books.read_piece, q, chapter)
            run(mcp_books.search_book, q, "boats")
            run(mcp_books.list_sources, q)
            run(mcp_books.add_source, q, {"title": "Salt Marsh", "author": [{"family": "Reed"}]})
            out = run(mcp_books.suggest, q, [
                {"piece": chapter, "kind": "edit", "quote": "boats lean", "text": "boats sag"},
                {"piece": chapter, "kind": "note", "quote": "mud", "text": "Soft."},
                {"piece": chapter, "kind": "index", "quote": "boats", "term": "ships > boats"},
                {"piece": chapter, "kind": "cite", "quote": "mud", "source": "vandijk2019", "locator": "p. 12"},
                {"piece": chapter, "kind": "comment", "quote": "Low Tide", "text": "Title?"}])
            self.assertTrue(out.startswith("Added 5 suggestions"), out)
            ids = [i["id"] for i in json.loads(run(mcp_books.list_suggestions, q))]
            self.assertEqual(len(ids), 5)
            run(mcp_books.withdraw_suggestions, q, ids[:2])
            run(mcp_books.add_research, {"type": "note", "title": "Tide table", "text": "High at six."}, book=q)
            run(mcp_books.list_research, q)
            run(mcp_books.read_research, "tide-table", q)
            run(mcp_books.get_book_design, q)
            run(mcp_books.set_book_design, q, {"trim": "a5"})
            with fake_compile(), mock.patch.object(compose, "export_pdf", return_value=FAKE_PDF):
                run(mcp_books.render_pages, q, "1-2")
                run(mcp_books.export_pdf, q)
            with fake_checks():
                run(mcp_books.preflight, q)
            self.assertEqual(digest(), before)
            # every tool defined in mcp_books was called above, so a new tool without a call here fails this test
            book_tools = {t.name for t in anyio.run(mcp_server.server.list_tools)
                          if getattr(getattr(mcp_books, t.name, None), "__module__", None) == mcp_books.__name__}
            self.assertEqual(called, book_tools)
            # the tools did write what they should (sources.json, suggestions.json), so the guard isn't vacuous
            self.assertIn("reed", (d / "sources.json").read_text(encoding="utf-8"))
            self.assertEqual(len(json.loads((d / "suggestions.json").read_text(encoding="utf-8"))["suggestions"]), 5)

    def test_design_tools(self):
        with temp_library():
            make_book()
            before = json.loads(call(mcp_books.get_book_design, "the quiet harbour"))
            for k in ("design", "stored", "templates", "trims", "printers", "fonts"):
                self.assertIn(k, before)
            self.assertEqual(before["stored"], {})
            out = json.loads(call(mcp_books.set_book_design, "The Quiet Harbour", {"trim": "a5"}))
            self.assertEqual(out["design"]["trim"], "a5")
            self.assertEqual(out["stored"]["trim"], "a5")
            self.assertEqual(json.loads(call(mcp_books.get_book_design, "The Quiet Harbour"))["stored"], out["stored"])
            out = json.loads(call(mcp_books.set_book_design, "The Quiet Harbour", reset="all"))
            self.assertEqual(out["stored"], {})
            tid = before["templates"][-1]["id"]
            out = json.loads(call(mcp_books.set_book_design, "The Quiet Harbour", template=tid, reset=["margins"]))
            self.assertEqual(out["design"]["template"], tid)
            with self.assertRaises(ToolError) as e:
                call(mcp_books.set_book_design, "The Quiet Harbour", {"trim": "nonsense"})
            self.assertTrue(str(e.exception).endswith("."), e.exception)
            self.assertIn("Compose", mcp_books.set_book_design.__doc__ or "")

    def test_render_pages(self):
        with temp_library():
            make_book()
            folder = lambda: config.CACHE / "mcp-pages" / "The Quiet Harbour"
            with fake_compile(pages=6) as f:
                out = call(mcp_books.render_pages, "The Quiet Harbour")        # the first four
                self.assertEqual(f.asked[-1], ([1, 2, 3, 4], 96))
                self.assertEqual(sum(1 for x in out if isinstance(x, str)), 1)
                text = out[0]
                self.assertIn("6 pages", text)
                files = sorted(folder().rglob("*.png"))
                self.assertEqual(len(files), 4)
                self.assertTrue(all(str(p) in text for p in files), text)
                self.assertEqual(len(out) - 1, 4)                              # four pictures
                call(mcp_books.render_pages, "The Quiet Harbour", "1-2, 6", 150)
                self.assertEqual(f.asked[-1], ([1, 2, 6], 150))
                self.assertEqual(len(list(folder().rglob("*.png"))), 3)        # the earlier run's files are gone
                out = call(mcp_books.render_pages, "The Quiet Harbour", "1-6")
                self.assertEqual(len(out) - 1, 4)                              # at most four pictures
                self.assertEqual(len(list(folder().rglob("*.png"))), 6)
                for bad in ("0", "7", "4-2", "x", "1,,2", "1-", "", "²", "٣"):
                    with self.assertRaises(ToolError) as e:
                        call(mcp_books.render_pages, "The Quiet Harbour", bad)
                    self.assertTrue(str(e.exception).endswith("."), (bad, e.exception))
                    self.assertIn("Name pages like", str(e.exception)) if bad in ("²", "٣") else None
                n = len(f.asked)
                for bad in (0, 301, -5):
                    with self.assertRaises(ToolError) as e:
                        call(mcp_books.render_pages, "The Quiet Harbour", "1", bad)
                    self.assertTrue(str(e.exception).endswith("."), e.exception)
                self.assertEqual(len(f.asked), n)                          # refused before drawing
            with fake_compile(pages=3), mock.patch.object(
                    compose, "compile_book", return_value=types.SimpleNamespace(pages=[0] * 3, error="bad font")):
                out = call(mcp_books.render_pages, "The Quiet Harbour", "1")
                self.assertIn("The book doesn't set now (bad font); these are the last good pages.", out[0])
            with fake_compile(pages=2) as f:
                call(mcp_books.render_pages, "The Quiet Harbour")
                self.assertEqual(f.asked[-1][0], [1, 2])

    def test_export_pdf(self):
        with temp_library():
            make_book()
            with mock.patch.object(compose, "export_pdf", return_value=FAKE_PDF):
                out = call(mcp_books.export_pdf, "The Quiet Harbour")
            self.assertEqual(out, "Exported The Quiet Harbour 2026-11-13.pdf: 12 pages, 33.8 KB to C:/x/exports/the.pdf")
            with mock.patch.object(compose, "export_pdf", return_value={**FAKE_PDF, "path": None}):
                out = call(mcp_books.export_pdf, "The Quiet Harbour")
            self.assertIn("couldn't be kept in the book's exports folder", out)

    def test_preflight(self):
        with temp_library():
            make_book()
            with fake_checks():
                out = call(mcp_books.preflight, "The Quiet Harbour")
            self.assertEqual(out.splitlines(), ["1 warning", "warn page 5 01-low-tide.md: A line is left alone.",
                                                "info: Fonts are embedded."])
            with fake_checks([]) as run:
                self.assertEqual(call(mcp_books.preflight, "The Quiet Harbour"), "1 warning")
                self.assertEqual(run.call_args.args[1], "The Quiet Harbour")

    def test_research_tools(self):
        with temp_library():
            make_book()
            q = "the quiet harbour"
            self.assertEqual(json.loads(call(mcp_books.list_research))["items"], [])
            out = call(mcp_books.add_research, {"type": "note", "title": "Tide table", "text": "High at *six*.", "tags": ["sea"]}, book=q)
            self.assertTrue(out.startswith("Added note ") and out.endswith(" to The Quiet Harbour"), out)
            out = call(mcp_books.add_research, {"type": "quote", "text": "Mud keeps count.", "source": "vandijk2019", "locator": "p. 3"}, book=q)
            self.assertTrue(out.startswith("Added quote "), out)
            call(mcp_books.add_research, {"type": "note", "title": "Shared idea", "text": "Elsewhere."})
            listed = json.loads(call(mcp_books.list_research, q))
            self.assertEqual(listed["board"], "The Quiet Harbour")
            self.assertEqual(len(listed["items"]), 2)
            for it in listed["items"]:
                self.assertFalse({"pos", "thumb", "html"} & set(it))
            self.assertEqual(len(json.loads(call(mcp_books.list_research, q, kind="quote"))["items"]), 1)
            self.assertEqual([i["title"] for i in json.loads(call(mcp_books.list_research, q, tag="sea"))["items"]], ["Tide table"])
            self.assertEqual([i["title"] for i in json.loads(call(mcp_books.list_research))["items"]], ["Shared idea"])
            hits = json.loads(call(mcp_books.list_research, q, query="mud"))
            self.assertEqual(len(hits["items"]), 1)
            item = json.loads(call(mcp_books.read_research, next(i["id"] for i in listed["items"] if i["title"] == "Tide table"), q))
            self.assertEqual(item["text"].strip(), "High at *six*.")
            self.assertNotIn("html", item)
            with self.assertRaises(ToolError):
                call(mcp_books.read_research, "nope", q)
            with self.assertRaises(ToolError):
                call(mcp_books.list_research, "No Such Book")
            with self.assertRaises(ToolError):
                call(mcp_books.add_research, {"type": "note", "text": "x"}, book="No Such Book")
            with self.assertRaises(ToolError):
                call(mcp_books.add_research, {"type": "bogus"}, book=q)

    def test_research_list_is_capped(self):
        with temp_library():
            make_book()
            with mock.patch.object(mcp_books, "RESEARCH_MAX", 2):
                for i in range(3):
                    call(mcp_books.add_research, {"type": "note", "title": f"N{i}", "text": "x"})
                got = json.loads(call(mcp_books.list_research))
            self.assertEqual((len(got["items"]), got["items_more"]), (2, 1))

    def test_research_clips(self):
        with temp_library():
            make_book()
            clip = {"type": "clip", "url": "https://example.org/page"}
            with self.assertRaises(ToolError) as e:
                call(mcp_books.add_research, {"type": "clip"})
            self.assertIn("A clip needs a url", str(e.exception))
            fake = mock.Mock(return_value={"id": "page", "type": "clip"})
            with mock.patch.object(research.Research, "clip", new=lambda self, board, url, **kw: fake(board, url)):
                out = call(mcp_books.add_research, clip, book="The Quiet Harbour")
            fake.assert_called_once_with("The Quiet Harbour", "https://example.org/page")
            self.assertEqual(out, "Added clip page to The Quiet Harbour")
            fake.return_value = {"id": "page-2", "type": "clip", "warning": "No picture of the page"}
            with mock.patch.object(research.Research, "clip", new=lambda self, board, url, **kw: fake(board, url)):
                out = call(mcp_books.add_research, clip)
            self.assertTrue(out.endswith("(No picture of the page)"), out)

    def test_suggest_echoes_the_stored_label(self):
        with temp_library():
            books, book, chapter = make_book()
            out = call(mcp_books.suggest, "The Quiet Harbour", [
                {"piece": chapter, "kind": "comment", "quote": "mud", "text": "Which mud?"},
                {"piece": chapter, "kind": "index", "quote": "boats"}], label="  Round   one ")
            self.assertTrue(out.startswith('Added 2 suggestions (group "Round one").'), out)
            out = call(mcp_books.suggest, "The Quiet Harbour", [
                {"piece": chapter, "kind": "comment", "quote": "lean", "text": "Lean how?"}], label=" Verbs ")
            self.assertTrue(out.startswith('Added 1 suggestion (label "Verbs").'), out)
            one = [s for s in json.loads(call(mcp_books.list_suggestions, "The Quiet Harbour")) if s["quote"] == "lean"]
            self.assertEqual(one[0]["label"], "Verbs")

    def test_list_suggestions_says_when_the_piece_left(self):
        with temp_library():
            books, book, chapter = make_book()
            call(mcp_books.suggest, "The Quiet Harbour", [
                {"piece": chapter, "kind": "comment", "quote": "mud", "text": "Which mud?"}])
            self.assertIs(json.loads(call(mcp_books.list_suggestions, "The Quiet Harbour"))[0]["missing"], False)
            books.delete_piece(book, chapter)
            got = json.loads(call(mcp_books.list_suggestions, "The Quiet Harbour"))
            self.assertEqual([(s["found"], s["missing"]) for s in got], [(False, True)])

    def test_suggest_doc_names_the_item_limit(self):
        self.assertIn(f"Send up to {suggestions.MAX_ITEMS} items", mcp_books.SUGGEST_DOC)


if __name__ == "__main__":
    unittest.main()
