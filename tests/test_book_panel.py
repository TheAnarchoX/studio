"""The format panel and the palette's Format group (studio/static/book-panel.js), run in node by tests/js/book_panel.js:
the rows and buttons the panel shows where the cursor is (a table's in a table) and which are pressed, the palette's commands that apply
there, keys as written on Windows and macOS, where the panel goes, and how the arrow keys and Tab move in it."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "studio" / "static"
HARNESS = ROOT / "tests" / "js" / "book_panel.js"


class BookPanelTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_panel_in_node(self):
        r = subprocess.run([shutil.which("node"), str(HARNESS), str(STATIC / "vendor" / "prosemirror.js"),
                            str(STATIC / "book-schema.js"), str(STATIC / "book-format.js"), str(STATIC / "book-panel.js"),
                            str(STATIC / "book-table.js")],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["failures"], [])
        self.assertGreaterEqual(out["checked"], 35)

    def test_loaded_after_book_format(self):
        """index.html loads the panel after book-format.js (it adds to BookFormat), its style sheet after book-format.css."""
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('src="/static/book-format.js"'), html.index('src="/static/book-panel.js"'))
        self.assertLess(html.index('href="/static/book-format.css"'), html.index('href="/static/book-panel.css"'))


if __name__ == "__main__":
    unittest.main()
