"""Module-level progress snapshot for the (single-flight) layout run.

The desktop app runs one layout at a time — it already has ONE global
cancellation flag and one engine process — and this module mirrors that
assumption: one module-level snapshot, replaced by a single assignment so
readers never observe a half-written dict. `get_progress` returns a copy so
callers cannot mutate the live snapshot.
"""
from __future__ import annotations

_IDLE: dict = {"active": False}
_snapshot: dict = dict(_IDLE)


def set_progress(**fields) -> None:
    """Replace the whole snapshot (atomic single assignment)."""
    global _snapshot
    _snapshot = dict(fields)


def get_progress() -> dict:
    """Return a copy of the current snapshot."""
    return dict(_snapshot)


def clear_progress() -> None:
    """Reset to idle. For test isolation only — the run path never clears;
    it leaves a final snapshot that the next run overwrites."""
    global _snapshot
    _snapshot = dict(_IDLE)
