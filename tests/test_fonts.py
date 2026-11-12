"""The font registry: families from bundled, library and system files, with their axes; metrics and routes use it."""
import base64
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

from fontTools.ttLib import TTCollection, TTFont

from studio import config, fonts, metrics
from studio.store import StoreError
from tests.support import temp_studio

BUNDLED = fonts.BUNDLED


class FontsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-fonts-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lib = self.tmp / "lib" / "Styles" / "fonts"
        self.lib.mkdir(parents=True)
        self.reg = fonts.Registry(BUNDLED, self.lib)

    def copy(self, name, to=None):
        dest = (to or self.tmp) / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BUNDLED / name, dest)
        return dest

    def test_reads_a_variable_family(self):
        fam = self.reg.get("Newsreader")
        self.assertEqual(fam.wght, (200, 800))
        self.assertIsNotNone(fam.opsz)
        self.assertEqual(sorted(f.italic for f in fam.files), [False, True])
        self.assertTrue(fam.italic)
        self.assertEqual(fam.source, "bundled")
        self.assertEqual(fam.license, "OFL-1.1")
        self.assertEqual(fam.category, "serif")

    def test_archivo_has_widths(self):
        fam = self.reg.get("Archivo")
        self.assertAlmostEqual(fam.wdth[0], 62, delta=0.5)
        self.assertAlmostEqual(fam.wdth[1], 125, delta=0.5)
        self.assertFalse(fam.italic)
        self.assertIsNone(fam.opsz)

    def test_static_family_picks_nearest_weight(self):
        self.assertEqual(self.reg.file_for("IBM Plex Mono", False, 650).path.name, "IBMPlexMono-Bold.ttf")
        self.assertEqual(self.reg.file_for("IBM Plex Mono", True, 400).path.name, "IBMPlexMono-Italic.ttf")
        self.assertEqual(self.reg.file_for("IBM Plex Mono", False, 300).path.name, "IBMPlexMono-Regular.ttf")
        self.assertEqual(self.reg.get("IBM Plex Mono").wght, (400, 700))

    def test_missing_italic_falls_back_to_roman(self):
        fam = self.reg.get("Bebas Neue")
        self.assertFalse(fam.italic)
        self.assertEqual(self.reg.file_for("Bebas Neue", True, 400).path.name, "BebasNeue-Regular.ttf")

    def test_ttc_gives_one_entry_per_face(self):
        coll = TTCollection()
        coll.fonts = [TTFont(BUNDLED / "IBMPlexMono-Regular.ttf"), TTFont(BUNDLED / "IBMPlexMono-Bold.ttf")]
        coll.save(self.tmp / "plex.ttc")
        faces = fonts.read_font(self.tmp / "plex.ttc", "file")
        self.assertEqual([(f.family, f.weight, f.italic) for f in faces], [("IBM Plex Mono", 400, False), ("IBM Plex Mono", 700, False)])
        self.assertNotEqual(faces[0].id, faces[1].id)

    def test_woff2_is_read(self):
        tt = TTFont(BUNDLED / "BebasNeue-Regular.ttf")
        tt.flavor = "woff2"
        tt.save(self.tmp / "bebas.woff2")
        [face] = fonts.read_font(self.tmp / "bebas.woff2", "file")
        self.assertEqual((face.family, face.weight, face.italic, face.source), ("Bebas Neue", 400, False, "file"))

    def test_unreadable_file_gives_nothing(self):
        (self.tmp / "broken.ttf").write_bytes(b"not a font at all")
        self.assertEqual(fonts.read_font(self.tmp / "broken.ttf", "file"), [])

    def test_restricted_embedding_is_flagged(self):
        tt = TTFont(BUNDLED / "BebasNeue-Regular.ttf")
        tt["OS/2"].fsType = 2
        tt.save(self.tmp / "restricted.ttf")
        [face] = fonts.read_font(self.tmp / "restricted.ttf", "file")
        self.assertFalse(face.embeddable)
        [free] = fonts.read_font(BUNDLED / "BebasNeue-Regular.ttf", "bundled")
        self.assertTrue(free.embeddable)

    def test_missing_cap_height_uses_H(self):
        tt = TTFont(BUNDLED / "BebasNeue-Regular.ttf")
        upm, glyf = tt["head"].unitsPerEm, tt["glyf"]
        h = glyf[tt.getBestCmap()[ord("H")]]
        h.recalcBounds(glyf)
        tt["OS/2"].version = 1
        tt.save(self.tmp / "v1.ttf")
        [face] = fonts.read_font(self.tmp / "v1.ttf", "file")
        self.assertAlmostEqual(face.cap, h.yMax / upm, places=4)

    def test_own_file_wins_over_bundled(self):
        self.copy("Inter[opsz,wght].ttf", self.lib / "Inter")
        names = [f.name for f in self.reg.families()]
        self.assertEqual(names.count("Inter"), 1)
        fam = self.reg.get("Inter")
        self.assertEqual(fam.source, "file")
        self.assertEqual(len(fam.files), 1)
        self.assertEqual(self.reg.to_json()[names.index("Inter")]["files"][0]["url"], "/fonts/library/Inter/Inter%5Bopsz%2Cwght%5D.ttf")

    def test_library_folder_details_come_from_family_json(self):
        self.copy("Caveat[wght].ttf", self.lib / "Caveat")
        (self.lib / "Caveat" / "family.json").write_text('{"family": "Caveat", "category": "hand", "source": "google", "license": "OFL-1.1"}', encoding="utf-8")
        fam = self.reg.get("Caveat")
        self.assertEqual((fam.source, fam.category, fam.license), ("google", "hand", "OFL-1.1"))

    def test_registry_notices_new_files(self):
        self.assertEqual(self.reg.get("Inter").source, "bundled")
        self.copy("Inter[opsz,wght].ttf", self.lib / "Inter")
        self.reg.check(every=0)   # what fonts.registry() does on each use, at most once a second
        self.assertEqual(self.reg.get("Inter").source, "file")
        (self.lib / "Inter" / "Inter[opsz,wght].ttf").unlink()
        self.reg.check(every=0)
        self.assertEqual(self.reg.get("Inter").source, "bundled")

    def test_process_registry_follows_the_library(self):
        with mock.patch.object(config, "ART", self.tmp / "one"):
            first = fonts.registry()
            self.assertIs(fonts.registry(), first)
            self.assertEqual(first.library, self.tmp / "one" / "Styles" / "fonts")
        with mock.patch.object(config, "ART", self.tmp / "two"):
            self.assertEqual(fonts.registry().library, self.tmp / "two" / "Styles" / "fonts")

    def test_reading_does_not_keep_files_open(self):
        p = self.copy("Inter[opsz,wght].ttf", self.lib / "Inter")
        self.reg.families()
        self.reg.file_for("Inter", False, 400)
        p.unlink()   # Windows refuses while a handle is open
        self.assertFalse(p.exists())

    def test_css_lists_every_file(self):
        css = self.reg.css()
        files = [f for fam in self.reg.families() for f in fam.files]
        self.assertEqual(css.count("@font-face"), len(files))
        for f in files:
            self.assertIn(f'url("{f.url}")', css)
        self.assertIn('@font-face{font-family:"Newsreader";font-style:italic;font-weight:200 800;font-display:block;'
                      'src:url("/fonts/bundled/Newsreader-Italic-VF.ttf") format("truetype")}', css)
        self.assertIn('@font-face{font-family:"Archivo";font-style:normal;font-weight:100 900;font-stretch:62% 125%;font-display:block;'
                      'src:url("/fonts/bundled/Archivo-VF.ttf") format("truetype")}', css)
        self.assertIn('font-family:"IBM Plex Mono";font-style:normal;font-weight:700;', css)
        self.assertIn("font-display:swap", self.reg.css("swap"))

    def test_to_json_shape(self):
        data = {f["family"]: f for f in self.reg.to_json()}
        self.assertEqual([f["family"] for f in self.reg.to_json()][:2], ["Newsreader", "Archivo"])
        a = data["Archivo"]
        self.assertEqual({k for k in a}, {"family", "category", "source", "license", "italic", "wght", "wdth", "opsz", "cap",
                                          "embeddable", "files"})
        self.assertEqual((a["wght"], a["wdth"], a["opsz"], a["italic"]), ([100, 900], [62, 125], None, False))
        self.assertAlmostEqual(a["cap"], 0.686, places=3)
        self.assertEqual(a["files"], [{"url": "/fonts/bundled/Archivo-VF.ttf", "italic": False, "weight": 600,
                                       "axes": {"wght": [100, 600, 900], "wdth": [62, 100, 125]}}])

    def test_system_fonts_only_when_asked(self):
        sysdir = self.tmp / "system"
        self.copy("BebasNeue-Regular.ttf", sysdir)
        shutil.copy2(BUNDLED / "Caveat[wght].ttf", sysdir / "Caveat.ttf")
        reg = fonts.Registry(BUNDLED, self.lib, [sysdir])
        caveat = [f for f in reg.families(include_system=True) if f.name == "Caveat"]
        self.assertEqual([f.source for f in caveat], ["bundled"])     # bundled wins over the system copy
        self.assertNotIn("system", {f.source for f in reg.families()})
        tt = TTFont(BUNDLED / "BebasNeue-Regular.ttf")
        for rec in tt["name"].names:
            if rec.nameID == 1:
                rec.string = "Bebas Local"
        tt.save(sysdir / "local.ttf")
        reg.rescan_system()
        local = [f for f in reg.families(include_system=True) if f.name == "Bebas Local"]
        self.assertEqual([f.source for f in local], ["system"])
        self.assertTrue(local[0].files[0].url.startswith("/fonts/system/"))
        self.assertNotIn("Bebas Local", reg.css())


class MetricsTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="studio-metrics-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name, value in (("ART", tmp / "lib"), ("CACHE", tmp / "cache")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_metrics_key_format_unchanged(self):
        self.assertEqual(metrics.key("Newsreader", False, 500, 100, 120), "Newsreader|0|500|100|72")
        self.assertEqual(metrics.key("Newsreader", True, 400, 87.5, 15), "Newsreader|1|400|100|14")
        self.assertEqual(metrics.key("Archivo", True, 700, 87.5, 40), "Archivo|0|700|87.5|0")
        self.assertEqual(metrics.key("Nonesuch", True, None, None, None), "Newsreader|1|400|100|72")
        self.assertTrue(metrics.key("Inter", False, 400, 100, 20).endswith("|20"))
        self.assertEqual(metrics.key("Inter", False, 400, 100, 6), "Inter|0|400|100|14")
        self.assertEqual(metrics.key("Bebas Neue", True, 400, 125, 40), "Bebas Neue|0|400|100|0")

    def test_metrics_for_a_new_family(self):
        m = metrics.instance(metrics.key("Literata", True, 400, 100, 40))
        self.assertGreater(m["cap"], 0.6)
        self.assertIn("é", m["g"])

    def test_metrics_for_a_static_family(self):
        m = metrics.instance(metrics.key("IBM Plex Mono", False, 700, 100, 40))
        self.assertAlmostEqual(m["cap"], 0.698, places=3)
        self.assertIn("H", m["g"])

    def test_many_skips_unknown_families(self):
        out = metrics.many(["Newsreader|0|500|100|72", "Nonesuch|0|400|100|0", "garbage"])
        self.assertEqual(list(out), ["Newsreader|0|500|100|72"])

    def test_one_cold_instance_is_measured_once(self):
        """Requests that arrive together for an instance nobody has measured yet wait for one measurement."""
        metrics._memory.clear()
        k = metrics.key("Newsreader", False, 430, 100, 72)          # in no seed and no cache
        self.assertIsNone(metrics.seeded(k))
        real, calls = metrics.instancer.instantiateVariableFont, []

        def slow(*a, **kw):
            calls.append(1)
            time.sleep(0.3)
            return real(*a, **kw)
        out, go = [], threading.Barrier(4)

        def ask():
            go.wait()
            out.append(metrics.instance(k))
        with mock.patch.object(metrics.instancer, "instantiateVariableFont", slow):
            threads = [threading.Thread(target=ask) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(out), 4)
        self.assertTrue(all(m == out[0] for m in out))

    def test_a_failed_measurement_is_not_kept(self):
        metrics._memory.clear()
        k = metrics.key("Newsreader", False, 440, 100, 72)
        with mock.patch.object(metrics, "measure", side_effect=ValueError("broken font")):
            with self.assertRaises(ValueError):
                metrics.instance(k)
        self.assertEqual(metrics._flights, {})
        self.assertGreater(metrics.instance(k)["cap"], 0.6)

    def test_a_seeded_instance_is_not_measured(self):
        metrics._memory.clear()
        for k in ("Newsreader|0|500|100|72", "Archivo|0|900|87.5|0", "Source Serif 4|0|400|100|48", "Inter|0|600|100|24", "Caveat|0|700|100|0"):
            self.assertIsNotNone(metrics.seeded(k), k)
            with mock.patch.object(metrics, "measure", side_effect=AssertionError("measured " + k)):
                self.assertEqual(metrics.instance(k), metrics.seeded(k))
        self.assertFalse((config.CACHE / "metrics").exists())     # nothing measured, nothing written

    def test_the_seed_holds_what_the_instancer_measures(self):
        reg = fonts.registry()
        for k in ("Archivo|0|700|100|0", "Newsreader|1|400|100|40", "Caveat|0|700|100|0"):
            font, italic, weight = k.split("|")[:3]
            f = reg.file_for(font, italic == "1", float(weight))
            self.assertEqual(metrics.measure(k, f.path, f.index), metrics.seeded(k), k)

    def test_the_seed_is_only_for_the_bundled_files(self):
        metrics._memory.clear()
        own = config.ART / "Styles" / "fonts" / "Caveat"
        own.mkdir(parents=True)
        shutil.copy2(BUNDLED / "Caveat[wght].ttf", own / "Caveat.ttf")
        self.assertEqual(fonts.registry().get("Caveat").source, "file")
        with mock.patch.object(metrics, "measure", wraps=metrics.measure) as m:
            metrics.instance("Caveat|0|700|100|0")
        self.assertEqual(m.call_count, 1)


