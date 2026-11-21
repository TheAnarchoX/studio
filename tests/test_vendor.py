"""The vendored front-end libraries are complete and self-contained (no network at runtime)."""
import re
import unittest
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "studio" / "static" / "vendor"
KATEX = VENDOR / "katex"


class KatexVendorTests(unittest.TestCase):
    def test_files_exist(self):
        for rel in ("katex.min.js", "katex.min.css"):
            self.assertTrue((KATEX / rel).is_file(), rel)
        self.assertTrue(list((KATEX / "fonts").glob("*.woff2")))
        self.assertTrue((VENDOR / "prosemirror.js").is_file())

    def test_licence_is_mit(self):
        text = (VENDOR / "LICENSE-katex.txt").read_text(encoding="utf-8")
        self.assertIn("MIT License", text)
        self.assertIn("Khan Academy", text)

    def test_css_references_only_existing_woff2(self):
        css = (KATEX / "katex.min.css").read_text(encoding="utf-8")
        urls = re.findall(r"url\(([^)]*)\)", css)
        self.assertTrue(urls)
        for u in urls:
            u = u.strip("'\"")
            self.assertTrue(u.endswith(".woff2"), u)
            self.assertTrue((KATEX / u).is_file(), u)

    def test_no_legacy_font_formats(self):
        css = (KATEX / "katex.min.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r"\.(woff|ttf)\b(?!2)")
        self.assertNotIn('format("woff")', css)
        self.assertNotIn("truetype", css)


if __name__ == "__main__":
    unittest.main()
