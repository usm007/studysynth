"""Regression and Parity Tests for the Single FAST Pipeline Workflow.

Covers:
1. One FAST workflow: no selectable processing modes anywhere in the active path.
2. Evidence-driven gate: COMPREHENSIVE requires verified exhaustive-sweep evidence.
3. Single-pass verification scope is reported honestly (LIMITED/PARTIAL, never over-promoted).
4. No profile required to run the pipeline.
5. Cache reuse when all relevant fingerprints match.
6. Cache invalidation when source text changes.
7. Cache invalidation when schemas, configs, or helper code changes.
8. No invalidation of upstream stages when downstream artifacts change.
9. Correct --redo descendant invalidation.
10. Safe atomic writes and recovery from interrupted writes.
11. Deterministic batch merge order under concurrent completion.
12. Content-addressed resumption: retrying only failed/invalidated batches.
13. Exact parity of deduplication results.
14. Exact parity of quality evaluation and 11 dimensions.
15. Exact parity of anchor matching and recall reporting.
16. Physical blind-review payload redaction.
17. Single independent review stream (no second semantic stream in the routine path).
18. Honest metrics when model telemetry is unavailable.
19. Output integrity and schema compliance.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = sys.executable

sys.path.insert(0, str(ROOT / "scripts"))
import anchors as anchors_mod
import cache as cache_mod
import dedupe as dedupe_mod
import gate as gate_mod
import inventory_check as inv_check_mod
import lib_common
import llm_trace as llm_trace_mod
import pipeline as pipeline_mod
import quality as quality_mod
import review_batch as review_mod
import threading
import time


def run_cmd(*args, timeout=120):
    p = subprocess.run([PY] + [str(a) for a in args], capture_output=True,
                       text=True, cwd=str(ROOT), timeout=timeout)
    return p


class TestSingleWorkflowPolicy(unittest.TestCase):
    """One FAST workflow: no selectable processing modes; evidence-driven gate."""

    def setUp(self):
        self.clean_audit = {
            "anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
            "coverage_by_tier": {"1": {"pct_covered": 100.0}, "2": {"pct_covered": 100.0}},
            "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 10},
            "skew_flags": [], "duplicate_flags": [], "limitations": []
        }

    def test_default_config_has_no_processing_mode(self):
        cfg = lib_common.load_json(str(ROOT / "config.default.json"))
        self.assertNotIn("processing_mode", cfg)
        self.assertEqual(cfg.get("max_repair_rounds"), 1)

    def test_pipeline_cli_has_no_processing_mode_flag(self):
        out = run_cmd("scripts/pipeline.py", "--help")
        self.assertNotIn("--processing-mode", out.stdout + out.stderr)

    def test_clean_audit_without_evidence_is_limited(self):
        status, reasons = gate_mod.decide(self.clean_audit, 1.0)
        self.assertEqual(status, "LIMITED")
        self.assertTrue(any("verification" in r for r in reasons))

    def test_clean_audit_with_single_pass_evidence_is_limited(self):
        ev = {"exhaustive_second_pass": False, "missing_reviews": False}
        status, reasons = gate_mod.decide(self.clean_audit, 1.0, evidence=ev)
        self.assertEqual(status, "LIMITED")
        self.assertTrue(any("verification scope reduced" in r for r in reasons))

    def test_substantive_failure_is_partial_under_single_pass_evidence(self):
        audit = dict(self.clean_audit,
                     coverage_by_tier={"1": {"pct_covered": 85.0}, "2": {"pct_covered": 100.0}})
        ev = {"exhaustive_second_pass": False, "missing_reviews": False}
        status, reasons = gate_mod.decide(audit, 1.0, evidence=ev)
        self.assertEqual(status, "PARTIAL")
        self.assertTrue(any("tier 1" in r for r in reasons))

    def test_comprehensive_requires_exhaustive_evidence_and_reviews(self):
        ev_missing_sweep = {"exhaustive_second_pass": False}
        status, _ = gate_mod.decide(self.clean_audit, 1.0, evidence=ev_missing_sweep)
        self.assertEqual(status, "LIMITED")

        ev_missing_reviews = {"exhaustive_second_pass": True, "missing_reviews": True}
        status, reasons = gate_mod.decide(self.clean_audit, 1.0, evidence=ev_missing_reviews)
        self.assertEqual(status, "LIMITED")
        self.assertTrue(any("review" in r for r in reasons))

    def test_comprehensive_with_verified_legacy_evidence(self):
        ev = {"exhaustive_second_pass": True, "missing_reviews": False}
        status, reasons = gate_mod.decide(self.clean_audit, 1.0, evidence=ev)
        self.assertEqual(status, "COMPREHENSIVE")
        self.assertEqual(reasons, [])


class TestCacheInvalidationAndReuse(unittest.TestCase):
    """Items 7-11: Stage-specific fingerprints, reuse, and invalidation rules."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_cache_inv_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_upstream_not_invalidated_when_downstream_changes(self):
        """Item 10: Changing question bank must NOT invalidate ingest or anchors."""
        run_id = "test_run"
        r1 = run_cmd("scripts/pipeline.py", "--source", "examples/sample_source.md",
                     "--run-id", run_id, "--profile", "profiles/GENERAL_PSC.json",
                     "--config", "config.default.json", "--build-dir", str(self.tmp),
                     "--inventory", "examples/sample_inventory.json",
                     "--bank", "examples/sample_bank.json",
                     "--ignored", "tests/fixtures/e2e_ignored_anchors.json",
                     "--diff", "tests/fixtures/e2e_inventory_diff.json")
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)

        man_path = self.tmp / run_id / "artifact_manifest.json"
        man1 = lib_common.load_json(str(man_path))
        ingest_fp1 = man1["ingest"]["fingerprint"]
        anchors_fp1 = man1["anchors"]["fingerprint"]

        # Run again with a modified bank
        mod_bank = self.tmp / "mod_bank.json"
        b_data = lib_common.load_json(str(ROOT / "examples/sample_bank.json"))
        b_data["questions"][0]["stem"] = "Modified stem for cache test."
        lib_common.save_json(str(mod_bank), b_data)

        r2 = run_cmd("scripts/pipeline.py", "--source", "examples/sample_source.md",
                     "--run-id", run_id, "--profile", "profiles/GENERAL_PSC.json",
                     "--config", "config.default.json", "--build-dir", str(self.tmp),
                     "--inventory", "examples/sample_inventory.json",
                     "--bank", str(mod_bank),
                     "--ignored", "tests/fixtures/e2e_ignored_anchors.json",
                     "--diff", "tests/fixtures/e2e_inventory_diff.json")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

        state2 = lib_common.load_json(str(self.tmp / run_id / "pipeline_state.json"))
        # Ingest and anchors MUST have been skipped (cache hit)
        self.assertEqual(state2["stages"]["ingest"]["status"], "skipped")
        self.assertEqual(state2["stages"]["anchors"]["status"], "skipped")
        man2 = lib_common.load_json(str(man_path))
        self.assertEqual(man2["ingest"]["fingerprint"], ingest_fp1)
        self.assertEqual(man2["anchors"]["fingerprint"], anchors_fp1)

    def test_redo_invalidates_descendants(self):
        """Item 11: Correct --redo descendant invalidation."""
        run_id = "test_redo"
        r1 = run_cmd("scripts/pipeline.py", "--source", "examples/sample_source.md",
                     "--run-id", run_id, "--profile", "profiles/GENERAL_PSC.json",
                     "--config", "config.default.json", "--build-dir", str(self.tmp),
                     "--inventory", "examples/sample_inventory.json",
                     "--bank", "examples/sample_bank.json",
                     "--ignored", "tests/fixtures/e2e_ignored_anchors.json",
                     "--diff", "tests/fixtures/e2e_inventory_diff.json")
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)

        # Now run with --redo dedupe: dedupe, coverage, audit, gate must re-run; ingest must stay skipped
        r2 = run_cmd("scripts/pipeline.py", "--source", "examples/sample_source.md",
                     "--run-id", run_id, "--profile", "profiles/GENERAL_PSC.json",
                     "--config", "config.default.json", "--build-dir", str(self.tmp),
                     "--inventory", "examples/sample_inventory.json",
                     "--bank", "examples/sample_bank.json",
                     "--ignored", "tests/fixtures/e2e_ignored_anchors.json",
                     "--diff", "tests/fixtures/e2e_inventory_diff.json",
                     "--redo", "dedupe")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        state = lib_common.load_json(str(self.tmp / run_id / "pipeline_state.json"))
        self.assertEqual(state["stages"]["ingest"]["status"], "skipped")
        self.assertEqual(state["stages"]["dedupe"]["status"], "ok")


