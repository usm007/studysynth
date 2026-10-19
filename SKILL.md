# DocToQuiz — operating instructions

Serious exam-prep skill (UPSC/APSC/PSC/SSC/Banking/Teaching/etc.). You are the
reasoner (extract, atomize, judge importance, write questions, blind re-solve);
scripts are deterministic (ingest, recall, schema/quote/key checks, coverage,
audit, gate, render). Every LLM step writes a JSON file that scripts validate.
Nothing is "done" until the deterministic check passes. Stdlib-only (+ reportlab
for PDF, pypdf for PDF ingest/check, openpyxl for XLSX, pymupdf optional).

## Rules R1–R12 (resolve conflicts toward accuracy first)

- R1 Knowledge inventory first. Questions come from `knowledge_inventory.json`, never raw text.
- R2 Mentioning a fact is not coverage. Only `coverage.py` statuses count. CONTENT COVERAGE != COGNITIVE COVERAGE (recall/distinction/application/statement tracked separately per KU).
- R3 Never declare COMPREHENSIVE without a passing `gate.py` on a clean `audit.py`. Use CONTENT COMPLETE / COGNITIVE COVERAGE PARTIAL labels honestly; never a single misleading percentage.
- R4 SOURCE_BOUND: no fact outside the document appears as true. Fixes are rewording, not new facts.
- R5 Single-select: exactly one defensible answer (checked by blind re-solve + `stmt_check`).
- R6 Every distractor needs `distractor_origin` + `confusion_type` (schema enums) + `ku_ref` where from source + `distractor_purpose` (confusable_fact | adjacent_value | partial_truth | reversed_relation | wrong_category | wrong_entity | wrong_date | scope_error | causal_reversal). No nonsense distractors.
- R7 Never cut important KUs to hit a round number (FIXED_COUNT keeps weighted coverage + honest report).
- R8 No section over its share: `section_share_cap` (default 2.0x) enforced in `audit.py`.
- R9 No trivia/entertainment questions; sober academic tone everywhere.
- R10 Every question teaches, discriminates, or diagnoses (explanation + confusion tag).
- R11 Quote real command output for every pass/fail claim.
- R12 Percentages/status only from `report.py`/`gate.py` output, never by hand.
- R13 QUALITY ACCEPTANCE != VALIDATION: Questions must pass 11-dimension deterministic quality evaluation (factual accuracy, source fidelity, single unambiguous answer, plausible distractors, meaningful discrimination, exam value, difficulty alignment, no clues, no artificial filler, substantive statement alterations). Only quality-accepted (Rubric A/B) questions enter final package. C/D questions are rejected/repaired.

## Pipeline (prompts/ → scripts/, artifacts in build/<run_id>/)

| # | LLM step (prompt) | Deterministic script | Writes |
|---|---|---|---|
| 1 | ingest config | `scripts/ingest.py SRC --out build --run-id R` | `document_structure.json`, `normalized_source.txt` |
| 2 | — | `scripts/anchors.py struct --out anchors.json` | `anchors.json` |
| 3 | `prompts/extract.md` + `prompts/inventory.md` | hand-write inventory | `knowledge_inventory.json` (draft) |
| 4 | — | `scripts/locate_excerpts.py inventory struct` | fills char spans/paths; FAILS on non-verbatim excerpts |
| 5 | `prompts/second-pass.md` (re-extract blind) | record diff | `inventory_diff.json` |
| 6 | `prompts/classify.md` | `scripts/inventory_check.py` (+ `--ignored`, `--diff`) | recall 100%, density, diff resolved |
| 7 | `prompts/exam-design.md` (+ profile: purpose + cognitive_level + difficulty_reason per row) | — | `coverage_plan.json` (per-KU cap 3, type mix, share cap, required purposes) |
| 8 | `prompts/generate.md` + `prompts/statement-engine.md` (statement/elimination/distinction/association/chronology/exception/integrated) | hand-write bank | `question_bank.json` (draft, every question has a purpose) |
| 9 | — | `scripts/validate_questions.py` (+ profile/mode/config) | `validation_results.json`; rejected = no credit |
| 10 | `prompts/validate-blind.md` (solve keyless from source) | record | `validation_semantic.json` |
| 11 | `prompts/validate-semantic.md` (checklist per question) | record | `validation_semantic.json` |
| 12 | — | `scripts/coverage.py`, `scripts/dedupe.py` | `coverage_matrix.json` (content + cognitive per-KU, purpose/section/tier coverage, CONTENT/CONGITIVE labels), `dedupe_report.json` |
| 13 | `prompts/audit-review.md` | `scripts/audit.py` | `audit_report.json` (cognitive gaps, distinction gaps, purpose coverage, cluster status) (+ keep `audit_report_roundN.json`) |
| 14 | `prompts/gap-fill.md` (exact missing forms/clusters/purposes only) | loop 9–13, max 5 rounds | gap-fill bank additions |
| 15 | — | `scripts/gate.py` → `scripts/report.py` | `gate.json` + printed FINAL REPORT (quote it) |
| 16 | `prompts/revision.md` | `scripts/package.py --inventory ...` | `quiz_package.json` (validated only, tiers stamped) |
| 17 | — | `scripts/build_web.py`, `scripts/build_pdf.py`, `scripts/check_pdf.py` | `quiz.html`, `pdf/*.pdf`, `check_report.json` |

