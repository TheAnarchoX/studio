"""Typesetting a piece: a manuscript document as Typst source.

User text only ever enters the source as string literals, so nothing the author types can run as Typst. Each source is
compiled against tests/typst_stub.typ (stand-ins for the template's functions) with Typst's own fonts only, an empty
root and empty package folders, and its markers are read back with queries."""
import json
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import typst

from studio import book_design, book_export, manuscript, typeset

STUB = (Path(__file__).parent / "typst_stub.typ").read_text(encoding="utf-8")
DESIGN = book_design.resolve({"kind": "memoir", "language": "nl", "design": {}},
                             {"fonts": {"text": {"family": "Literata", "weight": 400}}})
PLAIN = {**DESIGN, "headings": {**DESIGN["headings"], "opening": "none"}}       # no small capitals at the opening

DIJK = {"id": "d", "type": "book", "title": "Zee",
        "author":[{"family": "Dijk", "given": "Anna", "non-dropping-particle": "van"}],
        "issued": {"date-parts": [[2019]]}}
BAKKER = {"id": "b", "type": "book", "title": "Land", "author": [{"family": "Bakker", "given": "Jos"}],
          "issued": {"date-parts": [[2020]]}}

LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"')      # a Typst string literal in the source
# Typst syntax an author might type: code, math, labels, references, comments, escapes, a quote and a backslash that
# would close a literal early, and a marker of the typesetter's own.
PAYLOAD = '#let x = 1 $x$ [a] <l> @k \\ " // c /* d */ *b* _i_ \\u{41} ") #metadata((p: 9, b: 9))<blk> #('
ROOT = None


def setUpModule():
    global ROOT
    ROOT = Path(tempfile.mkdtemp(prefix="studio-typeset-"))
    for name in ("root", "packages", "package-cache"):
        (ROOT / name).mkdir()


def tearDownModule():
    shutil.rmtree(ROOT, ignore_errors=True)


def compiler(source):
    """A compiler that reads nothing outside empty folders. One per call: a Compiler made from bytes serves a single
    compile, query or eval (typst 0.15.2 reads its in-memory file once)."""
    return typst.Compiler(source.encode(), root=str(ROOT / "root"), ignore_system_fonts=True,
                          package_path=str(ROOT / "packages"), package_cache_path=str(ROOT / "package-cache"))


def query(source, selector):
    """The values (or element dicts, for elements that aren't metadata) a selector finds in the stubbed document."""
    found = json.loads(compiler(STUB + "\n" + source).query(selector))
    return [m["value"] if m.get("func") == "metadata" else m for m in found]


def set_doc(doc, i=0, kind="chapter", **ctx):
    """Typesets a document as piece `i` and compiles it to PNG (with the stub template); a TypstError fails the test."""
    ctx.setdefault("design", DESIGN)
    c = typeset.Context(**ctx)
    form = (doc.get("attrs") or {}).get("form") or "prose"
    source = typeset.piece(i, {"kind": kind, "form": form}, doc, c)
    pages, warnings = compiler(STUB + "\n" + source).compile_with_warnings(format="png", ppi=36)
    return types.SimpleNamespace(source=source, ctx=c, pages=pages, warnings=[w.message for w in warnings])


def compile_piece(md, form="prose", **ctx):
    return set_doc(manuscript.parse(md, form), **ctx)


def text(s, *marks):
    node = {"type": "text", "text": s}
    if marks:
        node["marks"] = list(marks)
    return node


def para(*content):
    return {"type": "paragraph", "content": list(content)}


def doc(*blocks):
    return {"type": "doc", "attrs": {"form": "prose"}, "content": list(blocks)}


class LiteralTest(unittest.TestCase):
    def test_lit_escapes(self):
        self.assertEqual(typeset.lit('a"b\\c\nd'), '"a\\"b\\\\c\\nd"')
        self.assertEqual(typeset.lit("a\tb"), '"a\\tb"')
        self.assertEqual(typeset.lit("a\x00b\x07c\rd\x1fe"), '"abcde"')       # other C0 controls dropped
        sample = 'Zij zei: "ja" \\ \\u{41} $x$ #let [a] <l> @k „Één” ‘ja’   // */'
        self.assertEqual(json.loads(compiler("").eval(typeset.lit(sample), format="json")), sample)

    def test_split_term(self):
        self.assertEqual(typeset.split_term("trauma > jeugd"), ("trauma", "jeugd"))
        self.assertEqual(typeset.split_term(" trauma "), ("trauma", ""))
        self.assertEqual(typeset.split_term("a  >  b > c"), ("a", "b > c"))


