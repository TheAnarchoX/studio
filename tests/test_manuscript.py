"""The manuscript dialect: Markdown pieces to editor documents (ProseMirror JSON) and back."""
import copy
import time
import unittest

from studio import manuscript, manuscript_lists

# Canonical pieces: serialize(parse(md)) gives back exactly md. Later tasks import these lists
# (the browser schema must load every one of them unchanged).
SAMPLES = [
    # piece title, section headings
    "# Een nieuwe dag\n\nDe eerste alinea van het stuk.\n",
    "## Een kop in het stuk\n\nTekst onder de kop.\n\n### Een kleinere kop\n\nMeer tekst.\n",
    # italic, bold
    "Dit is *schuin*, dit is **vet** en dit ***allebei***.\n",
    "Een woord met *schuin* binnen **vet *en schuin* samen** en verder.\n",
    # notes
    "Een zin met een noot.^[Een noot met *schuine* woorden erin.] Daarna gaat het verder.\n",
    "Een noot met een bron.^[Zie [@bron2020, p. 4] en verder.] Klaar.\n",
    # citations
    "Zoals eerder beschreven [@bron2020].\n",
    "Een bewering [see @bron2020, p. 12].\n",
    "Twee bronnen [@a; @b, pp. 3–5].\n",
    "Met een lastige sleutel [@{bron met spaties}, p. 1].\n",
    # index terms
    "In [Rotterdam]{.idx} begon het.\n",
    "Over [het trauma]{.idx term=\"trauma\"} schrijf ik later.\n",
    "Een [subingang]{.idx term=\"trauma > jeugd\"} in de index.\n",
    # comment to self
    "Op [12 maart]{.comment note=\"klopt \\\"deze\\\" datum?\"} gebeurde het.\n",
    "Een [opmerking]{.comment note=\"met \\{haken\\} en \\\\ een streep\"} erbij.\n",
    # small caps, other language, combined spans
    "In [HOOFDLETTERS]{.smallcaps} gezet.\n",
    "Ze zei [good morning]{lang=en} en liep door.\n",
    "Een [gemengd woord]{.idx .smallcaps term=\"a > b\" lang=en} hier.\n",
    "[Alles]{.idx .comment .smallcaps term=\"alles\" note=\"nakijken\" lang=nl-BE} samen.\n",
    "Een [*schuine* term]{.idx} en *een [term]{.idx} in schuin*.\n",
    # scene break
    "Eerste deel.\n\n***\n\nTweede deel.\n",
    # epigraph with attribution
    "::: epigraph\nWie schrijft, die blijft.\n\n— Een *oud* spreekwoord\n:::\n\nHet verhaal begint.\n",
    # poem inside prose, linked poem
    "Ze las voor:\n\n::: poem\nDe eerste regel\nde *tweede* regel\n\nEen nieuwe strofe\nen de laatste regel\n:::\n\n"
    "En ze stopte.\n",
    "::: {.poem src=\"Reeks/Een gedicht\"}\n:::\n",
    # image with width
    "![Een foto van de haven](../images/haven.jpg){width=60%}\n",
    "![Zonder breedte](../images/kade.jpg)\n",
    "![Met spaties](<../images/een foto (2).jpg>){width=\"50 %\"}\n",
    # page break
    "Voor het pagina-einde.\n\n::: pagebreak\n:::\n\nNa het pagina-einde.\n",
    # block quotation
    "Ze schreef:\n\n> Een citaat in proza.\n>\n> Een tweede alinea in het citaat.\n\nEinde.\n",
    # hard break
    "Een regel\\\nen een harde regelovergang.\n",
    # escapes
    "Een ster \\* en een haak \\[ blijven tekst, net als \\_ en \\` en \\\\.\n",
    "\\# geen kop\n\n1\\. geen lijst\n\n\\- geen opsomming\n\n\\> geen citaat\n\n\\::: geen blok\n",
    # Dutch quotes and diacritics
    "„Ja”, zei ze, ‘ja’… En ’s avonds? Één keer, café, naïef.\n",
    # lists: bullets, numbers, letters and roman numerals, nested; a list starting elsewhere; line breaks, empty items
    "- Een\n- Twee met *nadruk*^[Een noot.]\n- Drie [@bron2020, p. 4]\n",
    "1. Een\n2. Twee\n   a. Sub een\n   b. Sub twee\n      i. Diep\n3. Drie\n",
    "Tekst ervoor.\n\n3. Drie\n4. Vier\n\nTekst erna.\n",
    "A.  Eerste\nB.  Tweede\n",
    "I.  Een\nII.  Twee\nIII.  Drie\n",
    "i. een\nii. twee\n",
    "- Een regel\\\n  en de volgende\n- [Opmerking]{.comment note=\"nakijken\"} hier\n",
    "- Een\n\n1. Nu genummerd\n",
    "-\n- Na een lege\n",
    "a. een\nb. twee\nc. drie\nd. vier\ne. vijf\nf. zes\ng. zeven\nh. acht\ni. negen\n",
    # ordered lists side by side: the second one takes the other delimiter, so it doesn't continue the first
    "a. een\nb. twee\n\ni) drie\nii) vier\n",
    "i. een\nii. twee\n\nc) drie\nd) vier\n",
    # centred and right-aligned paragraphs
    "::: center\nIn het midden.\n\nNog een regel.\n:::\n\nGewoon verder.\n",
    "::: right\nAmsterdam, 3 maart\n:::\n",
    # underline, strikethrough, sizes; every span class at once; a literal tilde
    "Een [onderstreept]{.underline} woord.\n",
    "Een ~~doorgestreept~~ woord, *schuin ~~en weg~~*.\n",
    "[Klein]{.x-small}, [kleiner]{.small}, [groot]{.large} en [groter]{.x-large}.\n",
    "[Alles]{.idx .comment .smallcaps .underline .large term=\"alles\" note=\"n\" lang=en} samen.\n",
    "Een tilde \\~ blijft tekst.\n",
    # LaTeX math: inline, display, a literal dollar, math in a table cell
    "Einstein schreef $E = mc^2$ en meer.\n",
    "Een formule:\n\n$$\n\\int_0^1 x^2 \\, dx = \\frac{1}{3}\n$$\n\nEn verder.\n",
    "Het kost \\$20 of \\$30.\n",
    "| a |\n| --- |\n| $x$ |\n",
    # pipe tables: a header row, column alignment, marks and notes in cells; a table without a header (an empty first
    # row); a literal pipe
    "| Jaar | Plaats |\n| --- | :-: |\n| 1984 | Utrecht |\n| 1990 | *Gent*^[Een noot.] |\n",
    "|  |  |\n| --- | --: |\n| a | b |\n",
    "Een pijp \\| in tekst.\n",
]

# Pieces whose form is poem: every line break kept, blank lines between stanzas.
POEM_SAMPLES = [
    "# Een gedicht\n\nDe eerste regel\nde *tweede* regel\n\n"
    "De derde regel^[Een noot bij de regel.]\nde vierde [@bron2020]\n",
    "Regel een\n\\- regel twee met een streepje\n1\\. regel drie met een getal\n\n***\n\nNa de scheiding\n",
    "::: epigraph\nEen regel uit een ander gedicht\nen de volgende\n\n— Een dichter\n:::\n\n"
    "Mijn eerste regel\nen mijn [tweede\nregel]{.comment note=\"te lang\"}\n",
    # indented lines (no-break spaces); a stanza's first line starts with an entity, which Markdown can't strip
    "Een regel\n\N{NO-BREAK SPACE}\N{NO-BREAK SPACE}een ingesprongen regel\n\n"
    "&#xA0;\N{NO-BREAK SPACE}Ingesprongen eerste regel\nde tweede\n",
    # a centred stanza
    "Een regel\n\n::: center\nregel een\nregel twee\n:::\n",
]


def text(t, *marks):
    node = {"type": "text", "text": t}
    if marks:
        node["marks"] = list(marks)
    return node


