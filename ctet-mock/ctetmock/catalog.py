"""Assemble the classified catalogue the CTET Mock app reads at runtime.

The catalogue is a tree of paper -> subject -> class -> lesson -> mock, plus a
flat list of every mock with its ancestry so the app can search and filter
without walking the tree.
"""
from __future__ import annotations

import re

from .intake import (
    PAPER_CLASS_RANGE,
    PAPER_I,
    PAPER_II,
    SUBJECT_ORDER,
)

UNCLASSIFIED = "Unclassified"

PAPER_IDS = {
    PAPER_I: "paper-1",
    PAPER_II: "paper-2",
    UNCLASSIFIED: "paper-unclassified",
}


def paper_id(name: str) -> str:
    """A short, readable id for a paper."""
    return PAPER_IDS.get(name, f"paper-{slug(name)}")


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (text or "").lower())
    return value.strip("-") or "x"


def session_key(title: str) -> str:
    """The key the mock app itself uses to store its session."""
    return "quiz_session_v2_" + re.sub(r"\W+", "_", title)[:40]


def _paper_sort_key(name: str):
    if name == PAPER_I:
        return (0, 0, name)
    if name == PAPER_II:
        return (1, 0, name)
    if name == UNCLASSIFIED:
        return (9, 0, name)
    return (5, 0, name)


def _subject_sort_key(name: str):
    if name in SUBJECT_ORDER:
        return (0, SUBJECT_ORDER.index(name), name)
    if name == UNCLASSIFIED:
        return (9, 0, name)
    return (5, 0, name)


def _class_sort_key(value):
    if value is None:
        return (9, 0, "")
    return (0, int(value), "")


def _lesson_sort_key(name: str):
    if name == UNCLASSIFIED:
        return (9, 0, name)
    return (0, 0, name)


def _mock_sort_key(label, title):
    if label:
        match = re.search(r"(\d+)", label)
        if match:
            return (0, int(match.group(1)), title)
        return (1, 0, label)
    return (2, 0, title)


def _record_sort_key(record):
    return (
        _paper_sort_key(record.get("paper") or UNCLASSIFIED),
        _subject_sort_key(record.get("subject") or UNCLASSIFIED),
        _class_sort_key(record.get("klass")),
        _lesson_sort_key(record.get("lesson") or UNCLASSIFIED),
        _mock_sort_key(record.get("mock_label"), record.get("title") or ""),
        record.get("name") or "",
    )


def _unique_titles(records: list[dict]) -> list[dict]:
    """Give every mock a distinct title so no two share a saved session."""
    used: dict[str, int] = {}
    output = []
    for record in records:
        title = record.get("title") or record.get("name") or "Mock"
        count = used.get(title, 0) + 1
        used[title] = count
        final = title if count == 1 else f"{title} ({count})"
        item = dict(record)
        item["title"] = final
        output.append(item)
    return output


def build_catalog(records: list[dict], version: str = "0" * 12) -> dict:
    """Build the catalogue from classified records."""
    ordered = _unique_titles(
        sorted(records, key=_record_sort_key)
    )

    papers: list[dict] = []
    paper_index: dict[str, dict] = {}
    subject_index: dict[str, dict] = {}
    class_index: dict[str, dict] = {}
    lesson_index: dict[str, dict] = {}
    used_ids: set[str] = set()

    def unique_id(base: str) -> str:
        candidate = base
        counter = 2
        while candidate in used_ids:
            candidate = f"{base}-{counter}"
            counter += 1
        used_ids.add(candidate)
        return candidate

    counts = {"papers": 0, "subjects": 0, "classes": 0, "lessons": 0, "mocks": 0}
    flat: list[dict] = []

    for record in ordered:
        paper_name = record.get("paper") or UNCLASSIFIED
        subject_name = record.get("subject") or UNCLASSIFIED
        klass = record.get("klass")
        class_name = f"Class {klass}" if klass is not None else UNCLASSIFIED
        lesson_name = record.get("lesson") or UNCLASSIFIED
        label = record.get("mock_label") or ""

        paper = paper_index.get(paper_name)
        if paper is None:
            paper = {
                "id": unique_id(paper_id(paper_name)),
                "name": paper_name,
                "classRange": PAPER_CLASS_RANGE.get(paper_name, ""),
                "subjects": [],
            }
            paper_index[paper_name] = paper
            papers.append(paper)
            counts["papers"] += 1

        subject = subject_index.get((paper["id"], subject_name))
        if subject is None:
            subject = {
                "id": unique_id(f"{paper['id']}__subject-{slug(subject_name)}"),
                "name": subject_name,
                "classes": [],
            }
            subject_index[(paper["id"], subject_name)] = subject
            paper["subjects"].append(subject)
            counts["subjects"] += 1

        klass_node = class_index.get((subject["id"], klass))
        if klass_node is None:
            klass_node = {
                "id": unique_id(f"{subject['id']}__class-{slug(class_name)}"),
                "name": class_name,
                "lessons": [],
            }
            class_index[(subject["id"], klass)] = klass_node
            subject["classes"].append(klass_node)
            counts["classes"] += 1

        lesson = lesson_index.get((klass_node["id"], lesson_name))
        if lesson is None:
            lesson = {
                "id": unique_id(f"{klass_node['id']}__lesson-{slug(lesson_name)}"),
                "name": lesson_name,
                "mocks": [],
            }
            lesson_index[(klass_node["id"], lesson_name)] = lesson
            klass_node["lessons"].append(lesson)
            counts["lessons"] += 1

        file_name = record.get("name") or ""
        mock = {
            "id": unique_id(f"{lesson['id']}__mock-{slug(label or file_name)}"),
            "name": label or record.get("title") or file_name,
            "title": record.get("title") or file_name,
            "file": f"mocks/{file_name}" if file_name else "",
            "questions": record.get("questions", 0),
            "status": record.get("status", ""),
            "sessionKey": session_key(record.get("title") or file_name),
        }
        lesson["mocks"].append(mock)
        counts["mocks"] += 1

        flat.append(
            {
                **mock,
                "paperId": paper["id"],
                "subjectId": subject["id"],
                "classId": klass_node["id"],
                "lessonId": lesson["id"],
                "paper": paper_name,
                "subject": subject_name,
                "klass": klass,
                "lesson": lesson_name,
                "mockLabel": label,
            }
        )

    return {
        "version": version,
        "counts": counts,
        "papers": papers,
        "mocks": flat,
    }
