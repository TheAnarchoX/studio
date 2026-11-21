"""Spelling in the book's text: Hunspell (vendor/hunspell.js) in the worker (book-spell-worker.js) with the bundled
Dutch and English dictionaries, run in node by tests/js/spell_worker.js; the editor's word picking (book-spell.js) by
tests/js/book_spell.js; the dictionaries' and Hunspell's licences; the vendored bundle rebuilt byte for byte."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "studio" / "static"
TOOLS = ROOT / "tools"
DICTIONARIES = STATIC / "dictionaries"
WORKER_HARNESS = ROOT / "tests" / "js" / "spell_worker.js"
WORDS_HARNESS = ROOT / "tests" / "js" / "book_spell.js"
NODE = shutil.which("node")
# each bundled language and what its LICENSE must name (Dutch: OpenTaal's BSD and Creative Commons; English: SCOWL)
LICENCES = {"nl": [r"BSD", r"Creative Commons"], "en": [r"SCOWL", r"Kevin Atkinson"], "en-GB": [r"SCOWL", r"Kevin Atkinson"]}


@unittest.skipUnless(NODE, "node isn't installed")
class WorkerTest(unittest.TestCase):
    replies = None

    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, str(WORKER_HARNESS), str(STATIC)], capture_output=True, text=True, encoding="utf-8",
                           timeout=300)
        if r.returncode:
            raise AssertionError(f"the worker harness failed: {r.stderr[-3000:]}")
        cls.replies = json.loads(r.stdout)["replies"]

    def reply(self, name):
        return self.replies[name]

    def test_worker_in_node(self):
        for lang in ("nl", "en", "en-GB"):
            self.assertEqual(self.reply(f"load {lang}"), {"type": "loaded", "lang": lang})
        # ["maandag", "kliniek", "gigantsiche", "timeout"]: Dutch alone knows no timeout; English does
        self.assertEqual(self.reply("dutch in nl"), {"type": "checked", "bad": [2, 3]})
        self.assertEqual(self.reply("dutch in nl and en"), {"type": "checked", "bad": [2]})
        self.assertEqual(self.reply("Oktober in nl"), {"type": "checked", "bad": [0]})      # Dutch months are lower case
        self.assertIn("gigantische", self.reply("suggest gigantsiche")["words"])

    def test_a_check_waits_for_its_dictionaries(self):
        self.assertEqual(self.reply("check before loaded"), {"type": "checked", "bad": [1]})

    def test_a_lang_span_is_checked_in_its_own_language_only(self):
        # ["beautfil", "maandag", "beautiful"] in English, "kliniek" in Dutch
        self.assertEqual(self.reply("a lang span in en"), {"type": "checked", "bad": [0, 1]})

    def test_british_english(self):
        self.assertEqual(self.reply("British in en-GB")["bad"], [2])        # colour, realise; not colour in en-US

    def test_typographic_apostrophes(self):
        self.assertEqual(self.reply("apostrophes")["bad"], [])

    def test_a_language_without_a_dictionary_flags_nothing(self):
        self.assertEqual(self.reply("load missing")["type"], "error")
        self.assertEqual(self.reply("load missing")["lang"], "xx")
        self.assertEqual(self.reply("no dictionary")["bad"], [])

    def test_suggestions(self):
        self.assertLessEqual(len(self.reply("suggest gigantsiche")["words"]), 5)
        both = self.reply("suggest beautfil in nl and en")["words"]
        self.assertLessEqual(len(both), 5)
        self.assertIn("beautiful", both)


class WordsTest(unittest.TestCase):
    @unittest.skipUnless(NODE, "node isn't installed")
    def test_words_in_node(self):
        r = subprocess.run([NODE, str(WORDS_HARNESS), str(STATIC / "vendor" / "prosemirror.js"),
                            str(STATIC / "book-schema.js"), str(STATIC / "book-text.js"), str(STATIC / "book-tools.js"),
                            str(STATIC / "book-spell.js")], capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["failures"], [])
        self.assertGreater(out["checked"], 20)


class FilesTest(unittest.TestCase):
    def test_dictionaries_and_licences(self):
        for lang, names in LICENCES.items():
            folder = DICTIONARIES / lang
            for f in ("index.aff", "index.dic", "LICENSE"):
                self.assertTrue((folder / f).is_file(), f"{lang}/{f} is missing")
            self.assertGreater((folder / "index.dic").stat().st_size, 100_000, lang)
            text = (folder / "LICENSE").read_text(encoding="utf-8", errors="replace")
            for name in names:
                self.assertRegex(text, re.compile(name, re.I), f"{lang}/LICENSE doesn't name {name}")
        hunspell = (STATIC / "vendor" / "LICENSE-hunspell.txt").read_text(encoding="utf-8")
        self.assertIn("Mozilla Public License", hunspell)
        self.assertIn("MPL", hunspell)
        self.assertIn("hunspell-asm", hunspell)

    def test_the_worker_and_editor_are_loaded(self):
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/static/book-spell.js"></script>', index)
        self.assertLess(index.index("book-tools.js"), index.index("book-spell.js"))
        worker = (STATIC / "book-spell-worker.js").read_text(encoding="utf-8")
        self.assertIn('importScripts("/static/vendor/hunspell.js")', worker)

    @unittest.skipUnless(NODE and (TOOLS / "node_modules" / "esbuild").is_dir() and (TOOLS / "node_modules" / "hunspell-asm").is_dir(),
                         "node or tools/node_modules isn't there (cd tools && npm ci)")
    def test_vendor_build_is_reproducible(self):
        out = STATIC / "vendor" / "hunspell.js"
        before = out.read_bytes()
        r = subprocess.run([NODE, "build_vendor.mjs"], cwd=TOOLS, capture_output=True, text=True, encoding="utf-8",
                           timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out.read_bytes(), before, "rebuilding changed vendor/hunspell.js")
        git = shutil.which("git")
        if git:
            d = subprocess.run([git, "diff", "--exit-code", "--stat", "--", "studio/static/vendor/hunspell.js"], cwd=ROOT,
                               capture_output=True, text=True)
            self.assertEqual(d.returncode, 0, d.stdout)


if __name__ == "__main__":
    unittest.main()
