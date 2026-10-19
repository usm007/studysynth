"""Reproducible Opt-in Pipeline & Algorithmic Benchmark.

Measures:
1. Duplicate detection and uniqueness evaluation scalability on banks of 100, 500, 1000, and 2000 questions.
2. Cold vs Warm pipeline execution, stage timings, and cache reuse.
3. Compares with baseline_bench_results.json if available to report speedup multipliers.
"""
import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = sys.executable

sys.path.insert(0, str(ROOT / "scripts"))
import dedupe
import lib_common
import quality


TOPICS = [
    ("Polity", "Which constitutional amendment act introduced provisions regarding", "amendment", "Parliament", "President", "Judiciary"),
    ("History", "Who among the following ancient rulers patronized the academy at", "dynasty", "inscription", "chronicle", "monument"),
    ("Geography", "Which of the following tributaries originates in the northern plateau of", "basin", "watershed", "estuary", "plateau"),
    ("Economy", "What is the statutory liquidity ratio requirement determined by", "reserves", "inflation", "monetary", "fiscal"),
    ("Environment", "Which biosphere reserve in the Western Ghats is famous for protecting", "endemic", "ecosystem", "canopy", "sanctuary"),
    ("Science", "What physical phenomenon governs the propagation of coherent light through", "refraction", "diffraction", "dispersion", "polarization"),
    ("Culture", "Which classical dance form originated in the temple traditions of", "choreography", "costume", "repertoire", "recital")
]

PURPOSES = [
    "direct_recall", "conceptual_understanding", "distinction",
    "confusable_fact", "statement_evaluation"
]


def make_synthetic_bank(n, seed=42):
    import random
    random.seed(seed)
    questions = []
    for i in range(n):
        qid = f"Q-{i:04d}"
        prim_ku = f"KU-{i:04d}"
        purpose = PURPOSES[i % len(PURPOSES)]
        top = TOPICS[i % len(TOPICS)]

        if i > 0 and i % 25 == 5:
            prev = questions[i - 1]
            q = copy.deepcopy(prev)
            q["id"] = qid
        elif i > 0 and i % 25 == 10:
            prev = questions[i - 1]
            q = copy.deepcopy(prev)
            q["id"] = qid
            q["stem"] = prev["stem"] + " in the territory"
        elif i > 0 and i % 25 == 15 and purpose == "statement_evaluation":
            prev = questions[i - 1]
            q = copy.deepcopy(prev)
            q["id"] = qid
        elif i > 1 and i % 25 == 20:
            prev = questions[i - 2]
            q = copy.deepcopy(prev)
            q["id"] = qid
            q["stem"] = f"Regarding {top[1]} district_{i} province_{i} under {prev['id']}?"
        else:
            is_stmt = (purpose == "statement_evaluation")
            stmts = []
            if is_stmt:
                stmts = [
                    {"text": f"Statement 1 regarding {top[2]}_{i} authority was created in year 19{i % 80 + 10}.", "truth_value": True, "ku_basis": prim_ku},
                    {"text": f"Statement 2 regarding {top[3]}_{i} authority was repealed.", "truth_value": False, "ku_basis": prim_ku, "alteration": "scope_change", "alteration_type": "scope_change"}
                ]
            q = {
                "id": qid,
                "type": "statement_based" if is_stmt else "factual_mcq",
                "purpose": purpose,
                "stem": f"{top[1]} district_{i} province_{i} established in epoch_{i}?",
                "options": [
                    {"key": "A", "text": f"Statutory {top[2]}_{i} approved by committee_{i}", "is_correct": True, "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": prim_ku},
                    {"key": "B", "text": f"Autonomous {top[3]}_{i} defined by commission_{i}", "is_correct": False, "distractor_origin": "source_ku", "confusion_type": "wrong_category", "ku_ref": prim_ku, "distractor_purpose": "wrong_category"},
                    {"key": "C", "text": f"Auxiliary {top[4]}_{i} designated in gazette_{i}", "is_correct": False, "distractor_origin": "source_ku", "confusion_type": "wrong_entity", "ku_ref": prim_ku, "distractor_purpose": "wrong_entity"},
                    {"key": "D", "text": f"Provisional {top[5]}_{i} referenced in treaty_{i}", "is_correct": False, "distractor_origin": "source_ku", "confusion_type": "scope_error", "ku_ref": prim_ku, "distractor_purpose": "scope_error"},
                ],
                "answer": "A",
                "difficulty": "medium",
                "cognitive_level": "recall",
                "origin": "source",
                "statements": stmts,
                "knowledge_units": [{"ku_id": prim_ku, "role": "primary"}],
                "explanation": f"Pedagogical explanation for question {i} regarding {top[0]} concepts.",
                "source": [{"page": 1, "section_path": top[0], "block_id": f"B-{i:04d}", "char_start": 0, "char_end": 50}]
            }
        questions.append(q)
    return questions


