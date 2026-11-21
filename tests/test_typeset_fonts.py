"""Static font faces cut for Typst: real regular, bold, italic and bold italic per role, cached on disk."""
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

import typst
from fontTools.ttLib import TTFont

from studio import config, typeset_fonts

_ENV = ("STUDIO_ART", "STUDIO_CACHE", "STUDIO_CONFIG")


class TypesetFontsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-tsf-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        saved = {k: os.environ.get(k) for k in _ENV}
        saved_cfg = config.CONFIG_FILE
        os.environ["STUDIO_ART"] = str(self.tmp / "lib")
        os.environ["STUDIO_CACHE"] = str(self.tmp / "cache")
        os.environ["STUDIO_CONFIG"] = str(self.tmp / "config.json")
        config.CONFIG_FILE = self.tmp / "config.json"
        config.refresh()

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            config.CONFIG_FILE = saved_cfg
            config.refresh()
        self.addCleanup(restore)
        self.cache = self.tmp / "cache"

    def test_variable_family_gets_four_real_faces(self):
        out = typeset_fonts.prepare({"text": {"family": "Literata", "weight": 400, "opsz": 10.5}}, self.cache)
        found = typst.Fonts(include_system_fonts=False, include_embedded_fonts=False, font_paths=[str(out["folder"])]).fonts()
        text = [f for f in found if f["family"] == "Literata Text"] if isinstance(found[0], dict) else None
        if text is None:
            text = [f for f in found if getattr(f, "family", None) == "Literata Text"]
        got = set()
        for f in text:
            g = (lambda k: f[k] if isinstance(f, dict) else getattr(f, k))
            got.add((str(g("style")).lower(), int(g("weight"))))
        self.assertEqual(got, {("normal", 400), ("normal", 700), ("italic", 400), ("italic", 700)})

    def test_faces_are_cached(self):
        roles = {"text": {"family": "Literata", "weight": 400, "opsz": 10.5}}
        said = []
        first = typeset_fonts.prepare(roles, self.cache, on_cut=said.append)
        self.assertEqual(set(said), {"Literata"})               # cutting: the caller is told which family
        before = sorted(p.name for p in (self.cache / "typeset-fonts").glob("*.ttf"))
        t = time.time()
        second = typeset_fonts.prepare(roles, self.cache, on_cut=said.append)
        self.assertLess(time.time() - t, 0.5)
        self.assertEqual(set(said), {"Literata"})
        self.assertEqual(len(said), 4)                           # once per face cut, and nothing when cached
        self.assertEqual(before, sorted(p.name for p in (self.cache / "typeset-fonts").glob("*.ttf")))
        self.assertEqual(first["folder"], second["folder"])

    def test_two_roles_two_names(self):
        out = typeset_fonts.prepare({"text": {"family": "Literata", "weight": 400, "opsz": 10.5},
                                     "heading": {"family": "Literata", "weight": 400, "opsz": 18}}, self.cache)
        self.assertEqual(out["names"], {"text": "Literata Text", "heading": "Literata Heading"})
        self.assertEqual(len(out["faces"]), 8)
        self.assertEqual(len(list(out["folder"].iterdir())), 8)

    def test_unknown_family_falls_back(self):
        out = typeset_fonts.prepare({"text": {"family": "No Such Font", "weight": 400, "opsz": 10}}, self.cache)
        self.assertEqual(out["names"]["text"], "Literata Text")
        self.assertEqual(len(out["problems"]), 1)
        self.assertIn("No Such Font", out["problems"][0])

    def test_covers_and_smallcaps(self):
        out = typeset_fonts.prepare({"text": {"family": "Literata", "weight": 400, "opsz": 10.5}}, self.cache)
        missing = typeset_fonts.covers(out["faces"], "Één ₂ Ω")
        self.assertNotIn("É", missing)
        self.assertTrue(all(v == "text" for v in missing.values()))
        self.assertIsInstance(typeset_fonts.has_smallcaps(out["faces"][0]), bool)

    def test_family_without_bold_names_the_problem(self):
        out = typeset_fonts.prepare({"text": {"family": "Bebas Neue", "weight": 400, "opsz": 10}}, self.cache)
        self.assertTrue(any("has no bold" in p for p in out["problems"]))
        self.assertTrue(any("has no italic" in p for p in out["problems"]))

    def test_concurrent_prepares_both_succeed(self):
        roles = {"text": {"family": "Literata", "weight": 400, "opsz": 10.5}}
        results, errors = [], []

        def run():
            try:
                results.append(typeset_fonts.prepare(roles, self.cache))
            except Exception as e:  # noqa: BLE001
                errors.append(e)
        gate = threading.Barrier(4)
        threads = [threading.Thread(target=lambda: (gate.wait(), run())) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertEqual({r["folder"] for r in results}, {results[0]["folder"]})
        files = list(results[0]["folder"].iterdir())
        self.assertEqual(len(files), 4)
        for f in files:
            with TTFont(f) as tt:
                self.assertNotIn("fvar", tt)
        self.assertEqual(list((self.cache / "typeset-fonts").glob("*.part")), [])

    def test_nearby_sizes_share_faces(self):
        def cut(size):
            out = typeset_fonts.prepare({"text": {"family": "Literata", "weight": 400, "opsz": size}}, self.cache)
            return out["folder"], len(list((self.cache / "typeset-fonts").glob("*.ttf")))
        folder, count = cut(10)
        self.assertEqual(count, 4)
        for size in (10.5, 11, 11.5):
            self.assertEqual(cut(size), (folder, 4))
        other, count = cut(18)
        self.assertNotEqual(other, folder)
        self.assertEqual(count, 8)


if __name__ == "__main__":
    unittest.main()
