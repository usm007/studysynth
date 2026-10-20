"""CTET Mock PWA — hardening checks for the failures a real library hits.

Run: python -m pytest ctet-mock/tests/test_hardening.py -v
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ctetmock import build as build_mod  # noqa: E402
from ctetmock import intake  # noqa: E402
from ctetmock import sw as sw_mod  # noqa: E402
from helpers import make_mock_html  # noqa: E402


class BuildCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.public = self.tmp / "public"
        (self.public / "mocks").mkdir(parents=True)
        (self.public / "index.html").write_text("<html></html>", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_mock(self, name, title="Natural Resources", questions=3,
                 raw=None):
        path = self.public / "mocks" / name
        if raw is None:
            path.write_text(
                make_mock_html({"title": title},
                               [{"id": f"Q-{i}"} for i in range(questions)]),
                encoding="utf-8",
            )
        else:
            path.write_text(raw, encoding="utf-8")
        return path

    def catalogue(self):
        return json.loads(
            (self.public / "catalog.json").read_text(encoding="utf-8"))


class TestTitleStability(BuildCase):
    """A rebuild must never change a paper's title or its saved session."""

    def test_repeated_builds_do_not_grow_the_title(self):
        self.add_mock("p2-social-c8-m01.html", title="Natural Resources")
        build_mod.build(self.public)
        first = self.catalogue()["mocks"][0]
        build_mod.build(self.public)
        second = self.catalogue()["mocks"][0]
        self.assertEqual(first["title"], second["title"])
        self.assertEqual(first["sessionKey"], second["sessionKey"])

    def test_repeated_builds_do_not_change_the_version(self):
        self.add_mock("p2-social-c8-m01.html", title="Natural Resources")
        build_mod.build(self.public)
        first = self.catalogue()["version"]
        build_mod.build(self.public)
        self.assertEqual(first, self.catalogue()["version"])

    def test_the_mock_file_keeps_its_title_after_a_rebuild(self):
        path = self.add_mock("p2-social-c8-m01.html", title="Natural Resources")
        build_mod.build(self.public)
        first = intake.read_package(path.read_text(encoding="utf-8"))["meta"]["title"]
        build_mod.build(self.public)
        second = intake.read_package(path.read_text(encoding="utf-8"))["meta"]["title"]
        self.assertEqual(first, second)

    def test_adding_a_mock_does_not_rename_an_existing_one(self):
        self.add_mock("p1-evs-c4-light.html", title="Light")
        build_mod.build(self.public)
        before = self.catalogue()["mocks"][0]
        self.add_mock("p2-sci-c8-light.html", title="Light")
        build_mod.build(self.public)
        after = [m for m in self.catalogue()["mocks"]
                 if m["file"].endswith("p1-evs-c4-light.html")][0]
        self.assertEqual(before["title"], after["title"])
        self.assertEqual(before["sessionKey"], after["sessionKey"])

    def test_long_lesson_names_still_get_distinct_sessions(self):
        long = "Light Reflection And Refraction And Its Applications"
        self.add_mock("p2-sci-c8-light-reflection-and-refraction-m01.html",
                      title=long)
        self.add_mock("p2-sci-c8-light-reflection-and-refraction-m02.html",
                      title=long)
        build_mod.build(self.public)
        keys = [m["sessionKey"] for m in self.catalogue()["mocks"]]
        self.assertEqual(len(set(keys)), 2, "session keys must not collide")

    def test_the_title_carries_the_mock_label_first(self):
        self.add_mock("p2-social-c8-natural-resources-m01.html")
        build_mod.build(self.public)
        title = self.catalogue()["mocks"][0]["title"]
        self.assertTrue(title.startswith("Mock 1"), title)