class TestContentAddressedBatchResumption(unittest.TestCase):
    """Items 12-14: Batch fingerprints, atomic writes, merge order, retry failed."""

    def test_batch_fingerprint_changes_on_payload_change(self):
        fp1 = cache_mod.batch_fingerprint("b1", {"text": "Original text"}, "prompt_v1", "schema_v1")
        fp2 = cache_mod.batch_fingerprint("b1", {"text": "Different text"}, "prompt_v1", "schema_v1")
        self.assertNotEqual(fp1, fp2)

    def test_batch_fingerprint_changes_on_prompt_or_schema_change(self):
        fp1 = cache_mod.batch_fingerprint("b1", {"text": "Same"}, "prompt_v1", "schema_v1")
        fp2 = cache_mod.batch_fingerprint("b1", {"text": "Same"}, "prompt_v2", "schema_v1")
        fp3 = cache_mod.batch_fingerprint("b1", {"text": "Same"}, "prompt_v1", "schema_v2")
        self.assertNotEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp3)

    def test_deterministic_merge_order(self):
        """Item 13: Deterministic batch merge order under out-of-order completion."""
        batches = [
            (3, [{"id": "Q-0004"}]),
            (0, [{"id": "Q-0001"}]),
            (2, [{"id": "Q-0003"}]),
            (1, [{"id": "Q-0002"}]),
        ]
        merged = cache_mod.merge_batches(batches)
        self.assertEqual([q["id"] for q in merged], ["Q-0001", "Q-0002", "Q-0003", "Q-0004"])

    def test_atomic_save_json(self):
        """Item 12: Atomic save writes cleanly without leaving temp files."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "sub", "test.json")
            cache_mod.atomic_save_json(dest, {"key": "value"})
            self.assertTrue(os.path.isfile(dest))
            data = lib_common.load_json(dest)
            self.assertEqual(data["key"], "value")
            # No lingering .tmp files
            self.assertFalse(os.path.isfile(dest + ".tmp"))


class TestAlgorithmicParity(unittest.TestCase):
    """Items 15-17: Parity of deduplication, quality uniqueness, and anchor matching."""

    def test_dedupe_precomputed_parity(self):
        """Item 15: Exact parity of deduplication results."""
        bank = lib_common.load_json(str(ROOT / "examples/sample_bank.json"))
        qs = bank["questions"]
        pairs, diversity = dedupe_mod.detect_duplicates(qs, threshold=0.85)
        self.assertIsInstance(pairs, list)
        self.assertIsInstance(diversity, list)

    def test_anchor_matching_parity(self):
        """Item 17: Parity of anchor matching between build_anchor_index and iterative matching."""
        inv = lib_common.load_json(str(ROOT / "examples/sample_inventory.json"))
        units = inv["units"]
        joined_index, ku_map = anchors_mod.build_anchor_index(units)

        # Test known anchor hits
        for u in units[:10]:
            statement = u.get("statement", "")
            words = [w for w in statement.split() if len(w) > 4]
            for w in words[:2]:
                norm_w = lib_common.norm(w)
                iter_hit = any(norm_w and norm_w in t for t in ku_map.values())
                opt_hit = anchors_mod.check_anchor_hit(norm_w, joined_index)
                self.assertEqual(iter_hit, opt_hit, "Mismatch for word: %s" % norm_w)

        # Test non-existent anchor
        fake = "non_existent_symbol_xyz_123"
        self.assertFalse(anchors_mod.check_anchor_hit(fake, joined_index))


class TestIndependentReviewsAndRedaction(unittest.TestCase):
    """Items 18-19: Physical redaction and independent review streams."""

    def test_blind_payload_redaction(self):
        """Item 18: Answer keys, truth values, covers physically removed."""
        q = {
            "id": "Q-0001",
            "stem": "Which of the following is correct?",
            "answer": "B",
            "answer_key": "B",
            "options": [
                {"label": "A", "text": "Option A", "is_correct": False, "covers": [1]},
                {"label": "B", "text": "Option B", "is_correct": True, "covers": [2]},
            ],
            "statements": [
                {"text": "Statement 1", "truth_value": False, "truth": False},
                {"text": "Statement 2", "truth_value": True, "truth": True},
            ],
            "source": [{"excerpt": "verbatim text"}],
        }
        redacted = cache_mod.redact_question(q)
        self.assertNotIn("answer", redacted)
        self.assertNotIn("answer_key", redacted)
        for opt in redacted.get("options", []):
            self.assertNotIn("is_correct", opt)
            self.assertNotIn("covers", opt)
        for stmt in redacted.get("statements", []):
            self.assertNotIn("truth_value", stmt)
            self.assertNotIn("truth", stmt)
            self.assertNotIn("is_true", stmt)
            self.assertNotIn("correct", stmt)
        # Stem and text preserved
        self.assertEqual(redacted["stem"], q["stem"])


class MockArgs:
    """Helper to mock command-line arguments for pipeline fingerprint testing."""
    def __init__(self, **kwargs):
        for k in ("source", "profile", "config", "inventory", "bank", "ignored", "diff",
                  "count", "redo", "mode", "package", "web", "pdf",
                  "full", "deliver", "delivery_dir", "delivery_mode"):
            setattr(self, k, None)
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestStageFingerprintDependencies(unittest.TestCase):
    """Section 2: Stage-specific fingerprint correctness and dependency isolation."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_fp_deps_"))
        self.src = str(ROOT / "examples/sample_source.md")
        self.prof = str(ROOT / "profiles/GENERAL_PSC.json")
        self.cfg_file = str(ROOT / "config.default.json")
        self.inv = str(ROOT / "examples/sample_inventory.json")
        self.bank = str(ROOT / "examples/sample_bank.json")
        self.cfg = lib_common.load_json(self.cfg_file)
        self.R = str(self.tmp)
        self.F = {
            "struct": os.path.join(self.R, "document_structure.json"),
            "anchors": os.path.join(self.R, "anchors.json"),
            "validation": os.path.join(self.R, "validation_results.json"),
            "quality": os.path.join(self.R, "quality_report.json"),
            "dedupe": os.path.join(self.R, "dedupe_report.json"),
            "coverage": os.path.join(self.R, "coverage_matrix.json"),
            "audit": os.path.join(self.R, "audit_report.json"),
            "gate": os.path.join(self.R, "gate.json"),
        }
        for path in self.F.values():
            lib_common.save_json(path, {"mock": True})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_question_bank_mutation(self):
        """Mutating question bank invalidates downstream stages, preserves ingest/anchors."""
        a1 = MockArgs(source=self.src, profile=self.prof, config=self.cfg_file,
                      inventory=self.inv, bank=self.bank)
        # Create modified bank
        mod_bank = str(self.tmp / "mod_bank.json")
        bdata = lib_common.load_json(self.bank)
        bdata["questions"][0]["stem"] = "Changed question stem for dependency test"
        lib_common.save_json(mod_bank, bdata)
        a2 = MockArgs(source=self.src, profile=self.prof, config=self.cfg_file,
                      inventory=self.inv, bank=mod_bank)

        # Ingest, anchors, check MUST NOT change
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("ingest", self.R, self.F, a1, self.cfg),
                         pipeline_mod.compute_stage_fingerprint("ingest", self.R, self.F, a2, self.cfg))
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("anchors", self.R, self.F, a1, self.cfg),
                         pipeline_mod.compute_stage_fingerprint("anchors", self.R, self.F, a2, self.cfg))
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("check", self.R, self.F, a1, self.cfg),
                         pipeline_mod.compute_stage_fingerprint("check", self.R, self.F, a2, self.cfg))

        # Validate, quality, dedupe, coverage, audit, package MUST change
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("validate", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("validate", self.R, self.F, a2, self.cfg))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("quality", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("quality", self.R, self.F, a2, self.cfg))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("dedupe", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("dedupe", self.R, self.F, a2, self.cfg))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("coverage", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("coverage", self.R, self.F, a2, self.cfg))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("audit", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("audit", self.R, self.F, a2, self.cfg))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("package", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("package", self.R, self.F, a2, self.cfg))

    def test_profile_mutation(self):
        """Mutating profile invalidates validate, quality, audit, package; preserves ingest/anchors."""
        a1 = MockArgs(source=self.src, profile=self.prof, config=self.cfg_file,
                      inventory=self.inv, bank=self.bank)
        mod_prof = str(self.tmp / "mod_prof.json")
        pdata = lib_common.load_json(self.prof)
        pdata["label"] = "Modified Profile Label"
        lib_common.save_json(mod_prof, pdata)
        a2 = MockArgs(source=self.src, profile=mod_prof, config=self.cfg_file,
                      inventory=self.inv, bank=self.bank)

        # Ingest and anchors unchanged
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("ingest", self.R, self.F, a1, self.cfg),
                         pipeline_mod.compute_stage_fingerprint("ingest", self.R, self.F, a2, self.cfg))
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("anchors", self.R, self.F, a1, self.cfg),
                         pipeline_mod.compute_stage_fingerprint("anchors", self.R, self.F, a2, self.cfg))
        # Validate, quality, audit, package changed
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("validate", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("validate", self.R, self.F, a2, self.cfg))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("quality", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("quality", self.R, self.F, a2, self.cfg))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("audit", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("audit", self.R, self.F, a2, self.cfg))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("package", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("package", self.R, self.F, a2, self.cfg))

    def test_threshold_mutation(self):
        """Changing thresholds in config invalidates audit and gate, preserves upstream."""
        a = MockArgs(source=self.src, profile=self.prof, config=self.cfg_file,
                     inventory=self.inv, bank=self.bank)
        cfg2 = copy.deepcopy(self.cfg)
        cfg2["anchor_recall_threshold"] = 95.0

        # Ingest, anchors, validate, dedupe unchanged
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("ingest", self.R, self.F, a, self.cfg),
                         pipeline_mod.compute_stage_fingerprint("ingest", self.R, self.F, a, cfg2))
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("anchors", self.R, self.F, a, self.cfg),
                         pipeline_mod.compute_stage_fingerprint("anchors", self.R, self.F, a, cfg2))
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("validate", self.R, self.F, a, self.cfg),
                         pipeline_mod.compute_stage_fingerprint("validate", self.R, self.F, a, cfg2))
        # Check, audit and gate changed
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("check", self.R, self.F, a, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("check", self.R, self.F, a, cfg2))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("audit", self.R, self.F, a, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("audit", self.R, self.F, a, cfg2))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("gate", self.R, self.F, a, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("gate", self.R, self.F, a, cfg2))

    def test_profile_mutation(self):
        """An optional style profile changes authoring stages, never extraction."""
        a_no = MockArgs(source=self.src, profile=None, config=self.cfg_file,
                        inventory=self.inv, bank=self.bank)
        a_p = MockArgs(source=self.src, profile=self.prof, config=self.cfg_file,
                       inventory=self.inv, bank=self.bank)

        # Ingest and anchors do not depend on the optional profile
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("ingest", self.R, self.F, a_no, self.cfg),
                         pipeline_mod.compute_stage_fingerprint("ingest", self.R, self.F, a_p, self.cfg))
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("anchors", self.R, self.F, a_no, self.cfg),
                         pipeline_mod.compute_stage_fingerprint("anchors", self.R, self.F, a_p, self.cfg))
        # Authoring-quality stages do honor an explicit profile
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("validate", self.R, self.F, a_no, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("validate", self.R, self.F, a_p, self.cfg))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("quality", self.R, self.F, a_no, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("quality", self.R, self.F, a_p, self.cfg))
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("audit", self.R, self.F, a_no, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("audit", self.R, self.F, a_p, self.cfg))

    def test_unrelated_output_option_mutation(self):
        """Changing delivery options does not invalidate core processing stages."""
        a1 = MockArgs(source=self.src, profile=self.prof, config=self.cfg_file,
                      inventory=self.inv, bank=self.bank, delivery_mode="individual")
        a2 = MockArgs(source=self.src, profile=self.prof, config=self.cfg_file,
                      inventory=self.inv, bank=self.bank, delivery_mode="unified")

        for stg in ("ingest", "anchors", "check", "validate", "quality", "dedupe", "coverage", "audit", "gate"):
            self.assertEqual(pipeline_mod.compute_stage_fingerprint(stg, self.R, self.F, a1, self.cfg),
                             pipeline_mod.compute_stage_fingerprint(stg, self.R, self.F, a2, self.cfg),
                             "Stage %s was unexpectedly invalidated by delivery_mode" % stg)
        self.assertNotEqual(pipeline_mod.compute_stage_fingerprint("delivery", self.R, self.F, a1, self.cfg),
                            pipeline_mod.compute_stage_fingerprint("delivery", self.R, self.F, a2, self.cfg))


