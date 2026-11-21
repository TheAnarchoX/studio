"""The board's helpers and save queue (studio/static/board-core.js), run in node by tests/js/board.js: frames and cards
on the canvas, grouping and sorting, fitting the view, the quote a card becomes in the text, the drag payload, the
filter, and the item text's save queue (debounce, conflicts, kept text); the text side of the board beside the text
(studio/static/board-rail.js), run by tests/js/board_rail.js; and the canvas's helpers and the undo stack
(studio/static/board-canvas.js), run by tests/js/board_canvas.js."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "studio" / "static"
HARNESS = ROOT / "tests" / "js" / "board.js"


class BoardCoreTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_helpers_in_node(self):
        r = subprocess.run([shutil.which("node"), str(HARNESS), str(STATIC / "vendor" / "prosemirror.js"),
                            str(STATIC / "book-schema.js"), str(STATIC / "book-text.js"), str(STATIC / "board-core.js")],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["failures"], [])
        self.assertGreater(out["checked"], 30)

    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_into_the_text_in_node(self):
        """board-rail.js: what a prepared quote, source or image becomes in the text, where a drop puts it (inline, or a
        block after the top-level block there, never nested), the one transaction, and the drop place kept through
        changes (tests/js/board_rail.js)."""
        r = subprocess.run([shutil.which("node"), str(ROOT / "tests" / "js" / "board_rail.js"),
                            *(str(STATIC / f) for f in ("vendor/prosemirror.js", "book-schema.js", "book-text.js",
                                                        "board-core.js", "board-rail.js"))],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["failures"], [])
        self.assertGreater(out["checked"], 50)

    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_canvas_in_node(self):
        """board-canvas.js's helpers: the view and its zoom, fitting, the view kept in the browser, the selection box,
        where dragged, nudged and resized cards land and in which frame, a frame moved with its cards, what a drop
        holds, a card's escaped HTML with the style's quote marks, and the undo stack (tests/js/board_canvas.js)."""
        r = subprocess.run([shutil.which("node"), str(ROOT / "tests" / "js" / "board_canvas.js"),
                            *(str(STATIC / f) for f in ("vendor/prosemirror.js", "book-schema.js", "book-text.js",
                                                        "board-core.js", "board-canvas.js"))],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["failures"], [])
        self.assertGreater(out["checked"], 90)

    def test_no_control_characters(self):
        """The board's files hold text only: no stray control bytes (a BEL once stood in for an escape)."""
        for name in ("board-core.js", "board.js", "board.css", "board-rail.js", "board-rail.css", "board-canvas.js",
                     "board-canvas.css"):
            data = (STATIC / name).read_bytes()
            bad = sorted({b for b in data if b < 0x20 and b not in (0x09, 0x0A, 0x0D)})
            self.assertEqual(bad, [], f"{name} has control bytes {bad}")


if __name__ == "__main__":
    unittest.main()
