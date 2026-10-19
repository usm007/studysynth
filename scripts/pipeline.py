import argparse
import concurrent.futures
import importlib.util
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, ensure_dir, run_main
from cache import sha_file, sha_file_full, sha_obj, load_manifest, save_manifest, atomic_save_json
from llm_trace import summarize_llm_trace

HERE = os.path.dirname(os.path.abspath(__file__))
ALL_STAGES = (
    "ingest", "anchors", "check", "validate", "quality", "coverage", "dedupe",
    "audit", "gate", "report", "package", "build_web", "build_pdf", "delivery"
)
STAGES = ("ingest", "anchors", "check", "validate", "quality", "coverage", "dedupe", "audit", "gate", "report")
# redo invalidation: stage -> itself + descendants
DESCENDANTS = {
    "ingest": ALL_STAGES,
    "anchors": ("anchors", "check", "audit", "gate", "report", "package", "build_web", "build_pdf", "delivery"),
    "check": ("check", "audit", "gate", "report", "package", "build_web", "build_pdf", "delivery"),
    "validate": ("validate", "coverage", "audit", "gate", "report", "package", "build_web", "build_pdf", "delivery"),
    "quality": ("quality", "coverage", "audit", "gate", "report", "package", "build_web", "build_pdf", "delivery"),
    "dedupe": ("dedupe", "coverage", "audit", "gate", "report", "package", "build_web", "build_pdf", "delivery"),
    "coverage": ("coverage", "audit", "gate", "report", "package", "build_web", "build_pdf", "delivery"),
    "audit": ("audit", "gate", "report", "package", "build_web", "build_pdf", "delivery"),
    "gate": ("gate", "report", "package", "build_web", "build_pdf", "delivery"),
    "report": ("report",),
    "package": ("package", "build_web", "build_pdf", "delivery"),
    "build_web": ("build_web",),
    "build_pdf": ("build_pdf",),
    "delivery": ("delivery",),
    "all": ALL_STAGES,
}


def mod(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_stage(fn, argv):
    try:
        res = fn(argv)
        return int(res) if isinstance(res, (int, bool)) else (0 if res is None else 1)
    except SystemExit as e:
        if isinstance(e.code, int):
            return e.code
        if e.code:
            print(str(e.code), file=sys.stderr)
            return 1
        return 0
    except Exception as e:
        print("stage exception: %s" % e, file=sys.stderr)
        return 1


def run_parallel(jobs, max_workers=3):
    """Run {name: zero-arg fn} concurrently with bounded workers.

    Returns {name: return-code}. A raising job is captured as rc=1 (with a
    stderr note) so sibling jobs still complete and the caller can mark every
    stage reliably instead of losing results to a traceback.
    """
    results = {}
    if not jobs:
        return results
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(jobs))) as ex:
        futs = {ex.submit(fn): k for k, fn in jobs.items()}
        for fut in concurrent.futures.as_completed(futs):
            k = futs[fut]
            try:
                results[k] = fut.result()
            except Exception as e:
                print("parallel job %s raised: %s" % (k, e), file=sys.stderr)
                results[k] = 1
    return results


def schema_each(path, key, schema_path, label):
    vs = mod("validate_schema")
    try:
        doc = load_json(path)
        sch = load_json(schema_path)
    except Exception as e:
        print("schema %s: load failed: %s" % (label, e))
        return 1
    items = doc.get(key) if isinstance(doc, dict) else doc
    errs = []
    for i, it in enumerate(items or []):
        vs.check(it, sch, "%s[%d]" % (label, i), errs)
    if errs:
        print("schema %s: FAIL %d errors" % (label, len(errs)))
        for e in errs[:10]:
            print("  " + e)
        return 1
    print("schema %s: OK %d items" % (label, len(items or [])))
    return 0


def _file_sha(p):
    return sha_file(p) if p and os.path.isfile(p) else None


