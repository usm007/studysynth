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


def sha_bytes_full(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def sha_file_full(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_obj(obj) -> str:
    return sha_bytes(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":")).encode("utf-8"))


def sha_obj_full(obj) -> str:
    return sha_bytes_full(json.dumps(obj, sort_keys=True, ensure_ascii=False,
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
              "quality_grade", "quality_status", "review", "rejection_labels",
              "confidence", "attempt_count", "correct_count",
              "last_attempted", "last_result", "priority")
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


def atomic_save_json(path, data):
    """Write JSON data to path atomically using a process-and-thread-unique temporary file."""
    if not path:
        return
    path = str(path)
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    import threading
    tid = threading.get_ident()
    tmp_path = "%s.tmp.%d.%d.%d" % (path, os.getpid(), tid, id(data) % 100000)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def load_manifest(path):
    if path and os.path.isfile(path):
        try:
            return load_json(path)
        except Exception:
            return {}
    return {}


def save_manifest(path, manifest):
    if path:
        atomic_save_json(path, manifest)


# ---- content-addressed resumable per-batch progress ledger ------------
# Long LLM phases (extraction chunks, generation batches, review batches)
# record each completed batch fingerprint and output hash so an interrupted
# or modified run only re-executes pending or invalidated batches.

def batch_fingerprint(payload, prompt=None, schema=None, config=None,
                      processing_mode=None, fidelity_mode=None, scope_mode=None,
                      profile=None, model=None, request_params=None,
                      orchestration_version=None, extra=None):
    """Deterministic content-addressed fingerprint for a single batch."""
    # Extract stable block and source content if payload has structured items
    source_texts = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                t = item.get("text") or item.get("supporting_excerpt") or item.get("stem") or ""
                if t:
                    source_texts.append(t)
    elif isinstance(payload, dict):
        for item in payload.get("blocks", payload.get("questions", payload.get("units", []))):
            if isinstance(item, dict):
                t = item.get("text") or item.get("supporting_excerpt") or item.get("stem") or ""
                if t:
                    source_texts.append(t)

    fp = {
        "payload_sha": sha_obj_full(payload) if not isinstance(payload, (str, bytes)) else (
            sha_bytes_full(payload.encode("utf-8")) if isinstance(payload, str) else sha_bytes_full(payload)
        ),
        "source_content_sha": sha_obj_full(source_texts) if source_texts else None,
        "prompt_sha": sha_file_full(prompt) if (isinstance(prompt, str) and os.path.isfile(prompt)) else (
            sha_obj_full(prompt) if prompt else None
        ),
        "schema_sha": sha_file_full(schema) if (isinstance(schema, str) and os.path.isfile(schema)) else (
            sha_obj_full(schema) if schema else None
        ),
        "config_sha": sha_file_full(config) if (isinstance(config, str) and os.path.isfile(config)) else (
            sha_obj_full(config) if config else None
        ),
        "processing_mode": processing_mode,
        "fidelity_mode": fidelity_mode,
        "scope_mode": scope_mode,
        "profile_sha": sha_file_full(profile) if (isinstance(profile, str) and os.path.isfile(profile)) else (
            sha_obj_full(profile) if profile else None
        ),
        "model": model,
        "request_params": request_params or {},
        "orchestration_version": orchestration_version or "1.0",
        "extra": extra or {}
    }
    return sha_obj_full(fp)


def batch_fingerprint_short(fp: str) -> str:
    """Derive short display identifier from full fingerprint."""
    return (fp or "")[:16]


def progress_init(total_ids=None):
    return {"total": list(total_ids or []), "done": [], "batches": {}}


def progress_record_batch(progress, batch_id, fingerprint, output_path,
                          validation_status="valid", completed=True,
                          stage=None):
    """Record completed and validated batch entry atomically."""
    if "batches" not in progress:
        progress["batches"] = {}
    out_sha = sha_file_full(output_path) if output_path and os.path.isfile(output_path) else None

    # Verify output file exists and is valid JSON before declaring completed
    is_valid_output = False
    if out_sha is not None and validation_status == "valid":
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                json.load(f)
            is_valid_output = True
        except Exception:
            is_valid_output = False
            validation_status = "malformed_json"

    is_done = bool(completed and is_valid_output)
    progress["batches"][batch_id] = {
        "batch_id": batch_id,
        "stage": stage,
        "fingerprint": fingerprint,
        "output_path": output_path,
        "output_hash": out_sha,
        "validation_status": validation_status,
        "completed": is_done
    }
    done = progress.setdefault("done", [])
    if is_done and batch_id not in done:
        done.append(batch_id)
    elif (not is_done) and batch_id in done:
        done.remove(batch_id)
    return progress


def progress_mark_done(progress, batch_id):
    """Backward-compatible mark_done helper."""
    done = progress.setdefault("done", [])
    if batch_id not in done:
        done.append(batch_id)
    if "batches" not in progress:
        progress["batches"] = {}
    if batch_id not in progress["batches"]:
        progress["batches"][batch_id] = {
            "batch_id": batch_id,
            "fingerprint": None,
            "output_path": None,
            "output_hash": None,
            "validation_status": "legacy",
            "completed": True
        }
    return progress


def can_reuse_batch(entry, current_fingerprint, validator_fn=None, expected_stage=None, expected_batch_id=None):
    """Check if recorded batch result is reusable.
    Verifies all 7 requirements:
    1. Recorded fingerprint matches current full fingerprint.
    2. Referenced output exists.
    3. Output hash matches recorded output hash.
    4. Output parses successfully (valid JSON).
    5. Output passes applicable schema and structural validation.
    6. Output belongs to expected batch and stage (when specified).
    7. Batch has a valid completed state.
    """
    if not isinstance(entry, dict):
        return False
    if not entry.get("completed"):
        return False
    if current_fingerprint is not None and entry.get("fingerprint") != current_fingerprint:
        return False
    if expected_batch_id is not None and entry.get("batch_id") != expected_batch_id:
        return False
    if expected_stage is not None and entry.get("stage") != expected_stage:
        return False
    out_path = entry.get("output_path")
    if not out_path or not os.path.isfile(out_path):
        return False
    expected_hash = entry.get("output_hash")
    if expected_hash and sha_file(out_path) != expected_hash and sha_file_full(out_path) != expected_hash:
        return False
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
    except Exception:
        return False
    if entry.get("validation_status") != "valid":
        return False
    if validator_fn:
        try:
            val_ok = False
            try:
                val_ok = validator_fn(parsed)
            except TypeError:
                val_ok = validator_fn(out_path)
            if not val_ok:
                return False
        except Exception:
            return False
    return True


def progress_pending(progress, batch_fingerprints=None, validator_fn=None, stage=None):
    """Return list of pending batch IDs.
    If batch_fingerprints dict {batch_id: fp} is provided, validates that completed
    entries match their fingerprint, output hash, and schema validation.
    Marks stale or invalid batches explicitly.
    """
    total = progress.get("total", []) or []
    batches = progress.get("batches", {}) or {}
    done = set(progress.get("done", []) or [])
    if batch_fingerprints is not None:
        pending = []
        for b in total:
            entry = batches.get(b)
            curr_fp = batch_fingerprints.get(b)
            if not can_reuse_batch(entry, curr_fp, validator_fn, expected_stage=stage, expected_batch_id=b):
                if entry and isinstance(entry, dict):
                    entry["completed"] = False
                    entry["stale"] = True
                done.discard(b)
                pending.append(b)
        progress["done"] = sorted(list(done))
        return pending
    # Legacy fallback: check done list
    return [b for b in total if b not in done]


def load_progress(path, total_ids=None):
    if path and os.path.isfile(path):
        try:
            p = load_json(path)
            if isinstance(p, dict):
                if "batches" not in p:
                    # Safely migrate legacy progress entries without losing done list
                    p["batches"] = {}
                    p["legacy_migrated"] = True
                    for bid in p.get("done", []):
                        p["batches"][bid] = {
                            "batch_id": bid,
                            "fingerprint": None,
                            "completed": True,
                            "validation_status": "legacy",
                        }
                if total_ids is not None:
                    p["total"] = list(total_ids)
                return p
        except Exception:
            pass
    return progress_init(total_ids)


def save_progress(path, progress):
    if path:
        atomic_save_json(path, progress)


def execute_batch_pool(
    batches,
    worker_fn,
    max_concurrency=4,
    max_retries=2,
    backoff_factor=0.05,
    on_progress=None,
    max_workers=None,
    initial_backoff=None,
):
    """Execute batches with bounded concurrency, retry on transient errors with backoff,
    fast-abort on permanent errors, and deterministic ordered result merging.
    
    batches: list of items/tuples to process.
    worker_fn: fn(batch) -> result. May raise Exception on failure.
    max_concurrency: maximum in-flight concurrent worker threads.
    max_retries: maximum retries for retryable errors.
    backoff_factor: base delay for exponential backoff in seconds.
    on_progress: optional callback fn(completed_count, total_count).
    
    Returns: list of results in original batch order.
    """
    import concurrent.futures
    import time
    if max_workers is not None:
        max_concurrency = max_workers
    if initial_backoff is not None:
        backoff_factor = initial_backoff

    if not batches:
        return []

    results = [None] * len(batches)
    PERMANENT_ERRORS = (ValueError, TypeError, KeyError, json.JSONDecodeError)

    def run_one(idx, item):
        attempt = 0
        while True:
            try:
                res = worker_fn(item)
                return idx, res, None
            except PERMANENT_ERRORS as pe:
                # Fast fail permanent schema/config/value errors without useless retries
                return idx, None, pe
            except Exception as e:
                attempt += 1
                if attempt > max_retries:
                    return idx, None, e
                delay = backoff_factor * (2 ** (attempt - 1))
                time.sleep(delay)

    errors = []
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as pool:
        futures = {pool.submit(run_one, i, b): i for i, b in enumerate(batches)}
        for fut in concurrent.futures.as_completed(futures):
            idx, res, err = fut.result()
            if err is not None:
                errors.append((idx, err))
            else:
                results[idx] = res
            completed += 1
            if on_progress:
                try:
                    on_progress(completed, len(batches))
                except Exception:
                    pass

    if errors:
        first_err = sorted(errors, key=lambda x: x[0])[0][1]
        raise first_err
    return results

