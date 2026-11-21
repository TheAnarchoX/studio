"""The research board API over a live server."""
import base64
import io
import json
import unittest
import urllib.request
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from PIL import Image

from studio import clip, config
from tests.support import temp_studio


def picture(fmt="PNG", size=(900, 600)):
    out = io.BytesIO()
    Image.new("RGB", size, (30, 90, 160)).save(out, fmt)
    return out.getvalue()


def make(st, title="Harbour-Lights"):
    code, book = st.post("/api/books", {"title": title, "kind": "memoir"})
    assert code == 200, book
    return book["id"]


def fetch(st, path):
    """(status, body bytes, headers) of a GET, whatever the status."""
    try:
        with urllib.request.urlopen(urllib.request.Request(st.url + path), timeout=10) as r:
            return r.status, r.read(), r.headers
    except HTTPError as e:
        return e.code, e.read(), e.headers


def upload(st, bid, name="pier.png", data=None, **extra):
    raw = data if data is not None else picture()
    return st.post("/api/research/image", {"b": bid, "name": name, "data": base64.b64encode(raw).decode(), **extra})


class ResearchWebTest(unittest.TestCase):
    def test_board_lifecycle_over_http(self):
        with temp_studio() as st:
            bid = make(st)
            code, note = st.post("/api/research/item", {"b": bid, "fields": {"type": "note", "title": "Gulls", "text": "Loud."},
                                                         "at": {"x": 10, "y": 20}})
            self.assertEqual(code, 200, note)
            self.assertEqual((note["id"], note["type"]), ("gulls", "note"))
            board = st.get(f"/api/research?b={bid}")[1]
            self.assertEqual([i["id"] for i in board["items"]], ["gulls"])
            self.assertEqual(board["items"][0]["pos"]["x"], 10)
            self.assertEqual([b["board"] for b in st.get("/api/research/boards")[1]], [None, bid])
            self.assertEqual(st.get(f"/api/research/item?b={bid}&id=gulls")[1]["text"], "Loud.\n")
            self.assertIsInstance(st.get(f"/api/research/stamp?b={bid}")[1]["stamp"], float)
            code, upd = st.post("/api/research/update", {"b": bid, "id": "gulls", "fields": {"text": "Louder."},
                                                          "base_mtime": note["mtime"]})
            self.assertEqual(code, 200, upd)
            self.assertEqual(upd["text"], "Louder.\n")
            code, lay = st.post("/api/research/layout", {"b": bid, "items": {"gulls": {"x": 50, "y": 60}},
                                                          "frames": [{"id": "f-one", "x": 0, "y": 0, "w": 400, "h": 300, "title": "Birds"}]})
            self.assertEqual(code, 200, lay)
            board = st.get(f"/api/research?b={bid}")[1]
            self.assertEqual((board["items"][0]["pos"]["x"], board["frames"][0]["id"]), (50, "f-one"))
            code, gone = st.post("/api/research/delete", {"b": bid, "ids": ["gulls"]})
            self.assertEqual(code, 200)
            self.assertEqual(len(gone["trash"]), 1)
            self.assertTrue(gone["trash"][0].endswith("gulls.md"))
            self.assertNotIn("/", gone["trash"][0].replace("\\", "/"))
            self.assertEqual(st.get(f"/api/research?b={bid}")[1]["items"], [])
            code, back = st.post("/api/research/restore", {"b": bid, "names": gone["trash"]})
            self.assertEqual(code, 200, back)
            self.assertEqual([i["id"] for i in back["items"]], ["gulls"])
            self.assertEqual(len(st.get(f"/api/research?b={bid}")[1]["items"]), 1)
            # the shared board is the one without b (missing, empty or null)
            self.assertEqual(st.post("/api/research/item", {"fields": {"type": "note", "title": "Shared"}})[0], 200)
            self.assertEqual(st.post("/api/research/item", {"b": "", "fields": {"type": "note", "title": "Also"}})[0], 200)
            self.assertEqual(st.post("/api/research/item", {"b": None, "fields": {"type": "note", "title": "Too"}})[0], 200)
            ids = [i["id"] for i in st.get("/api/research")[1]["items"]]
            self.assertEqual(sorted(ids), ["also", "shared", "too"])
            self.assertEqual(len(st.get("/api/research?b=")[1]["items"]), 3)
            self.assertEqual([i["id"] for i in st.get(f"/api/research?b={bid}")[1]["items"]], ["gulls"])

    def test_stale_update_409_over_http(self):
        with temp_studio() as st:
            note = st.post("/api/research/item", {"fields": {"type": "note", "title": "A", "text": "one"}})[1]
            self.assertEqual(st.post("/api/research/update", {"id": "a", "fields": {"text": "two"}, "base_mtime": note["mtime"]})[0], 200)
            code, body = st.post("/api/research/update", {"id": "a", "fields": {"text": "three"}, "base_mtime": note["mtime"]})
            self.assertEqual(code, 409)
            self.assertIn("current", body)
            self.assertEqual(body["current"]["text"], "two\n")
            code, forced = st.post("/api/research/update", {"id": "a", "fields": {"text": "three"},
                                                            "base_mtime": note["mtime"], "force": True})
            self.assertEqual((code, forced["text"]), (200, "three\n"))

    def test_image_upload_and_thumbnail(self):
        with temp_studio() as st:
            bid = make(st)
            code, item = upload(st, bid)
            self.assertEqual(code, 200, item)
            self.assertEqual((item["type"], item["file"]), ("image", "files/pier.png"))
            self.assertRegex(item["thumb"], rf"^/researchfiles/{bid}/pier\.png\?w=640&v=\d+$")
            code, data, headers = fetch(st, f"/researchfiles/{bid}/pier.png")
            self.assertEqual((code, headers["Content-Type"]), (200, "image/png"))
            self.assertEqual(Image.open(io.BytesIO(data)).size, (900, 600))
            code, data, headers = fetch(st, f"/researchfiles/{bid}/pier.png?w=320")
            self.assertEqual((code, headers["Content-Type"]), (200, "image/jpeg"))
            self.assertEqual(headers["Cache-Control"], "max-age=31536000, immutable")
            self.assertEqual(Image.open(io.BytesIO(data)).size, (320, 213))
            folder = config.CACHE / "research-thumbs"
            cached = list(folder.glob("*.jpg"))
            self.assertEqual(len(cached), 1)
            mtime = cached[0].stat().st_mtime_ns
            self.assertEqual(fetch(st, f"/researchfiles/{bid}/pier.png?w=320")[1], data)
            self.assertEqual(cached[0].stat().st_mtime_ns, mtime)           # the second request used the cache file
            self.assertEqual(len(list(folder.glob("*"))), 1)               # and left no temp file behind
            code, data, headers = fetch(st, f"/researchfiles/{bid}/pier.png?w=999")      # not a thumbnail size
            self.assertEqual((code, headers["Content-Type"]), (200, "image/png"))
            self.assertEqual(Image.open(io.BytesIO(data)).size, (900, 600))
            self.assertEqual(upload(st, bid, "bad.png", b"not a picture")[0], 400)
            code, body = st.post("/api/research/image", {"b": bid, "name": "x.png", "data": "!!!"})
            self.assertEqual((code, body["error"]), (400, "The image couldn't be read."))
            self.assertEqual(st.post("/api/research/image", {"b": bid, "name": "x.png"})[0], 400)

    def test_pdf_is_a_download(self):
        with temp_studio() as st:
            bid = make(st)
            files = next(p for p in config.BOOKS.iterdir() if p.is_dir()) / "research" / "files"
            files.mkdir(parents=True)
            (files / "page.pdf").write_bytes(b"%PDF-1.4\n")
            code, data, headers = fetch(st, f"/researchfiles/{bid}/page.pdf")
            self.assertEqual((code, data, headers["Content-Type"]), (200, b"%PDF-1.4\n", "application/pdf"))
            self.assertIn("attachment", headers["Content-Disposition"])

    def test_researchfiles_confinement(self):
        with temp_studio() as st:
            bid = make(st)
            upload(st, bid)
            st.post("/api/research/item", {"b": bid, "fields": {"type": "note", "title": "N"}})
            st.post("/api/research/delete", {"b": bid, "ids": ["pier"]})
            for path in (f"/researchfiles/{bid}/../board.json", f"/researchfiles/{bid}/%2e%2e/board.json",
                         f"/researchfiles/{bid}/..%2F..%2Fbook.json", f"/researchfiles/{bid}/.trash/x.png",
                         f"/researchfiles/{bid}/n.md", "/researchfiles/nobook/pier.png", f"/researchfiles/{bid}/missing.png",
                         "/researchfiles/_shared/pier.png", "/researchfiles/", f"/researchfiles/{bid}"):
                self.assertEqual(fetch(st, path)[0], 404, path)

    def test_use_over_http(self):
        with temp_studio() as st:
            bid = make(st)
            csl = {"type": "book", "title": "Kind", "issued": {"date-parts": [[1998]]},
                   "author": [{"family": "Dijk", "non-dropping-particle": "van"}]}
            src = st.post("/api/research/item", {"b": bid, "fields": {"type": "source", "csl": csl}})[1]
            self.assertEqual(st.get(f"/api/book/sources?b={bid}")[1], [])
            code, used = st.post("/api/research/use", {"book": bid, "b": bid, "id": src["id"]})
            self.assertEqual(code, 200, used)
            self.assertEqual((used["kind"], used["added"]), ("cite", True))
            sources = st.get(f"/api/book/sources?b={bid}")[1]
            self.assertEqual([s["id"] for s in sources], [used["key"]])
            cit = st.get(f"/api/research/citable?b={bid}")[1]
            self.assertIn(used["key"], [c["key"] for c in cit])
            self.assertEqual(st.post("/api/research/use", {"book": "nobook", "b": bid, "id": src["id"]})[0], 404)

    def test_move_search_and_boards(self):
        with temp_studio() as st:
            bid = make(st)
            st.post("/api/research/item", {"b": bid, "fields": {"type": "note", "title": "Lighthouse", "text": "beam"}})
            hits = st.get(f"/api/research/search?b={bid}&q=lighthouse")[1]
            self.assertEqual([h["id"] for h in hits], ["lighthouse"])
            self.assertEqual(st.get("/api/research/search?q=lighthouse")[1], [])
            self.assertEqual(len(st.get("/api/research/search?q=lighthouse&every=1")[1]), 1)
            code, moved = st.post("/api/research/move", {"b": bid, "ids": ["lighthouse"], "to": None})
            self.assertEqual(code, 200, moved)
            self.assertEqual([i["id"] for i in moved["items"]], ["lighthouse"])
            self.assertEqual(st.post("/api/research/move", {"b": bid, "ids": ["lighthouse"], "to": None})[0], 404)
            self.assertEqual(st.post("/api/research/move", {"ids": ["lighthouse"], "to": None})[0], 400)    # already there

    def test_post_checks(self):
        with temp_studio() as st:
            body = json.dumps({"fields": {"type": "note", "title": "X"}}).encode()
            req = urllib.request.Request(st.url + "/api/research/item", data=body, method="POST",
                                         headers={"Origin": "http://evil.example", "Content-Type": "application/json"})
            with self.assertRaises(HTTPError) as e:
                urllib.request.urlopen(req, timeout=10)
            self.assertEqual(e.exception.code, 403)
            req = urllib.request.Request(st.url + "/api/research/item", data=body, method="POST",
                                         headers={"Origin": st.url, "Content-Type": "text/plain"})
            with self.assertRaises(HTTPError) as e:
                urllib.request.urlopen(req, timeout=10)
            self.assertEqual(e.exception.code, 415)
            self.assertEqual(st.get("/api/research")[1]["items"], [])

    def test_clip_endpoint_refuses_loopback(self):
        with temp_studio() as st:
            code, body = st.post("/api/research/clip", {"url": st.url + "/api/research"})
            self.assertEqual((code, body["error"]),
                             (400, "Studio clips pages on the internet, not on this computer or its network."))
            self.assertEqual(st.get("/api/research")[1]["items"], [])

    def test_clip_endpoint_with_a_fake_fetch(self):
        html = (Path(__file__).resolve().parent / "fixtures" / "clip" / "article.html").read_bytes()
        url = "https://example.org/2025/03/lighthouse-year"

        def fake_fetch(address):
            return clip.Fetched(address, address, 200, "text/html", "utf-8", html)

        def fake_picture(page, address, out):
            out.write_bytes(picture("JPEG"))
            return out, ""

        with temp_studio() as st, mock.patch.object(clip, "fetch", fake_fetch), mock.patch.object(clip, "picture", fake_picture):
            bid = make(st)
            code, item = st.post("/api/research/clip", {"b": bid, "url": url, "at": {"x": 5, "y": 6}})
            self.assertEqual(code, 200, item)
            self.assertEqual((item["type"], item["url"], item["pos"]["x"]), ("clip", url, 5))
            self.assertEqual(item["text"], clip.readable(html.decode("utf-8"), url)["markdown"] + "\n")
            self.assertNotIn("warning", item)
            code, data, headers = fetch(st, f"/researchfiles/{bid}/{item['shot'][len('files/'):]}")
            self.assertEqual((code, headers["Content-Type"]), (200, "image/jpeg"))
            code, again = st.post("/api/research/clip", {"b": bid, "id": item["id"]})
            self.assertEqual((code, again["id"]), (200, item["id"]))
            self.assertEqual(st.post("/api/research/clip", {"b": bid, "id": "nothing"})[0], 404)
            self.assertEqual(st.post("/api/research/clip", {"b": bid, "url": 5})[0], 400)
            self.assertEqual(st.post("/api/research/clip", {"b": bid})[0], 400)
            self.assertEqual(st.post("/api/research/clip", {"b": "nobook", "url": url})[0], 404)
            self.assertEqual(len(st.get(f"/api/research?b={bid}")[1]["items"]), 1)

    def test_reveal_shows_a_clips_pdf(self):
        def fake_fetch(address):
            return clip.Fetched(address, address, 200, "application/pdf", None, b"%PDF-1.4\n")

        with temp_studio() as st, mock.patch.object(clip, "fetch", fake_fetch):
            code, item = st.post("/api/research/clip", {"url": "https://example.org/tides.pdf"})
            self.assertEqual((code, item["file"]), (200, f"files/{item['id']}.pdf"))
            with mock.patch("studio.routes_research.subprocess.Popen") as popen:
                code, body = st.post("/api/research/reveal", {"id": item["id"]})
                self.assertEqual((code, body), (200, {"ok": True}))
                args = popen.call_args[0][0]
                self.assertTrue(any(str(a).endswith(f"{item['id']}.pdf") or str(a).endswith("files") for a in args), args)
                note = st.post("/api/research/item", {"fields": {"type": "note", "title": "N"}})[1]
                code, body = st.post("/api/research/reveal", {"id": note["id"]})
                self.assertEqual((code, body["error"]), (400, "This item has no file to show."))
                self.assertEqual(st.post("/api/research/reveal", {"id": "nothing"})[0], 404)
                self.assertEqual(popen.call_count, 1)

    def test_unknown_board_is_404(self):
        with temp_studio() as st:
            self.assertEqual(st.get("/api/research?b=nobook")[0], 404)
            self.assertEqual(st.get("/api/research/stamp?b=nobook")[0], 404)
            self.assertEqual(st.get("/api/research/item?b=nobook&id=x")[0], 404)
            self.assertEqual(st.get("/api/research/item?id=nothing")[0], 404)
            self.assertEqual(st.post("/api/research/item", {"b": "nobook", "fields": {"type": "note"}})[0], 404)
            self.assertEqual(st.post("/api/research/delete", {"b": "nobook", "ids": ["x"]})[0], 404)
            self.assertEqual(st.post("/api/research/update", {"id": "nothing", "fields": {"text": "x"}})[0], 404)

    # ——— part 3, final review ———
    def test_a_file_name_with_a_percent_sign(self):
        with temp_studio() as st:
            files = config.ART / "Research" / "files"
            files.mkdir(parents=True)
            raw = picture()
            (files / "a%41.png").write_bytes(raw)
            (config.ART / "Research" / "p.md").write_text('---\ntype: "image"\nfile: "files/a%41.png"\n---\n', encoding="utf-8")
            thumb = st.get("/api/research")[1]["items"][0]["thumb"]
            self.assertTrue(thumb.startswith("/researchfiles/_shared/a%2541.png?w=640&v="), thumb)
            self.assertEqual(fetch(st, "/researchfiles/_shared/a%2541.png")[:2], (200, raw))
            self.assertEqual(fetch(st, thumb)[0], 200)
            self.assertEqual(fetch(st, "/researchfiles/_shared/aA.png")[0], 404)

    def test_thumbnails_turn_and_keep_transparency_white(self):
        with temp_studio() as st:
            files = config.ART / "Research" / "files"
            files.mkdir(parents=True)
            turned = Image.new("RGB", (400, 200), (30, 90, 160))
            exif = turned.getexif()
            exif[0x0112] = 6                                  # orientation: turn 90° clockwise to show
            turned.save(files / "turned.jpg", "JPEG", exif=exif.tobytes())
            Image.new("RGBA", (200, 100), (0, 0, 0, 0)).save(files / "clear.png")
            Image.new("LA", (200, 100), (0, 0)).save(files / "grey.png")
            pal = Image.new("P", (200, 100), 0)
            pal.putpalette([0, 0, 0] * 256)
            pal.save(files / "pal.png", transparency=0)
            code, data, _ = fetch(st, "/researchfiles/_shared/turned.jpg?w=160")
            self.assertEqual((code, Image.open(io.BytesIO(data)).size), (200, (160, 320)))
            for name in ("clear.png", "grey.png", "pal.png"):
                code, data, headers = fetch(st, f"/researchfiles/_shared/{name}?w=160")
                self.assertEqual((code, headers["Content-Type"]), (200, "image/jpeg"), name)
                self.assertTrue(all(c > 245 for c in Image.open(io.BytesIO(data)).convert("RGB").getpixel((50, 50))), name)

    def test_thumbnail_without_a_cache_folder_serves_the_file(self):
        with temp_studio() as st:
            files = config.ART / "Research" / "files"
            files.mkdir(parents=True)
            raw = picture()
            (files / "pier.png").write_bytes(raw)
            config.CACHE.mkdir(parents=True, exist_ok=True)
            (config.CACHE / "research-thumbs").write_bytes(b"a file where the folder would go")
            code, data, headers = fetch(st, "/researchfiles/_shared/pier.png?w=320")
            self.assertEqual((code, headers["Content-Type"], data), (200, "image/png", raw))

    def test_use_needs_a_book_name(self):
        with temp_studio() as st:
            src = st.post("/api/research/item", {"fields": {"type": "source", "csl": {"type": "book", "title": "T"}}})[1]
            for book in (1, ["a"], {"a": 1}, True):
                code, body = st.post("/api/research/use", {"book": book, "id": src["id"]})
                self.assertEqual((code, body["error"]), (400, "Say which book."), book)


if __name__ == "__main__":
    unittest.main()
