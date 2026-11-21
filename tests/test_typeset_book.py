"""Typesetting a whole book: page rules, folios, running heads and the generated pages.

Books are built with `Books` in a temp library, set with `typeset_book.book` and compiled with Literata as
typeset_fonts cuts it (once for the whole module: cutting takes seconds) and Typst's own fonts only, from a main file
in a folder of its own. The page facts are read back from the compiled document: the footer's `<page-info>`, the
`<piece-start>` markers, the contents' `<toc-entry>` and the index's `<index-entry>` metadata."""
import itertools
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import typst

from studio import book_design, books, config, typeset, typeset_book, typeset_fonts

_ENV = ("STUDIO_ART", "STUDIO_CACHE", "STUDIO_CONFIG")
TMP = FONTS = None
_SAVED = {}
_COUNT = itertools.count()

DIJK = {"id": "d", "type": "book", "title": "Zee", "publisher": "Uitgeverij Golf",
        "author": [{"family": "Dijk", "given": "Anna", "non-dropping-particle": "van"}],
        "issued": {"date-parts": [[2019]]}}
BAKKER = {"id": "b", "type": "book", "title": "Land", "author": [{"family": "Bakker", "given": "Jos"}],
          "issued": {"date-parts": [[2020]]}}

_EN = ("the grey sea came in over the low dunes where we walked each morning and the wind kept the gulls high above "
       "the water while my mother counted the boats that went out past the harbour wall before the light was full").split()
_NL = ("de grijze zee kwam over de lage duinen waar wij elke ochtend liepen en de wind hield de meeuwen hoog boven het "
       "water terwijl mijn moeder de boten telde die langs de havenmuur uitvoeren voordat het licht er was en de "
       "arbeidsongeschiktheidsverzekering en de kinderboekenweekgeschenkenactie lagen nog op tafel").split()


def words(n, vocabulary=_EN, start=0):
    """`n` invented words in sentences of twelve."""
    out = []
    for k in range(n):
        w = vocabulary[(start + k) % len(vocabulary)]
        if k % 12 == 0:
            w = w.capitalize()
        out.append(w + ("." if k % 12 == 11 or k == n - 1 else ""))
    return " ".join(out)


def prose(n, per=90, vocabulary=_EN, mark=""):
    """About `n` words in paragraphs of `per` words; `mark` (Markdown) is added to the end of every paragraph."""
    paras, k = [], 0
    while k < n:
        paras.append(words(min(per, n - k), vocabulary, k) + mark)
        k += per
    return "\n\n".join(paras)


def setUpModule():
    global TMP, FONTS
    TMP = Path(tempfile.mkdtemp(prefix="studio-book-"))
    _SAVED.update({k: os.environ.get(k) for k in _ENV})
    _SAVED["cfg"] = config.CONFIG_FILE
    os.environ["STUDIO_ART"] = str(TMP / "lib")
    os.environ["STUDIO_CACHE"] = str(TMP / "cache")
    os.environ["STUDIO_CONFIG"] = str(TMP / "config.json")
    config.CONFIG_FILE = TMP / "config.json"
    config.refresh()
    (TMP / "empty").mkdir()
    FONTS = typeset_fonts.prepare({"text": {"family": "Literata", "weight": 400, "opsz": 10.5}}, config.CACHE)


def tearDownModule():
    for k in _ENV:
        if _SAVED.get(k) is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = _SAVED[k]
    config.CONFIG_FILE = _SAVED["cfg"]
    config.refresh()
    shutil.rmtree(TMP, ignore_errors=True)


