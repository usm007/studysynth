<p align="center">
  <img src="assets/brand/banner.jpg" alt="StudySynth — Create. Study. Test. Excel. A Smart Learning &amp; Assessment Skill." width="100%">
</p>

# StudySynth — Local-First Study Application & Revision Engine

StudySynth converts complex reference and study documents into interactive, standalone HTML study modules, master study libraries, and print-ready A4 PDF test papers (for UPSC, APSC, State PSC, SSC, Banking, Railways, Teaching, and other competitive objective examinations).

Deterministic Python stdlib scripts (+ `pypdf`, `reportlab`, `openpyxl`) enforce mathematical coverage, structural validation, 11-dimension question quality, deduplication, audit gates, dynamic metadata extraction, and rendering without external cloud dependencies.

---

## 1. Supported Input Formats

The ingestion engine (`scripts/ingest.py`) parses, normalizes, and extracts structured blocks from:
- **PDF Documents** (`.pdf`): Multi-page extraction via `pypdf`, automatic running header/footer deduplication, table extraction, and empty page detection.
- **Word Documents** (`.docx`): Paragraphs, headings, and tables parsed directly from XML.
- **PowerPoint Slides** (`.pptx`): Slide text and tables parsed directly from XML.
- **Excel Spreadsheets** (`.xlsx`): Multi-sheet tabular data parsed via `openpyxl`.
- **Text & Markdown** (`.txt`, `.md`): Headings, markdown tables, lists, and paragraphs with whitespace/BOM normalization.
- **HTML Pages** (`.html`, `.htm`): Headings, paragraphs, and tables parsed via `html.parser`.
- *Scanned / Image-heavy files*: Gracefully flagged with `extraction_status: "unreliable"` and explicit limitation notes rather than fabricated text.

---

## 2. Key Architecture & Features

### Dynamic Metadata & Clean Naming Convention (`scripts/naming.py`)
- Automatically parses raw source filenames (e.g. `assam_geography_v2.pdf`) into clean, human-readable titles (e.g. `Assam Geography v2`).
- Dynamically injects clean titles into `<title>` tags and UI header branding (`#apptitle`).
- Generates clean, URL-friendly output file slugs (e.g. `assam-geography-module.html`).

### Master Dashboard (`index.html` Library) (`scripts/dashboard.py`)
- Automatically generates and updates a master `index.html` library dashboard in the root output folder.
- Responsive CSS grid layout featuring search filtering, module count, metadata badges, and direct launch links.

### Desktop Shortcut Automation (`scripts/desktop_shortcut.py`)
- Cross-platform utility that generates OS-level shortcuts pointing to `index.html`:
  - **Windows**: `.lnk` shell shortcut (with `.url` fallback)
  - **macOS**: `.webloc` bookmark
  - **Linux**: `.desktop` desktop entry

### Interactive Study Desk UI
- Pure standalone offline HTML file (`file://` compatible).
- Features **Practice Deck**, **Test**, **Revision Engine**, and **Analytics** modes.
- Purged of generic "Quiz" terminology in favor of pedagogical study module workflows.

---

## 3. Pipeline Sequence

The pipeline transforms source documents into verified study packages through sequential checkpoints. It is ONE workflow (no QUICK/BALANCED/COMPREHENSIVE processing modes): planning, reconciliation and batching are deterministic code; model calls are one extraction pass per chunk, batched generation (~12 questions/call), and the single blind review stream (6–12 redacted items/call) plus at most one targeted repair round. An exam profile is optional style input only.

