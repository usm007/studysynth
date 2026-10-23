"""Phase C — deterministic reconciliation, planning and batching (FAST pipeline).

Single canonical planner. No exam profile required; a supplied profile can only
influence nothing here — planning is derived from the inventory itself plus
config limits. responsibilities (all deterministic, zero model calls):

- merge per-chunk extraction outputs into one knowledge inventory, in chunk
  order, deduplicated ONLY by stable source identity (block_id + excerpt);
- assign stable KU-#### ids, order units by tier/exam value;
- turn per-KU question hints into a blueprint of question rows, bounded by
  per_ku_cap and section share caps (no per-KU quota manufacturing);
- honor a requested question count as far as the source supports, never
  cutting higher-priority material first, and report shortfalls honestly;
- emit generation batches (~12 rows) with compact self-contained evidence so
  generation needs no second planning request;
- assemble a question bank from per-batch generation outputs deterministically.

CLI:
  planning  python scripts/plan.py --document-structure struct.json --out-dir RUN
            [--inventory inv.json --config cfg.json --count N]
  chunks-only (no --inventory): writes chunks.json for the extraction phase.
  assembly  python scripts/plan.py --bank-from DIR --out bank.json
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cache import chunk_blocks, dedupe_units_by_identity, merge_batches
from lib_common import load_json, save_json, ensure_dir, run_main

PIT = {"critical": 5, "very_high": 4, "high": 3, "medium": 2, "low": 1, "none": 0}

DEFAULT_PURPOSE_TYPE = {
    "direct_recall": "factual_mcq",
    "conceptual_understanding": "reasoning_mcq",
    "distinction": "reasoning_mcq",
    "confusable_fact": "reasoning_mcq",
    "elimination": "elimination_mcq",
    "statement_evaluation": "statement_based",
    "chronology": "sequence_mcq",
    "classification": "reasoning_mcq",
    "cause_effect": "reasoning_mcq",
    "exception": "reasoning_mcq",
    "association": "reasoning_mcq",
    "application": "reasoning_mcq",
    "integrated_concept": "reasoning_mcq",
}
VALID_PURPOSES = set(DEFAULT_PURPOSE_TYPE)
VALID_TYPES = {"factual_mcq", "statement_based", "assertion_reason", "match_pairs",
               "elimination_mcq", "one_liner_mcq", "data_interpretation_mcq",
               "reasoning_mcq", "pedagogy_mcq", "sequence_mcq", "true_false"}
DIFF_ORDER = {"easy": 0, "medium": 1, "hard": 2}


def ku_priority_key(u):
    """Deterministic ordering: lower tier number first, then exam value."""
    dims = u.get("dimensions") or {}
    tier = u.get("tier")
    try:
        tier = int(tier)
    except (TypeError, ValueError):
        tier = 3
    exam = PIT.get(str(dims.get("exam_relevance", "")).lower(), 2)
    imp = PIT.get(str(dims.get("importance", "")).lower(), 2)
    disc = PIT.get(str(dims.get("discrimination_value", "")).lower(), 2)
    return (tier, -exam, -imp, -disc, str(u.get("id") or ""))


def _hint_rows(unit, per_ku_cap):
    """Blueprint rows from a KU's question hints (emitted during chunk understanding)."""
    rows = []
    hints = unit.get("question_hints") or []
    if isinstance(hints, dict):
        hints = [hints]
    for h in hints[:per_ku_cap]:
        if not isinstance(h, dict):
            continue
        p = h.get("purpose")
        purpose = p if p in VALID_PURPOSES else None
        qtype = h.get("type") if h.get("type") in VALID_TYPES else None
        diff = str(h.get("difficulty") or "") if str(h.get("difficulty") or "") in DIFF_ORDER else None
        if not purpose:
            purpose, qtype, diff = derive_row_spec(unit, None, qtype, diff)
        rows.append({
            "ku_id": unit.get("id"),
            "qtype": qtype or DEFAULT_PURPOSE_TYPE[purpose],
            "archetype": (unit.get("archetype_hints") or [None])[0] if unit.get("archetype_hints") else None,
            "difficulty": diff or difficulty_of(unit, purpose),
            "purpose": purpose,
            "primary_skill": h.get("primary_skill"),
            "cognitive_level": unit.get("cognitive_level") or cognitive_of(purpose),
            "difficulty_reason": h.get("note") or "hint from source understanding pass",
            "target_knowledge_units": [unit.get("id")],
            "confusion_cluster": unit.get("confusion_cluster"),
            "passage_required": bool(unit.get("has_passage")),
            "origin": "hint",
        })
    return rows