def set_book(kind, entries, language="en", title="The Grey Sea", author="Anna Example", features=None, details=None,
             sources=None, **design):
    """A book of `entries` (an auto page's name, or (kind, markdown[, form]) for a piece) set and compiled to PDF.
    Returns the compiler (made from the main file, so it serves any number of queries), the source, the PDF and the
    Context. A compile error or warning fails the test."""
    n = next(_COUNT)
    lib = books.Books(TMP / f"lib{n}" / "Books")
    book = lib.create(title, author, language, kind, start=False)["id"]
    contents = []
    for e in entries:
        if isinstance(e, str):
            contents.append({"auto": e})
            continue
        piece_kind, md, form = (tuple(e) + ("prose",))[:3]
        p = lib.new_piece(book, piece_kind, form)
        lib.save_piece(book, p["file"], md=md)
        contents.append({"file": p["file"], "kind": piece_kind, "form": form})
    fields = {"contents": contents}
    if features:
        fields["features"] = features
    if details:
        fields["details"] = details
    if design:
        fields["design"] = design
    lib.update(book, fields)
    if sources:
        lib.save_sources(book, sources)
    meta = lib.read(book)
    pieces = [(i, e, lib.piece(book, e["file"])["doc"] if e.get("file") else None)
              for i, e in enumerate(meta["contents"])]
    resolved = book_design.resolve(meta, meta["style"])
    ctx = typeset.Context(design=resolved, lang=meta["language"], sources=lib.sources(book),
                          notes=meta["features"]["notes"], numbering=meta["features"]["noteNumbering"],
                          linked=lib.linked_poem)
    source = typeset_book.book(meta, pieces, resolved, FONTS["names"], ctx)
    folder = TMP / f"set{n}"
    folder.mkdir()
    main = folder / "main.typ"
    main.write_text(source, encoding="utf-8")
    compiler = typst.Compiler(str(main), root=str(folder), ignore_system_fonts=True,
                              font_paths=typst.Fonts(include_system_fonts=False, include_embedded_fonts=True,
                                                     font_paths=[str(FONTS["folder"])]),
                              package_path=str(TMP / "empty"), package_cache_path=str(TMP / "empty"))
    try:
        pdf, warnings = compiler.compile_with_warnings(format="pdf")
    except typst.TypstError as e:
        raise AssertionError(f"{e.message} {e.hints} {e.trace}") from None
    if warnings:
        raise AssertionError("Typst warnings: " + "; ".join(w.message for w in warnings))
    return SimpleNamespace(compiler=compiler, source=source, pdf=pdf, ctx=ctx, meta=meta, design=resolved,
                           kinds={i: e.get("kind") or e.get("auto") for i, e in enumerate(meta["contents"])})


def ev(r, expr):
    return json.loads(r.compiler.eval(expr, format="json"))


def page_infos(r):
    return ev(r, "query(<page-info>).map(m => m.value)")


def starts(r):
    """(contents index, physical page) of every piece and generated page, in order."""
    return [tuple(x) for x in ev(r, "query(<piece-start>).map(m => (m.value, m.location().page()))")]


def page_count(pdf):
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


FRONT = ["half-title", "title-page", "copyright"]


