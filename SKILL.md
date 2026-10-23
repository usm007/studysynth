---
name: StudySynth
description: Use when turning reference documents, notes, chapters, or existing question banks into exam-ready multiple-choice sets for UPSC, APSC, State PSC, SSC, Banking, Railways, or Teaching exams; when a bank must be audited, repaired, or proven source-bound and quality-accepted; or when a verified package must be rendered as a standalone HTML quiz or print-ready A4 PDF papers.
---

# StudySynth — operating instructions

Version 1.0 · Python 3.9+.

Serious exam-prep skill (UPSC/APSC/PSC/SSC/Banking/Teaching/etc.). You are the
reasoner (extract, atomize, judge importance, write questions, blind re-solve);
scripts are deterministic (ingest, recall, schema/quote/key checks, coverage,
audit, gate, render). Every LLM step writes a JSON file that scripts validate.
Nothing is "done" until the deterministic check passes. Stdlib-only core (+
pypdf for PDF ingest/check and delivery validation, reportlab for PDF build,
openpyxl for XLSX; pymupdf and psutil optional).

## When to use this skill

- Converting a source document (PDF, DOCX, PPTX, XLSX, TXT, MD, HTML) into a
  verified question bank for a competitive objective exam.
- Auditing, repairing, or re-verifying an existing bank: coverage, dedupe,
  answer-key consistency, distractor quality, source fidelity.
- Producing deliverables: standalone offline HTML quiz, print-ready A4 PDFs
  (question paper, answer key, explanations), or a single delivery folder.
- Any deliverable where "complete" or "validated" must be backed by evidence
  rather than assertion.

## When not to use

- No source material and the user wants explanation, tutoring, or discussion —
  answer directly.
- The request needs facts beyond the source as truth. ENHANCED fidelity is
  opt-in and every external fact must be tagged and shown.
- A throwaway trivia list with no accuracy or coverage claim.
- Bulk prose rewriting or translation of the source.

## Quick start

**Input**: one source file. No exam profile is required — pipelines run a
generalized competitive-exam authoring policy; `profiles/<EXAM>.json` is
optional style input (authoring wording/distractor/archetype rules only; it
never changes the workflow, the count, or the gates).

1. **Structure + plan scaffold** — deterministic only:
   ```
   python scripts/pipeline.py --source <file> --run-id <id> \
     --config config.default.json
   ```
   Writes `document_structure.json`, `anchors.json`, and `chunks.json` (the
   extraction chunking, computed in code). Stages that need the model stop
   with `pending (LLM step)`; that is expected, not a failure.
2. **Extraction** — one pass per chunk from `prompts/extract.md` (extraction +
   classification + scoring + question hints in the SAME call; save outputs as
   `chunk_<n>.json`), verify excerpts with `scripts/locate_excerpts.py`, then
   generate batches and blueprint with the deterministic planner:
   ```
   python scripts/plan.py --document-structure build/<id>/document_structure.json \
     --out-dir build/<id> --config config.default.json --extraction-dir build/<id>
   ```
   This merges chunks (identity dedupe only), writes
   `knowledge_inventory.json`, `coverage_plan.json` and
   `generation_batches.json`. Re-run step 1 with
   `--inventory build/<id>/knowledge_inventory.json` to continue.
3. **Bank** — write one `batch_<n>.json` per generation batch
   (`prompts/generate.md`, ~12 questions/call), then assemble and continue:
   `python scripts/plan.py --bank-from build/<id> --bank-out build/<id>/question_bank.json`
   followed by step 1 again adding `--bank build/<id>/question_bank.json`.
4. **Blind review + repair** — the single independent verification stream
   (`prompts/review-batch.md`): keyless re-solve of redacted questions,
   compared in code; failures land in the repair queue and take exactly one
   bounded repair round (`prompts/repair.md`).
5. **Deliver** — re-run the pipeline adding `--full` (package + HTML + PDF)
   or `--deliver` (single delivery folder). The requested question count is
   an ordinary parameter: pass `--count N` to step 1/planner when the user
   asks for N; otherwise the default count policy applies and any shortfall
   is reported honestly, never padded.

