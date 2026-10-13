import argparse
import concurrent.futures
import importlib.util
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, ensure_dir, run_main
from cache import sha_file, sha_obj, load_manifest, save_manifest

HERE = os.path.dirname(os.path.abspath(__file__))
STAGES = ("ingest", "anchors", "check", "validate", "quality", "coverage", "dedupe", "audit", "gate", "report")
# redo invalidation: stage -> itself + descendants
DESCENDANTS = {
    "ingest": ("ingest", "anchors", "check", "validate", "quality", "coverage", "dedupe", "audit", "gate", "report"),
    "anchors": ("anchors", "check", "validate", "quality", "coverage", "dedupe", "audit", "gate", "report"),
    "check": ("check", "audit", "gate", "report"),
    "validate": ("validate", "coverage", "audit", "gate", "report"),
    "quality": ("quality", "coverage", "audit", "gate", "report"),
    "dedupe": ("dedupe", "coverage", "audit", "gate", "report"),
    "coverage": ("coverage", "audit", "gate", "report"),
    "audit": ("audit", "gate", "report"),
    "gate": ("gate", "report"),
    "report": ("report",),
    "all": tuple(STAGES),
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
    t0 = time.time()
    metrics = {"run_id": a.run_id, "stages": {}, "model_calls": "unavailable (orchestrator cannot observe LLM layer)",
               "cache": {"hits": 0, "misses": 0}}
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
    for st in invalidated:
        key = {"ingest": F["struct"], "anchors": F["anchors"], "check": F["check"],
               "validate": F["validation"], "quality": F["quality"], "coverage": F["coverage"],
               "dedupe": F["dedupe"], "audit": F["audit"], "gate": F["gate"]}.get(st)
        if key and os.path.isfile(key) and redo in ("all", st):
            pass  # recompute below via fingerprint mismatch path
    cfg_sha = _file_sha(a.config)
    prof_sha = _file_sha(a.profile)

    def fingerprint(stage, extra=None):
        fp = {"source": _file_sha(a.source), "config": cfg_sha, "profile": prof_sha,
              "inventory": _file_sha(a.inventory), "bank": _file_sha(a.bank),
              "mode": mode, "extra": extra or {}}
        # code version: hash of the deterministic script driving this stage
        script = {"ingest": "ingest.py", "anchors": "anchors.py", "check": "inventory_check.py",
                  "validate": "validate_questions.py", "quality": "quality.py", "coverage": "coverage.py",
                  "dedupe": "dedupe.py", "audit": "audit.py", "gate": "gate.py"}.get(stage)
        if script:
            fp["code"] = _file_sha(os.path.join(HERE, script))
        return sha_obj(fp)

    def fresh(stage, outs, extra=None):
        """Dependency-aware reuse: all outputs exist AND fingerprint matches."""
        if stage in invalidated:
            return False
        if not all(os.path.isfile(o) for o in outs):
            return False
        fp = fingerprint(stage, extra)
        if manifest.get(stage, {}).get("fingerprint") != fp:
            return False
        outs_ok = all(manifest.get(stage, {}).get("outputs", {}).get(o) == _file_sha(o) for o in outs)
        return outs_ok

    def mark(stage, status, detail=""):
        state["stages"][stage] = {"status": status, "detail": detail}
        save_json(sp, state)

    def record_manifest(stage, outs, extra=None):
        manifest[stage] = {"fingerprint": fingerprint(stage, extra),
                           "outputs": {o: _file_sha(o) for o in outs}}
        save_manifest(manifest_path, manifest)

    def timed(stage, fn):
        s = time.time()
        rc = fn()
        dt = time.time() - s
        metrics["stages"][stage] = {"duration_s": round(dt, 3), "rc": rc}
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
    if fresh("anchors", [F["anchors"]], {"struct": _file_sha(F["struct"])}):
        mark("anchors", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1
    else:
        metrics["cache"]["misses"] += 1
        rc = timed("anchors", lambda: run_stage(mod("anchors").main, [F["struct"], "--out", F["anchors"]]))
        mark("anchors", "ok" if rc == 0 else "failed")
        if rc:
            save_json(metrics_path, metrics)
            return rc
        record_manifest("anchors", [F["anchors"]], {"struct": _file_sha(F["struct"])})
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
    if fresh("check", [F["check"]], {"struct": _file_sha(F["struct"]), "anchors": _file_sha(F["anchors"])}):
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
        record_manifest("check", [F["check"]], {"struct": _file_sha(F["struct"]), "anchors": _file_sha(F["anchors"])})
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
    v_extra = {"struct": _file_sha(F["struct"])}
    q_extra = {"struct": _file_sha(F["struct"])}
    d_extra = {}
    need_v = not fresh("validate", [F["validation"]], v_extra)
    need_q = not fresh("quality", [F["quality"]], q_extra)
    need_d = not fresh("dedupe", [F["dedupe"]], d_extra)
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
        s = time.time()
        rc = run_stage(mod("validate_questions").main, [a.bank, a.inventory, F["struct"], "--profile", a.profile, "--mode", mode, "--config", a.config, "--out", F["validation"]])
        metrics["stages"]["validate"] = {"duration_s": round(time.time() - s, 3), "rc": rc}
        return rc

    def do_quality():
        s = time.time()
        rc = run_stage(mod("quality").main, [a.bank, a.inventory, F["struct"], "--profile", a.profile, "--mode", mode, "--config", a.config, "--out", F["quality"]])
        metrics["stages"]["quality"] = {"duration_s": round(time.time() - s, 3), "rc": rc}
        return rc

    def do_dedupe():
        s = time.time()
        rc = run_stage(mod("dedupe").main, [a.bank, "--threshold", str(cfg.get("duplicate_threshold", 0.85)), "--out", F["dedupe"]])
        metrics["stages"]["dedupe"] = {"duration_s": round(time.time() - s, 3), "rc": rc}
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
                record_manifest("validate", [F["validation"]], v_extra)
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
            if True:
                try:
                    record_manifest("quality", [F["quality"]], q_extra)
                except Exception:
                    pass
        if "dedupe" in results:
            rc = results["dedupe"]
            mark("dedupe", "ok" if rc == 0 else "failed")
            if rc:
                save_json(metrics_path, metrics)
                return rc
            record_manifest("dedupe", [F["dedupe"]], d_extra)
    if os.path.isfile(sq):
        rc = schema_each(a.bank, "questions", sq, "question")
        mark("schema_bank", "ok" if rc == 0 else "failed")
        if rc:
            # schema violations are per-question defects: record, keep going
            # so valid items still reach coverage/audit; exit stays nonzero.
            bank_schema_ok = False
            print("pipeline %s: bank schema errors; continuing with valid items" % a.run_id)
    else:
        mark("schema_bank", "skipped", "no schema file")
    # coverage MUST see quality + dedupe so only validated/accepted/deduped
    # questions earn credit (Phase 8) — for new-engine banks (explicit
    # purposes present). Legacy banks without purpose tags are grandfathered
    # (validation-only credit), mirroring gate.py, so existing COMPREHENSIVE
    # packages keep passing; quality/dedupe reports are still built + audited.
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
    # blind-review comparison (scripts/review_batch.py output), written by the
    # LLM review layer as R/blind_review.json; a blind mismatch excludes the
    # question from coverage credit until repaired and re-reviewed.
    blind_path = os.path.join(R, "blind_review.json")
    cov_extra = {"validation": _file_sha(F["validation"]), "quality": _file_sha(F["quality"]),
                 "dedupe": _file_sha(F["dedupe"]), "blind": _file_sha(blind_path),
                 "new_engine": new_engine}
    if fresh("coverage", [F["coverage"]], cov_extra):
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
        record_manifest("coverage", [F["coverage"]], cov_extra)
    if fresh("audit", [F["audit"]], {"coverage": _file_sha(F["coverage"]), "validation": _file_sha(F["validation"]), "quality": _file_sha(F["quality"])}):
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
        record_manifest("audit", [F["audit"]], {"coverage": _file_sha(F["coverage"]), "validation": _file_sha(F["validation"]), "quality": _file_sha(F["quality"])})
    if fresh("gate", [F["gate"]], {"audit": _file_sha(F["audit"])}):
        mark("gate", "skipped", "cache hit (fingerprint match)")
        metrics["cache"]["hits"] += 1
    else:
        metrics["cache"]["misses"] += 1
        rc = timed("gate", lambda: run_stage(mod("gate").main, [F["audit"], "--config", a.config]))
        mark("gate", "ok" if rc == 0 else "failed")
        if rc:
            save_json(metrics_path, metrics)
            return rc
        record_manifest("gate", [F["gate"]], {"audit": _file_sha(F["audit"])})
    # authoritative final audit+gate are always recomputed above from the
    # current bank; never served from a stale cache (fresh() requires parent
    # fingerprints to match).
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
        s = time.time()
        rc = run_stage(mod("build_web").main, [pkg_dest, "--out", slug_dest, "--title", clean_title])
        metrics["stages"]["build_web"] = {"duration_s": round(time.time() - s, 3), "rc": rc}
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
        s = time.time()
        rc = run_stage(mod("build_pdf").main, [pkg_dest, "--out", pdf_dir, "--profile", a.profile])
        if rc:
            metrics["stages"]["build_pdf"] = {"duration_s": round(time.time() - s, 3), "rc": rc}
            return rc
        pdf_check = os.path.join(R, "pdf_check_report.json")
        rc2 = run_stage(mod("check_pdf").main, [
            os.path.join(pdf_dir, "question-paper-A.pdf"),
            os.path.join(pdf_dir, "answer-key-B.pdf"),
            os.path.join(pdf_dir, "explanations-C.pdf"),
            "--package", pkg_dest,
            "--report", pdf_check
        ])
        metrics["stages"]["build_pdf"] = {"duration_s": round(time.time() - s, 3), "rc": rc2}
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
    # run metrics: wall-clock per stage already recorded; add totals + counts
    metrics["total_s"] = round(time.time() - t0, 3)
    try:
        st = load_json(F["struct"]) if os.path.isfile(F["struct"]) else {}
        metrics["source_blocks"] = len(st.get("blocks", []))
    except Exception:
        metrics["source_blocks"] = "unknown"
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
        metrics["retries"] = 0  # deterministic layer performs no LLM retries; repair is a new LLM call
        metrics["gapfill_rounds"] = 0  # deterministic stages only; LLM gap-fill rounds tracked by orchestrator
    except Exception:
        pass
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
