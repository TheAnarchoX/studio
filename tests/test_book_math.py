"""LaTeX math in the writing window (studio/static/book-math.js), run in node by tests/js/book_math.js: typing `$tex$`
makes inline math as the dialect reads it (manuscript._math_rule), one Backspace gives the dollars back, `$$` + Enter
and / Math put in display math, prices and escaped dollars stay text, math is typed in headings, items, cells, the
title and notes, and KaTeX says what it can't render; documents after typing equal what a reload gives."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import manuscript

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "studio" / "static"
HARNESS = ROOT / "tests" / "js" / "book_math.js"

# math:parity. Each line is typed into an empty paragraph, a character at a time; the paragraph must be what the dialect
# reads from the same line. (No backslashes outside math: in the editor a backslash is text, in Markdown an escape.
# No digit right after a closing dollar: typing makes math at the closing dollar, before the digit is there.)
PARITY = [
    "Een $x^2$ twee",
    "$E = mc^2$",
    "$\\frac{a}{b}$ en $\\sqrt{2}$",
    "Het kost $20 en $30.",
    "Prijs $5 of meer, en $y$.",
    "$a$b$",
    "$a$$b$",
    "$$x$",
    "x$ y$",
    "1$ en 2$",
    "$x $ en $ y$",
    "a $x\\$y$ b",
    "a $x\\\\$ b",
    "$\\{a, b\\}$ is een verzameling",
    "$a \\text{ als $b$ } c$",
    "Dus $x = 1 \\text{ als $y > 0$}$, anders niet.",
]

# math:reload. The harness types into the document of this Markdown and hands back the document after it; a reload
# (serialize, then parse) must give that same document.
RELOAD = {
    "inline": "Een\n",                       # " $x^2$ twee" typed after "Een"
    "heading": "## Over\n",                  # " $E = mc^2$" in a heading
    "item": "- Punt\n",                      # " $a_1$" in a list item
    "cell": "| A |\n| --- |\n| b |\n",       # " $x$" in a table cell
    "title": "# Titel\n\nTekst\n",           # " $\\pi$" in the title
    "escaped": "Prijs\n",                    # " \\$5 en $y\\$z$": an escaped dollar in the text and in the TeX
    "text-group": "Dus\n",                   # " $x = 1 \\text{ als $y > 0$}$": math in a \text{…} group, dollars and all
    "display": "Tekst\n",                    # `$$` + Enter on a new line, the source filled in, "Na" typed after it
    # the source field: what it writes, from untidy source, is what a reload gives
    "source-inline": "Een\n",                # " $x$" typed, then its source set to SOURCE_INLINE in the field
    "source-display": "Tekst\n",             # as "display", its source set to SOURCE_DISPLAY in the field
}
SOURCE_INLINE = "  a$b + \\text{als $y$}\n c \\"
SOURCE_DISPLAY = "\n    a $$ b  \n\n\n      c\r\n    d   \n"

# math:source. Untidy source typed in the field, and the TeX the dialect writes of it (manuscript._inline_tex for
# inline math; manuscript._display_lines, then _display_dollars, for display math): the field writes that TeX.
SOURCE = [
    (" x ", False), ("x\\", False), ("\\", False), ("x \\\\", False), ("x\\\\\\", False), ("a\nb", False),
    ("  a \r\n  b  ", False), ("a$b", False), ("\\text{if $y$} z", False), ("\\text{ab", False), ("$", False),
    ("a\n\n\nb  ", True), ("  a\n    b\n", True), ("a $$ b", True), ("\\text{if $y$}", True), ("x\r\ny", True),
    ("\n \n", True), ("\ta\n\tb", True), ("$$$", True),
    (SOURCE_INLINE, False), (SOURCE_DISPLAY, True),
]


def _written(tex, display):
    """The TeX the dialect writes of `tex` in display or inline math."""
    if display:
        return manuscript._display_dollars(manuscript._display_lines(tex))
    return manuscript._inline_tex(tex)


class BookMathTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_math_in_node(self):
        payload = {"parity": [{"line": line, "content": manuscript.parse(line + "\n")["content"][0].get("content", [])}
                              for line in PARITY],
                   "reload": {name: manuscript.parse(md) for name, md in RELOAD.items()},
                   "source": [{"tex": tex, "display": display, "want": _written(tex, display)} for tex, display in SOURCE],
                   "sourceInline": SOURCE_INLINE, "sourceDisplay": SOURCE_DISPLAY}
        tmp = Path(tempfile.mkdtemp(prefix="studio-bookmath-"))
        try:
            (tmp / "input.json").write_text(json.dumps(payload), encoding="utf-8")
            r = subprocess.run([shutil.which("node"), str(HARNESS), str(STATIC / "vendor" / "prosemirror.js"),
                                str(STATIC / "book-schema.js"), str(STATIC / "book-math.js"),
                                str(STATIC / "vendor" / "katex" / "katex.min.js"), str(tmp / "input.json"),
                                str(STATIC / "book-format.js"), str(STATIC / "book-text.js")],
                               capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(out["failures"], [])
        self.assertGreaterEqual(out["checked"], len(PARITY) + 50)
        # the parity lines hold math the dialect reads, and lines it leaves text
        kinds = {any(n["type"] == "math" for n in p["content"]) for p in payload["parity"]}
        self.assertEqual(kinds, {True, False})
        # math:reload: the editor's document after typing is what a reload gives
        self.assertEqual(sorted(out["reload"]), sorted(RELOAD))
        for name, doc in out["reload"].items():
            with self.subTest(scenario=name):
                self.assertTrue(any(n["type"] in ("math", "math_display") for n in _nodes(doc)), doc)
                self.assertEqual(manuscript.parse(manuscript.serialize(doc)), doc)

    def test_loaded_in_order(self):
        """index.html loads KaTeX, then book-math.js, before book-text.js (which takes its node views, typing rule and
        Enter); KaTeX's style sheet after book.css, book-math.css after KaTeX's."""
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        at = html.index
        self.assertLess(at('src="/static/book-schema.js"'), at('src="/static/vendor/katex/katex.min.js"'))
        self.assertLess(at('src="/static/vendor/katex/katex.min.js"'), at('src="/static/book-math.js"'))
        self.assertLess(at('src="/static/book-math.js"'), at('src="/static/book-text.js"'))
        self.assertLess(at('href="/static/book.css"'), at('href="/static/vendor/katex/katex.min.css"'))
        self.assertLess(at('href="/static/vendor/katex/katex.min.css"'), at('href="/static/book-math.css"'))


def _nodes(node):
    """Every node of a document (JSON), the document first."""
    yield node
    for child in node.get("content") or []:
        yield from _nodes(child)


if __name__ == "__main__":
    unittest.main()