```
DOCUMENT
  ↓ [ingest.py + naming.py + anchors.py]
DOCUMENT STRUCTURE, ANCHORS & CLEAN METADATA (Dates, numbers, articles, entities, tables)
  ↓ [plan.py: deterministic section-aware chunking]
EXTRACTION CHUNKS (chunks.json)
  ↓ [extract.md — ONE pass per chunk: extract + classify + tier + question hints]
KNOWLEDGE INVENTORY (KUs, Tiers 1-4, confusion clusters, verbatim excerpts)
  ↓ [locate_excerpts.py + plan.py merge/reconcile]
RECONCILED INVENTORY + BLUEPRINT (coverage_plan.json, per-KU cap, section share cap, count policy)
  ↓ [generation_batches.json: ~12 rows/call with evidence packs]
  ↓ [generate.md]
QUESTION BANK (batch_<n>.json → question_bank.json, explicit exam purposes, confusion-typed distractors)
  ↓ [validate_questions.py]
DETERMINISTIC VALIDATION (Single key, key consistency, option count, source provenance)
  ↓ [quality.py]
QUESTION QUALITY EVALUATION (11 dimensions: accuracy, distractors, leaks, difficulty fit, purpose fit, rubric A-D)
  ↓ [review-batch.md → review-blind-batch.md: redacted keyless re-solve + code comparison]
BLIND REVIEW (single independent stream; mismatches/flags → repair.json)
  ↓ [repair.md — ONE bounded round, re-validated + re-reviewed]
REPAIR OUTCOMES (fixed items re-credited; retired items stay excluded)
  ↓ [coverage.py + dedupe.py]
COVERAGE & REDUNDANCY AUDIT (Tier 1/2 content coverage, cognitive coverage, semantic dedupe)
  ↓ [audit.py + gate.py]
AUDIT & FINAL GATE (honest LIMITED / PARTIAL / evidence-backed COMPREHENSIVE)
  ↓ [package.py]
PACKAGE ASSEMBLY (Validated + Quality-Accepted questions only)
  ↓ [build_web.py + dashboard.py + desktop_shortcut.py + build_pdf.py]
STANDALONE STUDY MODULE, MASTER DASHBOARD, DESKTOP SHORTCUT & PRINT-READY PDFS
```

---

## 4. Quickstart: One-Command Pipeline

Run all deterministic stages at once from a source document, inventory, and question bank:

```bash
# Full pipeline from source document to interactive web app & verified PDFs
# (--profile is optional style input; omit it for generalized authoring)
python scripts/pipeline.py \
  --source examples/sample_source.md \
  --inventory examples/sample_inventory.json \
  --bank examples/sample_bank.json \
  --config config.default.json \
  --run-id my_run \
  --build-dir build \
  --full
```

Generated outputs in `build/my_run/`:
- `document_structure.json` & `anchors.json`: Document structure and extracted anchors
- `inventory_check.json`: Anchor recall and section density audit
- `validation_results.json`: Syntactic and semantic validation results
- `quality_report.json`: 11-dimension quality analysis and A/B/C/D rubric grading
- `coverage_matrix.json`: Content coverage and cognitive coverage breakdown
- `dedupe_report.json`: Exact and semantic duplicate detection report
- `audit_report.json`: Global audit of content, cognitive coverage, shares, and clusters
- `gate.json`: Authoritative gate status (`LIMITED` for a clean single-pass
  run, `PARTIAL` when substance fails, `COMPREHENSIVE` only with verified
  exhaustive-sweep evidence)
- `run_metrics.json`: truthful stage/work/time/call metrics
  (`llm_trace.jsonl` records the observable model calls)
- `quiz_package.json`: Packaged delivery artifact with quality-accepted questions
- `sample-source-module.html` & `quiz.html`: Standalone offline study workspace
- `output/index.html`: Master StudySynth library dashboard
- `pdf/question-paper-A.pdf`: Printable A4 question paper with OMR grid
- `pdf/answer-key-B.pdf`: Compact answer key sheet
- `pdf/explanations-C.pdf`: Pedagogical explanation booklet with source citations
- `pdf_check_report.json`: PDF layout, font embedding, and glyph clip verification

---

## 5. Verification

See `SKILL.md` → “Verify the artifact (dry run)” for the supported end-to-end check. It runs the bundled starter bank through packaging, HTML, and PDF generation and reports the gate result.

---

## 6. Known Boundaries & Limitations

- **Source-Bound Elimination Limits**: When a source document does not provide enough cross-cutting contextual information for all 4 options within a single block, questions cannot arbitrarily introduce external facts to fabricate elimination steps. In such cases, questions are legitimately classified as `distinction` or `association` rather than forced `elimination`.
- **Scanned Document Extraction**: OCR requires an external OCR engine (like Tesseract). Scanned or pure image PDFs produce `extraction_status: unreliable` and `STATUS: LIMITED` rather than guessing ungrounded text.
- **Font Availability for Non-Latin PDF Printing**: Devanagari and Bengali/Assamese PDF rendering defaults to `Nirmala.ttc` on Windows, falling back to `DejaVuSans` or `Helvetica`.
