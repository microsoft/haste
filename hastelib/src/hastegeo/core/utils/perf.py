# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Lightweight, opt-in performance instrumentation.

Counts and times logical data-layer operations for a single request. A bulk
operation can issue multiple backend SDK requests, so these values are not
storage transaction counts.

Design notes:
- A ``ContextVar`` holds a shared ``PerfCounter`` *object*. ``asyncio.to_thread``
  copies the current context into the worker thread, so a read method running in
  the thread sees the *same* counter instance and its (lock-guarded) mutations are
  visible back in the calling coroutine. The ContextVar value (the reference) is
  never reassigned inside the thread, only the object it points to is mutated.
- When tracking is not enabled, ``timed()`` is a no-op with no measurable overhead,
  so instrumenting the shared data layer is safe for every caller (API + queues).
"""
import contextvars
import threading
import time
from contextlib import contextmanager

_current: "contextvars.ContextVar[PerfCounter | None]" = (
    contextvars.ContextVar("haste_perf_counter", default=None)
)


class PerfCounter:
    """Thread-safe accumulator of logical data-layer calls and duration."""

    def __init__(self):
        self.calls = 0
        self.seconds = 0.0
        self.by_op = {}
        self._lock = threading.Lock()

    def record(self, op, elapsed):
        with self._lock:
            self.calls += 1
            self.seconds += elapsed
            entry = self.by_op.get(op)
            if entry is None:
                self.by_op[op] = {"calls": 1, "seconds": elapsed}
            else:
                entry["calls"] += 1
                entry["seconds"] += elapsed


def begin(enabled=True):
    """Start tracking for the current context. Returns the counter (or None)."""
    if not enabled:
        _current.set(None)
        return None
    counter = PerfCounter()
    _current.set(counter)
    return counter


def end():
    """Stop tracking for the current context."""
    _current.set(None)


def get_counter():
    return _current.get()


@contextmanager
def bind(counter):
    """Bind ``counter`` as the active counter for the current context.

    Used to propagate the active counter into worker threads (e.g. a
    ``ThreadPoolExecutor``), which — unlike ``asyncio.to_thread`` — do not copy
    the parent context. ``counter`` may be ``None`` (tracking disabled).
    """
    token = _current.set(counter)
    try:
        yield
    finally:
        _current.reset(token)


@contextmanager
def timed(op):
    """Time an ``op`` and record it on the active counter, if any.

    Zero-overhead when tracking is disabled (no active counter).
    """
    counter = _current.get()
    if counter is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        counter.record(op, time.perf_counter() - start)


def headers(counter, wall_start):
    """Response headers exposing data-layer call timing for benchmarking."""
    if counter is None:
        return {}
    storage_ms = counter.seconds * 1000.0
    wall_ms = (time.perf_counter() - wall_start) * 1000.0
    return {
        "X-Haste-Data-Layer-Calls": str(counter.calls),
        "X-Haste-Data-Layer-Ms": f"{storage_ms:.1f}",
        # Keep the original names while benchmark consumers migrate.
        "X-Haste-Storage-Calls": str(counter.calls),
        "X-Haste-Storage-Ms": f"{storage_ms:.1f}",
        "X-Haste-Wall-Ms": f"{wall_ms:.1f}",
        "Server-Timing": ", ".join(
            [
                ";".join(
                    ["data-layer", "desc=data-layer", f"dur={storage_ms:.1f}"]
                ),
                ";".join(["wall", "desc=wall", f"dur={wall_ms:.1f}"]),
            ]
        ),
    }


def log_summary(logger, name, counter, wall_start, **fields):
    """Emit a single structured ``PERF`` line and stop tracking."""
    if counter is None:
        return
    wall_ms = (time.perf_counter() - wall_start) * 1000.0
    ops = {
        op: {"calls": e["calls"], "ms": round(e["seconds"] * 1000, 1)}
        for op, e in counter.by_op.items()
    }
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.info(
        "PERF %s %s data_layer_calls=%d data_layer_ms=%.1f wall_ms=%.1f ops=%s",
        name,
        extra,
        counter.calls,
        counter.seconds * 1000.0,
        wall_ms,
        ops,
    )
    end()
