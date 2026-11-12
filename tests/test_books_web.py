"""The Books API over a live server."""
import base64
import http.client
import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from studio import config
from studio.books import AUTO, FORMS, KINDS, PIECE_KINDS
from tests.support import temp_studio

STATIC = Path(__file__).resolve().parent.parent / "studio" / "static"

PNG = base64.b64encode(
    base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
).decode()


def doc_of(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def make(st, title="Harbour-Lights"):
    code, book = st.post("/api/books", {"title": title, "kind": "memoir"})
    assert code == 200, book
    return book


class BooksWebTest(unittest.TestCase):
    def test_book_lifecycle_over_http(self):
        with temp_studio() as st:
            self.assertEqual(st.get("/api/books"), (200, []))
            bid = make(st)["id"]
            shelf = st.get("/api/books")[1]
            self.assertEqual([b["id"] for b in shelf], [bid])
            code, read = st.get(f"/api/book?b={bid}")
            self.assertEqual(code, 200)
            self.assertEqual(read["title"], "Harbour-Lights")
            code, piece = st.post("/api/book/piece/new", {"b": bid, "kind": "chapter", "title": "The Pier"})
            self.assertEqual(code, 200)
            f = piece["file"]
            code, got = st.get(f"/api/book/piece?b={bid}&f={f}")
            self.assertEqual(got["doc"], piece["doc"])
            doc = {**piece["doc"], "content": [piece["doc"]["content"][0], doc_of("Gulls over the water.")["content"][0]]}
            code, saved = st.post("/api/book/piece", {"b": bid, "f": f, "doc": doc, "base_mtime": got["mtime"]})
            self.assertEqual(code, 200, saved)
            self.assertIn("mtime", saved)
            self.assertEqual(saved["counts"]["words"], 4)           # the title is not counted
            self.assertIn("snapshot", saved)
            again = st.get(f"/api/book/piece?b={bid}&f={f}")[1]
            self.assertEqual(again["doc"], doc)
            hist = st.get(f"/api/book/history?b={bid}&f={f}")[1]
            self.assertEqual(hist[0]["when"], saved["snapshot"])
            snap = st.get(f"/api/book/snapshot?b={bid}&f={f}&when={saved['snapshot']}")[1]
            self.assertIn("Gulls over the water.", snap["md"])
            self.assertEqual(snap["doc"], doc)
            code, upd = st.post("/api/book/update", {"b": bid, "fields": {"subtitle": "A memoir"}})
            self.assertEqual(code, 200)
            self.assertEqual(upd["subtitle"], "A memoir")
            self.assertEqual(st.post("/api/book/edition", {"b": bid, "name": "first"})[0], 200)
            self.assertEqual(st.post("/api/book/restore", {"b": bid, "f": f, "when": saved["snapshot"]})[0], 200)
            self.assertEqual(st.post("/api/book/piece/delete", {"b": bid, "f": f})[0], 200)
            self.assertEqual(st.get(f"/api/book/piece?b={bid}&f={f}")[0], 404)
            self.assertEqual(st.post("/api/book/delete", {"b": bid})[0], 200)
            self.assertEqual(st.get("/api/books"), (200, []))

    def test_a_linked_poem_is_read_fresh(self):
        with temp_studio() as st:
            poem = st.root / "Reeks" / "Gedicht"
            poem.mkdir(parents=True)
            (poem / "poem.json").write_text(json.dumps({"title": "Gedicht", "lines": ["een", "twee"]}), encoding="utf-8")
            url = "/api/book/poem?src=" + quote("Reeks/Gedicht")
            self.assertEqual(st.get(url), (200, {"title": "Gedicht", "lines": ["een", "twee"]}))
            (poem / "poem.json").write_text(json.dumps({"title": "Gedicht", "lines": ["drie"]}), encoding="utf-8")
            self.assertEqual(st.get(url)[1]["lines"], ["drie"])
            self.assertEqual(st.get("/api/book/poem?src=Reeks/Weg"), (200, {"missing": True}))
            self.assertEqual(st.get("/api/book/poem?src=..%2F..%2Fx"), (200, {"missing": True}))
            self.assertEqual(st.get("/api/book/poem?src=" + quote("C:/Windows"))[1], {"missing": True})      # a drive prefix
            self.assertEqual(st.get("/api/book/poem?src=" + quote("Reeks/C:Gedicht"))[1], {"missing": True})

    def test_editions_over_http(self):
        with temp_studio() as st:
            bid = make(st)["id"]
            self.assertEqual(st.get(f"/api/book/editions?b={bid}"), (200, []))
            self.assertEqual(st.post("/api/book/edition", {"b": bid, "name": "First proof"})[0], 200)
            code, got = st.get(f"/api/book/editions?b={bid}")
            self.assertEqual(code, 200)
            self.assertEqual([e["name"] for e in got], ["First proof"])
            self.assertRegex(got[0]["date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertEqual(st.get("/api/book/editions?b=Nope")[0], 404)
            with mock.patch("studio.routes_books.subprocess.Popen") as popen:
                code, r = st.post("/api/book/reveal", {"b": bid, "edition": f"{got[0]['date']} First proof"})
            self.assertEqual(code, 200)
            self.assertIn(got[0]["path"], popen.call_args.args[0][-1])
            with mock.patch("studio.routes_books.subprocess.Popen") as popen:
                self.assertEqual(st.post("/api/book/reveal", {"b": bid, "edition": "../../x"})[0], 404)
                self.assertEqual(st.post("/api/book/reveal", {"b": bid, "edition": "2000-01-01 Nothing"})[0], 404)
            popen.assert_not_called()

    def test_stale_save_is_refused(self):
        with temp_studio() as st:
            bid = make(st)["id"]
            f = st.post("/api/book/piece/new", {"b": bid, "kind": "chapter", "title": "One"})[1]["file"]
            opened = st.get(f"/api/book/piece?b={bid}&f={f}")[1]
            st.post("/api/book/piece", {"b": bid, "f": f, "doc": doc_of("First window."), "base_mtime": opened["mtime"]})
            code, body = st.post("/api/book/piece", {"b": bid, "f": f, "doc": doc_of("Second window."),
                                                      "base_mtime": opened["mtime"]})
            self.assertEqual(code, 409)
            self.assertIn("error", body)
            self.assertIn("First window.", body["current"]["md"])
            code, body = st.post("/api/book/piece", {"b": bid, "f": f, "doc": doc_of("Second window."),
                                                      "base_mtime": opened["mtime"], "force": True})
            self.assertEqual(code, 200)
            self.assertIn("Second window.", st.get(f"/api/book/piece?b={bid}&f={f}")[1]["md"])

    def test_search_and_replace_over_http(self):
        with temp_studio() as st:
            bid = make(st)["id"]
            f = st.post("/api/book/piece/new", {"b": bid, "kind": "chapter", "title": "One"})[1]["file"]
            st.post("/api/book/piece", {"b": bid, "f": f, "doc": doc_of("The tide came in. The Tide went out.")})
            self.assertEqual(len(st.get(f"/api/book/search?b={bid}&q=tide")[1]), 2)
            self.assertEqual(len(st.get(f"/api/book/search?b={bid}&q=tide&case=1")[1]), 1)
            self.assertEqual(st.get(f"/api/book/search?b={bid}&q=tid&whole=1")[1], [])
            code, out = st.post("/api/book/replace", {"b": bid, "q": "tide", "repl": "sea", "f": f, "index": 0})
            self.assertEqual((code, out["replaced"]), (200, 1))
            code, out = st.post("/api/book/replace", {"b": bid, "q": "Tide", "repl": "sea", "case": True})
            self.assertEqual(out["replaced"], 1)
            md = st.get(f"/api/book/piece?b={bid}&f={f}")[1]["md"]
            self.assertIn("The sea came in. The sea went out.", md)
            items = [{"id": "a1", "type": "book", "title": "A Book"}]
            self.assertEqual(st.post("/api/book/sources", {"b": bid, "items": items})[0], 200)
            self.assertEqual(st.get(f"/api/book/sources?b={bid}")[1][0]["id"], "a1")

    def test_image_upload_and_serving(self):
        with temp_studio() as st:
            bid = make(st)["id"]
            code, out = st.post("/api/book/image", {"b": bid, "name": "pier.png", "data": PNG})
            self.assertEqual(code, 200)
            self.assertEqual(out["src"], "../images/pier.png")
            code, data = st.get(f"/bookfiles/{bid.replace(' ', '%20')}/images/pier.png")
            self.assertEqual(code, 200)
            self.assertTrue(data.startswith(b"\x89PNG"))
            self.assertIn(st.get(f"/files/Books/{bid.replace(' ', '%20')}/images/pier.png")[0], (400, 404))     # /files/ is Poems
            self.assertEqual(st.post("/api/book/image", {"b": bid, "name": "x.png", "data": "!!!"})[0], 400)
            self.assertEqual(st.post("/api/book/image", {"b": bid, "name": "x.svg", "data": PNG})[0], 400)

    def test_export_over_http(self):
        """An export writes a file (the dated copy in exports/), so it is a POST with the Origin and JSON checks."""
        with temp_studio() as st:
            bid = make(st, "Één week")["id"]
            code, data = st.post("/api/book/export", {"b": bid, "format": "docx"})
            self.assertEqual(code, 200)
            self.assertTrue(data.startswith(b"PK"))
            req = urllib.request.Request(st.url + "/api/book/export", data=json.dumps({"b": bid, "format": "md"}).encode(),
                                         method="POST", headers={"Origin": st.url, "Content-Type": "application/json"})
            with urllib.request.urlopen(req) as r:
                self.assertEqual(r.headers["Content-Disposition"],
                                 "attachment; filename=\"Een week.md\"; filename*=UTF-8''%C3%89%C3%A9n%20week.md")
            self.assertEqual(st.post("/api/book/export", {"b": bid, "format": "pdf"})[0], 400)
            self.assertEqual(st.post("/api/book/export", {"b": "nope", "format": "md"})[0], 404)
            self.assertEqual(st.get(f"/api/book/export?b={quote(bid)}&format=md")[0], 404)       # no export by GET
            foreign = urllib.request.Request(st.url + "/api/book/export", data=b'{"b": "x", "format": "md"}', method="POST",
                                             headers={"Origin": "http://example.com", "Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(foreign)
            self.assertEqual(e.exception.code, 403)
            kept = sorted(p.name for p in (config.BOOKS / bid / "exports").iterdir())
            self.assertEqual(len(kept), 2)
            self.assertRegex(kept[0], r"^Één week \d{4}-\d{2}-\d{2} \d{4}\.docx$")
            self.assertRegex(kept[1], r"^Één week \d{4}-\d{2}-\d{2} \d{4}\.md$")

    def test_a_save_says_which_snapshot_it_made(self):
        with temp_studio() as st:
            bid = make(st)["id"]
            f = st.post("/api/book/piece/new", {"b": bid, "kind": "chapter", "title": "One"})[1]["file"]
            opened = st.get(f"/api/book/piece?b={bid}&f={f}")[1]
            code, first = st.post("/api/book/piece", {"b": bid, "f": f, "doc": doc_of("Words."), "base_mtime": opened["mtime"]})
            self.assertEqual(code, 200)
            self.assertRegex(first["snapshot"], r"^\d{4}-\d{2}-\d{2}T\d{4}$")         # the first save that changes it
            self.assertEqual([h["when"] for h in st.get(f"/api/book/history?b={bid}&f={f}")[1]], [first["snapshot"]])
            code, again = st.post("/api/book/piece", {"b": bid, "f": f, "doc": doc_of("More words."), "base_mtime": first["mtime"]})
            self.assertNotIn("snapshot", again)                                         # too soon, not leaving
            code, leaving = st.post("/api/book/piece", {"b": bid, "f": f, "doc": doc_of("More words."),
                                                        "base_mtime": again["mtime"], "leaving": True})
            self.assertEqual(leaving["snapshot"], st.get(f"/api/book/history?b={bid}&f={f}")[1][0]["when"])

    def test_spaces_and_diacritics_over_http(self):
        with temp_studio() as st:
            for title in ("Één week", "Small Things"):
                bid = make(st, title)["id"]
                qb = quote(bid)
                self.assertEqual(st.get(f"/api/book?b={qb}")[1]["title"], title)
                piece = st.post("/api/book/piece/new", {"b": bid, "kind": "chapter", "title": "Één dag in Genève"})[1]
                qf = quote(piece["file"])
                code, got = st.get(f"/api/book/piece?b={qb}&f={qf}")
                self.assertEqual((code, got["title"]), (200, "Één dag in Genève"))
                self.assertEqual(st.get(f"/api/book/history?b={qb}&f={qf}")[0], 200)
                code, out = st.post("/api/book/image", {"b": bid, "name": "één plaatje.png", "data": PNG})
                self.assertEqual(code, 200)
                name = out["src"].rsplit("/", 1)[1]
                code, data = st.get(f"/bookfiles/{qb}/images/{quote(name)}")
                self.assertEqual(code, 200)
                self.assertTrue(data.startswith(b"\x89PNG"))

    def test_false_flags_are_false(self):
        with temp_studio() as st:
            bid = make(st)["id"]
            f = st.post("/api/book/piece/new", {"b": bid, "kind": "chapter", "title": "One"})[1]["file"]
            opened = st.get(f"/api/book/piece?b={bid}&f={f}")[1]
            st.post("/api/book/piece", {"b": bid, "f": f, "doc": doc_of("A."), "base_mtime": opened["mtime"]})
            code, _ = st.post("/api/book/piece", {"b": bid, "f": f, "doc": doc_of("B."),
                                                  "base_mtime": opened["mtime"], "force": "false"})
            self.assertEqual(code, 409)

    def test_files_under_books_are_confined(self):
        with temp_studio() as st:
            bid = make(st)["id"]
            b = bid.replace(" ", "%20")
            st.post("/api/book/image", {"b": bid, "name": "a.png", "data": PNG})
            host, port = st.url[len("http://"):].split(":")

            def raw(path):
                c = http.client.HTTPConnection(host, int(port), timeout=10)
                c.request("GET", path)
                r = c.getresponse()
                r.read()
                c.close()
                return r.status
            for path in ("/bookfiles/../Poems/x/poem.json", f"/bookfiles/{b}/.studio/days.json",
                         f"/bookfiles/{b}/book.json", f"/bookfiles/{b}/manuscript/x.md",
                         "/bookfiles/%2e%2e/Poems/x/poem.json", "/bookfiles/.trash/a.png",
                         f"/bookfiles/{b}/images/nope.png", "/bookfiles//etc/passwd", "/bookfiles/C:/x.png"):
                self.assertIn(raw(path), (400, 404), path)
            (st.root.parent / "Books" / bid / "images" / "v.svg").write_text("<svg/>")
            self.assertIn(raw(f"/bookfiles/{b}/images/v.svg"), (400, 404))
            self.assertEqual(raw(f"/bookfiles/{b}/images/a.png"), 200)

    def test_a_poems_series_called_books_keeps_its_files(self):
        """Book images have their own prefix (/bookfiles/), so /files/Books/... is a Poems series' like any other."""
        with temp_studio() as st:
            poem = st.root / "Books" / "Een gedicht"
            poem.mkdir(parents=True)
            (poem / "poem.json").write_text(json.dumps({"title": "Een gedicht", "lines": ["regel"]}), encoding="utf-8")
            (poem / "slide.png").write_bytes(base64.b64decode(PNG))
            code, data = st.get("/files/Books/Een%20gedicht/slide.png")
            self.assertEqual(code, 200)
            self.assertTrue(data.startswith(b"\x89PNG"))

    def test_stamp_carries_books(self):
        with temp_studio() as st:
            before = st.get("/api/stamp")[1]
            self.assertIn("stamp", before)
            self.assertIn("books", before)
            make(st)
            self.assertGreater(st.get("/api/stamp")[1]["books"], before["books"])

    def test_kinds_are_served(self):
        with temp_studio() as st:
            code, got = st.get("/api/books/kinds")
            self.assertEqual(code, 200)
            kinds = got["kinds"]
            self.assertEqual(list(kinds), list(KINDS))                  # in the store's order
            self.assertEqual(kinds, json.loads(json.dumps(KINDS)))       # features, starting pieces and back pages
            # the front end's lists of piece kinds, forms and auto pages are the store's (no copies in the scripts)
            self.assertEqual((got["pieces"], got["forms"], got["autos"]), (list(PIECE_KINDS), list(FORMS), list(AUTO)))
            for script in ("book.js", "book-editor.js"):
                text = (STATIC / script).read_text(encoding="utf-8")
                self.assertNotIn('"introduction", "prologue"', text, script)
                self.assertNotIn('"essay", "letter"', text, script)

    def test_style_sheet_over_http(self):
        with temp_studio() as st:
            bid = make(st)["id"]
            sheet = {"quotes": "„…”", "numbers": "digits", "terms": [{"use": "e-mail", "not": ["email"], "note": ""}], "notes": ""}
            code, r = st.post("/api/book/update", {"b": bid, "fields": {"style_sheet": sheet}})
            self.assertEqual((code, r["style_sheet"]), (200, sheet))
            self.assertEqual(st.get(f"/api/book?b={bid}")[1]["style_sheet"], sheet)

    def test_unknown_book_is_404(self):
        with temp_studio() as st:
            self.assertEqual(st.get("/api/book?b=Nope"), (404, {"error": "There's no book called Nope in Books."}))
            self.assertEqual(st.get("/api/book/piece?b=Nope&f=x.md")[0], 404)
            self.assertEqual(st.post("/api/book/delete", {"b": "Nope"})[0], 404)
            bid = make(st)["id"]
            self.assertEqual(st.get(f"/api/book/piece?b={bid}&f=nope.md")[0], 404)
            self.assertEqual(st.get(f"/api/book/piece?b={bid}&f=../book.json")[0], 404)
            self.assertEqual(st.post("/api/books", {"title": ""})[0], 400)

    def test_import_proposes_then_commits(self):
        import io

        import docx
        d = docx.Document()
        d.add_paragraph("IMPORTED BOOK", style="Title")
        d.add_paragraph("Voorwoord", style="Heading 1")
        d.add_paragraph("Hello there.")
        d.add_paragraph("Chapter One", style="Heading 1")
        d.add_picture(io.BytesIO(base64.b64decode(PNG)))
        buf = io.BytesIO()
        d.save(buf)
        with temp_studio() as st:
            code, prop = st.post("/api/book/import", {"name": "x.docx", "data": base64.b64encode(buf.getvalue()).decode()})
            self.assertEqual(code, 200, prop)
            self.assertEqual(prop["title"], "Imported Book")
            self.assertEqual([p["kind"] for p in prop["pieces"]], ["foreword", "chapter"])
            self.assertEqual(st.get("/api/books"), (200, []))            # nothing written yet
            code, book = st.post("/api/book/import/commit", {**prop, "kind": "memoir", "language": "en"})
            self.assertEqual(code, 200, book)
            self.assertEqual([b["id"] for b in st.get("/api/books")[1]], ["Imported Book"])
            self.assertEqual([e.get("kind") or e["auto"] for e in book["contents"]],
                             ["half-title", "title-page", "copyright", "toc", "foreword", "chapter", "notes"])
            self.assertTrue((st.root.parent / "Books" / "Imported Book" / "images" / "image-1.png").exists())
            self.assertEqual(st.post("/api/book/import", {"name": "x.pdf", "data": "AAAA"})[0], 400)
            code, err = st.post("/api/book/import", {"name": "x.docx", "data": base64.b64encode(b"nope").decode()})
            self.assertEqual(code, 400)
            self.assertEqual(st.post("/api/book/import", {"name": "x.md"})[0], 400)


if __name__ == "__main__":
    unittest.main()
