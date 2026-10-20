"""Screenshot the built CTET Mock site on a phone-sized screen.

A quick way to see the library without deploying it:

    python ctet-mock/tools/screenshot.py

The pictures land in build/ctet-mock-shots/.
"""
from __future__ import annotations

import functools
import http.server
import shutil
import socket
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

OUT = ROOT.parent / "build" / "ctet-mock-shots"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "public", tmp / "public")
    public = tmp / "public"
    port = free_port()
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(public)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, device_scale_factor=2
    )
    page = context.new_page()
    page.goto(f"http://127.0.0.1:{port}/index.html")
    page.wait_for_selector(".view-papers")
    page.screenshot(path=str(OUT / "01-papers.png"))

    page.click('[data-go="paper"][data-id="paper-2"]')
    page.wait_for_selector(".view-subjects")
    page.screenshot(path=str(OUT / "02-subjects.png"))

    page.click('.view-subjects button:has-text("Social Science")')
    page.wait_for_selector(".view-classes")
    page.screenshot(path=str(OUT / "03-classes.png"))

    page.click('.view-classes button:has-text("Class 8")')
    page.wait_for_selector(".view-lessons")
    page.screenshot(path=str(OUT / "04-lessons.png"))

    page.click('.view-lessons button:has-text("Natural Resources")')
    page.wait_for_selector(".view-mocks")
    page.screenshot(path=str(OUT / "05-mocks.png"))

    href = page.get_attribute(".mock-card", "href")
    page.goto(f"http://127.0.0.1:{port}/{href}")
    page.wait_for_selector("#playerFrame")
    page.frame_locator("#playerFrame").locator("#qstem").wait_for(timeout=30000)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / "06-player.png"))

    context.close()
    browser.close()
    playwright.stop()
    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"shots written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
