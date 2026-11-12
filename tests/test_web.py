"""Route tables and the guards every routed handler inherits."""
import base64
import http.client
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fontTools.ttLib import TTFont
from PIL import Image

from studio import fonts
from studio.web import Handler

from studio import routes
from tests.support import temp_studio


@routes.get("/api/_t")
def _t_get(h, q):
    h._send(200, {"x": q.get("x")})


@routes.post("/api/_t")
def _t_post(h, body):
    h._send(200, {"echo": body})


@routes.get_prefix("/_p/")
def _t_prefix(h, rest, q):
    h._send(200, {"rest": rest})


class RoutesTest(unittest.TestCase):
    def test_no_table_path_is_also_a_built_in_one(self):
        """web.py asks the route tables after its built-in GET paths and before its built-in POST paths; that would only
        matter for a path in both places, so there is none."""
        import re
        from studio import web
        src = Path(web.__file__).read_text(encoding="utf-8")
        builtin = set(re.findall(r'path == "(/[^"]*)"', src))
        for group in re.findall(r"path in \(([^)]*)\)", src):
            builtin |= set(re.findall(r'"(/[^"]*)"', group))
        self.assertIn("/api/series", builtin)
        self.assertEqual(builtin & (set(routes.GET) | set(routes.POST)), set())

    def test_registered_get_and_post_routes(self):
        with temp_studio() as st:
            self.assertEqual(st.get("/api/_t?x=1"), (200, {"x": "1"}))
            self.assertEqual(st.post("/api/_t", {"a": [1]}), (200, {"echo": {"a": [1]}}))

    def test_prefix_route(self):
        with temp_studio() as st:
            self.assertEqual(st.get("/_p/a/b"), (200, {"rest": "a/b"}))

    def test_unknown_path_is_404(self):
        with temp_studio() as st:
            self.assertEqual(st.get("/api/_nope")[0], 404)
            self.assertEqual(st.post("/api/_nope", {})[0], 404)

    def _post_raw(self, st, headers, body=b"", length=None):
        """One POST on a fresh connection, with a body (or a declared length that may differ from it)."""
        host, port = st.url[len("http://"):].split(":")
        c = http.client.HTTPConnection(host, int(port), timeout=10)
        try:
            c.putrequest("POST", "/api/_t")
            for k, v in headers.items():
                c.putheader(k, v)
            c.putheader("Content-Length", str(len(body) if length is None else length))
            c.endheaders()
            if body:
                c.send(body)
            r = c.getresponse()
            r.read()
            return r
        finally:
            c.close()

    def test_post_from_another_origin_is_403(self):
        with temp_studio() as st:
            for _ in range(30):
                r = self._post_raw(st, {"Origin": "http://evil.test", "Content-Type": "application/json"},
                                   json.dumps({}).encode())
                self.assertEqual(r.status, 403)

    def test_post_without_json_is_415(self):
        with temp_studio() as st:
            for _ in range(30):
                r = self._post_raw(st, {"Content-Type": "text/plain"}, b"hello there")
                self.assertEqual(r.status, 415)

    def test_post_too_large_is_413(self):
        with temp_studio() as st:
            # Declares 50,000,000 bytes and sends none: the server refuses without reading, so no bytes
            # are left unread on its side (unread bytes make Windows reset the connection before the reply).
            for _ in range(30):
                r = self._post_raw(st, {"Content-Type": "application/json"}, b"", length=50_000_000)
                self.assertEqual(r.status, 413)
                self.assertEqual(r.getheader("Connection"), "close")


class ThemeTest(unittest.TestCase):
    def test_index_carries_the_theme(self):
        with temp_studio() as st:
            self.assertIn(b'<html data-theme="system" ', st.get("/")[1])        # the default follows the system
            self.assertEqual(st.post("/api/settings", {"theme": "light"})[0], 200)
            code, page = st.get("/")
            self.assertEqual(code, 200)
            self.assertIn(b'data-theme="light"', page)
            self.assertEqual(st.get("/api/settings")[1]["settings"]["theme"], "light")
            self.assertEqual(st.post("/api/settings", {"theme": "sepia"})[0], 400)
            self.assertIn(b'data-theme="light"', st.get("/")[1])                # a refused value changes nothing

    def test_export_page_is_not_themed(self):
        with temp_studio() as st:
            st.post("/api/settings", {"theme": "light"})
            self.assertNotIn(b"data-theme", st.get("/static/render.html")[1])


