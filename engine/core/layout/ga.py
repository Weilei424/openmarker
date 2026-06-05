"""Genetic Algorithm meta-heuristic wrapper for NFP-BLF.

Opt-in via auto_layout_polygon(ga_generations > 0). Sibling of sa.py. See
docs/superpowers/specs/2026-06-05-ga-meta-heuristic-design.md.

Pure-functional: run_ga() takes an evaluator callable so it can be tested with
a stub. The real evaluator (binding _blf_pack_nfp) is built in heuristic.py.

GA does NOT use cross-island shared-cutoff pruning (spec section 7): that pruning
only fires on offspring whose marker is >= the current global best, but those are
the recombination stepping-stones GA depends on -- poisoning them collapses the
population. Consequently GA is deterministic per seed.
"""
from __future__ import annotations

import random as _random
import time
from dataclasses import dataclass, field
from typing import Callable, NamedTuple, TYPE_CHECKING

from core.layout.cancellation import is_cancelled
from core.layout.sa import (
    NO_GRAINLINE_ROTATION_CAP,
    _reverse_move,
    _rotation_flip_move,
    _sample_move_type,
    _swap_move,
)
from core.models.piece import Piece

if TYPE_CHECKING:
    from core.layout.heuristic import Placement

# ---------------------------------------------------------------------------
# Hyperparameter constants. Module-level for visibility; also GAConfig field
# defaults (single source of truth). Starting points -- the bench_ga_sweep tunes
# them and bakes the winner before merge (spec sections 9, 10).
# ---------------------------------------------------------------------------
POPULATION_SIZE: int = 30
CROSSOVER_RATE: float = 0.9
MUTATION_RATE: float = 0.2
TOURNAMENT_SIZE: int = 3
ELITISM_COUNT: int = 2
SEED_MUTATION_MOVES: int = 2
"""Moves applied to the warm-start to create each initial-population variant."""
MUTATION_MOVE_WEIGHTS: dict = {"swap": 1.0, "reverse": 1.0, "rotation_flip": 3.0}
"""Mutation move-type weights; rotation_flip favored, matching SA's tuning win."""


@dataclass
class GAConfig:
    """Tunable GA hyperparameters. Field defaults mirror the module constants.
    Picklable so it crosses the ProcessPoolExecutor boundary via initargs."""
    population_size: int = POPULATION_SIZE
    crossover_rate: float = CROSSOVER_RATE
    mutation_rate: float = MUTATION_RATE
    tournament_size: int = TOURNAMENT_SIZE
    elitism_count: int = ELITISM_COUNT
    no_grainline_rotation_cap: int = NO_GRAINLINE_ROTATION_CAP
    seed_mutation_moves: int = SEED_MUTATION_MOVES
    mutation_move_weights: dict = field(default_factory=lambda: dict(MUTATION_MOVE_WEIGHTS))


class GAResult(NamedTuple):
    """Returned by run_ga. Best-seen individual across all generations."""
    best_order: list[int]
    best_rotations: list[float]
    best_placements: list["Placement"]
    best_marker: float
    best_util: float
    generations_executed: int
    evaluations: int


# ---------------------------------------------------------------------------
# Operators. Pure -- they never mutate their inputs. RNG is injected.
# ---------------------------------------------------------------------------


def _order_crossover(p1_order: list[int], p2_order: list[int],
                     rng: _random.Random) -> list[int]:
    """Order Crossover (OX): copy a random contiguous slice of p1 verbatim,
    fill the remaining positions with p2's genes in their p2 order (skipping
    genes already taken). Always returns a valid permutation."""
    n = len(p1_order)
    if n < 2:
        return list(p1_order)
    a, b = sorted(rng.sample(range(n), 2))
    child: list[int | None] = [None] * n
    child[a : b + 1] = p1_order[a : b + 1]
    taken = set(p1_order[a : b + 1])
    fill = [g for g in p2_order if g not in taken]
    f = 0
    for i in range(n):
        if child[i] is None:
            child[i] = fill[f]
            f += 1
    return child  # type: ignore[return-value]


def _uniform_rotation_crossover(r1: list[float], r2: list[float],
                                rng: _random.Random) -> list[float]:
    """Per-gene uniform crossover. Both parents carry valid rotations per piece,
    so the child is valid. Independent of order (rotations are piece-indexed)."""
    return [r1[i] if rng.random() < 0.5 else r2[i] for i in range(len(r1))]


def run_ga(*args, **kwargs):  # implemented in Task 4
    raise NotImplementedError("run_ga is implemented in Task 4")
