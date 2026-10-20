"""CTET Mock PWA — static checks on the landing page and the player.

Run: python -m pytest ctet-mock/tests/test_ui_static.py -v
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"

INDEX = PUBLIC / "index.html"
PLAYER = PUBLIC / "player.html"
APP_CSS = PUBLIC / "app.css"
APP_JS = PUBLIC / "app.js"
PLAYER_JS = PUBLIC / "player.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestLandingPage(unittest.TestCase):
    def setUp(self):
        self.html = read(INDEX)
        self.js = read(APP_JS)
        self.css = read(APP_CSS)

    def test_page_is_present(self):
        for path in (INDEX, APP_CSS, APP_JS):
            self.assertTrue(path.is_file(), f"missing {path.name}")

    def test_declares_the_manifest_and_the_app_icon(self):
        self.assertIn('rel="manifest"', self.html)
        self.assertIn("manifest.webmanifest", self.html)
        self.assertIn("icons/apple-touch-icon.png", self.html)

    def test_viewport_is_mobile_and_safe_area_aware(self):
        self.assertIn('name="viewport"', self.html)
        self.assertIn("width=device-width", self.html)
        self.assertIn("viewport-fit=cover", self.html)

    def test_theme_colour_matches_the_icon(self):
        self.assertIn('name="theme-color"', self.html)
        self.assertIn("#1e4634", self.html)

    def test_has_the_documented_dom_contract(self):
        for element_id in ("libApp", "appBar", "btnHome", "crumbs", "searchInput",
                           "view", "statusChip", "installBtn", "offlineBanner",
                           "updateBanner"):
            self.assertIn(f'id="{element_id}"', self.html,
                          f"missing #{element_id} in index.html")

    def test_has_the_documented_view_classes(self):
        source = self.html + self.js
        for class_name in ("view-papers", "view-subjects", "view-classes",
                           "view-lessons", "view-mocks", "view-all"):
            self.assertIn(class_name, source, f"missing .{class_name}")

    def test_has_the_documented_mock_card_contract(self):
        source = self.html + self.js
        for token in ("mock-title", "mock-badges", "mock-progress", "mock-open",
                      "data-mock-id"):
            self.assertIn(token, source, f"missing {token}")

    def test_exposes_a_small_public_api_for_the_tests(self):
        self.assertIn("window.CTETMock", self.js)
        for member in ("load", "navigate", "state"):
            self.assertIn(member, self.js)

    def test_reads_the_catalogue(self):
        self.assertIn("catalog.json", self.js)

    def test_reads_the_saved_session_for_the_progress_chip(self):
        self.assertIn("localStorage", self.js)
        self.assertIn("sessionKey", self.js)

    def test_offers_an_install_path_and_a_fallback_for_browsers_without_a_prompt(self):
        source = self.html + self.js
        self.assertIn("beforeinstallprompt", source)
        self.assertIn("Add to Home Screen", source)

    def test_registers_the_service_worker(self):
        self.assertIn("serviceWorker", self.js)

    def test_has_no_remote_resources(self):
        for path in (INDEX, APP_CSS, APP_JS):
            text = read(path)
            self.assertNotIn("http://", text, f"{path.name} references a remote URL")
            self.assertNotIn("https://", text, f"{path.name} references a remote URL")

    def test_stylesheet_has_no_imports(self):
        self.assertNotIn("@import", self.css)

    def test_uses_the_warm_study_desk_tokens(self):
        for token in ("--bg", "--surface", "--ink", "--accent"):
            self.assertIn(token, self.css)

    def test_touch_targets_are_large_enough(self):
        collapsed = "".join(self.css.split())
        self.assertIn("min-height:44px", collapsed)
        for value in re.findall(r"min-height:(\d+)px", self.css):
            self.assertGreaterEqual(int(value), 44,
                                    "a control is smaller than 44px")

    def test_the_player_reserves_the_home_indicator_space(self):
        collapsed = "".join(self.css.split())
        self.assertIn("#playerFrame{", collapsed)
        frame_rule = collapsed.split("#playerFrame{")[1].split("}")[0]
        self.assertIn("env(safe-area-inset-bottom)", frame_rule)

    def test_hidden_elements_stay_hidden(self):
        """A class with its own display rule must not defeat [hidden]."""
        collapsed = "".join(self.css.split())
        self.assertIn("[hidden]{display:none!important", collapsed)

    def test_offline_banner_reports_real_cache_progress(self):
        source = self.html + self.js
        self.assertIn("offlineBanner", source)
        # The worker owns the Cache API; the app asks it how far it has got.
        self.assertIn("CACHE_STATUS", source)
        self.assertIn("cached", source)


class TestPlayerPage(unittest.TestCase):
    def setUp(self):
        self.html = read(PLAYER)
        self.js = read(PLAYER_JS)

    def test_player_files_exist(self):
        for path in (PLAYER, PLAYER_JS):
            self.assertTrue(path.is_file(), f"missing {path.name}")

    def test_has_the_documented_dom_contract(self):
        for element_id in ("playerBar", "playerBack", "playerTitle",
                           "playerOpen", "playerFrame", "playerError"):
            self.assertIn(f'id="{element_id}"', self.html,
                          f"missing #{element_id} in player.html")

    def test_resolves_the_mock_from_the_query_string(self):
        self.assertIn("location.search", self.js)
        self.assertIn("m=", self.js)

    def test_sets_the_document_title_to_the_mock_title(self):
        self.assertIn("document.title", self.js)

    def test_has_a_fallback_when_the_paper_cannot_be_opened(self):
        self.assertIn("playerError", self.html)
        self.assertIn("playerError", self.js)

    def test_has_no_remote_resources(self):
        for path in (PLAYER, PLAYER_JS):
            text = read(path)
            self.assertNotIn("http://", text)
            self.assertNotIn("https://", text)


class TestJavaScriptSyntax(unittest.TestCase):
    """A typo in a script must fail fast, not at runtime on a phone."""

    def test_scripts_parse(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        for name in ("app.js", "player.js"):
            with self.subTest(script=name):
                result = subprocess.run(
                    [node, "--check", str(PUBLIC / name)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0,
                                 f"{name} does not parse:\n{result.stderr}")


if __name__ == "__main__":
    unittest.main()