def derive_row_spec(unit, purpose=None, qtype=None, difficulty=None):
    """Deterministic purpose/type when the extraction hinted nothing."""
    dims = unit.get("dimensions") or {}
    cv = PIT.get(str(dims.get("confusion_value", "")).lower(), 0)
    sp = PIT.get(str(dims.get("statement_potential", "")).lower(), 0)
    ev = PIT.get(str(dims.get("elimination_value", "")).lower(), 0)
    cov = PIT.get(str(dims.get("conceptual_value", "")).lower(), 0)
    if sp >= 3 and not purpose:
        purpose = "statement_evaluation"
    elif cv >= 3 or unit.get("confusion_cluster") or (unit.get("confusable_with") or []):
        purpose = purpose or "distinction"
    elif ev >= 3:
        purpose = purpose or "elimination"
    elif cov >= 3:
        purpose = purpose or "conceptual_understanding"
    purpose = purpose or "direct_recall"
    qtype = qtype or DEFAULT_PURPOSE_TYPE[purpose]
    return purpose, qtype, difficulty


def cognitive_of(purpose):
    return {
        "direct_recall": "recall",
        "conceptual_understanding": "understanding",
        "distinction": "distinction",
        "confusable_fact": "distinction",
        "elimination": "analysis",
        "statement_evaluation": "analysis",
    }.get(purpose, "understanding")


def difficulty_of(unit, purpose):
    if purpose in ("statement_evaluation", "elimination", "integrated_concept"):
        return "hard"
    if purpose in ("distinction", "confusable_fact", "classification", "association"):
        return "medium"
    dims = unit.get("dimensions") or {}
    return "medium" if PIT.get(str(dims.get("importance", "")).lower(), 2) >= 3 else "easy"


def fallback_row(unit):
    purpose, qtype, _ = derive_row_spec(unit)
    return {
        "ku_id": unit.get("id"),
        "qtype": qtype,
        "archetype": (unit.get("archetype_hints") or [None])[0] if unit.get("archetype_hints") else None,
        "difficulty": difficulty_of(unit, purpose),
        "purpose": purpose,
        "primary_skill": None,
        "cognitive_level": unit.get("cognitive_level") or cognitive_of(purpose),
        "difficulty_reason": "derived deterministically from knowledge-unit dimensions",
        "target_knowledge_units": [unit.get("id")],
        "confusion_cluster": unit.get("confusion_cluster"),
        "passage_required": bool(unit.get("has_passage")),
        "origin": "derived",
    }


def section_of(unit):
    src = unit.get("source") or {}
    parts = src.get("section_path") or []
    return str(parts[0]) if parts else (str(unit.get("topic")) if unit.get("topic") else "global")


