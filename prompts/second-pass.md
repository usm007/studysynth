# second-pass — recall sweep for missed facts (batched, independent)

Role: recall checker. Find facts the first pass missed. Do NOT trust pass 1;
re-read the source blocks independently.

Inputs: batched `chunks[]` (source `blocks[]` per chunk) + the corresponding
first-pass `kus[]` for those blocks.

Steps:
1. Independently re-scan tables (every cell + relationships), lists, captions,
   footnotes, structured data.
2. Hunt dates, numbers, percentages, names, places, article/provision refs.
3. Add material NOT represented by the first-pass inventory — including
   important relationships, exceptions and distinctions.
4. Add missing KUs only (same schema, new KU-#### ids). Never duplicate
   existing ids; mark weak-OCR blocks for LIMITED status.

Output JSON shape: `{"chunk_id": "...", "added_kus": [KnowledgeUnit], "weak_blocks": [block_id]}`.

Rules: R1, R4, R3 (unresolved diffs block COMPREHENSIVE).

Execution: run the audit concurrently across chunks (bounded concurrency 3).
Merge newly discovered units in deterministic chunk order; deduplicate only
verified overlap (same block_id + verbatim excerpt). Reconcile ALL additions
with the inventory and deterministic anchor/density checks before blueprinting.
A faster extraction that misses source knowledge is a failed optimization.