def benchmark_algorithms(sizes=(100, 500, 1000, 2000)):
    """Benchmark deduplication and uniqueness evaluation across bank sizes."""
    print("=" * 70)
    print("ALGORITHMIC BENCHMARK: Deduplication & Quality Uniqueness")
    print("=" * 70)

    baseline_data = {}
    base_file = ROOT / "baseline_bench_results.json"
    if base_file.is_file():
        try:
            baseline_data = lib_common.load_json(str(base_file))
        except Exception:
            baseline_data = {}

    results = {}
    for n in sizes:
        qs = make_synthetic_bank(n)

        # 1. Dedupe benchmark
        t0 = time.perf_counter()
        dups, diversity = dedupe.detect_duplicates(qs, threshold=0.85)
        dt_dedupe = time.perf_counter() - t0

        # 2. Uniqueness benchmark
        t0 = time.perf_counter()
        seen = []
        u_results = []
        # Precompute bank representations for the whole bank
        repr_cache = {id(q): quality.prepare_uniqueness_repr(q) for q in qs}
        for q in qs:
            u_res = quality.evaluate_uniqueness(q, seen, threshold=0.85, repr_cache=repr_cache)
            u_results.append(u_res)
            seen.append(q)
        dt_unique = time.perf_counter() - t0

        total_dt = dt_dedupe + dt_unique
        results[str(n)] = {
            "questions": n,
            "dedupe_s": round(dt_dedupe, 4),
            "uniqueness_s": round(dt_unique, 4),
            "total_s": round(total_dt, 4),
            "redundant_pairs": len(dups),
            "valuable_diversity": len(diversity),
        }

        base_n = baseline_data.get(str(n))
        speedup_str = ""
        if base_n and "total_s" in base_n and base_n["total_s"] > 0:
            speedup = base_n["total_s"] / total_dt
            speedup_str = " (Speedup vs Baseline: %.2fx)" % speedup

        print("N=%-5d | Dedupe: %7.4fs | Uniqueness: %7.4fs | Total: %7.4fs%s" % (
            n, dt_dedupe, dt_unique, total_dt, speedup_str
        ))
    print()
    return results


