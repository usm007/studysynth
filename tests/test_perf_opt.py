"""Phase 11 regression tests for the performance optimization.

Covers chunking, overlap dedup, bounded concurrency config, deterministic merge
order, batch JSON failure isolation, localized repair, review-key redaction,
cache hits/invalidation, interruption/resume, coverage eligibility, parallel
output behavior. Runnable via tests/run_all.py.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
FIX = HERE / "fixtures" / "longdoc"
PY = sys.executable

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cache
import coverage as covmod
import review_batch


class TestChunking(unittest.TestCase):
    def test_section_aware_and_table_intact(self):
        blocks = [
            {"id": "B-0001", "kind": "paragraph", "page": 1, "section_path": ["S1"], "text": "alpha " * 2000},
            {"id": "B-0002", "kind": "paragraph", "page": 1, "section_path": ["S1"], "text": "beta " * 50},
            {"id": "B-0003", "kind": "table", "page": 2, "section_path": ["S2"],
             "text": "h1 | h2\na | b", "table": {"rows": [["h1", "h2"], ["a", "b"]], "caption": None}},
        ]
        chunks = cache.chunk_blocks(blocks, max_tokens=5000)
        self.assertTrue(chunks)
        ids = [b["id"] for c in chunks for b in c["blocks"]]
        self.assertEqual(sorted(ids), ["B-0001", "B-0002", "B-0003"])
        # deterministic ids
        self.assertEqual([c["chunk_id"] for c in chunks],
                         [c["chunk_id"] for c in cache.chunk_blocks(blocks, max_tokens=5000)])

    def test_large_table_splits_at_rows_preserving_header(self):
        rows = [["h1", "h2"]] + [["r%dc1" % i, "r%dc2" % i] for i in range(200)]
        big = {"id": "B-0009", "kind": "table", "page": 3, "section_path": ["S"],
               "text": "x " * 6000, "table": {"rows": rows, "caption": "cap"}}
        chunks = cache.chunk_blocks([big], max_tokens=500)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            rr = c["blocks"][0]["table"]["rows"]
            self.assertEqual(rr[0], ["h1", "h2"])


class TestOverlapDedup(unittest.TestCase):
    def test_identity_dedup_only(self):
        u1 = {"id": "KU-0001", "supporting_excerpt": "The capital is Dispur",
              "source": {"block_id": "B-0001"}}
        u2 = {"id": "KU-0002", "supporting_excerpt": "the  capital is   Dispur ",
              "source": {"block_id": "B-0001"}}
        u3 = {"id": "KU-0003", "supporting_excerpt": "The capital is Dispur",
              "source": {"block_id": "B-0002"}}
        kept, dropped = cache.dedupe_units_by_identity([u1, u2, u3])
        self.assertEqual([u["id"] for u in kept], ["KU-0001", "KU-0003"])
        self.assertEqual(dropped, ["KU-0002"])


class TestBatchConfig(unittest.TestCase):
    def test_bounded_concurrency_defaults(self):
        cfg = json.loads((ROOT / "config.default.json").read_text(encoding="utf-8"))
        b = cfg["batching"]
        self.assertEqual(b["extraction_concurrency"], 3)
        self.assertEqual(b["question_concurrency"], 4)
        self.assertEqual(b["review_concurrency"], 4)
        self.assertTrue(4000 <= b["extraction_chunk_tokens"] <= 6000)
        self.assertTrue(6 <= b["question_batch_size"] <= 8)
        self.assertTrue(4 <= b["review_batch_size"] <= 6)
        self.assertEqual(cfg["max_repair_retries"], 2)
        self.assertEqual(cfg["max_gapfill_rounds"], 5)


class TestMergeOrder(unittest.TestCase):
    def test_deterministic_merge_and_dup_reject(self):
        qs = cache.merge_batches([(1, [{"id": "Q-2"}]), (0, [{"id": "Q-1"}])])
        self.assertEqual([q["id"] for q in qs], ["Q-1", "Q-2"])
        with self.assertRaises(ValueError):
            cache.merge_batches([(0, [{"id": "Q-1"}]), (1, [{"id": "Q-1"}])])


class TestRepairQueue(unittest.TestCase):
    def test_pipeline_continues_past_rejections(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="perfrepair_"))
        r = subprocess.run([PY, "scripts/pipeline.py", "--source", str(FIX / "longdoc_source.md"),
                            "--run-id", "r", "--profile", "profiles/APSC_PRELIMS.json",
                            "--config", "config.default.json", "--build-dir", str(tmp),
                            "--inventory", str(FIX / "inventory.json"),
                            "--bank", str(FIX / "question_bank_invalid.json"),
                            "--ignored", str(FIX / "ignored_anchors.json"),
                            "--diff", str(FIX / "inventory_diff.json")],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        # invalid bank must still signal failure (never a false success) ...
        self.assertNotEqual(r.returncode, 0)
        # ... but valid work continues: repair queue + audit artifacts exist
        self.assertTrue((tmp / "r" / "repair_queue.json").is_file())
        rq = json.loads((tmp / "r" / "repair_queue.json").read_text(encoding="utf-8"))
        self.assertGreater(len(rq["failed"]), 0)
        self.assertEqual(rq["max_retries"], 2)
        self.assertTrue((tmp / "r" / "audit_report.json").is_file())
        self.assertTrue((tmp / "r" / "run_metrics.json").is_file())


class TestRedaction(unittest.TestCase):
    def test_key_material_removed_evidence_kept(self):
        q = {"id": "Q-1", "stem": "Capital?", "answer": "B", "answer_key": "B",
             "options": [{"key": "A", "text": "X", "is_correct": False, "covers": [1]},
                         {"key": "B", "text": "Y", "is_correct": True, "covers": [2]}],
             "statements": [{"text": "s1", "truth_value": True, "ku_basis": "KU-1"}],
             "source": [{"block_id": "B-1"}], "knowledge_units": [{"ku_id": "KU-1", "role": "primary"}],
             "validation": {"x": 1}, "quality_grade": "A"}
        r = cache.redact_question(q)
        blob = json.dumps(r)
        for leak in ("answer_key", "is_correct", "truth_value", "covers", "quality_grade"):
            self.assertNotIn(leak, blob)
        self.assertEqual(r["stem"], "Capital?")
        self.assertEqual(r["options"][0]["key"], "A")
        self.assertEqual(r["statements"][0]["ku_basis"], "KU-1")

    def test_blind_compare(self):
        bank = [{"id": "Q-1", "answer_key": "b"}]
        self.assertEqual(review_batch.compare_results(bank, {"Q-1": {"blind_answer": "B"}})[0]["match"], True)
        self.assertEqual(review_batch.compare_results(bank, {"Q-1": {"blind_answer": "A"}})[0]["match"], False)


class TestCache(unittest.TestCase):
    def test_hit_and_invalidation(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="perfcache_"))
        base = [PY, "scripts/pipeline.py", "--source", str(FIX / "longdoc_source.md"),
                "--run-id", "r", "--profile", "profiles/APSC_PRELIMS.json",
                "--config", "config.default.json", "--build-dir", str(tmp),
                "--inventory", str(FIX / "inventory.json"),
                "--bank", str(FIX / "question_bank.json"),
                "--ignored", str(FIX / "ignored_anchors.json"),
                "--diff", str(FIX / "inventory_diff.json")]
        r1 = subprocess.run(base, capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        r2 = subprocess.run(base, capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        self.assertEqual(r2.returncode, 0)
        st = json.loads((tmp / "r" / "pipeline_state.json").read_text(encoding="utf-8"))
        self.assertEqual(st["stages"]["ingest"]["status"], "skipped")
        r3 = subprocess.run(base + ["--redo", "validate"], capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        self.assertEqual(r3.returncode, 0)
        st3 = json.loads((tmp / "r" / "pipeline_state.json").read_text(encoding="utf-8"))
        self.assertEqual(st3["stages"]["validate"]["status"], "ok")


class TestCoverageEligibility(unittest.TestCase):
    def _run_cov(self, tmp, bank_path, extra_args=()):
        import subprocess
        vr = tmp / "v.json"
        r = subprocess.run([PY, "scripts/validate_questions.py", str(bank_path), str(FIX / "inventory.json"),
                            str(tmp / "struct.json"), "--profile", "profiles/APSC_PRELIMS.json",
                            "--mode", "SOURCE_BOUND", "--config", "config.default.json", "--out", str(vr)],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        qr = tmp / "q.json"
        subprocess.run([PY, "scripts/quality.py", str(bank_path), str(FIX / "inventory.json"),
                        str(tmp / "struct.json"), "--profile", "profiles/APSC_PRELIMS.json",
                        "--out", str(qr)], capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        dr = tmp / "d.json"
        subprocess.run([PY, "scripts/dedupe.py", str(bank_path), "--out", str(dr)],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        cov = tmp / "cov.json"
        r2 = subprocess.run([PY, "scripts/coverage.py", str(bank_path), str(FIX / "inventory.json"),
                             str(vr), "--out", str(cov), "--config", "config.default.json",
                             "--quality", str(qr), "--dedupe", str(dr)] + list(extra_args),
                            capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        return json.loads(cov.read_text(encoding="utf-8")), vr, qr, dr

    def test_quality_rejected_and_dup_excluded_get_no_credit(self):
        import shutil
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="perfcov_"))
        import sys as _s
        _s.path.insert(0, str(SCRIPTS))
        r = subprocess.run([PY, "scripts/ingest.py", str(FIX / "longdoc_source.md"),
                            "--out", str(tmp), "--run-id", "s"],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        self.assertEqual(r.returncode, 0)
        shutil.copyfile(tmp / "s" / "document_structure.json", tmp / "struct.json")
        covd, vr, qr, dr = self._run_cov(tmp, FIX / "question_bank.json")
        # eligibility wiring is active
        self.assertTrue(covd.get("quality_filtered"))
        vrep = json.loads((tmp / "v.json").read_text(encoding="utf-8"))
        valid = {x["id"] for x in vrep["results"] if x["status"] == "validated"}
        qrep = json.loads((tmp / "q.json").read_text(encoding="utf-8"))
        accepted = {x["id"] for x in qrep["results"] if x["quality_status"] == "accepted"}
        drep = json.loads((tmp / "d.json").read_text(encoding="utf-8"))
        excluded = {p["b"] for p in drep.get("pairs", [])
                    if p.get("type") in ("exact_duplicate", "semantic_duplicate")}
        # every credited question is validated + quality-accepted + non-excluded
        for ku, e in covd["per_ku"].items():
            for qid in e["question_ids"]:
                self.assertIn(qid, valid, (ku, qid))
                self.assertIn(qid, accepted, (ku, qid))
                self.assertNotIn(qid, excluded, (ku, qid))
        # filters actually bite on this bank (legacy fixture has dup stems)
        self.assertGreater(len(excluded), 0)
        self.assertLess(covd["counted_questions"], covd["total_bank_questions"])

    def test_false_statement_alteration_not_unsupported(self):
        # declared date_shift inside a FALSE statement is the tested falsehood,
        # not an unsupported asserted fact (fixture Q-0003: 1928 not in source).
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="perfalter_"))
        r = subprocess.run([PY, "scripts/ingest.py", str(FIX / "longdoc_source.md"),
                            "--out", str(tmp), "--run-id", "s"],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        self.assertEqual(r.returncode, 0)
        bank = json.loads((FIX / "question_bank.json").read_text(encoding="utf-8"))
        mini = {"questions": [q for q in bank["questions"] if q["id"] == "Q-0003"]}
        minip = tmp / "mini_bank.json"
        minip.write_text(json.dumps(mini), encoding="utf-8")
        inv = json.loads((FIX / "inventory.json").read_text(encoding="utf-8"))
        invp = tmp / "mini_inv.json"
        invp.write_text(json.dumps(
            {"units": [u for u in inv["units"] if u["id"] in ("KU-0001", "KU-0039", "KU-0040")]}),
            encoding="utf-8")
        qr = tmp / "q.json"
        r2 = subprocess.run([PY, "scripts/quality.py", str(minip), str(invp),
                             str(tmp / "s" / "document_structure.json"),
                             "--profile", "profiles/APSC_PRELIMS.json",
                             "--out", str(qr)],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        rep = json.loads(qr.read_text(encoding="utf-8"))
        src_notes = rep["results"][0]["checks"]["source_support"]["notes"]
        self.assertFalse(any("1928" in n for n in src_notes), src_notes)

    def test_pipeline_supplies_quality_and_dedupe(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="perfpipesup_"))
        r = subprocess.run([PY, "scripts/pipeline.py", "--source", str(FIX / "longdoc_source.md"),
                            "--run-id", "r", "--profile", "profiles/APSC_PRELIMS.json",
                            "--config", "config.default.json", "--build-dir", str(tmp),
                            "--inventory", str(FIX / "inventory.json"),
                            "--bank", str(FIX / "question_bank.json"),
                            "--ignored", str(FIX / "ignored_anchors.json"),
                            "--diff", str(FIX / "inventory_diff.json")],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        covd = json.loads((tmp / "r" / "coverage_matrix.json").read_text(encoding="utf-8"))
        self.assertTrue(covd.get("quality_filtered"))

    def test_legacy_bank_grandfathered(self):
        # sample bank has no explicit purposes: coverage stays validation-only
        # so the pre-existing COMPREHENSIVE package keeps passing, while the
        # quality/dedupe reports are still produced for the audit.
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="perflegacy_"))
        r = subprocess.run([PY, "scripts/pipeline.py", "--source", "examples/sample_source.md",
                            "--run-id", "t1", "--profile", "profiles/GENERAL_PSC.json",
                            "--config", "config.default.json", "--build-dir", str(tmp),
                            "--inventory", "examples/sample_inventory.json",
                            "--bank", "examples/sample_bank.json",
                            "--processing-mode", "COMPREHENSIVE",
                            "--ignored", str(ROOT / "tests/fixtures/e2e_ignored_anchors.json"),
                            "--diff", str(ROOT / "tests/fixtures/e2e_inventory_diff.json")],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        gate = json.loads((tmp / "t1" / "gate.json").read_text(encoding="utf-8"))
        self.assertEqual(gate["status"], "COMPREHENSIVE")
        covd = json.loads((tmp / "t1" / "coverage_matrix.json").read_text(encoding="utf-8"))
        self.assertFalse(covd.get("quality_filtered"))
        self.assertTrue((tmp / "t1" / "quality_report.json").is_file())
        self.assertTrue((tmp / "t1" / "dedupe_report.json").is_file())


class TestParallelOutputs(unittest.TestCase):
    def test_web_only_skips_pdf(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="perfweb_"))
        base = [PY, "scripts/pipeline.py", "--source", str(FIX / "longdoc_source.md"),
                "--run-id", "r", "--profile", "profiles/APSC_PRELIMS.json",
                "--config", "config.default.json", "--build-dir", str(tmp),
                "--inventory", str(FIX / "inventory.json"),
                "--bank", str(FIX / "question_bank.json"),
                "--ignored", str(FIX / "ignored_anchors.json"),
                "--diff", str(FIX / "inventory_diff.json"),
                "--package", "--web"]
        r = subprocess.run(base, capture_output=True, text=True, cwd=str(ROOT), timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((tmp / "r" / "quiz_package.json").is_file())
        self.assertFalse((tmp / "r" / "pdf" / "question-paper-A.pdf").is_file())

    def test_pdf_only_skips_web(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="perfpdf_"))
        base = [PY, "scripts/pipeline.py", "--source", str(FIX / "longdoc_source.md"),
                "--run-id", "r", "--profile", "profiles/APSC_PRELIMS.json",
                "--config", "config.default.json", "--build-dir", str(tmp),
                "--inventory", str(FIX / "inventory.json"),
                "--bank", str(FIX / "question_bank.json"),
                "--ignored", str(FIX / "ignored_anchors.json"),
                "--diff", str(FIX / "inventory_diff.json"),
                "--package", "--pdf"]
        r = subprocess.run(base, capture_output=True, text=True, cwd=str(ROOT), timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((tmp / "r" / "pdf" / "question-paper-A.pdf").is_file())
        self.assertFalse((tmp / "r" / "quiz.html").is_file())


class TestRequiredFormsSourceAware(unittest.TestCase):
    """Section 4D: required forms follow source evidence, not mechanical rules."""

    def _ku(self, tier=1, conf="low", stmt="medium", ktype="fact", dens="low"):
        return {"id": "KU-T", "tier": tier, "type": ktype,
                "dimensions": {"confusion_risk": conf, "confusion_value": conf,
                               "statement_potential": stmt, "conceptual_density": dens},
                "confusable_with": []}

    def test_low_statement_potential_exempts_statement(self):
        ku = self._ku(tier=1, conf="high", stmt="low")
        ku["confusable_with"] = ["KU-X"]
        req = covmod.required_forms(ku)
        self.assertEqual(req, {"recall", "distinction"})

    def test_high_statement_potential_keeps_statement(self):
        ku = self._ku(tier=1, conf="high", stmt="high")
        ku["confusable_with"] = ["KU-X"]
        self.assertEqual(covmod.required_forms(ku), {"recall", "distinction", "statement"})

    def test_low_potential_plain_tier1_recall_only(self):
        self.assertEqual(covmod.required_forms(self._ku(tier=1, stmt="low")), {"recall"})

    def test_application_gated_by_type_and_density(self):
        self.assertIn("application", covmod.required_forms(
            self._ku(tier=2, ktype="concept", dens="high")))
        self.assertNotIn("application", covmod.required_forms(
            self._ku(tier=2, ktype="concept", dens="low")))
        self.assertNotIn("application", covmod.required_forms(
            self._ku(tier=2, ktype="fact", dens="high")))
        self.assertNotIn("application", covmod.required_forms(
            self._ku(tier=3, ktype="concept", dens="high")))


class TestBlindMismatchCoverage(unittest.TestCase):
    def _mini(self, tmp):
        ku = {"id": "KU-1", "tier": 1, "type": "fact",
              "dimensions": {"confusion_risk": "low", "statement_potential": "medium"},
              "source": {"section_path": ["S"], "block_id": "B-1"}}
        (tmp / "inv.json").write_text(json.dumps({"units": [ku]}), encoding="utf-8")

        def q(qid):
            return {"id": qid, "type": "factual_mcq", "purpose": "direct_recall",
                    "knowledge_units": [{"ku_id": "KU-1", "role": "primary"}]}
        (tmp / "bank.json").write_text(
            json.dumps({"questions": [q("Q-A"), q("Q-B")]}), encoding="utf-8")
        (tmp / "val.json").write_text(json.dumps({"results": [
            {"id": "Q-A", "status": "validated"}, {"id": "Q-B", "status": "validated"}]}),
            encoding="utf-8")

    def test_mismatched_answer_earns_no_credit(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="perfblind_"))
        self._mini(tmp)
        (tmp / "blind.json").write_text(json.dumps({"results": [
            {"id": "Q-A", "bank_key": "A", "blind_answer": "A", "match": True},
            {"id": "Q-B", "bank_key": "A", "blind_answer": "C", "match": False}]}),
            encoding="utf-8")
        cov = tmp / "cov.json"
        r = subprocess.run([PY, "scripts/coverage.py", str(tmp / "bank.json"),
                            str(tmp / "inv.json"), str(tmp / "val.json"),
                            "--out", str(cov), "--blind", str(tmp / "blind.json")],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        covd = json.loads(cov.read_text(encoding="utf-8"))
        self.assertTrue(covd.get("blind_filtered"))
        self.assertEqual(covd["per_ku"]["KU-1"]["primary_ids"], ["Q-A"])

    def test_no_blind_report_no_filtering(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="perfblind2_"))
        self._mini(tmp)
        cov = tmp / "cov.json"
        r = subprocess.run([PY, "scripts/coverage.py", str(tmp / "bank.json"),
                            str(tmp / "inv.json"), str(tmp / "val.json"),
                            "--out", str(cov)],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        covd = json.loads(cov.read_text(encoding="utf-8"))
        self.assertFalse(covd.get("blind_filtered"))
        self.assertEqual(sorted(covd["per_ku"]["KU-1"]["primary_ids"]), ["Q-A", "Q-B"])

    def test_mismatched_ids_helper(self):
        from review_batch import mismatched_ids
        self.assertEqual(mismatched_ids({"results": [
            {"id": "Q-A", "match": True}, {"id": "Q-B", "match": False}]}), ["Q-B"])


class TestBoundedParallel(unittest.TestCase):
    def test_max_workers_bounded_and_errors_propagate(self):
        import threading
        import time
        sys.path.insert(0, str(SCRIPTS))
        import pipeline as pipemod
        active = 0
        peak = 0
        lock = threading.Lock()

        def job():
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.2)
                return 0
            finally:
                with lock:
                    active -= 1

        def boom():
            raise RuntimeError("simulated stage failure")

        jobs = {"j%d" % i: job for i in range(6)}
        jobs["bad"] = boom
        res = pipemod.run_parallel(jobs, max_workers=3)
        self.assertEqual(res["bad"], 1)
        for i in range(6):
            self.assertEqual(res["j%d" % i], 0)
        self.assertLessEqual(peak, 3)
        self.assertGreater(peak, 1)


class TestBatchProgressLedger(unittest.TestCase):
    def test_interrupt_resumes_pending_only(self):
        from cache import (progress_init, progress_mark_done, progress_pending,
                           load_progress, save_progress)
        tmp = Path(tempfile.mkdtemp(prefix="perfprog_"))
        p = progress_init(["C-1", "C-2", "C-3", "C-4", "C-5"])
        progress_mark_done(p, "C-1")
        progress_mark_done(p, "C-2")
        save_progress(str(tmp / "batch_progress.json"), p)
        # simulate restart: reload and compute pending
        resumed = load_progress(str(tmp / "batch_progress.json"),
                                ["C-1", "C-2", "C-3", "C-4", "C-5"])
        self.assertEqual(progress_pending(resumed), ["C-3", "C-4", "C-5"])
        # double-marking is idempotent
        progress_mark_done(resumed, "C-3")
        progress_mark_done(resumed, "C-3")
        self.assertEqual(progress_pending(resumed), ["C-4", "C-5"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
