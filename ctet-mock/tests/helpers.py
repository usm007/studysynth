"""Shared helpers for the CTET Mock tests."""
from __future__ import annotations

import json


def make_mock_html(meta=None, questions=None) -> str:
    """A mock document that carries an embedded package like the real ones."""
    package = {
        "meta": meta if meta is not None else {},
        "questions": questions if questions is not None else [],
    }
    return (
        "<!DOCTYPE html><html><body><h1>mock</h1>"
        "<script>var PKG = /*__PACKAGE__*/"
        + json.dumps(package, ensure_ascii=False)
        + ";</script></body></html>"
    )


def make_record(**overrides) -> dict:
    """A classified record as the catalogue builder expects it."""
    record = {
        "name": "mock.html",
        "paper": "Paper II",
        "subject": "Science",
        "klass": 8,
        "lesson": "Light",
        "mock_label": "Mock 1",
        "title": "Light · Mock 1",
        "questions": 10,
        "status": "COMPREHENSIVE",
        "source": "filename",
    }
    record.update(overrides)
    return record
