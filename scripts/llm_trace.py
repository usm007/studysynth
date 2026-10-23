"""Truthful LLM Call Trace Instrumentation.

Appends structured, non-secret telemetry for each LLM batch request to
`llm_trace.jsonl` in the run directory. Thread-safe for concurrent batch workers.
"""
import json
import os
import threading
import time

_TRACE_LOCK = threading.Lock()


def record_llm_call(
    trace_path,
    stage,
    batch_id,
    batch_fingerprint,
    processing_mode=None,
    model=None,
    provider=None,
    duration_s=None,
    cache_hit=False,
    retry_count=0,
    success=True,
    input_tokens=None,
    output_tokens=None,
    error_category=None,
):
    """Append a truthful trace record to llm_trace.jsonl.

    Never logs raw source content, full prompts, keys, or synthetic tokens.
    `processing_mode` is kept for call compatibility; the single FAST workflow
    records no mode, so the key is omitted unless a caller passes one.
    """
    rec = {
        "timestamp": time.time(),
        "stage": stage,
        "batch_id": batch_id,
        "batch_fingerprint": batch_fingerprint,
        "cache_hit": bool(cache_hit),
        "success": bool(success),
        "retry_count": int(retry_count or 0),
    }
    if processing_mode:
        rec["processing_mode"] = str(processing_mode)
    if duration_s is not None:
        rec["duration_s"] = round(float(duration_s), 4)
    if model:
        rec["model"] = str(model)
    if provider:
        rec["provider"] = str(provider)
    if input_tokens is not None:
        rec["input_tokens"] = int(input_tokens)
    if output_tokens is not None:
        rec["output_tokens"] = int(output_tokens)
    if error_category:
        rec["error_category"] = str(error_category)

    line = json.dumps(rec, sort_keys=True) + "\n"
    with _TRACE_LOCK:
        parent = os.path.dirname(os.path.abspath(trace_path))
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    return rec


class LLMCallTimer:
    """Context manager to measure and record an LLM call using monotonic clock."""

    def __init__(
        self,
        trace_path,
        stage,
        batch_id,
        batch_fingerprint,
        processing_mode=None,
        model=None,
        provider=None,
        retry_count=0,
    ):
        self.trace_path = trace_path
        self.stage = stage
        self.batch_id = batch_id
        self.batch_fingerprint = batch_fingerprint
        self.processing_mode = processing_mode
        self.model = model
        self.provider = provider
        self.retry_count = retry_count
        self._start = None
        self.duration_s = None
        self.input_tokens = None
        self.output_tokens = None
        self.cache_hit = False

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._start is not None:
            self.duration_s = time.monotonic() - self._start
        success = exc_type is None
        err = exc_type.__name__ if exc_type else None
        record_llm_call(
            self.trace_path,
            stage=self.stage,
            batch_id=self.batch_id,
            batch_fingerprint=self.batch_fingerprint,
            processing_mode=self.processing_mode,
            model=self.model,
            provider=self.provider,
            duration_s=self.duration_s,
            cache_hit=self.cache_hit,
            retry_count=self.retry_count,
            success=success,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            error_category=err,
        )
        return False


def load_llm_trace(trace_path):
    """Load trace entries from llm_trace.jsonl."""
    if not trace_path or not os.path.isfile(trace_path):
        return []
    records = []
    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records


def summarize_llm_trace(trace_path):
    """Produce truthful summary of trace records, or None if trace is absent."""
    records = load_llm_trace(trace_path)
    if not records:
        return None
    total_calls = len(records)
    cache_hits = sum(1 for r in records if r.get("cache_hit"))
    cache_misses = total_calls - cache_hits
    total_duration = sum(r.get("duration_s", 0.0) for r in records)
    has_in_tokens = any("input_tokens" in r for r in records)
    has_out_tokens = any("output_tokens" in r for r in records)

    # per-stage rollup: calls, time, retries, tokens (when the provider exposes them)
    by_stage = {}
    for r in records:
        st = str(r.get("stage", "unknown"))
        d = by_stage.setdefault(st, {
            "calls": 0, "duration_s": 0.0, "retries": 0, "failures": 0,
            "cache_hits": 0, "input_tokens": 0, "output_tokens": 0,
            "tokens_observed": False,
        })
        d["calls"] += 1
        d["duration_s"] = round(d["duration_s"] + r.get("duration_s", 0.0), 3)
        d["retries"] += int(r.get("retry_count", 0) or 0)
        d["failures"] += 0 if r.get("success") else 1
        d["cache_hits"] += 1 if r.get("cache_hit") else 0
        if "input_tokens" in r or "output_tokens" in r:
            d["tokens_observed"] = True
            d["input_tokens"] += int(r.get("input_tokens") or 0)
            d["output_tokens"] += int(r.get("output_tokens") or 0)
    for st, d in by_stage.items():
        if not d["tokens_observed"]:
            d["input_tokens"] = "unavailable"
            d["output_tokens"] = "unavailable"
        d["duration_s"] = round(d["duration_s"], 3)
        del d["tokens_observed"]

    summary = {
        "total_calls": total_calls,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "total_duration_s": round(total_duration, 3),
        "retries": sum(r.get("retry_count", 0) for r in records),
        "failures": sum(1 for r in records if not r.get("success")),
        "by_stage": by_stage,
    }
    if has_in_tokens:
        summary["input_tokens"] = sum(r.get("input_tokens", 0) for r in records)
    else:
        summary["input_tokens"] = "unavailable"
    if has_out_tokens:
        summary["output_tokens"] = sum(r.get("output_tokens", 0) for r in records)
    else:
        summary["output_tokens"] = "unavailable"
    return summary


def main(argv):
    """CLI for the model layer: record one observable LLM call.

    The reasoning layer (agent/model harness) invokes this after every model
    request so run_metrics.json can report real call counts, durations, retries
    and token counts instead of marking them unavailable.
    """
    import argparse
    ap = argparse.ArgumentParser(description="Append one LLM call record to a trace file.")
    ap.add_argument("--trace", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--batch", dest="batch_id", required=True)
    ap.add_argument("--fingerprint", default=None)
    ap.add_argument("--duration", dest="duration_s", type=float, default=None)
    ap.add_argument("--input-tokens", dest="input_tokens", type=int, default=None)
    ap.add_argument("--output-tokens", dest="output_tokens", type=int, default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--retries", dest="retry_count", type=int, default=0)
    ap.add_argument("--cache-hit", dest="cache_hit", action="store_true")
    ap.add_argument("--failure", action="store_true")
    ap.add_argument("--error-category", dest="error_category", default=None)
    a = ap.parse_args(argv)
    record_llm_call(
        a.trace, a.stage, a.batch_id, a.fingerprint,
        model=a.model, provider=a.provider,
        duration_s=a.duration_s,
        cache_hit=a.cache_hit,
        retry_count=a.retry_count or 0,
        success=not a.failure,
        input_tokens=a.input_tokens,
        output_tokens=a.output_tokens,
        error_category=a.error_category,
    )
    print("llm_trace: recorded %s/%s -> %s" % (a.stage, a.batch_id, a.trace))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
