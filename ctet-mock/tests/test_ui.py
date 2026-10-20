"""CTET Mock PWA â€” browser and offline checks.

These run a real Chromium against the built site: the drill-down, the search,
the player, and the library with the network switched off.

Run: python -m pytest ctet-mock/tests/test_ui.py -v
"""
from __future__ import annotations

import functools
import http.server
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ctetmock import build as build_mod  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(FIXTURES))
from make_fixture_mock import write_fixture_mock  # noqa: E402

try:
    from playwright.sync_api import sync_playwright

    HAVE_PLAYWRIGHT = True
except ImportError:  # pragma: no cover - environment without playwright
    HAVE_PLAYWRIGHT = False


SHELL = [
    "index.html", "app.css", "app.js", "player.html", "player.js",
    "manifest.webmanifest",
    "icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-512.png",
    "icons/apple-touch-icon.png", "icons/favicon.png",
]

FIXTURE_MOCKS = [
    ("p1-evs-c4-plants-m01.html", "Plants", "Which part of the plant makes food?"),
    ("p2-social-c8-natural-resources-m01.html", "Natural Resources",
     "How do people use natural resources?"),
    ("p2-sci-c8-light-m01.html", "Light", "Which property of light travels in a straight line?"),
]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SiteFixture:
    """A built copy of the site, served over http for the browser tests."""

    def __init__(self, fail_paths=None):
        self.fail_paths = set(fail_paths or ())
        self.root = Path(tempfile.mkdtemp())
        self.public = self.root / "public"
        self.public.mkdir(parents=True)
        for name in SHELL:
            source = ROOT / "public" / name
            if source.is_file():
                target = self.public / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        mocks = self.public / "mocks"
        mocks.mkdir(parents=True, exist_ok=True)
        for name, title, stem in FIXTURE_MOCKS:
            write_fixture_mock(mocks, name, title, stem=stem)
        self.exit_code = build_mod.build(self.public, quiet=True)
        self.port = free_port()
        fixture = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path in fixture.fail_paths:
                    self.send_error(500, "paper unavailable")
                    return
                super().do_GET()

        handler = functools.partial(Handler, directory=str(self.public))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def publish_new_version(self):
        """Change the worker so the browser sees an update waiting to apply."""
        import os
        import time

        worker = self.public / "sw.js"
        worker.write_text(
            worker.read_text(encoding="utf-8").replace(
                'const VERSION = "', 'const VERSION = "new-', 1
            ),
            encoding="utf-8",
        )
        # The server answers 304 when the file's timestamp has not moved on.
        stamp = time.time() + 2
        os.utime(worker, (stamp, stamp))

    def close(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except OSError:
            pass
        shutil.rmtree(self.root, ignore_errors=True)


@unittest.skipUnless(HAVE_PLAYWRIGHT, "playwright is not installed")
class BrowserTestCase(unittest.TestCase):
    site: SiteFixture
    playwright = None
    browser = None

    @classmethod
    def setUpClass(cls):
        cls.site = SiteFixture()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - no browser binary
            cls.playwright.stop()
            cls.site.close()
            raise unittest.SkipTest(f"chromium is unavailable: {error}")

    @classmethod
    def tearDownClass(cls):
        if cls.browser:
            cls.browser.close()
        if cls.playwright:
            cls.playwright.stop()
        cls.site.close()

    def open_landing(self, context=None):
        page = (context or self.browser).new_page()
        page.goto(f"{self.site.base}/index.html")
        page.wait_for_selector(".view-papers")
        return page

    def wait_for_offline_ready(self, page):
        page.wait_for_function(
            "() => { const chip = document.getElementById('statusChip');"
            " return chip && chip.textContent.toLowerCase()"
            ".indexOf('ready offline') >= 0; }",
            timeout=60000,
        )


class TestLandingInBrowser(BrowserTestCase):
    def test_lists_the_papers(self):
        page = self.open_landing()
        try:
            text = page.inner_text(".view-papers")
            self.assertIn("Paper I", text)
            self.assertIn("Paper II", text)
        finally:
            page.close()

    def test_drills_down_to_a_mock(self):
        page = self.open_landing()
        try:
            page.click('[data-go="paper"][data-id="paper-2"]')
            page.wait_for_selector(".view-subjects")
            self.assertIn("Social Science", page.inner_text(".view-subjects"))

            page.click('.view-subjects button:has-text("Social Science")')
            page.wait_for_selector(".view-classes")
            self.assertIn("Class 8", page.inner_text(".view-classes"))

            page.click('.view-classes button:has-text("Class 8")')
            page.wait_for_selector(".view-lessons")
            self.assertIn("Natural Resources", page.inner_text(".view-lessons"))

            page.click('.view-lessons button:has-text("Natural Resources")')
            page.wait_for_selector(".view-mocks")
            card = page.query_selector(".mock-card")
            self.assertIsNotNone(card)
            self.assertIn("player.html?m=", card.get_attribute("href"))
            self.assertIn("Mock 1", page.inner_text(".view-mocks"))
        finally:
            page.close()

    def test_mock_card_shows_its_badge(self):
        page = self.open_landing()
        try:
            page.click('[data-go="paper"][data-id="paper-2"]')
            page.wait_for_selector(".view-subjects")
            page.click('.view-subjects button:has-text("Social Science")')
            page.wait_for_selector(".view-classes")
            page.click('.view-classes button:has-text("Class 8")')
            page.wait_for_selector(".view-lessons")
            page.click('.view-lessons button:has-text("Natural Resources")')
            page.wait_for_selector(".view-mocks")
            badges = page.inner_text(".mock-badges")
            self.assertIn("Paper II", badges)
            self.assertIn("Social Science", badges)
            self.assertIn("Class 8", badges)
        finally:
            page.close()

    def test_card_title_and_subtitle_are_on_separate_lines(self):
        page = self.open_landing()
        try:
            display = page.eval_on_selector(
                ".view-papers .card-title", "el => getComputedStyle(el).display")
            self.assertEqual(display, "block")
        finally:
            page.close()

    def test_breadcrumb_tracks_the_drill_down(self):
        page = self.open_landing()
        try:
            page.click('[data-go="paper"][data-id="paper-2"]')
            page.wait_for_selector(".view-subjects")
            crumbs = page.inner_text("#crumbs")
            self.assertIn("Library", crumbs)
            self.assertIn("Paper II", crumbs)
        finally:
            page.close()

    def test_search_filters_the_library(self):
        page = self.open_landing()
        try:
            page.fill("#searchInput", "light")
            page.wait_for_selector(".view-all")
            titles = page.inner_text(".view-all")
            self.assertIn("Light", titles)
            self.assertNotIn("Natural Resources", titles)
        finally:
            page.close()

    def test_shows_the_saved_progress_of_a_mock(self):
        page = self.open_landing()
        try:
            session_key = page.evaluate(
                """async () => {
                  const catalog = await (await fetch('catalog.json')).json();
                  const mock = catalog.mocks.filter(m => m.lesson === 'Natural Resources')[0];
                  return mock.sessionKey;
                }"""
            )
            page.evaluate(
                """(key) => {
                  localStorage.setItem(key, JSON.stringify({answers: {'Q-0001': 'A'}}));
                }""",
                session_key,
            )
            page.reload()
            page.wait_for_selector(".view-papers")
            page.fill("#searchInput", "Natural Resources")
            page.wait_for_selector(".view-all")
            self.assertIn("In progress", page.inner_text(".view-all"))
        finally:
            page.close()


class TestPlayerInBrowser(BrowserTestCase):
    def test_opens_the_paper_in_the_frame(self):
        page = self.open_landing()
        try:
            page.fill("#searchInput", "light")
            page.wait_for_selector(".view-all")
            href = page.get_attribute(".mock-card", "href")
            page.goto(f"{self.site.base}/{href}")
            page.wait_for_selector("#playerFrame")
            frame = page.frame_locator("#playerFrame")
            frame.locator("#qstem").wait_for(timeout=30000)
            self.assertIn(
                "straight line",
                frame.locator("#qstem").inner_text(),
            )
        finally:
            page.close()

    def test_the_frame_title_names_the_paper(self):
        page = self.open_landing()
        try:
            page.fill("#searchInput", "light")
            page.wait_for_selector(".view-all")
            href = page.get_attribute(".mock-card", "href")
            page.goto(f"{self.site.base}/{href}")
            page.wait_for_function(
                "() => { const t = document.getElementById('playerTitle');"
                " return t && t.textContent.indexOf('Light') >= 0; }",
                timeout=30000,
            )
        finally:
            page.close()


class TestOfflineInBrowser(BrowserTestCase):
    def test_library_and_papers_work_with_the_network_off(self):
        context = self.browser.new_context()
        page = self.open_landing(context)
        try:
            self.wait_for_offline_ready(page)
            context.set_offline(True)
            page.reload()
            page.wait_for_selector(".view-papers")
            self.assertIn("Paper II", page.inner_text(".view-papers"))

            page.click('[data-go="paper"][data-id="paper-2"]')
            page.wait_for_selector(".view-subjects")
            page.click('.view-subjects button:has-text("Social Science")')
            page.wait_for_selector(".view-classes")
            page.click('.view-classes button:has-text("Class 8")')
            page.wait_for_selector(".view-lessons")
            page.click('.view-lessons button:has-text("Natural Resources")')
            page.wait_for_selector(".view-mocks")
            href = page.get_attribute(".mock-card", "href")
            page.goto(f"{self.site.base}/{href}")
            page.wait_for_selector("#playerFrame")
            frame = page.frame_locator("#playerFrame")
            frame.locator("#qstem").wait_for(timeout=30000)
            self.assertIn("natural resources", frame.locator("#qstem").inner_text())
        finally:
            context.set_offline(False)
            page.close()
            context.close()


class TestOfflineReporting(unittest.TestCase):
    """A paper that cannot be cached must be named, not hidden."""

    def setUp(self):
        self.site = SiteFixture(fail_paths={"/mocks/p2-sci-c8-light-m01.html"})
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch()
        self.context = self.browser.new_context()
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()
        self.site.close()

    def test_the_app_does_not_claim_to_be_ready_when_a_paper_is_missing(self):
        page = self.page
        page.goto(f"{self.site.base}/index.html")
        page.wait_for_selector(".view-papers")
        page.wait_for_function(
            "() => { const chip = document.getElementById('statusChip');"
            " return chip && chip.textContent.indexOf('unavailable') >= 0; }",
            timeout=60000,
        )
        chip = page.inner_text("#statusChip")
        self.assertNotIn("ready offline", chip.lower())
        banner = page.inner_text("#offlineBanner")
        self.assertIn("light", banner.lower())

    def test_a_paper_missing_offline_shows_the_error_panel(self):
        page = self.page
        page.goto(f"{self.site.base}/index.html")
        page.wait_for_selector(".view-papers")
        page.wait_for_timeout(6000)
        self.context.set_offline(True)
        try:
            page.goto(f"{self.site.base}/player.html?m=paper-2__subject-science__class-class-8__lesson-light__mock-mock-1")
            page.wait_for_selector("#playerError", state="visible", timeout=20000)
        finally:
            self.context.set_offline(False)


@unittest.skipUnless(HAVE_PLAYWRIGHT, "playwright is not installed")
class TestUpdateInBrowser(BrowserTestCase):
    def test_a_new_library_reaches_the_device(self):
        page = self.open_landing()
        try:
            self.wait_for_offline_ready(page)
            self.site.publish_new_version()
            page.reload()
            page.wait_for_selector(".view-papers")
            page.wait_for_selector("#updateBanner", state="visible", timeout=30000)
            page.click("#updateBtn")
            page.wait_for_function(
                """async () => {
                  const names = await caches.keys();
                  return names.some(n => n.indexOf('new-') >= 0);
                }""",
                timeout=30000,
            )
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