**Outputs** in `build/<id>/`: `quiz_package.json`, `quiz.html`,
`pdf/question-paper-A.pdf`, `pdf/answer-key-B.pdf`, `pdf/explanations-C.pdf`,
and the evidence trail (`validation_results.json`, `quality_report.json`,
`coverage_matrix.json`, `audit_report.json`, `gate.json`, `run_metrics.json`,
`llm_trace.jsonl`). Report status from `gate.json` and the printed FINAL
REPORT only.

## Verify the artifact (dry run)

`examples/starter_bank.json` is a small, complete run. From the repo root:

```
python scripts/pipeline.py --source examples/sample_source.md --run-id verify \
  --config config.default.json \
  --inventory examples/sample_inventory.json --bank examples/starter_bank.json \
  --ignored examples/ignored_anchors.json --full
```

Expected: `14/14 validated`, `14/14 quality-accepted`, `GATE: PARTIAL` (a starter
bank cannot cover every tier-1/2 KU or cognitive form), and `build/verify/`
should contain `quiz_package.json`, `quiz.html`, and three A4 PDFs.
`pdf_check_report.json` must say `OVERALL: PASS`. A failure here is a defect in
this manual or its bundled assets, not in the source document.

`examples/ignored_anchors.json` records the six structural anchors (document
title, section headings, table headers) that are excluded from recall, with a
reason each. They are layout, not examinable facts.

The 64-question `examples/sample_bank.json` is the legacy coverage fixture used
by the contract tests. It predates explicit purposes, so it is not the packaging
demo; `starter_bank.json` is.

## When a gate fails

- `gate.json` and `audit_report.json` are the authority. Read `limitations`,
  uncovered KUs, and flags; never edit either file to change a verdict.
- Repair the cause in the inventory or bank, then re-run with
  `--redo <stage>` — it invalidates that stage and all descendants;
  `--redo all` forces a full recompute.
- A nonzero exit from validation is signal, not a crash: rejected questions go
  to `repair_queue.json` with exact reasons, valid items continue, and each item
  gets `max_repair_retries` attempts (default 2).
- Unfixable gaps remain visible. Deliver as the honest status the gate
  produced (LIMITED for a clean single-pass run, PARTIAL when substance
  still fails); never promote a run to COMPREHENSIVE without verified
  exhaustive-sweep evidence — and the single FAST workflow does not run
  that sweep, so a clean one-pass run is LIMITED by design. There is
  exactly ONE targeted repair round (`max_repair_rounds: 1`), not a
  gap-fill loop; failures after it are final and stay visible.

## Rules R1–R13 (resolve conflicts toward accuracy first)

- R1 Knowledge inventory first. Questions come from `knowledge_inventory.json`, never raw text.
- R2 Mentioning a fact is not coverage. Only `coverage.py` statuses count. CONTENT COVERAGE != COGNITIVE COVERAGE (recall/distinction/application/statement tracked separately per KU).
- R3 Never declare COMPREHENSIVE without a passing `gate.py` on a clean `audit.py`. Use CONTENT COMPLETE / COGNITIVE COVERAGE PARTIAL labels honestly; never a single misleading percentage.
- R4 SOURCE_BOUND: no fact outside the document appears as true. Fixes are rewording, not new facts.
- R5 Single-select: exactly one defensible answer (checked by blind re-solve + `stmt_check`).
- R6 Every distractor needs `distractor_origin` + `confusion_type` (schema enums) + `ku_ref` where from source + `distractor_purpose` (confusable_fact | adjacent_value | partial_truth | reversed_relation | wrong_category | wrong_entity | wrong_date | scope_error | causal_reversal). No nonsense distractors.
- R7 Never cut important KUs to hit a round number (the count policy keeps
  weighted coverage + an honest report of what was deferred).
- R8 No section over its share: `section_share_cap` (default 2.0x) enforced in `audit.py`.
- R9 No trivia/entertainment questions; sober academic tone everywhere.
- R10 Every question teaches, discriminates, or diagnoses (explanation + confusion tag).
- R11 Quote real command output for every pass/fail claim.
- R12 Percentages/status only from `report.py`/`gate.py` output, never by hand.
- R13 QUALITY ACCEPTANCE != VALIDATION: Questions must pass 11-dimension deterministic quality evaluation (factual accuracy, source fidelity, single unambiguous answer, plausible distractors, meaningful discrimination, exam value, difficulty alignment, no clues, no artificial filler, substantive statement alterations). Only quality-accepted (Rubric A/B) questions enter final package. C/D questions are rejected/repaired.