`scripts/pipeline.py --source --run-id --profile --config [--processing-mode MODE --inventory --bank --ignored --diff]`
runs the deterministic stages with checkpoints/resume (`--redo STAGE`).
`--processing-mode` accepts `QUICK`, `BALANCED` (default), or `COMPREHENSIVE`.
Stage-specific dependency fingerprints avoid unnecessary stage invalidation on downstream changes.
`--redo STAGE` invalidates that stage + descendants; `--redo all` forces recompute.

## Processing modes (`--processing-mode`)

Select mode consistently:
- **`QUICK`**: Use when the user requests a quick practice set, a small batch, a sample, or a fast first pass.
  - Primary extraction workflow runs over selected source.
  - Skips the exhaustive second-pass sweep across every source chunk.
  - Targeted source checks for answer-critical facts, uncertain evidence, uncovered anchors, and critical tables/dates/numbers.
  - Retains both blind and semantic review streams and all 11 deterministic quality gates.
  - Default maximum gap-fill rounds: **1**.
  - Re-reviews only new or modified questions.
  - Result status is `LIMITED`; never marked `COMPREHENSIVE`.
- **`BALANCED`** (Default in `config.default.json`): Use for ordinary chapter-to-quiz, notes-to-quiz, and study-material generation.
  - Full primary source extraction over the complete source.
  - Reconciles inventory, classifies units, and prioritizes Tier 1 and Tier 2 units for generation.
  - Skips redundant exhaustive second-pass sweep over every chunk; runs targeted secondary checks for anchor gaps, answer-critical claims, and structured tables.
  - Retains both independent review streams and all deterministic quality gates.
  - Default maximum gap-fill rounds: **2**.
  - Re-reviews only new or modified questions.
  - Result status is `LIMITED` with explicit reduced verification scope; never marked `COMPREHENSIVE`.
- **`COMPREHENSIVE`**: Use when the user explicitly requests an exhaustive question bank, comprehensive coverage, or complete source verification.
  - Full primary extraction AND independent exhaustive second-pass recall sweep across every source chunk (tables, lists, captions, footnotes, numbers, dates).
  - Global classification and reconciliation, both independent review streams, all 11 quality checks, deduplication.
  - Default maximum gap-fill rounds: **5**.
  - Comprehensive tier targets (T1/T2 100%) and cognitive requirements enforced.
  - Result status may be `COMPREHENSIVE` only when substantiated by passing audit and gate evidence.

Mode selection rules:
- Explicit exhaustive/full-coverage request → `COMPREHENSIVE`
- Explicit quick/sample/small practice request → `QUICK`
- All ordinary chapter and notes conversions → `BALANCED`
- `processing_mode` is independent from `fidelity_mode` (`SOURCE_BOUND` / `ENHANCED`) and `scope_mode` (`COMPREHENSIVE` / `FIXED_COUNT`).

## Execution phases (same product, fewer serial calls)

### Phase A — Source understanding
- Parse + deterministic anchors (`ingest.py`, `anchors.py`), then group blocks
  into section-aware chunks (~5000 input tokens, `batching.extraction_chunk_tokens`; tables intact, deterministic chunk_id).
- `prompts/extract.md` takes `blocks[]` per chunk; run chunks concurrently
  (bounded concurrency 3). Merge in chunk order; dedupe overlaps ONLY by stable source identity
  (block_id + normalized excerpt), never fuzzy-merge distinct facts.
- In `COMPREHENSIVE` mode, `prompts/second-pass.md` runs an exhaustive independent sweep across all chunks.
  In `QUICK` and `BALANCED` modes, targeted secondary checks focus on anchor gaps, uncertain claims, and structured tables.
