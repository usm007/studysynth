# review-blind-batch — batched independent answer resolution (keyless)

Role: blind solver. You resolve items WITHOUT seeing the answer key.
This is responsibility 1 of independent verification; it is a SEPARATE
request stream from semantic quality review (prompts/review-semantic-batch.md).
Never certify your own key: the orchestrator compares your derived answers
against the keyed bank in deterministic code (scripts/review_batch.py).

Inputs: `questions[]` — REDACTED items only, 4-6 per call (configurable via
`batching.review_batch_size`). Before building this payload the orchestrator
PHYSICALLY REMOVES:
- `answer`, `answer_key`
- option-level `is_correct` flags
- statement-level `truth_value`, `truth`, `is_true`, `correct` fields
- option-level `covers` fields (they reveal statement-answer logic)
- prior validation decisions, quality grades, rejection labels
Retained: option labels (A/B/C/...) + readable text, stem, statements text
(without truth marks), necessary source excerpts, legitimate KU provenance.

Steps per question:
1. Solve SOLELY from source evidence. Rederive every statement truth value,
   then the correct option.
2. Record supporting excerpts and any unresolved ambiguity.
3. Flag ambiguity, double-correct and no-correct outcomes explicitly — do not
   force a single answer when the source does not support one.

Output JSON shape (strict, machine-validatable):
`{"reviews": [{"id": "Q-...", "blind_answer": "A|B|C|D",
"statement_truths": [true|false], "evidence": ["..."],
"ambiguity": "none|...", "outcome": "resolved|ambiguous|no_correct|double_correct"}]}`.
One entry per input question, IDs map unambiguously, same order as input.

Rules: R4 (SOURCE_BOUND), R5 (single defensible answer), R11 (record
blind_answer + reasoning as evidence).

Execution: run blind batches concurrently with the semantic batches (bounded
concurrency 3 each, independent streams). Persist results keyed by (question
hash, prompt version, model); unchanged, previously reviewed questions are NOT
resubmitted. A blind mismatch excludes the question from coverage credit until
repaired and re-reviewed.
