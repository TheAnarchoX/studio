"""The suggestions' helpers (studio/static/book-suggest.js), run in node by tests/js/book_suggest.js: finding a
suggestion's words again in the writing window's text containers (the same cases as the server's, from the shared
fixture tests/fixtures/suggest-locate.json) and the rows of the Suggestions panel. JavaScript never parses Markdown:
the documents come from manuscript.parse, written into a temporary copy of the fixture."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import manuscript

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "studio" / "static"
HARNESS = ROOT / "tests" / "js" / "book_suggest.js"
FIXTURE = ROOT / "tests" / "fixtures" / "suggest-locate.json"


class BookSuggestTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_helpers_in_node(self):
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for c in cases:
            c["doc"] = manuscript.parse(c["md"], c["form"])
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "suggest-locate.json"
            copy.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([shutil.which("node"), str(HARNESS), str(STATIC / "vendor" / "prosemirror.js"),
                                str(STATIC / "book-schema.js"), str(STATIC / "book-text.js"),
                                str(STATIC / "book-tools.js"), str(STATIC / "book-suggest.js"), str(copy)],
                               capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["failures"], [])
        self.assertGreaterEqual(out["checked"], 15)

    def test_panel_wiring(self):
        """The Suggestions panel is the rail's sixth, after Comments, made by book-suggest.js (loaded after the rail);
        a change an accept makes while the author types has its own words on the conflict bar."""
        rail = (STATIC / "book-rail.js").read_text(encoding="utf-8")
        panels = re.search(r"const PANELS = (\[.*?\]);\n", rail).group(1)
        self.assertIn('["comments", "Comments"], ["suggestions", "Suggestions"]', panels)
        self.assertRegex(rail, r"BookSuggest\??\.panel\(")
        self.assertIn("suggestions:", re.search(r"const ICONS = \{.*?\};", rail, re.S).group(0))
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertGreater(html.index('src="/static/book-suggest.js"'), html.index('src="/static/book-rail.js"'))
        editor = (STATIC / "book-editor.js").read_text(encoding="utf-8")
        self.assertRegex(re.search(r"const CHANGED_BY = \{.*?\n  \};", editor, re.S).group(0), r"\n    suggestion: ")
        exported = re.search(r"root\.BookSuggest = \{\.\.\.helpers,?([^}]*)\}", (STATIC / "book-suggest.js").read_text(encoding="utf-8"))
        self.assertIn("panel", exported.group(1))
        self.assertIn("plugins", exported.group(1))

    def test_preview_wiring(self):
        """Every text gets the preview's plugin from book-tools.js, before the tools' own plugin so that right-click on a
        suggestion's words opens its menu and not the style sheet's; its marks are styled in the window's tokens. Focus
        mode hides the rail: the preview draws nothing there and offers no menu."""
        tools = (STATIC / "book-tools.js").read_text(encoding="utf-8")
        body = re.search(r"\n  function plugins\(T\) \{\n(.*?)\n  \}\n", tools, re.S).group(1)
        self.assertLess(body.index("root.BookSuggest?.plugins ? root.BookSuggest.plugins(T) : []"), body.index("contextmenu:"))
        self.assertIn("T.view.setProps({})", re.search(r"\n  function setFocus\(on\) \{\n.*?\n  \}\n", tools, re.S).group(0))
        js = (STATIC / "book-suggest.js").read_text(encoding="utf-8")
        self.assertIn("decorations: state => Tools.state?.focus ? null : KEY.getState(state)", js)
        self.assertRegex(js, r"function menu\(view, e\) \{\n    if \(Tools\.state\?\.focus\) return false;")
        css = (STATIC / "book-tools.css").read_text(encoding="utf-8")
        for rule in (".bk-text .bs-u{", ".bk-text .bs-u.on{", ".bk-text .bs-u.bs-del{", ".bk-text .bs-ins{", ".bk-text .bs-gn{", ".bk-text .bs-gc{"):
            self.assertIn(rule, css)
        self.assertNotIn(".bw.focus .bk-text .bs-", css)
        self.assertIn("line-height:0", re.search(r"\.bk-text \.bs-gn\{[^}]*\}", css).group(0))      # the note mark keeps the line's height


if __name__ == "__main__":
    unittest.main()
