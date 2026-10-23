"""Question-style prompt context for exam profiles.

A profile may carry a ``question_style_profile`` block.  That block changes how
questions are reasoned about and worded; it deliberately does not describe paper
counts, durations, sections or marks.  Profiles without the block (for example
``TEACHING.json``) keep the existing generic behaviour and produce no style
context.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ARCHETYPE_ORDER = (
    "classroom_situation",
    "child_development",
    "best_pedagogical_approach",
    "learner_error_misconception",
    "assessment_evaluation",
    "inclusive_education",
    "conceptual_subject_content",
    "subject_pedagogy",
    "language_comprehension",
    "language_pedagogy",
    "statement_assertion_reason",
)

CONTENT_KIND_ARCHETYPES = {
    "child_development": ("child_development", "classroom_situation"),
    "learner_error": ("learner_error_misconception", "classroom_situation"),
    "misconception": ("learner_error_misconception", "classroom_situation"),
    "assessment": ("assessment_evaluation",),
    "inclusive_education": ("inclusive_education", "classroom_situation"),
    "subject_content": ("conceptual_subject_content",),
    "subject_pedagogy": ("subject_pedagogy",),
    "language_comprehension": ("language_comprehension", "language_pedagogy"),
    "language_pedagogy": ("language_pedagogy",),
    "classroom_situation": ("classroom_situation",),
    "statement_assertion_reason": ("statement_assertion_reason",),
}

ABSURD_DISTRACTOR_PATTERNS = (
    r"\bpunish\b",
    r"\bbeat\b",
    r"\bslap\b",
    r"\bhumiliat",
    r"\bshame\b",
    r"\bscold\b",
    r"\bexpel\b",
    r"\bmock\b",
    r"\blaugh at\b",
)

BANNED_OPTION_PATTERNS = (
    r"^all of the above\.?$",
    r"^none of the above\.?$",
    r"^none of these\.?$",
    r"^all the above\.?$",
    r"^both \(?a\)? and \(?b\)?\.?$",
    r"^cannot be determined\.?$",
)


def load_profile(path: str | os.PathLike) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _style(profile: dict) -> dict:
    style = profile.get("question_style_profile") if isinstance(profile, dict) else None
    return style if isinstance(style, dict) else {}


def _profile_archetypes(style: dict) -> dict[str, dict]:
    out = {}
    for item in style.get("archetypes", []) or []:
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = item
    return out


def _bullets(items, prefix="- ") -> str:
    if not items:
        return ""
    return "\n".join(prefix + str(item) for item in items)


def _ordered_archetypes(style: dict) -> list[str]:
    declared = _profile_archetypes(style)
    selection = style.get("selection_rules", {}) if isinstance(style.get("selection_rules"), dict) else {}
    preferred = [a for a in (selection.get("default_order") or []) if a in declared]
    return preferred + [a for a in ARCHETYPE_ORDER if a in declared and a not in preferred]


def _difficulty_lines(style: dict) -> list[str]:
    rules = style.get("difficulty_rules", {}) if isinstance(style.get("difficulty_rules"), dict) else {}
    lines = []
    for level in ("easy", "medium", "hard"):
        if rules.get(level):
            lines.append(f"- {level}: {rules[level]}")
    if rules.get("rule"):
        lines.append(f"- rule: {rules['rule']}")
    return lines


def _assessment_lines(style: dict) -> list[str]:
    rules = style.get("assessment_rules", {}) if isinstance(style.get("assessment_rules"), dict) else {}
    lines = []
    if rules.get("purpose"):
        lines.append(f"- purpose: {rules['purpose']}")
    for rule in rules.get("rules", []) or []:
        lines.append(f"- {rule}")
    return lines


def style_context(profile: dict, stage: str) -> str:
    """Return prompt-ready style rules for a profile and pipeline stage.

    Stages: ``classify`` / ``extract`` (same style context), ``generate``.
    The legacy alias ``exam-design`` maps to ``extract``.  Unknown stages and
    profiles without ``question_style_profile`` return an empty string.
    """
    style = _style(profile)
    if not style:
        return ""
    identity = style.get("identity", {}) if isinstance(style.get("identity"), dict) else {}
    name = identity.get("label") or profile.get("name") or "Profile"
    stage = (stage or "").strip().lower()
    if stage == "exam-design":
        stage = "extract"
    if stage not in {"classify", "extract", "generate"}:
        return ""

    lines = [f"## {name} question-style profile", ""]
    summary = identity.get("summary")
    if summary:
        lines += [str(summary), ""]
    intent = identity.get("authoring_intent")
    if intent:
        lines += [f"Authoring intent: {intent}", ""]

    if stage == "classify":
        tags = style.get("tagging_rules", {}) if isinstance(style.get("tagging_rules"), dict) else {}
        lines.append("Tag every knowledge unit before blueprinting:")
        for key in ("content_kind", "pedagogical_relevance",
                    "classroom_application_potential", "has_passage"):
            rule = tags.get(key)
            if rule:
                lines.append(f"- {key}: {rule}")
        hints = tags.get("archetype_hints")
        if hints:
            lines.append(f"- archetype_hints: {hints}")
        lines += ["", "Use these tags to select the authoring archetype; do not force every unit into a classroom story."]
        return "\n".join(lines).strip()

    archetypes = _profile_archetypes(style)
    if stage == "extract":
        lines.append("Archetype selection (record the chosen `archetype` on every blueprint row):")
        for aid in ARCHETYPE_ORDER:
            item = archetypes.get(aid)
            if not item:
                continue
            use_when = item.get("use_when", "")
            lines.append(f"- {aid}: {use_when}".rstrip())
        selection = style.get("selection_rules", {}) if isinstance(style.get("selection_rules"), dict) else {}
        rules = selection.get("rules", []) if isinstance(selection.get("rules"), list) else []
        if rules:
            lines += ["", "Selection rules:"] + [f"- {r}" for r in rules]
        difficulty = _difficulty_lines(style)
        if difficulty:
            lines += ["", "Difficulty definitions (reasoning demand):"] + difficulty
        assessment = _assessment_lines(style)
        if assessment:
            lines += ["", "Assessment items:"] + assessment
        lines += [
            "",
            "Every row must keep one defensible best answer and a real reasoning demand. "
            "Do not invent question-type percentages or paper structure.",
        ]
        return "\n".join(lines).strip()

    # generate
    lines.append("Authoring contract:")
    authoring = style.get("authoring_rules", {}) if isinstance(style.get("authoring_rules"), dict) else {}
    for key in ("stem", "answer", "explanation", "tone"):
        rule = authoring.get(key)
        if rule:
            lines.append(f"- {key}: {rule}")
    difficulty = _difficulty_lines(style)
    if difficulty:
        lines += ["", "Difficulty definitions (reasoning demand):"] + difficulty
    assessment = _assessment_lines(style)
    if assessment:
        lines += ["", "Assessment items:"] + assessment
    quality = style.get("quality_codes", {}) if isinstance(style.get("quality_codes"), dict) else {}
    if quality:
        lines += ["", "Automatic style checks reject:"]
        for code in sorted(quality):
            lines.append(f"- {code}: {quality[code]}")
    distractor = style.get("distractor_rules", {}) if isinstance(style.get("distractor_rules"), dict) else {}
    lines += ["", "Distractor construction:"]
    for rule in distractor.get("rules", []) or []:
        lines.append(f"- {rule}")
    banned = distractor.get("banned_forms", []) or []
    if banned:
        lines.append("- banned option forms: " + ", ".join(str(b) for b in banned))
    classroom = style.get("classroom_rules", {}) if isinstance(style.get("classroom_rules"), dict) else {}
    lines += ["", "Classroom-scenario rules:"]
    for rule in classroom.get("rules", []) or []:
        lines.append(f"- {rule}")
    language = style.get("language_rules", {}) if isinstance(style.get("language_rules"), dict) else {}
    if language:
        lines += ["", "Language-section rules:"]
        for key in ("passage", "comprehension", "pedagogy"):
            rule = language.get(key)
            if rule:
                lines.append(f"- {rule}")
    source = style.get("source_rules", {}) if isinstance(style.get("source_rules"), dict) else {}
    lines += ["", "Source discipline:"]
    for rule in source.get("rules", []) or []:
        lines.append(f"- {rule}")
    if not source.get("rules"):
        lines.append("- Keep SOURCE_BOUND: every tested claim must be traceable to the source.")
    return "\n".join(lines).strip()


def build_prompt(profile_path: str | os.PathLike, stage: str) -> str:
    """Load a profile and return the style context for one pipeline stage."""
    return style_context(load_profile(profile_path), stage)


def select_archetypes(ku: dict, profile: dict) -> list[str]:
    """Rank archetypes for one KU, most suitable first.

    Selection is driven by the KU tags written by classification.  Only
    archetypes declared by the profile are returned.
    """
    style = _style(profile)
    declared = _profile_archetypes(style)
    if not declared:
        return []
    ku = ku if isinstance(ku, dict) else {}
    kind = str(ku.get("content_kind") or "").strip().lower()
    pedagogical = str(ku.get("pedagogical_relevance") or "").strip().lower()
    classroom_potential = str(ku.get("classroom_application_potential") or "").strip().lower()
    has_passage = bool(ku.get("has_passage"))
    qtype = str(ku.get("type") or "").strip().lower()

    picked: list[str] = []
    for aid in CONTENT_KIND_ARCHETYPES.get(kind, ()):
        if aid == "language_comprehension" and not has_passage:
            continue
        picked.append(aid)

    if kind == "subject_content" and classroom_potential == "high":
        picked.append("classroom_situation")
    if kind == "language_comprehension" and not has_passage:
        picked.append("language_pedagogy")

    if pedagogical == "high" and classroom_potential != "low":
        if kind not in {"subject_content", "language_comprehension"} or classroom_potential == "high":
            picked.append("classroom_situation")

    if pedagogical == "high" and not picked:
        picked.append("best_pedagogical_approach")

    if qtype in {"theory", "principle", "concept", "case_study"} and kind in {
        "child_development", "assessment", "subject_pedagogy", "inclusive_education"
    }:
        picked.append("statement_assertion_reason")

    picked.append("conceptual_subject_content" if kind in {"subject_content", "formula"} else "best_pedagogical_approach")

    out: list[str] = []
    for aid in picked:
        if aid in declared and aid not in out:
            out.append(aid)
    if not out:
        ordered = _ordered_archetypes(style)
        out = ordered[:1]
    return out


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower().rstrip(" .")


def validate_question_style(question: dict, profile: dict, *, supplied_passage=None) -> dict:
    """Check whether a generated question follows the profile's authoring style.

    Structural/schema validation remains the job of ``validate_questions.py``;
    this function checks style-specific defects and keeps SOURCE_BOUND intact.
    """
    q = question if isinstance(question, dict) else {}
    style = _style(profile)
    violations: list[dict] = []
    quality_messages = style.get("quality_codes", {}) if isinstance(style.get("quality_codes"), dict) else {}

    def add(code: str, message: str) -> None:
        text = quality_messages.get(code) or message
        violations.append({"code": code, "message": str(text)})

    if not style:
        return {"ok": True, "violations": []}

    if not q.get("source"):
        add("source_missing", "Question has no source citation.")
    if str(q.get("origin") or "") == "external":
        add("external_not_allowed", "CTET-style source-bound authoring does not allow external claims.")

    options = [o for o in (q.get("options") or []) if isinstance(o, dict)]
    correct = [o for o in options if o.get("is_correct") is True]
    if len(correct) > 1:
        add("multiple_correct_options", "Exactly one option must be defensible as correct.")
    elif not correct:
        add("missing_correct_option", "No option is marked correct.")

    texts = [_norm(o.get("text")) for o in options]
    non_empty = [t for t in texts if t]
    if len(set(non_empty)) != len(non_empty):
        add("duplicate_options", "Two or more options are textually identical.")

    for text in non_empty:
        if any(re.match(p, text) for p in BANNED_OPTION_PATTERNS):
            add("banned_option_form", "Options such as 'all/none of the above' are not used in CTET-style items.")
            break

    for opt in options:
        if opt.get("is_correct") is True:
            continue
        text = _norm(opt.get("text"))
        if any(re.search(p, text) for p in ABSURD_DISTRACTOR_PATTERNS):
            add("absurd_distractor", "Distractors must be plausible, not punitive or absurd.")

    if len(correct) == 1 and len(options) >= 2:
        correct_len = len(str(correct[0].get("text") or ""))
        other_lens = [len(str(o.get("text") or "")) for o in options if o is not correct[0]]
        longest_other = max(other_lens) if other_lens else 0
        if correct_len >= max(1, int(longest_other * 1.6)) and correct_len - longest_other >= 35:
            add("answer_length_clue", "The correct option is conspicuously longer than every distractor.")

    archetype = str(q.get("archetype") or "").strip().lower()
    stem = str(q.get("stem") or "").strip()

    if archetype == "classroom_situation":
        if len(stem) < 120:
            add("classroom_context_insufficient",
                "A classroom item needs a concrete class, learner and subject/topic situation.")

    if archetype == "conceptual_subject_content":
        if re.search(r"\b(?:a|the)\s+teacher\b.*\b(?:classroom|class)\b", stem, re.I) or \
                re.search(r"\bin the classroom\b", stem, re.I):
            add("content_forced_into_scenario",
                "Conceptual subject content should be tested directly, not wrapped in an artificial classroom story.")

    if archetype == "subject_pedagogy":
        if len(stem) < 120:
            add("subject_pedagogy_too_generic",
                "Subject pedagogy must name the subject, topic and a specific teaching decision.")

    if archetype == "language_comprehension":
        passage = q.get("passage") or supplied_passage
        if not isinstance(passage, str) or len(passage.strip()) < 40:
            add("language_passage_missing",
                "Language comprehension needs a real passage in the question or supplied context.")

    if archetype == "statement_assertion_reason":
        statements = q.get("statements")
        substantive = (
            isinstance(statements, list)
            and len(statements) >= 2
            and all(isinstance(s, dict) and len(str(s.get("text") or "").strip()) >= 10
                    for s in statements)
        )
        if not substantive:
            add("assertion_reason_payload_missing",
                "Assertion-reason items need substantive statements with truth values.")

    return {"ok": not violations, "violations": violations}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Print question-style prompt context for a profile.")
    ap.add_argument("--profile", required=True, help="Path to an exam profile JSON file")
    ap.add_argument("--stage", required=True,
                    choices=["classify", "extract", "generate", "exam-design"],
                    help="Style stage: classify/extract (same context; exam-design "
                         "is the legacy alias) or generate")
    args = ap.parse_args(argv)
    try:
        text = build_prompt(args.profile, args.stage)
    except (OSError, ValueError) as exc:
        print(f"profile_style: {exc}", file=sys.stderr)
        return 1
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
