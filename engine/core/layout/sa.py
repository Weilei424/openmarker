"""Simulated Annealing meta-heuristic wrapper for NFP-BLF.

Used opt-in via auto_layout_polygon(sa_iterations > 0). See the design spec
at docs/superpowers/specs/2026-05-31-sa-meta-heuristic-design.md for the
algorithm rationale and bench gates.

This module is pure-Python and pure-functional: run_sa() takes an evaluator
callable so it can be tested with a stub. The real evaluator (binding to
_blf_pack_nfp) is constructed at the call site inside heuristic.py.
"""
from __future__ import annotations

import time
from typing import Callable, NamedTuple, TYPE_CHECKING

from core.layout.cancellation import is_cancelled
from core.models.piece import Piece

if TYPE_CHECKING:
    from core.layout.heuristic import Placement

# ---------------------------------------------------------------------------
# Hyperparameter constants. Module-level for visibility; no per-call tunables
# on the public API in the first PR per the design spec (section 2 out-of-scope).
# ---------------------------------------------------------------------------

T0_FACTOR: float = 0.05
"""Initial temperature = T0_FACTOR * initial_marker_length."""

COOLING_ALPHA: float = 0.95
"""Geometric cooling: T_{k+1} = COOLING_ALPHA * T_k."""

T_MIN: float = 1e-3
"""Temperature floor for numerical stability."""

REVERSE_WINDOW_FRACTION: float = 0.25
"""Reverse-move window length cap = ceil(N * REVERSE_WINDOW_FRACTION)."""

NO_GRAINLINE_ROTATION_CAP: int = 4
"""For pieces with no grainline (allowed_rotations returns full 360), keep
only this many evenly-spaced angles: [0, 360/N, 2*360/N, ...]."""

MOVE_WEIGHTS: dict[str, float] = {"swap": 1.0, "reverse": 1.0, "rotation_flip": 1.0}
"""Uniform random pick across move types per iteration."""


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class WarmStart(NamedTuple):
    """One completed warm-start run. The retention list of these is built
    only when sa_iterations > 0 (see heuristic.py).

    Indexing convention for the parallel arrays `sorted_pieces` and
    `rotations_used`: both are positional in the BLF's sort order — entry
    `i` corresponds to the piece at position `i` in `sorted_pieces`. This is
    NOT the same convention as SA's runtime `rotations` array (which is
    indexed by piece position in the unsorted `pieces` list). The
    conversion happens in heuristic.py::_run_sa_chain when each chain
    initializes from its assigned warm-start.
    """
    mode: str                        # BLF mode used ('bi' or 'single')
    sorted_pieces: list[Piece]       # the ordering this run used
    rotations_used: list[float]      # rotations[i] = rotation chosen for sorted_pieces[i]
    placements: list["Placement"]
    marker: float
    util: float


class SAResult(NamedTuple):
    """Returned by run_sa. Best-seen state across the entire chain."""
    best_order: list[int]
    best_rotations: list[float]
    best_placements: list["Placement"]
    best_marker: float
    best_util: float
    iterations_executed: int
    accept_count: int
    improve_count: int


# ---------------------------------------------------------------------------
# Public entry point — implementation in subsequent tasks
# ---------------------------------------------------------------------------


def run_sa(
    initial_order: list[int],
    initial_rotations: list[float],
    pieces: list[Piece],
    allowed_rotations_per_piece: list[list[float]],
    iterations: int,
    max_time_s: float | None,
    seed: int,
    evaluator: Callable[[list[Piece], list[list[float]]], tuple[list["Placement"], float, float]],
    shared_best_value=None,
    clock: Callable[[], float] = time.perf_counter,
) -> SAResult:
    """Run one SA chain. Returns best-seen state.

    Args:
      initial_order: permutation of [0, N) — starting piece order (indices into `pieces`)
      initial_rotations: length-N list; rotations[i] is the rotation for pieces[i]
      pieces: the N pieces being placed (NOT in `initial_order` order)
      allowed_rotations_per_piece: outer length N; inner = allowed rotations for pieces[i]
      iterations: max SA iterations (move attempts)
      max_time_s: wall-clock cap in seconds, or None
      seed: RNG seed for this chain
      evaluator: callable taking (pieces_in_order, per_piece_rotation_singletons) → (placements, marker, util)
      shared_best_value: multiprocessing.Value('d') for cross-worker pruning, or None
      clock: time source (injected for test determinism)
    """
    raise NotImplementedError  # Filled in Task 6
