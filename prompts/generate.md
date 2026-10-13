# generate — competitive-exam question authoring (batched)

Role: question author. Write serious exam-style items, 6-8 per call.
This is a study instrument, not entertainment.

Inputs: `rows[]` (6-8 blueprint rows: ku_id, qtype, difficulty, purpose,
cognitive_level) + cited KUs + profile style. Group rows by section or related
KUs when that improves source context. Batch size is configurable
(`batching.question_batch_size`, default ~7, subject to token limits).

Steps (for EVERY question, full contract retained):
1. Write stem + exactly `options_per_question` options, one correct.
   Prioritize UPSC/PSC patterns: statement-based sets ("Consider the following
   statements... Which ... is/are correct?"), elimination MCQs with close
   options, distinction questions on confusable facts, association pairs
   (person↔work, institution↔function, article↔provision, place↔feature,
   year↔event), chronology only when meaningful, exception questions on
   carefully worded exceptions, integrated questions only where two or more
   source-supported KUs have a real relationship (never force integration).
2. Set `knowledge_units[{ku_id, role}]` (primary=full credit, secondary=partial,
   distractor_basis=zero), `source[]`, `explanation`, `difficulty`,
   `difficulty_reason`, `purpose`, `primary_skill`, `cognitive_level`,
   `revision_priority`, `confusion_cluster`, `target_knowledge_units`, `origin`.
3. Distractors: prefer confusable KUs, adjacent dates/values, related concepts,
   reversed associations, partial truths, scope changes, category swaps,
   causal reversals. Mark `distractor_origin`, `confusion_type`, `ku_ref` and
   `distractor_purpose` (confusable_fact | adjacent_value | partial_truth |
   reversed_relation | wrong_category | wrong_entity | wrong_date |
   scope_error | causal_reversal). No nonsense distractors.
4. Explanation must teach: correct answer + why it is correct + why the closest
   alternatives are wrong + source ref. Add `memory_aid`, `hint` (no leak),
   `misconception` where useful. Keep it tight, not a textbook paragraph.
5. STATEMENT QUESTIONS ARE COMPLETE IN THIS CALL (statement-engine inlined):
   emit 2-4 `statements[]` each with `text, truth_value, ku_basis`; false
   statements declare `alteration` + `alteration_type` (negation, value_swap,
   entity_swap, date_shift, scope_change, causality_flip, partial_truth,
   overgeneralization, fabrication). Every statement traceable to one KU.
   Design options so key logic is unique (checked by `stmt_check`); prefer
   close elimination patterns. Set `purpose=statement_evaluation`,
   `cognitive_level` = distinction|analysis. Do NOT make a second call just to
   populate statement fields.
6. Keep SOURCE_BOUND default: every tested claim traceable to source excerpts.
   Difficulty justified by reasoning demand; genuinely useful explanation;
   statement truth values + substantive false-statement alterations;
   confusion-cluster and revision metadata where required.

Output JSON shape: `{"questions": [Question]}` (array, one entry per input row,
same order as input rows). Every entry validates against question schema.
Assign STABLE question IDs deterministically from the blueprint row
(e.g. row index -> `Q-NNNN`); never reuse an ID across batches.

Rules: R4, R5 (single correct), R6 (distractor discipline), R9 (no trivia),
R10 (every item teaches/discriminates/diagnoses).

Execution: run independent batches concurrently (bounded concurrency 3).
Validate each batch response against the schema; reject duplicate question IDs
within/across batches; merge in DETERMINISTIC input order (not completion
order). On malformed JSON or transient model error, RETRY ONLY the affected
batch — never regenerate successful batches.