class RoundTripTest(unittest.TestCase):
    def test_round_trip(self):
        for md in SAMPLES:
            with self.subTest(md=md):
                doc = manuscript.parse(md)
                self.assertEqual(manuscript.serialize(doc), md)
                self.assertEqual(manuscript.parse(manuscript.serialize(doc)), doc)

    def test_poem_form_round_trip(self):
        for md in POEM_SAMPLES:
            with self.subTest(md=md):
                doc = manuscript.parse(md, "poem")
                self.assertEqual(doc["attrs"], {"form": "poem"})
                self.assertEqual(manuscript.serialize(doc, "poem"), md)
                self.assertEqual(manuscript.serialize(doc), md)   # the document knows its form
        doc = manuscript.parse("Een\ntwee\n\nDrie\n", "poem")
        self.assertEqual(doc["content"], [
            {"type": "paragraph", "content": [text("Een"), {"type": "hard_break"}, text("twee")]},
            {"type": "paragraph", "content": [text("Drie")]},
        ])

    def test_document_shape(self):
        doc = manuscript.parse("# Titel\n\nEen *zin*^[Noot.] [@bron, p. 3] [*x*]{.smallcaps .idx}.\n\n"
                               "## Kop\n\n::: poem\nRegel\n:::\n\n![Bijschrift](../images/a.jpg)\n")
        self.assertEqual(doc, {"type": "doc", "attrs": {"form": "prose"}, "content": [
            {"type": "title", "content": [text("Titel")]},
            {"type": "paragraph", "content": [
                text("Een "),
                text("zin", {"type": "em"}),
                {"type": "note", "content": [text("Noot.")]},
                text(" "),
                {"type": "cite", "attrs": {"items": [{"key": "bron", "prefix": "", "locator": "p. 3"}]}},
                text(" "),
                text("x", {"type": "em"}, {"type": "idx", "attrs": {"term": None}}, {"type": "smallcaps"}),
                text("."),
            ]},
            {"type": "heading", "attrs": {"level": 2}, "content": [text("Kop")]},
            {"type": "poem", "attrs": {"src": None}, "content": [{"type": "paragraph", "content": [text("Regel")]}]},
            {"type": "image", "attrs": {"src": "../images/a.jpg", "alt": "Bijschrift", "width": None}},
        ]})
        self.assertEqual(manuscript.parse("::: {.poem src=\"Reeks/Gedicht\"}\n:::\n")["content"],
                         [{"type": "poem", "attrs": {"src": "Reeks/Gedicht"}}])
        self.assertEqual(manuscript.parse(""), {"type": "doc", "attrs": {"form": "prose"}})
        epigraph = manuscript.parse("::: epigraph\nTekst.\n\n— Iemand\n:::\n")["content"][0]
        self.assertEqual(epigraph, {"type": "epigraph", "content": [
            {"type": "paragraph", "content": [text("Tekst.")]},
            {"type": "attribution", "content": [text("Iemand")]},
        ]})
        self.assertEqual(manuscript.SCHEMA["marks"], ["em", "strong", "idx", "comment", "smallcaps", "lang",
                                                      "underline", "strike", "size"])
        self.assertEqual(manuscript.SCHEMA["nodes"], [
            "doc", "title", "heading", "paragraph", "list_item", "aligned", "blockquote", "scene_break", "epigraph",
            "attribution", "poem", "image", "page_break", "table", "table_row", "table_cell", "math_display",
            "hard_break", "note", "cite", "math", "text"])
        self.assertEqual(manuscript.SIZES, ("x-small", "small", "large", "x-large"))

    def test_non_canonical_input_normalises(self):
        cases = [
            ("Dit is _schuin_ en __vet__.\n", "Dit is *schuin* en **vet**.\n"),
            ("Titel\n=====\n\nTekst.\n", "# Titel\n\nTekst.\n"),
            ("Tekst.[^1] Meer.\n\n[^1]: Een *noot*.\n", "Tekst.^[Een *noot*.] Meer.\n"),
            ("Tekst[^lang] en[^2].\n\n[^2]: Tweede.\n[^lang]: Eerste noot.\n",
             "Tekst^[Eerste noot.] en^[Tweede.].\n"),
            ("\N{BYTE ORDER MARK}# Titel\r\n\r\nEen regel\r\nloopt door.\r\n", "# Titel\n\nEen regel loopt door.\n"),
            ("* * *\n\n---\n", "***\n\n***\n"),
            ("#### Diepe kop\n", "### Diepe kop\n"),
            ("Tekst.\n\n# Tweede eerste kop\n", "Tekst.\n\n## Tweede eerste kop\n"),
            ("Een `code` en een [link](https://example.org).\n",
             "Een \\`code\\` en een \\[link\\](https://example.org).\n"),
            ("Een noot.[^x]\n\n[^x]: Eerste alinea.\n\n    Tweede alinea.\n",
             "Een noot.^[Eerste alinea. Tweede alinea.]\n"),
            ("Ongebruikt.\n\n[^z]: Losse noot.\n", "Ongebruikt.\n\nLosse noot.\n"),
            ("Tekst ![Bijschrift](../images/a.jpg) meer.\n",
             "Tekst\n\n![Bijschrift](../images/a.jpg)\n\nmeer.\n"),
            ("::: waarschuwing\nTekst.\n:::\n", "Tekst.\n"),
        ]
        for md, canonical in cases:
            with self.subTest(md=md):
                out = manuscript.serialize(manuscript.parse(md))
                self.assertEqual(out, canonical)
                self.assertEqual(manuscript.serialize(manuscript.parse(out)), canonical)

    def test_editor_documents_serialize_cleanly(self):
        def para(*content):
            return {"type": "doc", "attrs": {"form": "prose"},
                    "content": [{"type": "paragraph", "content": list(content)}]}
        em = {"type": "em"}
        # whitespace at the edge of an italic run goes outside the asterisks
        self.assertEqual(manuscript.serialize(para(text("een ", em), text("woord"))), "*een* woord\n")
        self.assertEqual(manuscript.serialize(para(text("een"), text(" woord", em))), "een *woord*\n")
        # adjacent text nodes with equal marks are one run
        self.assertEqual(manuscript.serialize(para(text("a", em), text("b", em))), "*ab*\n")
        # a hard break at the edge of an italic run, and at the end of a paragraph
        self.assertEqual(manuscript.serialize(para(text("a", em), {"type": "hard_break", "marks": [em]}, text("b"))),
                         "*a*\\\nb\n")
        self.assertEqual(manuscript.serialize(para(text("a"), {"type": "hard_break"})), "a\n")
        # attribute values: newlines become spaces, quotes and braces are escaped
        comment = {"type": "comment", "attrs": {"note": "een\n\"noot\" {x}"}}
        md = manuscript.serialize(para(text("a", comment)))
        self.assertEqual(md, "[a]{.comment note=\"een \\\"noot\\\" \\{x\\}\"}\n")
        mark = manuscript.parse(md)["content"][0]["content"][0]["marks"][0]
        self.assertEqual(mark["attrs"]["note"], "een \"noot\" {x}")
        # leading whitespace and markup characters at a line start
        self.assertEqual(manuscript.serialize(para(text("  # niet"))), "\\# niet\n")
        self.assertEqual(manuscript.serialize(para(text("a"), {"type": "hard_break"}, text("==="))), "a\\\n\\===\n")
        # a heading that ends in #
        doc = {"type": "doc", "attrs": {"form": "prose"},
               "content": [{"type": "heading", "attrs": {"level": 2}, "content": [text("Nummer #")]}]}
        md = manuscript.serialize(doc)
        self.assertEqual(manuscript.parse(md)["content"][0]["content"], [text("Nummer #")])
        # an empty document
        self.assertEqual(manuscript.serialize({"type": "doc", "attrs": {"form": "prose"}}), "")
        with self.assertRaises(ValueError):
            manuscript.serialize({"type": "doc", "content": [{"type": "sidebar"}]})

    def test_editor_documents_stay_canonical(self):
        """What the serializer writes reads back to a document that is written the same way."""
        em, strong, sc = {"type": "em"}, {"type": "strong"}, {"type": "smallcaps"}
        idx, comment = {"type": "idx", "attrs": {"term": None}}, {"type": "comment", "attrs": {"note": "n"}}
        br = {"type": "hard_break"}
        cite = {"type": "cite", "attrs": {"items": [{"key": "a", "prefix": "", "locator": ""}]}}

        def doc(*content, form="prose", block="paragraph"):
            node = {"type": block, "content": list(content)}
            if block == "heading":
                node["attrs"] = {"level": 2}
            return {"type": "doc", "attrs": {"form": form}, "content": [node]}
        cases = [
            # an italic run that ends with a span goes inside it: `*a [b]{.idx}*c` would not close
            (doc(text("a ", em), text("b", em, idx), text("c")), "*a* [*b*]{.idx}c\n"),
            # after a letter, `*[` would not open
            (doc(text("x"), text("a", em, comment), text(" b", em)), "x[*a*]{.comment note=\"n\"} *b*\n"),
            # a note at the end of a bold run goes outside it
            (doc(text("a", strong), {"type": "note", "content": [text("n")], "marks": [strong]}, text("b")),
             "**a**^[n]b\n"),
            # `^` before a span would open a note; `{` after a citation would make it a span;
            # `!` before a citation would make it an image
            (doc(text("x^"), text("y", idx)), "x\\^[y]{.idx}\n"),
            (doc(cite, text("{k}")), "[@a]\\{k}\n"),
            (doc(cite, text("{.idx}")), "[@a]\\{.idx}\n"),
            (doc(text("Wow!"), cite, text("(zie)")), "Wow\\![@a](zie)\n"),
            # indented poem lines keep their no-break spaces, also at the start of a stanza
            (doc(text("Regel"), br, text("\N{NO-BREAK SPACE}\N{NO-BREAK SPACE}in"), form="poem"),
             "Regel\n\N{NO-BREAK SPACE}\N{NO-BREAK SPACE}in\n"),
            (doc(text("\N{NO-BREAK SPACE}\N{NO-BREAK SPACE}in"), form="poem"), "&#xA0;\N{NO-BREAK SPACE}in\n"),
            # poems: an empty line ends the stanza; a space in a span at a line start stays
            (doc(text("a"), br, br, text("b"), form="poem"), "a\n\nb\n"),
            (doc(text("a"), br, text(" b", sc), form="poem"), "a\n[ b]{.smallcaps}\n"),
            (doc(text("regel"), {"type": "note", "content": [text("a"), br, br, text("b")]}, form="poem"),
             "regel^[a\nb]\n"),
            # a heading is one line, also inside its notes
            (doc(text("Kop"), {"type": "note", "content": [text("a"), br, text("b")]}, block="heading"),
             "## Kop^[a b]\n"),
        ]
        for document, md in cases:
            with self.subTest(md=md):
                form = document["attrs"]["form"]
                self.assertEqual(manuscript.serialize(document), md)
                again = manuscript.parse(md, form)
                self.assertEqual(manuscript.serialize(again), md)
                self.assertEqual(manuscript.plain_text(again), manuscript.plain_text(document))

    def test_unwritable_emphasis_degrades(self):
        """Italic or bold that Markdown can't write loses its mark at the edge (or entirely), never turns into
        printed asterisks."""
        em, strong = {"type": "em"}, {"type": "strong"}
        cases = [
            ([text("x"), text("(y)", em)], "x(*y)*\n"),       # only `(` must leave: `*` after `)` closes at the end
            ([text("x"), text("(y)", em), text("z")], "x(*y*)z\n"),
            ([text("zo"), text("’n", em)], "zo’*n*\n"),
            ([text("regel"), text("—", strong), text("x")], "regel—x\n"),
            ([text("a "), text("woord,", em), text("b")], "a *woord*,b\n"),
            ([text("x"), text("…", em), text("y")], "x…y\n"),
            ([text("wereld-", em), text("oorlog")], "*wereld*-oorlog\n"),
            # bold `ab` crossing italic `bc` inside one word: no exact form, but no asterisks in the text
            ([text("a", strong), text("b", strong, em), text("c", em), text("d")], None),
        ]
        for content, expected in cases:
            document = {"type": "doc", "attrs": {"form": "prose"}, "content": [{"type": "paragraph", "content": content}]}
            md = manuscript.serialize(document)
            with self.subTest(md=md):
                if expected is not None:
                    self.assertEqual(md, expected)
                again = manuscript.parse(md)
                self.assertNotIn("*", manuscript.plain_text(again))
                self.assertEqual(manuscript.plain_text(again), manuscript.plain_text(document))
                self.assertEqual(manuscript.serialize(again), md)
        md = manuscript.serialize({"type": "doc", "attrs": {"form": "prose"}, "content": [
            {"type": "paragraph", "content": cases[-1][0]}]})
        marked = [n for n in manuscript.parse(md)["content"][0]["content"] if n.get("marks")]
        self.assertTrue(marked)                     # one of the two runs keeps its mark

    def test_hand_written_poems_keep_every_line(self):
        """Poem lines are not read as Markdown blocks: lists, quotations, headings and rules stay lines."""
        poem_blocks = [
            ("::: poem\nregel een\n***\nregel twee\n:::\n", "::: poem\nregel een\n\\*\\*\\*\nregel twee\n:::\n"),
            ("::: poem\nregel een\n---\nregel twee\n:::\n", "::: poem\nregel een\n\\---\nregel twee\n:::\n"),
            ("::: poem\neerste regel\n- tweede regel\n\nnieuwe strofe\n:::\n",
             "::: poem\neerste regel\n\\- tweede regel\n\nnieuwe strofe\n:::\n"),
            ("::: poem\n> een regel\n# nog een\n1. een\n2) twee\n:::\n",
             "::: poem\n\\> een regel\n\\# nog een\n1\\. een\n2\\) twee\n:::\n"),
            ("::: poem\nregel\n===\n:::\n", "::: poem\nregel\n\\===\n:::\n"),
        ]
        for md, canonical in poem_blocks:
            with self.subTest(md=md):
                self.assertEqual(manuscript.serialize(manuscript.parse(md)), canonical)
                self.assertEqual(manuscript.serialize(manuscript.parse(canonical)), canonical)
        # a piece whose form is poem keeps the dialect's blocks (title, `##` heading, quotation, scene break);
        # lists and underlined headings are lines
        poem_pieces = [
            ("regel een\n---\nregel twee\n", "regel een\n\n***\n\nregel twee\n"),
            ("Regel een\n- regel twee\n1. regel drie\n+ regel vier\n",
             "Regel een\n\\- regel twee\n1\\. regel drie\n\\+ regel vier\n"),
            ("Regel een\n\n> Een geciteerde regel\n> en nog een\n", "Regel een\n\n> Een geciteerde regel\n> en nog een\n"),
            ("# Titel\n\nRegel\n===\n\n## Deel twee\n\nRegel\n", "# Titel\n\nRegel\n\\===\n\n## Deel twee\n\nRegel\n"),
        ]
        for md, canonical in poem_pieces:
            with self.subTest(md=md):
                self.assertEqual(manuscript.serialize(manuscript.parse(md, "poem")), canonical)
                self.assertEqual(manuscript.serialize(manuscript.parse(canonical, "poem")), canonical)

    def test_dutch_text(self):
        md = "# Één week\n\n„Ja”, zei ze. ‘Ja’… En “ja” – ’s avonds, café, naïef, ijs.\n"
        self.assertEqual(manuscript.serialize(manuscript.parse(md)), md)
        self.assertEqual(manuscript.title_of(md), "Één week")
        self.assertEqual(manuscript.counts("'s avonds")["words"], 1)
        self.assertEqual(manuscript.counts("Ze kwam ’s avonds thuis.")["words"], 4)
        self.assertEqual(manuscript.counts("„Ja”, zei ze… – zo’n auto’s.")["words"], 5)
        # a short word after an opening single quote is a word, not a clitic
        for line, words in [("‘Ik ben moe’, zei ze.", 5), ("‘Er is niets’, zei hij.", 5), ("‘Op de hoek’.", 3),
                            ("'It is late,' she said.", 5), ("Get 'em out.", 3), ("’t Is laat, ’k ga.", 3)]:
            with self.subTest(line=line):
                self.assertEqual(manuscript.counts(line)["words"], words)

    def test_counts(self):
        self.assertEqual(manuscript.counts("Een ^[noot met drie woorden] twee."),
                         {"words": 2, "note_words": 4, "notes": 1})
        self.assertEqual(manuscript.counts("# Titel\n\nEen [woord]{.comment note=\"vier woorden in noot\"} "
                                           "[@bron, p. 3].^[Eén.]^[Twee *woorden*.]\n"),
                         {"words": 2, "note_words": 3, "notes": 2})                    # the piece title is not counted
        self.assertEqual(manuscript.counts("Regel een\nregel twee\n", "poem")["words"], 4)
        self.assertEqual(manuscript.counts(""), {"words": 0, "note_words": 0, "notes": 0})

    def test_the_piece_title_is_not_counted(self):
        self.assertEqual(manuscript.counts("# Chapter 1\n")["words"], 0)                  # a new, empty piece
        self.assertEqual(manuscript.counts("# Untitled\n", "poem")["words"], 0)
        self.assertEqual(manuscript.counts("# Twee woorden\n\n## Kop hier\n\nEen.\n")["words"], 3)   # headings inside count
        self.assertEqual(manuscript.counts("# Titel^[Een noot.]\n\nTekst.\n"), {"words": 1, "note_words": 2, "notes": 1})
        self.assertEqual(manuscript.counts("# De zee\n\nGolven\nen zand\n", "poem")["words"], 3)
        self.assertIn("Twee woorden", manuscript.plain_text(manuscript.parse("# Twee woorden\n\nEen.\n")))   # search still sees it

    def test_plain_text(self):
        doc = manuscript.parse("# Titel\n\nEen *zin*^[noot] [@bron] hier.\n\n::: poem\nA\nB\n:::\n")
        self.assertEqual(manuscript.plain_text(doc), "Titel\n\nEen zin  hier.\n\nA\nB")

    def test_title_of(self):
        self.assertEqual(manuscript.title_of("# Titel\n\nTekst.\n"), "Titel")
        self.assertEqual(manuscript.title_of("\n\n# *Schuine* titel^[Met noot.]\n"), "Schuine titel")
        self.assertEqual(manuscript.title_of("Titel\n===\n\nTekst.\n"), "Titel")
        self.assertEqual(manuscript.title_of("# Titel[^1]\n\n[^1]: Noot.\n"), "Titel")
        self.assertEqual(manuscript.title_of("\N{BYTE ORDER MARK}# Met bom\r\n"), "Met bom")
        self.assertIsNone(manuscript.title_of("Geen titel.\n"))
        self.assertIsNone(manuscript.title_of("## Kop\n"))
        self.assertIsNone(manuscript.title_of(""))
        self.assertIsNone(manuscript.title_of("#\n\nTekst.\n"))

    def test_parse_is_fast(self):
        words = "de zee was *stil* die avond en niemand sprak over wat er gebeurd was".split()
        parts, n = [], 0
        while n < 30000:
            para = []
            for _ in range(100):
                para.append(words[n % len(words)])
                n += 1
                if n % 200 == 0:
                    para[-1] += "^[Een noot met een paar woorden.]"
            parts.append(" ".join(para) + ".")
        md = "# Een lang stuk\n\n" + "\n\n".join(parts) + "\n"
        start = time.perf_counter()
        doc = manuscript.parse(md)
        out = manuscript.serialize(doc)
        elapsed = time.perf_counter() - start
        self.assertEqual(out, md)
        self.assertGreaterEqual(manuscript.counts(md)["words"], 30000)
        self.assertLess(elapsed, 2.0)