class FontRoutesTest(unittest.TestCase):
    def test_fonts_json_css_and_files(self):
        with temp_studio() as st:
            code, data = st.get("/api/fonts")
            self.assertEqual(code, 200)
            self.assertEqual(data[0]["family"], "Newsreader")
            code, css = st.get("/api/fonts.css?display=block")
            self.assertEqual(code, 200)
            self.assertIn(b'font-family:"Archivo"', css)
            code, body = st.get("/fonts/bundled/Newsreader-VF.ttf")
            self.assertEqual((code, body), (200, (BUNDLED / "Newsreader-VF.ttf").read_bytes()))
            code, body = st.get("/fonts/bundled/Fraunces%5BSOFT%2CWONK%2Copsz%2Cwght%5D.ttf")
            self.assertEqual(code, 200)

    def test_only_indexed_files_are_served(self):
        with temp_studio() as st:
            own = config.ART / "Styles" / "fonts" / "Inter"
            own.mkdir(parents=True)
            shutil.copy2(BUNDLED / "Inter[opsz,wght].ttf", own / "Inter.ttf")
            (own / "notes.txt").write_text("not a font", encoding="utf-8")
            self.assertEqual(st.get("/fonts/library/Inter/Inter.ttf")[0], 200)
            for bad in ("/fonts/library/Inter/notes.txt", "/fonts/bundled/families.json", "/fonts/bundled/OFL-Inter.txt",
                        "/fonts/bundled/../../config.py", "/fonts/library/../../config.json", "/fonts/system/0123abcd",
                        "/fonts/system/" + str(BUNDLED / "Inter[opsz,wght].ttf"), "/fonts/nothing"):
                self.assertEqual(st.get(bad)[0], 404, bad)


