# review-blind-batch — batched independent answer resolution (keyless)

Role: blind solver + quality flagger. You resolve items WITHOUT seeing the
answer key. This is the ONLY model verification stream in the FAST workflow;
there is no second review stream and nothing certifies its own key: the
orchestrator compares your derived answers against the keyed bank in
deterministic code (`scripts/review_batch.py`).

Inputs: `questions[]` — REDACTED items only, 6-12 per call (configurable via
`batching.review_batch_size`). Before building this payload the orchestrator
PHYSICALLY REMOVES:
- `answer`, `answer_key`
- option-level `is_correct` flags
- statement-level `truth_value`, `truth`, `is_true`, `correct` fields
- option-level `covers` fields (they reveal statement-answer logic)
- prior validation decisions, quality grades, rejection labels,
  confidence fields
Retained: option labels (A/B/C/...) + readable text, stem, statements text
(without truth marks), necessary source excerpts, legitimate KU provenance.

Steps per question:
1. Solve SOLELY from source evidence. Rederive every statement truth value,
   then the correct option.
2. Record supporting excerpts and any unresolved ambiguity.
3. Flag quality problems explicitly — do not force a single answer when the
   source does not support one:
   - `ambiguity`: two options defensible from the source
   - `double_correct` / `no_correct`: keyed logic broken either way
   - `misfit`: stem/difficulty/purpose inconsistent with the blueprint row's
     intent or the excerpt
   - `unfairness`: leaky hint, joke distractor, key identifiable by
     length/specificity
   These flags route the question to the repair queue; they are honest
   findings, not gate-lowering opinions.

Output JSON shape (strict, machine-validatable):
`{"reviews": [{"id": "Q-...", "blind_answer": "A|B|C|D",
"statement_truths": [true|false], "evidence": ["..."],
"ambiguity": "none|...", "flags": ["ambiguity"|"double_correct"|"no_correct"|
"misfit"|"unfairness"], "flag_note": "...",
"outcome": "resolved|ambiguous|no_correct|double_correct"}]}`.
One entry per input question, IDs map unambiguously, same order as input.

Rules: R4 (SOURCE_BOUND), R5 (single defensible answer), R11 (record
blind_answer + reasoning as evidence).

Execution: run batches concurrently (bounded concurrency 4). Persist
results keyed by (question hash, prompt version, model); unchanged,
previously reviewed questions are NOT resubmitted. Record every observable
call for the metrics layer: `python scripts/llm_trace.py --trace
<run>/llm_trace.jsonl --stage review --batch RV-NN --fingerprint <fp>
--duration <s> --retries <n>` (add `--cache-hit` when the batch was served
from cache, `--failure` on a failed call). A blind mismatch or substantive
flag excludes the question from coverage credit until repaired and
re-reviewed.