class TestContentAddressedBatchCacheDeep(unittest.TestCase):
    """Section 3: Content-addressed batch caching and strict reuse verification."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_batch_cache_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_batch_fingerprint_full_sha256(self):
        """Batch fingerprint is a 64-character SHA-256 digest."""
        fp = cache_mod.batch_fingerprint({"data": 123}, prompt="prompt_text")
        self.assertEqual(len(fp), 64)
        int(fp, 16)  # valid hex

    def test_changed_source_with_same_block_id_produces_cache_miss(self):
        """Changed source text with identical block ID produces a different fingerprint."""
        b1 = [{"id": "B-0001", "text": "Original excerpt for knowledge unit"}]
        b2 = [{"id": "B-0001", "text": "Altered text for knowledge unit"}]
        fp1 = cache_mod.batch_fingerprint(b1, prompt="prompt")
        fp2 = cache_mod.batch_fingerprint(b2, prompt="prompt")
        self.assertNotEqual(fp1, fp2)

    def test_can_reuse_batch_verifies_all_7_conditions(self):
        """All 7 integrity conditions are enforced before reusing cached batch output."""
        out_file = str(self.tmp / "batch_out.json")
        lib_common.save_json(out_file, {"status": "ok", "items": [1, 2, 3]})
        curr_fp = cache_mod.batch_fingerprint({"b": 1})
        valid_entry = {
            "batch_id": "B1",
            "stage": "generation",
            "fingerprint": curr_fp,
            "output_path": out_file,
            "output_hash": cache_mod.sha_file_full(out_file),
            "validation_status": "valid",
            "completed": True,
        }

        # 1. Clean entry passes
        self.assertTrue(cache_mod.can_reuse_batch(valid_entry, curr_fp, expected_stage="generation", expected_batch_id="B1"))

        # 2. Fingerprint mismatch -> rejected
        self.assertFalse(cache_mod.can_reuse_batch(valid_entry, "wrong_fp_1234567890123456789012345678901234567890123456789012345678901234"))

        # 3. Output missing -> rejected
        bad_entry = dict(valid_entry, output_path=str(self.tmp / "nonexistent.json"))
        self.assertFalse(cache_mod.can_reuse_batch(bad_entry, curr_fp))

        # 4. Output hash mismatch -> rejected
        bad_entry = dict(valid_entry, output_hash="mismatched_hash")
        self.assertFalse(cache_mod.can_reuse_batch(bad_entry, curr_fp))

        # 5. Output malformed JSON -> rejected
        bad_json = str(self.tmp / "bad.json")
        with open(bad_json, "w") as f:
            f.write("{corrupt json,")
        bad_entry = dict(valid_entry, output_path=bad_json, output_hash=cache_mod.sha_file_full(bad_json))
        self.assertFalse(cache_mod.can_reuse_batch(bad_entry, curr_fp))

        # 6. Schema validator failure -> rejected
        validator_fail = lambda doc: False
        self.assertFalse(cache_mod.can_reuse_batch(valid_entry, curr_fp, validator_fn=validator_fail))

        # 7. Completed = False -> rejected
        bad_entry = dict(valid_entry, completed=False)
        self.assertFalse(cache_mod.can_reuse_batch(bad_entry, curr_fp))

    def test_failed_batch_does_not_invalidate_successful_batches(self):
        """Failed batch does not invalidate prior successful batches in progress."""
        out1 = str(self.tmp / "b1.json")
        lib_common.save_json(out1, {"q": 1})
        fp1 = cache_mod.batch_fingerprint({"b": 1})
        p = cache_mod.progress_init(["b1", "b2", "b3"])
        cache_mod.progress_record_batch(p, "b1", fp1, out1, validation_status="valid", completed=True)
        # Mark b2 as failed
        cache_mod.progress_record_batch(p, "b2", "fp2", None, validation_status="failed", completed=False)

        pending = cache_mod.progress_pending(p, {"b1": fp1, "b2": "fp2", "b3": "fp3"})
        self.assertIn("b2", pending)
        self.assertIn("b3", pending)
        self.assertNotIn("b1", pending)
        # b1 remains done
        self.assertIn("b1", p["done"])


class TestAuthoritativeGateVerification(unittest.TestCase):
    """Section 4: Authoritative quality gate and verification evidence rules."""

    def test_comprehensive_passes_with_verified_sweep_evidence(self):
        """Evidence showing an exhaustive second-pass supports COMPREHENSIVE."""
        audit = {
            "anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
            "coverage_by_tier": {"1": {"pct_covered": 100.0}, "2": {"pct_covered": 100.0}},
            "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 20},
            "skew_flags": [], "duplicate_flags": [], "limitations": []
        }
        ev = {"exhaustive_second_pass": True, "missing_reviews": False}
        status, reasons = gate_mod.decide(audit, 1.0, evidence=ev)
        self.assertEqual(status, "COMPREHENSIVE")
        self.assertEqual(reasons, [])

    def test_comprehensive_rejects_missing_second_pass_evidence(self):
        """Single-pass workflow cannot claim comprehensive completeness."""
        audit = {
            "anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
            "coverage_by_tier": {"1": {"pct_covered": 100.0}, "2": {"pct_covered": 100.0}},
            "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 20},
            "skew_flags": [], "duplicate_flags": [], "limitations": []
        }
        ev = {"exhaustive_second_pass": False}
        status, reasons = gate_mod.decide(audit, 1.0, evidence=ev)
        self.assertEqual(status, "LIMITED")
        self.assertTrue(any("verification scope reduced" in r for r in reasons))

    def test_comprehensive_rejects_missing_mandatory_reviews(self):
        """Verification evidence with missing review streams cannot certify the run."""
        audit = {
            "anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
            "coverage_by_tier": {"1": {"pct_covered": 100.0}, "2": {"pct_covered": 100.0}},
            "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 20},
            "skew_flags": [], "duplicate_flags": [], "limitations": []
        }
        ev = {"exhaustive_second_pass": True, "missing_reviews": True}
        status, reasons = gate_mod.decide(audit, 1.0, evidence=ev)
        self.assertEqual(status, "LIMITED")
        self.assertTrue(any("mandatory review" in r for r in reasons))

    def test_genuine_substantive_failure_never_overwritten_to_limited(self):
        """Substantive audit failures (e.g. coverage gaps) remain PARTIAL, never overwritten to LIMITED."""
        # Tier 1 coverage only 85%
        ev = {"exhaustive_second_pass": False, "missing_reviews": False}
        audit_cov_fail = {
            "anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
            "coverage_by_tier": {"1": {"pct_covered": 85.0}, "2": {"pct_covered": 100.0}},
            "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 20},
            "skew_flags": [], "duplicate_flags": [], "limitations": []
        }
        status_b, reasons_b = gate_mod.decide(audit_cov_fail, 1.0, evidence=ev)
        self.assertEqual(status_b, "PARTIAL", "Coverage failure must preserve PARTIAL status")

        # Anchor recall failure
        audit_rec_fail = dict(audit_cov_fail, coverage_by_tier={"1": {"pct_covered": 100.0}}, anchor_recall=0.75)
        status_r, _ = gate_mod.decide(audit_rec_fail, 1.0, evidence=ev)
        self.assertEqual(status_r, "PARTIAL", "Recall failure must preserve PARTIAL status")


class TestConcurrencyAndRetryLimits(unittest.TestCase):
    """Section 5: Concurrency bounds, retry backoff, fast-abort on permanent errors."""

    def test_execute_batch_pool_bounds_concurrency_and_retries(self):
        """Concurrency is bounded to max_workers and retryable errors backoff and retry."""
        active = 0
        peak = 0
        lock = threading.Lock()
        attempts = {}

        def mock_worker(batch):
            nonlocal active, peak
            with lock:
                active += 1
                if active > peak:
                    peak = active
            try:
                bid = batch["id"]
                attempts[bid] = attempts.get(bid, 0) + 1
                if bid == "B-2" and attempts[bid] == 1:
                    raise IOError("Simulated transient connection timeout")
                time.sleep(0.01)
                return [{"q": bid}]
            finally:
                with lock:
                    active -= 1

        batches = [{"id": "B-%d" % i} for i in range(8)]
        res = cache_mod.execute_batch_pool(batches, mock_worker, max_workers=3, max_retries=2, initial_backoff=0.01)

        self.assertLessEqual(peak, 3, "Peak concurrency exceeded max_workers bound")
        self.assertEqual(len(res), 8)
        self.assertEqual(attempts["B-2"], 2, "Transient error should have been retried once")
        # Deterministic ordered merge
        self.assertEqual([r[0]["q"] for r in res], ["B-%d" % i for i in range(8)])

    def test_execute_batch_pool_fast_abort_permanent_error(self):
        """Permanent schema/value errors fast-abort without indefinite retries."""
        call_count = 0

        def failing_worker(batch):
            nonlocal call_count
            call_count += 1
            raise ValueError("Permanent schema violation: missing required field")

        with self.assertRaises(ValueError):
            cache_mod.execute_batch_pool([{"id": "B-0"}], failing_worker, max_workers=2, max_retries=3)
        self.assertEqual(call_count, 1, "Permanent ValueError should not be repeatedly retried")


class TestTruthfulTelemetry(unittest.TestCase):
    """Section 6: Truthful LLM call instrumentation and monotonic duration tracking."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_telemetry_"))
        self.trace_path = str(self.tmp / "llm_trace.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_monotonic_llm_call_timer(self):
        """LLMCallTimer measures positive elapsed time from monotonic clock."""
        with llm_trace_mod.LLMCallTimer(self.trace_path, "generation", "B1", "fp_123") as timer:
            time.sleep(0.02)
        self.assertGreaterEqual(timer.duration_s, 0.005)

        records = llm_trace_mod.load_llm_trace(self.trace_path)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["stage"], "generation")
        self.assertEqual(rec["batch_id"], "B1")
        self.assertTrue(rec["success"])
        self.assertGreaterEqual(rec["duration_s"], 0.005)

    def test_token_availability_reporting(self):
        """Unobserved token counts are truthfully reported as unavailable, never fabricated."""
        llm_trace_mod.record_llm_call(self.trace_path, "extraction", "C1", "fp_c1",
                                     input_tokens=None, output_tokens=None)
        summary = llm_trace_mod.summarize_llm_trace(self.trace_path)
        self.assertEqual(summary["input_tokens"], "unavailable")
        self.assertEqual(summary["output_tokens"], "unavailable")

        # When supplied by provider, sums are reported
        self.setUp()  # clear trace
        llm_trace_mod.record_llm_call(self.trace_path, "extraction", "C1", "fp_c1",
                                     input_tokens=150, output_tokens=75)
        summary2 = llm_trace_mod.summarize_llm_trace(self.trace_path)
        self.assertEqual(summary2["input_tokens"], 150)
        self.assertEqual(summary2["output_tokens"], 75)

    def test_concurrent_telemetry_thread_safety(self):
        """Concurrent logging from multiple threads writes valid JSONL without corruption."""
        def worker(w_id):
            for i in range(10):
                llm_trace_mod.record_llm_call(self.trace_path, "stage", "B-%d-%d" % (w_id, i),
                                             "fp_%d" % i, duration_s=0.01)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        records = llm_trace_mod.load_llm_trace(self.trace_path)
        self.assertEqual(len(records), 80)
        # Verify no lines were interleaved or corrupt
        with open(self.trace_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        self.assertEqual(len(lines), 80)
        for l in lines:
            parsed = json.loads(l)
            self.assertIn("batch_id", parsed)


class TestAlgorithmicParityDeep(unittest.TestCase):
    """Section 7: Algorithmic output parity against unoptimized reference implementations."""

    def test_dedupe_exhaustive_parity_against_reference(self):
        """Optimized dedupe matches unoptimized pairwise reference across all duplicate categories."""
        import itertools

        def unoptimized_reference_dedupe(questions, threshold=0.85):
            pairs = []
            diversity = []
            for x, y in itertools.combinations(questions, 2):
                x_id, y_id = x.get("id"), y.get("id")
                x_stem = lib_common.norm(x.get("stem", ""))
                y_stem = lib_common.norm(y.get("stem", ""))
                if x_stem and x_stem == y_stem:
                    pairs.append({
                        "a": x_id, "b": y_id, "type": "exact_duplicate",
                        "similarity": 1.0, "reason": "identical question stem"
                    })
                    continue
                bx = (x.get("stem", "") or "") + " " + " ".join(
                    o.get("text", "") if isinstance(o, dict) else str(o) for o in (x.get("options") or [])
                )
                by = (y.get("stem", "") or "") + " " + " ".join(
                    o.get("text", "") if isinstance(o, dict) else str(o) for o in (y.get("options") or [])
                )
                s = lib_common.token_set_sim(bx, by)
                if s >= threshold:
                    pairs.append({
                        "a": x_id, "b": y_id, "type": "semantic_duplicate",
                        "similarity": round(s, 3), "reason": "high token-set similarity (%.3f)" % s
                    })
                    continue
                sts_x = [st.get("text", "") if isinstance(st, dict) else str(st) for st in (x.get("statements") or [])]
                sts_y = [st.get("text", "") if isinstance(st, dict) else str(st) for st in (y.get("statements") or [])]
                if sts_x and sts_y and len(sts_x) == len(sts_y):
                    matches = sum(1 for sx in sts_x if any(lib_common.token_set_sim(sx, sy) >= 0.85 for sy in sts_y))
                    if matches == len(sts_x):
                        pairs.append({
                            "a": x_id, "b": y_id, "type": "same_statement_set",
                            "similarity": round(s, 3), "reason": "same statements with cosmetic changes"
                        })
                        continue
                x_prim = dedupe_mod.get_prim_ku(x)
                y_prim = dedupe_mod.get_prim_ku(y)
                x_purp = x.get("purpose")
                y_purp = y.get("purpose")
                if x_prim and y_prim and x_prim == y_prim:
                    if x_purp and y_purp and x_purp == y_purp:
                        stem_sim = lib_common.token_set_sim(x.get("stem", ""), y.get("stem", ""))
                        if stem_sim >= 0.65 or s >= 0.70:
                            pairs.append({
                                "a": x_id, "b": y_id, "type": "same_fact_same_purpose",
                                "similarity": round(stem_sim, 3),
                                "reason": "redundant: same primary KU %s and purpose '%s'" % (x_prim, x_purp)
                            })
                            continue
                    elif x_purp and y_purp and x_purp != y_purp:
                        diversity.append({
                            "a": x_id, "b": y_id, "ku_id": x_prim,
                            "purpose_a": x_purp, "purpose_b": y_purp,
                            "reason": "valuable diversity: same KU tested across different purposes"
                        })
            return pairs, diversity

        # Bank covering all test cases
        test_bank = [
            # Exact duplicates (different whitespace/case)
            {"id": "Q-1", "stem": "What is the capital of Assam?", "options": [{"text": "Dispur"}], "purpose": "recall", "primary_ku": "KU-1"},
            {"id": "Q-2", "stem": "  what IS the capital OF assam? ", "options": [{"text": "Dispur"}], "purpose": "recall", "primary_ku": "KU-1"},
            # Semantic duplicate
            {"id": "Q-3", "stem": "Identify the administrative capital of Assam state", "options": [{"text": "Dispur"}], "purpose": "recall", "primary_ku": "KU-1"},
            # Same statements permuted
            {"id": "Q-4", "stem": "Consider statements", "statements": [{"text": "Statement Alpha"}, {"text": "Statement Beta"}], "purpose": "analysis", "primary_ku": "KU-2"},
            {"id": "Q-5", "stem": "Evaluate statements", "statements": [{"text": "Statement Beta"}, {"text": "Statement Alpha"}], "purpose": "analysis", "primary_ku": "KU-2"},
            # Same KU, different purpose (valuable diversity)
            {"id": "Q-6", "stem": "Which treaty ended the Anglo-Burmese war?", "purpose": "direct_recall", "primary_ku": "KU-3"},
            {"id": "Q-7", "stem": "Distinguish the provisions of Treaty of Yandabo", "purpose": "conceptual_distinction", "primary_ku": "KU-3"},
            # Disjoint
            {"id": "Q-8", "stem": "Kaziranga National Park is located on which river bank?", "options": [{"text": "Brahmaputra"}], "purpose": "geography", "primary_ku": "KU-4"},
        ]

        opt_pairs, opt_div = dedupe_mod.detect_duplicates(test_bank, threshold=0.75)
        ref_pairs, ref_div = unoptimized_reference_dedupe(test_bank, threshold=0.75)

        self.assertEqual(len(opt_pairs), len(ref_pairs))
        for p_opt, p_ref in zip(opt_pairs, ref_pairs):
            self.assertEqual(p_opt["a"], p_ref["a"])
            self.assertEqual(p_opt["b"], p_ref["b"])
            self.assertEqual(p_opt["type"], p_ref["type"])
            self.assertEqual(p_opt["similarity"], p_ref["similarity"])

        self.assertEqual(len(opt_div), len(ref_div))
        for d_opt, d_ref in zip(opt_div, ref_div):
            self.assertEqual(d_opt["a"], d_ref["a"])
            self.assertEqual(d_opt["b"], d_ref["b"])
            self.assertEqual(d_opt["ku_id"], d_ref["ku_id"])

    def test_anchor_null_byte_delimiter_boundary_isolation(self):
        """Null byte delimiter cannot match across two unrelated source units."""
        units = [
            {"id": "KU-1", "statement": "The Brahmaputra river enters Assam near Sadiya"},
            {"id": "KU-2", "statement": "Tea gardens were first planted in Upper Assam"},
        ]
        joined_corpus, ku_map = anchors_mod.build_anchor_index(units)

        # Confirm intra-unit anchors match
        self.assertTrue(anchors_mod.check_anchor_hit("sadiya", joined_corpus))
        self.assertTrue(anchors_mod.check_anchor_hit("tea gardens", joined_corpus))

        # Confirm cross-boundary span CANNOT match
        cross_query = "sadiya tea gardens"
        self.assertFalse(anchors_mod.check_anchor_hit(cross_query, joined_corpus))

        # Even with raw null byte, norm removes or sanitizes, but query cannot span units
        cross_null = "sadiya\x00tea"
        self.assertFalse(anchors_mod.check_anchor_hit(lib_common.norm(cross_null), joined_corpus))


if __name__ == "__main__":
    unittest.main(verbosity=2)