class HomeTest(unittest.TestCase):
    def test_home_lists_palettes_looks_and_fonts(self):
        with temp_studio() as st:
            code, home = st.get("/api/home")
            self.assertEqual(code, 200)
            self.assertEqual(next(iter(home["palettes"])), "Editorial light")   # the default look's palette comes first
            self.assertEqual(home["palettes"]["Blood"], [["Black", "#0B0B0C"], ["Bone", "#E9E4DA"], ["Blood", "#7A0019"],
                                                         ["Ash", "#8C8A87"]])      # Studio 1.0's shape, for the New series dialog
            self.assertEqual(len(home["looks"]), 10)
            self.assertIn("Newsreader", home["fonts"])
            code, s = st.post("/api/series", {"name": "Night Letters", "palette": "Blood"})
            self.assertEqual((code, s["palette"][2]["hex"]), (200, "#7A0019"))

    def test_a_new_series_can_follow_a_look(self):
        with temp_studio() as st:
            code, s = st.post("/api/series", {"name": "Small Ones", "look": "Children's book"})
            self.assertEqual((code, s["look"], s["style"]["fonts"]["display"]["family"]), (200, "Children's book", "Caveat"))
            self.assertEqual(st.post("/api/series", {"name": "Other Ones", "look": "No such look"})[0], 400)


class LibraryChangeTest(unittest.TestCase):
    def test_a_new_library_gets_its_fonts_indexed(self):
        """After the library changes in Settings, the font registry is the new library's and the computer's fonts are indexed for it."""
        new = Path(tempfile.mkdtemp(prefix="studio-lib2-"))
        self.addCleanup(shutil.rmtree, new, ignore_errors=True)
        with temp_studio() as st, mock.patch.dict(os.environ):
            os.environ.pop("STUDIO_ART")
            with mock.patch.object(fonts.Registry, "start_system_index") as started:
                code, info = st.post("/api/settings", {"library": str(new), "create": True})
            self.assertEqual(code, 200)
            self.assertEqual(Path(info["library"]), new.resolve())
            self.assertEqual(fonts.registry().library, new.resolve() / "Styles" / "fonts")
            started.assert_called_once()


def save_design(st, pid, name, elements, background=None):
    d = {"name": name, "format": "45", "elements": elements, **({"background": background} if background else {})}
    return st.post("/api/design", {"id": pid, "design": d})[1]["slug"]


