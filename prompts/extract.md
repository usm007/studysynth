# extract — source-bound KU extraction (batched)

Role: extractor. Emit only facts present in the given blocks.

Inputs: `blocks[]` (each `{block_id, page, section_path, text, table_ref}`) + profile name.
A single request processes MULTIPLE source blocks (one chunk, ~4000-6000 input
tokens, configurable via `batching.extraction_chunk_tokens`). Chunks are built
by deterministic section-aware chunking: keep tables intact wherever possible;
split exceptionally large tables at row boundaries while preserving headers and
source references. Never split a logical section merely to hit a block count.
Each chunk carries a deterministic `chunk_id`; original `block_id`s are preserved.

Steps:
1. Split every block into atomic facts; one KU per fact.
2. Copy a verbatim `supporting_excerpt` (<=500 chars) per KU.
3. Fill `source{page,section_path,block_id,char_start,char_end,table_ref}` exactly
   against the ORIGINAL block (offsets within that block's text).
4. Set `origin=source`; never invent. If OCR garbage: record the limitation,
   set aside, do not guess.
5. State explicit uncertainty / extraction limitations per chunk.

Output JSON shape: `{"chunk_id": "...", "kus": [KnowledgeUnit], "limitations": [...]}`.

Rules: R4 (source-bound verbatim excerpts), R1 (inventory before questions), R3 (unreliable regions block COMPREHENSIVE).

Execution: process independent chunks concurrently (bounded concurrency 3,
configurable; respect provider limits). Merge chunks in deterministic chunk
order; deduplicate overlap artifacts ONLY by stable source identity
(block_id + normalized excerpt) — never fuzzy-merge distinct facts.
