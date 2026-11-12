"""The manuscript dialect: Markdown pieces to editor documents (ProseMirror JSON) and back."""
import time
import unittest

from studio import manuscript

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
        self.assertEqual(manuscript.SCHEMA["marks"], ["em", "strong", "idx", "comment", "smallcaps", "lang"])

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
            ("- een\n- twee\n", "\\- een\n\n\\- twee\n"),
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
            manuscript.serialize({"type": "doc", "content": [{"type": "table"}]})

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


if __name__ == "__main__":
    unittest.main()