def item(style, level, start, *content):
    node = {"type": "list_item", "attrs": {"list": style, "level": level, "start": start}}
    if content:
        node["content"] = list(content)
    return node


def prose(*content):
    return {"type": "doc", "attrs": {"form": "prose"}, "content": list(content)}


class ListTest(unittest.TestCase):
    def assertCanonical(self, md, canonical=None):
        """`md` is written as `canonical`, which reads back as the same document."""
        canonical = md if canonical is None else canonical
        doc = manuscript.parse(md)
        self.assertEqual(manuscript.serialize(doc), canonical)
        self.assertEqual(manuscript.parse(canonical), doc)

    def test_list_documents(self):
        self.assertEqual(manuscript.parse("1. Een\n   - Sub\n2. Twee\n")["content"], [
            item("decimal", 0, None, text("Een")),
            item("bullet", 1, None, text("Sub")),
            item("decimal", 0, None, text("Twee")),
        ])
        self.assertEqual(manuscript.parse("3. Drie\n")["content"], [item("decimal", 0, 3, text("Drie"))])
        self.assertEqual(manuscript.parse("c. drie\n")["content"], [item("lower-alpha", 0, 3, text("drie"))])
        self.assertEqual(manuscript.parse("v. vijf\n")["content"], [item("lower-alpha", 0, 22, text("vijf"))])
        self.assertEqual(manuscript.parse("-\n")["content"], [item("bullet", 0, None)])
        self.assertEqual(manuscript.parse("0. Nul\n")["content"], [item("decimal", 0, 0, text("Nul"))])
        # an item is one paragraph: the item's other blocks follow it, and the next item keeps its number
        self.assertEqual(manuscript.parse("1. Een\n\n   Meer.\n\n2. Twee\n")["content"], [
            item("decimal", 0, None, text("Een")),
            {"type": "paragraph", "content": [text("Meer.")]},
            item("decimal", 0, 2, text("Twee")),
        ])

    def test_lists_normalise(self):
        cases = [
            ("* een\n+ twee\n", "- een\n- twee\n"),             # adjacent lists of one style are one list
            ("1) een\n2) twee\n", "1. een\n2. twee\n"),
            ("- een\n\n- twee\n", "- een\n- twee\n"),
            ("1. een\n1. twee\n1. drie\n", "1. een\n2. twee\n3. drie\n"),
            ("1. een\n\n   tweede alinea\n\n2. twee\n", "1. een\n\ntweede alinea\n\n2. twee\n"),
            ("1. een\n\n   > citaat\n\n2. twee\n", "1. een\n\n> citaat\n\n2. twee\n"),
            # where lists can't be, items keep their marker as text
            ("> - een\n> - twee\n", "> \\- een\n>\n> \\- twee\n"),
            ("> 1. een\n> 2) twee\n", "> 1\\. een\n>\n> 2\\. twee\n"),
            ("> a. een\n", "> a\\. een\n"),
            ("z. laatste\n", "z. laatste\n"),
        ]
        for md, canonical in cases:
            with self.subTest(md=md):
                self.assertCanonical(md, canonical)
        letters = prose(*[item("lower-alpha", 0, None, text(f"punt {k}")) for k in range(1, 29)])
        md = manuscript.serialize(letters)
        self.assertEqual([line.split(" ")[0] for line in md.splitlines()[-3:]], ["z.", "z.", "z."])
        self.assertEqual(manuscript.parse(md), letters)

    def test_list_edges_round_trip(self):
        for md in [
            "- Een\n\n  -\n- Twee\n",                  # a nested list starting with an empty item can't interrupt
            "1. Een\n\n   3. Drie\n",                    # ...nor one starting elsewhere than 1
            "-\n  3. Drie\n",                            # under an empty item there is nothing to interrupt
            "- Een\n  1. Sub\n  - Ander\n",              # a nested list of another style
            "1. Een\n\na) Twee\n",                       # ordered lists side by side at the top...
            "a. Een\n\ni) Twee\n\nA.  Drie\n",           # ...alternate their delimiter
            "a. Een\n\n- Twee\n\ni. Drie\n",             # (not across a bulleted list)
            "1. Een\n   a. Sub\n   i) Ander\n2. Twee\n   i. Diep\n",   # nested lists side by side; under another item
            "a. Een\n\nA) Twee\n   - Sub\n\nI.  Drie\n",  # a capital with `)` needs one space
            "0. Nul\n1. Een\n",                          # a list may start at 0
            "- Een\n\n  0. Nul\n",
            "A.  Een\n    - Sub\n",                      # nested items under the item's text
            "9. Negen\n10. Tien\n    - Sub\n",
            "- Een\\\n  a\\. geen lijst\n- a\\. ook geen\n",
            "- A. Einstein\n",
        ]:
            with self.subTest(md=md):
                self.assertCanonical(md)

    def test_v12_files_read_as_before(self):
        for md in ["I. Kant schreef.\n", "A. Einstein zei het.\n", "1\\. geen lijst\n", "\\- geen opsomming\n",
                   "Mr. Jansen kwam.\n"]:
            with self.subTest(md=md):
                content = manuscript.parse(md)["content"]
                self.assertEqual([n["type"] for n in content], ["paragraph"])
                self.assertEqual(manuscript.serialize(manuscript.parse(md)), md)
        # letters and roman numerals don't interrupt a paragraph outside a list: a line after a line break stays a line
        self.assertEqual(manuscript.parse("Een regel\\\na. een\n")["content"], [
            {"type": "paragraph", "content": [text("Een regel"), {"type": "hard_break"}, text("a. een")]}])
        self.assertEqual(manuscript.serialize(manuscript.parse("Een regel\\\na. een\n")), "Een regel\\\na\\. een\n")
        for md in ["Tekst\ni. een\n", "Tekst\nA.  een\n"]:
            with self.subTest(md=md):
                self.assertEqual([n["type"] for n in manuscript.parse(md)["content"]], ["paragraph"])
        # numbers and bullets keep CommonMark's rule, and inside a list letters interrupt too
        self.assertEqual([n["type"] for n in manuscript.parse("Tekst\n1. een\n- twee\n")["content"]],
                         ["paragraph", "list_item", "list_item"])
        self.assertEqual([n["type"] for n in manuscript.parse("- Tekst\n  a. een\n")["content"]],
                         ["list_item", "list_item"])

    def test_list_markers_escaped_at_line_starts(self):
        br = {"type": "hard_break"}
        for line, md in [
            ("a. geen lijst", "a\\. geen lijst"),
            ("iv. ook niet", "iv\\. ook niet"),
            ("(a) niet", "\\(a) niet"),
            ("(iv) niet", "\\(iv) niet"),
            ("(1) niet", "\\(1) niet"),
            ("A.  twee spaties", "A\\.  twee spaties"),
            ("A) haakje", "A\\) haakje"),
            ("II. Deel", "II\\. Deel"),
            ("A. een spatie", "A. een spatie"),
            ("e.g. zo", "e.g. zo"),
            ("iv.x", "iv.x"),
            ("Mr. Jansen", "Mr. Jansen"),
        ]:
            with self.subTest(line=line):
                paragraph = {"type": "paragraph", "content": [text(line)]}
                self.assertEqual(manuscript.serialize(prose(paragraph)), md + "\n")
                self.assertEqual(manuscript.parse(md + "\n")["content"], [paragraph])
                broken = {"type": "paragraph", "content": [text("Eerst"), br, text(line)]}
                self.assertEqual(manuscript.serialize(prose(broken)), "Eerst\\\n" + md + "\n")
                self.assertEqual(manuscript.parse("Eerst\\\n" + md + "\n")["content"], [broken])

    def test_lists_in_poems_stay_lines(self):
        self.assertEqual(manuscript.parse("- een\n- twee\n", "poem")["content"], [
            {"type": "paragraph", "content": [text("- een"), {"type": "hard_break"}, text("- twee")]}])

    def test_list_markers(self):
        doc = manuscript.parse("1. a\n   - b\n   - c\n2. d\n\nx\n\n- e\n")
        found = manuscript_lists.markers(doc["content"])
        self.assertEqual([m and m["marker"] for m in found], ["1.", "◦", "◦", "2.", None, "•"])
        self.assertEqual([m and m["first"] for m in found], [True, True, False, False, None, True])
        self.assertEqual([m and m["run"] for m in found], [0, 1, 1, 0, None, 5])
        deep = [item("bullet", level, None, text("x")) for level in (0, 2, 3)]
        self.assertEqual([m["level"] for m in manuscript_lists.markers(deep)], [0, 1, 2])

    def test_marker_helpers(self):
        L = manuscript_lists
        self.assertEqual(L.STYLES, ("bullet", "decimal", "lower-alpha", "upper-alpha", "lower-roman", "upper-roman"))
        self.assertEqual([L.to_alpha(n) for n in (1, 26, 27, 28)], ["a", "z", "aa", "ab"])
        self.assertEqual([L.to_roman(n) for n in (1, 4, 9, 14, 1990)], ["i", "iv", "ix", "xiv", "mcmxc"])
        self.assertEqual([L.from_roman(s) for s in ("i", "xiv", "MCMXC", "iiii", "Mr", "")],
                         [1, 14, 1990, None, None, None])
        self.assertEqual([L.marker_text("bullet", 1, level) for level in range(4)], ["•", "◦", "▪", "•"])
        self.assertEqual([L.marker_text(s, n, 0) for s, n in [("decimal", 1), ("lower-alpha", 1), ("upper-alpha", 1),
                                                                ("lower-roman", 4), ("upper-roman", 4)]],
                         ["1.", "a.", "A.", "iv.", "IV."])
        self.assertEqual([L.md_marker(s, n) for s, n in [("bullet", 1), ("decimal", 3), ("lower-alpha", 3),
                                                          ("upper-alpha", 3), ("lower-roman", 4), ("upper-roman", 4),
                                                          ("lower-alpha", 27)]],
                         ["- ", "3. ", "c. ", "C.  ", "iv. ", "IV.  ", "z. "])
        self.assertEqual([L.md_marker("upper-alpha", 3, ")"), L.md_marker("lower-roman", 4, ")")], ["C) ", "iv) "])

    def test_counts_include_lists(self):
        self.assertEqual(manuscript.counts("- een twee\n- drie\n")["words"], 3)
        self.assertEqual(manuscript.plain_text(manuscript.parse("- een\n- twee\n")), "een\n\ntwee")

    def test_starts_beyond_nine_digits_are_not_kept(self):
        """CommonMark reads at most nine digits: a larger start is dropped, the list starts at 1."""
        doc = prose(item("decimal", 0, 1234567890, text("Groot")))
        self.assertEqual(manuscript.serialize(doc), "1. Groot\n")
        self.assertEqual(manuscript.parse(manuscript.serialize(doc))["content"], [item("decimal", 0, None, text("Groot"))])
        doc = prose(item("decimal", 0, 999_999_999, text("Groot")))
        self.assertEqual(manuscript.serialize(doc), "999999999. Groot\n")
        self.assertEqual(manuscript.parse(manuscript.serialize(doc)), doc)

    def test_roman_starts_beyond_3999_are_not_kept(self):
        doc = prose(item("upper-roman", 0, 5000, text("Groot")))
        md = manuscript.serialize(doc)
        self.assertEqual(md, "I.  Groot\n")
        self.assertEqual(manuscript.parse(md)["content"], [item("upper-roman", 0, None, text("Groot"))])
        doc = prose(item("lower-roman", 0, 3999, text("Groot")))
        self.assertEqual(manuscript.parse(manuscript.serialize(doc)), doc)

    def test_normalize_import_shaped_blocks(self):
        """Blocks as an import makes them (no `_n`, any start, any level) come out as `parse` would give them."""
        between = {"type": "paragraph", "content": [text("Tussen")]}
        blocks = [
            item("decimal", 0, 3, text("drie")),            # starts a list at 3: kept
            item("decimal", 0, 7, text("vier")),            # continues it: its start is dropped
            item("bullet", 5, None, text("diep")),          # too deep: one deeper than the list above
            item("bullet", 0, 4, text("punt")),             # a bullet has no start
            between,
            item("decimal", 2, 1, text("een")),             # after a paragraph: level 0; start 1 is no start
            item("lower-alpha", 0, 0, text("nul")),         # another style starts a list; letters start at 1
        ]
        before = copy.deepcopy(blocks)
        self.assertEqual(manuscript_lists.normalize(blocks), [
            item("decimal", 0, 3, text("drie")),
            item("decimal", 0, None, text("vier")),
            item("bullet", 1, None, text("diep")),
            item("bullet", 0, None, text("punt")),
            between,
            item("decimal", 0, None, text("een")),
            item("lower-alpha", 0, None, text("nul")),
        ])
        self.assertEqual(blocks, before)                     # the input is left as it was


