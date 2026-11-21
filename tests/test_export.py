"""Book export tests (.docx, Markdown, zip, citations). Run: python -m unittest discover tests"""
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from PIL import Image

from studio import book_export
from studio.books import Books, BooksError



def _png():
    out = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(out, "PNG")
    return out.getvalue()


PNG = _png()

CHAPTER = """# The Harbour

Gulls circled *twice* over the **quay**. [Remark]{.comment note="cut this"} The [lamp]{.idx term="lighting"}
burned. A [word]{lang=nl} here.^[First note, *with* style.]

## The Water

### Low tide

* * *

::: epigraph
Salt keeps what the sea gives.

— An Old Saying
:::

::: poem
a line of the poem
and its second line

the next stanza
:::

> A quoted passage that is indented.

![The pier](../images/pier.png){width=50%}

![Gone](../images/gone.png)

As [@tide, p. 12] says; see also [see @tide; @unknown].^[Second note.]
"""

SOURCES = [{"id": "tide", "type": "book", "title": "Tides", "author": [{"family": "Marsh", "given": "A."}],
            "issued": {"date-parts": [[1999]]}}]


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-export-"))
        self.lib = self.tmp / "lib"
        self.b = Books(self.lib / "Books")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, language="en", title="The Long Road", numbering="chapter"):
        book = self.b.create(title, "A. Writer", language, "memoir")
        bid = book["id"]
        self.b.update(bid, {"subtitle": "A small subtitle", "features": {"noteNumbering": numbering}})
        files = [e["file"] for e in self.b.read(bid)["contents"] if e.get("file")]
        d = self.lib / "Books" / bid
        (d / "manuscript" / files[0]).write_text("# Dedication\n\nFor the ones who waited.\n", encoding="utf-8")
        (d / "manuscript" / files[1]).write_text(CHAPTER, encoding="utf-8")
        (d / "images").mkdir(exist_ok=True)
        (d / "images" / "pier.png").write_bytes(PNG)
        (d / "sources.json").write_text(json.dumps(SOURCES), encoding="utf-8")
        return bid, files

    def open(self, data):
        return Document(io.BytesIO(data))

    def test_docx_lists_alignment_and_marks(self):
        bid, files = self.make()
        md = ("# Kop\n\n1. Een\n2. Twee\n   a. Sub\n\nTussen.\n\n3. Drie\n\n- Punt\n\n::: center\nMidden\n:::\n\n"
              "::: right\nRechts\n:::\n\nEen [o]{.underline} ~~s~~ [g]{.large} woord.\n")
        (self.lib / "Books" / bid / "manuscript" / files[1]).write_text(md, encoding="utf-8")
        doc = self.open(book_export.to_docx(self.b, bid))
        by = {p.text: p for p in doc.paragraphs}

        def num(p):
            ilvl = p._p.xpath("./w:pPr/w:numPr/w:ilvl/@w:val")
            nid = p._p.xpath("./w:pPr/w:numPr/w:numId/@w:val")
            return (int(ilvl[0]), int(nid[0])) if ilvl else None

        names = ["Een", "Twee", "Sub", "Drie", "Punt"]
        self.assertEqual([num(by[n])[0] for n in names], [0, 0, 1, 0, 0])
        self.assertIsNone(num(by["Tussen."]))
        self.assertEqual(num(by["Een"])[1], num(by["Twee"])[1])
        self.assertEqual(len({num(by[n])[1] for n in names}), 4)       # Een/Twee share; the others have their own

        numbering = doc.part.numbering_part.element

        def level(p):
            lvl, nid = num(p)
            abstract = numbering.xpath(f"w:num[@w:numId='{nid}']/w:abstractNumId/@w:val")[0]
            return numbering.xpath(f"w:abstractNum[@w:abstractNumId='{abstract}']/w:lvl[@w:ilvl='{lvl}']")[0]

        def val(el, tag):
            return el.find(qn(f"w:{tag}")).get(qn("w:val"))

        self.assertEqual(val(level(by["Drie"]), "numFmt"), "decimal")
        self.assertEqual(val(level(by["Drie"]), "start"), "3")
        self.assertEqual(val(level(by["Sub"]), "numFmt"), "lowerLetter")
        self.assertEqual(val(level(by["Punt"]), "numFmt"), "bullet")
        self.assertEqual(val(level(by["Een"]), "start"), "1")
        self.assertEqual(by["Een"].style.name, "List Paragraph")
        self.assertEqual(by["Midden"].alignment, WD_ALIGN_PARAGRAPH.CENTER)
        self.assertEqual(by["Rechts"].alignment, WD_ALIGN_PARAGRAPH.RIGHT)
        body = next(p for p in doc.paragraphs if p.text.startswith("Een o"))
        runs = {r.text: r for r in body.runs}
        self.assertTrue(runs["o"].underline)
        self.assertTrue(runs["s"].font.strike)
        base = doc.styles["Normal"].font.size
        base = base.pt if base else 11
        self.assertAlmostEqual(runs["g"].font.size.pt, base * 1.2, delta=0.25)       # Word sizes are half-points

    def test_docx_table(self):
        bid, files = self.make(language="nl")
        md = ("Voor.\n\n| Jaar | Plaats |\n| --- | :-: |\n| 1984 | Utrecht |\n| 1990 | *Gent*^[Een noot.] |\n\n"
              "Na.\n\n|  |  |\n| --- | --: |\n| a | b |\n")
        (self.lib / "Books" / bid / "manuscript" / files[1]).write_text(md, encoding="utf-8")
        doc = self.open(book_export.to_docx(self.b, bid))
        first, second = doc.tables
        self.assertEqual((len(first.rows), len(first.columns)), (3, 2))
        self.assertEqual(first.style.name, "Table Grid")
        self.assertEqual([c.text for c in first.rows[0].cells], ["Jaar", "Plaats"])
        self.assertTrue(all(r.bold for c in first.rows[0].cells for r in c.paragraphs[0].runs))
        self.assertEqual(len(first.rows[0]._tr.xpath("./w:trPr/w:tblHeader")), 1)
        self.assertEqual(first.rows[1]._tr.xpath("./w:trPr/w:tblHeader"), [])
        self.assertFalse(any(r.bold for c in first.rows[1].cells for r in c.paragraphs[0].runs))
        self.assertEqual(first.cell(1, 1).paragraphs[0].alignment, WD_ALIGN_PARAGRAPH.CENTER)
        self.assertIsNone(first.cell(1, 0).paragraphs[0].alignment)
        self.assertEqual(first.cell(2, 1).text, "Gent1")
        self.assertTrue(first.cell(2, 1).paragraphs[0].runs[0].italic)
        texts = [p.text for p in doc.paragraphs]
        self.assertIn("Noten", texts)
        self.assertIn("1. Een noot.", texts)
        # no header: no empty first row, nothing marked as a header; the right-aligned column
        self.assertEqual((len(second.rows), len(second.columns)), (1, 2))
        self.assertEqual(second.rows[0]._tr.xpath("./w:trPr/w:tblHeader"), [])
        self.assertFalse(any(r.bold for r in second.cell(0, 1).paragraphs[0].runs))
        self.assertEqual(second.cell(0, 1).paragraphs[0].alignment, WD_ALIGN_PARAGRAPH.RIGHT)

    def test_tables_side_by_side_stay_two_tables(self):
        """Word joins two tables with nothing between them into one: an empty paragraph keeps them apart."""
        bid, files = self.make()
        md = "| a |\n| --- |\n| b |\n\n| c | d |\n| --- | --- |\n| e | f |\n"
        (self.lib / "Books" / bid / "manuscript" / files[1]).write_text(md, encoding="utf-8")
        doc = self.open(book_export.to_docx(self.b, bid))
        self.assertEqual(len(doc.tables), 2)
        tags = [el.tag for el in doc.element.body]
        k = tags.index(qn("w:tbl"))
        self.assertEqual(tags[k + 1:k + 3], [qn("w:p"), qn("w:tbl")])
        self.assertEqual(doc.element.body[k + 1].xpath("string(.)"), "")

    def test_docx_math_is_its_source_in_cambria_math(self):
        bid, files = self.make()
        md = ("Einstein schreef $E = mc^2$ en meer.\n\n$$\n\\int_0^1 x\\,dx\n= \\frac{1}{2}\n$$\n\n"
              "| a |\n| --- |\n| $y$ |\n")
        (self.lib / "Books" / bid / "manuscript" / files[1]).write_text(md, encoding="utf-8")
        doc = self.open(book_export.to_docx(self.b, bid))

        def font(run):
            fonts = run._r.find(qn("w:rPr")).find(qn("w:rFonts"))
            return [fonts.get(qn(f"w:{k}")) for k in ("ascii", "hAnsi", "cs")]

        body = next(p for p in doc.paragraphs if p.text.startswith("Einstein"))
        self.assertEqual(body.text, "Einstein schreef $E = mc^2$ en meer.")
        run = next(r for r in body.runs if r.text == "$E = mc^2$")
        self.assertEqual(font(run), ["Cambria Math"] * 3)
        self.assertIsNone(body.runs[0]._r.find(qn("w:rPr")))           # the text around it keeps its own font
        shown = next(p for p in doc.paragraphs if p.text.startswith("$$"))
        self.assertEqual(shown.text, "$$\\int_0^1 x\\,dx\n= \\frac{1}{2}$$")
        self.assertEqual(shown.alignment, WD_ALIGN_PARAGRAPH.CENTER)
        self.assertTrue(shown.runs and all(font(r) == ["Cambria Math"] * 3 for r in shown.runs))
        cell = doc.tables[0].cell(1, 0).paragraphs[0]
        self.assertEqual((cell.text, font(cell.runs[0])), ("$y$", ["Cambria Math"] * 3))

    def test_docx_has_the_book(self):
        bid, _ = self.make()
        doc = self.open(book_export.to_docx(self.b, bid))
        paras = doc.paragraphs
        heads = [(p.style.name, p.text) for p in paras if p.style.name.startswith(("Heading", "Title"))]
        self.assertEqual(heads, [("Title", "The Long Road"), ("Title", "The Long Road"),
                                 ("Heading 1", "The Harbour"), ("Heading 2", "The Water"),
                                 ("Heading 3", "Low tide"), ("Heading 1", "Notes"), ("Heading 3", "The Harbour")])
        ded = next(p for p in paras if p.text == "For the ones who waited.")
        self.assertEqual(ded.alignment, WD_ALIGN_PARAGRAPH.CENTER)
        self.assertTrue(ded.runs[0].italic)
        self.assertIn("A small subtitle", [p.text for p in paras])
        self.assertIn("A. Writer", [p.text for p in paras])
        body = next(p for p in paras if p.text.startswith("Gulls circled"))
        self.assertTrue(any(r.italic and r.text == "twice" for r in body.runs))
        self.assertTrue(any(r.bold and r.text == "quay" for r in body.runs))
        text = "\n".join(p.text for p in paras)
        self.assertNotIn("cut this", text)            # the comment's text is gone; the words it sat on stay
        self.assertIn("Remark", text)
        self.assertIn("lamp", text)
        self.assertNotIn("lighting", text)
        self.assertIn("A word here.", text)
        self.assertIn("1. First note, with style.", text)
        self.assertIn("2. Second note.", text)
        self.assertIn("(Marsh 1999, p. 12)", text)
        self.assertIn("(see Marsh 1999; unknown)", text)
        att = next(p for p in paras if p.text == "An Old Saying")
        self.assertEqual(att.alignment, WD_ALIGN_PARAGRAPH.RIGHT)
        epi = next(p for p in paras if p.text == "Salt keeps what the sea gives.")
        self.assertTrue(epi.runs[0].italic)
        star = [p for p in paras if p.text == "* * *"]
        self.assertEqual(len(star), 1)
        self.assertEqual(star[0].alignment, WD_ALIGN_PARAGRAPH.CENTER)
        poem = next(p for p in paras if p.text.startswith("a line of the poem"))
        self.assertEqual(poem.text, "a line of the poem\nand its second line")
        self.assertNotEqual(poem.alignment, WD_ALIGN_PARAGRAPH.JUSTIFY)
        quote = next(p for p in paras if p.text.startswith("A quoted passage"))
        self.assertTrue(quote.paragraph_format.left_indent)
        self.assertEqual(len(doc.inline_shapes), 1)          # the missing image is skipped
        sec = doc.sections[0]
        text_width = sec.page_width - sec.left_margin - sec.right_margin
        self.assertAlmostEqual(doc.inline_shapes[0].width / text_width, 0.5, places=2)

    def test_notes_heading_is_dutch_and_numbering_follows_the_book(self):
        bid, files = self.make("nl")
        d = self.lib / "Books" / bid / "manuscript"
        second = self.b.new_piece(bid, "chapter", "prose", "Two")
        (d / second["file"]).write_text("# Two\n\nMore.^[Third.]\n", encoding="utf-8")
        text = "\n".join(p.text for p in self.open(book_export.to_docx(self.b, bid)).paragraphs)
        self.assertIn("Noten", text)
        self.assertIn("1. Third.", text)              # restarts per chapter
        self.b.update(bid, {"features": {"noteNumbering": "book"}})
        text = "\n".join(p.text for p in self.open(book_export.to_docx(self.b, bid)).paragraphs)
        self.assertIn("3. Third.", text)

    def test_notes_inside_poems_are_numbered_and_listed(self):
        bid, files = self.make()
        d = self.lib / "Books" / bid / "manuscript"
        (d / files[1]).write_text("# One\n\nBody.^[First.]\n\n::: poem\nl1^[In poem.]\nl2\n:::\n", encoding="utf-8")
        second = self.b.new_piece(bid, "chapter", "prose", "Two")
        (d / second["file"]).write_text("# Two\n\nMore.^[Later.]\n", encoding="utf-8")
        for numbering, want in (("chapter", ["1. First.", "2. In poem.", "1. Later."]),
                                ("book", ["1. First.", "2. In poem.", "3. Later."])):
            self.b.update(bid, {"features": {"noteNumbering": numbering}})
            paras = self.open(book_export.to_docx(self.b, bid)).paragraphs
            self.assertEqual([p.text for p in paras if p.text[:2] in ("1.", "2.", "3.")], want)
            poem = next(p for p in paras if p.text.startswith("l1"))
            self.assertEqual(poem.text, "l12\nl2")

    def test_control_characters_do_not_break_the_docx(self):
        bid, files = self.make(title="Title\x00 here")
        d = self.lib / "Books" / bid / "manuscript"
        (d / files[1]).write_text("# Ch\x0bapter\n\nOne\x0btwo\x00 three \x1f four.\n", encoding="utf-8")
        self.b.update(bid, {"author": "Au\x0cthor"})
        paras = self.open(book_export.to_docx(self.b, bid)).paragraphs
        text = "\n".join(p.text for p in paras)
        self.assertIn("One\ntwo", text)
        self.assertIn("three  four.", text)
        self.assertIn("Ch\napter", text)

    def test_piece_titles_keep_their_marks(self):
        bid, files = self.make()
        d = self.lib / "Books" / bid / "manuscript"
        (d / files[1]).write_text("# The *Long* Night\n\nText.\n", encoding="utf-8")
        head = next(p for p in self.open(book_export.to_docx(self.b, bid)).paragraphs if p.style.name == "Heading 1")
        self.assertTrue(any(r.italic and r.text == "Long" for r in head.runs))

    def test_image_has_alt_text(self):
        bid, _ = self.make()
        xml = self.open(book_export.to_docx(self.b, bid)).element.xml
        self.assertIn('descr="The pier"', xml)

    def test_export_survives_a_kept_copy_held_open(self):
        if sys.platform != "win32":
            self.skipTest("Windows refuses to replace an open file")
        import ctypes
        from ctypes import wintypes
        bid, _ = self.make()
        name, _, _ = book_export.export(self.b, bid, "docx")
        [kept] = (self.lib / "Books" / bid / "exports").iterdir()
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                    wintypes.DWORD, wintypes.HANDLE]
        h = k32.CreateFileW(str(kept), 0x80000000, 1, None, 3, 0x80, None)      # others may read it, not write it
        self.assertNotEqual(h, wintypes.HANDLE(-1).value)
        try:
            name2, data, _ = book_export.export(self.b, bid, "docx")
        finally:
            k32.CloseHandle(h)
        self.assertEqual(name2, name)
        self.assertTrue(data.startswith(b"PK"))
        self.assertEqual(len(list(kept.parent.iterdir())), 2)          # a new dated copy beside the one held open
        self.assertEqual([p.name for p in kept.parent.iterdir() if p.name.startswith(".")], [])      # no temp left

    def test_export_name_is_safe_for_a_reserved_title(self):
        bid, _ = self.make()
        self.b.update(bid, {"title": "Con"})
        name, _, _ = book_export.export(self.b, bid, "md")
        self.assertEqual(name, "Con-1.md")
        [kept] = (self.lib / "Books" / bid / "exports").iterdir()
        self.assertRegex(kept.name, r"^Con-1 \d{4}-\d{2}-\d{2} \d{4}\.md$")

    def test_linked_poem_comes_from_the_library(self):
        bid, files = self.make()
        pdir = self.lib / "Poems" / "Series" / "one"
        pdir.mkdir(parents=True)
        (pdir / "poem.json").write_text(json.dumps({"title": "One", "lines": ["first line", "second line", "", "third"]}),
                                        encoding="utf-8")
        d = self.lib / "Books" / bid / "manuscript"
        (d / files[1]).write_text('# Ch\n\n::: {.poem src="Series/one"}\n:::\n\n::: {.poem src="Series/gone"}\n:::\n',
                                  encoding="utf-8")
        text = "\n".join(p.text for p in self.open(book_export.to_docx(self.b, bid)).paragraphs)
        self.assertIn("first line\nsecond line", text)
        self.assertIn("third", text)
        self.assertIn("This poem is no longer in your Poems library.", text)

    def test_markdown_export_keeps_order_and_kinds(self):
        bid, files = self.make()
        md = book_export.to_markdown(self.b, bid).decode("utf-8")
        self.assertLess(md.index("<!-- kind: dedication; form: prose -->"), md.index("<!-- kind: chapter; form: prose -->"))
        self.assertLess(md.index("# Dedication"), md.index("# The Harbour"))
        self.assertIn("Gulls circled *twice*", md)
        self.assertNotIn("\r", md)

    def test_docx_generated_pages(self):
        bid, files = self.make("nl")
        d = self.lib / "Books" / bid / "manuscript"
        (d / files[1]).write_text('# De haven\n\nEen [jeugd]{.idx term="trauma > jeugd"} lang geleden.^[Een noot.]\n',
                                  encoding="utf-8")
        self.b.update(bid, {"features": {"notes": "endnotes", "index": True, "sources": True}})
        contents = [{k: v for k, v in e.items() if k in ("auto", "file", "kind", "form")}
                    for e in self.b.read(bid)["contents"]]
        have = [e["auto"] for e in contents if e.get("auto")]
        contents += [{"auto": a} for a in ("bibliography", "index") if a not in have]
        self.b.update(bid, {"contents": contents})
        data = book_export.to_docx(self.b, bid)
        texts = [p.text for p in self.open(data).paragraphs]
        self.assertEqual(texts.count("The Long Road"), 2)             # half-title and title page
        self.assertTrue(any(t.startswith("Alle rechten voorbehouden") for t in texts))
        self.assertEqual(texts.count("Noten"), 1)
        self.assertEqual(sum(t == "1. Een noot." for t in texts), 1)  # once, at the back
        self.assertGreater(texts.index("Noten"), texts.index("De haven"))
        self.assertIn("Inhoud", texts)
        z = zipfile.ZipFile(io.BytesIO(data))
        xml = z.read("word/document.xml").decode("utf-8")
        self.assertIn("TOC \\o", xml)
        self.assertIn('XE "trauma:jeugd"', xml)
        self.assertIn("INDEX", xml)
        for label in ("Noten", "Register"):                      # the back pages start on a page of their own
            self.assertTrue(next(p for p in self.open(data).paragraphs if p.text == label)
                            .paragraph_format.page_break_before)
        self.assertIn("w:updateFields", z.read("word/settings.xml").decode("utf-8"))

    def test_docx_footnotes_keep_the_list_after_each_piece(self):
        bid, files = self.make()
        self.b.update(bid, {"features": {"notes": "footnotes"}})
        texts = [p.text for p in self.open(book_export.to_docx(self.b, bid)).paragraphs]
        self.assertIn("1. First note, with style.", texts)
        self.assertIn("Notes", texts)

    def test_docx_bibliography(self):
        bid, files = self.make()
        contents = [{k: v for k, v in e.items() if k in ("auto", "file", "kind", "form")}
                    for e in self.b.read(bid)["contents"]] + [{"auto": "bibliography"}]
        self.b.update(bid, {"contents": contents, "features": {"sources": True}})
        texts = [p.text for p in self.open(book_export.to_docx(self.b, bid)).paragraphs]
        self.assertIn("Bibliography", texts)
        self.assertTrue(any("Marsh" in t and "Tides" in t for t in texts))

    def test_docx_leaves_out_what_the_pdf_leaves_out(self):
        """The generated pages the PDF leaves out (typeset_book.left_out) aren't in the .docx either: a feature that
        is off, notes that are footnotes, and a page with nothing to list."""
        bid, files = self.make()
        contents = [{k: v for k, v in e.items() if k in ("auto", "file", "kind", "form")}
                    for e in self.b.read(bid)["contents"]]
        have = [e["auto"] for e in contents if e.get("auto")]
        self.b.update(bid, {"contents": contents + [{"auto": a} for a in ("notes", "bibliography", "index")
                                                    if a not in have]})

        def back(features):
            self.b.update(bid, {"features": features})
            data = book_export.to_docx(self.b, bid)
            heads = [p.text for p in self.open(data).paragraphs if p.style.name == "Heading 1"]
            return heads, zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")

        heads, xml = back({"notes": "endnotes", "sources": True, "index": True})       # everything has something
        self.assertTrue({"Notes", "Bibliography", "Index"} <= set(heads), heads)
        self.assertIn("INDEX", xml)
        heads, xml = back({"notes": "endnotes", "sources": False, "index": False})     # features off
        self.assertIn("Notes", heads)
        self.assertFalse({"Bibliography", "Index"} & set(heads), heads)
        self.assertNotIn("INDEX", xml)
        heads, xml = back({"notes": "footnotes", "sources": True, "index": True})      # footnotes: no notes page
        self.assertNotIn("Notes", heads)
        self.assertTrue({"Bibliography", "Index"} <= set(heads), heads)
        (self.lib / "Books" / bid / "manuscript" / files[1]).write_text("# The Harbour\n\nNothing marked.\n",
                                                                         encoding="utf-8")
        heads, xml = back({"notes": "endnotes", "sources": True, "index": True})       # nothing to list
        self.assertFalse({"Notes", "Bibliography", "Index"} & set(heads), heads)
        self.assertNotIn("INDEX", xml)

    def test_markdown_has_yaml(self):
        from studio import book_import
        bid, files = self.make("nl")
        md = book_export.to_markdown(self.b, bid).decode("utf-8")
        self.assertTrue(md.startswith("---\ntitle: "))
        head = md.split("\n---\n")[0]
        self.assertIn("author: ", head)
        self.assertIn("A. Writer", head)
        self.assertIn('lang: "nl"', head)
        self.assertIn("date: ", head)
        self.assertIn("subtitle: ", head)
        got = book_import.propose("book.md", md.encode("utf-8"))
        self.assertEqual(len(got["pieces"]), 2)
        self.assertEqual(got["pieces"][-1]["title"], "The Harbour")

    def test_zip_contains_the_files(self):
        bid, files = self.make()
        z = zipfile.ZipFile(io.BytesIO(book_export.to_zip(self.b, bid)))
        names = z.namelist()
        for want in ("book.json", "sources.json", "images/pier.png", f"manuscript/{files[1]}"):
            self.assertIn(want, names)
        self.assertEqual(json.loads(z.read("book.json"))["title"], "The Long Road")
        self.assertIn(b"The Harbour", z.read(f"manuscript/{files[1]}"))

    def test_the_kept_copy_is_dated_and_never_overwritten(self):
        """A kept copy the author edited in Word stays as it is: every export is a new file, dated to the minute."""
        bid, _ = self.make()
        when = datetime(2026, 11, 12, 14, 5)
        name, data, _ = book_export.export(self.b, bid, "md", now=when)
        self.assertEqual(name, "The Long Road.md")                     # the download keeps the book's name
        folder = self.lib / "Books" / bid / "exports"
        first = folder / "The Long Road 2026-11-12 1405.md"
        self.assertEqual(first.read_bytes(), data)
        first.write_text("Edited in another program.", encoding="utf-8")
        book_export.export(self.b, bid, "md", now=when)
        book_export.export(self.b, bid, "md", now=when + timedelta(seconds=40))
        book_export.export(self.b, bid, "md", now=when + timedelta(minutes=1))
        self.assertEqual(first.read_text(encoding="utf-8"), "Edited in another program.")
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["The Long Road 2026-11-12 1405-2.md", "The Long Road 2026-11-12 1405-3.md",
                          "The Long Road 2026-11-12 1405.md", "The Long Road 2026-11-12 1406.md"])

    def test_an_unreadable_piece_stops_the_export_by_name(self):
        bid, files = self.make()
        (self.lib / "Books" / bid / "manuscript" / files[1]).write_bytes("# Café\n".encode("cp1252"))
        for fmt in ("docx", "md"):
            with self.assertRaises(BooksError) as e:
                book_export.export(self.b, bid, fmt)
            self.assertIn(files[1], str(e.exception))
            self.assertIn("isn't readable text", str(e.exception))
        self.assertFalse((self.lib / "Books" / bid / "exports").exists())

    def test_cite_text(self):
        one = [{"key": "tide", "prefix": "", "locator": "p. 12"}]
        self.assertEqual(book_export.cite_text(one, SOURCES), "(Marsh 1999, p. 12)")
        two = one + [{"key": "tide", "prefix": "see", "locator": ""}]
        self.assertEqual(book_export.cite_text(two, SOURCES), "(Marsh 1999, p. 12; see Marsh 1999)")
        self.assertEqual(book_export.cite_text([{"key": "nope", "prefix": "", "locator": ""}], SOURCES), "(nope)")
        other = [{"id": "e", "type": "book", "title": "T", "editor": [{"family": "Ed"}]},
                 {"id": "t", "type": "book", "title": "Only Title", "issued": {"date-parts": [[2001]]}}]
        self.assertEqual(book_export.cite_text([{"key": "e"}, {"key": "t"}], other), "(Ed; Only Title 2001)")

    def test_cite_text_name_particles(self):
        """CSL keeps "van", "de" apart from the family name; a citation reads them together, as Dutch names are said."""
        sources = [{"id": "dijk", "type": "book", "author": [{"family": "Dijk", "non-dropping-particle": "van", "given": "A."}],
                    "issued": {"date-parts": [[2010]]}},
                   {"id": "wit", "type": "book", "author": [{"family": "Wit", "dropping-particle": "de", "given": "K."}],
                    "issued": {"date-parts": [[2015]]}},
                   {"id": "berg", "type": "book", "editor": [{"family": "Berg", "non-dropping-particle": "van den"}]}]
        self.assertEqual(book_export.cite_text([{"key": "dijk", "prefix": "", "locator": "p. 3"}], sources), "(van Dijk 2010, p. 3)")
        self.assertEqual(book_export.cite_text([{"key": "wit", "prefix": "zie", "locator": ""}], sources), "(zie de Wit 2015)")
        self.assertEqual(book_export.cite_text([{"key": "berg"}], sources), "(van den Berg)")


if __name__ == "__main__":
    unittest.main()
