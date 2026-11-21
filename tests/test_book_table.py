"""Tables in the writing window (studio/static/book-table.js), run in node by tests/js/book_table.js: / Table puts in a
table of three columns (a header row and two rows, the cursor in the first cell), and never in a poem piece; Tab and
Shift+Tab walk the cells (Tab in the last cell adds a row), Enter goes down and out of the last row; rows and columns
added and deleted keep `align` one per column; the column's alignment, the header row, Backspace in an empty table; the
keys, the rows for the panel and the palette, the Table button's menu, the decorations; one undo per command; and
documents after an edit that equal what a reload gives."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import manuscript

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "studio" / "static"
HARNESS = ROOT / "tests" / "js" / "book_table.js"

TABLE = "| Naam | Jaar |\n| --- | --: |\n| Een | 1990 |\n| Twee | 2001 |\n"
# table:reload. The harness makes each edit on the document of this Markdown and hands back the document after it; a
# reload (serialize, then parse) must give that same document.
RELOAD = {
    "insert": "Tekst\n",                  # / Table after "Tekst", the header typed with Tab between, "Een" in a row
    "insert-empty": "Tekst\n",            # / Table after "Tekst" and nothing typed: header and rows survive a reload
    "edited": TABLE,                      # a column right of Naam, centred, filled; a row below Een; Twee deleted; Tab
                                          # in the last cell, "Drie" typed
    "header-off": TABLE,                  # Header row off: the table is written with an empty first row
    "pipes": TABLE,                       # "a | b" typed in a cell: the pipe is written \|
    "deleted": "Voor\n\n" + TABLE + "\nNa\n",     # Delete table: Voor and Na again
    "last-row-out": TABLE,                # Enter in the last row, "Na de tabel" typed in the paragraph made after it
    "cells-cleared": TABLE,               # Delete over Na|am … 20|01: the cells' text cleared, rows and columns kept
    "cells-typed": TABLE,                 # "X" typed over E|en … 19|90: into the first cell, the second cleared
    "rectangular": TABLE,                 # a step that takes a cell out of a row: the editor puts an empty one back
    # a selection across the table's edge: the cells' text cleared, the text outside deleted, no cell joined with a line
    "edge-above": "Voor\n\n" + TABLE + "\nNa\n",    # Backspace over Vo|or … Ja|ar
    "edge-below": "Voor\n\n" + TABLE + "\nNa\n",    # Delete over 19|90 … N|a
    "edge-typed": "Voor\n\n" + TABLE + "\nNa\n",    # "X" typed over Tw|ee … N|a: into the cell
}


class BookTableTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_tables_in_node(self):
        payload = {"reload": {name: manuscript.parse(md) for name, md in RELOAD.items()},
                   "pinned": {"row-above-header": manuscript.parse(TABLE), "empty-header-off": manuscript.parse("Tekst\n")}}
        tmp = Path(tempfile.mkdtemp(prefix="studio-booktable-"))
        try:
            (tmp / "input.json").write_text(json.dumps(payload), encoding="utf-8")
            r = subprocess.run([shutil.which("node"), str(HARNESS), str(STATIC / "vendor" / "prosemirror.js"),
                                str(STATIC / "book-schema.js"), str(STATIC / "book-table.js"), str(tmp / "input.json")],
                               capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(out["failures"], [])
        self.assertGreaterEqual(out["checked"], 60)
        # table:reload: the editor's document after each edit is what a reload gives
        self.assertEqual(sorted(out["reload"]), sorted(RELOAD))
        for name, doc in out["reload"].items():
            with self.subTest(scenario=name):
                self.assertEqual(manuscript.parse(manuscript.serialize(doc)), doc)
        # pinned (spec ruling, "Tables in detail"): a row added above the header and left empty is the new header row;
        # Markdown can't write an empty header above rows with text, so a reload gives the table without a header and
        # without that row
        want = manuscript.parse(TABLE)
        want["content"][0]["attrs"]["header"] = False
        self.assertEqual(manuscript.parse(manuscript.serialize(out["pinned"]["row-above-header"])), want)
        # pinned (coordinator's ruling): a table with no text at all is written with its rows as they are, so a still
        # empty table with Header row off comes back with the header on and the same rows
        empty = out["pinned"]["empty-header-off"]
        back = manuscript.parse(manuscript.serialize(empty))
        empty["content"][1]["attrs"]["header"] = True
        self.assertEqual(back, empty)

    def test_loaded_before_the_text(self):
        """index.html loads book-table.js after the schema and before book-text.js (which reads BookTable when it makes
        its view), and book-table.css after book.css."""
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('src="/static/book-schema.js"'), html.index('src="/static/book-table.js"'))
        self.assertLess(html.index('src="/static/book-table.js"'), html.index('src="/static/book-text.js"'))
        self.assertLess(html.index('href="/static/book.css"'), html.index('href="/static/book-table.css"'))


if __name__ == "__main__":
    unittest.main()
