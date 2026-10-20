"""CTET Mock PWA — catalogue assembly checks.

Run: python -m pytest ctet-mock/tests/test_catalog.py -v
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ctetmock import catalog  # noqa: E402
from helpers import make_record  # noqa: E402

VERSION = "abc123def456"


def expected_session_key(title: str) -> str:
    """The key the mock app itself uses to store its session."""
    return "quiz_session_v2_" + re.sub(r"\W+", "_", title)[:40]


class TestCatalogShape(unittest.TestCase):
    def setUp(self):
        self.records = [
            make_record(name="a.html", paper="Paper I", subject="Environmental Studies",
                        klass=4, lesson="Plants", mock_label="Mock 1",
                        title="Plants · Mock 1"),
            make_record(name="b.html", paper="Paper II", subject="Social Science",
                        klass=8, lesson="Natural Resources", mock_label="Mock 1",
                        title="Natural Resources · Mock 1"),
            make_record(name="c.html", paper="Paper II", subject="Social Science",
                        klass=8, lesson="Natural Resources", mock_label="Mock 2",
                        title="Natural Resources · Mock 2"),
            make_record(name="d.html", paper="Paper II", subject="Science",
                        klass=8, lesson="Light", mock_label="Mock 1",
                        title="Light · Mock 1"),
            make_record(name="e.html", paper="Paper II", subject="Science",
                        klass=7, lesson="Light", mock_label="Mock 1",
                        title="Light · Mock 1"),
        ]
        self.catalog = catalog.build_catalog(self.records, VERSION)

    def test_papers_are_ordered_with_paper_one_first(self):
        names = [p["name"] for p in self.catalog["papers"]]
        self.assertEqual(names, ["Paper I", "Paper II"])

    def test_paper_ids_are_readable(self):
        self.assertEqual(self.catalog["papers"][0]["id"], "paper-1")
        self.assertEqual(self.catalog["papers"][1]["id"], "paper-2")

    def test_subjects_follow_the_fixed_display_order(self):
        paper_two = self.catalog["papers"][1]
        names = [s["name"] for s in paper_two["subjects"]]
        self.assertEqual(names, ["Science", "Social Science"])

    def test_classes_are_ordered_numerically(self):
        science = self.catalog["papers"][1]["subjects"][0]
        names = [c["name"] for c in science["classes"]]
        self.assertEqual(names, ["Class 7", "Class 8"])

    def test_lessons_group_their_mocks(self):
        paper_two = self.catalog["papers"][1]
        social = paper_two["subjects"][1]
        klass = social["classes"][0]
        lesson = klass["lessons"][0]
        self.assertEqual(lesson["name"], "Natural Resources")
        self.assertEqual([m["name"] for m in lesson["mocks"]],
                         ["Mock 1", "Mock 2"])

    def test_mock_carries_its_file_and_counts(self):
        mock = self.catalog["papers"][1]["subjects"][1]["classes"][0]["lessons"][0]["mocks"][0]
        self.assertEqual(mock["file"], "mocks/b.html")
        self.assertEqual(mock["questions"], 10)
        self.assertEqual(mock["status"], "COMPREHENSIVE")

    def test_flat_mock_list_carries_full_ancestry(self):
        by_file = {m["file"]: m for m in self.catalog["mocks"]}
        mock = by_file["mocks/d.html"]
        self.assertEqual(mock["paper"], "Paper II")
        self.assertEqual(mock["subject"], "Science")
        self.assertEqual(mock["klass"], 8)
        self.assertEqual(mock["lesson"], "Light")
        self.assertEqual(mock["paperId"], self.catalog["papers"][1]["id"])
        self.assertEqual(mock["subjectId"],
                         self.catalog["papers"][1]["subjects"][0]["id"])
        self.assertEqual(mock["classId"],
                         self.catalog["papers"][1]["subjects"][0]["classes"][1]["id"])

    def test_counts_match_the_tree(self):
        counts = self.catalog["counts"]
        self.assertEqual(counts["mocks"], 5)
        self.assertEqual(counts["papers"], 2)
        self.assertEqual(counts["lessons"], 4)
        self.assertEqual(counts["classes"], 4)
        self.assertEqual(counts["subjects"], 3)

    def test_version_is_carried_through(self):
        self.assertEqual(self.catalog["version"], VERSION)

    def test_ids_are_unique(self):
        ids = [m["id"] for m in self.catalog["mocks"]]
        self.assertEqual(len(ids), len(set(ids)))


class TestSessionKeys(unittest.TestCase):
    def test_session_key_matches_the_mock_app_rule(self):
        built = catalog.build_catalog(
            [make_record(title="Natural Resources · Mock 1")], VERSION
        )
        mock = built["mocks"][0]
        self.assertEqual(mock["sessionKey"],
                         expected_session_key("Natural Resources · Mock 1"))

    def test_duplicate_titles_are_made_unique(self):
        built = catalog.build_catalog(
            [
                make_record(name="one.html", title="Light · Mock 1"),
                make_record(name="two.html", title="Light · Mock 1"),
            ],
            VERSION,
        )
        titles = [m["title"] for m in built["mocks"]]
        self.assertEqual(len(set(titles)), 2, "titles must be unique")
        keys = [m["sessionKey"] for m in built["mocks"]]
        self.assertEqual(len(set(keys)), 2, "session keys must be unique")
        for mock in built["mocks"]:
            self.assertEqual(mock["sessionKey"], expected_session_key(mock["title"]))


class TestEmptyAndUnclassified(unittest.TestCase):
    def test_empty_input_yields_an_empty_catalogue(self):
        built = catalog.build_catalog([], VERSION)
        self.assertEqual(built["papers"], [])
        self.assertEqual(built["mocks"], [])
        self.assertEqual(built["counts"],
                         {"papers": 0, "subjects": 0, "classes": 0,
                          "lessons": 0, "mocks": 0})

    def test_unclassified_mocks_land_in_a_visible_bucket(self):
        built = catalog.build_catalog(
            [make_record(name="mystery.html", paper=None, subject=None,
                         klass=None, lesson=None, mock_label=None,
                         title="mystery", source="unclassified")],
            VERSION,
        )
        self.assertEqual(len(built["papers"]), 1)
        paper = built["papers"][0]
        self.assertEqual(paper["name"], "Unclassified")
        mock = built["mocks"][0]
        self.assertEqual(mock["paper"], "Unclassified")
        self.assertEqual(mock["subject"], "Unclassified")
        self.assertEqual(mock["file"], "mocks/mystery.html")

    def test_unclassified_bucket_sorts_last(self):
        built = catalog.build_catalog(
            [
                make_record(name="mystery.html", paper=None, subject=None,
                            klass=None, lesson=None, mock_label=None,
                            title="mystery", source="unclassified"),
                make_record(name="ok.html", paper="Paper I",
                            subject="Environmental Studies", klass=3,
                            lesson="Plants", mock_label="Mock 1",
                            title="Plants · Mock 1"),
            ],
            VERSION,
        )
        self.assertEqual([p["name"] for p in built["papers"]],
                         ["Paper I", "Unclassified"])


if __name__ == "__main__":
    unittest.main()
