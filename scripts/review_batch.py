"""Deterministic helpers for the batched independent review contract.

redact_bank() builds the keyless review payload (see prompts/review-batch.md).
compare_results() matches blind-derived answers against the keyed bank without
letting the reviewer certify its own key.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cache import redact_question, compare_blind


def redact_bank(questions):
    """Return {qid: redacted_question} with all key material removed."""
    return {q.get("id"): redact_question(q) for q in questions or []}


def compare_results(bank_questions, reviews):
    """Compare blind-derived answers to the keyed bank.

    reviews: {qid: {"blind_answer": "B", ...}}. Returns per-question
    [{id, bank_key, blind_answer, match}]. Missing reviews => match False.
    """
    keys = {}
    for q in bank_questions or []:
        keys[q.get("id")] = str(q.get("answer_key", q.get("answer", "")))
    out = []
    for qid, key in keys.items():
        r = (reviews or {}).get(qid) or {}
        blind = r.get("blind_answer", r.get("derived_answer", ""))
        out.append({"id": qid, "bank_key": key,
                    "blind_answer": str(blind),
                    "match": bool(blind) and compare_blind(blind, key)})
    return out


def mismatched_ids(comparison_results):
    """IDs whose independently derived answer disagrees with the bank key.

    Accepts the compare_results() list or a {"results": [...]} document.
    """
    if isinstance(comparison_results, dict):
        comparison_results = comparison_results.get("results", [])
    return [r["id"] for r in (comparison_results or [])
            if isinstance(r, dict) and r.get("id") and r.get("match") is False]


def main(argv):  # tiny CLI for pipeline/tests: redact + compare
    import argparse
    from lib_common import load_json, save_json, fail, run_main  # noqa
    ap = argparse.ArgumentParser()
    ap.add_argument("bank")
    ap.add_argument("--reviews", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if not os.path.isfile(a.bank):
        fail("file not found: %s" % a.bank)
    b = load_json(a.bank)
    qs = b.get("questions") if isinstance(b, dict) else b
    if a.reviews:
        rev = load_json(a.reviews)
        if isinstance(rev, dict) and "reviews" in rev:
            rev = rev["reviews"]
        if isinstance(rev, list):
            rev = {r.get("id", r.get("qid")): r for r in rev}
        save_json(a.out, {"results": compare_results(qs, rev)})
    else:
        save_json(a.out, {"payload": redact_bank(qs)})
    print("review_batch: wrote %s" % a.out)
    return 0


if __name__ == "__main__":
    from lib_common import run_main
    sys.exit(run_main(main, sys.argv[1:]))
