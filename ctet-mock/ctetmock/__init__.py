"""CTET Mock PWA — build pipeline package.

Modules:
    intake   — scan mock files and classify them into paper/subject/class/lesson
    catalog  — assemble the classified catalogue the app reads at runtime
    sw       — emit the offline service worker
"""

__all__ = ["intake", "catalog", "sw"]
