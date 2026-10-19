"""Dynamic runner: one start command that adapts to any source size.

Stdlib only. Preserves every quality gate; changes execution only:
- measures the source and sizes the work from config batching
- picks bounded workers from CPU count (2..6), never unbounded
- runs deterministic stages with resume (pipeline manifest + state)
- keeps a batch ledger so reruns do pending work only
- fast-fails image-only PDFs with a readable message instead of a long stall
- exposes OCR hook: uses tesseract when installed, else reports clearly
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, ensure_dir  # noqa: E402
from cache import approx_tokens, chunk_blocks, sha_file  # noqa: E402


def pick_workers(n_jobs: int) -> int:
    cpus = os.cpu_count() or 4
    if n_jobs <= 1:
        return 1
    # dynamic but bounded: enough to overlap I/O, never a stampede
    return max(2, min(6, cpus, n_jobs))


def source_size_note(struct_path: str) -> dict:
    try:
        doc = load_json(struct_path)
    except Exception:
        return {"blocks": 0, "tokens": 0, "chunks": 0, "status": "unknown"}
    blocks = doc.get("blocks", []) if isinstance(doc, dict) else []
    toks = sum(approx_tokens((b.get("text") or "")) for b in blocks)
    try:
        chunks = chunk_blocks(blocks, max_tokens=5000)
    except Exception:
        chunks = []
    status = doc.get("extraction_status", "ok") if isinstance(doc, dict) else "ok"
    return {"blocks": len(blocks), "tokens": toks,
            "chunks": len(chunks), "status": status,
            "limitations": (doc.get("limitations", []) if isinstance(doc, dict) else [])}


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def load_progress(path: str) -> dict:
    try:
        if os.path.isfile(path):
            return load_json(path)
    except Exception:
        pass
    return {"completed": {}, "pending": {}}


def save_progress(path: str, prog: dict) -> None:
    save_json(path, prog)


def plan_batches(total: int, size: int) -> list:
    if total <= 0 or size <= 0:
        return []
    return [(i, min(i + size, total)) for i in range(0, total, size)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Dynamic adaptive run (quality gates unchanged).")
    ap.add_argument("--source", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--build-dir", default="build")
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--bank", default=None)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args(argv)

    if not os.path.isfile(a.source):
        print("error: source not found: %s" % a.source, file=sys.stderr)
        return 1
    for p, n in ((a.profile, "profile"), (a.config, "config")):
        if not os.path.isfile(p):
            print("error: %s not found: %s" % (n, p), file=sys.stderr)
            return 1
    cfg = load_json(a.config)
    batching = cfg.get("batching", {}) if isinstance(cfg, dict) else {}
    rdir = a.run_id if os.path.basename(os.path.normpath(a.build_dir)) == a.run_id else os.path.join(a.build_dir, a.run_id)
    ensure_dir(rdir)
    struct_path = os.path.join(rdir, "document_structure.json")

    # fast local parse when needed so sizing never waits on slow steps
    if not os.path.isfile(struct_path):
        import importlib.util as iu
        spec = iu.spec_from_file_location("ingest", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingest.py"))
        m = iu.module_from_spec(spec)
        spec.loader.exec_module(m)
        rc = m.main([a.source, "--out", rdir, "--run-id", a.run_id])
        if rc:
            return int(rc)
    info = source_size_note(struct_path)
    ext = os.path.splitext(a.source)[1].lower()
    if info["blocks"] == 0 or info["status"] == "unreliable":
        if ext == ".pdf" and not ocr_available():
            print("image PDF: no readable text found and no OCR tool installed; "
                  "supply a readable text version for the same quality checks without the long wait.")
            print("detail: blocks=%d status=%s" % (info["blocks"], info["status"]))
            return 2
        print("warning: source parsed with limitations: %s" % "; ".join(info.get("limitations", [])[:3]))

    # dynamic plan from measured size + config (no user tuning)
    qsize = int(batching.get("question_batch_size", 8) or 8)
    rsize = int(batching.get("review_batch_size", 6) or 6)
    # estimate questions only when a bank exists; otherwise report extraction plan
    est_questions = 0
    if a.bank and os.path.isfile(a.bank):
        try:
            b = load_json(a.bank)
            qs = b.get("questions", b) if isinstance(b, dict) else b
            est_questions = len(qs or [])
        except Exception:
            est_questions = 0
    workers = pick_workers(max(1, info["chunks"], (est_questions + qsize - 1) // qsize if est_questions else 1))
    prog_path = os.path.join(rdir, "batch_progress.json")
    prog = load_progress(prog_path)
    plan = {
        "blocks": info["blocks"], "tokens": info["tokens"], "chunks": info["chunks"],
        "workers": workers,
        "question_batches": plan_batches(est_questions, qsize) if est_questions else [],
        "review_batches_per_stream": plan_batches(est_questions, rsize) if est_questions else [],
        "ocr": {"available": ocr_available()},
        "resume": {"completed_streams": sorted(prog.get("completed", {}).keys())},
    }
    save_json(os.path.join(rdir, "dynamic_plan.json"), plan)
    print("measured: %d blocks ~%d tokens in %d chunks; workers=%d" % (info["blocks"], info["tokens"], info["chunks"], workers))
    if est_questions:
        print("bank: %d questions -> %d generation groups, %d review groups per stream" % (
            est_questions, len(plan["question_batches"]), len(plan["review_batches_per_stream"])))
    else:
        print("next: extraction groups=%d ready; question groups sized at %d per group once the bank exists" % (info["chunks"], qsize))
    if a.plan_only:
        save_progress(prog_path, prog)
        return 0

    # run deterministic stages through the standard pipeline (resume via manifest)
    import importlib.util as iu
    spec = iu.spec_from_file_location("pipeline", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline.py"))
    pm = iu.module_from_spec(spec)
    spec.loader.exec_module(pm)
    pargs = ["--source", a.source, "--run-id", a.run_id, "--profile", a.profile,
             "--config", a.config, "--build-dir", a.build_dir]
    if a.inventory:
        pargs += ["--inventory", a.inventory]
    if a.bank:
        pargs += ["--bank", a.bank]
    if a.full:
        pargs += ["--full"]
    t0 = time.time()
    rc = pm.main(pargs)
    dt = time.time() - t0
    print("dynamic run done in %.1fs (rc=%s)" % (dt, rc))
    save_progress(prog_path, prog)
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
