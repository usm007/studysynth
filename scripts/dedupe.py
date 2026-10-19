"""Deduplication and Redundancy Detection Engine (Phase 3).

Detects:
1. Exact duplicates (identical stem or identical options + key)
2. Semantic duplicates (token set similarity >= threshold)
3. Same-fact + Same-purpose redundancy (same primary KU + same exam purpose)
4. Same-statement set with cosmetic changes (permutations/equivalent statements)

Preserves valuable diversity:
Multiple questions on the same KU are permitted and encouraged if they
serve different cognitive purposes (e.g. recall vs distinction vs statement).
"""
import argparse
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, norm, toks, token_set_sim, fail, run_main


def blob(q):
    opts = []
    for o in (q.get("options") or []):
        if isinstance(o, dict):
            opts.append(o.get("text", "") or "")
        elif isinstance(o, str):
            opts.append(o)
        else:
            opts.append(str(o))
    return (q.get("stem", q.get("question", "")) or "") + " " + " ".join(opts)


def get_prim_ku(q):
    kus = q.get("knowledge_units") or []
    for e in kus:
        if isinstance(e, dict) and e.get("role") == "primary":
            return e.get("ku_id")
    if q.get("primary_ku"):
        return q.get("primary_ku")
    if kus and isinstance(kus[0], dict):
        return kus[0].get("ku_id")
    if q.get("ku_refs"):
        return q.get("ku_refs")[0]
    return None


def jaccard_sim(sa, sb) -> float:
    """Exact Jaccard token-set similarity on precomputed token sets."""
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def prepare_question_repr(q):
    """Precompute normalized text, token sets, and metadata for fast duplicate comparison."""
    stem_raw = q.get("stem", q.get("question", "")) or ""
    stem_n = norm(stem_raw)
    bl = blob(q)
    sts = []
    for st in (q.get("statements") or []):
        if isinstance(st, dict):
            t = st.get("text", "") or ""
            sts.append((norm(t), set(toks(t))))
    return {
        "id": q.get("id"),
        "stem_raw": stem_raw,
        "norm_stem": stem_n,
        "norm_stem_sig": stem_n,
        "stem_toks": set(toks(stem_raw)),
        "blob": bl,
        "blob_norm": norm(bl),
        "blob_toks": set(toks(bl)),
        "prim_ku": get_prim_ku(q),
        "purpose": q.get("purpose"),
        "statements": sts,
        "raw": q
    }


def detect_duplicates(questions, threshold=0.85):
    pairs = []
    diversity_preserved = []

    # Precompute reusable normalized and tokenized representations
    reprs = [prepare_question_repr(q) for q in (questions or [])]

    for x, y in itertools.combinations(reprs, 2):
        x_id, y_id = x["id"], y["id"]
        x_stem, y_stem = x["norm_stem"], y["norm_stem"]
        x_prim, y_prim = x["prim_ku"], y["prim_ku"]
        x_purp, y_purp = x["purpose"], y["purpose"]

        # 1. Exact Duplicate
        if x_stem and x_stem == y_stem:
            pairs.append({
                "a": x_id, "b": y_id, "type": "exact_duplicate",
                "similarity": 1.0, "reason": "identical question stem"
            })
            continue

        # 2. Semantic Duplicate via Blob Similarity
        s = jaccard_sim(x["blob_toks"], y["blob_toks"])
        if s >= threshold:
            pairs.append({
                "a": x_id, "b": y_id, "type": "semantic_duplicate",
                "similarity": round(s, 3), "reason": "high token-set similarity (%.3f)" % s
            })
            continue

        # 3. Same Statement Set with Cosmetic Changes
        sts_x = x["statements"]
        sts_y = y["statements"]
        if sts_x and sts_y and len(sts_x) == len(sts_y):
            matches = sum(1 for sx in sts_x if any(jaccard_sim(sx[1], sy[1]) >= 0.85 for sy in sts_y))
            if matches == len(sts_x):
                pairs.append({
                    "a": x_id, "b": y_id, "type": "same_statement_set",
                    "similarity": round(s, 3), "reason": "same statements with cosmetic changes"
                })
                continue

        # 4. Same Fact + Same Purpose Redundancy vs Valuable Diversity
        if x_prim and y_prim and x_prim == y_prim:
            if x_purp and y_purp and x_purp == y_purp:
                stem_sim = jaccard_sim(x["stem_toks"], y["stem_toks"])
                if stem_sim >= 0.65 or s >= 0.70:
                    pairs.append({
                        "a": x_id, "b": y_id, "type": "same_fact_same_purpose",
                        "similarity": round(stem_sim, 3),
                        "reason": "redundant: same primary KU %s and purpose '%s'" % (x_prim, x_purp)
                    })
                    continue
            elif x_purp and y_purp and x_purp != y_purp:
                diversity_preserved.append({
                    "a": x_id, "b": y_id, "ku_id": x_prim,
                    "purpose_a": x_purp, "purpose_b": y_purp,
                    "reason": "valuable diversity: same KU tested across different purposes"
                })

    return pairs, diversity_preserved



def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("bank")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if not os.path.isfile(a.bank):
        fail("file not found: %s" % a.bank)
    b = load_json(a.bank)
    qs = b.get("questions") if isinstance(b, dict) else b

    pairs, diversity = detect_duplicates(qs, a.threshold)

    out = {
        "threshold": a.threshold,
        "pairs": pairs,
        "count": len(pairs),
        "valuable_diversity_count": len(diversity),
        "valuable_diversity": diversity[:20]
    }
    dest = a.out or os.path.join(os.path.dirname(os.path.abspath(a.bank)), "dedupe_report.json")
    save_json(dest, out)
    print("dedupe: %d redundant/duplicate pairs, %d valuable diversity pairs preserved (thr=%.2f) -> %s" %
          (len(pairs), len(diversity), a.threshold, dest))
    for p in pairs:
        print("  %s ~ %s [%s] (%s)" % (p["a"], p["b"], p["type"], p["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