def aligned(align, *paragraphs):
    return {"type": "aligned", "attrs": {"align": align}, "content": list(paragraphs)}


def para(*content):
    node = {"type": "paragraph"}
    if content:
        node["content"] = list(content)
    return node


STRIKE, EM, SIZE = {"type": "strike"}, {"type": "em"}, lambda s: {"type": "size", "attrs": {"size": s}}


def texts_of(node):
    """Every text node's text in a document, notes included."""
    if node.get("type") == "text":
        yield node["text"]
    for c in node.get("content") or []:
        yield from texts_of(c)


class AlignmentAndMarksTest(unittest.TestCase):
    def assertCanonical(self, md, canonical=None, form="prose"):
        canonical = md if canonical is None else canonical
        doc = manuscript.parse(md, form)
        self.assertEqual(manuscript.serialize(doc), canonical)
        self.assertEqual(manuscript.serialize(manuscript.parse(canonical, form)), canonical)

    def test_aligned_documents(self):
        self.assertEqual(manuscript.parse("::: {.center}\nA\n:::\n")["content"],
                         [aligned("center", para(text("A")))])
        self.assertEqual(manuscript.parse("::: right\nA\n\nB\n:::\n")["content"],
                         [aligned("right", para(text("A")), para(text("B")))])
        # neighbouring fences with the same alignment read as one block (as they are written); nested ones apart
        self.assertEqual(manuscript.parse("::: center\nA\n:::\n\n::: center\nB\n:::\n")["content"],
                         [aligned("center", para(text("A")), para(text("B")))])
        self.assertEqual(manuscript.parse(":::: right\n::: center\nA\n:::\n\nB\n::::\n")["content"],
                         [aligned("center", para(text("A"))), aligned("right", para(text("B")))])
        # other blocks in the fence come out between aligned blocks, unaligned; a list is a real list
        self.assertEqual(manuscript.parse("::: center\nA\n\n- een\n- twee\n\nB\n:::\n")["content"], [
            aligned("center", para(text("A"))),
            item("bullet", 0, None, text("een")),
            item("bullet", 0, None, text("twee")),
            aligned("center", para(text("B"))),
        ])
        # the marks of the text inside are kept
        self.assertEqual(manuscript.parse("::: center\n*Schuin* en ~~weg~~\n:::\n")["content"],
                         [aligned("center", para(text("Schuin", EM), text(" en "), text("weg", STRIKE)))])
        self.assertEqual(manuscript.plain_text(manuscript.parse("::: center\nA\n\nB\n:::\n\nC\n")), "A\n\nB\n\nC")
        self.assertEqual(manuscript.counts("::: right\nDrie losse woorden\n:::\n")["words"], 3)

    def test_aligned_normalises(self):
        cases = [
            ("::: center\nA\n:::\n\n::: center\nB\n:::\n", "::: center\nA\n\nB\n:::\n"),
            ("::: center\nA\n\n## Kop\n\nB\n:::\n", "::: center\nA\n:::\n\n## Kop\n\n::: center\nB\n:::\n"),
            ("::: center\n:::\n", ""),
            ("::: {.right}\nA\n:::\n", "::: right\nA\n:::\n"),
            ("::: center\nA\n:::\n\n::: right\nB\n:::\n", "::: center\nA\n:::\n\n::: right\nB\n:::\n"),
            ("::: center\nA\n\n- een\n- twee\n\nB\n:::\n", "::: center\nA\n:::\n\n- een\n- twee\n\n::: center\nB\n:::\n"),
            ("::: left\nA\n:::\n", "A\n"),                   # "as the book" is the only other alignment
            # where alignment can't be, its paragraphs stay paragraphs
            ("> ::: center\n> A\n> :::\n", "> A\n"),
            (":::: epigraph\n::: center\nA\n:::\n::::\n", "::: epigraph\nA\n:::\n"),
        ]
        for md, canonical in cases:
            with self.subTest(md=md):
                self.assertCanonical(md, canonical)
        self.assertEqual(manuscript.parse("> ::: center\n> A\n> :::\n")["content"],
                         [{"type": "blockquote", "content": [para(text("A"))]}])
        # from the editor: neighbours with the same alignment are one fence; one without text is dropped
        self.assertEqual(manuscript.serialize(prose(aligned("center", para(text("A"))), aligned("center", para(text("B"))),
                                                    aligned("right", para(text("C"))))),
                         "::: center\nA\n\nB\n:::\n\n::: right\nC\n:::\n")
        self.assertEqual(manuscript.serialize(prose(aligned("center", para()), para(text("x")))), "x\n")
        self.assertEqual(manuscript.serialize(prose(aligned("left", para(text("x"))))), "x\n")

    def test_aligned_in_poem_pieces(self):
        """In a piece whose form is poem, `::: center` holds centred stanzas: its lines keep their line breaks."""
        doc = manuscript.parse("::: center\nregel een\nregel twee\n:::\n", "poem")
        self.assertEqual(doc["content"], [aligned("center", para(text("regel een"), {"type": "hard_break"},
                                                                 text("regel twee")))])
        self.assertEqual(manuscript.serialize(doc), "::: center\nregel een\nregel twee\n:::\n")
        self.assertEqual(manuscript.parse(manuscript.serialize(doc), "poem"), doc)
        self.assertCanonical("::: center\nregel een\n- regel twee\n\nstrofe twee\n:::\n",
                             "::: center\nregel een\n\\- regel twee\n\nstrofe twee\n:::\n", form="poem")

    def test_underline_documents(self):
        self.assertEqual(manuscript.parse("Een [woord]{.underline}.\n")["content"][0]["content"],
                         [text("Een "), text("woord", {"type": "underline"}), text(".")])
        self.assertEqual(manuscript.parse("Een ~~woord~~.\n")["content"][0]["content"],
                         [text("Een "), text("woord", STRIKE), text(".")])
        doc = manuscript.parse("[Alles]{.idx .comment .smallcaps .underline .large term=\"alles\" note=\"n\" lang=en}\n")
        self.assertEqual([m["type"] for m in doc["content"][0]["content"][0]["marks"]],
                         ["idx", "comment", "smallcaps", "lang", "underline", "size"])

    def test_unwritable_strike_degrades(self):
        """Strikethrough that Markdown can't write loses its mark at the edge (or entirely), like italic and bold:
        it never turns into printed tildes."""
        idx = {"type": "idx", "attrs": {"term": None}}
        cases = [
            ([text("x"), text("(y)", STRIKE), text("z")], "x(~~y~~)z\n"),
            ([text("x"), text("…", STRIKE), text("y")], "x…y\n"),
            ([text("een "), text("woord,", STRIKE), text("b")], "een ~~woord~~,b\n"),
            # a hard break, a note or a space at the edge of a strike run goes outside it
            ([text("a", STRIKE), {"type": "hard_break", "marks": [STRIKE]}, text("b")], "~~a~~\\\nb\n"),
            ([text("a", STRIKE), {"type": "note", "content": [text("n")], "marks": [STRIKE]}, text(" b")],
             "~~a~~^[n] b\n"),
            ([text("a "), text("b ", STRIKE), text("c")], "a ~~b~~ c\n"),
            # inside a span, around a span, crossing italics, in a note
            ([text("a "), text("b", STRIKE, idx), text(" c")], "a [~~b~~]{.idx} c\n"),
            ([text("a ", STRIKE), text("b", STRIKE, idx), text(" c", STRIKE)], "~~a [b]{.idx} c~~\n"),
            ([text("a ", EM), text("b", EM, STRIKE), text(" c", STRIKE)], None),
            ([text("x"), {"type": "note", "content": [text("("), text("y", STRIKE), text(")z")]}], "x^[(~~y~~)z]\n"),
            ([text("a", STRIKE), text("b", STRIKE, EM), text("c", EM), text("d")], None),
            ([text("a", EM), text("b", EM, STRIKE), text("c", STRIKE), text("d")], None),
        ]
        for content, expected in cases:
            document = prose(para(*content))
            md = manuscript.serialize(document)
            with self.subTest(md=md):
                if expected is not None:
                    self.assertEqual(md, expected)
                again = manuscript.parse(md)
                self.assertNotIn("~", manuscript.plain_text(again))
                self.assertNotIn("~", "".join(texts_of(again)))           # notes included
                self.assertEqual(manuscript.plain_text(again), manuscript.plain_text(document))
                self.assertEqual(manuscript.serialize(again), md)
        # a literal tilde is escaped, so `~~` typed as text stays text
        document = prose(para(text("a ~~b~~ c ~ d")))
        md = manuscript.serialize(document)
        self.assertEqual(md, "a \\~\\~b\\~\\~ c \\~ d\n")
        self.assertEqual(manuscript.parse(md), document)

    def test_strike_gives_way_first(self):
        """When runs Markdown can't write all at once are equally long, strikethrough is given up first: `~~` can't
        share a delimiter run with `*`, so dropping it lets the asterisks meet (`*b***c**`)."""
        strong = {"type": "strong"}
        cases = [
            # italic `b` next to bold struck `c`: before, the italics went first and the strike after it (`ab**c**d`)
            ([text("a"), text("b", EM), text("c", strong, STRIKE), text("d")], "a*b***c**d\n"),
            # a strike run around italics inside a word: the italics on `c` stay
            ([text("a"), text("b", STRIKE), text("c", EM, STRIKE), text("d")], "ab*c*d\n"),
        ]
        for content, expected in cases:
            document = prose(para(*content))
            md = manuscript.serialize(document)
            with self.subTest(md=md):
                self.assertEqual(md, expected)
                again = manuscript.parse(md)
                self.assertEqual(manuscript.serialize(again), md)
                printed = "".join(texts_of(again))
                self.assertNotIn("~", printed)
                self.assertNotIn("*", printed)
                self.assertEqual(manuscript.plain_text(again), manuscript.plain_text(document))
        marked = manuscript.parse("a*b***c**d\n")["content"][0]["content"]
        self.assertEqual(marked, [text("a"), text("b", EM), text("c", strong), text("d")])
        self.assertEqual(manuscript.parse("ab*c*d\n")["content"][0]["content"], [text("ab"), text("c", EM), text("d")])

    def test_size_is_one_per_text(self):
        doc = prose(para(text("groot", SIZE("large"))))
        md = manuscript.serialize(doc)
        self.assertEqual(md, "[groot]{.large}\n")
        self.assertEqual(manuscript.parse(md), doc)
        self.assertEqual(manuscript.parse(md)["content"][0]["content"][0]["marks"], [SIZE("large")])
        # one size per text: the first class counts; a size inside another size replaces it
        self.assertEqual(manuscript.parse("[tekst]{.small .large}\n")["content"][0]["content"],
                         [text("tekst", SIZE("small"))])
        self.assertEqual(manuscript.parse("[[klein]{.small} groot]{.large}\n")["content"][0]["content"],
                         [text("klein", SIZE("small")), text(" groot", SIZE("large"))])
        # a size the dialect doesn't have isn't written
        self.assertEqual(manuscript.serialize(prose(para(text("gewoon", SIZE("medium"))))), "gewoon\n")
        self.assertEqual(manuscript.parse("[gewoon]{.medium}\n")["content"][0]["content"], [text("gewoon")])