def benchmark_pipeline_representative():
    """Benchmark the 5 required scenarios on the representative long-document fixture."""
    print("=" * 70)
    print("REPRESENTATIVE END-TO-END PIPELINE BENCHMARK (Long-Document Fixture)")
    print("=" * 70)

    fix_dir = ROOT / "tests" / "fixtures" / "longdoc"
    source_file = fix_dir / "longdoc_source.md"
    profile_file = ROOT / "profiles" / "APSC_PRELIMS.json"
    config_file = ROOT / "config.default.json"
    inventory_file = fix_dir / "inventory.json"
    bank_file = fix_dir / "question_bank.json"
    ignored_file = fix_dir / "ignored_anchors.json"
    diff_file = fix_dir / "inventory_diff.json"

    if not source_file.is_file():
        print("Long-doc fixture not found: %s" % source_file)
        return None

    source_size_bytes = source_file.stat().st_size
    inv_data = lib_common.load_json(str(inventory_file))
    bank_data = lib_common.load_json(str(bank_file))
    ku_count = len(inv_data.get("units", []))
    q_count = len(bank_data.get("questions", []))

    import platform
    env_info = {
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "machine": platform.machine(),
        "processor": platform.processor(),
    }

    scenarios = {}

    with tempfile.TemporaryDirectory(prefix="bench_pipeline_") as tmp:
        build_dir = Path(tmp)
        run_id = "longdoc_bench"

        base_cmd = [
            PY, "scripts/pipeline.py",
            "--source", str(source_file),
            "--run-id", run_id,
            "--profile", str(profile_file),
            "--config", str(config_file),
            "--build-dir", str(build_dir),
            "--inventory", str(inventory_file),
            "--bank", str(bank_file),
            "--ignored", str(ignored_file),
            "--diff", str(diff_file),
        ]

        def run_scenario(name, extra_args=None):
            cmd = base_cmd + (extra_args or [])
            t0 = time.perf_counter()
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            wall_time = time.perf_counter() - t0
            if r.returncode != 0:
                print(f"Scenario '{name}' failed (rc={r.returncode}):\n{r.stdout}\n{r.stderr}")
                return None, wall_time
            
            run_dir = build_dir / run_id
            metrics = lib_common.load_json(str(run_dir / "run_metrics.json"))
            state = lib_common.load_json(str(run_dir / "pipeline_state.json"))
            gate = lib_common.load_json(str(run_dir / "gate.json")) if (run_dir / "gate.json").is_file() else {}
            quality_rep = lib_common.load_json(str(run_dir / "quality_report.json")) if (run_dir / "quality_report.json").is_file() else {}
            struct = lib_common.load_json(str(run_dir / "document_structure.json")) if (run_dir / "document_structure.json").is_file() else {}
            evidence = lib_common.load_json(str(run_dir / "verification_evidence.json")) if (run_dir / "verification_evidence.json").is_file() else {}
            trace = run_dir / "llm_trace.jsonl"
            trace_summary = None
            if trace.is_file():
                import llm_trace
                trace_summary = llm_trace.summarize_llm_trace(str(trace))

            stages = state.get("stages", {})
            skipped = [s for s, d in stages.items() if d.get("status") == "skipped"]
            rerun = [s for s, d in stages.items() if d.get("status") != "skipped"]

            q_accepted = quality_rep.get("accepted_count", 0)
            q_rejected = quality_rep.get("rejected_count", 0)

            return {
                "wall_time_s": round(wall_time, 4),
                "deterministic_pipeline_s": round(metrics.get("total_duration_s", wall_time), 4),
                "external_llm_s": 0.0,
                "stage_durations": metrics.get("stage_durations", {}),
                "cache_hits": metrics.get("cache", {}).get("hits", 0),
                "cache_misses": metrics.get("cache", {}).get("misses", 0),
                "stages_skipped": skipped,
                "stages_rerun": rerun,
                "source_size_bytes": source_size_bytes,
                "extracted_blocks": len(struct.get("blocks", [])),
                "knowledge_units": ku_count,
                "questions_evaluated": q_count,
                "questions_accepted": q_accepted,
                "questions_rejected": q_rejected,
                "gapfill_rounds": 0,
                "gate_status": gate.get("status"),
                "verification_evidence": evidence,
                "llm_telemetry": trace_summary or {
                    "status": "unmeasured",
                    "reason": "external LLM provider orchestrator not invoked during deterministic offline fixture benchmark"
                }
            }, wall_time

        # 1. Cold cache
        print("\n[Scenario 1] Cold cache run (BALANCED mode)...")
        scen1, t_cold = run_scenario("1_cold_cache", ["--processing-mode", "BALANCED"])
        scenarios["1_cold_cache"] = scen1
        if scen1:
            print("  Wall-clock time: %.3fs | Cache misses: %d | Gate: %s" %
                  (scen1["wall_time_s"], scen1["cache_misses"], scen1["gate_status"]))

        # Snapshot cold audit output for substantive comparison
        cold_audit_path = build_dir / run_id / "audit_report.json"
        cold_audit_data = lib_common.load_json(str(cold_audit_path)) if cold_audit_path.is_file() else {}

        # 2. Warm cache with identical inputs
        print("\n[Scenario 2] Warm cache run with identical inputs...")
        scen2, t_warm = run_scenario("2_warm_cache_identical", ["--processing-mode", "BALANCED"])
        scenarios["2_warm_cache_identical"] = scen2
        if scen2:
            warm_audit_path = build_dir / run_id / "audit_report.json"
            warm_audit_data = lib_common.load_json(str(warm_audit_path)) if warm_audit_path.is_file() else {}
            substantive_parity = (cold_audit_data == warm_audit_data)
            speedup = scen1["wall_time_s"] / scen2["wall_time_s"] if scen2["wall_time_s"] > 0 else 1.0
            scen2["speedup_factor"] = round(speedup, 2)
            scen2["substantive_parity"] = substantive_parity
            print("  Wall-clock time: %.3fs | Cache hits: %d | Skipped: %d stages" %
                  (scen2["wall_time_s"], scen2["cache_hits"], len(scen2["stages_skipped"])))
            print("  Measured Speedup: %.2fx (Cold: %.3fs -> Warm: %.3fs) | Parity: %s" %
                  (speedup, scen1["wall_time_s"], scen2["wall_time_s"], substantive_parity))

        # 3. Warm cache after changing downstream question bank
        print("\n[Scenario 3] Warm cache after mutating question bank...")
        mod_bank = build_dir / "mod_bank.json"
        b_data = copy.deepcopy(bank_data)
        b_data["questions"][0]["stem"] = "Modified stem for benchmark downstream invalidation test."
        lib_common.save_json(str(mod_bank), b_data)
        scen3, _ = run_scenario("3_warm_cache_mutated_bank", [
            "--bank", str(mod_bank), "--processing-mode", "BALANCED"
        ])
        scenarios["3_warm_cache_mutated_bank"] = scen3
        if scen3:
            print("  Wall-clock time: %.3fs | Skipped: %s | Rerun: %s" %
                  (scen3["wall_time_s"], ", ".join(scen3["stages_skipped"]), ", ".join(scen3["stages_rerun"])))

        # 4. Warm cache after changing config
        print("\n[Scenario 4] Warm cache after changing quality/audit configuration...")
        mod_cfg = build_dir / "mod_config.json"
        c_data = copy.deepcopy(lib_common.load_json(str(config_file)))
        c_data["anchor_recall_threshold"] = 99.0
        lib_common.save_json(str(mod_cfg), c_data)
        scen4, _ = run_scenario("4_warm_cache_mutated_config", [
            "--config", str(mod_cfg), "--processing-mode", "BALANCED"
        ])
        scenarios["4_warm_cache_mutated_config"] = scen4
        if scen4:
            print("  Wall-clock time: %.3fs | Skipped: %s | Rerun: %s" %
                  (scen4["wall_time_s"], ", ".join(scen4["stages_skipped"]), ", ".join(scen4["stages_rerun"])))

        # 5. Balanced vs Comprehensive Processing Modes
        print("\n[Scenario 5] Comprehensive mode execution...")
        scen5, _ = run_scenario("5_comprehensive_mode", ["--processing-mode", "COMPREHENSIVE"])
        scenarios["5_comprehensive_mode"] = scen5
        if scen5:
            print("  Wall-clock time: %.3fs | Gate: %s | Sweep verified: %s" %
                  (scen5["wall_time_s"], scen5["gate_status"],
                   scen5.get("verification_evidence", {}).get("second_pass_sweep")))

    return {
        "environment": env_info,
        "scenarios": scenarios,
    }


def main():
    parser = argparse.ArgumentParser(description="DocToQuiz Pipeline & Algorithmic Benchmark")
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 500, 1000, 2000],
                        help="Question bank sizes for algorithmic benchmark")
    parser.add_argument("--skip-pipeline", action="store_true", help="Skip pipeline representative benchmark")
    parser.add_argument("--skip-algo", action="store_true", help="Skip algorithmic scalability benchmark")
    parser.add_argument("--out", default=None, help="Output JSON file for benchmark results")
    args = parser.parse_args()

    algo_results = None
    if not args.skip_algo:
        algo_results = benchmark_algorithms(sizes=args.sizes)

    pipe_results = None
    if not args.skip_pipeline:
        pipe_results = benchmark_pipeline_representative()

    combined = {
        "timestamp": time.time(),
        "algorithmic_benchmarks": algo_results,
        "representative_pipeline_benchmark": pipe_results,
    }

    if args.out:
        lib_common.save_json(args.out, combined)
        print("Benchmark results saved to %s" % args.out)

    return 0


if __name__ == "__main__":
    sys.exit(main())

