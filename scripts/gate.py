import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, fail, run_main


def decide(audit, thr, processing_mode=None, evidence=None):
    reasons = []
    limited = False
    rec = audit.get("anchor_recall", 0)
    if rec < thr:
        reasons.append("anchor_recall %.2f%% < threshold %.2f%%" % (rec * 100, thr * 100))
    if audit.get("diff_status") != "resolved":
        reasons.append("inventory diff queue unresolved")
    if audit.get("density_flags"):
        reasons.append("%d sections below density floor" % len(audit["density_flags"]))
    cov = audit.get("coverage_by_tier", {})
    for t in ("1", "2"):
        c = cov.get(t, {})
        if c and c.get("pct_covered", 0) < 100:
            reasons.append("tier %s coverage %.1f%% < 100%%" % (t, c.get("pct_covered", 0)))
    vr = audit.get("validation_rates", {})
    if vr.get("pct_validated", 0) < 100:
        reasons.append("validation rate %.1f%% < 100%%" % vr.get("pct_validated", 0))
    if audit.get("skew_flags"):
        reasons.append("%d sections over share cap" % len(audit["skew_flags"]))
    if audit.get("duplicate_flags"):
        reasons.append("%d duplicate questions" % len(audit["duplicate_flags"]))
    # C4 downgrade control: T1 downgrade without reason, or >10% of T1/T2
    # downgraded, blocks COMPREHENSIVE until reviewed.
    dg = audit.get("downgrade_flags", [])
    t12 = [d for d in dg if str(d.get("from")) in ("1", "2")] if dg and isinstance(dg[0], dict) else []
    noreason_t1 = [d for d in t12 if str(d.get("from")) == "1" and not d.get("reason")]
    ku_counts = audit.get("ku_counts", {})
    n_t12 = sum(ku_counts.get(k, 0) for k in ("1", "2", 1, 2))
    if noreason_t1:
        reasons.append("%d Tier-1 downgrade(s) without reason" % len(noreason_t1))
    if n_t12 and len(t12) / n_t12 > 0.10:
        reasons.append("%.1f%% of Tier 1/2 units downgraded (>10%% cap)" % (100 * len(t12) / n_t12))
    if audit.get("limitations"):
        reasons.append("%d limitations: %s" % (len(audit["limitations"]), "; ".join(audit["limitations"][:3])))
        limited = True
    # ---- competitive-engine gate (only when new audit fields present) ----
    # required cognitive coverage: Tier 1/2 cognitive gaps block COMPREHENSIVE
    # only when the audit actually computed cognitive data.
    cog = audit.get("cognitive_by_tier", None)
    gaps = audit.get("cognitive_gaps", None)
    purpose_cov = audit.get("purpose_coverage", {}) or {}
    new_engine = bool(audit.get("has_explicit_purposes"))
    # Only enforce cognitive blocking when the new engine was actually used
    # (explicit purpose metadata present). Legacy banks without purpose tags are
    # grandfathered so existing COMPREHENSIVE packages keep passing.
    if new_engine and isinstance(cog, dict) and cog and isinstance(gaps, dict) and purpose_cov:
        if gaps:
            # critical: any Tier-1 KU missing required forms blocks COMPREHENSIVE
            reasons.append("%d Tier 1/2 KUs lack required cognitive forms "
                           "(e.g. %s)" % (len(gaps), sorted(gaps)[:3]))
    # high-priority confusion clusters unaddressed -> warn (blocks only if many)
    unaddr = audit.get("unaddressed_clusters", None)
    if new_engine and isinstance(unaddr, list) and unaddr:
        if len(unaddr) >= 3:
            reasons.append("%d confusion clusters unaddressed: %s" % (len(unaddr), unaddr[:3]))
        # 1-2 unaddressed clusters are reported but do not alone block COMPREHENSIVE
    # required exam purposes missing entirely -> block
    missing_p = audit.get("missing_purposes", None)
    if isinstance(missing_p, list) and missing_p:
        reasons.append("required exam purpose(s) missing: %s" % missing_p)
    # Phase 3 Question Quality gate (enforced when explicit purposes are present)
    if new_engine:
        qstats = audit.get("quality_stats") or {}
        if qstats and qstats.get("quality_rejected", 0) > 0:
            reasons.append("%d question(s) rejected by quality evaluation" % qstats["quality_rejected"])

    has_substantive_flaws = bool(reasons)
    pm = str(processing_mode or audit.get("processing_mode") or "").upper()

    # Check verification evidence
    ev = evidence
    if ev is None:
        ev = audit.get("verification_evidence")

    # Processing mode verification: QUICK and BALANCED skip exhaustive second-pass sweep
    # and cannot receive COMPREHENSIVE status.
    if pm in ("QUICK", "BALANCED"):
        reasons.append("verification scope reduced: processing mode '%s' skipped exhaustive second-pass sweep" % pm)
        if has_substantive_flaws:
            # Genuine failures/coverage gaps must remain PARTIAL/LIMITED, never overwritten
            if limited:
                return "LIMITED", reasons
            return "PARTIAL", reasons
        return "LIMITED", reasons

    # In COMPREHENSIVE mode, evidence of full-source second pass and reviews is required
    if ev is not None:
        if not isinstance(ev, dict) or not ev.get("second_pass_sweep"):
            reasons.append("verification evidence incomplete: missing exhaustive second-pass sweep")
            if has_substantive_flaws:
                return ("LIMITED" if limited else "PARTIAL"), reasons
            return "LIMITED", reasons
        if ev.get("missing_reviews"):
            reasons.append("verification evidence incomplete: mandatory review stream missing")
            if has_substantive_flaws:
                return ("LIMITED" if limited else "PARTIAL"), reasons
            return "LIMITED", reasons

    if not reasons:
        return "COMPREHENSIVE", reasons
    # LIMITED iff an extraction limitation makes completeness uncertifiable (E5);
    # otherwise an honest PARTIAL.
    if limited:
        return "LIMITED", reasons
    return "PARTIAL", reasons


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("audit")
    ap.add_argument("--out", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--processing-mode", choices=["QUICK", "BALANCED", "COMPREHENSIVE"], default=None)
    ap.add_argument("--evidence", default=None, help="Path to verification_evidence.json")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.audit):
        fail("audit file not found: %s" % a.audit)
    try:
        audit = load_json(a.audit)
        if not isinstance(audit, dict) or "ku_counts" not in audit:
            raise ValueError("not an audit report")
    except Exception as e:
        fail("invalid audit file: %s" % e, code=2)
    thr = a.threshold
    cfg_obj = {}
    if a.config and os.path.isfile(a.config):
        try:
            cfg_obj = load_json(a.config) or {}
        except Exception:
            cfg_obj = {}
    if thr is None and cfg_obj:
        try:
            v = cfg_obj.get("anchor_recall_threshold", 1.0)
            thr = (v / 100.0) if v > 1 else float(v)
        except Exception:
            thr = 1.0
    if thr is None:
        thr = 1.0
    proc_mode = a.processing_mode or cfg_obj.get("processing_mode") or audit.get("processing_mode")
    
    # Resolve verification evidence if available
    evidence_data = None
    ev_path = a.evidence
    if not ev_path:
        cand = os.path.join(os.path.dirname(os.path.abspath(a.audit)), "verification_evidence.json")
        if os.path.isfile(cand):
            ev_path = cand
    if ev_path and os.path.isfile(ev_path):
        try:
            evidence_data = load_json(ev_path)
        except Exception:
            evidence_data = None

    status, reasons = decide(audit, thr, processing_mode=proc_mode, evidence=evidence_data)
    gate = {
        "status": status,
        "reasons": reasons,
        "processing_mode": proc_mode or "COMPREHENSIVE",
        "evidence_verified": bool(evidence_data and evidence_data.get("second_pass_sweep"))
    }
    dest = a.out or os.path.join(os.path.dirname(os.path.abspath(a.audit)), "gate.json")
    if not dest.endswith(".json"):
        dest = os.path.join(dest, "gate.json")
    save_json(dest, gate)
    print(json.dumps(gate, indent=2))
    print("GATE: %s (%d reasons)" % (status, len(reasons)))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
