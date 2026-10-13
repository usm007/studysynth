# review-batch — batched independent verification protocol (two streams)

Independent verification stays TWO distinct responsibilities, each batched:

1. **Blind-answer review** (`prompts/review-blind-batch.md`): keyless re-solve,
   4-6 redacted questions per call. The reviewer never sees the key.
2. **Semantic exam-quality review** (`prompts/review-semantic-batch.md`):
   full-item quality review, 4-6 questions per call. It does not re-derive the
   answer; answer correctness is owned by stream 1 + deterministic `stmt_check`.

The two streams are independent batch requests; run them concurrently (bounded
concurrency 3 each). Never merge them into a single self-review: the blind
stream must not receive key material, and neither stream certifies its own key.

Redaction (before the blind payload is built, physically remove):
`answer`, `answer_key`, option `is_correct`, statement `truth_value`/`truth`/
`is_true`/`correct`, option `covers`, prior decisions/grades/labels.
Retain labels, stem, statement text, excerpts, KU provenance.

Deterministic comparison (`scripts/review_batch.py`): blind-derived answers are
matched against the keyed bank in code. A mismatch excludes the question from
coverage credit (`coverage.py --blind`) until repaired and re-reviewed.

Persist both streams' results keyed by (question hash, prompt version, model).
Unchanged, previously reviewed questions are NOT resubmitted; every new or
modified question is reviewed again. Deterministic validation + the
11-dimension quality engine still run for every question.