def reconcile_and_plan(units, cfg, count, notes):
    """Inventory -> prioritized, share-capped blueprint rows."""
    per_ku_cap = int(cfg.get("per_ku_cap", 3) or 3)
    tier_targets = cfg.get("tier_targets") or {}
    units = sorted(units or [], key=ku_priority_key)
    by_id = {}
    for u in units:
        uid = u.get("id")
        if uid:
            by_id[uid] = u
    rows = []
    for u in units:
        uid = u.get("id")
        tier = u.get("tier")
        try:
            tier = int(tier)
        except (TypeError, ValueError):
            tier = 3
        if tier >= 4:
            notes.append("tier-4 unit excluded from blueprint: %s (%s)" % (
                uid, u.get("omission_reason") or "tier 4 / exclude"))
            continue
        hint_rows = _hint_rows(u, per_ku_cap) or [fallback_row(u)]
        added = hint_rows[:per_ku_cap]
        rows.extend(added)
        # high-value KUs that carry a real confusion cluster but no distinctions
        # hint may earn ONE extra derived distinction form (R10 quality, not
        # per-KU quota manufacturing).
        if u.get("confusion_cluster") and len(added) < per_ku_cap:
            dims = u.get("dimensions") or {}
            fv = PIT.get(str(dims.get("confusion_value", "")).lower(), 0)
            has_dist = any(r.get("purpose") in ("distinction", "confusable_fact") for r in added)
            if fv >= 3 and not has_dist and uid in by_id:
                fr = fallback_row(dict(u, dimensions=dict(dims)))
                fr["purpose"] = "distinction"
                fr["qtype"] = DEFAULT_PURPOSE_TYPE["distinction"]
                fr["cognitive_level"] = u.get("cognitive_level") or "distinction"
                fr["difficulty"] = difficulty_of(u, "distinction")
                fr["origin"] = "derived"
                rows.append(fr)
    plan_rows = rows

    # section share cap (R8): drop lowest-priority extra rows from over-share
    # sections, but never reduce a section to zero.
    cap = float(cfg.get("section_share_cap", 2.0) or 2.0)
    sec_rows = {}
    for idx, r in enumerate(plan_rows):
        u = by_id.get(r.get("ku_id"), {})
        sec_rows.setdefault(section_of(u), []).append(idx)
    counts = {s: len(v) for s, v in sec_rows.items() if v}
    n_sec = len([s for s in counts if counts[s] > 0])
    if plan_rows and n_sec:
        mean_share = len(plan_rows) / n_sec
        limit = max(1, int(cap * mean_share))
        for s, idxs in sec_rows.items():
            if len(idxs) > limit > 0:
                keep = idxs[:limit]
                for i in idxs[limit:]:
                    r = plan_rows[i]
                    if r.get("origin") == "derived":
                        notes.append("share cap: deferred extra distinction row for %s (section over %.1fx mean)" % (
                            r.get("ku_id"), cap))
                        r["_omit"] = "section share cap"
    plan_rows = [r for r in plan_rows if not r.get("_omit")]

    def apply_count_policy(rows, count, notes):
        """Honor the request as far as content supports; never cut
        higher-priority material first (rows are already priority-ordered)."""
        requested = None if count is None else int(count)
        if requested is not None:
            if requested <= 0:
                raise SystemExit("--count must be a positive integer")
            if requested > len(rows):
                notes.append("requested count %d exceeds the %d questions the source supports; "
                             "no filler questions were manufactured" % (requested, len(rows)))
            if requested < len(rows):
                truncated = rows[requested:]
                tiers = {}
                for r in truncated:
                    t = (by_id.get(r.get("ku_id"), {}) or {}).get("tier")
                    tiers[t] = tiers.get(t, 0) + 1
                notes.append("requested count %d honored by priority; deferred rows per tier: %s" % (
                    requested, {str(k): v for k, v in sorted((str(t), v) for t, v in tiers.items())}))
                deferred_kus = sorted({r.get("ku_id") for r in truncated})
                notes.append("deferred KUs: %s" % (deferred_kus[:12] if len(deferred_kus) > 12 else deferred_kus))
                rows = rows[:requested]
        else:
            dcp = cfg.get("default_count_policy") or {}
            mn = int(dcp.get("min_questions") or 0)
            if 0 < mn > len(rows):
                notes.append("default policy: %d planned rows are below the configured minimum %d; "
                             "the source supports fewer — no filler questions were manufactured"
                             % (len(rows), mn))
        return rows

    plan_rows = apply_count_policy(plan_rows, count, notes)
    return plan_rows, by_id