## Pipeline (prompts/ → scripts/, artifacts in build/<run_id>/)

| # | Step (LLM pass or deterministic) | Script / prompt | Writes |
|---|---|---|---|
| 1 | ingest config | `scripts/ingest.py SRC --out build --run-id R` | `document_structure.json`, `normalized_source.txt` |
| 2 | — | `scripts/anchors.py struct --out anchors.json` | `anchors.json` |
| 3 | — | `scripts/plan.py --document-structure --out-dir ` (no inventory yet) | `chunks.json` (deterministic chunking, chunk ids) |
| 4 | `prompts/extract.md` — ONE call per chunk: extract + classify + dimensions + tiers + question hints | save `chunk_<n>.json` per chunk | per-chunk extraction files |
| 5 | — | merge + blueprint in `scripts/plan.py --extraction-dir` (identity dedupe, tiers, hints→rows, per-KU cap, section share cap, count policy) | `knowledge_inventory.json`, `coverage_plan.json`, `generation_batches.json` (~12 rows/batch with evidence packs) |
| 6 | `prompts/generate.md` — one batch per call (~12 rows), statements inlined | save `batch_<n>.json` | per-batch generation files |
| 7 | — | assemble bank: `scripts/plan.py --bank-from` (deterministic order, duplicate-ID rejection) | `question_bank.json` |
| 8 | — | `scripts/validate_questions.py` (+ optional profile/config) | `validation_results.json`; rejected = no credit |
| 9 | `prompts/review-batch.md` → `prompts/review-blind-batch.md` (sole review stream; PHYSICALLY redacted payload) | `scripts/review_batch.py` compares blind answers in code | blind review records; mismatches → `repair.json` |
| 10 | — | `scripts/quality.py`, `scripts/dedupe.py` | `quality_report.json` (11 dimensions, Rubric A–D), `dedupe_report.json` |
| 11 | — | `scripts/coverage.py` | `coverage_matrix.json` (content + cognitive per-KU, purpose/section/tier coverage, CONTENT/COGNITIVE labels) |
| 12 | `prompts/repair.md` — ONE bounded round, only queued questions | re-validate + re-review repaired items | `repair.json` outcomes; retired items stay excluded |
| 13 | — | `scripts/audit.py`, `scripts/gate.py` → `scripts/report.py` | `audit_report.json` + `gate.json` + printed FINAL REPORT (quote it) |
| 14 | `prompts/revision.md` | `scripts/package.py --inventory ...` | `quiz_package.json` (validated only, tiers stamped) |
| 15 | — | `scripts/build_web.py`, `scripts/build_pdf.py`, `scripts/check_pdf.py` | `quiz.html`, `pdf/*.pdf`, `check_report.json` |

The pipeline command runs the deterministic stages with checkpoints/resume
(`--redo STAGE`):
`scripts/pipeline.py --source --run-id --config [--profile <optional style profile>] [--inventory --bank --ignored --diff --count]`.

**Profile style context** (optional). When a profile is supplied AND contains a
`question_style_profile` block (for example `profiles/CTET.json`), generate the
style context before the corresponding LLM step and prepend it to that prompt:

```
python scripts/profile_style.py --profile profiles/CTET.json --stage extract
python scripts/profile_style.py --profile profiles/CTET.json --stage generate
```

The block changes only how questions are selected and worded. It never supplies
paper counts, durations, sections, marks or type percentages. Profiles without
the block produce no context and keep the generic behaviour. After generation,
`scripts/validate_questions.py --profile <profile.json>` also applies
`validate_question_style(question, profile)` where provided and rejects
style-specific defects (classroom context, absurd distractors, answer-length
clues, passage requirements, assertion-reason payload, banned option forms)
while keeping SOURCE_BOUND enforced.

Stage-specific dependency fingerprints avoid unnecessary stage invalidation on
downstream changes. `--redo STAGE` invalidates that stage + descendants;
`--redo all` forces recompute. There is NO `--processing-mode` flag and no
QUICK/BALANCED/COMPREHENSIVE processing modes: one FAST workflow covers every
request, and the requested question count is an ordinary parameter
(`--count N`), not a mode. `fidelity_mode` (`SOURCE_BOUND` default / `ENHANCED`
opt-in external facts) still applies.

