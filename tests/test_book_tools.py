"""The writing tools' helpers (studio/static/book-tools.js), run in node by tests/js/book_tools.js: numbers as words in
Dutch and English, the style sheet's checks (terms, numbers, straight quotes), echoes, sentences, fuzzy matching for the
command palette, authors with name particles, source keys, find as the server finds, the history's comparison and the
outline of a piece."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "studio" / "static"
HARNESS = ROOT / "tests" / "js" / "book_tools.js"


class BookToolsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_helpers_in_node(self):
        r = subprocess.run([shutil.which("node"), str(HARNESS), str(STATIC / "vendor" / "prosemirror.js"),
                            str(STATIC / "book-schema.js"), str(STATIC / "book-text.js"), str(STATIC / "book-tools.js")],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["failures"], [])
        self.assertGreater(out["checked"], 75)

    def test_no_control_characters(self):
        """The tools' files hold text only: no stray control bytes (a BEL once stood in for an escape)."""
        for name in ("book-tools.js", "book-rail.js", "book-tools.css"):
            data = (STATIC / name).read_bytes()
            bad = sorted({b for b in data if b < 0x20 and b not in (0x09, 0x0A, 0x0D)})
            self.assertEqual(bad, [], f"{name} has control bytes {bad}")


if __name__ == "__main__":
    unittest.main()
