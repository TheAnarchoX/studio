"""Exports stop before Chrome runs when the type would be wrong."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio import config, fonts, shoot
from studio.store import Store, StoreError


class ExportFontsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-shoot-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, value in (("ART", self.tmp / "lib"), ("CACHE", self.tmp / "cache")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        root = self.tmp / "lib" / "Poems"
        kit = root / "Calls" / "_kit"
        kit.mkdir(parents=True)
        (kit / "build.py").write_text("RATIOS = {}\nVARIANTS = []\n", encoding="utf-8")
        self.store = Store(root, self.tmp / "cache")
        self.poem = self.store.create("A poem")

    def save(self, *fonts_used):
        els = [{"type": "text", "x": 0, "y": 0, "w": 100, "h": 20, "text": "x", **({"font": f} if f else {})} for f in fonts_used]
        return self.store.save_design(self.poem["id"], {"name": "d", "format": "45", "elements": els})

    def export(self, slug):
        with mock.patch.object(shoot, "screenshot") as shot:
            try:
                shoot.export_design(self.store, "http://127.0.0.1:1", self.poem["id"], slug)
            finally:
                self.assertFalse(shot.called, "Chrome must not run")

    def test_unknown_font_stops_the_export(self):
        slug = self.save("Newsreader", "Nonesuch Sans", None)
        with self.assertRaises(StoreError) as cm:
            self.export(slug)
        self.assertEqual(str(cm.exception), "This design uses fonts Studio doesn't have: Nonesuch Sans.")
        self.assertFalse(list(self.tmp.rglob("*.png")))

    def test_empty_registry_stops_the_export(self):
        slug = self.save(None)
        empty = mock.Mock()
        empty.families.return_value = []
        with mock.patch.object(fonts, "registry", return_value=empty):
            with self.assertRaises(StoreError) as cm:
                self.export(slug)
        self.assertEqual(str(cm.exception), "Studio couldn't load its fonts, so the export was stopped.")
        self.assertFalse(list(self.tmp.rglob("*.png")))

    def test_known_and_default_fonts_go_ahead(self):
        slug = self.save("Archivo", None)
        with mock.patch.object(shoot, "screenshot", side_effect=lambda url, w, h, out, scale=2: out) as shot:
            shoot.export_design(self.store, "http://127.0.0.1:1", self.poem["id"], slug)
        self.assertTrue(shot.called)

    def test_export_design_uses_series_formats(self):
        slug = self.save("Archivo")
        self.store.update_series("Calls", {"formats": ["9:16"]})
        folder = self.store.resolve(self.poem["id"])
        old = folder / "Design renders" / slug / f"{slug}-4x5.png"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_bytes(b"old")
        with mock.patch.object(shoot, "screenshot", side_effect=lambda url, w, h, out, scale=2: out) as shot:
            outs = shoot.export_design(self.store, "http://127.0.0.1:1", self.poem["id"], slug)
        self.assertEqual([o.name for o in outs], [f"{slug}-9x16.png"])
        self.assertEqual(shot.call_count, 1)
        self.assertEqual(old.read_bytes(), b"old")
        self.store.update_series("Calls", {"formats": ["1:1", "9:16"]})      # an explicit list is still narrowed to the series
        with mock.patch.object(shoot, "screenshot", side_effect=lambda url, w, h, out, scale=2: out):
            outs = shoot.export_design(self.store, "http://127.0.0.1:1", self.poem["id"], slug, ["45", "11"])
        self.assertEqual([o.name for o in outs], [f"{slug}-1x1.png"])


if __name__ == "__main__":
    unittest.main()
