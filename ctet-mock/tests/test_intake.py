"""CTET Mock PWA — intake and classification checks.

Run: python -m pytest ctet-mock/tests/test_intake.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ctetmock import intake  # noqa: E402
from helpers import make_mock_html as make_html  # noqa: E402


class TestTokenParsing(unittest.TestCase):
    def test_full_convention_is_parsed(self):
        tokens = intake.parse_tokens("p2-social-c8-natural-resources-m01")
        self.assertEqual(tokens["paper"], "Paper II")
        self.assertEqual(tokens["subject"], "Social Science")
        self.assertEqual(tokens["klass"], 8)
        self.assertEqual(tokens["lesson_slug"], "natural-resources")
        self.assertEqual(tokens["mock_label"], "Mock 1")

    def test_paper_aliases(self):
        self.assertEqual(intake.parse_tokens("p1-evs-c3-a-m01")["paper"], "Paper I")
        self.assertEqual(intake.parse_tokens("paper2-evs-c3-a-m01")["paper"], "Paper II")
        self.assertEqual(intake.parse_tokens("paper-ii-evs-c3-a-m01")["paper"], "Paper II")
        self.assertEqual(intake.parse_tokens("paper-i-evs-c3-a-m01")["paper"], "Paper I")

    def test_subject_aliases(self):
        cases = {
            "cdp": "Child Development & Pedagogy",
            "math": "Mathematics",
            "maths": "Mathematics",
            "mathematics": "Mathematics",
            "evs": "Environmental Studies",
            "science": "Science",
            "sci": "Science",
            "social": "Social Science",
            "socialscience": "Social Science",
            "socialstudies": "Social Science",
            "sst": "Social Science",
            "lang1": "Language I",
            "hindi": "Language I",
            "lang2": "Language II",
            "english": "Language II",
        }
        for token, expected in cases.items():
            with self.subTest(token=token):
                parsed = intake.parse_tokens(f"p2-{token}-c6-lesson-m01")
                self.assertEqual(parsed["subject"], expected)

    def test_class_aliases(self):
        self.assertEqual(intake.parse_tokens("p2-sci-c6-x-m01")["klass"], 6)
        self.assertEqual(intake.parse_tokens("p2-sci-class-7-x-m01")["klass"], 7)
        self.assertEqual(intake.parse_tokens("p2-sci-grade8-x-m01")["klass"], 8)
        self.assertEqual(intake.parse_tokens("p2-sci-6-x-m01")["klass"], 6)

    def test_mock_label_aliases(self):
        self.assertEqual(intake.parse_tokens("p2-sci-c6-x-m01")["mock_label"], "Mock 1")
        self.assertEqual(intake.parse_tokens("p2-sci-c6-x-mock2")["mock_label"], "Mock 2")
        self.assertEqual(intake.parse_tokens("p2-sci-c6-x-mock-03")["mock_label"], "Mock 3")
        self.assertEqual(intake.parse_tokens("p2-sci-c6-x-set4")["mock_label"], "Mock 4")

    def test_lesson_slug_keeps_everything_else(self):
        tokens = intake.parse_tokens("p2-sci-c8-my-chapter-1-m01")
        self.assertEqual(tokens["lesson_slug"], "my-chapter-1")
        self.assertEqual(tokens["klass"], 8)

    def test_unknown_filename_yields_nothing(self):
        tokens = intake.parse_tokens("random-file")
        self.assertIsNone(tokens["paper"])
        self.assertIsNone(tokens["subject"])
        self.assertIsNone(tokens["klass"])
        self.assertIsNone(tokens["lesson_slug"])
        self.assertIsNone(tokens["mock_label"])


class TestPackageReading(unittest.TestCase):
    def test_package_is_extracted(self):
        html = make_html({"title": "Light"}, [{"id": "Q-1"}, {"id": "Q-2"}])
        package = intake.read_package(html)
        self.assertIsNotNone(package)
        self.assertEqual(package["meta"]["title"], "Light")
        self.assertEqual(package["question_count"], 2)

    def test_missing_package_returns_none(self):
        self.assertIsNone(intake.read_package("<html><body>no package</body></html>"))

    def test_braces_inside_strings_do_not_end_the_package(self):
        html = make_html({"title": "Set {x} and } brace"}, [{"id": "Q-1"}])
        package = intake.read_package(html)
        self.assertIsNotNone(package)
        self.assertEqual(package["meta"]["title"], "Set {x} and } brace")
        self.assertEqual(package["question_count"], 1)


class TestClassify(unittest.TestCase):
    def test_filename_classifies_everything(self):
        html = make_html({"title": "Natural Resources"}, [{"id": "Q-1"}])
        record = intake.classify(Path("p2-social-c8-natural-resources-m01.html"), html)
        self.assertEqual(record["paper"], "Paper II")
        self.assertEqual(record["subject"], "Social Science")
        self.assertEqual(record["klass"], 8)
        self.assertEqual(record["lesson"], "Natural Resources")
        self.assertEqual(record["mock_label"], "Mock 1")
        self.assertEqual(record["source"], "filename")
        self.assertEqual(record["questions"], 1)
        self.assertEqual(record["name"], "p2-social-c8-natural-resources-m01.html")

    def test_sidecar_overrides_the_filename(self):
        html = make_html({"title": "Ignored"}, [])
        record = intake.classify(
            Path("p1-evs-c4-whatever-m01.html"),
            html,
            sidecar={
                "paper": "Paper II",
                "subject": "Science",
                "class": 8,
                "lesson": "Light",
                "title": "My own title",
                "mock": "Mock 4",
            },
        )
        self.assertEqual(record["source"], "sidecar")
        self.assertEqual(record["paper"], "Paper II")
        self.assertEqual(record["subject"], "Science")
        self.assertEqual(record["klass"], 8)
        self.assertEqual(record["lesson"], "Light")
        self.assertEqual(record["mock_label"], "Mock 4")
        self.assertEqual(record["title"], "My own title")

    def test_package_supplies_class_and_lesson(self):
        html = make_html(
            {"title": "Light", "source": "NCERT Grade 8, Science, Chapter 12",
             "status": "COMPREHENSIVE"},
            [{"id": "Q-1"}],
        )
        record = intake.classify(Path("mystery.html"), html)
        self.assertEqual(record["klass"], 8)
        self.assertEqual(record["lesson"], "Light")
        self.assertEqual(record["status"], "COMPREHENSIVE")
        self.assertEqual(record["source"], "package")

    def test_paper_is_inferred_from_the_class(self):
        html = make_html({"title": "Plants", "source": "Class 4 NCERT"}, [])
        record = intake.classify(Path("mystery.html"), html)
        self.assertEqual(record["klass"], 4)
        self.assertEqual(record["paper"], "Paper I")

        html = make_html({"title": "Plants", "source": "Class 7 NCERT"}, [])
        record = intake.classify(Path("mystery.html"), html)
        self.assertEqual(record["paper"], "Paper II")

    def test_file_with_no_signal_is_unclassified(self):
        record = intake.classify(Path("mystery.html"), "<html></html>")
        self.assertEqual(record["source"], "unclassified")
        self.assertIsNone(record["paper"])
        self.assertIsNone(record["subject"])
        self.assertIsNone(record["klass"])
        self.assertIsNone(record["lesson"])

    def test_lesson_slug_is_humanised(self):
        self.assertEqual(intake.humanise_slug("natural-resources"), "Natural Resources")
        self.assertEqual(intake.humanise_slug("light"), "Light")
        self.assertEqual(intake.humanise_slug("my-chapter-1"), "My Chapter 1")
        self.assertEqual(intake.humanise_slug(""), "")

    def test_title_combines_lesson_and_mock_label(self):
        html = make_html({"title": "Natural Resources"}, [])
        record = intake.classify(Path("p2-social-c8-natural-resources-m01.html"), html)
        self.assertEqual(record["title"], "Natural Resources · Mock 1")


if __name__ == "__main__":
    unittest.main()