class StylesApiTest(unittest.TestCase):
    def test_styles_empty_library(self):
        with temp_studio() as st:
            code, out = st.get("/api/styles")
            self.assertEqual(code, 200)
            self.assertEqual(len(out["looks"]), 10)
            self.assertTrue(out["palettes"])
            self.assertEqual(out["default_look"], "Editorial light")
            self.assertEqual(out["used"], {"palettes": {}, "looks": {}, "fonts": {}})
            self.assertIsInstance(out["rules"], str)
            self.assertEqual(st.get("/api/settings")[1]["settings"]["default_look"], "Editorial light")

    def test_save_and_delete_palette_over_http(self):
        with temp_studio() as st:
            pal = {"name": "Dusk", "swatches": [{"hex": "#101820", "role": "background"}, {"hex": "#F2E9DC", "role": "text"}]}
            code, out = st.post("/api/styles/palette", {"palette": pal})
            self.assertEqual((code, out["name"], out["source"]), (200, "Dusk", "own"))
            self.assertIn("Dusk", [p["name"] for p in st.get("/api/styles")[1]["palettes"]])
            self.assertIn("Dusk", st.get("/api/home")[1]["palettes"])
            self.assertEqual(st.post("/api/styles/palette", {"palette": {"name": "", "swatches": []}})[0], 400)
            self.assertEqual(st.post("/api/styles/palette/delete", {"name": "Dusk"})[0], 200)
            self.assertNotIn("Dusk", [p["name"] for p in st.get("/api/styles")[1]["palettes"]])
            self.assertEqual(st.post("/api/styles/palette/delete", {"name": "Dusk"})[0], 400)
            look = {"name": "Dusky", "palette": "Blood", "fonts": {r: {"family": "Newsreader", "weight": 400} for r in ("display", "text", "label")}}
            self.assertEqual(st.post("/api/styles/look", {"look": look})[0], 200)
            self.assertIn("Dusky", [lk["name"] for lk in st.get("/api/styles")[1]["looks"]])
            self.assertEqual(st.post("/api/styles/look/delete", {"name": "Dusky"})[0], 200)
            code, out = st.post("/api/styles/rules", {"text": "Keep it quiet.\n"})
            self.assertEqual(code, 200)
            self.assertEqual(st.get("/api/styles")[1]["rules"], "Keep it quiet.\n")

    def test_series_style_detach_over_http(self):
        with temp_studio() as st:
            st.post("/api/series", {"name": "Night Letters", "palette": "Blood"})
            code, s = st.post("/api/series/style", {"name": "Night Letters", "look": "Riso"})
            self.assertEqual((code, s["look"]), (200, "Riso"))
            used = st.get("/api/styles")[1]["used"]
            self.assertEqual(used["looks"]["Riso"], ["Night Letters"])
            self.assertEqual(used["palettes"]["Blood"], ["Night Letters"])
            code, s = st.post("/api/series/style", {"name": "Night Letters", "detach": True})
            self.assertEqual((code, s["palette_linked"], s["look"]), (200, False, None))
            self.assertEqual(s["palette"][2]["hex"], "#7A0019")
            code, s = st.post("/api/series/style", {"name": "Night Letters", "link": "Editorial light"})
            self.assertEqual((s["look"], s["palette_linked"]), ("Editorial light", True))
            code, s = st.post("/api/series/style", {"name": "Night Letters", "fonts": {"display": {"family": "Archivo", "weight": 800}}})
            self.assertEqual(s["font_roles"]["display"]["family"], "Archivo")
            self.assertIn("Night Letters", st.get("/api/styles")[1]["used"]["fonts"]["Archivo"])
            self.assertEqual(st.post("/api/series/style", {"name": "Night Letters", "look": "No such look"})[0], 400)

    def test_used_lists_name_books_by_title(self):
        with temp_studio() as st:
            st.post("/api/series", {"name": "Night Letters", "look": "Riso"})
            self.assertEqual(st.post("/api/books", {"title": "The Quiet Year", "kind": "fiction"})[0], 200)
            st.post("/api/book/update", {"b": "The Quiet Year", "fields": {"title": "A Quiet Year", "link": "Riso"}})
            used = st.get("/api/styles")[1]["used"]
            self.assertEqual(used["looks"]["Riso"], ["Night Letters", "A Quiet Year"])      # by title, after the series
            st.post("/api/book/update", {"b": "The Quiet Year", "fields": {"palette": "Blood", "fonts": {"display": {"family": "Archivo", "weight": 800}}}})
            used = st.get("/api/styles")[1]["used"]
            self.assertEqual(used["palettes"]["Blood"], ["A Quiet Year"])
            self.assertIn("A Quiet Year", used["fonts"]["Archivo"])
            (st.root.parent / "Books" / "Broken").mkdir()
            (st.root.parent / "Books" / "Broken" / "book.json").write_text("not json", encoding="utf-8")       # left out
            self.assertEqual(st.get("/api/styles")[0], 200)

    def test_poem_details_endpoint(self):
        with temp_studio() as st:
            st.post("/api/series", {"name": "Night Letters"})
            pid = st.post("/api/poems", {"title": "A poem", "series": "Night Letters"})[1]["id"]
            code, p = st.post("/api/poem/details", {"id": pid, "author": "A. Poet"})
            self.assertEqual((code, p["author"]), (200, "A. Poet"))
            self.assertEqual(json.loads((st.root / pid / "poem.json").read_text(encoding="utf-8"))["author"], "A. Poet")
            self.assertEqual(st.post("/api/poem/details", {"id": pid, "author": "x" * 200})[0], 400)
            self.assertIsNone(st.post("/api/poem/details", {"id": pid, "author": ""})[1]["author"])

    def test_poem_style_override_and_clear(self):
        with temp_studio() as st:
            st.post("/api/series", {"name": "Night Letters"})
            pid = st.post("/api/poems", {"title": "A poem", "series": "Night Letters"})[1]["id"]
            code, p = st.post("/api/poem/style", {"id": pid, "palette": "Blood", "look": "Riso"})
            self.assertEqual(code, 200)
            self.assertEqual((p["style"]["look"], p["style"]["palette"]["name"], p["style"]["palette"]["from"]),
                             ("Riso", "Blood", "poem"))
            raw = json.loads((st.root / pid / "poem.json").read_text(encoding="utf-8"))
            self.assertEqual((raw["look"], raw["palette"]), ("Riso", "Blood"))
            code, p = st.post("/api/poem/style", {"id": pid, "clear": True})
            self.assertEqual(code, 200)
            raw = json.loads((st.root / pid / "poem.json").read_text(encoding="utf-8"))
            self.assertFalse({"look", "palette", "fonts"} & set(raw))
            self.assertEqual(p["style"]["palette"]["from"], "series")

    def test_palette_from_image_over_http(self):
        with temp_studio() as st:
            img = Image.new("RGB", (40, 40), "#CC2222")
            img.paste(Image.new("RGB", (40, 20), "#2222CC"), (0, 20))
            buf = io.BytesIO()
            img.save(buf, "PNG")
            code, out = st.post("/api/palette/from-image", {"data": base64.b64encode(buf.getvalue()).decode()})
            self.assertEqual((code, sorted(out["swatches"])), (200, ["#2222CC", "#CC2222"]))
            self.assertEqual(st.post("/api/palette/from-image", {"data": base64.b64encode(b"nope").decode()})[0], 400)
            self.assertEqual(st.post("/api/palette/from-image", {"data": "!!!"})[0], 400)

    def test_colours_used_in_a_series(self):
        with temp_studio() as st:
            st.post("/api/series", {"name": "Night Letters"})
            pid = st.post("/api/poems", {"title": "A poem", "series": "Night Letters"})[1]["id"]
            grad = {"type": "linear", "angle": 90, "stops": [{"c": "#ff0000", "p": 0}, {"c": "#00ff00", "p": 1}]}
            save_design(st, pid, "one", [
                {"type": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "fill": "#aa0000"},
                {"type": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "fill": grad, "stroke": "none"},
                {"type": "text", "x": 0, "y": 0, "w": 10, "h": 10, "text": "x", "color": "#ffffff"}], background="#101010")
            save_design(st, pid, "two", [
                {"type": "text", "x": 0, "y": 0, "w": 10, "h": 10, "text": "y", "color": "#FFFFFF"},
                {"type": "ellipse", "x": 0, "y": 0, "w": 10, "h": 10, "fill": "transparent", "stroke": "#AA0000"}], background="#101010")
            code, out = st.get("/api/series/colours?name=Night%20Letters")
            self.assertEqual(code, 200)
            counts = {c["hex"]: c["count"] for c in out}
            self.assertEqual(counts, {"#101010": 2, "#FFFFFF": 2, "#AA0000": 2, "#FF0000": 1, "#00FF00": 1})
            self.assertEqual({c["count"] for c in out[:3]}, {2})
            self.assertEqual(st.get("/api/series/colours?name=Nonesuch")[0], 400)


