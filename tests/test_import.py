"""Importing a book from .docx and Markdown: the rules, on invented fixtures."""
import base64
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import docx

from studio import book_export, book_import, examples, manuscript
from studio.books import Books, BooksError

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def italic(doc, text):
    doc.add_paragraph().add_run(text).italic = True


def build(extra=None):
    """The fixture: a capitalised title, an author line, empty headings, a dedication, a foreword with an epigraph."""
    d = docx.Document()
    d.add_paragraph("TEST BOOK", style="Title")
    d.add_paragraph("A. Poet", style="Subtitle")
    for _ in range(4):
        d.add_paragraph("", style="Heading 1")
    italic(d, "For everyone who stayed.")
    d.add_paragraph("Voorwoord", style="Heading 1")
    italic(d, "“Be kind.”")
    d.add_paragraph("\t\t- Someone, Somewhere")
    p = d.add_paragraph("A body with one ")
    p.add_run("italic").italic = True
    p.add_run(" word.")
    d.add_paragraph("Chapter One", style="Heading 1")
    d.add_paragraph("It began on a Monday.")
    d.add_paragraph("A section", style="Heading 2")
    d.add_paragraph("More of it.")
    d.add_paragraph("Nawoord", style="Heading 1")
    d.add_paragraph("It ended.")
    if extra:
        extra(d)
    return save(d)


def save(d):
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def with_footnote(data, anchor, footnote_xml):
    """Add one real footnote (id 1) to the paragraph that contains `anchor`."""
    fn = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:footnotes {W}>'
          '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
          f'<w:footnote w:id="1"><w:p><w:r><w:footnoteRef/></w:r>{footnote_xml}</w:p></w:footnote></w:footnotes>')
    zin, out = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name in zin.namelist():
            blob = zin.read(name)
            if name == "[Content_Types].xml":
                blob = blob.replace(b"</Types>", b'<Override PartName="/word/footnotes.xml" ContentType="application/'
                                    b'vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>')
            elif name == "word/_rels/document.xml.rels":
                blob = blob.replace(b"</Relationships>", b'<Relationship Id="rIdFn" Type="http://schemas.openxmlformats.'
                                    b'org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/></Relationships>')
            elif name == "word/document.xml":
                end = anchor.encode() + b"</w:t></w:r>"
                assert end in blob, "anchor not found"
                blob = blob.replace(end, end + b'<w:r><w:footnoteReference w:id="1"/></w:r>', 1)
            z.writestr(name, blob)
        z.writestr("word/footnotes.xml", fn)
    return out.getvalue()


NOTE_XML = ('<w:r><w:t xml:space="preserve"> A note with </w:t></w:r>'
            '<w:r><w:rPr><w:i/></w:rPr><w:t>italics</w:t></w:r>')

MARKDOWN = """# TEST BOOK

## A. Poet

*For everyone who stayed.*

# Voorwoord

*“Be kind.”*

— Someone, Somewhere

A body with one *italic* word.

# Chapter One

It began on a Monday.

## A section

More of it.

# Nawoord

It ended.
"""


def kinds(proposal):
    return [p["kind"] for p in proposal["pieces"]]


