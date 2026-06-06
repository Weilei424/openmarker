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
MUTATION_MOVE_WEIGHTS: dict = {"swap": 1.0, "reverse": 1.0, "rotation_flip": 1.0}
"""Mutation move-type weights. UNIFORM (1:1:1) is the tuned default: the
2026-06-05 grain=90 sweep found uniform beats rotation-flip-heavy for GA
(11426.6 vs 11518.8mm at seed 42; < bar on 5/5 seeds). Unlike SA -- which has no
crossover and relied on rotation_flip moves to explore grain choices -- GA's
uniform rotation crossover already recombines per-piece rotations, so mutation is
better spent on order diversity (swap/reverse). See PERFORMANCE.md section 6 [2026-06-05]."""


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


def _tournament_select(fitnesses: list[float], k: int,
                       rng: _random.Random) -> int:
    """Return the index of the lowest-fitness (best) of k random contenders."""
    n = len(fitnesses)
    contenders = rng.sample(range(n), min(k, n))
    return min(contenders, key=lambda j: fitnesses[j])


def _mutate(order: list[int], rotations: list[float],
            allowed_per_piece: list[list[float]], rng: _random.Random,
            weights: dict) -> tuple[list[int], list[float]]:
    """Apply ONE move (swap/reverse/rotation_flip per `weights`). Returns
    (new_order, new_rotations); never mutates inputs. A rotation_flip with no
    flippable piece is a no-op (returns copies)."""
    move = _sample_move_type(rng, weights)
    if move == "swap":
        return _swap_move(order, rng), list(rotations)
    if move == "reverse":
        return _reverse_move(order, rng), list(rotations)
    new_rot, _idx = _rotation_flip_move(rotations, allowed_per_piece, rng)
    return list(order), new_rot


def _seed_variant(order: list[int], rotations: list[float],
                  allowed_per_piece: list[list[float]], rng: _random.Random,
                  weights: dict, moves: int) -> tuple[list[int], list[float]]:
    """Apply `moves` consecutive mutations to seed an initial-population variant."""
    o, r = list(order), list(rotations)
    for _ in range(moves):
        o, r = _mutate(o, r, allowed_per_piece, rng, weights)
    return o, r


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


def run_ga(
    warm_start_order: list[int],
    warm_start_rotations: list[float],
    pieces: list[Piece],
    allowed_rotations_per_piece: list[list[float]],
    generations: int,
    max_time_s: float | None,
    seed: int,
    evaluator: Callable[[list[Piece], list[list[float]]],
                        tuple[list["Placement"], float, float]],
    clock: Callable[[], float] = time.perf_counter,
    config: "GAConfig | None" = None,
) -> GAResult:
    """Run one island GA. Returns the best-seen individual.

    Args mirror sa.run_sa. `evaluator(pieces_in_order, per_piece_rotation_singletons)
    -> (placements, marker, util)`; a ValueError means "infeasible" -> +inf fitness.
    No shared_best_value: GA does not prune (spec section 7), so it is deterministic.
    """
    cfg = GAConfig() if config is None else config
    rng = _random.Random(seed)
    start = clock()

    # Fast path: 0 generations. The phase aggregator retains warm_start_best, so
    # we return an inf sentinel without touching the evaluator (mirrors run_sa).
    if generations == 0:
        return GAResult(list(warm_start_order), list(warm_start_rotations),
                        [], float("inf"), 0.0, 0, 0)

    P = max(2, cfg.population_size)
    weights = cfg.mutation_move_weights

    def _eval(order: list[int], rots: list[float]):
        pieces_in_order = [pieces[idx] for idx in order]
        per_piece = [[rots[idx]] for idx in order]
        try:
            placements, marker, util = evaluator(pieces_in_order, per_piece)
            return marker, util, placements
        except ValueError:
            return float("inf"), 0.0, []

    # Initial population: individual 0 = warm-start; rest = mutated variants.
    pop_orders = [list(warm_start_order)]
    pop_rots = [list(warm_start_rotations)]
    for _ in range(P - 1):
        o, r = _seed_variant(warm_start_order, warm_start_rotations,
                             allowed_rotations_per_piece, rng, weights,
                             cfg.seed_mutation_moves)
        pop_orders.append(o)
        pop_rots.append(r)

    fits: list[float] = []
    utils: list[float] = []
    places: list = []
    evals = 0
    for o, r in zip(pop_orders, pop_rots):
        m, u, pl = _eval(o, r)
        evals += 1
        fits.append(m)
        utils.append(u)
        places.append(pl)

    def _capture_best(gens_done: int) -> GAResult:
        bi = min(range(len(fits)), key=lambda j: fits[j])
        return GAResult(list(pop_orders[bi]), list(pop_rots[bi]), list(places[bi]),
                        fits[bi], utils[bi], gens_done, evals)

    best = _capture_best(0)
    gens_done = 0

    for _gen in range(generations):
        if is_cancelled():
            break
        if max_time_s is not None and (clock() - start) >= max_time_s:
            break

        # Elitism: carry the best `elitism_count` unchanged.
        elite = sorted(range(len(fits)), key=lambda j: fits[j])[: max(0, cfg.elitism_count)]
        new_orders = [list(pop_orders[j]) for j in elite]
        new_rots = [list(pop_rots[j]) for j in elite]
        new_fits = [fits[j] for j in elite]
        new_utils = [utils[j] for j in elite]
        new_places = [list(places[j]) for j in elite]

        while len(new_orders) < P:
            i1 = _tournament_select(fits, cfg.tournament_size, rng)
            i2 = _tournament_select(fits, cfg.tournament_size, rng)
            if rng.random() < cfg.crossover_rate:
                c_order = _order_crossover(pop_orders[i1], pop_orders[i2], rng)
                c_rot = _uniform_rotation_crossover(pop_rots[i1], pop_rots[i2], rng)
            else:
                c_order = list(pop_orders[i1])
                c_rot = list(pop_rots[i1])
            if rng.random() < cfg.mutation_rate:
                c_order, c_rot = _mutate(c_order, c_rot,
                                         allowed_rotations_per_piece, rng, weights)
            m, u, pl = _eval(c_order, c_rot)
            evals += 1
            new_orders.append(c_order)
            new_rots.append(c_rot)
            new_fits.append(m)
            new_utils.append(u)
            new_places.append(pl)

        pop_orders, pop_rots = new_orders, new_rots
        fits, utils, places = new_fits, new_utils, new_places
        gens_done += 1

        candidate = _capture_best(gens_done)
        if candidate.best_marker < best.best_marker:
            best = candidate

    return best._replace(generations_executed=gens_done, evaluations=evals)