def compact_ku(u):
    return {
        "id": u.get("id"),
        "type": u.get("type"),
        "statement": u.get("statement"),
        "supporting_excerpt": u.get("supporting_excerpt"),
        "source": {k: u.get("source", {}).get(k) for k in
                   ("page", "section_path", "block_id", "table_ref") if isinstance(u.get("source"), dict)},
        "confusion_cluster": u.get("confusion_cluster"),
        "confusable_with": u.get("confusable_with"),
        "cognitive_level": u.get("cognitive_level"),
    }


def evidence_pack(rows, by_id):
    """Compact per-batch evidence: cited KUs + their cluster confusable partners."""
    need = []
    for r in rows:
        for kid in r.get("target_knowledge_units") or [r.get("ku_id")]:
            if kid and kid not in need:
                need.append(kid)
        u = by_id.get(r.get("ku_id")) or {}
        for kid in (u.get("confusable_with") or []):
            if kid and kid in by_id and kid not in need:
                need.append(kid)
    return {kid: compact_ku(by_id[kid]) for kid in need if kid in by_id}


def make_batches(rows, by_id, cfg):
    size = int((cfg.get("batching") or {}).get("question_batch_size", 12) or 12)
    batches = []
    for i in range(0, len(rows), size):
        chunk = rows[i:i + size]
        batches.append({
            "batch_id": "GB-%03d" % (i // size + 1),
            "rows": chunk,
            "evidence": evidence_pack(chunk, by_id),
        })
    return {"batch_size": size, "batch_count": len(batches),
            "planned_questions": len(rows), "batches": batches}


def write_chunks(struct_path, out_dir, cfg):
    doc = load_json(struct_path)
    blocks = doc.get("blocks", []) if isinstance(doc, dict) else []
    batching = cfg.get("batching") or {}
    tokens = int(batching.get("extraction_chunk_tokens", 5000) or 5000)
    chunks = chunk_blocks(blocks, max_tokens=tokens)
    payload = {
        "chunk_tokens": tokens,
        "chunk_count": len(chunks),
        "chunk_order": [c["chunk_id"] for c in chunks],
        "chunks": [{"chunk_id": c["chunk_id"], "block_ids": c["block_ids"]} for c in chunks],
    }
    save_json(os.path.join(out_dir, "chunks.json"), payload)
    return payload


def load_extraction_dir(extraction_dir):
    """Read per-chunk extraction outputs in deterministic chunk order."""
    files = []
    for name in os.listdir(extraction_dir):
        m = re.match(r"chunk[_-]?(\d+)\.json$", name)
        if m:
            files.append((int(m.group(1)), os.path.join(extraction_dir, name)))
    files.sort()
    units = []
    limitations = []
    seen_chunks = []
    merged = []
    for _, path in files:
        doc = load_json(path)
        chunk_id = (doc.get("chunk_id") if isinstance(doc, dict) else None) or os.path.basename(path)
        seen_chunks.append(chunk_id)
        chunk_units = doc.get("kus", []) if isinstance(doc, dict) else []
        merged.extend(chunk_units)
        for lim in (doc.get("limitations") or []) if isinstance(doc, dict) else []:
            limitations.append({"chunk_id": chunk_id, "limitation": lim})
    if not files:
        raise SystemExit("no chunk_*.json extraction outputs found in %s" % extraction_dir)
    return merged, limitations, seen_chunks


def stable_ids(units):
    """Assign/keep stable KU ids after identity dedupe; returns remap info."""
    for i, u in enumerate(units, 1):
        if not u.get("id"):
            u["id"] = "KU-%04d" % i
    return units


def merge_planning(inventory_path, extraction_dir, cfg, count, notes):
    """Produce the reconciled inventory document + blueprint rows."""
    if extraction_dir:
        raw, limitations, chunks = load_extraction_dir(extraction_dir)
    else:
        inv = load_json(inventory_path)
        units = inv.get("units", []) if isinstance(inv, dict) else inv
        raw = list(units or [])
        limitations = (inv.get("limitations", []) if isinstance(inv, dict) else []) or []
        chunks = None
    kept, dropped = dedupe_units_by_identity(raw)
    if dropped:
        notes.append("identity dedupe dropped %d overlapping unit(s) (%s...)" % (len(dropped), dropped[:5]))
    kept = stable_ids(kept)
    if limitations:
        notes.append("%d extraction limitation(s) carried from the understanding pass" % len(limitations))
    rows, by_id = reconcile_and_plan(kept, cfg, count, notes)
    return kept, rows, by_id, limitations, notes


def main(argv):
    ap = argparse.ArgumentParser(description="FAST Phase C planner (deterministic).")
    ap.add_argument("--document-structure", "--struct", dest="struct", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--extraction-dir", default=None,
                    help="Directory of per-chunk chunk_*.json extraction outputs")
    ap.add_argument("--count", type=int, default=None,
                    help="Requested question count (ordinary parameter, not a mode)")
    ap.add_argument("--inventory-out", default=None,
                    help="Write the merged inventory here (used with --extraction-dir)")
    ap.add_argument("--bank-from", default=None,
                    help="Directory of per-batch generation outputs (batch_*.json)")
    ap.add_argument("--bank-out", default=None, help="Path for the assembled question bank")
    a = ap.parse_args(argv)

    ensure_dir(a.out_dir)
    cfgl = load_json(a.config) if a.config and os.path.isfile(a.config) else {}
    cfg = cfgl if isinstance(cfgl, dict) else {}

    if a.bank_from:
        if not a.bank_out:
            print("error: --bank-out required with --bank-from", file=sys.stderr)
            return 2
        files = []
        for name in os.listdir(a.bank_from):
            m = re.match(r"batch[_-]?(\d+)\.json$", name)
            if m:
                files.append((int(m.group(1)), os.path.join(a.bank_from, name)))
        files.sort()
        if not files:
            print("error: no batch_*.json generation outputs in %s" % a.bank_from, file=sys.stderr)
            return 1
        # merge in deterministic batch order with duplicate-id rejection
        payloads = []
        for i, p in files:
            doc = load_json(p)
            if isinstance(doc, dict):
                doc = doc.get("questions") or []
            payloads.append((i, doc or []))
        merged = merge_batches(payloads)
        bank = {"questions": merged,
                "assembled_from": {"batch_files": len(files), "bank_schema": "question.schema.json"}}
        if a.inventory_out:
            save_json(a.inventory_out, bank)
        save_json(a.bank_out, bank)
        print("plan: bank assembled -> %s (%d questions from %d batches)" % (a.bank_out, len(merged), len(files)))
        return 0

    chunks = write_chunks(a.struct, a.out_dir, cfg)
    if not (a.inventory or a.extraction_dir):
        print("plan: %d extraction chunk(s) ready -> %s (extraction_dir not passed; chunks.json only)"
              % (chunks["chunk_count"], os.path.join(a.out_dir, "chunks.json")))
        return 0

    notes = []
    units, rows, by_id, limitations, notes = merge_planning(
        a.inventory, a.extraction_dir, cfg, a.count, notes)
    plan_doc = {
        "plan_version": 2,
        "workflow": "FAST",
        "count_request": a.count,
        "policy_notes": notes,
        "tier_targets": cfg.get("tier_targets"),
        "section_share_cap": cfg.get("section_share_cap", 2.0),
        "per_ku_cap": cfg.get("per_ku_cap", 3),
        "limitations": limitations,
        "rows": rows,
    }
    save_json(os.path.join(a.out_dir, "coverage_plan.json"), plan_doc)
    batches = make_batches(rows, by_id, cfg)
    save_json(os.path.join(a.out_dir, "generation_batches.json"), batches)
    if a.inventory_out and a.extraction_dir:
        save_json(a.inventory_out, {"units": units, "limitations": limitations})
    print("plan: %d knowledge units -> %d blueprint rows in %d generation batch(es) -> %s"
          % (len(units), len(rows), batches["batch_count"], a.out_dir))
    for n in notes[:8]:
        print("  note: %s" % n)
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
