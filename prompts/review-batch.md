# review — the single independent verification stream

Independent verification is ONE blind review stream, run batched:

- **Blind-answer review** (`prompts/review-blind-batch.md`): keyless
  re-solve + quality flags, 6-12 redacted questions per call
  (`batching.review_batch_size`). The reviewer never sees the key.
- There is no second "semantic review" stream. Semantic exam-quality
  judgments come from the deterministic quality engine
  (`scripts/quality.py`, 11 dimensions) plus the reviewer's quality flags;
  answer correctness is owned by the blind stream + deterministic
  `stmt_check` + code-level comparison.

Redaction (before the blind payload is built, physically remove):
`answer`, `answer_key`, option `is_correct`, statement `truth_value`/`truth`/
`is_true`/`correct`, option `covers`, prior decisions/grades/labels,
confidence fields. Retain labels, stem, statement text, excerpts, KU
provenance.

Deterministic comparison (`scripts/review_batch.py`): blind-derived answers
are matched against the keyed bank in code. A mismatch, or a substantive
reviewer flag (ambiguity / double-correct / no-correct / unanswerable),
routes the question to the repair queue (`repair.json`); such questions are
excluded from coverage credit (`coverage.py --blind`) until repaired AND
re-reviewed. Bad review outcomes weaken the gate; they never lower the bar.

Persistence and resume: results are keyed by (question hash, prompt
version, model) in the run directory. Unchanged, previously reviewed
questions are NOT resubmitted; every new or modified question is reviewed
again. Deterministic validation + the quality engine still run for every
question regardless.

Batch honesty: record every observable call for the metrics layer
(`python scripts/llm_trace.py --trace <run>/llm_trace.jsonl --stage review
--batch RV-NN --duration <s> --retries <n>`). Run independent batches
concurrently (bounded concurrency 4).
