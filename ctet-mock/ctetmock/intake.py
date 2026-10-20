"""Read generated mock apps and classify them for the CTET Mock library.

The intake contract is a filename convention:

    <paper>-<subject>-<class>-<lesson>-<mock>.html

for example ``p2-social-c8-natural-resources-m01.html`` means Paper II,
Social Science, Class 8, lesson "Natural Resources", Mock 1. A sidecar file
``<name>.meta.json`` next to the mock overrides any of it, and the package
embedded in the mock is the last resort for a class, a lesson and a title.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PACKAGE_MARKER = "/*__PACKAGE__*/"

PAPER_I = "Paper I"
PAPER_II = "Paper II"

PAPER_CLASS_RANGE = {
    PAPER_I: "Class I–V",
    PAPER_II: "Class VI–VIII",
}

SUBJECT_ORDER = [
    "Child Development & Pedagogy",
    "Mathematics",
    "Environmental Studies",
    "Science",
    "Social Science",
    "Language I",
    "Language II",
]

SUBJECT_TOKENS = {
    "cdp": "Child Development & Pedagogy",
    "childdevelopment": "Child Development & Pedagogy",
    "pedagogy": "Child Development & Pedagogy",
    "math": "Mathematics",
    "maths": "Mathematics",
    "mathematics": "Mathematics",
    "evs": "Environmental Studies",
    "environmentalscience": "Environmental Studies",
    "science": "Science",
    "sci": "Science",
    "social": "Social Science",
    "socialscience": "Social Science",
    "socialstudies": "Social Science",
    "sst": "Social Science",
    "lang1": "Language I",
    "language1": "Language I",
    "hindi": "Language I",
    "lang2": "Language II",
    "language2": "Language II",
    "english": "Language II",
}

PAPER_TOKENS = {
    "p1": PAPER_I,
    "paper1": PAPER_I,
    "paperi": PAPER_I,
    "p2": PAPER_II,
    "paper2": PAPER_II,
    "paperii": PAPER_II,
}

CLASS_RE = re.compile(r"^(?:c|class|grade|gr)(\d{1,2})$")
BARE_CLASS_RE = re.compile(r"^\d{1,2}$")
MOCK_RE = re.compile(r"^(?:m|mock|set)(\d{1,2})$")
CLASS_IN_TEXT_RE = re.compile(r"\b(?:grade|class)\s*([1-8])\b", re.IGNORECASE)


def _tokens(stem: str) -> list[str]:
    return [t for t in re.split(r"[-_\s]+", stem.strip()) if t]


def _normalise(stem: str) -> str:
    """Join a word and its number so ``mock-03`` reads as one token."""
    text = re.sub(r"\b(mock|set|m)[-_](\d{1,2})\b", r"\1\2", stem)
    text = re.sub(r"\b(class|grade|gr)[-_](\d{1,2})\b", r"\1\2", text)
    text = re.sub(r"\bpaper[-_](i{1,2})\b", r"paper\1", text)
    return text


def humanise_slug(slug: str) -> str:
    """"natural-resources" -> "Natural Resources"."""
    words = []
    for word in re.split(r"[-_\s]+", slug.strip()):
        if not word:
            continue
        if word.isdigit():
            words.append(word)
        else:
            words.append(word[0].upper() + word[1:])
    return " ".join(words)


def parse_tokens(stem: str) -> dict:
    """Read the classification tokens out of a filename stem."""
    tokens = _tokens(_normalise(stem))
    result = {
        "paper": None,
        "subject": None,
        "klass": None,
        "lesson_slug": None,
        "mock_label": None,
    }

    # First pass: an explicit class token always wins, so that a lesson name
    # ending in a number ("chapter-1") is not mistaken for a class.
    strong_index = None
    for index, token in enumerate(tokens):
        match = CLASS_RE.match(token.lower())
        if match and 1 <= int(match.group(1)) <= 8:
            strong_index = index
            break

    paper = subject = None
    strong_class = weak_class = None
    mock_label = None
    lesson_parts = []
    recognised = False

    for index, token in enumerate(tokens):
        lowered = token.lower()
        # The paper and the subject sit at the front of the name; a later word
        # that happens to match is part of the lesson, not the subject.
        if index <= 1 and paper is None and lowered in PAPER_TOKENS:
            paper = PAPER_TOKENS[lowered]
            recognised = True
            continue
        if index <= 1 and subject is None and lowered in SUBJECT_TOKENS:
            subject = SUBJECT_TOKENS[lowered]
            recognised = True
            continue
        if index == strong_index:
            strong_class = int(CLASS_RE.match(lowered).group(1))
            recognised = True
            continue
        mock_match = MOCK_RE.match(lowered)
        if mock_match and mock_label is None:
            mock_label = f"Mock {int(mock_match.group(1))}"
            recognised = True
            continue
        if (
            BARE_CLASS_RE.match(lowered)
            and strong_class is None
            and weak_class is None
        ):
            value = int(lowered)
            if 1 <= value <= 8:
                weak_class = value
                recognised = True
                continue
        lesson_parts.append(lowered)

    result["paper"] = paper
    result["subject"] = subject
    result["klass"] = strong_class if strong_class is not None else weak_class
    result["mock_label"] = mock_label
    # A leftover word only names a lesson when the filename is a convention
    # name at all; "mystery.html" must stay unclassifiable.
    if recognised and lesson_parts:
        result["lesson_slug"] = "-".join(lesson_parts)
    return result


def _package_span(html: str) -> tuple[int, int] | None:
    """Locate the embedded package literal; returns (start, end) offsets."""
    index = html.find(PACKAGE_MARKER)
    if index < 0:
        return None
    start = html.find("{", index)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for position in range(start, len(html)):
        char = html[position]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, position + 1
    return None


def extract_package(html: str) -> str | None:
    """Return the raw JSON text of the package embedded in a mock document."""
    span = _package_span(html)
    if not span:
        return None
    return html[span[0]:span[1]]


def rewrite_package_title(html: str, new_title: str,
                          library: dict | None = None) -> str:
    """Set the package title inside a mock document, leaving the rest alone.

    The library record is written alongside it so that a later build reads the
    same classification back instead of re-deriving it from a title this
    build has just written.
    """
    span = _package_span(html)
    if not span:
        return html
    start, end = span
    try:
        package = json.loads(html[start:end])
    except (ValueError, TypeError):
        return html
    if not isinstance(package, dict):
        return html
    meta = package.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        package["meta"] = meta
    if library is not None:
        meta["library"] = library
    if meta.get("title") == new_title and (
        library is None or meta.get("library") == library
    ):
        return html
    meta["title"] = new_title
    payload = json.dumps(package, ensure_ascii=False, separators=(",", ":"))
    return html[:start] + payload + html[end:]


def read_package(html: str) -> dict | None:
    """Parse the embedded package; returns None when the mock carries none."""
    raw = extract_package(html)
    if not raw:
        return None
    try:
        package = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(package, dict):
        return None
    questions = package.get("questions")
    package["question_count"] = len(questions) if isinstance(questions, list) else 0
    return package


def compose_title(lesson: str | None, label: str | None, fallback: str = "") -> str:
    """The title a mock carries.

    The mock label comes first so that the first forty characters - all the
    saved session key is made of - always tell two papers of the same lesson
    apart.
    """
    if label and lesson:
        return f"{label} · {lesson}"
    if label:
        return label
    if lesson:
        return lesson
    return fallback


def _package_class(meta: dict) -> int | None:
    for key in ("source", "source_title", "title", "description"):
        value = meta.get(key)
        if not isinstance(value, str):
            continue
        match = CLASS_IN_TEXT_RE.search(value)
        if match:
            return int(match.group(1))
    return None


def _paper_for_class(klass: int | None) -> str | None:
    if klass is None:
        return None
    return PAPER_I if klass <= 5 else PAPER_II


def _sidecar_value(sidecar: dict, *names):
    for name in names:
        if name in sidecar and sidecar[name] not in (None, ""):
            return sidecar[name]
    return None


def classify(path: Path, html: str, sidecar: dict | None = None) -> dict:
    """Classify one mock file into the library's tree."""
    stem = Path(path).stem
    tokens = parse_tokens(stem)
    package = read_package(html)
    meta = (package or {}).get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    library = meta.get("library")
    if not isinstance(library, dict):
        library = {}

    paper = tokens["paper"]
    subject = tokens["subject"]
    klass = tokens["klass"]
    lesson = humanise_slug(tokens["lesson_slug"] or "")
    mock_label = tokens["mock_label"]
    source = "filename" if any(
        (paper, subject, klass, lesson, mock_label)
    ) else "package"

    package_class = _package_class(meta)
    package_title = meta.get("title") if isinstance(meta.get("title"), str) else ""

    # What an earlier build recorded fills the gaps the file name leaves.
    if not paper and library.get("paper"):
        paper = str(library["paper"])
    if not subject and library.get("subject"):
        subject = str(library["subject"])
    if klass is None and library.get("class") is not None:
        try:
            klass = int(library["class"])
        except (TypeError, ValueError):
            klass = None
    if not lesson and library.get("lesson"):
        lesson = str(library["lesson"])
    if not mock_label and library.get("mock"):
        mock_label = str(library["mock"])

    if not lesson and package_title:
        lesson = package_title
        if source == "filename" and not any((paper, subject, klass, mock_label)):
            source = "package"
    if not paper and package_class is not None:
        paper = _paper_for_class(package_class)
    if klass is None and package_class is not None:
        klass = package_class

    if sidecar:
        applied = False
        side_paper = _sidecar_value(sidecar, "paper")
        if side_paper:
            paper = str(side_paper)
            applied = True
        side_subject = _sidecar_value(sidecar, "subject")
        if side_subject:
            subject = str(side_subject)
            applied = True
        side_class = _sidecar_value(sidecar, "class", "klass")
        if side_class is not None:
            try:
                klass = int(side_class)
                applied = True
            except (TypeError, ValueError):
                pass
        side_lesson = _sidecar_value(sidecar, "lesson")
        if side_lesson:
            lesson = str(side_lesson)
            applied = True
        side_mock = _sidecar_value(sidecar, "mock", "mock_label")
        if side_mock:
            mock_label = str(side_mock)
            applied = True
        if applied:
            source = "sidecar"

    if not paper:
        paper = _paper_for_class(klass)
    if not subject:
        subject = None

    # A title a previous build settled on is kept, so that rebuilding never
    # renames a paper or orphans the session saved under it.
    derived = compose_title(
        lesson, mock_label, package_title or humanise_slug(stem)
    )
    stored = library.get("title")
    title_locked = (
        isinstance(stored, str)
        and bool(stored)
        and library.get("lesson") == lesson
        and library.get("mock") == mock_label
    )
    title = stored if title_locked else derived
    if sidecar and _sidecar_value(sidecar, "title"):
        title = str(_sidecar_value(sidecar, "title"))
        title_locked = True

    unclassified = not any((paper, subject, klass, lesson))
    if unclassified:
        source = "unclassified"

    return {
        "name": Path(path).name,
        "paper": paper,
        "subject": subject,
        "klass": klass,
        "lesson": lesson or None,
        "mock_label": mock_label,
        "title": title,
        "title_locked": title_locked,
        "questions": (package or {}).get("question_count", 0),
        "status": meta.get("status") if isinstance(meta.get("status"), str) else "",
        "source": source,
    }


def is_complete(record: dict) -> bool:
    """True when the record can be filed in the paper/subject/class tree."""
    return bool(record.get("paper") and record.get("subject")
                and record.get("klass"))


def load_sidecar(path: Path) -> dict | None:
    """Read ``<name>.meta.json`` next to a mock, when it exists."""
    sidecar_path = path.with_suffix(".meta.json")
    if not sidecar_path.is_file():
        return None
    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
