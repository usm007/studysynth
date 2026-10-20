"""Generate the CTET Mock PWA icons with the standard library only.

The mark is a cream study sheet on a deep forest rounded square, with three
subject rules and a green "verified" badge at the lower right. It is drawn
procedurally so the repository needs no image assets and no dependencies.

Usage:
    python ctet-mock/tools/make_icons.py
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = ROOT / "public" / "icons"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Palette (Warm Study Desk family, M3 primary deepened for the app icon).
FOREST = (0x1E, 0x46, 0x34)
CREAM = (0xF5, 0xF2, 0xE9)
RULE = (0x31, 0x5D, 0x49)
BADGE = (0x20, 0x5F, 0x35)

SUPERSAMPLE = 3


# --------------------------------------------------------------------------
# Geometry helpers. All shapes take normalised coordinates (0..1, y down).
# --------------------------------------------------------------------------


def in_rounded_rect(px, py, x0, y0, x1, y1, r):
    """True when (px, py) is inside the rounded rectangle."""
    if px < x0 or px > x1 or py < y0 or py > y1:
        return False
    cx = min(max(px, x0 + r), x1 - r)
    cy = min(max(py, y0 + r), y1 - r)
    dx = px - cx
    dy = py - cy
    return dx * dx + dy * dy <= r * r


def in_circle(px, py, cx, cy, r):
    dx = px - cx
    dy = py - cy
    return dx * dx + dy * dy <= r * r


def in_capsule(px, py, ax, ay, bx, by, r):
    """True when (px, py) is within radius r of the segment a->b."""
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        t = 0.0
    else:
        t = ((px - ax) * dx + (py - ay) * dy) / length_sq
        t = max(0.0, min(1.0, t))
    qx = ax + t * dx
    qy = ay + t * dy
    ex = px - qx
    ey = py - qy
    return ex * ex + ey * ey <= r * r


# --------------------------------------------------------------------------
# The mark
# --------------------------------------------------------------------------

SHEET = (0.26, 0.18, 0.74, 0.78, 0.04)
BADGE_CENTER = (0.63, 0.655)
BADGE_RADIUS = 0.10
CHECK_POINTS = ((0.585, 0.655), (0.618, 0.700), (0.678, 0.605))


def art_layers(px, py, detail: str):
    """Return the ordered list of (colour, alpha) layers covering a point."""
    layers = []

    def add(colour, alpha=1.0):
        layers.append((colour, alpha))

    if detail == "full":
        rules = (
            (0.33, 0.305, 0.67, 0.350),
            (0.33, 0.395, 0.60, 0.440),
            (0.33, 0.485, 0.63, 0.530),
        )
    else:
        rules = ((0.33, 0.330, 0.62, 0.395),)

    if in_rounded_rect(px, py, 0.0, 0.0, 1.0, 1.0, 0.22):
        add(FOREST)
    x0, y0, x1, y1, r = SHEET
    if in_rounded_rect(px, py, x0, y0, x1, y1, r):
        add(CREAM)
        for rx0, ry0, rx1, ry1 in rules:
            if in_rounded_rect(px, py, rx0, ry0, rx1, ry1, (ry1 - ry0) / 2):
                add(RULE)
        bx, by = BADGE_CENTER
        if in_circle(px, py, bx, by, BADGE_RADIUS):
            add(BADGE)
            if detail == "full":
                (ax, ay), (mx, my), (cx, cy) = CHECK_POINTS
                if in_capsule(px, py, ax, ay, mx, my, 0.020) or in_capsule(
                    px, py, mx, my, cx, cy, 0.020
                ):
                    add(CREAM)
    return layers


def _clamp8(value: float) -> int:
    return max(0, min(255, int(round(value))))


def sample_colour(px, py, scale, detail, opaque_background):
    """Composite the layers for one normalised sample point (0..1, y down)."""
    r = g = b = a = 0.0
    if opaque_background:
        # The full-bleed field is painted before any scaling, so a maskable
        # icon has no transparent corners.
        r, g, b, a = FOREST[0], FOREST[1], FOREST[2], 1.0
    if scale != 1.0:
        ax = 0.5 + (px - 0.5) / scale
        ay = 0.5 + (py - 0.5) / scale
    else:
        ax, ay = px, py
    if not (0.0 <= ax <= 1.0 and 0.0 <= ay <= 1.0):
        return (r, g, b, a)
    for colour, alpha in art_layers(ax, ay, detail):
        sr, sg, sb = colour
        na = alpha + a * (1.0 - alpha)
        if na <= 0:
            continue
        r = (sr * alpha + r * a * (1.0 - alpha)) / na
        g = (sg * alpha + g * a * (1.0 - alpha)) / na
        b = (sb * alpha + b * a * (1.0 - alpha)) / na
        a = na
    return (r, g, b, a)


def render_rgba(size, scale=1.0, detail="full", opaque_background=False):
    """Render the mark into a list of RGBA scanlines (bytes)."""
    rows = []
    step = 1.0 / (size * SUPERSAMPLE)
    for y in range(size):
        row = bytearray()
        for x in range(size):
            acc_r = acc_g = acc_b = acc_a = 0.0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    ox = (x * SUPERSAMPLE + sx) * step
                    oy = (y * SUPERSAMPLE + sy) * step
                    cr, cg, cb, ca = sample_colour(
                        ox, oy, scale, detail, opaque_background
                    )
                    acc_r += cr * ca
                    acc_g += cg * ca
                    acc_b += cb * ca
                    acc_a += ca
            total = SUPERSAMPLE * SUPERSAMPLE
            alpha = acc_a / total
            if alpha > 0:
                # acc_* hold premultiplied colour; divide by alpha to un-premultiply.
                row += bytes(
                    (
                        _clamp8(acc_r / total / alpha),
                        _clamp8(acc_g / total / alpha),
                        _clamp8(acc_b / total / alpha),
                        _clamp8(alpha * 255),
                    )
                )
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))
    return rows


# --------------------------------------------------------------------------
# PNG encoding
# --------------------------------------------------------------------------


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rows: list[bytes]) -> bytes:
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def write_icon(path: Path, size: int, scale: float = 1.0, detail: str = "full",
               opaque_background: bool = False) -> Path:
    rows = render_rgba(size, scale=scale, detail=detail,
                       opaque_background=opaque_background)
    path.write_bytes(encode_png(size, size, rows))
    return path


def build_all(out_dir: Path = ICONS_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [
        write_icon(out_dir / "icon-192.png", 192),
        write_icon(out_dir / "icon-512.png", 512),
        # Maskable: full-bleed field so the system mask can crop any shape;
        # the mark itself already sits inside the 80% safe circle.
        write_icon(out_dir / "icon-maskable-512.png", 512,
                   opaque_background=True),
        write_icon(out_dir / "apple-touch-icon.png", 180),
        write_icon(out_dir / "favicon.png", 32, detail="simple"),
    ]
    return written


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out_dir = Path(argv[0]) if argv else ICONS_DIR
    for path in build_all(out_dir):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
