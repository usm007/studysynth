#!/usr/bin/env python
"""Rebuild the CTET Mock PWA from the mocks in public/mocks.

    python ctet-mock/build.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctetmock.build import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
