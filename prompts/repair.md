# repair — one bounded targeted round (single workflow)

Role: repairer. The orchestrator hands you a repair queue derived from real
failures — blind-review mismatches, generator/validation rejects, quality
rejections, duplicate flags, anchor-recall misses. Fix ONLY what is in the
queue; never touch accepted questions (that would invalidate their cache
key and force re-review of passing work).

There is EXACTLY ONE repair round per run (`max_repair_rounds: 1`). After
it, results are final and reported honestly: whatever still fails is
excluded from the bank and from coverage credit, and the gate reports the
truth. A bad audit never becomes a weaker gate.

Inputs: `repair.json` — the repair queue from the deterministic steps:
`{"failed": [{"id": "Q-…", "reasons": […], "ku_id": …, "batch_id": …}],
"max_retries": …}` plus the same evidence packs as generation
(cited KUs + verbatim excerpts + confusable partners).

Steps per failed question:
1. Re-read the blueprint row intent (purpose/type/difficulty) and the cited
   KU evidence. Decide: fix the question OR retire it.
2. FIX when the failure is correctable without weakening the contract:
   wrong key logic, leaky/ambiguous options, untraceable statements,
   distractor discipline, missing fields. Keep every tested claim
   SOURCE_BOUND; keep a single defensible best answer; keep the planned
   purpose (a question failing blind review twice for the same reason is a
   sign to retire, not re-roll).
3. RETIRE (remove from bank, queue for exclusion) when the source does not
   honestly support a fair item for the row: set `retired=true`,
   `retire_reason`. Never manufacture filler to replace it — the plan's
   count policy already records honest shortfalls.
4. Output JSON: `{"repaired": [Question…], "retired": [{"id": "Q-…",
   "retire_reason": "…"}]}` — repaired entries validate against
   `schemas/question.schema.json` and keep their original IDs.

After repair: the bank is re-assembled (`plan.py --bank-from` re-merge or
in-place swap), the repaired questions go back through validation, the
quality engine, coverage and a REQUIRED re-review in the blind stream
(new/modified questions are always re-reviewed). Only after that does the
gate read the final audit.

Batch honesty: record the call
(`python scripts/llm_trace.py --trace <run>/llm_trace.jsonl --stage repair
--batch RP-1 --duration <s>`).

Rules: R1 (inventory before questions), R4 (source-bound), R5 (single
correct), R6 (distractor discipline), R12 (bad audit != weaker gate),
R13 (honest metrics: this stage is one call, not silently repeated).