class FontsInDesignsCacheTest(unittest.TestCase):
    def test_design_files_are_read_again_only_when_they_change(self):
        with temp_studio() as st:
            st.post("/api/series", {"name": "Night Letters"})
            pid = st.post("/api/poems", {"title": "A poem", "series": "Night Letters"})[1]["id"]
            text = lambda f: [{"type": "text", "x": 0, "y": 0, "w": 10, "h": 10, "text": "x", "font": f}]   # noqa: E731
            slug = save_design(st, pid, "one", text("Archivo"))
            store = Handler.store
            self.assertEqual(store.fonts_in_designs(), {"archivo"})
            real = Path.read_text
            reads = []

            def counting(self, *a, **k):
                reads.append(self.parent.name)
                return real(self, *a, **k)
            with mock.patch.object(Path, "read_text", counting):
                self.assertEqual(store.fonts_in_designs(), {"archivo"})
                st.get("/api/fonts")
                self.assertFalse([r for r in reads if r == "designs"], "unchanged designs were read again")
            st.post("/api/design", {"id": pid, "slug": slug, "design": {"name": "one", "format": "45", "elements": text("Bebas Neue")}})   # edited
            self.assertEqual(store.fonts_in_designs(), {"bebas neue"})
            other = save_design(st, pid, "two", text("Archivo"))   # added
            self.assertEqual(store.fonts_in_designs(), {"bebas neue", "archivo"})
            st.post("/api/design/delete", {"id": pid, "slug": other})   # removed
            self.assertEqual(store.fonts_in_designs(), {"bebas neue"})


class SystemFontsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-sysfonts-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.sysdir = self.tmp / "sys"
        self.sysdir.mkdir()
        tt = TTFont(fonts.BUNDLED / "BebasNeue-Regular.ttf")
        for rec in tt["name"].names:
            if rec.nameID in (1, 16):
                rec.string = "Bebas Local"
        tt.save(self.sysdir / "local.ttf")

    def test_used_system_font_is_listed_and_exportable(self):
        from studio import shoot
        from studio.store import StoreError
        with mock.patch.object(fonts, "system_dirs", lambda: [self.sysdir]):
            with temp_studio() as st:
                st.post("/api/series", {"name": "Night Letters"})
                pid = st.post("/api/poems", {"title": "A poem", "series": "Night Letters"})[1]["id"]
                save_design(st, pid, "one", [{"type": "text", "x": 0, "y": 0, "w": 10, "h": 10, "text": "x", "font": "Bebas Local"}])
                save_design(st, pid, "two", [{"type": "text", "x": 0, "y": 0, "w": 10, "h": 10, "text": "x", "font": "Nonesuch Sans"}])
                reg = fonts.registry()
                self.assertNotIn("Bebas Local", [f["family"] for f in st.get("/api/fonts")[1]])   # not indexed yet
                reg.start_system_index()
                for _ in range(200):
                    if reg.system_ready():
                        break
                    time.sleep(0.05)
                names = [f["family"] for f in st.get("/api/fonts")[1]]
                self.assertIn("Bebas Local", names)
                self.assertNotIn("Nonesuch Sans", names)
                self.assertIn('font-family:"Bebas Local"', st.get("/api/fonts.css")[1].decode())
                self.assertEqual([f["family"] for f in st.get("/api/fonts/system")[1]], ["Bebas Local"])
                shoot.check_fonts({"elements": [{"type": "text", "font": "Bebas Local"}]})
                with self.assertRaises(StoreError):
                    shoot.check_fonts({"elements": [{"type": "text", "font": "Nonesuch Sans"}]})

    def test_check_fonts_waits_for_a_running_index(self):
        from studio import shoot
        with mock.patch.object(fonts, "system_dirs", lambda: [self.sysdir]):
            with temp_studio():
                real = fonts.Registry._scan_system

                def slow(reg):
                    time.sleep(0.5)
                    return real(reg)
                with mock.patch.object(fonts.Registry, "_scan_system", slow):
                    fonts.registry().start_system_index()
                    shoot.check_fonts({"elements": [{"type": "text", "font": "Bebas Local"}]})


if __name__ == "__main__":
    unittest.main()