## One workflow, honest scope (no processing modes)

There is exactly ONE processing workflow (FAST). Requested question count,
speed, and sample-vs-full scope are ordinary parameters, not modes:

- `--count N` (planner + pipeline): honor the request as far as the source
  supports, highest-priority material first; report any shortfall and the
  deferred KUs; never manufacture filler to hit N (R7).
- No usability or depth knobs: extraction is one pass per chunk
  (`prompts/extract.md`), planning/reconciliation is fully deterministic
  (`scripts/plan.py`), generation is batched ~12 rows/call, and verification
  is the single blind review stream (6-12/call) — no separate semantic
  review pass.
- Status semantics: a clean single-pass run is honestly `LIMITED`
  (verification scope: no exhaustive second-pass sweep). `COMPREHENSIVE`
  is reached only when verified `exhaustive_second_pass` evidence exists
  (legacy fully-audited runs); the FAST workflow never synthesizes it, so
  never write it by hand. Substantive failures keep `PARTIAL` with exact
  reasons — bad review outcomes never lower the bar.
- Inventory diff (`--diff`) and ignored anchors (`--ignored`) still feed
  `inventory_check.py`; record the extraction diff honestly when the
  source understanding pass yields a different reading than the original
  inventory. There is no mandatory blind re-extraction sweep; targeted
  re-checks happen when evidence disagrees (anchor gaps, uncertain claims,
  structured tables).

## Execution phases (same product, fewer serial calls)

### Phase A — Source understanding + deterministic planning
- Parse + deterministic anchors (`ingest.py`, `anchors.py`), then group blocks
  into section-aware chunks IN CODE (`plan.py` -> `chunks.json`, ~5000 input
  tokens, `batching.extraction_chunk_tokens`; tables intact, deterministic
  chunk_id).
- `prompts/extract.md` takes `block_ids` per chunk and emits extraction +
  classification + dimensions + tiers + `question_hints` in ONE call per
  chunk; run chunks concurrently (bounded concurrency 3). Save each result
  as `chunk_<n>.json`. The planner merges in chunk order; dedupe overlaps
  ONLY by stable source identity (block_id + normalized excerpt), never
  fuzzy-merge distinct facts.
- `locate_excerpts.py` + `inventory_check.py` verify every excerpt/region
  (recall 100% on non-ignored anchors, density, diff resolved).
- Reconciliation and blueprinting are DETERMINISTIC (`plan.py`): tier/value
  prioritization, hints -> blueprint rows bounded by `per_ku_cap` (3),
  section share cap (2.0x mean, R8), count policy with honest shortfall
  notes. No global LLM design pass; question_hints during extraction are the
  only model-shaped planning input, and the planner may drop hints it cannot
  honor — it never manufactures quota.

### Phase B — Generation
- Batches come from `generation_batches.json` (~12 rows/call,
  `prompts/generate.md` -> `{"questions": [...]}`, bounded concurrency 4,
  `batching.question_concurrency`), each with a compact evidence pack (cited
  KUs + excerpts + confusable partners) so a request is self-contained
  (no second planning request).
- STABLE IDs per blueprint row position; statement fields are inlined in
  the same call (no second statement call). Merge in input order
  (`plan.py --bank-from`); reject duplicate IDs; retry ONLY the failed
  batch; record every call via `scripts/llm_trace.py` (see honest metrics).

### Phase C — Independent verification + deterministic controls
- ONE review stream (`prompts/review-batch.md` -> `review-blind-batch.md`):
  keyless re-solve + quality flags, 6-12 questions/call
  (`batching.review_batch_size`), PHYSICALLY redacted payload — no
  answer/answer_key, is_correct, truth fields, covers, prior decisions;
  bounded concurrency 4. There is no second "semantic review" stream;
  semantic quality is owned by the deterministic engines + the reviewer's
  flags. Never let a stream certify its own key.
- `scripts/review_batch.py` compares blind answers vs bank key in code; a
  mismatch or substantive flag excludes the question from coverage
  (`coverage.py --blind`) until repaired and re-reviewed.
