"""CTET question-style profile tests.

These tests protect the distinction between a question-style profile and an
exam-structure blueprint.  The profile must change how questions are authored
without introducing paper counts, durations, section marks or invented
question-type percentages.
"""
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lib_quiz
import profile_style
import validate_schema

PROFILES = ROOT / "profiles"
CTET_PATH = PROFILES / "CTET.json"
TEACHING_PATH = PROFILES / "TEACHING.json"

ARCHETYPE_IDS = {
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
}


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def option(key, text, correct=False):
    return {
        "key": key,
        "text": text,
        "is_correct": correct,
        "distractor_origin": "source_ku",
        "confusion_type": "near_synonym" if correct else "partial_truth",
        "ku_ref": "KU-0001",
    }


def base_question(archetype, stem, options, answer="A", **overrides):
    q = {
        "id": "Q-0001",
        "type": "pedagogy_mcq",
        "archetype": archetype,
        "stem": stem,
        "options": options,
        "answer": answer,
        "difficulty": "medium",
        "statements": None,
        "knowledge_units": [{"ku_id": "KU-0001", "role": "primary"}],
        "source": [{
            "page": 1,
            "section_path": "Child Development and Pedagogy",
            "block_id": "B-0001",
            "char_start": 0,
            "char_end": 120,
            "table_ref": None,
        }],
        "explanation": "The response follows the learning principle described in the source.",
        "memory_aid": None,
        "hint": None,
        "topic": "Learning",
        "origin": "source",
        "exam_profile": "CTET",
        "language": "en",
        "passage": None,
    }
    q.update(overrides)
    return q


def classroom_scenario(**overrides):
    q = base_question(
        "classroom_situation",
        "A Class VII teacher finds that several learners can state the formula for the "
        "area of a rectangle but cannot decide which side to treat as the length when "
        "the rectangle is drawn in an unfamiliar orientation. Which response is most "
        "appropriate?",
        [
            option("A", "Ask learners to rotate the rectangle and explain why its area does not change.", True),
            option("B", "Ask learners to copy the formula five times and memorise it."),
            option("C", "Move to the next topic because the formula has already been taught."),
            option("D", "Give a short test and rank learners by their marks."),
        ],
    )
    q.update(overrides)
    return q


class TestCTETProfileLoading(unittest.TestCase):
    def test_profile_loads_through_existing_loader(self):
        prof = lib_quiz.resolve_profile({}, str(CTET_PATH), PROFILES)
        self.assertEqual(prof.get("name"), "CTET")
        style = prof.get("question_style_profile")
        self.assertIsInstance(style, dict)
        self.assertIn("identity", style)
        self.assertIn("selection_rules", style)

    def test_profile_matches_exam_profile_schema(self):
        prof = load_json(CTET_PATH)
        schema = load_json(ROOT / "schemas" / "exam-profile.schema.json")
        errors = []
        validate_schema.check(prof, schema, "$", errors)
        self.assertEqual(errors, [])

    def test_profile_declares_every_archetype(self):
        style = load_json(CTET_PATH)["question_style_profile"]
        ids = {a.get("id") for a in style.get("archetypes", []) if isinstance(a, dict)}
        self.assertEqual(ids, ARCHETYPE_IDS)

    def test_profile_does_not_invent_type_percentages(self):
        prof = load_json(CTET_PATH)
        self.assertEqual(prof.get("target_type_mix"), {})
        self.assertTrue(prof.get("blueprint_rules", {}).get("quantitative_blueprint") is False)

    def test_profile_is_not_an_exam_structure_blueprint(self):
        prof = load_json(CTET_PATH)
        for forbidden in ("paper_count", "duration_minutes", "sections",
                          "marks_distribution", "full_paper_blueprint"):
            self.assertNotIn(forbidden, prof)

    def test_profile_records_official_sources_and_limitations(self):
        style = load_json(CTET_PATH)["question_style_profile"]
        evidence = style.get("evidence", {})
        urls = {s.get("url") for s in evidence.get("sources", []) if isinstance(s, dict)}
        self.assertIn("https://ctet.nic.in/question-paper-feb-2026/", urls)
        self.assertIn("https://ctet.nic.in/document-category/previous-year-answer-key/", urls)
        self.assertTrue(evidence.get("limitations"))
        self.assertFalse(evidence.get("claims_percentage_distribution", True))

    def test_generic_teaching_profile_is_unchanged(self):
        teaching = load_json(TEACHING_PATH)
        self.assertNotIn("question_style_profile", teaching)
        loaded = lib_quiz.resolve_profile({}, str(TEACHING_PATH), PROFILES)
        self.assertEqual(loaded.get("name"), "TEACHING")
        self.assertEqual(profile_style.style_context(loaded, "generate"), "")


