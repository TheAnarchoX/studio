"""Book design tests. Run: python -m unittest discover tests"""
import unittest

from studio import book_design
from studio.books import BooksError

LOOK = {"fonts": {"text": {"family": "Source Serif 4", "weight": 400}}}

KEYS = {
    "template": None, "trim": None, "width": None, "height": None, "printer": None, "paper": None, "interior": None,
    "margins": ("inside", "outside", "top", "bottom"),
    "text": ("font", "weight", "size", "line", "align", "hyphenate", "paragraph"),
    "headings": ("font", "size", "case", "number", "sections", "sink", "start", "opening"),
    "heads": ("verso", "recto", "style", "folio"),
    "poems": ("place", "keepStanzas"), "scene": None, "notes": ("size", "pageRefs"),
    "citations": ("style", "list"), "pages": ("labels", "contentsSections", "leaders", "setIn"),
}


def meta(language="nl", kind="memoir", **design):
    return {"language": language, "kind": kind, "design": design}


class BookDesignTest(unittest.TestCase):
    def test_each_kind_resolves_complete(self):
        for kind, template in book_design.KIND_TEMPLATE.items():
            d = book_design.resolve(meta("en", kind), LOOK)
            self.assertEqual(d["template"], template)
            for key, subs in KEYS.items():
                self.assertIn(key, d, (kind, key))
                for sub in subs or ():
                    self.assertIn(sub, d[key], (kind, key, sub))
            self.assertIsNotNone(d["text"]["font"])
            self.assertTrue(d["rights"])

    def test_templates_differ(self):
        t = {k: book_design.resolve(meta("nl", kind), LOOK) for kind, k in (("nonfiction", "n"), ("academic", "a"),
                                                                           ("poetry", "p"))}
        self.assertEqual(t["n"]["headings"]["number"], "digits")
        self.assertTrue(t["n"]["pages"]["contentsSections"])
        self.assertEqual((t["a"]["text"]["size"], t["a"]["text"]["line"], t["a"]["notes"]["size"]), (10, 13.5, 8))
        self.assertEqual((t["a"]["headings"]["start"], t["a"]["headings"]["sections"]), ("next", "numbered"))
        self.assertEqual((t["p"]["heads"]["recto"], t["p"]["headings"]["sink"]), ("none", 30))

    def test_trim_defaults_by_language(self):
        nl = book_design.resolve(meta("nl"), LOOK)
        self.assertEqual((nl["trim"], nl["width"], nl["height"]), ("135x210", 135, 210))
        en = book_design.resolve(meta("en-GB"), LOOK)
        self.assertEqual((en["trim"], en["width"], en["height"]), ("5.5x8.5in", 139.7, 215.9))

    def test_margins_from_trim(self):
        m = book_design.resolve(meta("nl"), LOOK)["margins"]
        self.assertEqual(m, {"inside": 19, "outside": 15, "top": 18, "bottom": 23})
        m = book_design.resolve(meta("nl", margins={"top": 20}), LOOK)["margins"]
        self.assertEqual((m["top"], m["inside"]), (20, 19))

    def test_custom_trim(self):
        d = book_design.resolve(meta("nl", trim="custom", width=120, height=200), LOOK)
        self.assertEqual((d["width"], d["height"]), (120, 200))
        d = book_design.resolve(meta("nl", trim="custom"), LOOK)         # no size stored: the default trim
        self.assertEqual(d["trim"], "135x210")

    def test_stored_overrides_and_template_switch(self):
        d = book_design.resolve(meta("nl", "memoir", text={"size": 11}), LOOK)
        self.assertEqual((d["text"]["size"], d["headings"]["sink"]), (11, 42))
        d = book_design.resolve(meta("nl", "memoir", template="academic", text={"size": 11}), LOOK)
        self.assertEqual(d["text"]["size"], 11)
        self.assertEqual(d["headings"]["sink"], 24)             # not stored: follows the new template

    def test_unhashable_template_and_kind_do_not_raise(self):
        for bad in ([], {}):
            d = book_design.resolve(meta("nl", "nonfiction", template=bad), LOOK)
            self.assertEqual(d["template"], "nonfiction")
            d = book_design.resolve({"language": "nl", "kind": bad, "design": {"template": bad}}, LOOK)
            self.assertEqual(d["template"], "literary")
            with self.assertRaises(BooksError) as e:
                book_design.clean({}, {"template": bad})
            self.assertTrue(str(e.exception).startswith("The template is "))
            book_design.clean({"template": bad}, {"text": {"line": 12}})       # no TypeError

    def test_one_bad_label_keeps_the_others(self):
        d = book_design.resolve(meta("nl", pages={"labels": {"toc": "Inhoudsopgave", "notes": "x" * 99, "zz": "a"}}),
                                LOOK)
        self.assertEqual((d["pages"]["labels"]["toc"], d["pages"]["labels"]["notes"]), ("Inhoudsopgave", "Noten"))

    def test_bad_stored_value_falls_back(self):
        d = book_design.resolve(meta("nl", margins={"inside": "wide"}, text={"size": 99}, scene="x"), LOOK)
        self.assertEqual(d["margins"]["inside"], 19)
        self.assertEqual(d["text"]["size"], 10.5)
        self.assertEqual(d["scene"], "asterisks")
        book_design.resolve({"design": "nonsense", "language": None}, None)          # never raises

    def test_clean_validates(self):
        with self.assertRaises(BooksError) as e:
            book_design.clean({}, {"margins": {"inside": 2}})
        self.assertEqual(str(e.exception), "The inside margin is 5 to 60 mm.")
        with self.assertRaises(BooksError):
            book_design.clean({}, {"trim": "custom"})
        self.assertEqual(book_design.clean({}, {"trim": "custom", "width": 120, "height": 200})["width"], 120)
        with self.assertRaises(BooksError):
            book_design.clean({}, {"template": "fancy"})
        with self.assertRaises(BooksError):
            book_design.clean({}, {"text": {"size": 10, "line": 40}})
        out = book_design.clean({"x": 1, "text": {"size": 11}}, {"text": {"align": "left"}, "template": "poetry"})
        self.assertEqual(out, {"x": 1, "text": {"size": 11, "align": "left"}, "template": "poetry"})
        self.assertEqual(book_design.clean({}, {"x": 1}), {"x": 1})

    def test_clean_labels_merge(self):
        s = book_design.clean({}, {"pages": {"labels": {"toc": "Inhoudsopgave"}}})
        s = book_design.clean(s, {"pages": {"labels": {"notes": "Aantekeningen"}}})
        self.assertEqual(s["pages"]["labels"], {"toc": "Inhoudsopgave", "notes": "Aantekeningen"})
        s = book_design.clean(s, {"pages": {"labels": {"toc": ""}}})
        self.assertEqual(s["pages"]["labels"], {"notes": "Aantekeningen"})
        with self.assertRaises(BooksError):
            book_design.clean({}, {"pages": {"labels": {"toc": "x" * 61}}})

    def test_reset_sections(self):
        s = {"template": "poetry", "trim": "custom", "width": 120, "height": 200, "text": {"size": 11}, "x": 1}
        self.assertEqual(book_design.reset(s, ["trim"]), {"template": "poetry", "text": {"size": 11}, "x": 1})
        self.assertNotIn("text", book_design.reset(s, "text"))
        self.assertEqual(book_design.reset(s, "all"), {"template": "poetry"})
        self.assertEqual(book_design.reset({"text": {}}, "all"), {})

    def test_labels_and_rights_follow_language(self):
        d = book_design.resolve(meta("nl"), LOOK)
        self.assertEqual(d["pages"]["labels"]["toc"], "Inhoud")
        self.assertEqual(d["rights"], book_design.RIGHTS["nl"])
        d = book_design.resolve(meta("nl", pages={"labels": {"toc": "Inhoudsopgave"}}), LOOK)
        self.assertEqual(d["pages"]["labels"]["toc"], "Inhoudsopgave")
        self.assertEqual(d["pages"]["labels"]["notes"], "Noten")
        d = book_design.resolve(meta("fr"), LOOK)
        self.assertEqual((d["pages"]["labels"]["toc"], d["rights"]), ("Contents", book_design.RIGHTS["en"]))

    def test_look_font_is_default(self):
        look = {"fonts": {"text": {"family": "Source Serif 4", "weight": 350}}}
        d = book_design.resolve(meta("nl"), look)
        self.assertEqual((d["text"]["font"], d["text"]["weight"]), ("Source Serif 4", 350))
        d = book_design.resolve(meta("nl", text={"font": "Literata"}), look)
        self.assertEqual(d["text"]["font"], "Literata")

    def test_spelling_defaults_and_clean(self):
        self.assertEqual(book_design.spelling({"language": "nl"}), {"languages": ["nl", "en"], "words": []})
        self.assertEqual(book_design.spelling({"language": "en-GB"}), {"languages": ["en"], "words": []})
        s = book_design.spelling({"language": "nl", "spelling": {"languages": ["en", "nl"], "words": ["abc"]}})
        self.assertEqual(s, {"languages": ["nl", "en"], "words": ["abc"]})
        self.assertEqual(book_design.clean_spelling({"words": ["a", "b", "a"]}), {"words": ["a", "b"]})
        self.assertEqual(book_design.clean_spelling({"languages": ["nl", "NL", "de"]}), {"languages": ["nl", "de"]})
        for bad in ({"languages": []}, {"languages": ["n"]}, {"languages": ["nl"] * 5 + ["de"]},
                    {"words": ["two words"]}, {"words": ["x" * 61]}, {"words": ["w"] * 5001}, {"words": "abc"}, "nl"):
            with self.assertRaises(BooksError, msg=bad):
                book_design.clean_spelling(bad)


if __name__ == "__main__":
    unittest.main()