- Deterministic `validate_questions.py` + 11-dimension `quality.py` +
  `dedupe.py` run concurrently on the frozen bank; coverage waits for all
  eligibility reports. Persist the review stream; never re-review unchanged
  questions; re-review every new/modified one.

### Phase D — One bounded repair round + delivery
- Failures (blind mismatches, validation/quality rejects, duplicate flags,
  anchor misses) converge into `repair.json`; `prompts/repair.md` fixes or
  retires ONLY queued questions, then repaired items re-run validate +
  quality + blind review. Exactly ONE round (`max_repair_rounds: 1`); no
  gap-fill loop. `audit.py`/`gate.py` are authoritative and the model never
  overrides them; the final status reports what survived, honestly.
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
- Metrics (`run_metrics.json`) are truthful: stage durations, chunks/batches
  (`work_counts`), cache hits/misses, validated/rejected/accepted/retired,
  html/pdf times, and the model layer split (`time.model_s` vs
  `time.python_s`). Every observable model call is recorded to
  `llm_trace.jsonl` via the CLI
  `python scripts/llm_trace.py --trace <run>/llm_trace.jsonl --stage <stage>
  --batch <batch-id> --fingerprint <fp> --duration <s> [--retries N]
  [--cache-hit] [--failure] [--input-tokens N --output-tokens N]`; the
  summary reports per-stage calls/durations/retries/cache hits and token
  counts ONLY when the provider exposed them — otherwise token counts read
  `"unavailable"` (never fabricated). No call recorded → `model_calls` is
  explicitly `"unavailable (no llm_trace.jsonl recorded…)"`.

## Field contracts (must match schemas/*.json)

- KU: `id KU-####`, `type` (schema enum), `supporting_excerpt` verbatim, `source{block_id,...}`,
  `origin source|external`, `tier 1-4`, `tier_history[{from,to,reason}]`, `dimensions` (base low/med/high;
  exam_relevance also allows very_high; optional recall/conceptual/confusion/elimination/statement values),
  optional `cognitive_level` (recall|understanding|distinction|application|analysis),
  `confusion_cluster`, `prerequisite_units`. Exam-value fields drive blueprinting.
  Profile-guided banks also carry optional `content_kind`, `pedagogical_relevance`,
  `classroom_application_potential`, `has_passage` and `archetype_hints`.
- Question roles: `knowledge_units[{ku_id, role: primary|secondary|distractor_basis}]`;
  coverage = primary full, secondary partial, distractor_basis zero; only `validated` count.
  Profile-guided questions may also carry `archetype`, `content_kind`,
  `classroom_context_required` and `passage`; these do not change coverage credit.
- Statements: `{text, truth_value, ku_basis, alteration, alteration_type}`; options carry
  `covers: [n,...]` for key-logic checking.
- `confusion_type` enum: near_synonym, adjacent_value, reversed_causality, wrong_date,
  wrong_person, wrong_place, wrong_article, partial_truth, overgeneralization, plausible_external.
- Question `type` enum: factual_mcq, statement_based, assertion_reason, match_pairs,
  elimination_mcq, one_liner_mcq, data_interpretation_mcq, reasoning_mcq, pedagogy_mcq,
  sequence_mcq, true_false (2 options allowed).
- Gate: LIMITED-clean / PARTIAL-with-substance / COMPREHENSIVE-with-evidence.
  A clean single-pass run (tier1=tier2=100% validated, recall at threshold,
  diff resolved, no density/downgrade/skew/dup flags, no limitations, and —
  new-engine banks — required cognitive forms present, no critical KU only
  weakly tested, required exam purposes present, high-priority confusion
  clusters addressed) is LIMITED: verification scope is a single blind pass.
  COMPREHENSIVE requires additionally verified `exhaustive_second_pass`
  evidence with every review stream completed; the FAST workflow never
  fabricates it. Any limitation → at most LIMITED.
  `gate.py` recomputes from the audit body; hand-edited status headers are
  ignored.
  Difficulty = reasoning demand (easy recall / medium relation-distinction / hard statement-elimination-integration).
- Fidelity: `SOURCE_BOUND` (default) | `ENHANCED` (external tagged+shown).
  There are no processing modes; the requested count is a parameter.
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