class BookPagesTest(unittest.TestCase):
    def test_chapters_start_on_right_hand_pages(self):
        r = set_book("memoir", FRONT + [("dedication", "For M., who counted the boats."), "toc",
                                        ("foreword", "# Foreword\n\n" + prose(1000)),
                                        ("chapter", "# The Harbour\n\n" + prose(150)),
                                        ("chapter", "# The Dunes\n\n" + prose(700)),
                                        ("chapter", "# The Light\n\n" + prose(60) + "^[A note.]"), "notes"])
        found = starts(r)
        self.assertEqual([i for i, _ in found], list(range(len(r.kinds))))
        for i, page in found:
            if r.kinds[i] in ("half-title", "title-page", "dedication", "toc", "chapter", "notes"):
                self.assertEqual(page % 2, 1, f"{r.kinds[i]} (entry {i}) starts on page {page}")
        pages = dict(found)
        foreword = next(i for i, k in r.kinds.items() if k == "foreword")
        self.assertGreaterEqual(pages[foreword + 1] - pages[foreword], 3)      # the foreword really is three pages
        self.assertEqual((pages[0], pages[1], pages[2]), (1, 3, 4))      # half-title, title page, copyright (verso)
        evens = [pages[i + 1] - pages[i] for i in range(len(found) - 1) if r.kinds[i] == "chapter"]
        self.assertIn(True, [d % 2 == 0 for d in evens])        # a chapter ended on a recto: a blank page followed

    def test_folios_roman_then_arabic(self):
        r = set_book("memoir", FRONT + [("dedication", "For M."), "toc", ("chapter", "# One\n\n" + prose(500)),
                                        ("chapter", "# Two\n\n" + prose(200))])
        toc = next(i for i, k in r.kinds.items() if k == "toc")
        first = next(i for i, k in r.kinds.items() if k == "chapter")
        at = "query(<piece-start>).find(m => m.value == %d).location()"
        self.assertEqual(ev(r, f"{at % toc}.page-numbering()"), "i")
        self.assertEqual(ev(r, f"({at % first}.page-numbering(), counter(page).at({at % first}).first())"), ["1", 1])
        infos = {p["page"]: p for p in page_infos(r)}
        pages = dict(starts(r))
        self.assertEqual(infos[pages[toc]]["folio"], "vii")
        self.assertTrue(infos[pages[toc]]["shown"])
        self.assertEqual(infos[pages[first]]["folio"], "1")
        self.assertTrue(infos[pages[first]]["shown"])
        self.assertEqual(infos[pages[first] + 1]["folio"], "2")

    def test_arabic_starts_with_the_body(self):
        """Arabic page 1 is the body's first piece as the list of pieces groups the book (book.js, bookGroups): a
        prologue or an introduction before chapter 1 counts from 1, on a right-hand page; a foreword stays roman."""
        for kind in ("prologue", "introduction"):
            with self.subTest(kind=kind):
                r = set_book("memoir", FRONT + ["toc", ("foreword", "# Foreword\n\n" + prose(500)),
                                                (kind, "# Before\n\n" + prose(500)),
                                                ("chapter", "# One\n\n" + prose(500))])
                foreword, before, one = (next(i for i, k in r.kinds.items() if k == want)
                                         for want in ("foreword", kind, "chapter"))
                at = "query(<piece-start>).find(m => m.value == %d).location()"
                self.assertEqual(ev(r, f"{at % foreword}.page-numbering()"), "i")
                self.assertEqual(ev(r, f"({at % before}.page-numbering(), counter(page).at({at % before}).first())"),
                                 ["1", 1])
                pages, infos = dict(starts(r)), {p["page"]: p for p in page_infos(r)}
                self.assertEqual(pages[before] % 2, 1)                    # arabic page 1 is a right-hand page
                self.assertEqual(infos[pages[before]]["folio"], "1")
                self.assertRegex(infos[pages[foreword]]["folio"], "^[ivx]+$")
                self.assertGreater(int(infos[pages[one]]["folio"]), 1)
                self.assertIn(f"#let body-start = {before}", r.source)
        # a book that is all front and back matter has no arabic pages
        r = set_book("memoir", FRONT + ["toc", ("foreword", "# Foreword\n\nText."),
                                        ("afterword", "# Afterword\n\nText.")])
        self.assertIn("#let body-start = none", r.source)
        self.assertEqual(set(ev(r, "query(<piece-start>).map(m => m.location().page-numbering())")), {"i"})

    def test_body_groups_are_the_list_of_pieces(self):
        """typeset_book's groups are book.js's: the same front and back kinds, the same scan from both ends."""
        js = (Path(__file__).parent.parent / "studio" / "static" / "book.js").read_text(encoding="utf-8")
        found = {name: set(re.findall(r'"([a-z-]+)"', re.search(name + r" = new Set\(\[([^\]]*)\]\)", js)[1]))
                 for name in ("BOOK_FRONT", "BOOK_BACK")}
        self.assertEqual(found["BOOK_FRONT"], set(typeset_book.FRONT_MATTER))
        self.assertEqual(found["BOOK_BACK"], set(books.BACK_MATTER))
        contents = [{"auto": "half-title"}, {"kind": "dedication"}, {"auto": "toc"}, {"kind": "prologue"},
                    {"kind": "chapter"}, {"kind": "afterword"}, {"auto": "notes"}]
        self.assertEqual(typeset_book.body_range(contents), (3, 5))
        self.assertEqual(typeset_book.body_range([{"kind": "foreword"}, {"auto": "index"}]), (1, 1))
        self.assertEqual(typeset_book.body_range([]), (0, 0))

    def test_generated_pages_left_out(self):
        """A generated page whose feature is off, or that has nothing to list, isn't set: no page, no contents line,
        no piece-start; the book is as long as one without its entry."""
        noted = ("chapter", "# Harbour\n\n" + prose(200) + " The boats came in.^[At dawn.]\n")
        plain = ("chapter", "# Harbour\n\n" + prose(200) + "\n")
        back = ["notes", "bibliography", "index"]
        cases = [
            ("notes as footnotes", noted, {"notes": "footnotes", "sources": True, "index": True},
             {"notes": "the notes are footnotes", "bibliography": "nothing in the book cites a source yet",
              "index": "no index terms are marked yet"}),
            ("features off", noted, {"notes": "off", "sources": False, "index": False},
             {"notes": "notes are off in this book", "bibliography": "sources are off in this book",
              "index": "the index is off in this book"}),
            ("endnotes, none yet", plain, {"notes": "endnotes", "sources": True, "index": "first-lines"},
             {"notes": "the book has no endnotes yet", "bibliography": "nothing in the book cites a source yet",
              "index": "the book has no poems yet"}),
        ]
        for name, chapter, features, why in cases:
            with self.subTest(name):
                r = set_book("memoir", FRONT + ["toc", chapter] + back, features=features)
                index = {r.kinds[i]: i for i in r.kinds}
                self.assertEqual(typeset_book.left_out(r.meta, r.design, r.ctx), {index[a]: w for a, w in why.items()})
                self.assertEqual([i for i, _ in starts(r)], list(range(5)))         # the back pages never start
                targets = ev(r, "query(<toc-entry>).map(m => m.value.target)")
                self.assertEqual(targets, ["piece-4"])                               # the chapter alone
                for call in ("#notes-page(", "#bibliography-page(", "#index-page(", "#first-lines-page("):
                    self.assertNotIn(call, r.source)
                alone = set_book("memoir", FRONT + ["toc", chapter], features=features)
                self.assertEqual(page_count(r.pdf), page_count(alone.pdf))
        # with something to list, each is there
        r = set_book("memoir", FRONT + ["toc", ("chapter", "# Harbour\n\nThe boats.^[At dawn.] As said [@d]. A "
                                                           "[quay]{.idx}.\n")] + back,
                     features={"notes": "endnotes", "sources": True, "index": True}, sources=[DIJK])
        self.assertEqual(typeset_book.left_out(r.meta, r.design, r.ctx), {})
        self.assertEqual([i for i, _ in starts(r)], list(range(8)))
        # the bibliography of every source, with none at all
        r = set_book("memoir", FRONT + ["toc", plain, "bibliography"], features={"sources": True},
                     citations={"list": "all"})
        self.assertEqual(typeset_book.left_out(r.meta, r.design, r.ctx), {5: "the book has no sources yet"})

    def test_contents_and_index_link_to_their_pages(self):
        """The PDF is a reading copy: each contents line's title and page number, each index page number and each
        first line and its page link to the page they name."""
        r = set_book("nonfiction", FRONT + ["toc", ("chapter", "# One\n\nAn [apple]{.idx}.\n"),
                                            ("chapter", "# Two\n\n" + prose(700) + " An [apple]{.idx}.\n"), "index"],
                     features={"notes": "off", "sources": False, "index": True})
        pages = dict(starts(r))
        one, two, index = (i for i, k in r.kinds.items() if k in ("chapter", "index"))
        dests = ev(r, "query(link).filter(l => type(l.dest) == location).map(l => l.dest.page())")
        marks = sorted({p for _, p in ev(r, "query(<idx>).map(m => (m.value.t, m.location().page()))")})
        want = [pages[one]] * 2 + [pages[two]] * 2 + [pages[index]] * 2 + marks       # title and page per line
        self.assertEqual(sorted(dests), sorted(want))
        self.assertEqual(len(re.findall(rb"/Subtype\s*/Link", r.pdf)), len(want))
        # first lines
        poem = "# {0}\n\n{0} came in over the dunes\nand the wind kept the gulls\n"
        r = set_book("poetry", FRONT + ["toc", ("chapter", poem.format("Grey sea"), "poem"),
                                        ("chapter", poem.format("Low tide"), "poem"), "index"],
                     features={"index": "first-lines"})
        pages = dict(starts(r))
        poems = [i for i, k in r.kinds.items() if k == "chapter"]
        call = r.source[r.source.index("#first-lines-page("):]
        self.assertIn(typeset.lit("Grey sea came in over the dunes"), call)
        dests = ev(r, "query(link).filter(l => type(l.dest) == location).map(l => l.dest.page())")
        index = next(i for i, k in r.kinds.items() if k == "index")
        lines = [pages[i] for i in poems] * 2                         # a first line and its page, per poem
        self.assertEqual(sorted(dests), sorted([pages[i] for i in poems + [index]] * 2 + lines))

    def test_contents_numbers_are_right(self):
        chapter = "# {}\n\n" + prose(300) + "\n\n## A section\n\n" + prose(400) + "\n\n## Another\n\n" + prose(200)
        r = set_book("nonfiction", FRONT + ["toc", ("preface", "# Preface\n\n" + prose(400)),
                                            ("introduction", "# Introduction\n\n" + prose(400)),
                                            ("part", "# The Coast"),
                                            ("chapter", chapter.format("Harbour") + "^[A note.] As said [@d]."),
                                            ("chapter", chapter.format("Dunes") + " The [dunes]{.idx}."), "notes",
                                            "bibliography", "index"], sources=[DIJK])
        found = ev(r, """{
          let infos = query(<page-info>).map(m => m.value)
          query(<toc-entry>).map(m => {
            let t = m.value.target
            let loc = if t.starts-with("piece-") { locate(label(t)) } else {
              let parts = t.split("-")
              query(<blk>).find(b => b.value == (p: int(parts.at(1)), b: int(parts.at(2)))).location()
            }
            (t, m.value.shown, infos.find(x => x.page == loc.page()).folio)
          })
        }""")
        targets = [t for t, _, _ in found]
        titled = [i for i, k in r.kinds.items() if k not in ("half-title", "title-page", "copyright", "toc")]
        self.assertEqual([t for t in targets if t.startswith("piece-")], [f"piece-{i}" for i in titled])
        self.assertEqual(len([t for t in targets if t.startswith("blk-")]), 4)        # two sections in two chapters
        for target, shown, folio in found:
            self.assertEqual(shown, folio, target)
        shown = dict((t, s) for t, s, _ in found)
        preface, intro, part = titled[0], titled[1], titled[2]
        self.assertRegex(shown[f"piece-{preface}"], "^[ivx]+$")                   # front matter: roman
        self.assertEqual(shown[f"piece-{intro}"], "1")                            # arabic from the body's first piece
        self.assertRegex(shown[f"piece-{part}"], r"^\d+$")
        self.assertGreater(int(shown[f"piece-{part}"]), 1)

    def test_endnotes_grouped_and_numbered(self):
        one = "# Harbour\n\nThe boats went out.^[First note.] The light came.^[Second note.]\n"
        two = "# Dunes\n\nWe walked.^[Third note.] The gulls stayed high.^[Fourth note.]\n"
        for numbering, expected in (("chapter", [1, 2, 1, 2]), ("book", [1, 2, 3, 4])):
            with self.subTest(numbering=numbering):
                r = set_book("memoir", FRONT + ["toc", ("chapter", one), ("chapter", two), "notes"],
                             features={"notes": "endnotes", "noteNumbering": numbering})
                self.assertEqual([e["n"] for e in r.ctx.endnotes], expected)
                first, second = (i for i, k in r.kinds.items() if k == "chapter")
                call = r.source[r.source.index("#notes-page("):]
                self.assertLess(call.index('(title: "Harbour", notes: ((n: 1,'),
                                call.index(f'(title: "Dunes", notes: ((n: {expected[2]},'))
                for e in r.ctx.endnotes:
                    i, n = e["piece"], e["n"]
                    self.assertIn(i, (first, second))
                    self.assertEqual(ev(r, f"query(<note-{i}-{n}>).len()"), 1)
                    self.assertEqual(ev(r, f"query(<noteref-{i}-{n}>).len()"), 1)
                    self.assertEqual(ev(r, f"query(link).filter(l => l.dest == <note-{i}-{n}>).len()"), 1)
                    self.assertEqual(ev(r, f"query(link).filter(l => l.dest == <noteref-{i}-{n}>).len()"), 1)

    def test_footnotes_reset_per_chapter(self):
        one = "# Harbour\n\nThe boats went out.^[First note.] The light came.^[Second note.]\n"
        two = "# Dunes\n\nWe walked.^[Third note.] The gulls stayed high.^[Fourth note.]\n"
        for numbering, expected in (("chapter", [1, 2, 1, 2]), ("book", [1, 2, 3, 4])):
            with self.subTest(numbering=numbering):
                r = set_book("memoir", FRONT + [("chapter", one), ("chapter", two)],
                             features={"notes": "footnotes", "noteNumbering": numbering})
                self.assertEqual(ev(r, "query(footnote).map(f => counter(footnote).at(f.location()).first())"),
                                 expected)

    def test_index_pages(self):
        one = "# Orchard\n\n" + prose(200, mark=" An [apple]{.idx} and [Één]{.idx} and an [elm]{.idx}.") + \
            "\n\nThe [youth]{.idx term=\"trauma > youth\"} and [trauma]{.idx} itself.\n"
        two = "# River\n\n" + prose(1400, per=60, mark=" The [river]{.idx} ran on.")
        r = set_book("nonfiction", FRONT + ["toc", ("chapter", one), ("chapter", two), ("chapter", "# Fiets\n\nA "
                                            "[fiets]{.idx}.\n"), "index"])
        entries = ev(r, "query(<index-entry>).map(m => m.value)")
        marks = ev(r, "query(<idx>).map(m => (m.value.t, m.location().page()))")
        self.assertEqual(len(entries), len(r.ctx.terms))
        for e in entries:
            self.assertEqual(sorted(e["pages"]), sorted({p for t, p in marks if t == e["key"]}), e)
        river = next(e for e in entries if e["key"] == r.ctx.terms[("river", "")])
        self.assertGreaterEqual(len(river["pages"]), 3)
        self.assertRegex(river["shown"], r"^\d+–\d+$")          # a run of pages joined with an en dash
        call = r.source[r.source.index("#index-page("):]
        e_group, f_group = call.index('(letter: "E"'), call.index('(letter: "F"')
        self.assertLess(e_group, call.index('term: "Één"'))
        self.assertLess(call.index('term: "Één"'), call.index('term: "elm"'))          # Één sorts as een
        self.assertLess(call.index('term: "elm"'), f_group)
        self.assertRegex(call, r'\(term: "trauma", key: "t\d+", subs: \(\(term: "youth", key: "t\d+"\),\)\)')
        # an index that fits on its page is balanced over both columns, not all in the left one
        index = next(i for i, k in r.kinds.items() if k == "index")
        xs =ev(r, "query(<index-entry>).map(m => (m.location().page(), m.location().position().x / 1pt))")
        self.assertEqual({p for p, _ in xs}, {dict(starts(r))[index]})
        half = (r.design["width"] - r.design["margins"]["inside"] - r.design["margins"]["outside"]) / 2 * 72 / 25.4
        self.assertGreater(max(x for _, x in xs) - min(x for _, x in xs), half * 0.8)

    def test_bibliography_lists_cited(self):
        entries = FRONT + ["toc", ("chapter", "# One\n\nAs was said [@d].\n"), "bibliography"]
        r = set_book("nonfiction", entries, sources=[DIJK, BAKKER])
        self.assertIn('#emph[#"Zee"]', r.source)
        self.assertNotIn('#emph[#"Land"]', r.source)
        r = set_book("nonfiction", entries, sources=[DIJK, BAKKER], citations={"list": "all"})
        self.assertIn('#emph[#"Zee"]', r.source)
        self.assertIn('#emph[#"Land"]', r.source)
        self.assertLess(r.source.index('#emph[#"Land"]'), r.source.index('#emph[#"Zee"]'))     # Bakker before Dijk

    def test_generated_labels_dutch(self):
        r = set_book("memoir", FRONT + ["toc", ("chapter", "# Een\n\nDe zee.^[Een noot.]\n"), "notes"],
                     language="nl", title="De grijze zee")
        self.assertIn(typeset.lit("Inhoud"), r.source)
        self.assertIn(typeset.lit("Noten"), r.source)
        self.assertNotIn(typeset.lit("Contents"), r.source)

    def test_even_page_count_and_trim(self):
        r = set_book("memoir", FRONT + ["toc", ("chapter", "# One\n\n" + prose(300) + "^[A note.]"), "notes"],
                     language="nl")
        count = page_count(r.pdf)
        self.assertEqual(count % 2, 0)
        self.assertEqual(count, len(page_infos(r)))
        boxes = re.findall(rb"/MediaBox\s*\[([^\]]*)\]", r.pdf)
        self.assertEqual(len(boxes), count)
        for box in boxes:
            for got, want in zip((float(x) for x in box.split()), (0, 0, 382.68, 595.28)):
                self.assertAlmostEqual(got, want, delta=0.01)
        self.assertTrue(page_infos(r)[-1]["blank"])        # the notes page ended on a recto: a blank page closes

    def test_dutch_hyphenation_on(self):
        r = set_book("memoir", FRONT + [("chapter", "# Een\n\n" + prose(400, vocabulary=_NL))], language="nl")
        self.assertIn('lang: "nl"', r.source)
        self.assertIn("hyphenate: true", r.source)
        self.assertEqual((r.design["width"], r.design["height"], r.design["text"]["size"]), (135, 210, 10.5))
        self.assertGreater(page_count(r.pdf), 4)

    def test_blank_pages_have_no_folio(self):
        r = set_book("memoir", FRONT + ["toc", ("chapter", "# One\n\nA single page."),
                                        ("chapter", "# Two\n\n" + prose(300)), ("part", "# Later"),
                                        ("chapter", "# Three\n\n" + prose(100))])
        infos = page_infos(r)
        self.assertEqual([p["page"] for p in infos], list(range(1, page_count(r.pdf) + 1)))
        self.assertTrue(any(p["blank"] for p in infos))
        self.assertFalse(any(p["blank"] and p["shown"] for p in infos))
        self.assertFalse(infos[0]["shown"])         # half-title
        self.assertFalse(infos[2]["shown"])         # title page
        self.assertFalse(infos[3]["shown"])         # copyright page
        pages = dict(starts(r))
        one = next(i for i, k in r.kinds.items() if k == "chapter")
        self.assertTrue(infos[pages[one]]["blank"])          # the page after a one-page chapter
        part = next(i for i, k in r.kinds.items() if k == "part")
        self.assertFalse(infos[pages[part] - 1]["shown"])    # no folio on a part page
        self.assertTrue(infos[pages[part]]["blank"])          # and its back is blank
        for p in infos:
            if p["blank"]:
                self.assertIsNone(p["folio"], p)
        # the contents is page v; the blank before arabic page 1 belongs to neither numbering: no folio, not "6"
        self.assertEqual((pages[one], infos[4]["folio"], infos[6]["folio"]), (7, "v", "1"))
        self.assertTrue(infos[5]["blank"])
        self.assertIsNone(infos[5]["folio"])

    def test_untitled_numbered_chapter_keeps_its_opening(self):
        r = set_book("nonfiction", FRONT + ["toc", ("chapter", "# One\n\nText."), ("chapter", "# Two\n\nText."),
                                            ("chapter", "Text without a title."), ("chapter", "# Four\n\nText.")])
        pages = dict(starts(r))
        chapters = [i for i, k in r.kinds.items() if k == "chapter"]
        found = ev(r, "query(<chapter-number>).map(m => (m.value, m.location().page()))")
        self.assertEqual(found, [[str(n), pages[i]] for n, i in enumerate(chapters, 1)])
        top, sink, line = r.design["margins"]["top"], r.design["headings"]["sink"], r.design["text"]["line"]
        at = "query(<blk>).find(m => m.value == (p: {}, b: {})).location().position().y"
        for i, b in ((chapters[1], 1), (chapters[2], 0)):      # the first text of a titled chapter and the untitled one
            y = ev(r, f"({at.format(i, b)} - {top}mm) / {line}pt")
            self.assertAlmostEqual(y, round(y), places=3)                         # on the line grid
            self.assertGreater(y * line, sink * 72 / 25.4 + r.design["headings"]["size"])      # under its number
        self.assertNotIn(f"<piece-{chapters[2]}>", r.source)          # no title, no label, no contents line

    def test_contents_titles_line_up(self):
        chapter = "# Chapter {}\n\nText.\n\n## A section\n\nMore text.^[A note.]\n"
        r = set_book("nonfiction", FRONT + ["toc"] + [("chapter", chapter.format(n)) for n in range(1, 12)] +
                     ["notes"], features={"notes": "endnotes"}, pages={"leaders": True})
        notes = next(i for i, k in r.kinds.items() if k == "notes")
        xs = ev(r, "query(<toc-title>).map(m => (m.value, m.location().position().x / 1pt))")
        chapters = [x for key, x in xs if key.startswith("piece-") and r.kinds[int(key[6:])] == "chapter"]
        sections = [x for key, x in xs if key.startswith("blk-")]
        self.assertEqual((len(chapters), len(sections)), (11, 11))
        for x in chapters + sections:           # 1 to 11: every title, and every section, starts at the same place
            self.assertAlmostEqual(x, chapters[0], delta=0.01)
        self.assertLess(dict(xs)[f"piece-{notes}"], chapters[0] - 5)    # an unnumbered title starts at the edge

    def test_printed_characters_reach_the_font_check(self):
        md = "# One\n\n::: epigraph\nThe sea.\n\n— A. Walker\n:::\n\nText.^[A note.]\n\n***\n\nMore [sea]{.idx}.\n"
        r = set_book("nonfiction", FRONT + ["toc", ("chapter", md), "notes", "index"],
                     features={"notes": "endnotes"}, scene="asterism")
        for c in "⁂—©–p.()0123456789iv":
            self.assertIn(c, r.ctx.chars)

    def test_running_heads(self):
        r = set_book("memoir", FRONT + ["toc", ("chapter", "# The Harbour\n\n" + prose(1200)),
                                        ("chapter", "# The Dunes\n\n" + prose(100)), "notes"],
                     features={"notes": "endnotes"})
        infos = {p["page"]: p for p in page_infos(r)}
        pages = dict(starts(r))
        harbour = next(i for i, k in r.kinds.items() if k == "chapter")
        notes = next(i for i, k in r.kinds.items() if k == "notes")
        self.assertIsNone(infos[pages[harbour]]["head"])                  # no head on an opening
        self.assertEqual(infos[pages[harbour] + 1]["head"], "The Grey Sea")    # verso: the book's title
        self.assertEqual(infos[pages[harbour] + 2]["head"], "The Harbour")     # recto: the piece's title
        for p in infos.values():
            if p["blank"] or not p["shown"]:
                self.assertIsNone(p["head"], p)
        self.assertEqual(r.kinds[notes], "notes")
        r = set_book("memoir", FRONT + [("chapter", "# The Harbour\n\n" + prose(1200))], heads={"verso": "author"})
        infos = {p["page"]: p for p in page_infos(r)}
        self.assertEqual(infos[dict(starts(r))[3] + 1]["head"], "Anna Example")

    def test_book_details_are_text(self):
        odd = 'A [b] <l> #let x = 1 $x$ @k "q" \\ // c /* d */ *s* _i_ ]'
        r = set_book("memoir", FRONT + ["toc", ("chapter", "# One\n\nText.")], title="Sea " + odd, author=odd,
                     details={"publisher": odd, "edition": odd, "isbn": odd, "nur": odd, "copyright": odd})
        self.assertGreater(page_count(r.pdf), 4)
        self.assertIn(typeset.lit("Sea " + odd), r.source)
        for line in r.source.split("\n"):
            if "#let x" in line:
                self.assertNotIn("#let x = 1", re.sub(r'"(?:[^"\\]|\\.)*"', '""', line))

    def test_book_text_is_never_code(self):
        """Typst syntax in every place the book's own pages print the author's words: the page names (labels), the
        contents' titles (a part's and a chapter's, numbered), the index's terms and subentries, the first lines, the
        notes' piece titles. It compiles without a warning (set_book fails on one) and is only ever inside literals."""
        odd = '#let x = 1 $x$ @k " // c /* d */ #('             # up to 60 characters: a page name's limit
        names = {k: odd for k in ("toc", "notes", "bibliography", "index", "first-lines", "part", "chapter")}
        typed = ("x = 1", "$x$", "@k", "/* d */")
        literal = re.compile(r'"(?:[^"\\]|\\.)*"')
        chapter = f"# {odd}\n\n[{odd}]{{.idx}} and a [sub]{{.idx term=\"{odd.replace(chr(34), '')} > {odd[:9]}\"}}."
        r = set_book("nonfiction", FRONT + ["toc", ("part", f"# {odd}"), ("chapter", chapter + "^[A note.]\n"),
                                            ("chapter", "Untitled, numbered.^[Another.]\n"), "notes", "index"],
                     features={"notes": "endnotes", "index": True}, pages={"labels": names},
                     headings={"number": "digits"})
        self.assertTrue(r.ctx.terms)
        self.assertGreater(ev(r, "query(<toc-entry>).len()"), 2)
        r2 = set_book("poetry", FRONT + ["toc", ("chapter", f"# {odd}\n\n{odd}\nsecond line\n", "poem"), "index"],
                      features={"index": "first-lines"}, pages={"labels": names})
        self.assertEqual([t for t, _ in r2.ctx.first_lines], [odd])
        for book in (r, r2):
            self.assertIn(typeset.lit(odd), book.source)
            rest = literal.sub('""', book.source)
            for t in typed:
                self.assertNotIn(t, rest)


if __name__ == "__main__":
    unittest.main()
