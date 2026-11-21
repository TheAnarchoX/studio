"""Citations and bibliography entries: one formatter for the PDF composer and the .docx export."""
import unittest

from studio import book_export, citations, manuscript

DIJK = {"id": "d", "type": "book", "title": "Zee", "publisher": "Querido",
        "author": [{"family": "Dijk", "given": "Anna", "non-dropping-particle": "van"}],
        "issued": {"date-parts": [[2019]]}}
BAKKER = {"id": "b", "type": "book", "title": "Land", "author": [{"family": "Bakker", "given": "Jos"}],
          "issued": {"date-parts": [[2020]]}}


def person(family, given="Piet", particle=None):
    p = {"family": family, "given": given}
    if particle:
        p["non-dropping-particle"] = particle
    return p


class CitationsTest(unittest.TestCase):
    def test_particles_cited_and_sorted(self):
        self.assertEqual(citations.cite_text([{"key": "d"}], [DIJK]), "(van Dijk 2019)")
        self.assertEqual(citations.cited_name(DIJK["author"][0]), "van Dijk")
        self.assertEqual(citations.sort_key(DIJK)[0], "dijk")
        self.assertLess(citations.sort_key(BAKKER), citations.sort_key(DIJK))

    def test_prefix_locator_and_styles(self):
        item = [{"key": "d", "prefix": "see", "locator": "p. 12"}]
        self.assertEqual(citations.cite_text(item, [DIJK]), "(see van Dijk 2019, p. 12)")
        self.assertEqual(citations.cite_text(item, [DIJK], style="apa"), "(see van Dijk, 2019, p. 12)")

    def test_several_items_and_authors(self):
        self.assertEqual(citations.cite_text([{"key": "d"}, {"key": "b"}], [DIJK, BAKKER]),
                         "(van Dijk 2019; Bakker 2020)")
        two = dict(DIJK, author=[person("Dijk", particle="van"), person("Jansen")])
        self.assertEqual(citations.cite_text([{"key": "d"}], [two]), "(van Dijk and Jansen 2019)")
        self.assertEqual(citations.cite_text([{"key": "d"}], [two], style="apa"), "(van Dijk & Jansen, 2019)")
        four = dict(DIJK, author=[person("Dijk", particle="van")] + [person(n) for n in ("Jansen", "Berg", "Wit")])
        self.assertEqual(citations.cite_text([{"key": "d"}], [four]), "(van Dijk et al. 2019)")
        nod = dict(two, issued=None)
        nod.pop("issued")
        self.assertEqual(citations.cite_text([{"key": "d"}], [nod], lang="nl"), "(van Dijk en Jansen z.j.)")
        self.assertEqual(citations.cite_text([{"key": "d"}], [nod]), "(van Dijk and Jansen n.d.)")

    def test_unknown_key_stands_for_itself(self):
        self.assertEqual(citations.cite_text([{"key": "nope"}], []), "(nope)")

    def test_entry_types(self):
        runs = citations.entry(DIJK)
        self.assertEqual("".join(t for t, _ in runs), "Dijk, Anna van. 2019. Zee. Querido.")
        self.assertEqual([t for t, i in runs if i], ["Zee"])
        self.assertEqual("".join(t for t, _ in citations.entry(DIJK, "apa")), "Dijk, A. van. (2019). Zee. Querido.")

        art = {"id": "a", "type": "article-journal", "title": "Titel", "container-title": "Tijdschrift",
               "volume": "3", "issue": "2", "page": "45–67",
               "author": [{"family": "Dijk", "given": "Anna", "non-dropping-particle": "van"}],
               "issued": {"date-parts": [[2019]]}}
        runs = citations.entry(art)
        self.assertEqual("".join(t for t, _ in runs), "Dijk, Anna van. 2019. “Titel.” Tijdschrift 3 (2): 45–67.")
        self.assertEqual([t for t, i in runs if i], ["Tijdschrift"])

        chap = {"id": "c", "type": "chapter", "title": "Deel", "container-title": "Bundel", "page": "10–20",
                "author": [person("Bakker", "Jos")], "editor": [person("Jansen", "Piet")],
                "issued": {"date-parts": [[2018]]}}
        text = "".join(t for t, _ in citations.entry(chap))
        self.assertIn("In ", text)
        self.assertIn("edited by Piet Jansen", text)
        self.assertIn("onder redactie van", "".join(t for t, _ in citations.entry(chap, lang="nl")))

        web = {"id": "w", "type": "webpage", "title": "Pagina", "container-title": "Site", "URL": "https://example.org/x",
               "accessed": {"date-parts": [[2020, 3, 4]]}, "author": [person("Bakker", "Jos")]}
        text = "".join(t for t, _ in citations.entry(web))
        self.assertIn("https://example.org/x", text)
        self.assertTrue(text.endswith("Accessed 4 March 2020."), text)
        nl = "".join(t for t, _ in citations.entry(web, lang="nl"))
        self.assertTrue(nl.endswith("Geraadpleegd op 4 maart 2020."), nl)

    def test_web_page_address_ends_before_the_date(self):
        """The address is a unit of its own: a stop after it when the date it was read follows, none when it ends the
        entry (a stop there could be read as part of it)."""
        web = {"id": "w", "type": "webpage", "title": "Pagina", "container-title": "Site", "URL": "https://example.org/x",
               "accessed": {"date-parts": [[2020, 3, 4]]}, "author": [person("Bakker", "Jos")]}
        for style in ("chicago", "apa"):
            text = "".join(t for t, _ in citations.entry(web, style))
            self.assertIn("https://example.org/x. Accessed 4 March 2020.", text)
        nl = "".join(t for t, _ in citations.entry(web, lang="nl"))
        self.assertIn("https://example.org/x. Geraadpleegd op 4 maart 2020.", nl)
        undated = "".join(t for t, _ in citations.entry({k: v for k, v in web.items() if k != "accessed"}))
        self.assertTrue(undated.endswith("Site. https://example.org/x"), undated)

    def test_bibliography_order_and_filter(self):
        zed = {"id": "z", "type": "book", "title": "Ä", "author": [person("Émile")]}
        self.assertEqual(len(citations.bibliography([DIJK, BAKKER, zed], keys=["b", "zz"])), 1)
        allof = citations.bibliography([DIJK, BAKKER, zed])
        self.assertEqual([r[0][0].split(",")[0] for r in allof], ["Bakker", "Dijk", "Émile"])

    def test_cited_keys_in_order(self):
        doc = manuscript.parse("Text [@b] and ^[a note [@a]] and [@b; @c].")
        self.assertEqual(citations.cited_keys([doc]), ["b", "a", "c"])

    def test_part_one_alias(self):
        self.assertIs(book_export.cite_text, citations.cite_text)


if __name__ == "__main__":
    unittest.main()
