"""The writing window's text helpers (studio/static/book-text.js), run in node by tests/js/book_text.js: word counts
that match manuscript.counts for every sample, straight quotes in each quote style and apostrophes, note numbers through
the book, citation labels, the / menu and the selection bar by features, comment ranges, titles."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import manuscript
from tests.test_manuscript import POEM_SAMPLES, SAMPLES

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "studio" / "static"
HARNESS = ROOT / "tests" / "js" / "book_text.js"


class BookTextTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_helpers_in_node(self):
        docs = [{"doc": manuscript.parse(md), "words": manuscript.counts(md)["words"]} for md in SAMPLES]
        docs += [{"doc": manuscript.parse(md, "poem"), "words": manuscript.counts(md, "poem")["words"]} for md in POEM_SAMPLES]
        tmp = Path(tempfile.mkdtemp(prefix="studio-booktext-"))
        try:
            (tmp / "input.json").write_text(json.dumps(docs), encoding="utf-8")
            r = subprocess.run([shutil.which("node"), str(HARNESS), str(STATIC / "vendor" / "prosemirror.js"),
                                str(STATIC / "book-schema.js"), str(STATIC / "book-text.js"), str(tmp / "input.json")],
                               capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(out["failures"], [])
        self.assertGreater(out["checked"], len(docs) + 40)
        # poem lines indented in the editor (typed, tabbed, pasted) keep their indentation through the Markdown
        self.assertEqual(len(out["typed"]), 4)
        for doc in out["typed"]:
            with self.subTest(doc=doc):
                md = manuscript.serialize(doc)
                self.assertRegex(md, "(\N{NO-BREAK SPACE}|&#xA0;)\N{NO-BREAK SPACE}")
                self.assertEqual(manuscript.parse(md, doc["attrs"]["form"]), solid(doc))


def solid(doc):
    """A document as Markdown keeps it: without empty paragraphs (the editor's line to type on)."""
    if isinstance(doc, dict):
        out = {k: solid(v) for k, v in doc.items()}
        if isinstance(out.get("content"), list):
            out["content"] = [n for n in out["content"] if not (n.get("type") == "paragraph" and not n.get("content"))]
        return out
    return [solid(x) for x in doc] if isinstance(doc, list) else doc


if __name__ == "__main__":
    unittest.main()
