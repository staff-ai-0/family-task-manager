"""In-process, best-effort application counters.

Hand-rolled — deliberately NO ``prometheus_client`` dependency. This module
holds only cheap, process-lifetime counters (things that can't be derived from
a DB query). Gauges (families total, active users, …) are computed on demand by
the ``/metrics`` route from a handful of ``COUNT`` queries — they do NOT live
here.

Multi-worker caveat: prod runs several uvicorn workers, each with its own copy
of these counters. A scrape hits whichever worker answers, so counter values are
per-worker and best-effort — fine for rate/trend signals, not for exact totals.
See ``docs/OBSERVABILITY.md``.
"""

from __future__ import annotations

import threading

# A lock keeps increments coherent even though the FastAPI event loop is
# single-threaded: the blocking LLM calls are offloaded to a threadpool, and a
# future refactor could bump a counter from a worker thread. Contention is
# negligible (a couple of integer writes).
_lock = threading.Lock()

_counters: dict[str, int] = {
    # Best-effort count of outbound LLM/vision calls made by this process since
    # startup. Incremented at each call site (jarvis, receipt/calendar scanners,
    # recipe/translation, task-proof + budget categorizer). Resets on restart —
    # that's a normal counter reset and Prometheus handles it.
    "llm_calls_total": 0,
}


def increment(name: str, amount: int = 1) -> None:
    """Bump a counter. Best-effort: never raises into the caller's hot path."""
    try:
        with _lock:
            _counters[name] = _counters.get(name, 0) + amount
    except Exception:
        # A metrics bump must never break the thing it's measuring.
        pass


def record_llm_call() -> None:
    """Convenience: increment the outbound-LLM-call counter."""
    increment("llm_calls_total")


def snapshot() -> dict[str, int]:
    """Return a copy of the current counter values."""
    with _lock:
        return dict(_counters)