def cell(*content):
    node = {"type": "table_cell"}
    if content:
        node["content"] = list(content)
    return node


def row(*cells):
    return {"type": "table_row", "content": list(cells)}


def table(header, align, *rows):
    return {"type": "table", "attrs": {"header": header, "align": list(align)}, "content": list(rows)}


class TableTest(unittest.TestCase):
    def assertCanonical(self, md, canonical=None, form="prose"):
        """`md` is written as `canonical`, which reads back as the same document."""
        canonical = md if canonical is None else canonical
        doc = manuscript.parse(md, form)
        self.assertEqual(manuscript.serialize(doc), canonical)
        self.assertEqual(manuscript.parse(canonical, form), doc)

    def test_table_documents(self):
        self.assertEqual(manuscript.parse(SAMPLES[-3])["content"], [table(True, [None, "center"],
            row(cell(text("Jaar")), cell(text("Plaats"))),
            row(cell(text("1984")), cell(text("Utrecht"))),
            row(cell(text("1990")), cell(text("Gent", EM), {"type": "note", "content": [text("Een noot.")]})))])
        # an empty first row: the table has no header
        self.assertEqual(manuscript.parse(SAMPLES[-2])["content"],
                         [table(False, [None, "right"], row(cell(text("a")), cell(text("b"))))])
        # every alignment; a pipe escaped in a cell is text in that cell
        self.assertEqual(manuscript.parse("| a | b | c | d |\n| --- | :-- | :-: | --: |\n| x \\| y |  | z |  |\n")["content"],
                         [table(True, [None, "left", "center", "right"],
                                row(cell(text("a")), cell(text("b")), cell(text("c")), cell(text("d"))),
                                row(cell(text("x | y")), cell(), cell(text("z")), cell()))])
        self.assertEqual(manuscript.parse("Een pijp \\| in tekst.\n")["content"],
                         [para(text("Een pijp | in tekst."))])

    def test_empty_cells(self):
        for md in [
            "| Kop |  |\n| --- | --- |\n|  | b |\n",          # an empty header cell and an empty body cell
            "|  |  |\n| --- | --- |\n|  |  |\n",               # a table without any text
        ]:
            with self.subTest(md=md):
                self.assertCanonical(md)
        # a table that is only an empty header row keeps that row as its header
        self.assertEqual(manuscript.parse("|  |  |\n| --- | --- |\n")["content"], [table(True, [None, None], row(cell(), cell()))])
        self.assertCanonical("|  |  |\n| --- | --- |\n")
        # a table without any text (as the editor puts one in: a header row and two rows) keeps its header and its rows
        empty = table(True, [None, None, None], *[row(cell(), cell(), cell()) for _ in range(3)])
        md = manuscript.serialize(prose(empty))
        self.assertEqual(md, "|  |  |  |\n| --- | --- | --- |\n|  |  |  |\n|  |  |  |\n")
        self.assertEqual(manuscript.parse(md), prose(empty))
        # ...also with Header row off: its rows are written as they are (no empty header row put above them), so it reads
        # back with the header on and the same rows (coordinator's ruling: the toggle of a still-empty table comes back on)
        headless = table(False, [None, None, None], *[row(cell(), cell(), cell()) for _ in range(3)])
        self.assertEqual(manuscript.serialize(prose(headless)), md)
        self.assertEqual(manuscript.parse(manuscript.serialize(prose(headless))), prose(empty))
        # ...but an empty first row above text is no header
        self.assertEqual(manuscript.parse("|  |  |\n| --- | --- |\n|  | b |\n|  |  |\n")["content"],
                         [table(False, [None, None], row(cell(), cell(text("b"))), row(cell(), cell()))])

    def test_tables_normalise(self):
        cases = [
            ("a | b\n--|--\nc | d\n", "| a | b |\n| --- | --- |\n| c | d |\n"),
            ("| a | b |\n|:---|---:|\n", "| a | b |\n| :-- | --: |\n"),
            ("|a|b|\n|-|:-:|\n|*c*|d|\n", "| a | b |\n| --- | :-: |\n| *c* | d |\n"),
            # every row has the table's number of cells: a long row is cut, a short one filled
            ("| a | b |\n| --- | --- |\n| c | d | e |\n", "| a | b |\n| --- | --- |\n| c | d |\n"),
            ("| a | b |\n| --- | --- |\n| c |\n", "| a | b |\n| --- | --- |\n| c |  |\n"),
            ("| a |\n| --- |\n| x \\| y |\n", "| a |\n| --- |\n| x \\| y |\n"),
            # a table may interrupt a paragraph (Pandoc and GFM)
            ("Tekst\n| a |\n| --- |\n", "Tekst\n\n| a |\n| --- |\n"),
            # in a cell a line is one line: an image is its caption
            ("| a |\n| --- |\n| ![Foto](../images/a.jpg) |\n", "| a |\n| --- |\n| Foto |\n"),
            # where a table can't be it is a paragraph per row, its cells joined by ` | `
            ("> | a | b |\n> | --- | --- |\n> | c | d |\n", "> a \\| b\n>\n> c \\| d\n"),
            ("::: epigraph\n| a | b |\n| --- | --- |\n| c |  |\n:::\n", "::: epigraph\na \\| b\n\nc \\|\n:::\n"),
            ("Tekst.[^1]\n\n[^1]: | a | b |\n    | --- | --- |\n    | c | d |\n", "Tekst.^[a \\| b c \\| d]\n"),
            ("|  |  |\n| --- | --- |\n|  |  |\n\n> |  |\n> | --- |\n> |  |\n", "|  |  |\n| --- | --- |\n|  |  |\n"),
            # ...without spaces at its edges where an edge cell is empty
            ("> |  | d |\n> | --- | --- |\n> | c |  |\n", "> \\| d\n>\n> c \\|\n"),
            ("> | *a* |  |\n> | --- | --- |\n", "> *a* \\|\n"),
            ("Tekst.[^1]\n\n[^1]: | a | b |\n    | --- | --- |\n    |  | d |\n", "Tekst.^[a \\| b \\| d]\n"),
            ("> | c | d&#xA0; |\n> | --- | --- |\n", "> c \\| d\n"),        # a paragraph ends without a no-break space
            # aligned text around a table: the table comes out between, unaligned; an item's table follows the item
            ("::: center\nA\n\n| a |\n| --- |\n\nB\n:::\n", "::: center\nA\n:::\n\n| a |\n| --- |\n\n::: center\nB\n:::\n"),
            ("- Een\n\n  | a |\n  | --- |\n", "- Een\n\n| a |\n| --- |\n"),
        ]
        for md, canonical in cases:
            with self.subTest(md=md):
                out = manuscript.serialize(manuscript.parse(md))
                self.assertEqual(out, canonical)
                self.assertEqual(manuscript.serialize(manuscript.parse(out)), canonical)
                self.assertEqual(manuscript.parse(out), manuscript.parse(md))     # the document, not only its Markdown

    def test_tables_in_poems_stay_lines(self):
        """In a piece whose form is poem, and inside `::: poem`, table lines are lines of the poem."""
        br = {"type": "hard_break"}
        self.assertEqual(manuscript.parse("| a |\n| --- |\n", "poem")["content"],
                         [para(text("| a |"), br, text("| --- |"))])
        self.assertCanonical("| a |\n| --- |\n", "\\| a \\|\n\\| --- \\|\n", form="poem")
        self.assertEqual(manuscript.parse("::: poem\n| a |\n| --- |\n:::\n")["content"],
                         [{"type": "poem", "attrs": {"src": None}, "content": [para(text("| a |"), br, text("| --- |"))]}])

    def test_table_writing(self):
        """Tables from the editor are written as pipe tables that read back as the same table."""
        br = {"type": "hard_break"}
        comment = {"type": "comment", "attrs": {"note": "een | twee"}}
        def cite_with(locator):
            return {"type": "cite", "attrs": {"items": [{"key": "bron", "prefix": "", "locator": locator}]}}
        cite = cite_with("p. 3|4")
        cases = [
            # no header: an empty first row; alignments; unknown alignments are none
            (table(False, ["left", "justify"], row(cell(text("a")), cell(text("b")))),
             "|  |  |\n| :-- | --- |\n| a | b |\n",
             table(False, ["left", None], row(cell(text("a")), cell(text("b"))))),
            # a line break in a cell's note is a space (a pipe table row is one line); spaces at a cell's edges go
            (table(True, [None], row(cell(text("Kop"))),
                   row(cell(text(" x"), {"type": "note", "content": [text("een"), br, text("twee")]}, text(" ")))),
             "| Kop |\n| --- |\n| x^[een twee] |\n",
             table(True, [None], row(cell(text("Kop"))), row(cell(text("x"), {"type": "note", "content": [text("een twee")]})))),
            # a pipe in text, in a comment and in a citation: escaped everywhere
            (table(True, [None, None], row(cell(text("a|b")), cell(text("c", comment), cite))),
             "| a\\|b | [c]{.comment note=\"een \\| twee\"}[@bron, p. 3\\|4] |\n| --- | --- |\n",
             table(True, [None, None], row(cell(text("a|b")), cell(text("c", comment), cite)))),
            # a backslash in a citation, also right before a pipe
            (table(True, [None], row(cell(cite_with("a\\|b \\c")))), "| [@bron, a\\\\\\|b \\\\c] |\n| --- |\n",
             table(True, [None], row(cell(cite_with("a\\|b \\c"))))),
            # no-break and other wide spaces at a cell's edges are kept, as entities (markdown-it trims them from cells)
            (table(True, [None, None], row(cell(text("\N{NO-BREAK SPACE}x\N{NO-BREAK SPACE}")),
                                           cell(text(" \t\N{IDEOGRAPHIC SPACE}y\N{NARROW NO-BREAK SPACE} "))),
                   row(cell(text("\N{NO-BREAK SPACE}\N{NO-BREAK SPACE}z")), cell(text("w\N{NO-BREAK SPACE}", EM)))),
             "| &#xA0;x&#xA0; | &#x3000;y&#x202F; |\n| --- | --- |\n| &#xA0;\N{NO-BREAK SPACE}z | *w*&#xA0; |\n",
             table(True, [None, None], row(cell(text("\N{NO-BREAK SPACE}x\N{NO-BREAK SPACE}")),
                                           cell(text("\N{IDEOGRAPHIC SPACE}y\N{NARROW NO-BREAK SPACE}"))),
                   row(cell(text("\N{NO-BREAK SPACE}\N{NO-BREAK SPACE}z")), cell(text("w", EM), text("\N{NO-BREAK SPACE}"))))),
            # a row with more cells than `align` says widens the table: no text is lost
            (table(True, [None], row(cell(text("a"))), row(cell(text("b")), cell(text("c")))),
             "| a |  |\n| --- | --- |\n| b | c |\n",
             table(True, [None, None], row(cell(text("a")), cell()), row(cell(text("b")), cell(text("c"))))),
            # a backslash at a cell's end stays text
            (table(True, [None], row(cell(text("a\\")))), "| a\\\\ |\n| --- |\n", table(True, [None], row(cell(text("a\\"))))),
        ]
        for document, md, back in cases:
            with self.subTest(md=md):
                self.assertEqual(manuscript.serialize(prose(document)), md)
                self.assertEqual(manuscript.parse(md)["content"], [back])
                self.assertEqual(manuscript.serialize(manuscript.parse(md)), md)
        # a table without rows or cells is not written
        self.assertEqual(manuscript.serialize(prose(table(True, []), para(text("x")))), "x\n")
        self.assertEqual(manuscript.serialize(prose({"type": "table", "attrs": {"header": True, "align": [None]},
                                                     "content": [row()]})), "")

    def test_pipes_in_text_stay_text(self):
        """`|` is written `\\|` everywhere, and a line that would make a paragraph a table is escaped."""
        br = {"type": "hard_break"}
        for content, md in [
            ([text("a | b")], "a \\| b\n"),
            ([text("a | b"), br, text(":-")], "a \\| b\\\n\\:-\n"),
            ([text("a | b"), br, text(":--:")], "a \\| b\\\n\\:--:\n"),
            ([text("a | b"), br, text("|---|")], "a \\| b\\\n\\|---\\|\n"),
            ([text("a | b"), br, text(":-) ja")], "a \\| b\\\n:-) ja\n"),
        ]:
            with self.subTest(md=md):
                document = prose(para(*content))
                self.assertEqual(manuscript.serialize(document), md)
                self.assertEqual(manuscript.parse(md), document)
        item_doc = prose(item("bullet", 0, None, text("a | b"), br, text(":-")))
        self.assertEqual(manuscript.serialize(item_doc), "- a \\| b\\\n  \\:-\n")
        self.assertEqual(manuscript.parse(manuscript.serialize(item_doc)), item_doc)
        quote = prose({"type": "blockquote", "content": [para(text("a | b"), br, text(":-"))]})
        self.assertEqual(manuscript.parse(manuscript.serialize(quote)), quote)

    def test_pipes_and_backslashes_in_citations(self):
        """A citation's prefix, key and locator keep `|` and `\\`: written `\\|` and `\\\\`, read back."""
        def cited(prefix, key, locator):
            return prose(para(text("Zie "), {"type": "cite", "attrs": {"items": [
                {"key": key, "prefix": prefix, "locator": locator}]}}))
        for document, md in [
            (cited("", "bron", "p. 3|4"), "Zie [@bron, p. 3\\|4]\n"),
            (cited("a|b", "bron", "c\\d"), "Zie [a\\|b @bron, c\\\\d]\n"),
            (cited("", "x|y", "a\\|b"), "Zie [@{x\\|y}, a\\\\\\|b]\n"),
        ]:
            with self.subTest(md=md):
                self.assertEqual(manuscript.serialize(document), md)
                self.assertEqual(manuscript.parse(md), document)
        # as written by hand or by v1.2: a bare pipe or backslash in a citation reads as itself
        for md, locator, canonical in [("Zie [@bron, p. 3|4]\n", "p. 3|4", "Zie [@bron, p. 3\\|4]\n"),
                                       ("Zie [@bron, p. 3\\4]\n", "p. 3\\4", "Zie [@bron, p. 3\\\\4]\n")]:
            with self.subTest(md=md):
                self.assertEqual(manuscript.parse(md), cited("", "bron", locator))
                self.assertEqual(manuscript.serialize(manuscript.parse(md)), canonical)

    def test_counts_include_tables(self):
        self.assertEqual(manuscript.counts("| een twee |\n| --- |\n| drie |\n")["words"], 3)
        self.assertEqual(manuscript.counts(SAMPLES[-3]), {"words": 6, "note_words": 2, "notes": 1})
        self.assertEqual(manuscript.plain_text(manuscript.parse("Voor.\n\n| a | b |\n| --- | --- |\n| c |  |\n")),
                         "Voor.\n\na | b\n\nc | ")


