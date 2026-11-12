"""Styles: palettes, looks and house rules, bundled with Studio or the library's own, inherited from global to poem."""
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from studio import config, fonts, styles
from studio.store import Store, StoreError
from studio.styles import Styles, contrast, palette_from_image, palette_warnings

EDITORIAL = [("global", {"look": "Editorial light"})]

# a series.json as Studio 1.0 wrote it: an own palette list and voice/command fonts
LEGACY = ('{\n  "name": "Old Series",\n  "tagline": "Made before looks.",\n  "signature": "A. Poet",\n'
          '  "palette": [\n    {\n      "name": "Night",\n      "hex": "#0C0E11"\n    },\n'
          '    {\n      "name": "Paper",\n      "hex": "#EEEAE2"\n    },\n'
          '    {\n      "name": "Red",\n      "hex": "#DA291C"\n    }\n  ],\n'
          '  "fonts": [\n    {\n      "family": "Newsreader",\n      "role": "voice"\n    },\n'
          '    {\n      "family": "Archivo",\n      "role": "command"\n    }\n  ],\n'
          '  "formats": [\n    "1:1",\n    "4:5",\n    "9:16"\n  ],\n  "created": "2026-01-01"\n}\n')


def roles(resolved):
    return {r: (f["family"], f["weight"], f["width"]) for r, f in resolved["fonts"].items()}


class StylesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-styles-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.st = Styles(self.tmp)

    # ——— the library ———
    def test_bundled_looks_and_palettes(self):
        looks = self.st.looks()
        self.assertEqual(len(looks), 10)
        self.assertEqual({l["name"] for l in looks}, {"Signal", "Editorial light", "Warm linen", "Pastel", "Monochrome",
                                                       "High contrast", "Academic", "Botanical", "Riso", "Children's book"})
        self.assertTrue(all(l["source"] == "bundled" and not l["edited"] for l in looks))
        pals = {p["name"]: p for p in self.st.palettes()}
        for name in ("Signal", "Ink and paper", "Blood", "Ultramarine", "Ochre"):
            self.assertIn(name, pals)
        self.assertEqual(pals["Blood"]["swatches"][2]["hex"], "#7A0019")
        self.assertEqual(self.st.palette("Signal")["swatches"],
                         [{"name": "Night", "hex": "#0C0E11", "role": "background"},
                          {"name": "Paper", "hex": "#EEEAE2", "role": "text"},
                          {"name": "Signal red", "hex": "#DA291C", "role": "accent"},
                          {"name": "Fog", "hex": "#959AA2", "role": "muted"},
                          {"name": "Fog ink", "hex": "#77726B"}])
        self.assertEqual(self.st.look("Signal")["fonts"], {"display": {"family": "Archivo", "weight": 900, "width": 87.5},
                                                           "text": {"family": "Newsreader", "weight": 400},
                                                           "label": {"family": "Archivo", "weight": 700}})
        reg = fonts.Registry(fonts.BUNDLED, self.tmp / "no-fonts")
        for look in looks:   # every starter names a bundled palette, gives every role, and uses bundled fonts
            self.assertIn(look["palette"], pals)
            self.assertEqual(tuple(look["fonts"]), styles.FONT_ROLES)
            for f in look["fonts"].values():
                self.assertIsNotNone(reg.get(f["family"]), f["family"])
        for pal in pals.values():
            self.assertEqual(len([s for s in pal["swatches"] if s.get("role") == "background"]), 1, pal["name"])
        self.assertEqual(self.st.look("signal")["name"], "Signal")   # names match in any case, as file names do
        self.assertFalse((self.tmp / "Styles").exists())               # reading never writes

    def test_editing_a_bundled_palette_makes_an_own_copy(self):
        pal = self.st.palette("Signal")
        pal["swatches"][2]["hex"] = "#ff0000"
        saved = self.st.save_palette(pal)
        self.assertEqual((saved["source"], saved["edited"]), ("own", True))
        self.assertTrue((self.tmp / "Styles" / "palettes" / "Signal.json").exists())
        self.assertEqual(self.st.palette("Signal")["swatches"][2]["hex"], "#FF0000")
        self.assertEqual([p["name"] for p in self.st.palettes()].count("Signal"), 1)
        starter = json.loads((styles.BUNDLED / "palettes" / "Signal.json").read_text(encoding="utf-8"))
        self.assertEqual(starter["swatches"][2]["hex"], "#DA291C")   # the starter itself is untouched
        look = self.st.look("Signal")
        look["fonts"]["text"] = {"family": "Literata", "weight": 400}
        self.assertEqual(self.st.save_look(look)["source"], "own")
        self.assertTrue(self.st.look("Signal")["edited"])
        self.assertEqual(self.st.resolve([("global", {"look": "Signal"})])["palette"]["swatches"][2]["hex"], "#FF0000")

    def test_editing_a_bundled_palette_then_deleting_it_restores_the_bundled_one(self):
        with self.assertRaisesRegex(StoreError, r"^Built-in palettes can't be deleted\. Editing one saves your own copy\.$"):
            self.st.delete_palette("Blood")
        with self.assertRaisesRegex(StoreError, "Built-in looks can't be deleted"):
            self.st.delete_look("Riso")
        pal = self.st.palette("Blood")
        pal["swatches"][2]["hex"] = "#000000"
        self.st.save_palette(pal)
        self.st.delete_palette("Blood")
        back = self.st.palette("Blood")
        self.assertEqual((back["source"], back["edited"], back["swatches"][2]["hex"]), ("bundled", False, "#7A0019"))
        self.assertFalse((self.tmp / "Styles" / "palettes" / "Blood.json").exists())
        self.st.save_palette({"name": "Mine", "swatches": [{"name": "Ink", "hex": "#111111"}]})
        self.st.delete_palette("Mine")
        with self.assertRaises(StoreError):
            self.st.palette("Mine")
        with self.assertRaisesRegex(StoreError, "No palette called"):
            self.st.delete_palette("Mine")

    def test_palette_validation(self):
        one = [{"name": "Ink", "hex": "#111111", "role": "text"}]
        bad = {
            "bad hex": ({"name": "X", "swatches": [{"name": "a", "hex": "red"}]}, "Not a colour"),
            "two backgrounds": ({"name": "X", "swatches": [{"name": "a", "hex": "#000000", "role": "background"},
                                                           {"name": "b", "hex": "#FFFFFF", "role": "background"}]},
                                "Only one colour can be the background"),
            "unknown role": ({"name": "X", "swatches": [{"name": "a", "hex": "#000000", "role": "shadow"}]}, "role"),
            "empty name": ({"name": "  ", "swatches": one}, "1 to 60 characters"),
            "long name": ({"name": "x" * 61, "swatches": one}, "1 to 60 characters"),
            "slash in name": ({"name": "a/b", "swatches": one}, "can't contain"),
            "17 swatches": ({"name": "X", "swatches": [{"name": f"c{i}", "hex": "#000000"} for i in range(17)]}, "1 to 16"),
            "no swatches": ({"name": "X", "swatches": []}, "1 to 16"),
        }
        for label, (p, message) in bad.items():
            with self.subTest(label), self.assertRaisesRegex(StoreError, message):
                self.st.save_palette(p)
        self.assertFalse((self.tmp / "Styles" / "palettes").exists())
        saved = self.st.save_palette({"name": " Night  walk ", "swatches": [
            {"name": "Sky", "hex": "#0b0e1a", "role": "background"}, {"name": "Moon", "hex": "#f1eee6", "role": "text"},
            ["Lamp", "#FFD400"]]})
        self.assertEqual((saved["name"], saved["source"], saved["edited"]), ("Night walk", "own", False))
        self.assertEqual(saved["swatches"], [{"name": "Sky", "hex": "#0B0E1A", "role": "background"},
                                             {"name": "Moon", "hex": "#F1EEE6", "role": "text"},
                                             {"name": "Lamp", "hex": "#FFD400"}])
        self.assertEqual(saved["warnings"], [])

    def test_look_validation(self):
        good = {"name": "Night shift", "palette": "blood",
                "fonts": {"display": {"family": "Archivo", "weight": 900, "width": 87.5},
                          "text": {"family": "Newsreader", "weight": 400}, "label": {"family": "Inter", "weight": "600"}}}
        saved = self.st.save_look(good)
        self.assertEqual((saved["name"], saved["palette"], saved["source"], saved["warnings"]),
                         ("Night shift", "Blood", "own", []))
        self.assertEqual(saved["fonts"]["label"], {"family": "Inter", "weight": 600})
        fonts_ = good["fonts"]
        bad = {
            "unknown palette": ({**good, "palette": "No such palette"}, "No palette called"),
            "own palette": ({**good, "palette": [{"name": "a", "hex": "#000000"}]}, "palette"),
            "missing label": ({**good, "fonts": {k: v for k, v in fonts_.items() if k != "label"}}, "label"),
            "no family": ({**good, "fonts": {**fonts_, "text": {"weight": 400}}}, "text font"),
            "bad weight": ({**good, "fonts": {**fonts_, "text": {"family": "Newsreader", "weight": "bold"}}}, "weight"),
            "weight out of range": ({**good, "fonts": {**fonts_, "text": {"family": "Newsreader", "weight": 0}}}, "weight"),
            "bad width": ({**good, "fonts": {**fonts_, "display": {"family": "Archivo", "weight": 900, "width": 500}}}, "width"),
            "no name": ({**good, "name": ""}, "1 to 60 characters"),
        }
        for label, (look, message) in bad.items():
            with self.subTest(label), self.assertRaisesRegex(StoreError, message):
                self.st.save_look(look)
        odd = self.st.save_look({**good, "name": "Odd", "fonts": {**fonts_, "text": {"family": "Nonesuch Sans", "weight": 400}}})
        self.assertEqual(odd["source"], "own")                       # an unknown family warns, it doesn't refuse
        self.assertEqual(len(odd["warnings"]), 1)
        self.assertIn("Nonesuch Sans", odd["warnings"][0])

    def test_house_rules_round_trip(self):
        self.assertEqual(self.st.rules(), "")
        self.st.save_rules("Use British spelling.\r\nNever add hashtags.\n")
        self.assertEqual((self.tmp / "Styles" / "rules.md").read_bytes(), b"Use British spelling.\nNever add hashtags.\n")
        self.assertEqual(Styles(self.tmp).rules(), "Use British spelling.\nNever add hashtags.\n")

    # ——— resolution, global to poem ———
    def test_resolve_global_only(self):
        r = self.st.resolve(EDITORIAL)
        self.assertEqual(r["look"], "Editorial light")
        self.assertEqual({k: r["palette"][k] for k in ("name", "from", "linked")},
                         {"name": "Editorial light", "from": "global", "linked": True})
        self.assertEqual(r["palette"]["swatches"][0], {"name": "Paper", "hex": "#F7F5F0", "role": "background"})
        self.assertEqual(r["fonts"]["display"], {"family": "Fraunces", "weight": 500, "width": None, "from": "global"})
        self.assertEqual(roles(r), {"display": ("Fraunces", 500, None), "text": ("Source Serif 4", 400, None),
                                    "label": ("Inter", 600, None)})

    def test_resolve_series_look(self):
        r = self.st.resolve(EDITORIAL + [("series", {"name": "Calls", "tagline": "x", "look": "Signal"}), ("poem", {"title": "A"})])
        self.assertEqual(r["look"], "Signal")
        self.assertEqual((r["palette"]["name"], r["palette"]["from"], r["palette"]["linked"]), ("Signal", "series", True))
        self.assertEqual(r["fonts"]["display"], {"family": "Archivo", "weight": 900, "width": 87.5, "from": "series"})
        self.assertEqual({f["from"] for f in r["fonts"].values()}, {"series"})

    def test_resolve_own_palette(self):
        own = [{"name": "Bone", "hex": "#E9E4DA", "role": "background"}, {"name": "Black", "hex": "#0B0B0C"}]
        r = self.st.resolve(EDITORIAL + [("series", {"look": "Signal", "palette": own})])
        self.assertEqual(r["palette"], {"name": None, "swatches": own, "from": "series", "linked": False})
        self.assertEqual(r["look"], "Signal")                       # the fonts still follow the look
        self.assertEqual(r["fonts"]["text"]["family"], "Newsreader")
        r = self.st.resolve(EDITORIAL + [("series", {"palette": {"name": "Mine", "swatches": own}})])
        self.assertEqual((r["palette"]["name"], r["palette"]["linked"], r["palette"]["swatches"]), ("Mine", False, own))
        r = self.st.resolve(EDITORIAL + [("series", {"palette": "Blood"})])
        self.assertEqual((r["palette"]["name"], r["palette"]["linked"], r["palette"]["from"]), ("Blood", True, "series"))
        self.assertEqual(r["fonts"]["display"]["from"], "global")

    def test_resolve_poem_override(self):
        r = self.st.resolve(EDITORIAL + [("series", {"look": "Signal"}),
                                         ("poem", {"palette": "Blood", "fonts": {"text": {"family": "Literata", "weight": 300}}})])
        self.assertEqual(r["look"], "Signal")
        self.assertEqual((r["palette"]["name"], r["palette"]["from"]), ("Blood", "poem"))
        self.assertEqual(r["fonts"]["text"], {"family": "Literata", "weight": 300, "width": None, "from": "poem"})
        self.assertEqual(r["fonts"]["display"]["from"], "series")
        r = self.st.resolve(EDITORIAL + [("series", {"look": "Signal"}), ("poem", {"look": "Riso"})])
        self.assertEqual((r["look"], r["palette"]["name"], r["fonts"]["label"]["family"]), ("Riso", "Riso", "IBM Plex Mono"))

    def test_resolve_says_where_the_look_comes_from(self):
        self.assertEqual(self.st.resolve(EDITORIAL)["look_from"], "global")
        r = self.st.resolve(EDITORIAL + [("series", {"look": "Signal", "palette": "Blood"}), ("poem", {"palette": "Ochre"})])
        self.assertEqual((r["look"], r["look_from"]), ("Signal", "series"))     # the fonts still follow the series' look
        r = self.st.resolve(EDITORIAL + [("series", {"look": "Signal"}), ("poem", {"look": "Riso"})])
        self.assertEqual((r["look"], r["look_from"]), ("Riso", "poem"))
        own = {"palette": [{"hex": "#000000"}], "fonts": {r: {"family": "Inter", "weight": 400} for r in styles.FONT_ROLES}}
        r = self.st.resolve(EDITORIAL + [("series", own)])
        self.assertEqual((r["look"], r["look_from"]), (None, None))              # nothing of a look is left

    def test_resolve_unknown_name_falls_back(self):
        r = self.st.resolve(EDITORIAL + [("series", {"look": "Gone", "palette": "Missing", "fonts": {"text": "Newsreader"}}),
                                         ("poem", {"look": "Nope"})])
        self.assertEqual(r, self.st.resolve(EDITORIAL))
        r = self.st.resolve([("global", {"look": "Deleted look"})])   # nothing above global: the built-in default
        self.assertEqual((r["look"], r["palette"]["name"], r["fonts"]["text"]["family"]),
                         ("Editorial light", "Editorial light", "Source Serif 4"))
        self.assertEqual(r["palette"]["from"], "global")

    def test_detach_and_link(self):
        meta = {"name": "Night Letters", "tagline": "x", "look": "Signal"}
        before = self.st.resolve(EDITORIAL + [("series", meta)])
        detached = self.st.detach(meta, before)
        self.assertEqual(meta["look"], "Signal")                     # the original is left alone
        self.assertNotIn("look", detached)
        self.assertEqual(detached["palette"], {"name": "Signal", "swatches": self.st.palette("Signal")["swatches"]})
        self.assertEqual(detached["fonts"], {"display": {"family": "Archivo", "weight": 900, "width": 87.5},
                                             "text": {"family": "Newsreader", "weight": 400},
                                             "label": {"family": "Archivo", "weight": 700}})
        after = self.st.resolve(EDITORIAL + [("series", detached)])
        self.assertIsNone(after["look"])
        self.assertEqual((after["palette"]["linked"], after["palette"]["from"]), (False, "series"))
        self.assertEqual(after["palette"]["swatches"], before["palette"]["swatches"])
        self.assertEqual(roles(after), roles(before))
        linked = self.st.link(detached, "pastel")
        self.assertEqual(linked, {"name": "Night Letters", "tagline": "x", "look": "Pastel"})
        with self.assertRaisesRegex(StoreError, "No look called"):
            self.st.link(detached, "No such look")

        # the same through a series: series.json changes only when asked
        s = Store(self.tmp / "Poems", self.tmp / "cache")
        with mock.patch.object(config, "DEFAULT_LOOK", "Editorial light"):
            s.create_series("Night Letters", look="Signal")
            f = self.tmp / "Poems" / "Night Letters" / "series.json"
            s.update_series("Night Letters", {"tagline": "Letters."})
            self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["look"], "Signal")
            self.assertNotIn("palette", json.loads(f.read_text(encoding="utf-8")))   # a link stays a link
            m = s.update_series("Night Letters", {"detach": True})
            data = json.loads(f.read_text(encoding="utf-8"))
            self.assertNotIn("look", data)
            self.assertEqual(data["palette"]["name"], "Signal")
            self.assertEqual((m["look"], m["palette_linked"], m["font_roles"]["display"]["from"]), (None, False, "series"))
            m = s.update_series("Night Letters", {"link": "Riso"})
            self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["look"], "Riso")
            self.assertNotIn("palette", json.loads(f.read_text(encoding="utf-8")))
            self.assertEqual((m["look"], m["palette_linked"]), ("Riso", True))

    def test_update_series_styles(self):
        s = Store(self.tmp / "Poems", self.tmp / "cache")
        with mock.patch.object(config, "DEFAULT_LOOK", "Editorial light"):
            s.create_series("Night Letters")
            m = s.update_series("Night Letters", {"look": "Monochrome", "palette": "ochre",
                                                  "fonts": {"text": {"family": "Literata", "weight": 400}}})
            self.assertEqual((m["look"], m["palette"][2]["hex"], m["palette_from"]), ("Monochrome", "#C98A1B", "series"))
            self.assertEqual(m["font_roles"]["text"]["family"], "Literata")
            self.assertEqual(m["font_roles"]["display"]["family"], "Inter")
            self.assertEqual(m["fonts"], [{"family": "Inter"}, {"family": "Literata"}])
            data = json.loads((self.tmp / "Poems" / "Night Letters" / "series.json").read_text(encoding="utf-8"))
            self.assertEqual((data["look"], data["palette"], data["fonts"]),
                             ("Monochrome", "Ochre", {"text": {"family": "Literata", "weight": 400}}))
            m = s.update_series("Night Letters", {"palette": [{"name": "Ink", "hex": "#111111"}, {"name": "Paper", "hex": "#fafafa"}]})
            self.assertEqual((m["palette"][1]["hex"], m["palette_linked"]), ("#FAFAFA", False))
            m = s.update_series("Night Letters", {"palette": None, "fonts": None})
            self.assertEqual((m["palette"][0]["hex"], m["font_roles"]["text"]["family"]), ("#F2EFE8", "Inter"))   # Monochrome again
            for bad in ({"look": "No such look"}, {"palette": "No such palette"}, {"fonts": {"text": {"family": ""}}},
                        {"palette": [{"name": "x", "hex": "red"}]}):
                with self.subTest(bad=bad), self.assertRaises(StoreError):
                    s.update_series("Night Letters", bad)

    def test_legacy_series_unchanged_on_read(self):
        d = self.tmp / "Poems" / "Old Series"
        (d / "First").mkdir(parents=True)
        f = d / "series.json"
        f.write_bytes(LEGACY.encode("utf-8"))
        (d / "First" / "poem.json").write_text('{"title": "First", "slug": "first", "lines": ["one"], "slides": []}\n', encoding="utf-8")
        old = f.stat().st_mtime - 3600
        os.utime(f, (old, old))
        stamp = f.stat().st_mtime_ns
        s = Store(self.tmp / "Poems", self.tmp / "cache")
        with mock.patch.object(config, "DEFAULT_LOOK", "Editorial light"):
            m = s.series_meta(d)
            p = s.read("Old Series/First")
            s.series_list()
            s.series_read("Old Series")
        self.assertEqual(f.read_bytes(), LEGACY.encode("utf-8"))
        self.assertEqual(f.stat().st_mtime_ns, stamp)
        self.assertFalse((self.tmp / "Styles").exists())
        self.assertEqual(m["palette"], json.loads(LEGACY)["palette"])   # the palette reads back as it was
        self.assertEqual((m["palette_from"], m["palette_linked"], m["look"]), ("series", False, None))
        self.assertEqual(m["font_roles"]["text"]["family"], "Newsreader")
        self.assertEqual(m["font_roles"]["display"]["family"], "Archivo")
        self.assertEqual(m["font_roles"]["label"]["family"], "Archivo")
        self.assertEqual(m["fonts"], [{"family": "Archivo"}, {"family": "Newsreader"}])
        self.assertEqual(p["series_info"]["palette"], m["palette"])
        self.assertEqual(p["series_info"]["font_roles"], m["font_roles"])
        self.assertEqual({k for k in p["series_info"]}, {"name", "tagline", "palette", "fonts", "signature", "has_kit", "look",
                                                         "palette_from", "palette_linked", "font_roles", "checks", "formats"})
        self.assertEqual(p["style"]["palette"]["from"], "series")
        self.assertEqual(p["style"]["fonts"]["text"], {"family": "Newsreader", "weight": 400, "width": None, "from": "series"})

    def test_create_series_uses_the_default_look(self):
        s = Store(self.tmp / "Poems", self.tmp / "cache")
        with mock.patch.object(config, "DEFAULT_LOOK", "Editorial light"):
            m = s.create_series("Night Letters", "Letters written at night.")
            d = self.tmp / "Poems" / "Night Letters"
            data = json.loads((d / "series.json").read_text(encoding="utf-8"))
            self.assertEqual(data["look"], config.DEFAULT_LOOK)
            self.assertNotIn("palette", data)
            self.assertNotIn("fonts", data)
            readme = (d / "README.md").read_text(encoding="utf-8")
            self.assertIn("- **Type:** Fraunces and Source Serif 4.", readme)
            self.assertIn("Paper `#F7F5F0`", readme)
            self.assertEqual((m["look"], m["palette"][0]["hex"]), ("Editorial light", "#F7F5F0"))
            m = s.create_series("Warm Nights", look="warm LINEN")
            self.assertEqual(m["look"], "Warm linen")
            self.assertIn("- **Type:** EB Garamond.", (self.tmp / "Poems" / "Warm Nights" / "README.md").read_text(encoding="utf-8"))
            m = s.create_series("Red Nights", palette="Blood")
            data = json.loads((self.tmp / "Poems" / "Red Nights" / "series.json").read_text(encoding="utf-8"))
            self.assertEqual((data["look"], data["palette"]), ("Editorial light", "Blood"))
            self.assertEqual(m["palette"][2]["hex"], "#7A0019")
            with self.assertRaises(StoreError):
                s.create_series("Nowhere", look="No such look")
            self.assertFalse((self.tmp / "Poems" / "Nowhere").exists())

    def test_colours_by_role_then_by_place(self):
        """The same rule as Design.colours (tests/test_design_core.py has the same cases)."""
        self.assertEqual(styles.colours([{"hex": "#111111", "role": "text"}, {"hex": "#222222", "role": "background"}, {"hex": "#333333"}]),
                         {"background": "#222222", "text": "#111111", "accent": "#333333", "muted": "#959AA2"})
        self.assertEqual(styles.colours([["Ink", "#141414"], ["Paper", "#F2EFE8"], ["Graphite", "#6E6B66"]]),
                         {"background": "#141414", "text": "#F2EFE8", "accent": "#6E6B66", "muted": "#959AA2"})
        self.assertEqual(styles.colours({"swatches": [{"hex": "#444444", "role": "accent"}]}),
                         {"background": "#0C0E11", "text": "#EEEAE2", "accent": "#444444", "muted": "#959AA2"})
        self.assertEqual(styles.colours([]), styles.COLOURS)

    def test_a_new_series_starts_from_the_house_rules(self):
        s = Store(self.tmp / "Poems", self.tmp / "cache")
        s.create_series("Plain")
        self.assertNotIn("House rules", (self.tmp / "Poems" / "Plain" / "README.md").read_text(encoding="utf-8"))
        s.styles.save_rules("- British spelling.\n- No exclamation marks.\n")
        s.create_series("Ruled", "Short ones.")
        readme = (self.tmp / "Poems" / "Ruled" / "README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith("# Ruled\n\nShort ones.\n\n## House rules\n\n- British spelling.\n- No exclamation marks.\n\n## The rules\n"), readme)

    def test_default_look_setting(self):
        self.assertEqual(config.DEFAULTS["default_look"], "Editorial light")
        saved = config.CONFIG_FILE
        self.addCleanup(config.refresh)
        self.addCleanup(setattr, config, "CONFIG_FILE", saved)
        config.CONFIG_FILE = self.tmp / "config.json"
        config.refresh()
        self.assertEqual(config.DEFAULT_LOOK, "Editorial light")
        config.save({"default_look": "  Riso "})
        self.assertEqual(config.DEFAULT_LOOK, "Riso")
        for bad in ("", "x" * 61, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                config.save({"default_look": bad})

    # ——— colour ———
    def test_contrast(self):
        self.assertEqual(contrast("#000000", "#FFFFFF"), 21.0)
        self.assertAlmostEqual(contrast("#777777", "#FFFFFF"), 4.48, places=2)
        self.assertEqual(contrast("#ffffff", "#777777"), contrast("#777777", "#FFFFFF"))
        warnings = palette_warnings({"swatches": [{"name": "Paper", "hex": "#FFFFFF", "role": "background"},
                                                  {"name": "Grey", "hex": "#777777", "role": "text"},
                                                  {"name": "Ink", "hex": "#111111", "role": "accent"}]})
        self.assertEqual(len(warnings), 1)
        self.assertIn("4.48:1", warnings[0])
        self.assertEqual(palette_warnings({"swatches": [{"name": "Grey", "hex": "#777777"}]}), [])   # no roles, no pairs
        self.assertEqual(palette_warnings(self.st.palette("Editorial light")), [])

    def test_palette_from_image(self):
        colours = [(12, 14, 17), (238, 234, 226), (218, 41, 28), (31, 61, 209)]   # widest block first
        img, x = Image.new("RGB", (200, 100)), 0
        for c, w in zip(colours, (90, 60, 35, 15)):
            img.paste(c, (x, 0, x + w, 100))
            x += w
        buf = io.BytesIO()
        img.save(buf, "PNG")
        got = palette_from_image(buf.getvalue())
        self.assertEqual(len(got), 4)
        for want, hexv in zip(colours, got):   # by frequency
            rgb = tuple(int(hexv[i:i + 2], 16) for i in (1, 3, 5))
            self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(rgb, want)), (hexv, want))
        self.assertEqual(len(palette_from_image(buf.getvalue(), n=2)), 2)
        with self.assertRaises(StoreError):
            palette_from_image(b"not an image")


if __name__ == "__main__":
    unittest.main()
