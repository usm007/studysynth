"""CTET Mock PWA — offline worker and build command checks.

Run: python -m pytest ctet-mock/tests/test_sw.py -v
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


class TestRewriteTitle(unittest.TestCase):
    def test_rewrites_the_title_inside_the_package(self):
        html = make_mock_html({"title": "Old"}, [{"id": "Q-1"}])
        out = intake.rewrite_package_title(html, "New")
        self.assertEqual(intake.read_package(out)["meta"]["title"], "New")

    def test_leaves_the_rest_of_the_document_alone(self):
        html = make_mock_html({"title": "Old"}, [{"id": "Q-1"}])
        out = intake.rewrite_package_title(html, "New")
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        self.assertTrue(out.endswith("</body></html>"))
        self.assertEqual(out.count("Q-1"), html.count("Q-1"))

    def test_preserves_the_other_metadata(self):
        html = make_mock_html(
            {"title": "Old", "status": "COMPREHENSIVE", "source": "NCERT Grade 8"},
            [],
        )
        package = intake.read_package(intake.rewrite_package_title(html, "New"))
        self.assertEqual(package["meta"]["status"], "COMPREHENSIVE")
        self.assertEqual(package["meta"]["source"], "NCERT Grade 8")

    def test_documents_without_a_package_are_untouched(self):
        html = "<html><body>hi</body></html>"
        self.assertEqual(intake.rewrite_package_title(html, "New"), html)

    def test_rewriting_twice_changes_nothing_the_second_time(self):
        html = make_mock_html({"title": "Old"}, [])
        once = intake.rewrite_package_title(html, "New")
        twice = intake.rewrite_package_title(once, "New")
        self.assertEqual(once, twice)


class TestVersion(unittest.TestCase):
    def test_version_is_twelve_hex_characters(self):
        version = sw_mod.compute_version([("a.html", b"x")])
        self.assertEqual(len(version), 12)
        int(version, 16)

    def test_version_is_stable_for_the_same_content(self):
        self.assertEqual(
            sw_mod.compute_version([("a.html", b"x"), ("b.html", b"y")]),
            sw_mod.compute_version([("b.html", b"y"), ("a.html", b"x")]),
        )

    def test_version_changes_when_a_file_changes(self):
        self.assertNotEqual(
            sw_mod.compute_version([("a.html", b"x")]),
            sw_mod.compute_version([("a.html", b"z")]),
        )

    def test_version_changes_when_a_file_is_added(self):
        self.assertNotEqual(
            sw_mod.compute_version([("a.html", b"x")]),
            sw_mod.compute_version([("a.html", b"x"), ("b.html", b"y")]),
        )


class TestServiceWorker(unittest.TestCase):
    def setUp(self):
        self.source = sw_mod.render_service_worker(
            "abc123def456",
            ["./", "index.html", "catalog.json", "mocks/a.html", "mocks/b.html"],
        )

    def test_precache_lists_every_asset(self):
        for url in ("mocks/a.html", "mocks/b.html", "index.html", "catalog.json"):
            self.assertIn(f'"{url}"', self.source)

    def test_has_the_four_lifecycle_handlers(self):
        for handler in ("install", "activate", "fetch", "message"):
            self.assertIn(f'"{handler}"', self.source)

    def test_one_failed_download_does_not_abort_the_install(self):
        self.assertIn("Promise.allSettled", self.source)

    def test_cache_name_carries_the_version(self):
        self.assertIn("ctet-mock-abc123def456", self.source)

    def test_has_no_remote_urls(self):
        self.assertNotIn("http://", self.source)
        self.assertNotIn("https://", self.source)

    def test_ignores_non_get_and_cross_origin_requests(self):
        self.assertIn('request.method !== "GET"', self.source)
        self.assertIn("self.location.origin", self.source)


class TestBuildCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.public = self.tmp / "public"
        (self.public / "mocks").mkdir(parents=True)
        (self.public / "index.html").write_text("<html></html>", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_mock(self, name, title="Natural Resources", questions=3):
        html = make_mock_html({"title": title}, [{"id": f"Q-{i}"} for i in range(questions)])
        (self.public / "mocks" / name).write_text(html, encoding="utf-8")

    def test_build_writes_the_catalogue_and_the_worker(self):
        self.add_mock("p2-social-c8-natural-resources-m01.html")
        code = build_mod.build(self.public)
        self.assertEqual(code, 0)
        catalog = json.loads((self.public / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["counts"]["mocks"], 1)
        self.assertEqual(catalog["mocks"][0]["file"],
                         "mocks/p2-social-c8-natural-resources-m01.html")
        self.assertTrue((self.public / "sw.js").is_file())
        worker = (self.public / "sw.js").read_text(encoding="utf-8")
        self.assertIn("mocks/p2-social-c8-natural-resources-m01.html", worker)

    def test_build_gives_every_mock_a_unique_saved_session(self):
        self.add_mock("p2-social-c8-natural-resources-m01.html")
        self.add_mock("p2-social-c8-natural-resources-m02.html")
        build_mod.build(self.public)
        catalog = json.loads((self.public / "catalog.json").read_text(encoding="utf-8"))
        keys = [m["sessionKey"] for m in catalog["mocks"]]
        self.assertEqual(len(set(keys)), 2)
        titles = [m["title"] for m in catalog["mocks"]]
        self.assertEqual(len(set(titles)), 2)

    def test_build_rewrites_the_mock_title(self):
        self.add_mock("p2-social-c8-natural-resources-m01.html",
                      title="Natural Resources")
        build_mod.build(self.public)
        html = (self.public / "mocks" /
                "p2-social-c8-natural-resources-m01.html").read_text(encoding="utf-8")
        self.assertEqual(intake.read_package(html)["meta"]["title"],
                         "Mock 1 · Natural Resources")

    def test_build_can_leave_the_mock_title_alone(self):
        self.add_mock("p2-social-c8-natural-resources-m01.html",
                      title="Natural Resources")
        build_mod.build(self.public, retitle=False)
        html = (self.public / "mocks" /
                "p2-social-c8-natural-resources-m01.html").read_text(encoding="utf-8")
        self.assertEqual(intake.read_package(html)["meta"]["title"],
                         "Natural Resources")
        catalog = json.loads((self.public / "catalog.json").read_text(encoding="utf-8"))
        # The saved session still has to be found under the title the mock
        # actually uses.
        self.assertEqual(catalog["mocks"][0]["sessionKey"],
                         "quiz_session_v2_Natural_Resources")

    def test_unclassified_mock_fails_the_build(self):
        self.add_mock("mystery.html")
        code = build_mod.build(self.public)
        self.assertNotEqual(code, 0)
        catalog = json.loads((self.public / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["papers"][0]["name"], "Unclassified")

    def test_allow_unclassified_passes_the_build(self):
        self.add_mock("mystery.html")
        self.assertEqual(build_mod.build(self.public, allow_unclassified=True), 0)

    def test_build_is_idempotent(self):
        self.add_mock("p2-social-c8-natural-resources-m01.html")
        build_mod.build(self.public)
        first = json.loads((self.public / "catalog.json").read_text(encoding="utf-8"))
        build_mod.build(self.public)
        second = json.loads((self.public / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(first["version"], second["version"])
        self.assertEqual(first["mocks"][0]["title"], second["mocks"][0]["title"])

    def test_version_changes_when_a_mock_changes(self):
        self.add_mock("p2-social-c8-natural-resources-m01.html")
        build_mod.build(self.public)
        first = json.loads((self.public / "catalog.json").read_text(encoding="utf-8"))
        self.add_mock("p2-social-c8-natural-resources-m01.html", questions=9)
        build_mod.build(self.public)
        second = json.loads((self.public / "catalog.json").read_text(encoding="utf-8"))
        self.assertNotEqual(first["version"], second["version"])

    def test_empty_library_builds_cleanly(self):
        code = build_mod.build(self.public)
        self.assertEqual(code, 0)
        catalog = json.loads((self.public / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["papers"], [])
        self.assertEqual(catalog["counts"]["mocks"], 0)


class TestDeployment(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(
            (ROOT / "vercel.json").read_text(encoding="utf-8")
        )

    def test_vercel_config_is_valid_json(self):
        self.assertIsInstance(self.config, dict)

    def test_serves_the_public_folder(self):
        self.assertEqual(self.config["outputDirectory"], "public")

    def test_does_not_rewrite_urls(self):
        self.assertFalse(self.config.get("cleanUrls", False))

    def test_the_worker_is_never_cached_stale(self):
        sources = [rule["source"] for rule in self.config["headers"]]
        self.assertIn("/sw.js", sources)

    def test_the_catalogue_is_revalidated(self):
        sources = [rule["source"] for rule in self.config["headers"]]
        self.assertIn("/catalog.json", sources)

    def test_icons_are_cached_for_a_year(self):
        rules = {rule["source"]: rule for rule in self.config["headers"]}
        icons = rules.get("/icons/(.*)")
        self.assertIsNotNone(icons)
        value = icons["headers"][0]["value"]
        self.assertIn("immutable", value)

    def test_no_build_step_is_required(self):
        self.assertNotIn("buildCommand", self.config)


class TestSeedContent(unittest.TestCase):
    def test_a_demo_mock_is_published(self):
        mocks = ROOT / "public" / "mocks"
        files = sorted(mocks.glob("*.html"))
        self.assertTrue(files, "the library ships with no demo mock")

    def test_the_demo_mock_is_classified(self):
        from ctetmock import intake

        path = ROOT / "public" / "mocks" / "p2-social-c8-natural-resources-m01.html"
        self.assertTrue(path.is_file())
        record = intake.classify(path, path.read_text(encoding="utf-8"))
        self.assertEqual(record["paper"], "Paper II")
        self.assertEqual(record["subject"], "Social Science")
        self.assertEqual(record["klass"], 8)
        self.assertEqual(record["lesson"], "Natural Resources")
        self.assertEqual(record["mock_label"], "Mock 1")
        self.assertTrue(intake.is_complete(record))

    def test_the_demo_mock_carries_questions(self):
        from ctetmock import intake

        path = ROOT / "public" / "mocks" / "p2-social-c8-natural-resources-m01.html"
        package = intake.read_package(path.read_text(encoding="utf-8"))
        self.assertIsNotNone(package)
        self.assertGreater(package["question_count"], 0)


if __name__ == "__main__":
    unittest.main()