- Classify per section (`prompts/classify.md`), then GLOBAL reconciliation
  (`prompts/exam-design.md`) for cross-section clusters, cognitive forms,
  purposes, type mix. Never finalize per-section blueprints alone.
- `locate_excerpts.py` + `inventory_check.py` verify every excerpt/region.

### Phase B — Exam design and generation
- Blueprint only after the inventory is reconciled.
- Generate up to 8 questions/call (`prompts/generate.md` -> `{"questions": [...]}`),
  grouped by section, bounded concurrency 4 (`batching.question_concurrency`), STABLE IDs per blueprint row. Statement
  fields are inlined in the same call (no second statement-engine call).
- Merge in input order; reject duplicate IDs; retry ONLY the failed batch.

### Phase C — Independent verification + deterministic controls
- TWO separate batched streams (`prompts/review-batch.md` protocol):
  blind-answer review (`review-blind-batch.md`, PHYSICALLY redacted payload —
  no answer/answer_key, is_correct, truth fields, covers, prior decisions)
  and semantic quality review (`review-semantic-batch.md`, full item), up to 6 questions/call (`batching.review_batch_size`).
  Run both streams concurrently (bounded concurrency 4 each); never merge into one self-review.
- `scripts/review_batch.py` compares blind answers vs bank key in code; a
  mismatch excludes the question from coverage (`coverage.py --blind`) until
  repaired and re-reviewed.
- Deterministic `validate_questions.py` + 11-dimension `quality.py` +
  `dedupe.py` run concurrently on the frozen bank; coverage waits for all
  eligibility reports. Persist both review streams; never re-review unchanged
  questions; re-review every new/modified one.

### Phase D — Targeted gap closure and delivery
- Gap-fill is event-driven (`prompts/gap-fill.md`): one compact manifest/round
  (uncovered T1/T2, missing forms/purposes/clusters, failed IDs, accepted
  status); batched candidates; validate/review ONLY new/changed items;
  recompute audit+gate; stop on COMPREHENSIVE (in COMPREHENSIVE mode), on no progress, or at mode-specific max rounds
  (1 for QUICK, 2 for BALANCED, 5 for COMPREHENSIVE). No full-bank LLM audit pass: `audit.py`/`gate.py` are authoritative
  and the model never overrides them.
- Repair locally: `repair_queue.json` carries exact reasons + excerpts + KU
  mappings; max `max_repair_retries: 2`; excluded items stay as coverage gaps.
  Unrecoverable stage failures still abort.
- After the package is immutable, build HTML + requested PDFs concurrently
  (separate outputs, errors propagate); never build PDFs when not requested.

## Agent operating rules
- Work independent chunks/batches concurrently where supported; keep a content-addressed batch
  ledger (`batch_progress.json`: completed vs pending per stream with payload/schema/config fingerprints)
  and persist successful work atomically before starting the next stage, so interruption resumes
  pending or invalidated batches instead of restarting.
- Reuse only dependency-valid results (`artifact_manifest.json` stage-specific fingerprints);
  `--redo STAGE` invalidates that stage + descendants.
- Use deterministic code for deterministic decisions; quote script output for
  every pass/fail claim; never bypass a failed gate or claim COMPREHENSIVE
  without `gate.py` evidence.
  every pass/fail claim; never bypass a failed gate or claim COMPREHENSIVE
  without `gate.py` evidence.

## Deterministic performance rules

- Content-addressed cache (`artifact_manifest.json`): reuse only when input hashes
  + config/profile hashes + script version + prompt version + model id all match.
  Changing source/profile/prompt/question/config/schema/code invalidates descendants.
- Coverage MUST be computed with `--quality quality_report.json --dedupe dedupe_report.json`
  (plus `--blind blind_review.json` when the blind-review comparison exists)
  for new-engine banks (explicit purposes present):
  only validated + quality-accepted + non-duplicate + blind-agreeing questions
  earn credit
  (primary full, secondary partial, distractor_basis zero). Legacy banks without
  purpose tags are grandfathered to validation-only credit (mirroring `gate.py`);
  their quality/dedupe reports are still built and audited.
- Safe parallelism only: validate/quality/dedupe run concurrently after inputs freeze
  (coverage waits for all three); web + pdf run concurrently after the package is
  immutable. Never build PDFs when not requested.
- Metrics (`run_metrics.json`): stage durations, counts, chunks/batches, cache
  hits/misses, rejected/repaired/accepted/excluded, gap rounds, html/pdf times.
  Model-call counts marked unavailable when the orchestrator cannot observe them.

## Field contracts (must match schemas/*.json)