def compute_stage_fingerprint(stage, R, F, a, cfg, extra=None):
    """Compute deterministic stage fingerprint given stage, environment and inputs."""
    schdir = os.path.join(os.path.dirname(HERE), "schemas")
    lib_common_sha = _file_sha(os.path.join(HERE, "lib_common.py"))
    anchors_sha = _file_sha(os.path.join(HERE, "anchors.py"))
    naming_sha = _file_sha(os.path.join(HERE, "naming.py"))
    mode = getattr(a, "mode", None) or cfg.get("fidelity_mode") or "SOURCE_BOUND"
    proc_mode = (getattr(a, "processing_mode", None) or cfg.get("processing_mode") or "BALANCED").upper()
    pkg_dest = os.path.join(R, "quiz_package.json")

    fp = {"stage": stage}
    if extra:
        fp["extra"] = extra
    if stage == "ingest":
        fp["source"] = _file_sha(getattr(a, "source", None))
        fp["code"] = _file_sha(os.path.join(HERE, "ingest.py"))
        fp["helpers"] = [lib_common_sha]
    elif stage == "anchors":
        fp["struct"] = _file_sha(F.get("struct"))
        fp["code"] = anchors_sha
        fp["helpers"] = [lib_common_sha]
    elif stage == "check":
        fp["inventory"] = _file_sha(getattr(a, "inventory", None))
        fp["struct"] = _file_sha(F.get("struct"))
        fp["anchors"] = _file_sha(F.get("anchors"))
        fp["ignored"] = _file_sha(getattr(a, "ignored", None))
        fp["diff"] = _file_sha(getattr(a, "diff", None))
        fp["threshold"] = cfg.get("anchor_recall_threshold", 100)
        fp["code"] = _file_sha(os.path.join(HERE, "inventory_check.py"))
        fp["helpers"] = [anchors_sha, lib_common_sha]
    elif stage == "validate":
        fp["bank"] = _file_sha(getattr(a, "bank", None))
        fp["inventory"] = _file_sha(getattr(a, "inventory", None))
        fp["struct"] = _file_sha(F.get("struct"))
        fp["profile"] = _file_sha(getattr(a, "profile", None))
        fp["fidelity_mode"] = mode
        fp["config"] = {
            "options_per_question": cfg.get("options_per_question", 4),
            "fidelity_mode": cfg.get("fidelity_mode", "SOURCE_BOUND"),
        }
        fp["schema"] = _file_sha(os.path.join(schdir, "question.schema.json"))
        fp["code"] = _file_sha(os.path.join(HERE, "validate_questions.py"))
        fp["helpers"] = [lib_common_sha, _file_sha(os.path.join(HERE, "validate_schema.py"))]
    elif stage == "quality":
        fp["bank"] = _file_sha(getattr(a, "bank", None))
        fp["inventory"] = _file_sha(getattr(a, "inventory", None))
        fp["struct"] = _file_sha(F.get("struct"))
        fp["profile"] = _file_sha(getattr(a, "profile", None))
        fp["fidelity_mode"] = mode
        fp["processing_mode"] = proc_mode
        fp["config"] = {
            "duplicate_threshold": cfg.get("duplicate_threshold", 0.85),
            "options_per_question": cfg.get("options_per_question", 4),
            "fidelity_mode": cfg.get("fidelity_mode", "SOURCE_BOUND"),
        }
        fp["code"] = _file_sha(os.path.join(HERE, "quality.py"))
        fp["helpers"] = [lib_common_sha]
    elif stage == "dedupe":
        fp["bank"] = _file_sha(getattr(a, "bank", None))
        fp["duplicate_threshold"] = cfg.get("duplicate_threshold", 0.85)
        fp["code"] = _file_sha(os.path.join(HERE, "dedupe.py"))
        fp["helpers"] = [lib_common_sha]
    elif stage == "coverage":
        fp["bank"] = _file_sha(getattr(a, "bank", None))
        fp["inventory"] = _file_sha(getattr(a, "inventory", None))
        fp["validation"] = _file_sha(F.get("validation"))
        fp["quality"] = _file_sha(F.get("quality"))
        fp["dedupe"] = _file_sha(F.get("dedupe"))
        blind_p = os.path.join(R, "blind_review.json")
        fp["blind"] = _file_sha(blind_p) if os.path.isfile(blind_p) else None
        fp["config"] = {
            "tier_targets": cfg.get("tier_targets"),
            "per_ku_cap": cfg.get("per_ku_cap"),
            "section_share_cap": cfg.get("section_share_cap"),
        }
        fp["code"] = _file_sha(os.path.join(HERE, "coverage.py"))
        fp["helpers"] = [lib_common_sha]
    elif stage == "audit":
        fp["inventory"] = _file_sha(getattr(a, "inventory", None))
        fp["coverage"] = _file_sha(F.get("coverage"))
        fp["validation"] = _file_sha(F.get("validation"))
        fp["anchors"] = _file_sha(F.get("anchors"))
        fp["struct"] = _file_sha(F.get("struct"))
        fp["quality"] = _file_sha(F.get("quality"))
        fp["bank"] = _file_sha(getattr(a, "bank", None))
        fp["profile"] = _file_sha(getattr(a, "profile", None))
        fp["ignored"] = _file_sha(getattr(a, "ignored", None))
        fp["diff"] = _file_sha(getattr(a, "diff", None))
        fp["config"] = {
            "anchor_recall_threshold": cfg.get("anchor_recall_threshold", 100),
            "tier_targets": cfg.get("tier_targets"),
            "section_share_cap": cfg.get("section_share_cap"),
            "duplicate_threshold": cfg.get("duplicate_threshold"),
        }
        fp["code"] = _file_sha(os.path.join(HERE, "audit.py"))
        fp["helpers"] = [anchors_sha, lib_common_sha]
    elif stage == "gate":
        fp["audit"] = _file_sha(F.get("audit"))
        fp["processing_mode"] = proc_mode
        fp["threshold"] = cfg.get("anchor_recall_threshold", 100)
        fp["gate_thresholds"] = cfg.get("gate_thresholds")
        ev_p = os.path.join(R, "verification_evidence.json")
        fp["evidence"] = _file_sha(ev_p) if os.path.isfile(ev_p) else None
        fp["code"] = _file_sha(os.path.join(HERE, "gate.py"))
        fp["helpers"] = [lib_common_sha]
    elif stage == "report":
        fp["audit"] = _file_sha(F.get("audit"))
        fp["gate"] = _file_sha(F.get("gate"))
        fp["bank"] = _file_sha(getattr(a, "bank", None))
        fp["code"] = _file_sha(os.path.join(HERE, "report.py"))
        fp["helpers"] = [lib_common_sha]
    elif stage == "package":
        fp["bank"] = _file_sha(getattr(a, "bank", None))
        fp["audit"] = _file_sha(F.get("audit"))
        fp["gate"] = _file_sha(F.get("gate"))
        fp["profile"] = _file_sha(getattr(a, "profile", None))
        fp["inventory"] = _file_sha(getattr(a, "inventory", None))
        fp["quality"] = _file_sha(F.get("quality"))
        fp["schema"] = _file_sha(os.path.join(schdir, "quiz-package.schema.json"))
        fp["code"] = _file_sha(os.path.join(HERE, "package.py"))
        fp["helpers"] = [naming_sha, lib_common_sha]
    elif stage == "build_web":
        fp["package"] = _file_sha(pkg_dest)
        fp["source"] = _file_sha(getattr(a, "source", None))
        fp["template"] = _file_sha(os.path.join(os.path.dirname(HERE), "templates", "web", "app.template.html"))
        fp["code"] = _file_sha(os.path.join(HERE, "build_web.py"))
        fp["helpers"] = [naming_sha, _file_sha(os.path.join(HERE, "dashboard.py")), lib_common_sha]
    elif stage == "build_pdf":
        fp["package"] = _file_sha(pkg_dest)
        fp["profile"] = _file_sha(getattr(a, "profile", None))
        fp["code"] = _file_sha(os.path.join(HERE, "build_pdf.py"))
        fp["helpers"] = [_file_sha(os.path.join(HERE, "check_pdf.py")), naming_sha, lib_common_sha]
    elif stage == "delivery":
        fp["package"] = _file_sha(pkg_dest)
        fp["profile"] = _file_sha(getattr(a, "profile", None))
        fp["delivery_mode"] = getattr(a, "delivery_mode", "individual")
        fp["code"] = _file_sha(os.path.join(HERE, "package_delivery.py"))
        fp["helpers"] = [naming_sha, lib_common_sha]
    return sha_obj(fp)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--count", type=int, default=None)
    ap.add_argument("--build-dir", default="build")
    ap.add_argument("--redo", default=None)
    ap.add_argument("--mode", default=None)
    ap.add_argument("--processing-mode", choices=["QUICK", "BALANCED", "COMPREHENSIVE"], default=None,
                    help="Pipeline processing mode: QUICK, BALANCED (default), or COMPREHENSIVE")
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--bank", default=None)
    ap.add_argument("--ignored", default=None)
    ap.add_argument("--diff", default=None)
    ap.add_argument("--package", action="store_true", help="Assemble quiz_package.json")
    ap.add_argument("--web", action="store_true", help="Build standalone HTML quiz (implies --package)")
    ap.add_argument("--pdf", action="store_true", help="Build print-ready PDFs (implies --package)")
    ap.add_argument("--full", action="store_true", help="Run full pipeline including package, web, and pdf")
    ap.add_argument("--deliver", action="store_true", help="Generate final user delivery package (PDF + HTML only)")
    ap.add_argument("--delivery-dir", default=None, help="Directory for final user delivery deliverables (default: output)")
    ap.add_argument("--delivery-mode", choices=["individual", "unified", "both"], default="individual", help="Delivery mode")
    ap.add_argument("--dashboard", default=None, help="Path to master index.html dashboard")
    ap.add_argument("--shortcut", action="store_true", help="Generate OS desktop shortcut to master dashboard")
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    if not os.path.isfile(a.source):
        print("error: source not found: %s" % a.source, file=sys.stderr)
        return 1
    for p, n in ((a.profile, "profile"), (a.config, "config")):
        if not os.path.isfile(p):
            print("error: %s not found: %s" % (n, p), file=sys.stderr)
            return 1
    if a.inventory and not os.path.isfile(a.inventory):
        print("error: inventory not found: %s" % a.inventory, file=sys.stderr)
        return 1
    if a.bank and not os.path.isfile(a.bank):
        print("error: bank not found: %s" % a.bank, file=sys.stderr)
        return 1
    R = a.run_id if os.path.basename(os.path.normpath(a.build_dir)) == a.run_id else os.path.join(a.build_dir, a.run_id)
    ensure_dir(R)
    pkg_dest = os.path.join(R, "quiz_package.json")
    cfg = load_json(a.config)
    mode = a.mode or cfg.get("fidelity_mode", "SOURCE_BOUND")
    proc_mode = str(a.processing_mode or cfg.get("processing_mode") or "BALANCED").upper()
    metrics = {"run_id": a.run_id, "processing_mode": proc_mode, "fidelity_mode": mode,
               "stages": {}, "model_calls": "unavailable (orchestrator cannot observe LLM layer)",
               "cache": {"hits": 0, "misses": 0}}
    F = {"struct": os.path.join(R, "document_structure.json"),
         "anchors": os.path.join(R, "anchors.json"),
         "check": os.path.join(R, "inventory_check.json"),
         "validation": os.path.join(R, "validation_results.json"),
         "quality": os.path.join(R, "quality_report.json"),
         "coverage": os.path.join(R, "coverage_matrix.json"),
         "dedupe": os.path.join(R, "dedupe_report.json"),
         "audit": os.path.join(R, "audit_report.json"),
         "gate": os.path.join(R, "gate.json")}
    manifest_path = os.path.join(R, "artifact_manifest.json")
    metrics_path = os.path.join(R, "run_metrics.json")
    repair_path = os.path.join(R, "repair_queue.json")
    manifest = load_manifest(manifest_path)
    sp = os.path.join(R, "pipeline_state.json")
    state = load_json(sp) if os.path.isfile(sp) else {"run_id": a.run_id, "stages": {}}
    redo = (a.redo or "").lower()
    invalidated = set(DESCENDANTS.get(redo, ())) if redo else set()
    metrics["stage_invalidations"] = sorted(list(invalidated))

    schdir = os.path.join(os.path.dirname(HERE), "schemas")
    lib_common_sha = _file_sha(os.path.join(HERE, "lib_common.py"))
    anchors_sha = _file_sha(os.path.join(HERE, "anchors.py"))
    naming_sha = _file_sha(os.path.join(HERE, "naming.py"))

    def stage_fingerprint(stage, extra=None):
        return compute_stage_fingerprint(stage, R, F, a, cfg, extra=extra)

    def fresh(stage, outs, extra=None):
        """Dependency-aware reuse: all outputs exist AND stage-specific fingerprint matches."""
        if stage in invalidated:
            return False
        if not all(os.path.isfile(o) for o in outs):
            return False
        fp = stage_fingerprint(stage, extra)
        if manifest.get(stage, {}).get("fingerprint") != fp:
            return False
        outs_ok = all(manifest.get(stage, {}).get("outputs", {}).get(o) == _file_sha(o) for o in outs)
        return outs_ok

    def mark(stage, status, detail=""):
        state["stages"][stage] = {"status": status, "detail": detail}
        save_json(sp, state)

    def record_manifest(stage, outs, extra=None):
        manifest[stage] = {"fingerprint": stage_fingerprint(stage, extra),
                           "outputs": {o: _file_sha(o) for o in outs}}
        save_manifest(manifest_path, manifest)

    def timed(stage, fn):
        s = time.monotonic()
        rc = fn()
        dt = time.monotonic() - s
        metrics["stages"][stage] = {"duration_s": round(dt, 4), "rc": rc}
        return rc

    if fresh("ingest", [F["struct"]]):
        mark("ingest", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1
    else:
        metrics["cache"]["misses"] += 1
        rc = timed("ingest", lambda: run_stage(mod("ingest").main, [a.source, "--out", R, "--run-id", a.run_id]))
        mark("ingest", "ok" if rc == 0 else "failed")
        if rc:
            save_manifest(manifest_path, manifest)
            save_json(metrics_path, metrics)
            return rc
        record_manifest("ingest", [F["struct"]])
    if fresh("anchors", [F["anchors"]]):
        mark("anchors", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1
    else:
        metrics["cache"]["misses"] += 1
        rc = timed("anchors", lambda: run_stage(mod("anchors").main, [F["struct"], "--out", F["anchors"]]))
        mark("anchors", "ok" if rc == 0 else "failed")
        if rc:
            save_json(metrics_path, metrics)
            return rc
        record_manifest("anchors", [F["anchors"]])
    schdir = os.path.join(os.path.dirname(HERE), "schemas")
    sstruct = os.path.join(schdir, "document_structure.schema.json")
    if os.path.isfile(sstruct):
        rc = run_stage(mod("validate_schema").main, [F["struct"], "--schema", sstruct])
        mark("validate_struct", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    else:
        mark("validate_struct", "skipped", "no schema file")
    sku = os.path.join(schdir, "knowledge-unit.schema.json")
    sq = os.path.join(schdir, "question.schema.json")
    bank_schema_ok = True
    if not a.inventory:
        mark("check", "pending", "no --inventory (LLM step)")
        mark("validate", "pending", "needs inventory")
        mark("coverage", "pending", "needs inventory/bank")
        mark("dedupe", "pending" if not a.bank else "ready", "")
        if a.bank and fresh("dedupe", [F["dedupe"]]):
            mark("dedupe", "skipped", "cache hit")
        elif a.bank:
            rc = timed("dedupe", lambda: run_stage(mod("dedupe").main, [a.bank, "--threshold", str(cfg.get("duplicate_threshold", 0.85)), "--out", F["dedupe"]]))
            mark("dedupe", "ok" if rc == 0 else "failed")
            if rc == 0:
                record_manifest("dedupe", [F["dedupe"]])
        mark("audit", "pending", "needs inventory")
        mark("gate", "pending", "needs audit")
        mark("report", "pending", "needs audit/gate")

        if (a.deliver or a.delivery_dir) and os.path.isfile(pkg_dest):
            deliv_dir = a.delivery_dir or "output"
            rc = run_stage(mod("package_delivery").main, [
                pkg_dest,
                "--out-dir", deliv_dir,
                "--mode", a.delivery_mode,
                "--profile", a.profile,
            ])
            mark("delivery", "ok" if rc == 0 else "failed")
            if rc:
                save_json(sp, state)
                return rc

        save_json(sp, state)
        save_json(metrics_path, metrics)
        print("pipeline %s: deterministic stages done; inventory/bank pending (LLM steps)" % a.run_id)
        return 0
    if fresh("check", [F["check"]]):
        mark("check", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1
    else:
        metrics["cache"]["misses"] += 1
        args = [a.inventory, F["struct"], "--anchors", F["anchors"], "--config", a.config, "--out", F["check"]]
        if a.ignored:
            args += ["--ignored", a.ignored]
        if a.diff:
            args += ["--diff", a.diff]
        rc = timed("check", lambda: run_stage(mod("inventory_check").main, args))
        mark("check", "ok" if rc == 0 else "failed")
        if rc:
            save_json(metrics_path, metrics)
            return rc
        record_manifest("check", [F["check"]])
    if os.path.isfile(sku):
        rc = schema_each(a.inventory, "units", sku, "knowledge-unit")
        mark("schema_inventory", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    else:
        mark("schema_inventory", "skipped", "no schema file")
    if not a.bank:
        for s in ("validate", "coverage", "dedupe", "audit", "gate", "report"):
            mark(s, "pending", "no --bank (LLM step)")
        save_json(sp, state)
        save_json(metrics_path, metrics)
        print("pipeline %s: check done; question bank pending (LLM step)" % a.run_id)
        return 0
    # validate + quality + dedupe share inputs and no output files: run concurrently
    need_v = not fresh("validate", [F["validation"]])
    need_q = not fresh("quality", [F["quality"]])
    need_d = not fresh("dedupe", [F["dedupe"]])
    results = {}
    if not need_v:
        mark("validate", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1
    if not need_q:
        mark("quality", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1
    if not need_d:
        mark("dedupe", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1

    def do_validate():
        s = time.monotonic()
        rc = run_stage(mod("validate_questions").main, [a.bank, a.inventory, F["struct"], "--profile", a.profile, "--mode", mode, "--config", a.config, "--out", F["validation"]])
        metrics["stages"]["validate"] = {"duration_s": round(time.monotonic() - s, 4), "rc": rc}
        return rc

    def do_quality():
        s = time.monotonic()
        rc = run_stage(mod("quality").main, [a.bank, a.inventory, F["struct"], "--profile", a.profile, "--mode", mode, "--config", a.config, "--out", F["quality"]])
        metrics["stages"]["quality"] = {"duration_s": round(time.monotonic() - s, 4), "rc": rc}
        return rc

    def do_dedupe():
        s = time.monotonic()
        rc = run_stage(mod("dedupe").main, [a.bank, "--threshold", str(cfg.get("duplicate_threshold", 0.85)), "--out", F["dedupe"]])
        metrics["stages"]["dedupe"] = {"duration_s": round(time.monotonic() - s, 4), "rc": rc}
        return rc

    jobs = {}
    if need_v:
        jobs["validate"] = do_validate
    if need_q:
        jobs["quality"] = do_quality
    if need_d:
        jobs["dedupe"] = do_dedupe
    if jobs:
        results = run_parallel(jobs, max_workers=3)
        for k, rc in results.items():
            metrics["cache"]["misses"] += 1
        # validate: localized repair instead of abort. Persist per-question
        # results, build a bounded repair queue, and continue so valid
        # questions still reach audit/package. Exit code stays nonzero so a
        # partially rejected bank is never reported as success.
        if "validate" in results:
            rc = results["validate"]
            if rc == 0:
                mark("validate", "ok", "")
                record_manifest("validate", [F["validation"]])
            else:
                try:
                    vr = load_json(F["validation"])
                    rej = [r for r in vr.get("results", []) if r.get("status") == "rejected"]
                    max_retry = int(cfg.get("max_repair_retries", 2))
                    save_json(repair_path, {"max_retries": max_retry,
                                            "failed": [{"id": r["id"], "notes": r.get("notes", []),
                                                        "checks": r.get("checks", {})} for r in rej]})
                    mark("validate", "completed_with_rejections",
                         "%d rejected; repair queue -> %s (max_retries=%d)" % (len(rej), repair_path, max_retry))
                    print("pipeline %s: %d question(s) rejected; valid items continue to audit/package; repair queue has %d (max %d retries each)" % (a.run_id, len(rej), len(rej), max_retry))
                except Exception as e:
                    mark("validate", "completed_with_rejections", "results unreadable: %s" % e)
        if "quality" in results:
            rc = results["quality"]
            # quality.py returns 1 when rejections exist; that is signal, not crash
            mark("quality", "ok" if rc == 0 else "flagged",
                 "" if rc == 0 else "quality rejections present; excluded from coverage/package")
            try:
                record_manifest("quality", [F["quality"]])
            except Exception:
                pass
        if "dedupe" in results:
            rc = results["dedupe"]
            mark("dedupe", "ok" if rc == 0 else "failed")
            if rc:
                save_json(metrics_path, metrics)
                return rc
            record_manifest("dedupe", [F["dedupe"]])
    if os.path.isfile(sq):
        rc = schema_each(a.bank, "questions", sq, "question")
        mark("schema_bank", "ok" if rc == 0 else "failed")
        if rc:
            bank_schema_ok = False
            print("pipeline %s: bank schema errors; continuing with valid items" % a.run_id)
    else:
        mark("schema_bank", "skipped", "no schema file")

    valid_purposes = {"direct_recall", "conceptual_understanding", "distinction",
                      "confusable_fact", "elimination", "statement_evaluation",
                      "chronology", "classification", "cause_effect", "exception",
                      "association", "application", "integrated_concept"}
    new_engine = False
    try:
        _b = load_json(a.bank)
        _qs = _b.get("questions") if isinstance(_b, dict) else _b
        new_engine = any((q.get("purpose") or "") in valid_purposes for q in _qs)
    except Exception:
        new_engine = False
    metrics["coverage_new_engine"] = new_engine
    blind_path = os.path.join(R, "blind_review.json")
    if fresh("coverage", [F["coverage"]]):
        mark("coverage", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1
    else:
        metrics["cache"]["misses"] += 1
        cargs = [a.bank, a.inventory, F["validation"], "--out", F["coverage"], "--config", a.config]
        if new_engine:
            if os.path.isfile(F["quality"]):
                cargs += ["--quality", F["quality"]]
            if os.path.isfile(F["dedupe"]):
                cargs += ["--dedupe", F["dedupe"]]
            if os.path.isfile(blind_path):
                cargs += ["--blind", blind_path]
        else:
            print("pipeline %s: legacy bank (no explicit purposes); coverage uses validation-only credit" % a.run_id)
        rc = timed("coverage", lambda: run_stage(mod("coverage").main, cargs))
        mark("coverage", "ok" if rc == 0 else "failed")
        if rc:
            save_json(metrics_path, metrics)
            return rc
        record_manifest("coverage", [F["coverage"]])
    if fresh("audit", [F["audit"]]):
        mark("audit", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1
    else:
        metrics["cache"]["misses"] += 1
        args = [a.inventory, F["coverage"], F["validation"], F["anchors"], "--profile", a.profile, "--config", a.config, "--struct", F["struct"], "--quality", F["quality"], "--out", F["audit"]]
        if a.bank:
            args += ["--bank", a.bank]
        if a.ignored:
            args += ["--ignored", a.ignored]
        if a.diff:
            args += ["--diff", a.diff]
        rc = timed("audit", lambda: run_stage(mod("audit").main, args))
        mark("audit", "ok" if rc == 0 else "failed")
        if rc:
            save_json(metrics_path, metrics)
            return rc
        record_manifest("audit", [F["audit"]])
    if fresh("gate", [F["gate"]]):
        mark("gate", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1
    else:
        metrics["cache"]["misses"] += 1
        ev_path = os.path.join(R, "verification_evidence.json")
        ev_data = {
            "processing_mode": proc_mode,
            "source_sha": sha_file_full(a.source) if a.source and os.path.isfile(a.source) else None,
            "second_pass_sweep": (proc_mode == "COMPREHENSIVE"),
            "blind_review_completed": os.path.isfile(blind_path),
            "missing_reviews": False,
            "stages_completed": sorted(list(manifest.get("stages", {}).keys())),
        }
        atomic_save_json(ev_path, ev_data)
        rc = timed("gate", lambda: run_stage(mod("gate").main, [F["audit"], "--config", a.config, "--processing-mode", proc_mode, "--evidence", ev_path]))
        mark("gate", "ok" if rc == 0 else "failed")
        if rc:
            save_json(metrics_path, metrics)
            return rc
        record_manifest("gate", [F["gate"], ev_path])
    rc = timed("report", lambda: run_stage(mod("report").main, [F["audit"], F["gate"]] + ([a.bank] if a.bank else [])))
    mark("report", "ok" if rc == 0 else "failed")
    if a.count is not None:
        state["requested_count"] = a.count

    do_pkg = a.package or a.web or a.pdf or a.full or a.deliver or bool(a.delivery_dir)
    do_web = a.web or a.full
    do_pdf = a.pdf or a.full

    pkg_dest = os.path.join(R, "quiz_package.json")
    if do_pkg and a.bank and a.inventory:
        rc = timed("package", lambda: run_stage(mod("package").main, [
            a.bank, F["audit"], F["gate"],
            "--profile", a.profile,
            "--inventory", a.inventory,
            "--quality", F["quality"],
            "--out", pkg_dest
        ]))
        mark("package", "ok" if rc == 0 else "failed")
        if rc:
            save_json(sp, state)
            save_json(metrics_path, metrics)
            return rc

    # web + pdf share only the immutable package snapshot: run concurrently
    def run_web():
        import shutil
        from naming import parse_clean_title, generate_slug
        clean_title = parse_clean_title(a.source)
        slug_file = generate_slug(a.source)
        slug_dest = os.path.join(R, slug_file)
        html_dest = os.path.join(R, "quiz.html")
        s = time.monotonic()
        rc = run_stage(mod("build_web").main, [pkg_dest, "--out", slug_dest, "--title", clean_title])
        metrics["stages"]["build_web"] = {"duration_s": round(time.monotonic() - s, 4), "rc": rc}
        if rc:
            return rc
        if slug_file != "quiz.html":
            try:
                shutil.copy2(slug_dest, html_dest)
            except Exception:
                pass
        root_out = a.delivery_dir or (a.build_dir if a.build_dir != "build" else "output")
        dash_dest = a.dashboard or os.path.join(root_out, "index.html")
        try:
            from dashboard import update_dashboard
            from desktop_shortcut import create_desktop_shortcut
            q_cnt = None
            try:
                pkg_data = load_json(pkg_dest)
                q_cnt = len(pkg_data.get("questions", []))
            except Exception:
                pass
            update_dashboard(
                dashboard_path=dash_dest,
                module_path=slug_dest,
                title=clean_title,
                metadata={
                    "status": state.get("stages", {}).get("gate", {}).get("status", "Comprehensive"),
                    "question_count": q_cnt,
                    "profile": a.profile,
                }
            )
            create_desktop_shortcut(dash_dest, "StudySynth Library")
        except Exception as e:
            print("notice: dashboard/shortcut automation: %s" % e, file=sys.stderr)
        return 0

    def run_pdf():
        pdf_dir = os.path.join(R, "pdf")
        s = time.monotonic()
        rc = run_stage(mod("build_pdf").main, [pkg_dest, "--out", pdf_dir, "--profile", a.profile])
        if rc:
            metrics["stages"]["build_pdf"] = {"duration_s": round(time.monotonic() - s, 4), "rc": rc}
            return rc
        pdf_check = os.path.join(R, "pdf_check_report.json")
        rc2 = run_stage(mod("check_pdf").main, [
            os.path.join(pdf_dir, "question-paper-A.pdf"),
            os.path.join(pdf_dir, "answer-key-B.pdf"),
            os.path.join(pdf_dir, "explanations-C.pdf"),
            "--package", pkg_dest,
            "--report", pdf_check
        ])
        metrics["stages"]["build_pdf"] = {"duration_s": round(time.monotonic() - s, 4), "rc": rc2}
        return rc2

    if (do_web or do_pdf) and os.path.isfile(pkg_dest):
        jobs = {}
        if do_web:
            jobs["build_web"] = run_web
        if do_pdf:
            jobs["build_pdf"] = run_pdf
        if len(jobs) == 1:
            k, fn = next(iter(jobs.items()))
            rc = timed(k, fn)
            mark(k, "ok" if rc == 0 else "failed")
            if rc:
                save_json(sp, state)
                save_json(metrics_path, metrics)
                return rc
        else:
            results = run_parallel(jobs, max_workers=2)
            for k, rc in results.items():
                mark(k, "ok" if rc == 0 else "failed")
                if rc:
                    save_json(sp, state)
                    save_json(metrics_path, metrics)
                    return rc

    if (a.deliver or a.delivery_dir) and os.path.isfile(pkg_dest):
        deliv_dir = a.delivery_dir or "output"
        rc = timed("delivery", lambda: run_stage(mod("package_delivery").main, [
            pkg_dest,
            "--out-dir", deliv_dir,
            "--mode", a.delivery_mode,
            "--profile", a.profile,
        ]))
        mark("delivery", "ok" if rc == 0 else "failed")
        if rc:
            save_json(sp, state)
            save_json(metrics_path, metrics)
            return rc

    save_json(sp, state)
    metrics["total_s"] = round(time.monotonic() - t0, 4)
    try:
        metrics["source_size_bytes"] = os.path.getsize(a.source) if os.path.isfile(a.source) else 0
    except Exception:
        metrics["source_size_bytes"] = 0
    try:
        st = load_json(F["struct"]) if os.path.isfile(F["struct"]) else {}
        metrics["source_blocks"] = len(st.get("blocks", []))
    except Exception:
        metrics["source_blocks"] = "unknown"
    try:
        inv = load_json(a.inventory) if a.inventory and os.path.isfile(a.inventory) else {}
        units = inv.get("units", []) if isinstance(inv, dict) else (inv if isinstance(inv, list) else [])
        metrics["inventory_units"] = len(units)
    except Exception:
        metrics["inventory_units"] = "unknown"
    try:
        b = load_json(a.bank) if a.bank and os.path.isfile(a.bank) else {}
        qs = b.get("questions", []) if isinstance(b, dict) else []
        metrics["bank_questions"] = len(qs)
    except Exception:
        metrics["bank_questions"] = "unknown"
    try:
        cov = load_json(F["coverage"]) if os.path.isfile(F["coverage"]) else {}
        metrics["coverage_counted"] = cov.get("counted_questions", "unknown")
        metrics["coverage_total"] = cov.get("total_bank_questions", "unknown")
    except Exception:
        pass
    try:
        v = load_json(F["validation"]) if os.path.isfile(F["validation"]) else {}
        res = v.get("results", []) if isinstance(v, dict) else []
        metrics["validated"] = sum(1 for r in res if r.get("status") == "validated")
        metrics["rejected"] = sum(1 for r in res if r.get("status") == "rejected")
        metrics["repair_queue"] = load_json(repair_path) if os.path.isfile(repair_path) else None
        metrics["retries"] = 0
        metrics["gapfill_rounds"] = 0
    except Exception:
        pass
    try:
        qrep = load_json(F["quality"]) if os.path.isfile(F["quality"]) else {}
        metrics["quality_accepted"] = qrep.get("accepted", 0)
        metrics["quality_rejected"] = qrep.get("rejected", 0)
    except Exception:
        pass
    trace_file = os.path.join(R, "llm_trace.jsonl")
    if os.path.isfile(trace_file):
        summary = summarize_llm_trace(trace_file)
        metrics["llm_telemetry"] = summary
        metrics["model_calls"] = summary.get("total_calls", 0) if summary else 0
    else:
        metrics["model_calls"] = "unavailable (orchestrator cannot observe LLM layer)"
    save_json(metrics_path, metrics)
    print("pipeline %s: done -> %s (%.2fs, cache hits=%d misses=%d)" % (a.run_id, R, metrics["total_s"], metrics["cache"]["hits"], metrics["cache"]["misses"]))
    # A partially rejected bank completed useful work above but must not
    # report success: preserve the old nonzero signal.
    try:
        if not bank_schema_ok:
            print("pipeline %s: bank schema errors present" % a.run_id)
            return 1
        if os.path.isfile(F["validation"]):
            vr = load_json(F["validation"])
            if any(r.get("status") == "rejected" for r in vr.get("results", [])):
                print("pipeline %s: validation rejected questions; see repair_queue.json" % a.run_id)
                return 1
    except SystemExit:
        raise
    except Exception:
        pass
    return rc


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
