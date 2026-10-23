# extract — one-pass chunk extraction (single call per chunk)

Role: extractor + classifier + planner. ONE request per chunk does the
extraction, classification and planning-hint work together; there is no second
classification pass, no separate inventory pass and no exam-design pass.

Inputs: `chunks[]` (from `chunks.json`; each `{chunk_id, block_ids[]}` resolved
against `document_structure.json`: `{block_id, page, section_path, text,
table_ref}`). A single request processes one chunk, ~4000-6000 input tokens
(configurable via `batching.extraction_chunk_tokens`). Chunks are built by
deterministic section-aware chunking: keep tables intact wherever possible;
split exceptionally large tables at row boundaries while preserving headers and
source references. Never split a logical section merely to hit a block count.
No exam profile is required; without one, use a generalized competitive-exam
relevance policy.

Steps (all in the same call):
1. Split every block into atomic facts; one KU per fact.
2. Classify each KU in place: `type`, `topic/subtopic`, `content_kind`,
   `cognitive_level`, `archetype_hints`, `has_passage`,
   `pedagogical_relevance`, `classroom_application_potential`.
3. Score dimensions honestly: `exam_relevance`, `importance`,
   `discrimination_value`, `confusion_value`, `statement_potential`,
   `elimination_value`, `conceptual_value`; then set `tier` (1=must-test …
   4=exclude) and keep the honest `tier_history` for audit.
4. Record relationships: `related_ku`, `prerequisite_units`,
   `confusable_with`, `confusion_cluster` (name clusters explicitly when two
   or more KUs are commonly confused).
5. Add per-KU `question_hints` (optional, evidence-based): an array of
   `{purpose, type, difficulty, primary_skill, note}` describing the
   competitive-exam forms this fact legitimately supports (distinction,
   statement_evaluation, elimination, chronology, direct_recall…). Hints are
   planning input; the deterministic planner caps and drops them by quality,
   never manufactures quota from them. Do not add hints you cannot justify
   from the source.
6. Copy a verbatim `supporting_excerpt` (<=500 chars) per KU.
7. Fill `source{page,section_path,block_id,char_start,char_end,table_ref}`
   exactly against the ORIGINAL block (offsets within that block's text).
8. Set `origin=source`; never invent. If OCR garbage: record the limitation,
   set aside, do not guess.

Output JSON shape per chunk:
`{"chunk_id": "...", "kus": [KnowledgeUnit…], "limitations": ["…"]}` —
KnowledgeUnit validates against `schemas/knowledge-unit.schema.json`.
State explicit uncertainty / extraction limitations in `limitations`.

Execution: process independent chunks concurrently (bounded concurrency 3,
configurable; respect provider limits). Save each chunk result as
`chunk_<n>.json` in the run directory (`chunk_1.json`, `chunk_2.json`, …,
1-based chunk order). Merge/dedupe/ordering happens deterministically in
`scripts/plan.py` — identity dedupe only (block_id + normalized excerpt);
never fuzzy-merge distinct facts.

Rules: R4 (source-bound verbatim excerpts), R1 (inventory before questions),
R10 (examinable over mechanical), R13 honest limitations.