class TestBadInput(BuildCase):
    def test_a_mock_without_a_package_is_rejected(self):
        self.add_mock("p2-social-c8-broken-m01.html",
                      raw="<!DOCTYPE html><html><body>truncated")
        self.assertNotEqual(build_mod.build(self.public), 0)

    def test_a_mock_with_no_questions_is_rejected(self):
        self.add_mock("p2-social-c8-empty-m01.html", questions=0)
        self.assertNotEqual(build_mod.build(self.public), 0)

    def test_a_file_that_is_not_a_mock_is_reported(self):
        (self.public / "mocks" / "notes.txt").write_text("hello", encoding="utf-8")
        self.add_mock("p2-social-c8-natural-resources-m01.html")
        self.assertNotEqual(build_mod.build(self.public), 0)

    def test_a_filename_with_a_hash_is_rejected(self):
        self.add_mock("p2-social-c8-light#1-m01.html")
        self.assertNotEqual(build_mod.build(self.public), 0)

    def test_a_filename_with_a_space_is_rejected(self):
        self.add_mock("p2 social c8 light m01.html")
        self.assertNotEqual(build_mod.build(self.public), 0)

    def test_a_sidecar_is_not_mistaken_for_a_mock(self):
        self.add_mock("p2-social-c8-natural-resources-m01.html")
        (self.public / "mocks" / "p2-social-c8-natural-resources-m01.meta.json") \
            .write_text(json.dumps({"lesson": "Natural Resources"}), encoding="utf-8")
        self.assertEqual(build_mod.build(self.public), 0)


class TestFilenameHandling(unittest.TestCase):
    def test_a_subject_word_in_the_lesson_is_kept(self):
        tokens = intake.parse_tokens("p2-c8-science-chapter-1-m01")
        self.assertIsNone(tokens["subject"])
        self.assertEqual(tokens["lesson_slug"], "science-chapter-1")

    def test_the_convention_order_still_works(self):
        tokens = intake.parse_tokens("p2-social-c8-natural-resources-m01")
        self.assertEqual(tokens["paper"], "Paper II")
        self.assertEqual(tokens["subject"], "Social Science")
        self.assertEqual(tokens["klass"], 8)
        self.assertEqual(tokens["lesson_slug"], "natural-resources")

    def test_the_build_keeps_the_line_endings_of_a_mock(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            public = tmp / "public"
            (public / "mocks").mkdir(parents=True)
            path = public / "mocks" / "p2-social-c8-light-m01.html"
            body = ("<!DOCTYPE html>\n<html>\n<body>\n" +
                    make_mock_html({"title": "Light"}, [{"id": "Q-1"}]) +
                    "\n</body>\n</html>\n")
            path.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
            build_mod.build(public)
            self.assertIn(b"\r\n", path.read_bytes())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestWorkerBehaviour(unittest.TestCase):
    def setUp(self):
        self.source = sw_mod.render_service_worker(
            "abc123def456", ["./", "index.html", "mocks/a.html"])

    def test_the_worker_waits_before_taking_over(self):
        install_block = self.source.split('"install"')[1].split('"activate"')[0]
        self.assertNotIn("skipWaiting", install_block,
                         "the worker must wait so the refresh button works")

    def test_the_worker_reports_what_it_could_not_cache(self):
        self.assertIn("failed", self.source)

    def test_the_worker_does_not_serve_the_library_for_a_paper(self):
        catch_block = self.source.split("catch (error)")[1]
        self.assertIn("mocks/", catch_block)

    def test_a_quote_in_a_path_cannot_break_the_worker(self):
        source = sw_mod.render_service_worker("abc123def456",
                                               ['mocks/we"ird.html'])
        self.assertIn('we\\"ird', source)
        self.assertNotIn('"mocks/we"ird.html"', source)


class TestCommittedArtefacts(unittest.TestCase):
    """The published worker must match the published library."""

    def test_the_worker_declares_the_published_version(self):
        public = ROOT / "public"
        catalog = json.loads(
            (public / "catalog.json").read_text(encoding="utf-8"))
        worker = (public / "sw.js").read_text(encoding="utf-8")
        self.assertIn(f'const VERSION = "{catalog["version"]}"', worker)

    def test_the_worker_caches_every_published_paper(self):
        public = ROOT / "public"
        catalog = json.loads(
            (public / "catalog.json").read_text(encoding="utf-8"))
        worker = (public / "sw.js").read_text(encoding="utf-8")
        for mock in catalog["mocks"]:
            self.assertIn(f'"{mock["file"]}"', worker)


if __name__ == "__main__":
    unittest.main()
