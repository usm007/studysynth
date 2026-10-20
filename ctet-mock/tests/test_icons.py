"""CTET Mock PWA — icon and manifest checks.

Run: python -m pytest ctet-mock/tests/test_icons.py -v
"""
from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "public" / "icons"
MANIFEST = ROOT / "public" / "manifest.webmanifest"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

EXPECTED_ICONS = {
    "icon-192.png": (192, 192),
    "icon-512.png": (512, 512),
    "icon-maskable-512.png": (512, 512),
    "apple-touch-icon.png": (180, 180),
    "favicon.png": (32, 32),
}


def png_size(data: bytes) -> tuple[int, int]:
    """Read width/height from a PNG IHDR chunk."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG")
    if data[12:16] != b"IHDR":
        raise ValueError("missing IHDR")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


class TestIconFiles(unittest.TestCase):
    def test_every_expected_icon_exists(self):
        for name in EXPECTED_ICONS:
            self.assertTrue((ICONS / name).is_file(), f"missing icon {name}")

    def test_icons_are_valid_png_files(self):
        for name in EXPECTED_ICONS:
            data = (ICONS / name).read_bytes()
            self.assertTrue(
                data.startswith(PNG_SIGNATURE),
                f"{name} is not a PNG (bad signature)",
            )
            self.assertTrue(data.endswith(b"IEND\xae\x42\x60\x82"), f"{name} has no IEND")

    def test_icon_dimensions_match_their_purpose(self):
        for name, (w, h) in EXPECTED_ICONS.items():
            data = (ICONS / name).read_bytes()
            self.assertEqual(png_size(data), (w, h), f"{name} has the wrong size")

    def test_icons_are_not_blank(self):
        """A blank icon would install but show nothing on the home screen."""
        for name in EXPECTED_ICONS:
            data = (ICONS / name).read_bytes()
            # IEND + IHDR + at least one non-trivial IDAT payload.
            self.assertGreater(len(data), 200, f"{name} looks empty")


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_manifest_is_named_ctet_mock(self):
        self.assertEqual(self.manifest["name"], "CTET Mock")
        self.assertEqual(self.manifest["short_name"], "CTET Mock")

    def test_manifest_is_installable_and_standalone(self):
        self.assertEqual(self.manifest["display"], "standalone")
        self.assertEqual(self.manifest["start_url"], "./")
        self.assertEqual(self.manifest["scope"], "./")
        self.assertIn("theme_color", self.manifest)
        self.assertIn("background_color", self.manifest)

    def test_manifest_declares_a_maskable_icon(self):
        purposes = [i.get("purpose", "") for i in self.manifest["icons"]]
        self.assertTrue(
            any("maskable" in p for p in purposes),
            "no maskable icon declared",
        )

    def test_manifest_icon_sources_all_exist(self):
        for icon in self.manifest["icons"]:
            src = icon["src"]
            self.assertTrue(
                (ROOT / "public" / src).is_file(),
                f"manifest references missing icon {src}",
            )

    def test_manifest_has_no_remote_resources(self):
        raw = MANIFEST.read_text(encoding="utf-8")
        self.assertNotIn("http://", raw)
        self.assertNotIn("https://", raw)


if __name__ == "__main__":
    unittest.main()