def math(tex, *marks):
    node = {"type": "math", "attrs": {"tex": tex}}
    if marks:
        node["marks"] = list(marks)
    return node


def display(tex):
    return {"type": "math_display", "attrs": {"tex": tex}}


def note(*content):
    return {"type": "note", "content": list(content)}


class MathTest(unittest.TestCase):
    def assertCanonical(self, md, canonical=None, form="prose"):
        """`md` is written as `canonical`, which reads back as the same document."""
        canonical = md if canonical is None else canonical
        doc = manuscript.parse(md, form)
        self.assertEqual(manuscript.serialize(doc), canonical)
        self.assertEqual(manuscript.parse(canonical, form), doc)

    def test_math_documents(self):
        self.assertEqual(manuscript.parse("Einstein schreef $E = mc^2$ en meer.\n")["content"],
                         [para(text("Einstein schreef "), math("E = mc^2"), text(" en meer."))])
        self.assertEqual(manuscript.parse("Een formule:\n\n$$\n\\int_0^1 x^2 \\, dx = \\frac{1}{3}\n$$\n\nEn verder.\n")
                         ["content"], [para(text("Een formule:")), display("\\int_0^1 x^2 \\, dx = \\frac{1}{3}"),
                                       para(text("En verder."))])
        # display math keeps its lines and their indentation, not the blank space around it
        self.assertEqual(manuscript.parse("$$\n\\begin{aligned}\n  a &= b \\\\\n  c &= d\n\\end{aligned}\n$$\n")["content"],
                         [display("\\begin{aligned}\n  a &= b \\\\\n  c &= d\n\\end{aligned}")])
        # a literal dollar is text; inside math `\$` is TeX's own
        self.assertEqual(manuscript.parse("Het kost \\$20 of \\$30.\n")["content"], [para(text("Het kost $20 of $30."))])
        self.assertEqual(manuscript.parse("Prijs $a\\$b$.\n")["content"][0]["content"],
                         [text("Prijs "), math("a\\$b"), text(".")])
        # inline math sits in any text: the title, headings, items, notes, cells, spans; it keeps the marks around it
        self.assertEqual(manuscript.parse("# Titel $t$\n\n## Kop $k$\n\n- Punt $p$^[Noot $n$.]\n")["content"], [
            {"type": "title", "content": [text("Titel "), math("t")]},
            {"type": "heading", "attrs": {"level": 2}, "content": [text("Kop "), math("k")]},
            item("bullet", 0, None, text("Punt "), math("p"), note(text("Noot "), math("n"), text(".")))])
        self.assertEqual(manuscript.parse("| a |\n| --- |\n| $x$ |\n")["content"],
                         [table(True, [None], row(cell(text("a"))), row(cell(math("x"))))])
        self.assertEqual(manuscript.parse("*a $x$ b* en [$y$]{.idx}\n")["content"][0]["content"],
                         [text("a ", EM), math("x", EM), text(" b", EM), text(" en "),
                          math("y", {"type": "idx", "attrs": {"term": None}})])
        # in poems: inline math in the lines, display math between stanzas in a poem piece
        br = {"type": "hard_break"}
        self.assertEqual(manuscript.parse("Regel $x$\nregel twee\n\n$$\ny\n$$\n", "poem")["content"],
                         [para(text("Regel "), math("x"), br, text("regel twee")), display("y")])
        self.assertEqual(manuscript.parse("::: poem\nRegel $x$\n:::\n")["content"],
                         [{"type": "poem", "attrs": {"src": None}, "content": [para(text("Regel "), math("x"))]}])

    def test_math_round_trip(self):
        for md, form in [
            ("Zie [@bron, p. 3]$x$^[Noot $y$.] en [$z$]{.idx}.\n", "prose"),
            ("[a]{.comment note=\"kost $5\"} en $x$.\n", "prose"),
            ("*a $x$ b* en **c$y$d**\n", "prose"),
            ("$x$ aan het begin\\\n$y$ na een harde regel\n", "prose"),
            ("2$\\pi$ rad\n", "prose"),
            ("$a$$b$\n", "prose"),
            ("# Titel $t$\n\n- Punt $p$\n\n$$\nq\n$$\n\n1. Een\n", "prose"),
            ("| $a$ | b^[$c$] |\n| --- | --- |\n", "prose"),
            ("Regel $x$\nregel $y$\n\n$$\nz\n$$\n\nStrofe\n", "poem"),
        ]:
            with self.subTest(md=md):
                self.assertCanonical(md, form=form)

    def test_math_normalise(self):
        cases = [
            # Pandoc's rules: an opening `$` has a non-space after it, a closing one a non-space before it and no digit
            # after it; otherwise the dollars are text
            ("Het kost $20 en $30.\n", "Het kost \\$20 en \\$30.\n"),
            ("$ x $\n", "\\$ x \\$\n"),
            ("$x $ en\n", "\\$x \\$ en\n"),
            ("Prijs: $x$5\n", "Prijs: \\$x\\$5\n"),
            ("Een $\n", "Een \\$\n"),
            # a line break in inline math is a space
            ("$a\nb$\n", "$a b$\n"),
            # display math on one line, with spaces; a blank line inside it ends it (it is text then)
            ("$$x$$\n", "$$\nx\n$$\n"),
            ("$$ a = b $$\n", "$$\na = b\n$$\n"),
            ("$$\na\n\nb\n$$\n", "\\$\\$ a\n\nb \\$\\$\n"),
            ("Tekst\n$$ geen formule\nmeer\n", "Tekst \\$\\$ geen formule meer\n"),
            # display math interrupts a paragraph: text, display math, text
            ("Hieruit volgt\n$$\nx = 1\n$$\nen dus.\n", "Hieruit volgt\n\n$$\nx = 1\n$$\n\nen dus.\n"),
            # a single dollar in display math stays; only dollars side by side are `\$` (they would end it)
            ("$$$ geld $$$\n", "$$\n$ geld $\n$$\n"),
            ("$$\na$b\n$$\n", "$$\na$b\n$$\n"),
            # where display math can't be (quotations, epigraphs), it is inline math in a paragraph, as inline math is
            # written (a lone backslash at its end goes, a dollar is `\$`); in a fence or a list item it comes out
            # after it
            ("> $$\n> x\n> y\n> $$\n", "> $x y$\n"),
            ("> $$\n> a \\\n> $$\n", "> $a$\n"),
            ("> $$\n> a$b\n> $$\n", "> $a\\$b$\n"),
            ("> $$\n> \\\n> $$\n", ""),
            ("::: epigraph\n$$\nx\n$$\n:::\n", "::: epigraph\n$x$\n:::\n"),
            ("::: center\nA\n\n$$\nx\n$$\n:::\n", "::: center\nA\n:::\n\n$$\nx\n$$\n"),
            ("- Een\n\n  $$\n  x\n  $$\n", "- Een\n\n$$\nx\n$$\n"),
            ("Tekst.[^1]\n\n[^1]: $$\n    x\n    $$\n", "Tekst.^[$x$]\n"),
            # an image's caption is text: its math too
            ("![Formule $x$](../images/a.jpg)\n", "![Formule \\$x\\$](../images/a.jpg)\n"),
            # in a cell a pipe can only be written `\|` (a bare one ends the cell), and markdown-it drops that backslash:
            # math's `\|` is TeX's `\|`, written `\Vert`, which no table reads as a cell's end; in a note too
            ("| a |\n| --- |\n| $\\|x\\|$ |\n", "| a |\n| --- |\n| $\\Vert x\\Vert$ |\n"),
            ("| a |\n| --- |\n| b^[$\\|y\\|+1$] |\n", "| a |\n| --- |\n| b^[$\\Vert y\\Vert+1$] |\n"),
        ]
        for md, canonical in cases:
            with self.subTest(md=md):
                out = manuscript.serialize(manuscript.parse(md))
                self.assertEqual(out, canonical)
                self.assertEqual(manuscript.serialize(manuscript.parse(out)), canonical)
                self.assertEqual(manuscript.parse(out), manuscript.parse(md))     # the document, not only its Markdown
        self.assertEqual(manuscript.parse("$ x $\n")["content"], [para(text("$ x $"))])
        self.assertEqual(manuscript.parse("Het kost $20 en $30.\n")["content"], [para(text("Het kost $20 en $30."))])
        self.assertEqual(manuscript.parse("Hieruit volgt\n$$\nx = 1\n$$\nen dus.\n")["content"],
                         [para(text("Hieruit volgt")), display("x = 1"), para(text("en dus."))])
        self.assertEqual(manuscript.parse("| a |\n| --- |\n| $\\|v\\|$ |\n")["content"][0]["content"][1],
                         row(cell(math("\\Vert v\\Vert"))))

    def test_dollars_in_tex_stay_tex(self):
        """Only a dollar that would end the math is `\\$`: in display math dollars side by side, in inline math any
        dollar outside `\\text{…}` (where Pandoc reads balanced braces as they are). TeX like this is written as it
        is, and reads back the same."""
        for md, tex, block in [
            ("$$\nx = 1 \\quad \\text{if $y>0$}\n$$\n", "x = 1 \\quad \\text{if $y>0$}", True),
            ("$$\na$b\n$$\n", "a$b", True),
            ("Zie $a \\text{ als $b$ } c$.\n", "a \\text{ als $b$ } c", False),
            ("Zie $\\text{a {b $c$} d}+\\text{$e$}$.\n", "\\text{a {b $c$} d}+\\text{$e$}", False),
            ("Zie $\\text{a \\$ b}$.\n", "\\text{a \\$ b}", False),
        ]:
            with self.subTest(md=md):
                self.assertCanonical(md)
                doc = manuscript.parse(md)
                self.assertEqual(doc["content"][0]["attrs"]["tex"] if block else doc["content"][0]["content"][1]["attrs"]["tex"], tex)
        # from the editor
        for node, md, back in [
            (display("a$$b"), "$$\na\\$\\$b\n$$\n", display("a\\$\\$b")),
            (display("\\$$ en $$$"), "$$\n\\$\\$ en \\$\\$\\$\n$$\n", display("\\$\\$ en \\$\\$\\$")),
            (para(math("\\text{$x$} $y")), "$\\text{$x$} \\$y$\n", para(math("\\text{$x$} \\$y"))),
            (para(math("\\textbf{$x$}")), "$\\textbf{\\$x\\$}$\n", para(math("\\textbf{\\$x\\$}"))),
            # a `\text{` that doesn't close in the TeX is `\text {` (the same in TeX), so the `}` after it closes nothing
            (para(math("\\text{a $"), text(" b}")), "$\\text {a \\$$ b}\n", para(math("\\text {a \\$"), text(" b}"))),
        ]:
            with self.subTest(md=md):
                self.assertEqual(manuscript.serialize(prose(node)), md)
                self.assertEqual(manuscript.parse(md)["content"], [back])
                self.assertEqual(manuscript.serialize(manuscript.parse(md)), md)

    def test_math_writing(self):
        """Math from the editor is written so that it reads back as itself (or the nearest TeX that can be written)."""
        br = {"type": "hard_break"}
        cases = [
            # a `$` in TeX is `\$`, TeX's literal dollar; a line break a space; spaces at its ends go
            ([math("a$b")], "$a\\$b$\n", [math("a\\$b")]),
            ([math("a\\$b")], "$a\\$b$\n", None),
            ([math("\\\\$")], "$\\\\\\$$\n", [math("\\\\\\$")]),
            ([math("a\nb")], "$a b$\n", [math("a b")]),
            ([math("a\r\nb\rc")], "$a b c$\n", [math("a b c")]),
            ([text("x "), math("  y\N{NO-BREAK SPACE}"), text(" z")], "x $y$ z\n", [text("x "), math("y"), text(" z")]),
            # a lone backslash at its end would escape the closing dollar: it goes
            ([math("x\\")], "$x$\n", [math("x")]),
            ([math("x \\")], "$x$\n", [math("x")]),
            ([math("x\\\\")], "$x\\\\$\n", None),
            # empty math isn't written
            ([text("a "), math(" "), text("b")], "a b\n", [text("a b")]),
            ([math("")], "", []),
            # a digit right after the closing dollar would make it text: the digit is an entity
            ([math("x"), text("5 keer")], "$x$&#x35; keer\n", None),
            ([text("2"), math("\\pi")], "2$\\pi$\n", None),
            ([math("a"), math("b")], "$a$$b$\n", None),
            # a dollar or a backslash in the text before it
            ([text("kost $"), math("x")], "kost \\$$x$\n", None),
            ([text("a\\"), math("x")], "a\\\\$x$\n", None),
            ([math("x"), text("$")], "$x$\\$\n", None),
            # math at the start and a backslash at the end (dollarmath's own rule took that first dollar as escaped)
            ([math("x"), text(" a\\")], "$x$ a\\\\\n", None),
            ([math("\\\\"), text("\\")], "$\\\\$\\\\\n", None),
            # marks: math inside an italic run stays in it; at its edge it is left out, like a citation
            ([text("a ", EM), math("x", EM), text(" b", EM)], "*a $x$ b*\n", None),
            ([text("a ", EM), math("x", EM)], "*a* $x$\n", [text("a", EM), text(" "), math("x")]),
            # at a line start, after a hard break
            ([text("a"), br, math("x"), text(" b")], "a\\\n$x$ b\n", None),
        ]
        for content, md, back in cases:
            document = prose(para(*content))
            with self.subTest(md=md):
                self.assertEqual(manuscript.serialize(document), md)
                again = manuscript.parse(md)
                self.assertEqual(again.get("content", []), [para(*(content if back is None else back))] if md else [])
                self.assertEqual(manuscript.serialize(again), md)

    def test_display_math_writing(self):
        cases = [
            # blank lines inside collapse (Pandoc can't hold them); spaces at line ends go; dollars side by side are
            # `\$` (a single one stays)
            (display("a\n\n  \nb  "), "$$\na\nb\n$$\n", display("a\nb")),
            (display("  \\sum\n    x\n"), "$$\n\\sum\n  x\n$$\n", display("\\sum\n  x")),     # indentation kept relative
            (display("a$b\n$$"), "$$\na$b\n\\$\\$\n$$\n", display("a$b\n\\$\\$")),
        ]
        for node, md, back in cases:
            with self.subTest(md=md):
                self.assertEqual(manuscript.serialize(prose(node)), md)
                self.assertEqual(manuscript.parse(md)["content"], [back])
                self.assertEqual(manuscript.serialize(manuscript.parse(md)), md)
        # empty display math isn't written
        self.assertEqual(manuscript.serialize(prose(display(" \n "), para(text("x")))), "x\n")
        # between list items and in a poem piece
        doc = prose(item("bullet", 0, None, text("a")), display("x"), item("decimal", 0, None, text("b")))
        self.assertEqual(manuscript.serialize(doc), "- a\n\n$$\nx\n$$\n\n1. b\n")
        self.assertEqual(manuscript.parse(manuscript.serialize(doc)), doc)
        poem = {"type": "doc", "attrs": {"form": "poem"}, "content": [para(text("regel")), display("x")]}
        self.assertEqual(manuscript.serialize(poem), "regel\n\n$$\nx\n$$\n")
        self.assertEqual(manuscript.parse(manuscript.serialize(poem), "poem"), poem)

    def test_math_in_tables(self):
        """A table cell's math has no pipe in it: `|` is written `\\vert`, `\\|` `\\Vert` (the same symbols in TeX)."""
        cases = [
            (cell(math("|x|")), "| $\\vert x\\vert$ |\n| --- |\n", cell(math("\\vert x\\vert"))),
            (cell(math("\\|v\\| + a|b")), "| $\\Vert v\\Vert + a\\vert b$ |\n| --- |\n",
             cell(math("\\Vert v\\Vert + a\\vert b"))),
            (cell(math("\\\\|1|")), "| $\\\\\\vert1\\vert$ |\n| --- |\n", cell(math("\\\\\\vert1\\vert"))),
            (cell(text("n"), note(math("|y|"))), "| n^[$\\vert y\\vert$] |\n| --- |\n", cell(text("n"), note(math("\\vert y\\vert")))),
        ]
        for node, md, back in cases:
            with self.subTest(md=md):
                self.assertEqual(manuscript.serialize(prose(table(True, [None], row(node)))), md)
                self.assertEqual(manuscript.parse(md)["content"], [table(True, [None], row(back))])
                self.assertEqual(manuscript.serialize(manuscript.parse(md)), md)
        # outside a table a pipe in math stays as it is
        self.assertCanonical("Een norm $|x|$.\n")
        # a note defined outside the table keeps its pipes, as `\vert` in the cell it is written into
        md = "| a |\n| --- |\n| b[^1] |\n\n[^1]: $|z|$\n"
        self.assertEqual(manuscript.parse(md)["content"][0]["content"][1], row(cell(text("b"), note(math("|z|")))))
        self.assertEqual(manuscript.serialize(manuscript.parse(md)), "| a |\n| --- |\n| b^[$\\vert z\\vert$] |\n")

    def test_math_and_citations(self):
        """A `]` in math doesn't end a citation's bracket (nor make a citation of a span's text); a `$` in a citation is
        `\\$`, so it opens no math."""
        idx = {"type": "idx", "attrs": {"term": None}}
        doc = prose(para(math("x]@y", idx), text(" en")))
        self.assertEqual(manuscript.serialize(doc), "[$x]@y$]{.idx} en\n")
        self.assertEqual(manuscript.parse("[$x]@y$]{.idx} en\n"), doc)

        def cited(locator, *after):
            return prose(para(text("Zie "), {"type": "cite", "attrs": {"items": [
                {"key": "bron", "prefix": "", "locator": locator}]}}, *after))
        for document, md in [
            (cited("$5", text(" en"), math("y")), "Zie [@bron, \\$5] en$y$\n"),
            (cited("p. $3$"), "Zie [@bron, p. \\$3\\$]\n"),
            (cited("a\\$"), "Zie [@bron, a\\\\\\$]\n"),
        ]:
            with self.subTest(md=md):
                self.assertEqual(manuscript.serialize(document), md)
                self.assertEqual(manuscript.parse(md), document)
        # math inside a citation's bracket, written by hand, is its text there
        self.assertEqual(manuscript.parse("Zie [@bron, $a]b$].\n")["content"][0]["content"][1]["attrs"]["items"],
                         [{"key": "bron", "prefix": "", "locator": "$a]b$"}])

    def test_math_is_not_words(self):
        self.assertEqual(manuscript.counts("De som $a+b$ klopt.\n")["words"], 3)
        self.assertEqual(manuscript.counts("Een formule:\n\n$$\na + b + c\n$$\n")["words"], 2)
        self.assertEqual(manuscript.counts("Tekst^[Een $x$ noot.]\n"), {"words": 1, "note_words": 2, "notes": 1})
        self.assertEqual(manuscript.plain_text(manuscript.parse("Som $a$ hier.\n\n$$\nb\n$$\n")), "Som  hier.")
        self.assertEqual(manuscript.title_of("# Titel $x$\n"), "Titel")


if __name__ == "__main__":
    unittest.main()
