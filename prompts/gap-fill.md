# gap-fill — targeted cognitive regeneration (event-driven, batched)

Role: gap filler. Target the EXACT weakness, not just the KU.

Inputs: ONE compact deterministic gap manifest per round:
`{"uncovered_t12": [...], "missing_cognitive": {ku: [forms]},
"missing_purposes": [...], "unaddressed_clusters": [...],
"failed_questions": [{"id": "...", "reasons": [...]}],
"accepted_coverage": {...}}` + uncovered KUs + source excerpts. The manifest is
built by scripts/audit.py + scripts/coverage.py — never restate it via a
full-bank LLM audit.

Steps:
1. Prioritize ALL important gaps together (Tier 1/2 uncovered first, then
   missing cognitive forms, missing mandatory purposes, unaddressed confusion
   clusters, failed-question repairs), subject to context limits and question
   dependencies. Example: if KU-17 recall=covered but distinction=uncovered,
   generate a DISTINCTION question (purpose=distinction|confusable_fact), NOT
   another recall item.
2. Generate ALL independent gap-fill candidates in BATCHES (see generate.md
   batch contract), not one question per call. If two gaps admit a legitimate
   INTEGRATED question, permit it only when the source establishes the
   relationship — never force integration.
3. If the problem is a confusion cluster, create a question that directly
   discriminates between the confusable concepts (paired options, statement
   set, or association reversal using ku_refs from the cluster).
4. Re-run generate -> batched review per new item (validate-blind +
   validate-semantic via review-batch.md); deterministic stmt_check holds.

After each round (orchestrator, deterministic):
1. Append only new, uniquely identified candidates.
2. Validate + review ONLY new/changed questions through the LLM layer;
   unchanged accepted questions are never regenerated or re-reviewed.
3. Recompute deterministic validation, quality, dedupe, coverage as required.
4. Recompute audit + authoritative gate (scripts/audit.py, scripts/gate.py).
5. STOP immediately if COMPREHENSIVE passes.
6. If no meaningful progress, stop wasting model calls; report honest
   PARTIAL/LIMITED with unresolved gaps.
7. Otherwise continue, up to max_gapfill_rounds=5 (config; never reduced).

Output JSON shape: `{"new_questions": [Question], "rounds_used": n,
"targeted_gaps": [{"ku_id": "...", "missing_forms": [...], "purpose": "..."}]}`.

Rules: R3 (loop until gate or max rounds), R2 (flagged KUs/forms only). No
early-stop may override a failed mandatory coverage condition or relabel an
incomplete package COMPREHENSIVE.