class ImportTest(unittest.TestCase):
    def check_structure(self, got):
        self.assertEqual(got["title"], "Test Book")
        self.assertEqual(got["author"], "A. Poet")
        self.assertEqual(got["subtitle"], "")
        self.assertEqual(kinds(got), ["dedication", "foreword", "chapter", "afterword"])
        ded, fore, chap, after = got["pieces"]
        self.assertEqual(ded["md"], "*For everyone who stayed.*\n")
        self.assertEqual(ded["title"], "")
        self.assertEqual(fore["title"], "Voorwoord")
        self.assertEqual(fore["md"], "# Voorwoord\n\n::: epigraph\n*“Be kind.”*\n\n— Someone, Somewhere\n:::\n\n"
                                     "A body with one *italic* word.\n")
        self.assertEqual(chap["md"], "# Chapter One\n\nIt began on a Monday.\n\n## A section\n\nMore of it.\n")
        self.assertEqual(after["md"], "# Nawoord\n\nIt ended.\n")
        for p in got["pieces"]:
            self.assertEqual(manuscript.serialize(manuscript.parse(p["md"], p["form"]), p["form"]), p["md"])
            self.assertEqual(p["words"], manuscript.counts(p["md"], p["form"])["words"])
        self.assertEqual(fore["first"], "A body with one italic word.")

    def test_docx_import(self):
        got = book_import.propose("memoir.docx", build(), "a. poet")
        self.check_structure(got)
        self.assertEqual(got["images"], {})

    def test_markdown_import(self):
        for name in ("memoir.md", "memoir.markdown", "memoir.txt"):
            self.check_structure(book_import.propose(name, MARKDOWN.encode("utf-8"), "A. POET"))

    def test_subtitle_is_kept_when_it_is_not_the_signature(self):
        got = book_import.propose("m.docx", build(), "Someone Else")
        self.assertEqual((got["author"], got["subtitle"]), ("", "A. Poet"))

    def test_title_from_the_first_heading_and_name_fallbacks(self):
        got = book_import.propose("x.md", b"# Harbour Lights\n\nText.\n")
        self.assertEqual((got["title"], kinds(got), got["pieces"][0]["md"]), ("Harbour Lights", ["chapter"], "Text.\n"))
        got = book_import.propose("my_notes.md", b"Just a paragraph.\n\n# Voorwoord\n\nHello.\n")
        self.assertEqual(got["title"], "my notes")                 # the file's name as it is (only capitals change)
        self.assertEqual(kinds(got), ["chapter", "foreword"])      # the loose text is kept, not dropped
        got = book_import.propose("x.md", b"# Voorwoord\n\nHello.\n")      # a kind heading is a piece, not the title
        self.assertEqual((got["title"], kinds(got)), ("x", ["foreword"]))

    def test_empty_headings_and_all_caps_apostrophes(self):
        got = book_import.propose("x.md", "# DON’T PANIC\n\n#\n\n# One\n\nText.\n".encode())
        self.assertEqual(got["title"], "Don’t Panic")
        self.assertEqual([p["title"] for p in got["pieces"]], ["One"])

    def test_epigraph_needs_an_attribution_and_at_most_four_lines(self):
        base = "# B\n\n# One\n\n{}\n\nText.\n"
        five = "\n\n".join(f"*Line {i}.*" for i in range(5))
        loose = book_import.propose("b.md", base.format("*Not an epigraph.*").encode())["pieces"][0]["md"]
        self.assertNotIn("::: epigraph", loose)
        self.assertIn("*Not an epigraph.*", loose)
        none = book_import.propose("b.md", base.format(five + "\n\n— Someone").encode())["pieces"][0]["md"]
        self.assertNotIn("::: epigraph", none)
        four = "\n\n".join(f"*Line {i}.*" for i in range(4))
        four = book_import.propose("b.md", base.format(four + "\n\n– Someone").encode())["pieces"][0]["md"]
        self.assertIn("::: epigraph", four)
        self.assertIn("— Someone\n:::", four)

    def test_epigraph_from_a_quote_style_and_a_quote_mark(self):
        d = docx.Document()
        d.add_paragraph("One", style="Heading 1")
        d.add_paragraph("Be quiet and listen.", style="Quote")
        d.add_paragraph("— Someone")
        d.add_paragraph("“Words in marks.”")
        d.add_paragraph("   -   Another")
        d.add_paragraph("Body.")
        md = book_import.propose("a.docx", save(d))["pieces"][0]["md"]
        self.assertEqual(md.count("::: epigraph"), 1)       # the first pair only; the second pair is not at the start
        self.assertIn("“Words in marks.”", md)

    def test_longer_italic_paragraph_is_not_a_dedication(self):
        long = " ".join(["word"] * 41)
        got = book_import.propose("b.md", f"# B\n\n*{long}*\n\n# One\n\nText.\n".encode())
        self.assertEqual(kinds(got), ["chapter", "chapter"])
        self.assertEqual(got["pieces"][0]["title"], "")

    def test_footnotes_from_mammoth_html(self):
        html = ('<p>Before<sup><a href="#footnote-1" id="footnote-ref-1">[1]</a></sup> after.</p>'
                '<p>End<sup><a href="#endnote-2" id="endnote-ref-2">[2]</a></sup></p>'
                '<ol><li id="footnote-1"><p> A <em>note</em> here <a href="#footnote-ref-1">↑</a></p></li>'
                '<li id="endnote-2"><p>First.</p><p>Second <strong>part</strong> <a href="#endnote-ref-2">↑</a></p></li></ol>')
        blocks = book_import.html_to_blocks(html)
        self.assertEqual([b["md"] for b in blocks], ["Before^[A *note* here] after.", "End^[First. Second **part**]"])
        self.assertEqual([b["type"] for b in blocks], ["p", "p"])

    def test_block_kinds_and_flags(self):
        html = ('<h1 class="doc-title">T</h1><p class="doc-subtitle">S</p><h1></h1><p></p><h2>Two</h2><h4>Four</h4>'
                '<p><em>All italic</em></p><p>Some <em>italic</em></p><blockquote><p>Q</p></blockquote>'
                '<ul><li>one</li><li>two</li></ul><ol><li>first</li></ol>')
        blocks = book_import.html_to_blocks(html)
        self.assertEqual([b["type"] for b in blocks],
                         ["title", "subtitle", "h2", "h3", "p", "p", "quote", "p", "p", "p"])
        self.assertEqual([b["italic_only"] for b in blocks][4:6], [True, False])
        self.assertFalse(any(b["empty"] for b in blocks))
        self.assertEqual([b["md"] for b in blocks][7:], ["• one", "• two", "1\\. first"])

    def test_footnote_in_a_real_docx(self):
        data = with_footnote(build(), "It began on a Monday.", NOTE_XML)
        md = book_import.propose("m.docx", data, "A. Poet")["pieces"][2]["md"]
        self.assertIn("It began on a Monday.^[A note with *italics*]", md)
        self.assertEqual(manuscript.counts(md)["notes"], 1)

    def test_footnote_in_a_dedication_and_an_epigraph(self):
        data = with_footnote(build(), "For everyone who stayed.", NOTE_XML)
        got = book_import.propose("m.docx", data, "A. Poet")
        self.assertEqual(got["pieces"][0]["kind"], "dedication")      # an italic paragraph with a note is still one
        self.assertEqual(got["pieces"][0]["md"], "*For everyone who stayed.*^[A note with *italics*]\n")
        data = with_footnote(build(), "Be kind.”", NOTE_XML)
        fore = book_import.propose("m.docx", data, "A. Poet")["pieces"][1]["md"]
        self.assertIn("::: epigraph\n*“Be kind.”*^[A note with *italics*]\n\n— Someone, Somewhere\n:::", fore)

    def test_docx_image_is_kept(self):
        def add(d):
            d.add_paragraph("Look:")
            d.add_picture(io.BytesIO(PNG))
        got = book_import.propose("m.docx", build(add), "A. Poet")
        self.assertEqual(list(got["images"]), ["image-1.png"])
        self.assertEqual(base64.b64decode(got["images"]["image-1.png"]), PNG)
        self.assertIn("![](../images/image-1.png)", got["pieces"][-1]["md"])

    def test_same_picture_twice_is_one_image(self):
        def add(d):
            d.add_picture(io.BytesIO(PNG))
            d.add_picture(io.BytesIO(PNG))
        got = book_import.propose("m.docx", build(add), "A. Poet")
        self.assertEqual(len(got["images"]), 1)
        self.assertEqual(got["pieces"][-1]["md"].count("![](../images/image-1.png)"), 2)

    def test_commit_creates_the_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            books = Books(Path(tmp) / "Books")

            def add(d):
                d.add_picture(io.BytesIO(PNG))
            got = book_import.propose("m.docx", build(add), "A. Poet")
            got.update(kind="memoir", language="nl", subtitle="A story")
            book = book_import.commit(books, got)
            self.assertEqual((book["title"], book["author"], book["language"], book["subtitle"]),
                             ("Test Book", "A. Poet", "nl", "A story"))
            order = [e.get("auto") or e["kind"] for e in book["contents"]]
            self.assertEqual(order, ["half-title", "title-page", "copyright", "dedication", "toc", "foreword", "chapter",
                                     "afterword", "notes"])
            files = [e["file"] for e in book["contents"] if e.get("file")]
            self.assertEqual(files, ["dedication.md", "voorwoord.md", "chapter-one.md", "nawoord.md"])
            piece = books.piece(book["id"], "nawoord.md")
            self.assertIn("![](../images/image-1.png)", piece["md"])
            self.assertEqual(books.piece(book["id"], "chapter-one.md")["title"], "Chapter One")
            self.assertEqual((books.dir(book["id"]) / "images" / "image-1.png").read_bytes(), PNG)

    def test_commit_follows_the_names_images_are_saved_under(self):
        with tempfile.TemporaryDirectory() as tmp:
            books = Books(Path(tmp) / "Books")
            final = {"title": "Pics", "kind": "fiction", "pieces": [
                {"kind": "chapter", "form": "prose", "title": "One", "md": "# One\n\n![a](<../images/Shot 1.png>)\n"}],
                "images": {"Shot 1.png": base64.b64encode(PNG).decode()}}
            book = book_import.commit(books, final)
            md = books.piece(book["id"], "one.md")["md"]
            self.assertIn("../images/Shot-1.png", md)
            self.assertTrue((books.dir(book["id"]) / "images" / "Shot-1.png").exists())

    def test_a_failed_commit_leaves_no_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            books = Books(Path(tmp) / "Books")
            final = {"title": "Pics", "pieces": [{"kind": "chapter", "md": "# One\n"}],
                     "images": {"vector.svg": base64.b64encode(b"<svg/>").decode()}}
            with self.assertRaises(BooksError):
                book_import.commit(books, final)
            self.assertEqual(books.list(), [])
            self.assertEqual([p for p in (Path(tmp) / "Books").glob("*")], [])
            with self.assertRaises(BooksError):
                book_import.commit(books, {"title": "X", "pieces": [{"kind": "nonsense", "md": ""}]})
            self.assertEqual(books.list(), [])

    def test_nothing_is_written_by_propose(self):
        with tempfile.TemporaryDirectory() as tmp:
            book_import.propose("m.docx", build(), "A. Poet")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_other_files_are_refused(self):
        for name in ("book.pdf", "book.doc", "book", "book.rtf"):
            with self.assertRaisesRegex(BooksError, r"\.docx, \.md"):
                book_import.propose(name, b"x")

    def test_a_corrupt_docx_is_a_plain_sentence(self):
        for data in (b"this is not a zip", b"PK\x03\x04garbage", zipfile.ZipFile(io.BytesIO(), "w") and b"PK"):
            with self.assertRaises(BooksError) as cm:
                book_import.propose("broken.docx", data)
            self.assertEqual(cm.exception.code, 400)
            self.assertIn("couldn't be read", str(cm.exception))
            self.assertNotIn("Traceback", str(cm.exception))
        empty = io.BytesIO()
        with zipfile.ZipFile(empty, "w") as z:
            z.writestr("hello.txt", "hi")
        with self.assertRaises(BooksError):
            book_import.propose("empty.docx", empty.getvalue())

    def test_large_docx(self):
        def add(d):
            for _ in range(3):
                p = d.add_paragraph()
                p.add_run("x" * 2000)
        data = build(add)
        # a 30 MB file of noise inside a docx still imports
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
            for n in zin.namelist():
                z.writestr(n, zin.read(n))
            z.writestr("word/media/ballast.bin", bytes(30_000_000))
        self.assertGreater(len(out.getvalue()), 30_000_000)
        self.assertEqual(len(book_import.propose("big.docx", out.getvalue(), "A. Poet")["pieces"]), 4)

    def test_tampered_commit_bodies_are_refused(self):
        piece = {"kind": "chapter", "form": "prose", "title": "One", "md": "# One\n"}
        good = {"title": "T", "kind": "memoir", "language": "en", "pieces": [piece]}
        bad = [
            {"kind": ["a"]}, {"kind": "nonsense"}, {"language": 5}, {"language": "not a code!"}, {"title": ""},
            {"title": 7}, {"title": ["x"]}, {"author": 3}, {"subtitle": ["s"]}, {"images": []}, {"images": {"a.png": 5}},
            {"images": {"a.png": "!!!"}}, {"pieces": "x"}, {"pieces": [5]},
            {"pieces": [{**piece, "kind": ["chapter"]}]}, {"pieces": [{**piece, "form": ["prose"]}]},
            {"pieces": [{**piece, "form": "sonnet"}]}, {"pieces": [{**piece, "title": 4}]}, {"pieces": [{**piece, "md": 4}]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            books = Books(Path(tmp) / "Books")
            for change in bad:
                with self.assertRaises(BooksError, msg=str(change)) as cm:
                    book_import.commit(books, {**good, **change})
                self.assertEqual(cm.exception.code, 400)
            self.assertEqual(books.list(), [])
            book_import.commit(books, good)

    def test_dutch_dialogue_is_not_an_epigraph(self):
        d = docx.Document()
        d.add_paragraph("Book", style="Title")
        d.add_paragraph("One", style="Heading 1")
        d.add_paragraph("\u201eHallo,\u201d zei hij.")
        d.add_paragraph("- Ja, zei zij.")
        d.add_paragraph("Verder.")
        md = book_import.propose("a.docx", save(d))["pieces"][0]["md"]
        self.assertEqual(md, "# One\n\n\u201eHallo,\u201d zei hij.\n\n\\- Ja, zei zij.\n\nVerder.\n")

    def test_long_dash_lines_are_never_attributions(self):
        long = "- " + " ".join(["word"] * 13)
        d = docx.Document()
        d.add_paragraph("Book", style="Title")
        d.add_paragraph("One", style="Heading 1")
        italic(d, "A quote.")
        d.add_paragraph(long)
        self.assertNotIn("::: epigraph", book_import.propose("a.docx", save(d))["pieces"][0]["md"])

    def test_italic_quote_with_plain_dash_name_is_an_epigraph(self):
        d = docx.Document()
        d.add_paragraph("Book", style="Title")
        d.add_paragraph("One", style="Heading 1")
        italic(d, "A quote.")
        d.add_paragraph("- Name")
        md = book_import.propose("a.docx", save(d))["pieces"][0]["md"]
        self.assertIn("::: epigraph\n*A quote.*\n\n\u2014 Name\n:::", md)

    def test_note_in_a_heading_is_kept(self):
        html = ('<h1>Head<sup><a href="#footnote-1" id="footnote-ref-1">[1]</a></sup></h1><p>Body.</p>'
                '<h2>Sub<sup><a href="#footnote-2" id="footnote-ref-2">[2]</a></sup></h2><p>More.</p>'
                '<ol><li id="footnote-1"><p>First <em>note</em>. <a href="#footnote-ref-1">\u2191</a></p></li>'
                '<li id="footnote-2"><p>Second.</p></li></ol>')
        blocks = book_import.html_to_blocks("<h1 class=\"doc-title\">T</h1>" + html)
        got = book_import._assemble(blocks, "", "X")
        self.assertEqual(got["pieces"][0]["md"], "# Head^[First *note*.]\n\nBody.\n\n## Sub^[Second.]\n\nMore.\n")
        self.assertEqual(manuscript.counts(got["pieces"][0]["md"])["notes"], 2)
    def test_title_cased_is_reported(self):
        self.assertTrue(book_import.propose("a.md", b"# TEST BOOK\n\nText.\n")["title_cased"])
        self.assertFalse(book_import.propose("a.md", b"# Test Book\n\nText.\n")["title_cased"])
        self.assertFalse(book_import.propose("a.md", b"Text only.\n")["title_cased"])

    def test_commit_applies_an_edited_piece_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            books = Books(Path(tmp) / "Books")
            pieces = [{"kind": "chapter", "title": "New *name*", "retitled": True, "md": "# Old\n\nBody^[a note].\n"},
                      {"kind": "chapter", "title": "Kept", "md": "# Old *two*\n\nBody.\n"},
                      {"kind": "chapter", "title": "Added", "retitled": True, "md": "Loose text.\n"},
                      {"kind": "chapter", "title": "", "retitled": True, "md": "# Gone\n\nText.\n"}]
            book = book_import.commit(books, {"title": "B", "kind": "fiction", "pieces": pieces})
            files = [e["file"] for e in book["contents"] if e.get("file")]
            texts = [books.piece(book["id"], f)["md"] for f in files]
            self.assertEqual(texts, ["# New \\*name\\*\n\nBody^[a note].\n", "# Old *two*\n\nBody.\n",
                                     "# Added\n\nLoose text.\n", "Text.\n"])
            self.assertNotIn("gone.md", files)      # a cleared title is not the file name
            self.assertEqual(book["contents"][-1]["title"], "")

    # ——— the final review ———
    def test_studios_own_markdown_export_imports_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            books = Books(Path(tmp) / "Books")
            [d] = examples.add_book(books)
            data = book_export.to_markdown(books, d.name)
            self.assertIn(b"<!-- kind: chapter; form: poem -->", data)
            got = book_import.propose(f"{d.name}.md", data)
            entries = [e for e in books.read(d.name)["contents"] if e.get("file")]
            self.assertEqual(got["title"], d.name)
            self.assertEqual([(p["kind"], p["form"]) for p in got["pieces"]],
                             [(e["kind"], e.get("form") or "prose") for e in entries])
            for p, e in zip(got["pieces"], entries):
                self.assertEqual(p["md"], books.piece(d.name, e["file"])["md"], e["file"])
                self.assertNotIn("<!--", p["md"])
            made = book_import.commit(books, {**got, "title": "Back again", "kind": "memoir", "language": "en"})
            back = [e for e in made["contents"] if e.get("file")]
            self.assertEqual([(e["kind"], e["form"]) for e in back], [(e["kind"], e.get("form") or "prose") for e in entries])
            for e, orig in zip(back, entries):
                self.assertEqual(books.piece(made["id"], e["file"])["md"], books.piece(d.name, orig["file"])["md"])

    def test_a_marker_starts_a_piece_of_its_kind_and_form(self):
        md = ("Loose words before.\n\n<!-- kind: dedication; form: prose -->\n\nFor you.\n\n"
              "<!-- kind: chapter; form: poem -->\n\n# Twee regels\n\nDe eerste regel\n  de tweede, ingesprongen\n\tde derde\n\n"
              "<!-- kind: nonsense -->\n\n# Odd\n\nText.\n")
        got = book_import.propose("bundel.md", md.encode())
        self.assertEqual([(p["kind"], p["form"], p["title"]) for p in got["pieces"]],
                         [("chapter", "prose", ""), ("dedication", "prose", ""), ("chapter", "poem", "Twee regels"),
                          ("chapter", "prose", "Odd")])
        self.assertEqual(got["pieces"][2]["md"], "# Twee regels\n\nDe eerste regel\n\xa0\xa0de tweede, ingesprongen\n"
                                                 "\xa0\xa0de derde\n")
        self.assertEqual(got["pieces"][1]["md"], "For you.\n")
        self.assertNotIn("kind:", "".join(p["md"] for p in got["pieces"]))

    def test_a_plain_text_poem_keeps_its_lines_when_it_becomes_a_poem(self):
        text = "Eerste regel\ntweede regel\n    ingesprongen regel\n\nNieuwe strofe\n\tlaatste regel\n"
        got = book_import.propose("Gedichten.txt", text.encode())
        [p] = got["pieces"]
        self.assertEqual((p["form"], p["md"]), ("prose", "Eerste regel tweede regel ingesprongen regel\n\nNieuwe strofe laatste regel\n"))
        with tempfile.TemporaryDirectory() as tmp:
            books = Books(Path(tmp) / "Books")
            for form, want in (("poem", "Eerste regel\ntweede regel\n\xa0\xa0\xa0\xa0ingesprongen regel\n\nNieuwe strofe\n"
                                        "\xa0\xa0laatste regel\n"), ("prose", p["md"])):
                made = book_import.commit(books, {**got, "title": f"Als {form}", "kind": "poetry", "language": "nl",
                                                  "pieces": [{**p, "form": form}]})
                [e] = [e for e in made["contents"] if e.get("file")]
                self.assertEqual((e["form"], books.piece(made["id"], e["file"])["md"]), (form, want))

    def test_merged_sources_are_read_in_the_form_chosen(self):
        """The review screen merges two pieces' sources as it merges their Markdown (the second title a ## heading)."""
        got = book_import.propose("b.md", "# Boek\n\n# Een\n\nregel een\nregel twee\n\n# Twee\n\nregel drie\n  regel vier\n".encode())
        a, b = got["pieces"]
        self.assertEqual((a["source"], b["source"]), ("# Een\n\nregel een\nregel twee\n", "# Twee\n\nregel drie\n  regel vier\n"))
        merged = {**a, "form": "poem", "md": "# Een\n\nregel een regel twee\n\n## Twee\n\nregel drie regel vier\n",
                  "source": a["source"].rstrip() + "\n\n#" + b["source"]}
        with tempfile.TemporaryDirectory() as tmp:
            books = Books(Path(tmp) / "Books")
            made = book_import.commit(books, {**got, "kind": "poetry", "pieces": [merged]})
            [e] = [e for e in made["contents"] if e.get("file")]
            self.assertEqual(books.piece(made["id"], e["file"])["md"],
                             "# Een\n\nregel een\nregel twee\n\n## Twee\n\nregel drie\n\xa0\xa0regel vier\n")

    def test_poem_blocks_keep_their_indentation_and_prose_does_not_change(self):
        md = "# Boek\n\n# Hoofdstuk\n\nZe las voor:\n\n::: poem\nDe eerste regel\n  de tweede\n:::\n\n  Gewone tekst.\n"
        got = book_import.propose("b.md", md.encode())
        self.assertEqual(got["pieces"][0]["md"], "# Hoofdstuk\n\nZe las voor:\n\n::: poem\nDe eerste regel\n\xa0\xa0de tweede\n"
                                                 ":::\n\nGewone tekst.\n")

    def test_docx_stanza_lines_keep_their_indentation(self):
        d = docx.Document()
        d.add_paragraph("Bundel", style="Title")
        d.add_paragraph("Gedicht", style="Heading 1")
        p = d.add_paragraph("De eerste regel")
        p.add_run().add_break()
        p.add_run("    de tweede, ingesprongen")
        p.add_run().add_break()
        p.add_run("\tde derde")
        d.add_paragraph("    Een gewone alinea.")
        md = book_import.propose("b.docx", save(d))["pieces"][0]["md"]
        self.assertEqual(md, "# Gedicht\n\nDe eerste regel\\\n\xa0\xa0\xa0\xa0de tweede, ingesprongen\\\n\xa0\xa0de derde\n\n"
                             "Een gewone alinea.\n")
        with tempfile.TemporaryDirectory() as tmp:
            books = Books(Path(tmp) / "Books")
            got = book_import.propose("b.docx", save(d))
            made = book_import.commit(books, {**got, "pieces": [{**got["pieces"][0], "form": "poem"}]})
            [e] = [e for e in made["contents"] if e.get("file")]
            self.assertIn("De eerste regel\n\xa0\xa0\xa0\xa0de tweede, ingesprongen\n\xa0\xa0de derde\n",
                          books.piece(made["id"], e["file"])["md"])

    def test_a_title_from_the_file_name_is_not_title_cased(self):
        d = docx.Document()
        d.add_paragraph("Gewoon een alinea.")
        got = book_import.propose("De reis van mijn moeder.docx", save(d))
        self.assertEqual((got["title"], got["title_cased"]), ("De reis van mijn moeder", False))
        got = book_import.propose("OUDE BRIEVEN.md", b"Tekst.\n")             # all capitals: rule 1
        self.assertEqual((got["title"], got["title_cased"]), ("Oude Brieven", True))


if __name__ == "__main__":
    unittest.main()