FIXTURES = Path(__file__).parent / "fixtures"
META = (FIXTURES / "google-metadata.json").read_bytes()
LISTS = json.loads((FIXTURES / "google-download-list.json").read_text(encoding="utf-8"))
FONT_FILE = {"Newsreader-VariableFont_opsz,wght.ttf": "Newsreader-VF.ttf", "Newsreader-Italic-VariableFont_opsz,wght.ttf": "Newsreader-Italic-VF.ttf"}


def fake_fetch(calls=None):
    """Serves the recorded Google responses; the font files are the bundled Newsreader files."""
    def fetch(url):
        if calls is not None:
            calls.append(url)
        if url == "https://fonts.google.com/metadata/fonts":
            return META
        if url.startswith("https://fonts.google.com/download/list?family="):
            return LISTS[unquote(url.split("=", 1)[1])].encode("utf-8")
        for ref in json.loads(LISTS["Newsreader"].split("\n", 1)[1])["manifest"]["fileRefs"]:
            if ref["url"] == url and ref["filename"] in FONT_FILE:
                return (BUNDLED / FONT_FILE[ref["filename"]]).read_bytes()
        raise AssertionError("unexpected url " + url)
    return fetch


class AddFontsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-addfonts-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, value in (("ART", self.tmp / "lib"), ("CACHE", self.tmp / "cache")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.lib = self.tmp / "lib" / "Styles" / "fonts"

    def plex(self, *names):
        return [(n, (BUNDLED / n).read_bytes()) for n in names]

    def test_add_files_groups_a_family(self):
        out = fonts.add_files(self.plex("IBMPlexMono-Regular.ttf", "IBMPlexMono-Bold.ttf"))
        self.assertEqual(out["added"], ["IBM Plex Mono"])
        self.assertEqual(out["warnings"], [])
        folder = self.lib / "IBM Plex Mono"
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["IBMPlexMono-Bold.ttf", "IBMPlexMono-Regular.ttf", "family.json"])
        meta = json.loads((folder / "family.json").read_text(encoding="utf-8"))
        self.assertEqual(meta, {"family": "IBM Plex Mono", "category": "sans", "source": "file", "license": "OFL-1.1"})
        fam = fonts.registry().get("IBM Plex Mono")
        self.assertEqual((fam.source, len(fam.files)), ("file", 2))

    def add_plex(self):
        fonts.add_files(self.plex("IBMPlexMono-Regular.ttf"))
        return self.lib / "IBM Plex Mono"

    def test_update_family_category_and_licence(self):
        folder = self.add_plex()
        out = fonts.update_family("IBM Plex Mono", {"category": "mono", "license": " OFL-1.1 (mine) "})
        self.assertEqual((out["category"], out["license"]), ("mono", "OFL-1.1 (mine)"))
        meta = json.loads((folder / "family.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["category"], meta["license"], meta["source"]), ("mono", "OFL-1.1 (mine)", "file"))
        self.assertEqual(fonts.registry().get("IBM Plex Mono").category, "mono")
        for bad in ({"category": "fancy"}, {"license": "x" * 61}):
            with self.assertRaises(StoreError):
                fonts.update_family("IBM Plex Mono", bad)

    def test_bundled_family_cannot_be_edited(self):
        for name in ("Newsreader", "Nonesuch"):
            with self.assertRaisesRegex(StoreError, "Only fonts you added can be edited."):
                fonts.update_family(name, {"category": "serif"})
            with self.assertRaisesRegex(StoreError, "Only fonts you added can be removed."):
                fonts.remove_family(name)

    def test_remove_family_moves_it_to_the_trash(self):
        folder = self.add_plex()
        dest = fonts.remove_family("IBM Plex Mono")
        self.assertFalse(folder.exists())
        self.assertEqual(dest.parent, self.tmp / "lib" / "Styles" / ".trash" / "fonts")
        self.assertTrue(dest.name.startswith("IBM Plex Mono "))
        self.assertTrue((dest / "family.json").exists())
        self.assertEqual(fonts.registry().get("IBM Plex Mono").source, "bundled")   # the bundled copy shows again

    def test_remove_family_in_use_needs_force(self):
        folder = self.add_plex()
        with self.assertRaisesRegex(StoreError, "IBM Plex Mono is used in 2 designs; change them first."):
            fonts.remove_family("IBM Plex Mono", used=2)
        self.assertTrue(folder.exists())
        fonts.remove_family("IBM Plex Mono", used=2, force=True)
        self.assertFalse(folder.exists())

    def test_remove_family_message_counts_styles_too(self):
        self.add_plex()
        with self.assertRaisesRegex(StoreError, "IBM Plex Mono is used in 1 series, poem or book; change them first."):
            fonts.remove_family("IBM Plex Mono", styled=1)
        with self.assertRaisesRegex(StoreError, "used in 2 designs and 3 series, poems or books;"):
            fonts.remove_family("IBM Plex Mono", used=2, styled=3)

    def test_add_rejects_non_fonts(self):
        with self.assertRaises(StoreError) as cm:
            fonts.add_files(self.plex("IBMPlexMono-Regular.ttf") + [("notes.txt", b"hello")])
        self.assertEqual(str(cm.exception), "notes.txt isn't a font file.")
        self.assertFalse(self.lib.exists())     # nothing is kept when one file is refused

    def test_add_keeps_only_the_file_name(self):
        out = fonts.add_files([("..\\..\\evil/Bebas.ttf", (BUNDLED / "BebasNeue-Regular.ttf").read_bytes())])
        self.assertEqual(out["added"], ["Bebas Neue"])
        self.assertEqual(sorted(p.name for p in (self.lib / "Bebas Neue").iterdir()), ["Bebas.ttf", "family.json"])

    def test_add_warns_about_restricted_fonts(self):
        tt = TTFont(BUNDLED / "BebasNeue-Regular.ttf")
        tt["OS/2"].fsType = 2
        tt["name"].names = [n for n in tt["name"].names if n.nameID not in (13, 14)]
        tt.save(self.tmp / "restricted.ttf")
        out = fonts.add_files([("restricted.ttf", (self.tmp / "restricted.ttf").read_bytes())])
        self.assertEqual(out["warnings"], ["No licence found in Bebas Neue; check it allows use in print.",
                                            "Bebas Neue doesn't allow embedding in PDFs."])

    def test_a_pipe_in_a_family_name_is_dropped(self):
        tt = TTFont(BUNDLED / "BebasNeue-Regular.ttf")
        for rec in tt["name"].names:
            if rec.nameID in (1, 16):
                rec.string = "Bebas | Pipe"
        tt.save(self.tmp / "pipe.ttf")
        out = fonts.add_files([("pipe.ttf", (self.tmp / "pipe.ttf").read_bytes())])
        self.assertEqual(out["added"], ["Bebas Pipe"])
        self.assertEqual(fonts._clean("A|B"), "A B")

    def test_google_catalog_with_and_without_prefix(self):
        bare = META.split(b"\n", 1)[1]
        self.assertTrue(META.startswith(b")]}'"))
        a = fonts.google_catalog(lambda url: META)
        (self.tmp / "cache" / "google-fonts.json").unlink()
        b = fonts.google_catalog(lambda url: bare)
        self.assertEqual(a, b)
        self.assertEqual([f["family"] for f in a], ["Archivo", "Bebas Neue", "Newsreader"])
        news = next(f for f in a if f["family"] == "Newsreader")
        self.assertEqual((news["category"], news["italic"]), ("serif", True))
        self.assertEqual({x["tag"] for x in news["axes"]}, {"opsz", "wght"})
        self.assertFalse(next(f for f in a if f["family"] == "Bebas Neue")["italic"])

    def test_google_catalog_is_cached_for_a_week(self):
        calls = []
        fonts.google_catalog(fake_fetch(calls))
        fonts.google_catalog(fake_fetch(calls))
        self.assertEqual(len(calls), 1)
        old = time.time() - 8 * 86400
        os.utime(self.tmp / "cache" / "google-fonts.json", (old, old))
        fonts.google_catalog(fake_fetch(calls))
        self.assertEqual(len(calls), 2)

    def test_google_files_prefers_variable(self):
        got = fonts.google_files("Newsreader", fake_fetch())
        self.assertEqual([n for n, _ in got], ["Newsreader-VariableFont_opsz,wght.ttf", "Newsreader-Italic-VariableFont_opsz,wght.ttf"])
        self.assertTrue(all(u.startswith("https://fonts.gstatic.com/") for _, u in got))
        self.assertEqual([n for n, _ in fonts.google_files("Bebas Neue", fake_fetch())], ["BebasNeue-Regular.ttf"])
        self.assertEqual([n for n, _ in fonts.google_files("Archivo", fake_fetch())],
                         ["Archivo-VariableFont_wdth,wght.ttf", "Archivo-Italic-VariableFont_wdth,wght.ttf"])

    def test_add_google_downloads_into_the_library(self):
        out = fonts.add_google("Newsreader", fake_fetch())
        self.assertEqual(out, {"added": ["Newsreader"], "warnings": []})
        folder = self.lib / "Newsreader"
        meta = json.loads((folder / "family.json").read_text(encoding="utf-8"))
        self.assertEqual(meta, {"family": "Newsreader", "category": "serif", "source": "google", "license": "OFL-1.1"})
        self.assertEqual(len([p for p in folder.iterdir() if p.suffix == ".ttf"]), 2)
        self.assertEqual(fonts.registry().get("Newsreader").source, "google")

    def test_add_google_refuses_unknown_families(self):
        with self.assertRaises(StoreError):
            fonts.add_google("Nonesuch Sans", fake_fetch())

    def test_network_failure_is_a_plain_error(self):
        def down(url):
            raise OSError("offline")
        with self.assertRaises(StoreError) as cm:
            fonts.google_catalog(down)
        self.assertIn("Google Fonts", str(cm.exception))


class SystemFontsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-sysfonts-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.sysdir = self.tmp / "system"
        self.sysdir.mkdir()
        tt = TTFont(BUNDLED / "BebasNeue-Regular.ttf")
        for rec in tt["name"].names:
            if rec.nameID in (1, 16):
                rec.string = "Bebas Local"
        tt.save(self.sysdir / "local.ttf")
        (self.sysdir / "readme.txt").write_text("not a font", encoding="utf-8")
        self.lib = self.tmp / "lib"
        self.cache = self.tmp / "system-fonts.json"

    def wait(self, reg):
        for _ in range(200):
            if reg.system_ready():
                return
            time.sleep(0.05)
        self.fail("the system index never finished")

    def test_system_dirs_are_listed_per_platform(self):
        self.assertTrue(fonts.system_dirs())
        self.assertTrue(all(isinstance(p, Path) for p in fonts.system_dirs()))

    def test_system_index_lists_a_temp_dir(self):
        reg = fonts.Registry(BUNDLED, self.lib, [self.sysdir], self.cache)
        reg.start_system_index()
        self.wait(reg)
        [fam] = reg.system_json()
        self.assertEqual((fam["family"], fam["source"]), ("Bebas Local", "system"))
        self.assertTrue(fam["files"][0]["url"].startswith("/fonts/system/"))
        saved = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertEqual(list(saved["files"]), [str(self.sysdir / "local.ttf")])

    def test_system_index_reuses_the_cache_for_unchanged_files(self):
        fonts.Registry(BUNDLED, self.lib, [self.sysdir], self.cache).families(include_system=True)
        reg = fonts.Registry(BUNDLED, self.lib, [self.sysdir], self.cache)
        real = fonts.read_font

        def read(path, source):
            self.assertNotEqual(source, "system", "a cached file was opened again")
            return real(path, source)
        with mock.patch.object(fonts, "read_font", read):
            self.assertEqual([f.name for f in reg.families(include_system=True) if f.source == "system"], ["Bebas Local"])

    def test_system_urls_survive_a_library_refresh(self):
        reg = fonts.Registry(BUNDLED, self.lib, [self.sysdir], self.cache)
        [fam] = [f for f in reg.families(include_system=True) if f.source == "system"]
        url = fam.files[0].url
        self.assertIsNotNone(reg.open(url))
        reg.refresh()
        self.assertIsNotNone(reg.open(url))
        self.assertEqual(reg.get("Bebas Local").source, "system")

    def test_system_font_served_only_by_id(self):
        with mock.patch.object(fonts, "system_dirs", lambda: [self.sysdir]):
            with temp_studio() as st:
                data = {"indexing": True}
                for _ in range(200):
                    code, data = st.get("/api/fonts/system")
                    if isinstance(data, list):
                        break
                    self.assertEqual(data, {"indexing": True})
                    time.sleep(0.05)
                self.assertEqual([f["family"] for f in data], ["Bebas Local"])
                code, body = st.get(data[0]["files"][0]["url"])
                self.assertEqual((code, body), (200, (self.sysdir / "local.ttf").read_bytes()))
                for bad in ("/fonts/system/0123abcd", "/fonts/system/" + str(self.sysdir / "local.ttf"),
                            "/fonts/system/..%2Flocal.ttf"):
                    self.assertEqual(st.get(bad)[0], 404, bad)


class FontAddRoutesTest(unittest.TestCase):
    def test_add_and_google_endpoints(self):
        with temp_studio() as st:
            data = base64.b64encode((BUNDLED / "BebasNeue-Regular.ttf").read_bytes()).decode()
            code, out = st.post("/api/fonts/add", {"files": [{"name": "Bebas.ttf", "data": data}]})
            self.assertEqual((code, out["added"]), (200, ["Bebas Neue"]))
            code, out = st.post("/api/fonts/add", {"files": [{"name": "x.txt", "data": base64.b64encode(b"hi").decode()}]})
            self.assertEqual((code, out["error"]), (400, "x.txt isn't a font file."))
            self.assertEqual(st.post("/api/fonts/add", {"files": [{"name": "x.ttf", "data": "!!!"}]})[0], 400)
            self.assertEqual(st.post("/api/fonts/add", {})[0], 400)
            self.assertIn("Bebas Neue", [f["family"] for f in st.get("/api/fonts")[1]])
            with mock.patch.object(fonts, "_fetch", fake_fetch()):
                code, out = st.get("/api/fonts/google?q=news")
                self.assertEqual((code, [f["family"] for f in out]), (200, ["Newsreader"]))
                self.assertEqual([f["family"] for f in st.get("/api/fonts/google?category=sans")[1]], ["Archivo", "Bebas Neue"])
                code, out = st.post("/api/fonts/google/add", {"family": "Newsreader"})
                self.assertEqual((code, out["added"]), (200, ["Newsreader"]))
                self.assertEqual(st.post("/api/fonts/google/add", {})[0], 400)


class FontEditRoutesTest(unittest.TestCase):
    def test_update_and_remove_endpoints(self):
        with temp_studio() as st:
            data = base64.b64encode((BUNDLED / "BebasNeue-Regular.ttf").read_bytes()).decode()
            st.post("/api/fonts/add", {"files": [{"name": "Bebas.ttf", "data": data}]})
            code, out = st.post("/api/fonts/update", {"family": "Bebas Neue", "category": "display", "license": "OFL-1.1"})
            self.assertEqual((code, out["category"]), (200, "display"))
            self.assertEqual(st.post("/api/fonts/update", {"family": "Newsreader", "category": "serif"})[0], 400)
            code, out = st.post("/api/fonts/remove", {"family": "Bebas Neue"})
            self.assertEqual(code, 200)
            self.assertNotIn("Bebas Neue", [f["family"] for f in st.get("/api/fonts")[1] if f["source"] == "file"])
            self.assertEqual(st.post("/api/fonts/remove", {"family": "Newsreader"})[0], 400)

    def test_remove_refused_when_a_series_or_look_uses_the_font(self):
        with temp_studio() as st:
            data = base64.b64encode((BUNDLED / "BebasNeue-Regular.ttf").read_bytes()).decode()
            st.post("/api/fonts/add", {"files": [{"name": "Bebas.ttf", "data": data}]})
            st.post("/api/series", {"name": "Night Letters"})
            st.post("/api/series/style", {"name": "Night Letters", "fonts": {"display": {"family": "Bebas Neue", "weight": 400}}})
            code, out = st.post("/api/fonts/remove", {"family": "Bebas Neue"})
            self.assertEqual((code, out["error"]), (400, "Bebas Neue is used in 1 series, poem or book; change them first."))
            self.assertEqual((out["designs"], out["styled"]), (0, 1))     # the counts, for the "Remove anyway" question
            st.post("/api/series/style", {"name": "Night Letters", "fonts": None})
            self.assertEqual(st.post("/api/styles/look", {"look": {"name": "Poster", "palette": "Blood", "fonts": {
                r: {"family": "Bebas Neue", "weight": 400} for r in ("display", "text", "label")}}})[0], 200)
            st.post("/api/series/style", {"name": "Night Letters", "link": "Poster"})
            self.assertEqual(st.post("/api/fonts/remove", {"family": "Bebas Neue"})[0], 400)
            self.assertEqual(st.post("/api/fonts/remove", {"family": "Bebas Neue", "force": True})[0], 200)

    def test_remove_counts_books_that_use_the_font(self):
        with temp_studio() as st:
            data = base64.b64encode((BUNDLED / "BebasNeue-Regular.ttf").read_bytes()).decode()
            st.post("/api/fonts/add", {"files": [{"name": "Bebas.ttf", "data": data}]})
            self.assertEqual(st.post("/api/books", {"title": "The Quiet Year", "kind": "fiction"})[0], 200)
            self.assertEqual(st.post("/api/books", {"title": "Small Hours", "kind": "memoir"})[0], 200)
            fonts_ = {"fonts": {"display": {"family": "Bebas Neue", "weight": 400}}}
            self.assertEqual(st.post("/api/book/update", {"b": "The Quiet Year", "fields": fonts_})[0], 200)
            code, out = st.post("/api/fonts/remove", {"family": "Bebas Neue"})
            self.assertEqual((code, out["error"]), (400, "Bebas Neue is used in 1 series, poem or book; change them first."))
            self.assertEqual((out["designs"], out["styled"]), (0, 1))
            st.post("/api/book/update", {"b": "The Quiet Year", "fields": {"fonts": None}})
            self.assertEqual(st.post("/api/fonts/remove", {"family": "Bebas Neue"})[0], 200)      # nothing uses it now
            st.post("/api/fonts/add", {"files": [{"name": "Bebas.ttf", "data": data}]})
            self.assertEqual(st.post("/api/styles/look", {"look": {"name": "Poster", "palette": "Blood", "fonts": {
                r: {"family": "Bebas Neue", "weight": 400} for r in ("display", "text", "label")}}})[0], 200)
            self.assertEqual(st.post("/api/book/update", {"b": "Small Hours", "fields": {"link": "Poster"}})[0], 200)
            (config.BOOKS / "Broken").mkdir()
            (config.BOOKS / "Broken" / "book.json").write_text("not json", encoding="utf-8")     # left out, not an error
            code, out = st.post("/api/fonts/remove", {"family": "Bebas Neue"})
            self.assertEqual((code, out["styled"]), (400, 1))      # through its look
            self.assertEqual(st.post("/api/fonts/remove", {"family": "Bebas Neue", "force": True})[0], 200)


class DownloadLimitsTest(unittest.TestCase):
    """The download rules, on AddFontsTest's temp library and cache."""
    setUp = AddFontsTest.setUp

    def test_only_google_https_urls_are_fetched(self):
        base = fake_fetch()

        def evil(url):
            raw = base(url)
            if "download/list" in url:
                raw = raw.replace(b"https://fonts.gstatic.com/s/newsreader/v26/cY9AfjOCX1hbuyalUrK479n4jaBGNpY.ttf", b"file:///etc/hosts")
            return raw
        with self.assertRaises(StoreError):
            fonts.add_google("Newsreader", evil)
        self.assertFalse((self.lib / "Newsreader").exists())
        for bad in ("file:///etc/hosts", "ftp://fonts.gstatic.com/a.ttf", "http://fonts.gstatic.com/a.ttf",
                    "https://example.com/a.ttf", "https://fonts.gstatic.com.evil.test/a.ttf", "https://fonts.google.com/other"):
            with self.assertRaises(StoreError, msg=bad):
                fonts._get(bad, lambda u: b"x")

    def test_responses_have_a_size_cap(self):
        with mock.patch.object(fonts, "MAX_FONT_BYTES", 100), mock.patch.object(fonts, "MAX_META_BYTES", 200):
            self.assertEqual(len(fonts._get("https://fonts.gstatic.com/a.ttf", lambda u: b"x" * 100)), 100)
            with self.assertRaises(StoreError):
                fonts._get("https://fonts.gstatic.com/a.ttf", lambda u: b"x" * 101)
            with self.assertRaises(StoreError):
                fonts.google_catalog(lambda u: b"x" * 201)


class SystemIndexRobustnessTest(unittest.TestCase):
    setUp = SystemFontsTest.setUp
    wait = SystemFontsTest.wait

    def test_a_rescan_during_an_index_takes_effect(self):
        reg = fonts.Registry(BUNDLED, self.lib, [self.sysdir], self.cache)
        stale = reg._scan_system()
        release, started = threading.Event(), threading.Event()
        calls = []

        def scan():
            calls.append(1)
            if len(calls) == 1:
                started.set()
                release.wait(5)
                return stale
            return []
        reg._scan_system = scan
        reg.start_system_index()
        self.assertTrue(started.wait(5))
        reg.rescan_system()
        reg.start_system_index()        # already running: no second thread
        release.set()
        self.wait(reg)
        self.assertEqual(reg.system_json(), [])
        self.assertEqual(len(calls), 2)

    def test_a_broken_cache_entry_is_read_again(self):
        fonts.Registry(BUNDLED, self.lib, [self.sysdir], self.cache).families(include_system=True)
        data = json.loads(self.cache.read_text(encoding="utf-8"))
        entry = data["files"][str(self.sysdir / "local.ttf")]
        del entry["faces"][0]["axes"]
        self.cache.write_text(json.dumps(data), encoding="utf-8")
        reg = fonts.Registry(BUNDLED, self.lib, [self.sysdir], self.cache)
        self.assertEqual([f.name for f in reg.families(include_system=True) if f.source == "system"], ["Bebas Local"])
        self.assertIn("axes", json.loads(self.cache.read_text(encoding="utf-8"))["files"][str(self.sysdir / "local.ttf")]["faces"][0])


if __name__ == "__main__":
    unittest.main()
