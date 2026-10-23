"""FAST single-workflow contract tests (refactor §9).

Covers: deterministic planner correctness (identity/count policy/share caps),
physical redaction, one bounded repair queue, honest gate evidence (no
self-claimed COMPREHENSIVE), single review stream, batch assembly, and
truthful run_metrics.

Stdlib only; runnable via `python tests/test_fast_pipeline.py` and
`python -m unittest discover tests`.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = sys.executable
SCRIPTS = str(ROOT / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import cache as cache_mod  # noqa: E402
import plan as plan_mod    # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "longdoc"


def run_pipeline(tmp, run_id, extra=None, profile=None):
    args = [PY, "scripts/pipeline.py", "--source", "examples/sample_source.md",
            "--run-id", run_id, "--config", "config.default.json",
            "--ignored", "examples/ignored_anchors.json",
            "--build-dir", str(tmp)]
    if profile:
        args += ["--profile", profile]
    if extra:
        args += [str(x) for x in extra]
    return subprocess.run(args, capture_output=True, text=True,
                          cwd=str(ROOT), timeout=300)


def make_struct(tmp, stem="st"):
    """Ingest the sample source deterministically; returns struct path."""
    struct_dir = Path(tmp) / stem
    struct = struct_dir / "document_structure.json"
    if not struct.is_file():
        r = subprocess.run([PY, "scripts/ingest.py", "examples/sample_source.md",
                            "--out", str(struct_dir), "--run-id", stem],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        if r.returncode != 0:
            raise AssertionError(r.stdout + r.stderr)
    return str(struct)


def run_plan(out_dir, count=None, inventory=None, extraction_dir=None,
             struct=None, cfg=None, tmpdir=None):
    struct = struct or make_struct(tmpdir or Path(out_dir).parent)
    args = [PY, "scripts/plan.py", "--document-structure", struct,
            "--out-dir", str(out_dir),
            "--config", cfg or "config.default.json"]
    if count is not None:
        args += ["--count", str(count)]
    if inventory:
        args += ["--inventory", str(inventory)]
    if extraction_dir:
        args += ["--extraction-dir", str(extraction_dir)]
    return subprocess.run(args, capture_output=True, text=True,
                          cwd=str(ROOT), timeout=300)


class TestPlannerDeterminism(unittest.TestCase):
    """Reconciliation is deterministic: same inputs, same artifacts."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fastplan_"))
        self.inv = ROOT / "examples/sample_inventory.json"

    def test_plan_outputs_identical_across_runs(self):
        r1 = run_plan(self.tmp / "a", inventory=self.inv, tmpdir=self.tmp)
        r2 = run_plan(self.tmp / "b", inventory=self.inv, tmpdir=self.tmp)
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        for name in ("coverage_plan.json", "generation_batches.json", "chunks.json"):
            a = json.loads((self.tmp / "a" / name).read_text(encoding="utf-8"))
            b = json.loads((self.tmp / "b" / name).read_text(encoding="utf-8"))
            self.assertEqual(a, b, name)

    def test_blueprint_rows_carry_core_fields(self):
        r = run_plan(self.tmp, inventory=self.inv, tmpdir=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        plan = json.loads((self.tmp / "coverage_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["workflow"], "FAST")
        for row in plan["rows"]:
            self.assertIn(row["qtype"], {
                "factual_mcq", "statement_based", "assertion_reason", "match_pairs",
                "elimination_mcq", "one_liner_mcq", "data_interpretation_mcq",
                "reasoning_mcq", "pedagogy_mcq", "sequence_mcq", "true_false"})
            self.assertTrue(row["ku_id"])
            self.assertIn(row["difficulty"], ("easy", "medium", "hard"))
            self.assertTrue(row["purpose"])
        gb = json.loads((self.tmp / "generation_batches.json").read_text(encoding="utf-8"))
        bs = gb["batch_size"]
        self.assertEqual(gb["batch_count"], (len(plan["rows"]) + bs - 1) // bs)
        self.assertEqual(gb["planned_questions"], len(plan["rows"]))
        self.assertEqual(sum(len(b["rows"]) for b in gb["batches"]), len(plan["rows"]))


class TestCountPolicy(unittest.TestCase):
    """Requested count is an ordinary parameter: honored by priority, never
    padded, higher-priority material never cut first."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fastcount_"))
        self.inv = ROOT / "examples/sample_inventory.json"

    def _meta(self, out):
        plan = json.loads((Path(out) / "coverage_plan.json").read_text(encoding="utf-8"))
        return plan

    def test_requested_count_honored(self):
        r = run_plan(self.tmp, count=20, inventory=self.inv, tmpdir=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        plan = self._meta(self.tmp)
        self.assertEqual(len(plan["rows"]), 20)
        self.assertIn("deferred", " ".join(plan["policy_notes"]).lower())

    def test_overrequest_not_padded(self):
        r = run_plan(self.tmp, count=100000, inventory=self.inv, tmpdir=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        plan = self._meta(self.tmp)
        r2 = run_plan(self.tmp / "all_rows", inventory=self.inv, tmpdir=self.tmp)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        full_plan = json.loads((self.tmp / "all_rows" / "coverage_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(len(plan["rows"]), len(full_plan["rows"]))
        self.assertIn("no filler", " ".join(plan["policy_notes"]).lower())

    def test_truncation_keeps_top_priority_rows(self):
        r = run_plan(self.tmp, count=25, inventory=self.inv, tmpdir=self.tmp)
        full = run_plan(self.tmp / "full", inventory=self.inv, tmpdir=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(full.returncode, 0, full.stdout + full.stderr)
        plan = self._meta(self.tmp)
        full_plan = self._meta(self.tmp / "full")

        kept_kus = {row["ku_id"] for row in plan["rows"]}
        deferred_kus = {row["ku_id"] for row in full_plan["rows"]} - kept_kus
        # a tier of every kept row must be <= every deferred row's tier
        units = json.loads(self.inv.read_text(encoding="utf-8")).get("units", [])
        tier = {u["id"]: u.get("tier", 3) for u in units}
        kept_tiers = [tier.get(k, 3) for k in kept_kus if k in tier]
        deferred_tiers = [tier.get(k, 3) for k in deferred_kus if k in tier]
        self.assertTrue(kept_tiers)
        self.assertLessEqual(max(kept_tiers), min(deferred_tiers))

    def test_extractor_dir_merge_dedupes_and_orders(self):
        """Per-chunk extraction files merge in chunk order with identity dedupe."""
        base = [{"chunk_id": "C-001", "kus": [
                    {"id": "KU-A", "statement": "the capital is Dispur",
                     "supporting_excerpt": "The capital is Dispur",
                     "source": {"block_id": "B-0001"}, "tier": 1}],
                 "limitations": ["table edge clipped"]},
                {"chunk_id": "C-002", "kus": [
                    # duplicate identity of KU-A (same block, same excerpt)
                    {"id": "KU-B", "statement": "The capital dispur",
                     "supporting_excerpt": "the  capital is   Dispur ",
                     "source": {"block_id": "B-0001"}, "tier": 2},
                    {"id": "KU-C", "statement": "Dehing Patkai", 
                     "supporting_excerpt": "Dehing Patkai wildlife",
                     "source": {"block_id": "B-0002"}, "tier": 2}],
                 "limitations": []}]
        ed = self.tmp / "chunks"
        ed.mkdir(parents=True)
        for i, doc in enumerate(base, 1):
            (ed / ("chunk_%d.json" % i)).write_text(json.dumps(doc), encoding="utf-8")
        r = run_plan(self.tmp, extraction_dir=ed, tmpdir=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        plan = self._meta(self.tmp)
        kept = {row["ku_id"] for row in plan["rows"]}
        self.assertIn("KU-A", kept)
        self.assertNotIn("KU-B", kept)  # identity duplicate dropped
        self.assertIn("KU-C", kept)
        self.assertTrue(any("dedupe" in n.lower() for n in plan["policy_notes"]))
        self.assertTrue(any("limitation" in n.lower() for n in plan["policy_notes"]))


class TestBatchAssembly(unittest.TestCase):
    def test_bank_from_merges_in_batch_order_and_rejects_duplicates(self):
        tmp = Path(tempfile.mkdtemp(prefix="fastbank_"))
        gen = tmp / "gen"
        gen.mkdir(parents=True)
        (gen / "batch_1.json").write_text(json.dumps(
            {"questions": [{"id": "Q-0001", "stem": "a"},
                           {"id": "Q-0002", "stem": "b"}]}), encoding="utf-8")
        (gen / "batch_2.json").write_text(json.dumps(
            {"questions": [{"id": "Q-0003", "stem": "c"}]}), encoding="utf-8")
        r = subprocess.run([PY, "scripts/plan.py",
                            "--document-structure", make_struct(tmp),
                            "--out-dir", str(tmp),
                            "--bank-from", str(gen),
                            "--bank-out", str(tmp / "bank.json")],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        bank = json.loads((tmp / "bank.json").read_text(encoding="utf-8"))
        self.assertEqual([q["id"] for q in bank["questions"]],
                         ["Q-0001", "Q-0002", "Q-0003"])
        # duplicate id across batches is a hard error, never silently merged
        (gen / "batch_2.json").write_text(json.dumps(
            {"questions": [{"id": "Q-0001", "stem": "dup"}]}), encoding="utf-8")
        r2 = subprocess.run([PY, "scripts/plan.py",
                             "--document-structure", make_struct(tmp),
                             "--out-dir", str(tmp),
                             "--bank-from", str(gen),
                             "--bank-out", str(tmp / "bank2.json")],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertNotEqual(r2.returncode, 0)
        self.assertIn("duplicate", (r2.stderr + r2.stdout).lower())


class TestRedactionAndSingleStream(unittest.TestCase):
    """Blind review: physical redaction and in-code comparison."""

    def test_redaction_removes_every_key_signal(self):
        q = {"id": "Q-1", "stem": "s", "answer": "A", "answer_key": "A",
             "confidence": 0.9, "attempt_count": 0,
             "options": [{"key": "A", "text": "t", "is_correct": True,
                          "covers": [1]}],
             "statements": [{"text": "x", "truth_value": True,
                             "truth": "true", "is_true": True}],
             "review": {"decision": "ok"}, "quality_status": "accepted"}
        r = cache_mod.redact_question(q)
        self.assertNotIn("answer", r)
        self.assertNotIn("answer_key", r)
        self.assertNotIn("confidence", r)
        self.assertNotIn("quality_status", r)
        self.assertNotIn("is_correct", r["options"][0])
        self.assertNotIn("covers", r["options"][0])
        for s in r["statements"]:
            self.assertNotIn("truth_value", s)
            self.assertNotIn("truth", s)
            self.assertNotIn("is_true", s)
        # retained teaching material
        self.assertEqual(r["options"][0]["text"], "t")
        self.assertEqual(r["statements"][0]["text"], "x")

    def test_redaction_is_deep(self):
        q = {"id": "Q-2", "options": [{"key": "B", "is_correct": False}],
             "statements": []}
        r = cache_mod.redact_question(q)
        self.assertNotIn("is_correct", r["options"][0])
        # mutating the redacted copy must never leak back into the bank
        r["options"][0]["is_correct"] = True
        self.assertFalse(q["options"][0]["is_correct"])

    def test_blind_comparison_matches_keys_case_insensitive(self):
        self.assertTrue(cache_mod.compare_blind("a", "A"))
        self.assertTrue(cache_mod.compare_blind(" D ", "d"))
        self.assertFalse(cache_mod.compare_blind("A", "B"))


class TestRepairIsolation(unittest.TestCase):
    """An invalid bank signals failure but never stops valid work: the repair
    queue targets exactly the rejected questions."""

    def test_repair_queue_lists_only_rejected_questions(self):
        tmp = Path(tempfile.mkdtemp(prefix="fastrepair_"))
        r = subprocess.run([PY, "scripts/pipeline.py", "--source", str(FIX / "longdoc_source.md"),
                            "--run-id", "r", "--config", "config.default.json",
                            "--ignored", str(FIX / "ignored_anchors.json"),
                            "--build-dir", str(tmp),
                            "--inventory", str(FIX / "inventory.json"),
                            "--bank", str(FIX / "question_bank_invalid.json")],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        # invalid bank must still signal failure (never a false success) ...
        self.assertNotEqual(r.returncode, 0)
        # ... but valid work continues: repair queue + audit artifacts exist
        self.assertTrue((tmp / "r" / "repair_queue.json").is_file())
        self.assertTrue((tmp / "r" / "audit_report.json").is_file())
        repair = json.loads((tmp / "r" / "repair_queue.json").read_text(encoding="utf-8"))
        self.assertGreater(len(repair.get("failed", [])), 0)
        self.assertEqual(repair.get("max_retries"), 2)
        val_path = tmp / "r" / "validation_results.json"
        if val_path.is_file():
            val = json.loads(val_path.read_text(encoding="utf-8"))
            rejected = {res["id"] for res in val.get("results", [])
                        if res.get("status") == "rejected"}
            queued = {item.get("id") for item in repair.get("failed", [])}
            self.assertTrue(queued <= rejected,
                            "queue must target rejected items only")


class TestHonestGateAndEvidence(unittest.TestCase):
    """The FAST workflow never overclaims: single-pass evidence is recorded."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fastgate_"))

    def test_pipeline_records_single_pass_evidence(self):
        r = run_pipeline(self.tmp, "t_ev",
                         extra=["--inventory", "examples/sample_inventory.json",
                                "--bank", "examples/starter_bank.json"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run_dir = self.tmp / "t_ev"
        ev = json.loads((run_dir / "verification_evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(ev["verification_policy"], "single_pass_blind_review")
        self.assertFalse(ev["exhaustive_second_pass"])
        gate = json.loads((run_dir / "gate.json").read_text(encoding="utf-8"))
        self.assertIn(gate["status"], ("PARTIAL", "LIMITED"))
        self.assertNotEqual(gate["status"], "COMPREHENSIVE")
        self.assertEqual(gate["verification_policy"], "single_pass_blind_review")
        self.assertFalse(gate["evidence_verified"])

    def test_gate_never_comprehensive_without_sweep_evidence_even_for_legacy_runs(self):
        import gate as gate_mod
        audit = {"anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
                 "coverage_by_tier": {"1": {"pct_covered": 100.0},
                                      "2": {"pct_covered": 100.0}},
                 "validation_rates": {"pct_validated": 100.0},
                 "ku_counts": {"total": 2}, "skew_flags": [],
                 "duplicate_flags": [], "limitations": []}
        status, reasons = gate_mod.decide(audit, 1.0)
        self.assertEqual(status, "LIMITED")
        self.assertTrue(any("verification" in x for x in reasons))
        ev_clean = {"exhaustive_second_pass": True, "missing_reviews": False}
        self.assertEqual(gate_mod.decide(audit, 1.0, evidence=ev_clean)[0], "COMPREHENSIVE")
        ev_missing = {"exhaustive_second_pass": True, "missing_reviews": True}
        self.assertEqual(gate_mod.decide(audit, 1.0, evidence=ev_missing)[0], "LIMITED")


class TestRunMetricsTruth(unittest.TestCase):
    """run_metrics.json is truthful and free of mode vocabulary."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fastmetrics_"))

    def test_metrics_report_workflow_and_counts(self):
        r = run_pipeline(self.tmp, "t_m",
                         extra=["--inventory", "examples/sample_inventory.json",
                                "--bank", "examples/starter_bank.json"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = json.loads((self.tmp / "t_m" / "run_metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(m["workflow"], "FAST")
        self.assertEqual(m["verification_policy"], "single_pass_blind_review")
        self.assertNotIn("processing_mode", m)
        self.assertIn("stages", m)
        self.assertIn("plan", m["stages"])
        wc = m.get("work_counts") or {}
        self.assertTrue(wc.get("extraction_chunks", 0) >= 1)
        self.assertTrue(wc.get("question_batches", 0) >= 1)

    def test_llm_telemetry_summary_when_trace_recorded(self):
        run_dir = self.tmp / "t_llm"
        (run_dir).mkdir(parents=True)
        trace = run_dir / "llm_trace.jsonl"
        r = subprocess.run([PY, "scripts/llm_trace.py", "--trace", str(trace),
                            "--stage", "generate", "--batch", "GB-001",
                            "--fingerprint", "fp1", "--duration", "3.5",
                            "--input-tokens", "900", "--output-tokens", "100",
                            "--retries", "1"],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        import llm_trace
        s = llm_trace.summarize_llm_trace(str(trace))
        self.assertEqual(s["total_calls"], 1)
        self.assertEqual(s["retries"], 1)
        self.assertEqual(s["input_tokens"], 900)
        self.assertEqual(s["by_stage"]["generate"]["calls"], 1)
        self.assertEqual(s["by_stage"]["generate"]["duration_s"], 3.5)

    def test_token_counts_unavailable_never_fabricated(self):
        import llm_trace
        tmp = Path(tempfile.mkdtemp(prefix="fasttok_"))
        trace = tmp / "llm_trace.jsonl"
        record = {"timestamp": 0, "stage": "generate", "batch_id": "GB-1",
                  "batch_fingerprint": "fp", "cache_hit": False, "success": True,
                  "retry_count": 0, "duration_s": 1.0}
        trace.write_text(json.dumps(record) + "\n", encoding="utf-8")
        s = llm_trace.summarize_llm_trace(str(trace))
        self.assertEqual(s["input_tokens"], "unavailable")
        self.assertEqual(s["output_tokens"], "unavailable")
        self.assertEqual(s["by_stage"]["generate"]["input_tokens"], "unavailable")

    def test_no_llm_trace_keeps_honest_unavailable_marker(self):
        r = run_pipeline(self.tmp, "t_notrace",
                         extra=["--inventory", "examples/sample_inventory.json",
                                "--bank", "examples/starter_bank.json"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = json.loads((self.tmp / "t_notrace" / "run_metrics.json").read_text(encoding="utf-8"))
        self.assertIn("unavailable", str(m["model_calls"]))


class TestCacheInvalidationOnCountAndConfig(unittest.TestCase):
    """The plan stage fingerprint includes the count; changing it re-plans and
    changes generation batches, without re-running ingest/anchors."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fastcache_"))

    def test_count_change_replans_but_keeps_ingest(self):
        r1 = run_pipeline(self.tmp, "t_c1",
                          extra=["--inventory", "examples/sample_inventory.json",
                                 "--bank", "examples/starter_bank.json"])
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        state1 = json.loads((self.tmp / "t_c1" / "pipeline_state.json").read_text(encoding="utf-8"))
        r2 = run_pipeline(self.tmp, "t_c1",
                          extra=["--inventory", "examples/sample_inventory.json",
                                 "--bank", "examples/starter_bank.json",
                                 "--count", "12"])
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        state2 = json.loads((self.tmp / "t_c1" / "pipeline_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state1["stages"]["ingest"]["status"], "ok")
        self.assertEqual(state2["stages"]["ingest"]["status"], "skipped")
        self.assertEqual(state2["stages"]["anchors"]["status"], "skipped")
        self.assertIn(state2["stages"]["plan"]["status"], ("ok", "skipped"))
        gb = json.loads((self.tmp / "t_c1" / "generation_batches.json").read_text(encoding="utf-8"))
        self.assertEqual(gb["planned_questions"], 12)

    def test_fingerprint_includes_count(self):
        import pipeline as pipeline_mod
        import lib_common
        tmp = self.tmp
        args = ["--source", "examples/sample_source.md", "--run-id", "fp",
                "--config", "config.default.json", "--build-dir", str(tmp)]
        ap = pipeline_mod.main
        # compute_stage_fingerprint exposed; check directly with mocked args
        class A:
            source = "examples/sample_source.md"
            profile = None
            config = "config.default.json"
            inventory = "examples/sample_inventory.json"
            bank = "examples/starter_bank.json"
            ignored = None
            diff = None
            count = None
            redo = None
            mode = None
            package = web = pdf = full = deliver = delivery_dir = delivery_mode = None
        a1 = A()
        a2 = A()
        a2.count = 12
        cfg = json.loads((ROOT / "config.default.json").read_text(encoding="utf-8"))
        R = str(tmp)
        F = pipeline_mod._default_F(R) if hasattr(pipeline_mod, "_default_F") else {
            "struct": os.path.join(R, "document_structure.json"),
            "anchors": os.path.join(R, "anchors.json"),
            "chunks": os.path.join(R, "chunks.json"),
            "check": os.path.join(R, "inventory_check.json"),
            "coverage_plan": os.path.join(R, "coverage_plan.json"),
            "generation_batches": os.path.join(R, "generation_batches.json"),
            "validation": os.path.join(R, "validation_results.json"),
        }
        fp_none = pipeline_mod.compute_stage_fingerprint("plan", R, F, a1, cfg)
        fp_12 = pipeline_mod.compute_stage_fingerprint("plan", R, F, a2, cfg)
        self.assertNotEqual(fp_none, fp_12)
        # ingest does not see the count
        self.assertEqual(pipeline_mod.compute_stage_fingerprint("ingest", R, F, a1, cfg),
                         pipeline_mod.compute_stage_fingerprint("ingest", R, F, a2, cfg))


class TestPlannerIdentityRules(unittest.TestCase):
    """Planner honors per-KU cap and section share cap deterministically."""

    def _units(self):
        units = []
        for i in range(1, 13):
            u = {"id": "KU-%04d" % i,
                 "statement": "unit %d statement" % i,
                 "supporting_excerpt": "excerpt %d" % i,
                 "source": {"block_id": "B-%04d" % i,
                            "section_path": ["Sec%d" % (1 if i <= 6 else i)],
                            "page": 1},
                 "tier": 1 if i <= 8 else 2,
                 "type": "concept", "topic": "t", "subtopic": "s",
                 "origin": "source", "omission_reason": None,
                 "language": "en", "related_ku": [], "confusable_with": [],
                 "tier_history": [], "dimensions": {}}
            if i == 1:
                u["question_hints"] = [
                    {"purpose": "direct_recall", "type": "factual_mcq"},
                    {"purpose": "elimination", "type": "elimination_mcq"},
                    {"purpose": "chronology", "type": "sequence_mcq"},
                    {"purpose": "application", "type": "reasoning_mcq"}]
            units.append(u)
        return units

    def test_per_ku_cap(self):
        cfg = {"per_ku_cap": 3, "section_share_cap": 100.0}
        notes = []
        rows, _ = plan_mod.reconcile_and_plan(self._units(), cfg, None, notes)
        per_ku = {}
        for r in rows:
            per_ku[r["ku_id"]] = per_ku.get(r["ku_id"], 0) + 1
        self.assertEqual(per_ku.get("KU-0001"), 3)  # 4 hints capped to per_ku_cap 3

    def test_every_eligible_ku_gets_a_row(self):
        cfg = {"per_ku_cap": 3, "section_share_cap": 100.0}
        rows, _ = plan_mod.reconcile_and_plan(self._units(), cfg, None, [])
        planned = {r["ku_id"] for r in rows}
        self.assertEqual(len(planned), 12)

    def test_requested_count_zero_rejected(self):
        cfg = {"per_ku_cap": 3}
        with self.assertRaises(SystemExit):
            plan_mod.reconcile_and_plan(self._units(), cfg, 0, [])
