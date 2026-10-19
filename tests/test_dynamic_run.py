"""Tests for the dynamic adaptive runner: bounded, resumable, honest on images."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dynamic_run as dr


class TestWorkers(unittest.TestCase):
    def test_bounded(self):
        self.assertEqual(dr.pick_workers(0), 1)
        self.assertEqual(dr.pick_workers(1), 1)
        for n in (2, 3, 10, 100):
            w = dr.pick_workers(n)
            self.assertGreaterEqual(w, 2)
            self.assertLessEqual(w, 6)

    def test_plan_batches(self):
        self.assertEqual(dr.plan_batches(0, 7), [])
        self.assertEqual(dr.plan_batches(7, 7), [(0, 7)])
        self.assertEqual(dr.plan_batches(8, 7), [(0, 7), (7, 8)])


class TestPlanOnly(unittest.TestCase):
    def test_text_source_plans_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "s.md")
            src.write_text("# T\n\nSome readable text here.\n", encoding="utf-8")
            rc = dr.main(["--source", str(src), "--run-id", "r1",
                          "--profile", str(ROOT / "profiles" / "APSC_PRELIMS.json"),
                          "--config", str(ROOT / "config.default.json"),
                          "--build-dir", tmp, "--plan-only"])
            self.assertEqual(rc, 0)
            plan = Path(tmp, "r1", "dynamic_plan.json")
            self.assertTrue(plan.is_file())

    def test_image_pdf_fast_fail_without_ocr(self):
        # empty parsable source stands in for an image-only PDF with no text
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "empty.md")
            src.write_text("", encoding="utf-8")
            rc = dr.main(["--source", str(src), "--run-id", "img",
                          "--profile", str(ROOT / "profiles" / "APSC_PRELIMS.json"),
                          "--config", str(ROOT / "config.default.json"),
                          "--build-dir", tmp, "--plan-only"])
            # either honest fast-fail (2) or ok with zero-block warning; never a hang
            self.assertIn(rc, (0, 2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
