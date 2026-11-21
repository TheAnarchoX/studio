"""The writing window's lists (studio/static/book-format.js), run in node by tests/js/book_format.js: the markers of
every sample (the same as manuscript_lists.markers), the typing triggers and their undo, Enter, Backspace, Tab and
Shift+Tab in a list, setList, the plugin that keeps a list's numbers, and documents after an edit that equal what a
reload gives."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import manuscript, manuscript_lists
from tests.test_manuscript import POEM_SAMPLES, SAMPLES

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "studio" / "static"
HARNESS = ROOT / "tests" / "js" / "book_format.js"

LIST = "1. Een\n2. Twee\n3. Drie\n4. Vier\n"
# numbers:reload-equal. The harness makes each edit on the document of this Markdown and hands back the document after
# it; a reload (serialize, then parse) must give that same document.
RELOAD = {
    "enter-ends-list": LIST,      # Enter twice at the end of "Twee", then "Tussendoor." typed: 1, 2, text, 3, 4
    "tab-nests": LIST,            # Tab on "Twee", Tab twice on "Drie": 1, a, i, 2
    "scene-between": LIST,        # a scene break put between "Twee" and "Drie": 1, 2, ***, 3, 4
    "bullet-in-numbers": LIST,    # "Twee" made a bulleted item: 1, •, 2, 3
    # v1.2 wrote these markers as text (`a. ` reads as an item now): Make a list of these lines on all of it
    "from-text": "Tekst\n\n• een\n\n1\\. twee\n\na. drie\n",
    "centre-join": "Een\n\nTwee\n\nDrie\n",       # "Een" centred, then "Twee" (joined), "Drie" right
    "heading-in-list": LIST,                       # "Twee" made a heading: 1, heading, 2, 3
    "quotation-join": "Een\n\nTwee\n\nDrie\n",     # "Twee" a quotation, then Ctrl+] on "Drie" (joined)
    "size-steps": "Een twee drie\n",               # "twee" two steps larger, "drie" one smaller
    "heading-note-break": "Kop^[Een\\\ntwee]\n",  # made a heading: the line break in its note a space
    # a list that counted on follows the earlier list: Enter after "Twee" and "Nieuw" typed (1, 2, 3, text, 4, 5); "Twee"
    # deleted (1, text, 2, 3)
    "counted-on-grows": "1. Een\n2. Twee\n\nTussen\n\n3. Drie\n4. Vier\n",
    "counted-on-shrinks": "1. Een\n2. Twee\n\nTussen\n\n3. Drie\n4. Vier\n",
}


def _doc(*blocks):
    """A document of list items, given as (style, level, start), and paragraphs, given as None."""
    def block(b):
        if b is None:
            return {"type": "paragraph", "content": [{"type": "text", "text": "Tekst"}]}
        style, level, start = b
        return {"type": "list_item", "attrs": {"list": style, "level": level, "start": start},
                "content": [{"type": "text", "text": "Punt"}]}
    return {"type": "doc", "attrs": {"form": "prose"}, "content": [block(b) for b in blocks]}


# markers:parity beyond what Markdown writes: levels to clamp, starts kept and ignored, letters past z, bullets by level
EXTRA = [
    _doc(("decimal", 2, None), ("decimal", 3, None)),
    _doc(("bullet", 0, None), ("bullet", 3, None), ("bullet", 2, None), ("bullet", 1, None), ("bullet", 3, None)),
    _doc(("bullet", 0, None), ("bullet", 1, None), ("bullet", 2, None), ("bullet", 3, None), ("bullet", 3, None)),
    _doc(("lower-alpha", 0, 27), ("lower-alpha", 0, None), ("upper-alpha", 0, 52)),
    _doc(("decimal", 0, 0), ("lower-roman", 0, 0), ("bullet", 0, 5), ("upper-roman", 0, 14), ("upper-roman", 0, None)),
    _doc(("decimal", 0, None), None, ("decimal", 0, None), ("lower-alpha", 1, None), ("decimal", 0, 5)),
    _doc(("decimal", 0, 3), ("lower-alpha", 1, 2), ("upper-roman", 2, None), ("lower-alpha", 1, 9), ("decimal", 0, None)),
    # starts as far as they go: nine digits (CommonMark), roman numerals up to 3999; past that a list starts at 1
    _doc(("decimal", 0, 999_999_999), ("decimal", 0, None), None, ("decimal", 0, 1_000_000_000)),
    _doc(("lower-roman", 0, 3999), ("upper-roman", 0, 4000), ("lower-alpha", 0, 1_000_000_000), ("upper-alpha", 0, 999_999_999)),
]


class BookFormatTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_lists_in_node(self):
        docs = [manuscript.parse(md) for md in SAMPLES] + [manuscript.parse(md, "poem") for md in POEM_SAMPLES] + EXTRA
        payload = {"samples": [{"doc": d, "markers": manuscript_lists.markers(d.get("content") or [])} for d in docs],
                   "reload": {name: manuscript.parse(md) for name, md in RELOAD.items()}}
        tmp = Path(tempfile.mkdtemp(prefix="studio-bookformat-"))
        try:
            (tmp / "input.json").write_text(json.dumps(payload), encoding="utf-8")
            r = subprocess.run([shutil.which("node"), str(HARNESS), str(STATIC / "vendor" / "prosemirror.js"),
                                str(STATIC / "book-schema.js"), str(STATIC / "book-format.js"), str(tmp / "input.json")],
                               capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(out["failures"], [])
        self.assertGreaterEqual(out["checked"], len(SAMPLES) + 30)
        # numbers:reload-equal: the editor's document after each edit is what a reload gives
        self.assertEqual(sorted(out["reload"]), sorted(RELOAD))
        for name, doc in out["reload"].items():
            with self.subTest(scenario=name):
                self.assertEqual(manuscript.parse(manuscript.serialize(doc)), doc)


if __name__ == "__main__":
    unittest.main()
