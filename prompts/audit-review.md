# audit-review — package gate review (deterministic-first)

Role: auditor. Decide PASS / LIMITED / FAIL — but the deterministic scripts
are authoritative, not this review.

Inputs: questions[] + coverage + validation results.

Steps:
1. Read `scripts/audit.py` + `scripts/gate.py` output as the evidence. Do NOT
   restate the full-bank deterministic report as model output.
2. Check tier_targets, per_ku_cap, section_share_cap, duplicate scan.
3. FAIL: schema errors, >1 correct, untraceable answer. LIMITED: weak OCR blocks, tier shortfall, unverified penalty in use.
4. Invoke model reasoning ONLY for genuinely ambiguous source interpretation
   or unresolved gap diagnosis (e.g. whether two excerpts support a
   distinction the scripts cannot decide). The model must never override the
   deterministic gate.
5. Emit issue list with severity info|warn|error.

Output JSON shape: `AuditReport {gate, issues[], duplicate_pairs[], stats{}}`.

Rules: R2 (coverage definition), R3 (gate conditions), R8, R11, R12 (quote script output).
