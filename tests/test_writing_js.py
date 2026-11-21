"""The writing log's helpers (studio/static/writing.js: dates, periods, totals, goal statistics), run in node by
tests/js/writing.js."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "studio" / "static"
HARNESS = ROOT / "tests" / "js" / "writing.js"


class WritingJsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_helpers_in_node(self):
        r = subprocess.run([shutil.which("node"), str(HARNESS), str(STATIC / "writing.js")],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["failures"], [])
        self.assertGreater(out["checked"], 15)


if __name__ == "__main__":
    unittest.main()
