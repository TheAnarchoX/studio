"""Making a carousel without Claude: render and QA with the test kit, and the endpoints the Art tab uses."""
import shutil
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest import mock

import anyio

from studio import making, mcp_server
from studio.store import Store
from tests.support import temp_studio

KIT = Path(__file__).parent / "fixtures" / "kit"


class MakingTest(unittest.TestCase):
    def setUp(self):
        ctx = temp_studio()
        self.st = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        shutil.copytree(KIT, self.st.root / "Night" / "_kit", ignore=shutil.ignore_patterns("__pycache__"))
        self.s = Store()
        p = self.s.create("Hold the Line", "Night")
        self.s.save_text(p["id"], "Hold the Line", "Hold the line\nwhen they push.\nHold it longer.")
        self.s.set_slides(p["id"], [{"concept": "plain"}, {"concept": "bars", "mark": [1]}])
        self.id = p["id"]

    def test_render_with_the_test_kit(self):
        self.s.set_status(self.id, "ready")
        res = making.render(self.s, self.id)
        self.assertEqual(len(res["images"]), 4)                  # 2 slides x 4:5 x with and without the name
        for rel in res["images"]:
            self.assertTrue((self.s.root / rel).is_file(), rel)
        self.assertTrue((self.s.root / res["sheet"]).is_file())
        self.assertEqual(res["status"], "in review")
        self.assertEqual(self.s.read(self.id)["status"], "in review")
        self.assertIsInstance(res["seconds"], float)
        self.assertFalse(making.progress(self.s, self.id)["running"])

    def test_render_one_slide_one_format(self):
        res = making.render(self.s, self.id, slide=2, format="4:5", signed=True)
        self.assertEqual(len(res["images"]), 1)
        self.assertTrue(res["images"][0].endswith("/With name/hold-the-line-4x5-2-bars.png"), res["images"])
        self.assertIsNone(res["sheet"])                          # slide 1 isn't rendered yet: no contact sheet
        self.assertEqual(res["status"], "draft")                 # only a ready poem moves to in review
        with self.assertRaises(Exception):
            making.render(self.s, self.id, slide=3)

    def test_qa_runs_after_render(self):
        making.render(self.s, self.id)
        out = making.run_qa(self.s, self.id)
        self.assertIn("4 images, 0 fail", out["summary"])
        self.assertIn("slide 1 Plain (signed)", out["summary"])
        self.assertIn("slide 2 Bars (signed)", out["summary"])
        self.assertEqual(out["report"]["poem"], self.id)
        rows = {im["slide"]: len(im["rows"]) for im in out["report"]["images"].values() if not im["signed"]}
        self.assertEqual(rows, {1: 3, 2: 3})                     # the plate leaves the bars and takes the letters
        self.assertTrue(self.s.read(self.id)["qa"])

    def test_one_job_per_poem_at_a_time(self):
        with making._job(self.id, "render"):
            self.assertTrue(making.progress(self.s, self.id)["running"])
            with self.assertRaises(ValueError):
                making.render(self.s, self.id)
        self.assertFalse(making.progress(self.s, self.id)["running"])

    def test_render_without_slides_is_a_400(self):
        p = self.s.create("Empty", "Night")
        self.s.save_text(p["id"], "Empty", "One line.")
        code, body = self.st.post("/api/render", {"id": p["id"]})
        self.assertEqual(code, 400)
        self.assertIn("no slides", body["error"])
        code, body = self.st.post("/api/render", {"id": self.id, "format": "2:3"})
        self.assertEqual((code, body["error"]), (400, "unknown format '2:3'; use 1:1, 4:5 or 9:16"))
        code, body = self.st.post("/api/qa", {"id": self.id})
        self.assertEqual((code, body["error"]), (400, "nothing rendered to check yet; render first"))

    def test_render_and_qa_over_http(self):
        code, r = self.st.post("/api/render", {"id": self.id, "slide": 1, "format": "45", "signed": None})
        self.assertEqual(code, 200, r)
        self.assertEqual(len(r["images"]), 2)
        self.assertEqual(r["poem"]["art"]["formats"]["45"]["slides"][0]["signed"], r["images"][0])
        code, q = self.st.post("/api/qa", {"id": self.id, "slide": 1})
        self.assertEqual(code, 200, q)
        self.assertIn("2 images", q["summary"])
        self.assertTrue(q["poem"]["qa"]["images"])
        code, body = self.st.post("/api/render", {"id": self.id, "slide": "2"})
        self.assertEqual(code, 400)
        code, prog = self.st.get("/api/render/progress?id=" + quote(self.id))
        self.assertEqual((code, prog), (200, {"running": False}))

    def test_slides_brief_and_posting_notes_over_http(self):
        code, cs = self.st.get("/api/concepts?series=Night")
        self.assertEqual(code, 200)
        self.assertEqual([(c["id"], c["name"]) for c in cs], [("bars", "Bars"), ("plain", "Plain")])
        self.assertIn("params: ground", cs[1]["doc"])
        code, p = self.st.post("/api/slides", {"id": self.id, "slides": [{"concept": "bars"}, {"concept": "plain", "ground": "paper"}]})
        self.assertEqual(code, 200)
        self.assertEqual(p["slides"], [{"concept": "bars"}, {"concept": "plain", "ground": "paper"}])
        code, body = self.st.post("/api/slides", {"id": self.id, "slides": [{"concept": "nope"}]})
        self.assertEqual(code, 400)
        self.assertIn("unknown concept", body["error"])
        code, p = self.st.post("/api/brief", {"id": self.id, "text": "# Brief\r\n\r\nTwo slides."})
        self.assertEqual((code, p["brief"]), (200, "# Brief\n\nTwo slides.\n"))
        code, p = self.st.post("/api/posting-notes", {"id": self.id, "text": "Post it at night.\r\n"})
        self.assertEqual((code, p["notes"]), (200, "Post it at night.\n"))
        self.assertEqual((Path(p["path"]) / "NOTES.md").read_text(encoding="utf-8"), "Post it at night.\n")
        self.assertFalse((Path(p["path"]) / "writing-notes.md").exists())
        code, body = self.st.post("/api/posting-notes", {"text": "x"})
        self.assertEqual(code, 400)

    def test_mcp_render_uses_making(self):
        made, real = [], making.render

        def spy(*a, **kw):
            made.append(real(*a, **kw))
            return made[-1]
        saved = mcp_server.store
        mcp_server.store = self.s
        try:
            with mock.patch.object(making, "render", spy):
                out = anyio.run(mcp_server.render, self.id)
            qa_text = anyio.run(mcp_server.qa, self.id)
        finally:
            mcp_server.store = saved
        text, folder = out[0], self.s.root / self.id
        self.assertEqual(len(made), 1)
        self.assertTrue(text.startswith("Rendered 4 images in "), text)
        self.assertIn(f"for {self.id} (status: draft).", text)
        self.assertIn(f"Preview page: {folder / 'hold-the-line.html'}", text)
        self.assertIn(f"Contact sheet: {folder / 'hold-the-line-carousel-preview.png'}", text)
        listed = [ln.strip() for ln in text.splitlines() if ln.startswith("  ")]
        self.assertEqual(listed, [(self.s.root / rel).relative_to(folder).as_posix() for rel in made[0]["images"]])
        self.assertTrue(text.endswith("Next: run qa, and look at the picture."))
        self.assertEqual(out[1].to_image_content().mime_type, "image/jpeg")
        self.assertTrue(qa_text.startswith(f"QA {self.id}: 4 images, 0 fail"), qa_text)


if __name__ == "__main__":
    unittest.main()