class PieceTest(unittest.TestCase):
    def test_user_text_is_never_code(self):
        md = ('#let x = 1 $x$ [a] <l> @k \\ " // c /* d */ *b* _i_ \\u{41} ") #metadata((p: 9, b: 9))<blk> #("\n\n'
              '= Heading\n\n'
              '#import "@preview/foo:1.0.0": *\n')
        r = compile_piece(md)
        self.assertEqual(r.warnings, [])
        self.assertTrue(r.pages)
        self.assertEqual(len(query(r.source, "<blk>")), 3)
        self.assertEqual(query(r.source, "heading"), [])
        self.assertIn(typeset.lit("= Heading"), r.source)
        self.assertIn(typeset.lit('#import "@preview/foo:1.0.0": *'), r.source)
        # outside the literals there is nothing but what the typesetter wrote itself
        rest = LITERAL.sub("", r.source)
        for typed in ("let", "$", "@", "//", "/*", "import", "Heading"):
            self.assertNotIn(typed, rest)
        # a backslash before a quote, and one at the very end, can't close a literal early
        r = set_doc(doc(para(text('C:\\") #metadata((p: 9, b: 9))<blk> #(" \\'))))
        self.assertEqual(r.warnings, [])
        self.assertEqual(len(query(r.source, "<blk>")), 1)

    def test_user_text_is_never_code_in_any_node(self):
        """The same text in every place a piece carries the author's words besides its paragraphs: an image's caption
        (staged and missing), a citation (a source's author, and a title for a source without one, its prefix and
        locator), a linked poem's lines, table cells, a list marker, the piece's kind, math and its display, a note,
        an index term, an epigraph's attribution. Each compiles without a warning, and the text is only ever inside a
        literal."""
        bad = PAYLOAD
        sources = [{"id": "a", "type": "book", "title": bad, "author": [{"family": bad, "given": bad}],
                    "issued": {"date-parts": [[2001]]}},
                   {"id": "t", "type": "book", "title": bad, "issued": {"date-parts": [[2002]]}}]
        cite = {"type": "cite", "attrs": {"items": [{"key": "a", "prefix": bad, "locator": bad}, {"key": "t"}]}}

        def row(*cells):
            return {"type": "table_row", "content": [{"type": "table_cell", "content": [text(c)]} for c in cells]}

        d = doc(para(text("Zo "), cite, text(" en "), {"type": "note", "content": [text(bad)]}),
                {"type": "image", "attrs": {"src": "a", "alt": bad, "width": "50%"}},
                {"type": "image", "attrs": {"src": "gone", "alt": bad}},
                {"type": "poem", "attrs": {"src": "Reeks/Gedicht"}, "content": []},
                {"type": "table", "attrs": {"header": True}, "content": [row(bad, bad), row(bad, "x")]},
                {"type": "list_item", "attrs": {"list": "decimal", "level": 0, "start": None}, "content": [text(bad)]},
                para(text("Formule "), {"type": "math", "attrs": {"tex": bad}}),
                {"type": "math_display", "attrs": {"tex": bad}},
                para(text(bad, {"type": "idx", "attrs": {"term": bad + " > " + bad}})),
                {"type": "epigraph", "content": [para(text(bad)), {"type": "attribution", "content": [text(bad)]}]})
        stub = types.SimpleNamespace(markers=lambda blocks: [{"marker": bad, "level": 0}
                                                             if b.get("type") == "list_item" else None
                                                             for b in blocks])
        for notes in ("footnotes", "endnotes"):
            with self.subTest(notes=notes), mock.patch.dict(sys.modules, {"studio.manuscript_lists": stub}):
                r = set_doc(d, kind=bad, sources=sources, notes=notes, images={"a": "images/a.png"},
                            linked=lambda src: {"title": bad, "lines": [bad, bad, "", bad]})
                self.assertEqual(r.warnings, [])
                self.assertTrue(r.pages)
                self.assertEqual(len(query(r.source, "<blk>")), len(d["content"]))       # none from the text
                self.assertEqual(len(query(r.source, "<idx>")), 1)
                self.assertEqual(r.ctx.cited, ["a", "t"])
                self.assertIn(typeset.lit(bad), r.source)
                self.assertNotIn(bad, LITERAL.sub("", r.source))
                rest = LITERAL.sub("", r.source)
                for typed in ("let", "$", "@", "//", "/*", "x = 1", "\\u"):
                    self.assertNotIn(typed, rest)
                for e in r.ctx.endnotes:                # a note's body is set later, on the notes page: markup too
                    self.assertNotIn("let", LITERAL.sub("", e["body"]))

    def test_markers_per_block(self):
        r = compile_piece("Een.\n\n## Kop\n\nTwee.\n\nDrie.\n", i=3)
        self.assertEqual(query(r.source, "<blk>"), [{"p": 3, "b": b} for b in range(4)])
        self.assertEqual(query(r.source, "<blkend>"), [{"p": 3, "b": b} for b in (0, 2, 3)])
        self.assertTrue(r.source.startswith('#piece-start(3, "chapter")'))
        self.assertTrue(r.source.rstrip().endswith("#piece-end(3)"))

    def test_blocks(self):
        md = ("# Titel\n\n::: epigraph\nDe zee.\n\n— Anna\n:::\n\n### Klein kopje\n\n> Een citaat.\n\n***\n\n"
              "::: pagebreak\n:::\n\nSlot.\n")
        r = compile_piece(md, design=PLAIN)
        self.assertEqual(r.warnings, [])
        for part in ('#piece-title(0)[#"Titel"]', '#epigraph(([#"De zee."],), [#"Anna"])',
                     '#section(3)[#"Klein kopje"]', '#quote(block: true)[#"Een citaat."]', "#scene-break()",
                     "#pagebreak(weak: true)", '#"Slot."'):
            self.assertIn(part, r.source)
        self.assertEqual([m["b"] for m in query(r.source, "<blk>")], list(range(7)))

    def test_marks_and_inline(self):
        md = ('*schuin* **vet** [klein]{.smallcaps} [word]{lang=en} [hier]{.comment note="geheim briefje"} regel\\\n'
              'nieuw [jeugd]{.idx term="trauma > jeugd"} en [x]{lang=1} [y]{lang=en-GB}\n')
        r = compile_piece(md)
        self.assertEqual(r.warnings, [])
        for part in ('#emph[#"schuin"]', '#strong[#"vet"]', '#smallcaps[#"klein"]', '#text(lang: "en")[#"word"]',
                     '#"hier"', "#linebreak()", '#text(lang: "en", region: "GB")[#"y"]'):
            self.assertIn(part, r.source)
        self.assertNotIn("geheim", r.source)         # a comment prints its text, never its note
        self.assertNotIn('lang: "1"', r.source)       # not a language code: ignored
        self.assertEqual(r.ctx.terms, {("trauma", "jeugd"): "t0"})
        self.assertEqual(query(r.source, "<idx>"), [{"t": "t0"}])

    def test_idx_marker_once_per_marked_run(self):
        idx = {"type": "idx", "attrs": {"term": None}}
        r = set_doc(doc(para(text("de "), text("oude ", idx), text("zee", {"type": "em"}, idx), text(" hier"))))
        self.assertEqual(r.ctx.terms, {("oude zee", ""): "t0"})
        self.assertEqual(query(r.source, "<idx>"), [{"t": "t0"}])

    def test_notes_by_mode(self):
        md = "Tekst^[Een *noot*.] verder.\n"
        r = compile_piece(md, notes="footnotes")
        self.assertIn('#footnote[#"Een "#emph[#"noot"]#"."]', r.source)
        self.assertNotIn("#note-ref", r.source)
        self.assertEqual(r.ctx.endnotes, [])

        r = compile_piece(md, notes="endnotes")
        self.assertIn("#note-ref(0, 1)<noteref-0-1>", r.source)
        self.assertNotIn("#footnote[", r.source)
        self.assertEqual(r.ctx.endnotes, [{"piece": 0, "n": 1, "body": '#"Een "#emph[#"noot"]#"."'}])
        self.assertEqual(len(query(r.source, "<noteref-0-1>")), 1)

        r = compile_piece(md, notes="both")
        self.assertIn("#footnote[", r.source)
        self.assertEqual([(e["piece"], e["n"]) for e in r.ctx.endnotes], [(0, 1)])
        self.assertEqual(len(query(r.source, "<noteref-0-1>")), 1)       # the footnote is the reference

        r = compile_piece(md, notes="off")
        self.assertNotIn("#footnote[", r.source)
        self.assertNotIn("#note-ref", r.source)
        self.assertNotIn("noot", r.source)
        self.assertEqual(r.ctx.endnotes, [])

        for numbering, expected in (("chapter", [(0, 1), (1, 1)]), ("book", [(0, 1), (1, 2)])):
            ctx = typeset.Context(design=DESIGN, notes="endnotes", numbering=numbering)
            for i in (0, 1):
                typeset.piece(i, {"kind": "chapter"}, manuscript.parse(md), ctx)
            self.assertEqual([(e["piece"], e["n"]) for e in ctx.endnotes], expected)

    def test_citations_in_text_and_notes(self):
        r = compile_piece("Zo was het [see @d, p. 12].\n", sources=[DIJK, BAKKER])
        self.assertIn(typeset.lit("(see van Dijk 2019, p. 12)"), r.source)
        self.assertEqual(r.ctx.cited, ["d"])

        r = compile_piece("Zo [@d] was het.^[Zie ook [@b] en [@d].]\n", sources=[DIJK, BAKKER], notes="footnotes")
        self.assertIn(typeset.lit("(Bakker 2020)"), r.source)
        self.assertEqual(r.ctx.cited, ["d", "b"])

        apa = {**DESIGN, "citations": {"style": "apa", "list": "cited"}}
        two = dict(DIJK, author=DIJK["author"] + [{"family": "Jansen", "given": "Piet"}])
        r = compile_piece("Zo [see @d, p. 12].\n", sources=[two], design=apa)
        self.assertIn(typeset.lit("(see van Dijk & Jansen, 2019, p. 12)"), r.source)
        r = compile_piece("Zo [@d].\n", sources=[two], lang="nl")
        self.assertIn(typeset.lit("(van Dijk en Jansen 2019)"), r.source)

    def test_poems(self):
        r = compile_piece("::: poem\nregel een\nregel twee\n\nregel drie\n:::\n")
        self.assertIn("#poem(", r.source)
        self.assertEqual(query(r.source, "<stub-poem>"), [[2, 1]])
        self.assertEqual(r.ctx.first_lines, [])          # a poem inside prose is no poem piece

        r = compile_piece("# Gedicht\n\nwind in de wilgen\nwater\n\nstil\n", form="poem", i=2)
        self.assertEqual(query(r.source, "<stub-poem>"), [[2, 1]])
        self.assertEqual(r.ctx.first_lines, [("wind in de wilgen", 2)])
        self.assertEqual(query(r.source, "<blk>"), [{"p": 2, "b": b} for b in range(3)])
        self.assertEqual(query(r.source, "<blkend>"), [{"p": 2, "b": b} for b in (1, 2)])

        linked = {"Reeks/Gedicht": {"title": "Gedicht", "lines": ["a", "b", "", "c"]}}
        r = compile_piece('::: {.poem src="Reeks/Gedicht"}\n:::\n', form="poem",
                          linked=lambda src: linked.get(src, {"missing": True}))
        self.assertEqual(query(r.source, "<stub-poem>"), [[2, 1]])
        self.assertEqual(r.ctx.first_lines, [("a", 0)])

        r = compile_piece('::: {.poem src="Reeks/Weg"}\n:::\n', linked=lambda src: {"missing": True})
        self.assertEqual(typeset.MISSING_POEM, book_export.MISSING_POEM)
        self.assertIn(typeset.lit(book_export.MISSING_POEM), r.source)
        self.assertEqual(query(r.source, "<stub-poem>"), [])

    def test_images(self):
        md = "![Een kat](../images/a.png){width=60%}\n\n![](../images/missing.png)\n"
        r = compile_piece(md, images={"../images/a.png": "images/a.png"})
        self.assertIn('#image-block("images/a.png", 60%, [#"Een kat"])', r.source)
        self.assertIn("#missing-image(none)", r.source)
        self.assertEqual(r.ctx.missing_images, [(0, "../images/missing.png")])
        self.assertEqual(query(r.source, "<stub-image>"), [{"path": "images/a.png", "width": "60%"}])

        r = compile_piece("![x](../../etc/x.png)\n", images={}, i=4)       # never staged: only shown as missing
        self.assertEqual(r.ctx.missing_images, [(4, "../../etc/x.png")])
        self.assertIn('#missing-image([#"x"])', r.source)

        def image(width):
            return {"type": "image", "attrs": {"src": "a", "alt": "", "width": width}}
        r = set_doc(doc(*(image(w) for w in ("33.5%", "150%", "abc", None, "0%"))), images={"a": "images/a.png"})
        self.assertEqual([m["width"] for m in query(r.source, "<stub-image>")],
                         ["33.5%", "100%", "100%", "100%", "100%"])

    def test_opening_small_caps(self):
        r = compile_piece("# Titel\n\nHet was koud, zei ze.\n\nHet was laat, zei hij.\n")
        self.assertIn('#smallcaps[#"Het was koud"]#", zei ze."', r.source)
        self.assertNotIn('#smallcaps[#"Het was laat"]', r.source)
        self.assertEqual(r.warnings, [])

        r = compile_piece("# Titel\n\n::: epigraph\nDe zee.\n:::\n\nEen twee drie vier vijf zes zeven.\n")
        self.assertIn('#smallcaps[#"Een twee drie vier vijf"]#" zes zeven."', r.source)
        r = compile_piece("# Titel\n\n*Nooit* meer.\n")                  # its marks stay
        self.assertIn('#emph[#smallcaps[#"Nooit"]]#" meer."', r.source)

        r = compile_piece("Het was koud, zei ze.\n")                     # no title: no opening
        self.assertNotIn("#smallcaps", r.source)
        r = compile_piece("# Titel\n\nHet was koud, zei ze.\n", design=PLAIN)
        self.assertNotIn("#smallcaps", r.source)

    def test_dutch_text_kept(self):
        r = compile_piece("„Ja”, zei ze, ‘ja’, 's avonds. [Één]{.idx} keer.\n")
        literals = " ".join(LITERAL.findall(r.source))
        for s in ("„Ja”, zei ze, ‘ja’, 's avonds. ", "Één"):
            self.assertIn(s, literals)
        self.assertTrue({"„", "”", "‘", "’", "'", "É"} <= r.ctx.chars)
        self.assertEqual(r.ctx.terms, {("Één", ""): "t0"})
        self.assertEqual(r.warnings, [])

    def test_editor_power_nodes(self):
        def item(style, level, s):
            return {"type": "list_item", "attrs": {"list": style, "level": level, "start": None}, "content": [text(s)]}

        def row(*cells):
            return {"type": "table_row", "content": [{"type": "table_cell", "content": [text(c)]} for c in cells]}

        d = doc(item("decimal", 0, "Een"), item("decimal", 0, "Twee"), item("bullet", 1, "Sub"),
                {"type": "aligned", "attrs": {"align": "center"}, "content": [para(text("Midden"))]},
                para(text("onder", {"type": "underline"}), text(" "), text("weg", {"type": "strike"}), text(" "),
                     text("groot", {"type": "size", "attrs": {"size": "large"}}), text(" "),
                     text("raar", {"type": "glow"})),
                {"type": "future", "content": [text("Toekomst")]},
                {"type": "table", "attrs": {"header": True, "align": [None, "right"]},
                 "content": [row("Jaar", "Plaats"), row("1984", "Utrecht")]},
                para(text("Formule "), {"type": "math", "attrs": {"tex": "x^2"}}),
                {"type": "math_display", "attrs": {"tex": "\\frac{a}{b}"}})
        with mock.patch.dict(sys.modules, {"studio.manuscript_lists": None}):        # the module isn't there
            r = set_doc(d)
        self.assertEqual(r.warnings, [])
        s = r.source
        self.assertLess(s.index('#list-item(0, "1.")'), s.index('#list-item(0, "2.")'))
        self.assertLess(s.index('#list-item(0, "2.")'), s.index('#list-item(1, "•")'))
        for part in ('#aligned("center")[#"Midden"]', '#underline[#"onder"]', '#strike[#"weg"]',
                     '#text(size: 1.2em)[#"groot"]', '#"raar"', '#"Toekomst"', '#book-table(true, (auto, right), ',
                     '#math-tex("x^2")', '#math-tex-block("\\\\frac{a}{b}")'):
            self.assertIn(part, s)
        self.assertNotIn("glow", s)                   # an unknown mark is ignored
        self.assertEqual(query(s, "<stub-table>"), [{"header": True, "aligns": ["auto", "right"], "rows": [2, 2]}])
        self.assertEqual(r.ctx.math, 2)
        self.assertEqual(len(query(s, "<blk>")), 9)

        def markers(blocks):
            return [({"marker": "IV.", "level": 0} if k == 0 else {"marker": "x.", "level": b["attrs"]["level"]})
                    if b.get("type") == "list_item" else None for k, b in enumerate(blocks)]
        stub = types.SimpleNamespace(markers=markers)
        with mock.patch.dict(sys.modules, {"studio.manuscript_lists": stub}):
            r = set_doc(d)
        self.assertIn('#list-item(0, "IV.")[#"Een"]', r.source)


if __name__ == "__main__":
    unittest.main()
