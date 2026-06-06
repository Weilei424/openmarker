"""Cooperative cancellation flag for long-running auto-layout runs.

The auto-layout endpoint runs the NFP computation in a worker thread (via
FastAPI's run_in_threadpool). A concurrent /cancel-layout request can set
this module-level flag; the layout loop checks `is_cancelled()` between
piece placements and raises CancellationError to abort.

Why a module-level flag (not a token passed through call args): keeping
the engine API signature unchanged means tests don't need to be aware of
cancellation, and the heuristic module stays single-purpose. The flag is
process-local — appropriate for our single-process desktop engine.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_cancel_requested = False


def request_cancellation() -> None:
    global _cancel_requested
    with _lock:
        _cancel_requested = True


def reset_cancellation() -> None:
    global _cancel_requested
    with _lock:
        _cancel_requested = False


def is_cancelled() -> bool:
    with _lock:
        return _cancel_requested


class CancellationError(RuntimeError):
    """Raised by the layout loop when cancellation has been requested."""


class StoppedWithWarmStart(Exception):
    """Raised by auto_layout_polygon when a GA meta-heuristic run is cancelled
    AFTER the warm-start has been computed. Carries the warm-start result so the
    API layer can return it (HTTP 200) instead of discarding the whole run.

    `result` is the (placements, marker_length_mm, utilization_pct) tuple.
    """

    def __init__(self, result) -> None:
        super().__init__("Optimizer cancelled; returning warm-start result.")
        self.result = result
