"""QA tests on synthetic slides: ink edges, near misses, the name, and collisions."""
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from studio.qa import DEFAULT_CHECKS, measure

NIGHT, PAPER = (12, 14, 17), (238, 234, 226)


def slide(path, rows, name=None, size=(2160, 2700)):
    """rows: [(x0, y0, x1, y1)] in image px, drawn in paper on night; name: an extra box."""
    im = Image.new("RGB", size, NIGHT)
    d = ImageDraw.Draw(im)
    for box in rows + ([name] if name else []):
        d.rectangle(box, fill=PAPER)
    im.save(path)
    return path


class QATest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-qa-"))
        self.plate = slide(self.tmp / "plate.png", [])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_pair(self, rows, name, rows_unsigned=None):
        s = slide(self.tmp / "s.png", rows, name)
        u = slide(self.tmp / "u.png", rows if rows_unsigned is None else rows_unsigned)
        return measure((s, self.plate), (u, self.plate), (1080, 1350), 2)

    def test_columns_and_a_near_miss(self):
        rows = [(200, 300, 1500, 420), (200, 500, 1200, 620), (206, 700, 1400, 820)]   # third row 3 slide px off
        m = self.run_pair(rows, (200, 2300, 600, 2340))[True]
        self.assertEqual(m["columns"]["left"][0]["x"], 100.0)
        texts = " ".join(i["text"] for i in m["issues"])
        self.assertIn("3.0 px off the left column at 100.0", texts)

    def test_the_name_is_found_and_layout_is_identical(self):
        rows = [(200, 300, 1500, 420), (200, 500, 1200, 620)]
        m = self.run_pair(rows, (200, 2300, 600, 2340))[True]
        self.assertTrue(any(s.get("name") for r in m["rows"] for s in r["segments"]))
        self.assertFalse([i for i in m["issues"] if "layout" in i["text"]])

    def test_a_layout_that_moves_without_the_name(self):
        rows = [(200, 300, 1500, 420), (200, 500, 1200, 620)]
        moved = [(200, 340, 1500, 460), (200, 540, 1200, 660)]
        m = self.run_pair(rows, (200, 2300, 600, 2340), moved)[True]
        self.assertTrue([i for i in m["issues"] if "isn't identical" in i["text"]])

    def test_a_name_that_runs_into_the_poem_fails(self):
        rows = [(200, 300, 1500, 420)]
        m = self.run_pair(rows, (1510, 330, 1800, 400))[True]   # 10 image px from the row's end, same band
        self.assertTrue([i for i in m["issues"] if i["level"] == "fail" and "runs into" in i["text"]])

    def test_near_miss_threshold_is_per_series(self):
        rows = [(200, 300, 1500, 420), (200, 500, 1200, 620), (206, 700, 1400, 820)]
        m = self.run_pair(rows, (200, 2300, 600, 2340))[True]
        self.assertIn("off the left column", " ".join(i["text"] for i in m["issues"]))
        s = slide(self.tmp / "s.png", rows)
        m = measure((s, self.plate), None, (1080, 1350), 2, checks={"near": 2.0})[True]
        self.assertNotIn("off the left column", " ".join(i["text"] for i in m["issues"]))

    def test_story_safe_zone_is_per_series(self):
        size = (2160, 3840)
        plate = slide(self.tmp / "plate916.png", [], size=size)
        s = slide(self.tmp / "s916.png", [(200, 500, 1500, 620)], size=size)    # starts 250 slide px down
        texts = lambda m: " ".join(i["text"] for i in m["issues"])  # noqa: E731
        self.assertIn("story", texts(measure((s, plate), None, (1080, 1920), 2, story=True)[True]))
        m = measure((s, plate), None, (1080, 1920), 2, story=True, checks={"story_top": 200})[True]
        self.assertNotIn("story", texts(m))
        self.assertEqual(DEFAULT_CHECKS["story_top"], 280)



if __name__ == "__main__":
    unittest.main()