class TestPromptContext(unittest.TestCase):
    def setUp(self):
        self.profile = load_json(CTET_PATH)

    def test_exam_design_prompt_receives_ctet_style_rules(self):
        text = profile_style.build_prompt(CTET_PATH, "exam-design")
        self.assertIn("CTET question-style profile", text)
        self.assertIn("classroom_situation", text)
        self.assertIn("subject_pedagogy", text)
        self.assertIn("conceptual_subject_content", text)
        self.assertIn("one defensible best answer", text)
        self.assertIn("archetype", text)

    def test_generate_prompt_receives_authoring_and_distractor_rules(self):
        text = profile_style.build_prompt(CTET_PATH, "generate")
        self.assertIn("CTET question-style profile", text)
        self.assertIn("Distractor construction", text)
        self.assertIn("Classroom-scenario rules", text)
        self.assertIn("SOURCE_BOUND", text)
        self.assertIn("passage", text.lower())
        self.assertIn("all of the above", text.lower())

    def test_classify_prompt_receives_tagging_rules(self):
        text = profile_style.build_prompt(CTET_PATH, "classify")
        self.assertIn("content_kind", text)
        self.assertIn("pedagogical_relevance", text)
        self.assertIn("classroom_application_potential", text)
        self.assertIn("language_comprehension", text)

    def test_generic_profile_prompt_is_not_polluted_with_ctet_rules(self):
        text = profile_style.build_prompt(TEACHING_PATH, "generate")
        self.assertNotIn("CTET question-style profile", text)
        self.assertNotIn("classroom_situation", text)


class TestArchetypeSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_json(CTET_PATH)

    def select(self, **ku):
        return profile_style.select_archetypes(ku, self.profile)

    def test_child_development_prefers_development_and_classroom_judgement(self):
        picked = self.select(content_kind="child_development", pedagogical_relevance="high",
                             type="theory")
        self.assertEqual(picked[0], "child_development")
        self.assertIn("classroom_situation", picked)

    def test_subject_content_is_not_forced_into_a_classroom_scenario(self):
        picked = self.select(content_kind="subject_content", pedagogical_relevance="low",
                             type="formula", classroom_application_potential="low")
        self.assertEqual(picked[0], "conceptual_subject_content")
        self.assertNotIn("classroom_situation", picked)

    def test_subject_pedagogy_selects_pedagogy(self):
        picked = self.select(content_kind="subject_pedagogy", pedagogical_relevance="high",
                             type="process")
        self.assertEqual(picked[0], "subject_pedagogy")

    def test_assessment_selects_assessment(self):
        picked = self.select(content_kind="assessment", pedagogical_relevance="high",
                             type="concept")
        self.assertEqual(picked[0], "assessment_evaluation")

    def test_language_comprehension_requires_a_passage(self):
        with_passage = self.select(content_kind="language_comprehension",
                                   pedagogical_relevance="medium", has_passage=True)
        without_passage = self.select(content_kind="language_comprehension",
                                      pedagogical_relevance="medium", has_passage=False)
        self.assertEqual(with_passage[0], "language_comprehension")
        self.assertNotIn("language_comprehension", without_passage)
        self.assertIn("language_pedagogy", without_passage)

    def test_language_pedagogy_selects_language_pedagogy(self):
        picked = self.select(content_kind="language_pedagogy",
                             pedagogical_relevance="high", type="principle")
        self.assertEqual(picked[0], "language_pedagogy")

    def test_selection_varies_by_knowledge_unit(self):
        picks = {
            self.select(content_kind="subject_content", pedagogical_relevance="low")[0],
            self.select(content_kind="subject_pedagogy", pedagogical_relevance="high")[0],
            self.select(content_kind="child_development", pedagogical_relevance="high")[0],
            self.select(content_kind="assessment", pedagogical_relevance="high")[0],
        }
        self.assertGreaterEqual(len(picks), 3)


class TestQuestionStyleValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_json(CTET_PATH)

    def validate(self, q, **kwargs):
        return profile_style.validate_question_style(q, self.profile, **kwargs)

    def codes(self, result):
        return {v["code"] for v in result["violations"]}

    def test_good_classroom_situation_passes(self):
        result = self.validate(classroom_scenario())
        self.assertTrue(result["ok"], result["violations"])

    def test_classroom_situation_needs_enough_context(self):
        q = classroom_scenario(
            stem="A teacher sees a learner struggling. What should she do?"
        )
        self.assertIn("classroom_context_insufficient", self.codes(self.validate(q)))

    def test_classroom_situation_needs_one_defensible_answer(self):
        q = classroom_scenario()
        q["options"][1]["is_correct"] = True
        self.assertIn("multiple_correct_options", self.codes(self.validate(q)))

    def test_absurd_distractor_is_rejected(self):
        q = classroom_scenario()
        q["options"][1]["text"] = "Punish the learner in front of the class."
        self.assertIn("absurd_distractor", self.codes(self.validate(q)))

    def test_answer_length_clue_is_rejected(self):
        q = classroom_scenario()
        q["options"][0]["text"] = (
            "Ask learners to rotate the rectangle, compare the original and rotated "
            "positions, explain why the area remains unchanged, and then apply the "
            "same reasoning to a second rectangle drawn in an unfamiliar orientation."
        )
        self.assertIn("answer_length_clue", self.codes(self.validate(q)))

    def test_subject_content_is_not_forced_into_a_classroom_scenario(self):
        q = base_question(
            "conceptual_subject_content",
            "A teacher is explaining in the classroom. Which gas is most abundant in air?",
            [
                option("A", "Nitrogen", True),
                option("B", "Oxygen"),
                option("C", "Carbon dioxide"),
                option("D", "Hydrogen"),
            ],
        )
        self.assertIn("content_forced_into_scenario", self.codes(self.validate(q)))

    def test_subject_pedagogy_must_test_a_specific_teaching_decision(self):
        q = base_question(
            "subject_pedagogy",
            "A teacher wants good teaching. Which approach is best?",
            [
                option("A", "Use learner-centred teaching.", True),
                option("B", "Use teacher-centred teaching."),
                option("C", "Use a longer textbook."),
                option("D", "Use more tests."),
            ],
        )
        self.assertIn("subject_pedagogy_too_generic", self.codes(self.validate(q)))

    def test_good_subject_pedagogy_passes(self):
        q = base_question(
            "subject_pedagogy",
            "A mathematics teacher wants Class VI learners to understand why the angles "
            "of a triangle add up to 180 degrees. Which activity is most appropriate?",
            [
                option("A", "Ask learners to tear the corners and arrange them on a straight line.", True),
                option("B", "Ask learners to memorise the statement of the theorem."),
                option("C", "Ask learners to copy the proof from the textbook."),
                option("D", "Ask learners to solve ten similar numerical problems."),
            ],
        )
        result = self.validate(q)
        self.assertTrue(result["ok"], result["violations"])

    def test_language_comprehension_requires_a_real_passage(self):
        q = base_question(
            "language_comprehension",
            "According to the passage, why does the speaker describe the caged bird as crippled?",
            [
                option("A", "It cannot fly or soar freely.", True),
                option("B", "It is hungry."),
                option("C", "It has a broken leg."),
                option("D", "It is wild."),
            ],
        )
        self.assertIn("language_passage_missing", self.codes(self.validate(q)))
        passed = self.validate(
            q, supplied_passage="A bird in a cage is a crippled thing, but my bird sings."
        )
        self.assertTrue(passed["ok"], passed["violations"])

    def test_assertion_reason_needs_substantive_payload(self):
        q = base_question(
            "statement_assertion_reason",
            "Assertion (A): Formative assessment informs teaching. Reason (R): It is "
            "conducted during learning. Choose the correct option.",
            [
                option("A", "Both A and R are true and R is the correct explanation of A.", True),
                option("B", "Both A and R are true but R is not the correct explanation of A."),
                option("C", "A is true but R is false."),
                option("D", "Both A and R are false."),
            ],
            statements=None,
        )
        self.assertIn("assertion_reason_payload_missing", self.codes(self.validate(q)))

    def test_source_bound_support_remains_enforced(self):
        q = classroom_scenario(source=[])
        self.assertIn("source_missing", self.codes(self.validate(q)))
        q = classroom_scenario(origin="external")
        self.assertIn("external_not_allowed", self.codes(self.validate(q)))

    def test_duplicate_and_banned_option_forms_are_rejected(self):
        q = classroom_scenario()
        q["options"][1]["text"] = q["options"][2]["text"]
        self.assertIn("duplicate_options", self.codes(self.validate(q)))
        q = classroom_scenario()
        q["options"][1]["text"] = "None of the above."
        self.assertIn("banned_option_form", self.codes(self.validate(q)))


class TestBackwardCompatibility(unittest.TestCase):
    def test_all_profiles_load(self):
        for path in sorted(PROFILES.glob("*.json")):
            prof = lib_quiz.resolve_profile({}, str(path), PROFILES)
            self.assertTrue(prof.get("name"), path.name)

    def test_generic_teaching_still_has_its_original_shape(self):
        teaching = load_json(TEACHING_PATH)
        self.assertEqual(teaching.get("name"), "TEACHING")
        self.assertIn("factual_mcq", teaching.get("preferred_question_types", []))
        self.assertIn("pedagogy_mcq", teaching.get("preferred_question_types", []))
        self.assertNotIn("question_style_profile", teaching)


if __name__ == "__main__":
    unittest.main()