- KU: `id KU-####`, `type` (schema enum), `supporting_excerpt` verbatim, `source{block_id,...}`,
  `origin source|external`, `tier 1-4`, `tier_history[{from,to,reason}]`, `dimensions` (base low/med/high;
  exam_relevance also allows very_high; optional recall/conceptual/confusion/elimination/statement values),
  optional `cognitive_level` (recall|understanding|distinction|application|analysis),
  `confusion_cluster`, `prerequisite_units`. Exam-value fields drive blueprinting.
- Question roles: `knowledge_units[{ku_id, role: primary|secondary|distractor_basis}]`;
  coverage = primary full, secondary partial, distractor_basis zero; only `validated` count.
- Statements: `{text, truth_value, ku_basis, alteration, alteration_type}`; options carry
  `covers: [n,...]` for key-logic checking.
- `confusion_type` enum: near_synonym, adjacent_value, reversed_causality, wrong_date,
  wrong_person, wrong_place, wrong_article, partial_truth, overgeneralization, plausible_external.
- Question `type` enum: factual_mcq, statement_based, assertion_reason, match_pairs,
  elimination_mcq, one_liner_mcq, data_interpretation_mcq, reasoning_mcq, pedagogy_mcq,
  sequence_mcq, true_false (2 options allowed).
- Gate: COMPREHENSIVE iff tier1=tier2=100% validated, recall at threshold, diff resolved,
  no density/downgrade/skew/dup flags, no limitations, plus (new-engine banks) required
  cognitive forms present, no critical KU only weakly tested, required exam purposes present,
  high-priority confusion clusters addressed. Any limitation → at most LIMITED.
  `gate.py` recomputes from the audit body; hand-edited status headers are ignored.
  Difficulty = reasoning demand (easy recall / medium relation-distinction / hard statement-elimination-integration).
- Modes: fidelity `SOURCE_BOUND` (default) | `ENHANCED` (external tagged+shown);
  scope `COMPREHENSIVE` (default) | `FIXED_COUNT` (exact N, honest coverage report).
- Never invent facts (R4); never claim 100% without script output (R12).

## Revision engine (Phase 2)

Learner attempts become observable performance events; `scripts/revision.py`
aggregates them per primary KU (secondaries exposure-only, distractor_basis
ignored), scores deterministic priorities (tier/exam-relevance amplify
observed errors only), tracks NEW/LEARNING/WEAK/IMPROVING/STABLE mastery
overall and per cognitive form, and builds reason-coded revision queues and
sessions. Same algorithm runs in the browser (`templates/web/revision.engine.js`,
inlined by `build_web.py`); Python is the source of truth, node parity tests
enforce agreement. Sessions persist as v2 (`study_session_version: 2`;
legacy formats migrate via `migrate_session`). New revision questions come
only from validated banks or via the `revision_request` hook + 
`validate_revision_question` — unvalidated output never reaches learners.

## Question Quality Engine (Phase 3)

Questions must satisfy competitive-exam quality beyond MCQ validity:
- **11 Evaluation Dimensions:** accuracy, source_support, uniqueness, distractor_quality, exam_value, difficulty_fit, clarity, purpose_fit, leak_prevention, statement_quality, explanation_quality (`scripts/quality.py`).
- **Deterministic Purpose Mismatch:** Every question has an explicit purpose matching its actual cognitive mechanism (`direct_recall`, `conceptual_understanding`, `distinction`, `confusable_fact`, `statement_evaluation`, `elimination`, `chronology`, `classification`, `association`, `exception`, `cause_effect`, `application`, `integrated_concept`). Flag and reject questions with mismatched purposes (e.g. asking a date under `distinction`).
- **Distractor Quality:** Distractors must be domain-relevant, plausible, based on genuine confusion, and differ along a meaningful dimension. Absurd/impossible options, duplicate options, and accidental giveaways are rejected.
- **Statement Construction:** Statement questions must alter substantive properties (date, entity, place, function, classification, relationship, scope, causality, exception, quantitative value), not trivial syntactic tricks.
- **Elimination & Difficulty:** Difficulty arises from knowledge and reasoning demand (easy = direct recall, medium = distinction/classification/association, hard = statement evaluation/elimination/integration), never artificial filler or convoluting language.
- **Human Rubric:** A (Excellent), B (Good), C (Needs improvement), D (Reject). Package gate permits only A/B questions (`scripts/package.py`). C/D questions are rejected or repaired.
- **Separate Statuses:** `validation_status` ("validated" | "rejected") tracks syntactic/semantic validity; `quality_status` ("accepted" | "rejected") tracks competitive-exam quality standards.
