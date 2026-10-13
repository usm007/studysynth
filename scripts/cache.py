"""Content-addressed caching, chunking, batch-merge and review-redaction helpers.

Stdlib only. All functions are deterministic and side-effect free except
manifest load/save.
"""
import hashlib
import json
import os

try:
    from lib_common import load_json, save_json
except ImportError:  # pragma: no cover - direct script execution
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lib_common import load_json, save_json


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def sha_obj(obj) -> str:
    return sha_bytes(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":")).encode("utf-8"))


def approx_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def chunk_blocks(blocks, max_tokens=5000, overlap=0):
    """Section-aware chunking for batched extraction.

    Groups consecutive blocks; never splits a logical section merely to hit a
    count. Tables stay intact unless a single table exceeds max_tokens, in
    which case it is split at row boundaries with the header row preserved.
    Returns [{chunk_id, block_ids, blocks}]. Deterministic order.
    """
    chunks = []
    cur = []
    cur_tok = 0
    cur_sec = None

    def sec_of(b):
        sp = b.get("section_path") or ["global"]
        return sp[0] if sp else "global"

    def flush():
        nonlocal cur, cur_tok
        if not cur:
            return
        ids = [b.get("id") for b in cur]
        chunks.append({"chunk_id": "C-" + sha_obj(ids),
                       "block_ids": ids, "blocks": list(cur)})
        cur = []
        cur_tok = 0

    for b in blocks or []:
        sec = sec_of(b)
        if cur and sec != cur_sec and cur_tok >= max_tokens // 2:
            flush()  # section boundary is a natural cut once half-full
        cur_sec = sec if not cur else cur_sec
        t = approx_tokens(b.get("text") or "")
        if b.get("kind") == "table" and t > max_tokens and len(cur) == 0:
            for part in _split_table(b, max_tokens):
                chunks.append({"chunk_id": "C-" + sha_obj(
                    [b.get("id"), part["row_start"]]),
                    "block_ids": [b.get("id")],
                    "blocks": [part["block"]]})
            cur_sec = sec
            continue
        if cur and cur_tok + t > max_tokens:
            flush()
            cur_sec = sec
        cur.append(b)
        cur_tok += t
    flush()
    return chunks


def _split_table(block, max_tokens):
    rows = ((block.get("table") or {}).get("rows") or [])
    if not rows:
        return [{"row_start": 0, "block": block}]
    header, body = rows[0], rows[1:]
    out, cur_rows, start = [], [header], 0
    for i, r in enumerate(body):
        trial = cur_rows + [r]
        t = approx_tokens("\n".join(" | ".join(c) for c in trial))
        if t > max_tokens and len(cur_rows) > 1:
            out.append((start, list(cur_rows)))
            cur_rows, start = [header, r], i
        else:
            cur_rows.append(r)
    out.append((start, cur_rows))
    parts = []
    for s, rr in out:
        nb = dict(block)
        nb["table"] = {"rows": rr,
                       "caption": (block.get("table") or {}).get("caption")}
        nb["text"] = "\n".join(" | ".join(c) for c in rr)
        parts.append({"row_start": s, "block": nb})
    return parts


def unit_identity(u) -> str:
    """Stable source identity for overlap dedup: block + normalized excerpt."""
    import re
    import unicodedata
    src = u.get("source") or {}
    exc = unicodedata.normalize("NFKC", u.get("supporting_excerpt") or "")
    exc = re.sub(r"\s+", " ", exc.lower()).strip()
    return "%s::%s" % (src.get("block_id", "?"), exc)


def dedupe_units_by_identity(units):
    """Drop exact source-identity duplicates from overlapped chunks.

    Never fuzzy-merges distinct facts: only identical (block_id, excerpt)
    pairs collapse. Returns (kept, dropped_ids).
    """
    seen, kept, dropped = {}, [], []
    for u in units or []:
        k = unit_identity(u)
        if k in seen:
            dropped.append(u.get("id"))
        else:
            seen[k] = u.get("id")
            kept.append(u)
    return kept, dropped


def merge_batches(batch_results):
    """Merge per-batch question lists in deterministic batch-index order.

    batch_results: [(batch_index, [questions])]. Raises on duplicate qids.
    """
    merged = []
    seen = set()
    for _, qs in sorted(batch_results, key=lambda x: x[0]):
        for q in qs or []:
            qid = q.get("id")
            if qid in seen:
                raise ValueError("duplicate question id across batches: %s" % qid)
            seen.add(qid)
            merged.append(q)
    return merged


REDACT_TOP = ("answer", "answer_key", "validation", "validation_status",
              "quality_grade", "quality_status", "review", "rejection_labels")
REDACT_STMT = ("truth_value", "truth", "is_true", "correct")
REDACT_OPT = ("is_correct", "covers")


def redact_question(q):
    """Physically remove answer-key material for blind review.

    Strips top-level keys, option flags/covers, statement truth fields and
    prior decisions. Retains labels, stem, options text, excerpts, KU refs.
    """
    import copy
    r = copy.deepcopy(q)
    for k in REDACT_TOP:
        r.pop(k, None)
    for o in r.get("options") or []:
        if isinstance(o, dict):
            for k in REDACT_OPT:
                o.pop(k, None)
    for s in r.get("statements") or []:
        if isinstance(s, dict):
            for k in REDACT_STMT:
                s.pop(k, None)
    return r


def compare_blind(blind_answer, bank_key) -> bool:
    return str(blind_answer).strip().upper() == str(bank_key).strip().upper()


def fingerprint_inputs(paths):
    out = {}
    for p in paths or []:
        out[p] = sha_file(p) if p and os.path.isfile(p) else None
    return out


def load_manifest(path):
    if path and os.path.isfile(path):
        try:
            return load_json(path)
        except Exception:
            return {}
    return {}


def save_manifest(path, manifest):
    if path:
        save_json(path, manifest)


# ---- resumable per-batch progress ledger -------------------------------
# Long LLM phases (extraction chunks, generation batches, review batches)
# record each completed batch id here so an interrupted run resumes pending
# batches instead of starting over. Deterministic stages use artifact_manifest;
# this ledger is for batch streams whose items complete one at a time.

def progress_init(total_ids):
    return {"total": list(total_ids or []), "done": []}


def progress_mark_done(progress, batch_id):
    done = progress.setdefault("done", [])
    if batch_id not in done:
        done.append(batch_id)
    return progress


def progress_pending(progress):
    total = progress.get("total", []) or []
    done = set(progress.get("done", []) or [])
    return [b for b in total if b not in done]


def load_progress(path, total_ids=None):
    if path and os.path.isfile(path):
        try:
            p = load_json(path)
            if isinstance(p, dict) and "done" in p:
                if total_ids is not None:
                    p["total"] = list(total_ids)
                return p
        except Exception:
            pass
    return progress_init(total_ids)


def save_progress(path, progress):
    if path:
        save_json(path, progress)
