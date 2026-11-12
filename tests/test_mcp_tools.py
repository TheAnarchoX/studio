import contextlib
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import anyio

from fontTools.ttLib import TTFont

from studio import config, fonts, mcp_server, shoot
from studio.store import Store, StoreError, write_text

_ENV = ("STUDIO_ART", "STUDIO_CONFIG", "STUDIO_CACHE")


@contextlib.contextmanager
def temp_library():
    tmp = Path(tempfile.mkdtemp(prefix="studio-mcp-"))
    saved = {k: os.environ.get(k) for k in _ENV}
    saved_cfg, saved_store = config.CONFIG_FILE, mcp_server.store
    os.environ["STUDIO_ART"] = str(tmp / "lib")
    os.environ["STUDIO_CONFIG"] = str(tmp / "config.json")
    os.environ["STUDIO_CACHE"] = str(tmp / "cache")
    config.CONFIG_FILE = tmp / "config.json"
    config.refresh()
    config.POEMS.mkdir(parents=True, exist_ok=True)
    mcp_server.store = Store()
    try:
        yield mcp_server.store
    finally:
        mcp_server.store = saved_store
        config.CONFIG_FILE = saved_cfg
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.refresh()


class McpToolsTest(unittest.TestCase):
    def test_unknown_fonts(self):
        with temp_library():
            d = {"elements": [
                {"type": "text", "text": "a", "font": "Archivo"},
                {"type": "text", "text": "b"},
                {"type": "text", "text": "c", "font": "No Such Face"},
                {"type": "text", "text": "d", "font": "No Such Face"},
                {"type": "rect", "font": "Nope"}]}
            self.assertEqual(mcp_server.unknown_fonts(d), ["No Such Face"])
            self.assertEqual(mcp_server.unknown_fonts({"elements": []}), [])

    def test_save_design_rejects_unknown_font(self):
        with temp_library() as s:
            s.create_series("Night", "")
            p = s.create("One", "Night")
            d = {"name": "X", "format": "45", "background": "#000000",
                 "elements": [{"type": "text", "text": "a", "font": "No Such Face"}]}
            with self.assertRaises(Exception) as cm:
                anyio.run(mcp_server.save_design, p["id"], d)
            self.assertIn("Unknown fonts: No Such Face. Available: ", str(cm.exception))

    def test_read_poem_has_style(self):
        with temp_library() as s:
            s.create_series("Night", "")
            p = s.create("One", "Night")
            out = json.loads(anyio.run(mcp_server.read_poem, p["id"]))
            self.assertIn("fonts", out["style"])

    def test_get_rules_starts_with_house_rules(self):
        with temp_library() as s:
            s.create_series("Night", "")
            write_text(config.ART / "Styles" / "rules.md", "Never centre the title.")
            out = anyio.run(mcp_server.get_rules, "Night")
            self.assertTrue(out.startswith("# House rules"))
            self.assertIn("Never centre the title.", out)
            self.assertIn("# Rules", out)

    def test_get_rules_without_house_rules(self):
        with temp_library() as s:
            s.create_series("Night", "")
            self.assertNotIn("House rules", anyio.run(mcp_server.get_rules, "Night"))


class SystemFontTest(unittest.TestCase):
    def setUp(self):
        import shutil
        tmp = Path(tempfile.mkdtemp(prefix="studio-mcp-sys-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        sysdir = tmp / "sys"
        sysdir.mkdir()
        tt = TTFont(fonts.BUNDLED / "BebasNeue-Regular.ttf")
        for rec in tt["name"].names:
            if rec.nameID in (1, 16):
                rec.string = "Bebas Local"
        tt.save(sysdir / "local.ttf")
        p = mock.patch.object(fonts, "system_dirs", lambda: [sysdir])
        p.start()
        self.addCleanup(p.stop)
        fonts._registry = None
        self.addCleanup(setattr, fonts, "_registry", None)

    def design(self, family):
        return {"name": "X", "format": "45", "background": "#000000",
                "elements": [{"type": "text", "text": "a", "font": family}]}

    def test_computer_font_is_accepted_without_a_web_server(self):
        with temp_library() as s:
            s.create_series("Night", "")
            p = s.create("One", "Night")
            self.assertEqual(mcp_server.unknown_fonts(self.design("Bebas Local")), [])
            self.assertIn("Saved design", anyio.run(mcp_server.save_design, p["id"], self.design("Bebas Local")))
            shoot.check_fonts(self.design("Bebas Local"))

    def test_font_that_exists_nowhere_is_refused(self):
        with temp_library() as s:
            s.create_series("Night", "")
            p = s.create("One", "Night")
            with self.assertRaises(StoreError):
                shoot.check_fonts(self.design("Nonesuch Sans"))
            with self.assertRaises(Exception) as cm:
                anyio.run(mcp_server.save_design, p["id"], self.design("Nonesuch Sans"))
            msg = str(cm.exception)
            self.assertIn("Unknown fonts: Nonesuch Sans. Available: ", msg)
            self.assertIn("and 1 fonts on this computer", msg)


if __name__ == "__main__":
    unittest.main()
