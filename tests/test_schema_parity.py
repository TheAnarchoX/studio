"""The browser's editor schema mirrors the manuscript dialect: same node and mark names, and every document
the dialect produces loads into it and comes back unchanged (tests/js/schema_roundtrip.js runs in node)."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import manuscript
from tests.test_manuscript import POEM_SAMPLES, SAMPLES

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_JS = ROOT / "studio" / "static" / "book-schema.js"
PM_JS = ROOT / "studio" / "static" / "vendor" / "prosemirror.js"
HARNESS = ROOT / "tests" / "js" / "schema_roundtrip.js"


class SchemaParityTest(unittest.TestCase):
    def test_schema_names_match_python(self):
        first = SCHEMA_JS.read_text(encoding="utf-8").splitlines()[0]
        want = "// schema: nodes=%s; marks=%s" % (",".join(manuscript.SCHEMA["nodes"]),
                                                   ",".join(manuscript.SCHEMA["marks"]))
        self.assertEqual(first, want)

    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_documents_round_trip_in_js(self):
        docs = [manuscript.parse(md) for md in SAMPLES] + [manuscript.parse(md, "poem") for md in POEM_SAMPLES]
        docs.append(manuscript.parse(""))
        tmp = Path(tempfile.mkdtemp(prefix="studio-schema-"))
        try:
            (tmp / "input.json").write_text(json.dumps(docs), encoding="utf-8")
            r = subprocess.run([shutil.which("node"), str(HARNESS), str(PM_JS), str(SCHEMA_JS),
                                str(tmp / "input.json")], capture_output=True, text=True, encoding="utf-8",
                               timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(out["count"], len(SAMPLES) + len(POEM_SAMPLES) + 1)
        self.assertEqual(out["failures"], [])
        self.assertEqual(out["checks"], [])     # paste and display rules (no DOM here; see schema_roundtrip.js)
        # the schema as built in JS, not only its first line: the same node and mark names, the marks in the same order
        self.assertEqual(out["names"], {"nodes": manuscript.SCHEMA["nodes"], "marks": manuscript.SCHEMA["marks"]})


if __name__ == "__main__":
    unittest.main()
