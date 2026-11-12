"""The design core's starters and colours, run in node (tests/js/starters.js stands in for the browser).

tests/fixtures/starters-1.0.json holds what the starters made before they followed the look (Studio 1.1.0's
design-core.js, run through the same harness with the same cases): with Studio 1.0's type roles a series must
still get exactly that.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import fonts, styles

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "studio" / "static" / "design-core.js"
HARNESS = Path(__file__).parent / "js" / "starters.js"
FIXTURE = Path(__file__).parent / "fixtures" / "starters-1.0.json"

LINES = ["The kettle starts before I do,", "and the window holds a grey it has not named yet,", "so I leave the door open", "for the day."]
PALETTE_10 = [{"name": "Night", "hex": "#0C0E11"}, {"name": "Paper", "hex": "#EEEAE2"}, {"name": "Red", "hex": "#DA291C"},
              {"name": "Fog", "hex": "#959AA2"}, {"name": "Ink", "hex": "#77726B"}]       # a 1.0 series: no roles
PALETTE_3 = [{"name": "Ink", "hex": "#141414"}, {"name": "Paper", "hex": "#F2EFE8"}, {"name": "Graphite", "hex": "#6E6B66"}]
ROLES_10 = {"display": {"family": "Archivo", "weight": 900, "width": None, "from": "series"},       # what a 1.0 series resolves to
            "text": {"family": "Newsreader", "weight": 400, "width": None, "from": "series"},
            "label": {"family": "Archivo", "weight": 700, "width": None, "from": "series"}}


def legacy_cases(extra=None):
    """Every starter in every format, for a 1.0 series with a poem and a name, and for a short palette without either."""
    out = []
    for kind in ("blank", "page", "wall", "field"):
        for fmt in ("11", "45", "916"):
            for info in ({"lines": LINES, "palette": PALETTE_10, "signature": "A. Poet", "title": "Morning"},
                         {"lines": [], "palette": PALETTE_3}):
                out.append({"kind": kind, "format": None, "info": {**info, "format": fmt, **(extra or {})}})
    return out


def font_list():
    tmp = Path(tempfile.mkdtemp(prefix="studio-core-"))
    try:
        return fonts.Registry(fonts.BUNDLED, tmp).to_json()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(payload, core=CORE):
    tmp = Path(tempfile.mkdtemp(prefix="studio-core-"))
    try:
        (tmp / "input.json").write_text(json.dumps(payload), encoding="utf-8")
        r = subprocess.run([shutil.which("node"), str(HARNESS), str(core), str(tmp / "input.json")],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if r.returncode:
            raise AssertionError(r.stderr)
        return json.loads(r.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def look(name):
    st = styles.Styles(Path(tempfile.gettempdir()) / "studio-no-library")
    lk = st.look(name)
    return lk, st.palette(lk["palette"])


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class StartersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = font_list()

    def starters(self, cases):
        return run({"fonts": self.fonts, "cases": cases})["starters"]

    def test_a_1_0_series_gets_the_same_starters(self):
        want = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(len(want), 24)
        self.assertEqual(self.starters(legacy_cases({"fonts": ROLES_10})), want)
        self.assertEqual(self.starters(legacy_cases()), want)             # no roles given: 1.0's pairing

    def test_1_0_is_told_by_its_weights_as_well_as_its_families(self):
        """Newsreader and Archivo in other weights are not 1.0's pairing: they get starters in those weights. 1.0's own
        families and weights at another width (the Signal look) still get 1.0's starters (the Wall searches widths itself)."""
        roles = {**ROLES_10, "display": {"family": "Archivo", "weight": 500, "width": None, "from": "series"}}
        page, wall = self.starters([{"kind": k, "format": "45", "info": {"lines": LINES, "palette": PALETTE_10, "signature": "A. Poet",
                                                                         "fonts": roles}} for k in ("page", "wall")])
        rows = [e for e in wall["elements"] if e["type"] == "text" and e.get("role") != "name"]
        self.assertEqual({(e["font"], e["weight"]) for e in rows}, {("Archivo", 500)})
        poem, name = page["elements"]
        self.assertEqual((poem["font"], poem["weight"]), ("Newsreader", 400))           # the text role's weight, not 1.0's 500
        self.assertEqual((name["font"], name["weight"], name.get("italic")), ("Archivo", 700, None))   # signed in the label role
        signal = {r: {**f, "from": "series"} for r, f in look("Signal")[0]["fonts"].items()}
        self.assertEqual(signal["display"]["width"], 87.5)
        self.assertEqual(self.starters(legacy_cases({"fonts": signal})), json.loads(FIXTURE.read_text(encoding="utf-8")))

    def test_starters_are_measured_in_the_role_fonts(self):
        """A starter asked for before its fonts have loaded loads them first instead of fitting the poem to a fallback."""
        lk, pal = look("Children's book")
        roles = {r: {**f, "from": "series"} for r, f in lk["fonts"].items()}
        cases = [{"kind": k, "format": "45", "info": {"lines": LINES, "palette": pal["swatches"], "fonts": roles, "signature": "A. Poet"}}
                 for k in ("page", "wall", "field")]
        self.assertEqual(run({"fonts": self.fonts, "cases": cases, "cold": True})["starters"], self.starters(cases))
        want = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(run({"fonts": self.fonts, "cases": legacy_cases({"fonts": ROLES_10}), "cold": True})["starters"], want)

    def test_starters_follow_the_look(self):
        lk, pal = look("Children's book")
        roles = {r: {**f, "from": "series"} for r, f in lk["fonts"].items()}
        by = {s["role"]: s["hex"] for s in pal["swatches"] if s.get("role")}
        cases = [{"kind": k, "format": "45", "info": {"lines": LINES, "palette": pal["swatches"], "fonts": roles, "signature": "A. Poet"}}
                 for k in ("blank", "page", "wall", "field")]
        blank, page, wall, field = self.starters(cases)
        self.assertEqual(blank["background"], by["background"])
        poem, name = page["elements"]
        self.assertEqual((poem["font"], poem["weight"], poem["color"], poem["accent"]), ("Atkinson Hyperlegible", 400, by["text"], by["accent"]))
        self.assertEqual((name["font"], name["weight"], name["color"], name["role"]), ("Atkinson Hyperlegible", 700, by["muted"], "name"))
        self.assertEqual(page["background"], by["background"])
        rows = [e for e in wall["elements"] if e["type"] == "text" and e.get("role") != "name"]
        self.assertEqual({(e["font"], e["weight"], e["color"]) for e in rows}, {("Caveat", 700, by["background"])})
        self.assertTrue(all("stretch" not in e for e in rows))          # Caveat has no width axis: no width search
        self.assertEqual(wall["background"], by["accent"])
        self.assertEqual([e["font"] for e in wall["elements"] if e.get("role") == "name"], ["Atkinson Hyperlegible"])
        fpoem = [e for e in field["elements"] if e.get("name") == "Poem"][0]
        self.assertEqual((fpoem["font"], fpoem["weight"], fpoem["color"]), ("Caveat", 700, by["text"]))
        self.assertEqual([e["fill"] for e in field["elements"] if e["type"] == "rect"], [by["accent"]])

    def test_a_width_axis_is_searched_only_where_the_family_has_one(self):
        roles = {"display": {"family": "Archivo", "weight": 800}, "text": {"family": "Inter", "weight": 400},
                 "label": {"family": "Inter", "weight": 600}}
        wall = self.starters([{"kind": "wall", "format": "45", "info": {"lines": LINES, "fonts": roles}}])[0]
        rows = [e for e in wall["elements"] if e["type"] == "text" and e.get("role") != "name"]
        self.assertEqual({(e["font"], e["weight"]) for e in rows}, {("Archivo", 800)})
        self.assertTrue(all(62.5 <= e["stretch"] <= 125 for e in rows))

    def test_the_story_safe_zone_comes_from_the_series(self):
        lk, pal = look("Editorial light")
        info = {"lines": LINES, "palette": pal["swatches"], "fonts": lk["fonts"], "format": "916"}
        plain, safe = self.starters([{"kind": "wall", "format": "916", "info": info},
                                     {"kind": "wall", "format": "916", "info": {**info, "safe": {"t": 400, "b": 450}}}])
        sig = lambda d: [e for e in d["elements"] if e.get("role") == "name"][0]      # noqa: E731
        rule = lambda d: [e for e in d["elements"] if e["type"] == "rect"][0]         # noqa: E731
        self.assertEqual(sig(safe)["y"] - sig(plain)["y"], -(450 - 330))
        self.assertGreaterEqual(min(e["y"] for e in safe["elements"] if e["type"] == "text"), 400)
        self.assertEqual(rule(safe)["y"] - rule(plain)["y"], -(450 - 330))

    def test_colours_by_role_then_by_place(self):
        out = run({"fonts": self.fonts, "cases": [], "colours": [
            [{"hex": "#111111", "role": "text"}, {"hex": "#222222", "role": "background"}, {"hex": "#333333"}],
            PALETTE_3,
            {"swatches": [{"hex": "#444444", "role": "accent"}]},
            [],
        ]})["colours"]
        self.assertEqual(out[0], {"background": "#222222", "text": "#111111", "accent": "#333333", "muted": "#959AA2"})
        self.assertEqual(out[1], {"background": "#141414", "text": "#F2EFE8", "accent": "#6E6B66", "muted": "#959AA2"})
        self.assertEqual(out[2], {"background": "#0C0E11", "text": "#EEEAE2", "accent": "#444444", "muted": "#959AA2"})   # a swatch with a role stands in for no other
        self.assertEqual(out[3], {"background": "#0C0E11", "text": "#EEEAE2", "accent": "#DA291C", "muted": "#959AA2"})


if __name__ == "__main__":
    unittest.main()
