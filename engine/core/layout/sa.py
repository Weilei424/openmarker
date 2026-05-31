"""Simulated Annealing meta-heuristic wrapper for NFP-BLF.

Used opt-in via auto_layout_polygon(sa_iterations > 0). See the design spec
at docs/superpowers/specs/2026-05-31-sa-meta-heuristic-design.md for the
algorithm rationale and bench gates.

This module is pure-Python and pure-functional: run_sa() takes an evaluator
callable so it can be tested with a stub. The real evaluator (binding to
_blf_pack_nfp) is constructed at the call site inside heuristic.py.
"""
from __future__ import annotations

import math
import random as _random
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
# Move operators. Each takes the current state plus an RNG and returns
# the proposed neighbor state. Operators are pure — they do not mutate inputs.
# ---------------------------------------------------------------------------


def _swap_move(order: list[int], rng: _random.Random) -> list[int]:
    """Pick two distinct indices uniformly at random and swap them."""
    n = len(order)
    if n < 2:
        return list(order)
    i, j = rng.sample(range(n), 2)
    new_order = list(order)
    new_order[i], new_order[j] = new_order[j], new_order[i]
    return new_order


def _reverse_move(order: list[int], rng: _random.Random) -> list[int]:
    """Reverse a contiguous slice of `order`. Window length is uniform in
    [2, cap] where cap = ceil(N * REVERSE_WINDOW_FRACTION). Window position
    is uniform-random subject to staying within bounds."""
    n = len(order)
    if n < 2:
        return list(order)
    cap = max(2, math.ceil(n * REVERSE_WINDOW_FRACTION))
    cap = min(cap, n)
    window_len = rng.randint(2, cap)
    start = rng.randint(0, n - window_len)
    new_order = list(order)
    new_order[start : start + window_len] = reversed(new_order[start : start + window_len])
    return new_order


def _rotation_flip_move(
    rotations: list[float],
    allowed_per_piece: list[list[float]],
    rng: _random.Random,
) -> tuple[list[float], int | None]:
    """Pick a piece uniformly at random whose allowed list has 2+ options,
    and resample its rotation from that list excluding the current value.

    Returns (new_rotations, flipped_piece_index). If NO piece has 2+ options,
    returns (unchanged_rotations, None) so the caller can pick a different move."""
    flippable = [i for i, alts in enumerate(allowed_per_piece) if len(alts) >= 2]
    if not flippable:
        return list(rotations), None
    piece_index = rng.choice(flippable)
    alternatives = [r for r in allowed_per_piece[piece_index] if r != rotations[piece_index]]
    if not alternatives:
        # This piece's "allowed" list has 2+ entries but all equal the current value
        # (shouldn't happen with normal grain data, but be defensive).
        return list(rotations), None
    new_rotations = list(rotations)
    new_rotations[piece_index] = rng.choice(alternatives)
    return new_rotations, piece_index


def _sample_move_type(rng: _random.Random) -> str:
    """Pick a move type per MOVE_WEIGHTS distribution."""
    move_types = list(MOVE_WEIGHTS.keys())
    weights = [MOVE_WEIGHTS[m] for m in move_types]
    return rng.choices(move_types, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Cooling + acceptance helpers
# ---------------------------------------------------------------------------


def _temperature_at(T0: float, k: int) -> float:
    """Geometric cooling with T_MIN floor."""
    return max(T_MIN, T0 * (COOLING_ALPHA ** k))


def _metropolis_accept(delta: float, T: float, rng: _random.Random) -> bool:
    """Standard Metropolis criterion.
    - delta <= 0  → accept (strictly better OR equal)
    - delta > 0   → accept with probability exp(-delta / T)"""
    if delta <= 0:
        return True
    return rng.random() < math.exp(-delta / T)


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
    n = len(pieces)
    rng = _random.Random(seed)

    # Capture start_time BEFORE any work (including initial evaluation) so
    # max_time_s genuinely bounds wall-clock from caller's perspective.
    start_time = clock()

    # Fast-path: no iterations requested — return initial state without
    # touching the evaluator (some tests assert zero evaluator calls here).
    if iterations == 0:
        return SAResult(
            best_order=list(initial_order),
            best_rotations=list(initial_rotations),
            best_placements=[],
            best_marker=float("inf"),
            best_util=0.0,
            iterations_executed=0,
            accept_count=0,
            improve_count=0,
        )

    # Evaluate the initial state once to seed `current`/`best`/`T0`.
    init_pieces_in_order = [pieces[idx] for idx in initial_order]
    init_per_piece_rots = [[initial_rotations[idx]] for idx in initial_order]
    init_placements, init_marker, init_util = evaluator(init_pieces_in_order, init_per_piece_rots)

    current_order = list(initial_order)
    current_rotations = list(initial_rotations)
    current_marker = init_marker

    best_order = list(initial_order)
    best_rotations = list(initial_rotations)
    best_placements = init_placements
    best_marker = init_marker
    best_util = init_util

    T0 = max(T_MIN, T0_FACTOR * init_marker)
    accept_count = 0
    improve_count = 0
    iteration = 0

    while iteration < iterations:
        # Termination checks: cancellation, wall-clock cap.
        if is_cancelled():
            break
        if max_time_s is not None and (clock() - start_time) >= max_time_s:
            break

        # Sample neighbor. Up to 3 tries to pick a non-no-op move when
        # rotation_flip lands on a chain of all-1-allowed pieces.
        new_order = current_order
        new_rotations = current_rotations
        for _retry in range(3):
            move_type = _sample_move_type(rng)
            if move_type == "swap":
                new_order = _swap_move(current_order, rng)
                new_rotations = current_rotations
                break
            elif move_type == "reverse":
                new_order = _reverse_move(current_order, rng)
                new_rotations = current_rotations
                break
            else:  # rotation_flip
                flipped_rots, flipped_idx = _rotation_flip_move(
                    current_rotations, allowed_rotations_per_piece, rng
                )
                if flipped_idx is not None:
                    new_order = current_order
                    new_rotations = flipped_rots
                    break
                # else: retry with a different move type
        else:
            # All 3 retries hit no-op pieces. Fall through with `current` —
            # the next iteration will try again. Counts as one iteration burned.
            iteration += 1
            continue

        # Evaluate neighbor. Treat ValueError as "infinitely bad" → reject.
        try:
            pieces_in_order = [pieces[idx] for idx in new_order]
            per_piece_rots = [[new_rotations[idx]] for idx in new_order]
            new_placements, new_marker, new_util = evaluator(pieces_in_order, per_piece_rots)
        except ValueError:
            iteration += 1
            continue

        # Metropolis acceptance.
        T_k = _temperature_at(T0, iteration)
        delta = new_marker - current_marker
        if _metropolis_accept(delta, T_k, rng):
            current_order = new_order
            current_rotations = new_rotations
            current_marker = new_marker
            accept_count += 1
            # Track best-seen.
            if new_marker < best_marker:
                best_order = list(new_order)
                best_rotations = list(new_rotations)
                best_placements = new_placements
                best_marker = new_marker
                best_util = new_util
                improve_count += 1

        iteration += 1

    return SAResult(
        best_order=best_order,
        best_rotations=best_rotations,
        best_placements=best_placements,
        best_marker=best_marker,
        best_util=best_util,
        iterations_executed=iteration,
        accept_count=accept_count,
        improve_count=improve_count,
    )
