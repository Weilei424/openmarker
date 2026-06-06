# GA Meta-Heuristic Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, island-model Genetic Algorithm meta-heuristic that wraps the NFP-BLF packer as its fitness function, sitting beside the shipped SA wrapper, and either beat the 11699 mm bar across ≥3 seeds or ship with a documented gap analysis.

**Architecture:** New pure-functional `engine/core/layout/ga.py` (`run_ga` + operators + `GAConfig`/`GAResult`), reusing `sa.py`'s move operators. Orchestration in `heuristic.py` mirrors the SA trio (`_init_ga_worker` / `_run_ga_chain` / `_run_ga_phase`) over the existing `ProcessPoolExecutor`. Opt-in via new `ga_*` params on `auto_layout_polygon`. GA does **not** use cross-island shared-cutoff pruning, so it is deterministic per seed (spec §7).

**Tech Stack:** Python 3.11, dataclasses, `concurrent.futures.ProcessPoolExecutor`, pytest. Geometry via the existing `_blf_pack_nfp`.

**Spec:** `docs/superpowers/specs/2026-06-05-ga-meta-heuristic-design.md`.

---

## Conventions (read once)

- **All paths below are inside the worktree** `D:\openmarker\.worktrees\ga-meta-heuristic\`.
- **Run tests** with the main-tree venv Python against worktree source (the test files `sys.path.insert` the worktree engine dir, so cwd doesn't matter):
  ```
  D:\openmarker\engine\.venv\Scripts\python.exe -m pytest <test-path> -v
  ```
- **Fixtures** (`examples/input/*.dxf`) are already staged in the worktree.
- **Commit in the worktree, never push** (user must approve push):
  ```
  git -C D:\openmarker\.worktrees\ga-meta-heuristic add <paths>
  git -C D:\openmarker\.worktrees\ga-meta-heuristic commit -m "<msg>" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
  ```
- **TDD:** write the failing test, run it red, implement minimally, run it green, commit. One logical change per commit.

---

## File Structure

**Create**
- `engine/core/layout/ga.py` — constants, `GAConfig`, `GAResult`, operators (`_order_crossover`, `_uniform_rotation_crossover`, `_tournament_select`, `_mutate`, `_seed_variant`), `run_ga`.
- `engine/tests/unit/test_ga.py` — operator + driver unit tests (stub evaluator).
- `engine/tests/bench_ga.py` — G1–G5 acceptance gates on the canonical workload.
- `engine/tests/bench_ga_sweep.py` — hyperparameter sweep (TTL + always-writes-a-report), adapted from `bench_sa_sweep.py`.

**Modify**
- `engine/core/layout/heuristic.py` — GA worker globals, `_init_ga_worker`, `_run_ga_chain`, `_run_ga_phase`, `auto_layout_polygon` (`ga_*` params, validation, retention widening, phase calls).
- `engine/tests/unit/test_heuristic.py` — GA integration tests.
- `docs/planning/PERFORMANCE.md`, `docs/planning/BACKLOG.md` — docs (Task 9).

---

## Task 1: `ga.py` foundation — constants, `GAConfig`, `GAResult`

**Files:**
- Create: `engine/core/layout/ga.py`
- Test: `engine/tests/unit/test_ga.py`

- [ ] **Step 1: Write the failing test**

Create `engine/tests/unit/test_ga.py`:
```python
"""Unit tests for the GA meta-heuristic driver. Uses stub evaluators
(no real BLF) so tests are deterministic and fast."""
import os
import pickle
import random
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.layout import ga
from core.models.piece import Piece, BoundingBox


def _p(piece_id: str, w: float = 100, h: float = 50) -> Piece:
    """Minimal Piece for stub-evaluator tests. id encodes the index."""
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True, validation_notes=[], grainline_direction_deg=0.0,
    )


def test_ga_module_exports_and_config_defaults():
    assert callable(ga.run_ga)
    assert hasattr(ga, "GAConfig")
    assert hasattr(ga, "GAResult")
    cfg = ga.GAConfig()
    assert cfg.population_size == ga.POPULATION_SIZE
    assert cfg.crossover_rate == ga.CROSSOVER_RATE
    assert cfg.mutation_rate == ga.MUTATION_RATE
    assert cfg.tournament_size == ga.TOURNAMENT_SIZE
    assert cfg.elitism_count == ga.ELITISM_COUNT
    assert cfg.no_grainline_rotation_cap == ga.NO_GRAINLINE_ROTATION_CAP
    assert cfg.mutation_move_weights == ga.MUTATION_MOVE_WEIGHTS
    # rotation_flip favored, matching SA's tuning win (spec §5.4).
    assert cfg.mutation_move_weights["rotation_flip"] == 3.0
    # Sanity bounds.
    assert cfg.population_size >= 2
    assert 0.0 <= cfg.crossover_rate <= 1.0
    assert 0.0 <= cfg.mutation_rate <= 1.0
    assert cfg.tournament_size >= 2
    assert 0 <= cfg.elitism_count < cfg.population_size


def test_ga_config_picklable():
    """GAConfig must cross the ProcessPoolExecutor boundary (initargs)."""
    cfg = ga.GAConfig(population_size=12)
    restored = pickle.loads(pickle.dumps(cfg))
    assert restored.population_size == 12
    assert restored.mutation_move_weights == ga.MUTATION_MOVE_WEIGHTS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_ga.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.layout.ga'`.

- [ ] **Step 3: Write minimal implementation**

Create `engine/core/layout/ga.py`:
```python
"""Genetic Algorithm meta-heuristic wrapper for NFP-BLF.

Opt-in via auto_layout_polygon(ga_generations > 0). Sibling of sa.py. See
docs/superpowers/specs/2026-06-05-ga-meta-heuristic-design.md.

Pure-functional: run_ga() takes an evaluator callable so it can be tested with
a stub. The real evaluator (binding _blf_pack_nfp) is built in heuristic.py.

GA does NOT use cross-island shared-cutoff pruning (spec §7): that pruning only
fires on offspring whose marker is >= the current global best, but those are the
recombination stepping-stones GA depends on — poisoning them collapses the
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
# defaults (single source of truth). Starting points — the bench_ga_sweep tunes
# them and bakes the winner before merge (spec §9, §10).
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_ga.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```
git -C D:\openmarker\.worktrees\ga-meta-heuristic add engine/core/layout/ga.py engine/tests/unit/test_ga.py
git -C D:\openmarker\.worktrees\ga-meta-heuristic commit -m "feat(ga): GAConfig + GAResult foundation" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Crossover operators

**Files:**
- Modify: `engine/core/layout/ga.py`
- Test: `engine/tests/unit/test_ga.py`

- [ ] **Step 1: Write the failing test** (append to `test_ga.py`)

```python
def test_order_crossover_produces_valid_permutation():
    rng = random.Random(3)
    p1 = list(range(10))
    p2 = [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
    for _ in range(50):
        child = ga._order_crossover(p1, p2, rng)
        assert sorted(child) == list(range(10))  # valid permutation, no dupes/omissions


def test_order_crossover_preserves_a_parent1_slice():
    """OX copies a contiguous slice from parent1 verbatim; the rest comes from
    parent2 in order. With identical parents the child equals the parent."""
    rng = random.Random(0)
    p = list(range(8))
    assert ga._order_crossover(p, p, rng) == p


def test_uniform_rotation_crossover_inherits_only_parent_values():
    rng = random.Random(1)
    r1 = [0.0, 0.0, 180.0, 90.0]
    r2 = [180.0, 0.0, 0.0, 270.0]
    for _ in range(50):
        child = ga._uniform_rotation_crossover(r1, r2, rng)
        assert len(child) == 4
        for i in range(4):
            assert child[i] in (r1[i], r2[i])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_ga.py -v -k crossover`
Expected: FAIL — `AttributeError: module 'core.layout.ga' has no attribute '_order_crossover'`.

- [ ] **Step 3: Write minimal implementation** (append to `ga.py`, after the dataclasses)

```python
# ---------------------------------------------------------------------------
# Operators. Pure — they never mutate their inputs. RNG is injected.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_ga.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 5: Commit**

```
git -C D:\openmarker\.worktrees\ga-meta-heuristic add engine/core/layout/ga.py engine/tests/unit/test_ga.py
git -C D:\openmarker\.worktrees\ga-meta-heuristic commit -m "feat(ga): order + uniform-rotation crossover operators" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Selection, mutation, and seeding helpers

**Files:**
- Modify: `engine/core/layout/ga.py`
- Test: `engine/tests/unit/test_ga.py`

- [ ] **Step 1: Write the failing test** (append to `test_ga.py`)

```python
def test_tournament_select_returns_lowest_fitness_contender():
    """With tournament_size == population, the global best (min fitness) wins."""
    rng = random.Random(0)
    fitnesses = [5.0, 2.0, 9.0, 1.0, 7.0]
    winner = ga._tournament_select(fitnesses, k=5, rng=rng)
    assert winner == 3  # index of 1.0


def test_mutate_dispatches_to_sa_moves_and_changes_state():
    """rotation_flip-only weights must change rotations, not order."""
    rng = random.Random(2)
    order = list(range(6))
    rotations = [0.0] * 6
    allowed = [[0.0, 180.0]] * 6
    weights = {"swap": 0.0, "reverse": 0.0, "rotation_flip": 1.0}
    new_order, new_rot = ga._mutate(order, rotations, allowed, rng, weights)
    assert new_order == order          # rotation_flip leaves order untouched
    assert new_rot != rotations         # exactly one rotation flipped to 180
    assert sum(1 for i in range(6) if new_rot[i] != rotations[i]) == 1


def test_mutate_swap_only_changes_order_not_rotations():
    rng = random.Random(4)
    order = list(range(6))
    rotations = [0.0] * 6
    allowed = [[0.0, 180.0]] * 6
    weights = {"swap": 1.0, "reverse": 0.0, "rotation_flip": 0.0}
    new_order, new_rot = ga._mutate(order, rotations, allowed, rng, weights)
    assert sorted(new_order) == list(range(6))
    assert new_rot == rotations


def test_seed_variant_keeps_valid_permutation_and_allowed_rotations():
    rng = random.Random(5)
    order = list(range(8))
    rotations = [0.0] * 8
    allowed = [[0.0, 180.0]] * 8
    o, r = ga._seed_variant(order, rotations, allowed, rng,
                            ga.MUTATION_MOVE_WEIGHTS, moves=3)
    assert sorted(o) == list(range(8))
    for i in range(8):
        assert r[i] in allowed[i]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_ga.py -v -k "tournament or mutate or seed_variant"`
Expected: FAIL — `_tournament_select` undefined.

- [ ] **Step 3: Write minimal implementation** (append to `ga.py`)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_ga.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git -C D:\openmarker\.worktrees\ga-meta-heuristic add engine/core/layout/ga.py engine/tests/unit/test_ga.py
git -C D:\openmarker\.worktrees\ga-meta-heuristic commit -m "feat(ga): tournament selection, mutation dispatch, seeding" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `run_ga` driver

**Files:**
- Modify: `engine/core/layout/ga.py`
- Test: `engine/tests/unit/test_ga.py`

- [ ] **Step 1: Write the failing test** (append to `test_ga.py`)

```python
def _index_inversion_stub():
    """Stub evaluator: marker = order-inversions + count(rotation != 0).
    Optimum (marker 0) = ascending order + all rotations 0. Counts calls."""
    calls = {"n": 0}

    def ev(pieces_in_order, per_piece_rots):
        calls["n"] += 1
        order = [int(p.id) for p in pieces_in_order]
        inv = sum(1 for i in range(len(order)) for j in range(i + 1, len(order))
                  if order[i] > order[j])
        flips = sum(1 for r in per_piece_rots if r[0] != 0.0)
        marker = float(inv + flips)
        return ([("pl", marker)], marker, 50.0)

    return ev, calls


def test_run_ga_zero_generations_is_fast_path_no_eval():
    pieces = [_p(str(i)) for i in range(5)]
    ev, calls = _index_inversion_stub()
    res = ga.run_ga(
        warm_start_order=list(range(5)), warm_start_rotations=[0.0] * 5,
        pieces=pieces, allowed_rotations_per_piece=[[0.0, 180.0]] * 5,
        generations=0, max_time_s=None, seed=1, evaluator=ev,
    )
    assert calls["n"] == 0
    assert res.generations_executed == 0
    assert res.best_marker == float("inf")


def test_run_ga_is_monotone_non_worsening_vs_warm_start():
    pieces = [_p(str(i)) for i in range(8)]
    ev, _ = _index_inversion_stub()
    warm_order = [7, 6, 5, 4, 3, 2, 1, 0]      # fully reversed (28 inversions)
    warm_rot = [180.0] * 8                       # 8 flips → warm marker 36
    res = ga.run_ga(
        warm_start_order=warm_order, warm_start_rotations=warm_rot,
        pieces=pieces, allowed_rotations_per_piece=[[0.0, 180.0]] * 8,
        generations=10, max_time_s=None, seed=42, evaluator=ev,
        config=ga.GAConfig(population_size=16, mutation_rate=0.6),
    )
    # Warm-start marker = 28 + 8 = 36; GA best must never exceed it.
    assert res.best_marker <= 36.0


def test_run_ga_improves_on_a_suboptimal_start():
    pieces = [_p(str(i)) for i in range(8)]
    ev, _ = _index_inversion_stub()
    res = ga.run_ga(
        warm_start_order=[7, 6, 5, 4, 3, 2, 1, 0], warm_start_rotations=[180.0] * 8,
        pieces=pieces, allowed_rotations_per_piece=[[0.0, 180.0]] * 8,
        generations=25, max_time_s=None, seed=42, evaluator=ev,
        config=ga.GAConfig(population_size=20, mutation_rate=0.6),
    )
    assert res.best_marker < 36.0          # strictly improved on the warm-start
    assert res.generations_executed == 25


def test_run_ga_is_deterministic_per_seed():
    pieces = [_p(str(i)) for i in range(8)]
    ev1, _ = _index_inversion_stub()
    ev2, _ = _index_inversion_stub()
    kw = dict(
        warm_start_order=[7, 6, 5, 4, 3, 2, 1, 0], warm_start_rotations=[180.0] * 8,
        pieces=pieces, allowed_rotations_per_piece=[[0.0, 180.0]] * 8,
        generations=15, max_time_s=None, seed=99,
        config=ga.GAConfig(population_size=16, mutation_rate=0.5),
    )
    r1 = ga.run_ga(evaluator=ev1, **kw)
    r2 = ga.run_ga(evaluator=ev2, **kw)
    assert r1.best_marker == r2.best_marker
    assert r1.best_order == r2.best_order
    assert r1.best_rotations == r2.best_rotations


def test_run_ga_respects_time_cap_via_injected_clock():
    pieces = [_p(str(i)) for i in range(5)]
    ev, _ = _index_inversion_stub()
    ticks = iter([0.0] + [100.0] * 50)         # start=0, then time already past cap
    res = ga.run_ga(
        warm_start_order=list(range(5)), warm_start_rotations=[0.0] * 5,
        pieces=pieces, allowed_rotations_per_piece=[[0.0, 180.0]] * 5,
        generations=100, max_time_s=1.0, seed=1, evaluator=ev,
        clock=lambda: next(ticks),
    )
    assert res.generations_executed == 0       # cap fires before the first generation


def test_run_ga_breaks_on_cancellation(monkeypatch):
    pieces = [_p(str(i)) for i in range(5)]
    ev, _ = _index_inversion_stub()
    monkeypatch.setattr(ga, "is_cancelled", lambda: True)
    res = ga.run_ga(
        warm_start_order=list(range(5)), warm_start_rotations=[0.0] * 5,
        pieces=pieces, allowed_rotations_per_piece=[[0.0, 180.0]] * 5,
        generations=100, max_time_s=None, seed=1, evaluator=ev,
    )
    assert res.generations_executed == 0


def test_run_ga_treats_value_error_as_infeasible():
    pieces = [_p(str(i)) for i in range(4)]

    def bad_ev(pieces_in_order, per_piece_rots):
        raise ValueError("cannot place")

    res = ga.run_ga(
        warm_start_order=list(range(4)), warm_start_rotations=[0.0] * 4,
        pieces=pieces, allowed_rotations_per_piece=[[0.0, 180.0]] * 4,
        generations=3, max_time_s=None, seed=1, evaluator=bad_ev,
        config=ga.GAConfig(population_size=6),
    )
    assert res.best_marker == float("inf")     # every individual infeasible
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_ga.py -v -k run_ga`
Expected: FAIL — `run_ga` is not yet defined.

- [ ] **Step 3: Write minimal implementation** (append to `ga.py`)

```python
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
    -> (placements, marker, util)`; a ValueError means "infeasible" → +inf fitness.
    No shared_best_value: GA does not prune (spec §7), so it is deterministic.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_ga.py -v`
Expected: PASS (all GA unit tests). If `test_run_ga_improves_on_a_suboptimal_start` does not strictly improve for seed 42, raise `generations`/`population_size` or change the seed — the inversion+flip landscape guarantees improvement is reachable; pick a config where it lands.

- [ ] **Step 5: Commit**

```
git -C D:\openmarker\.worktrees\ga-meta-heuristic add engine/core/layout/ga.py engine/tests/unit/test_ga.py
git -C D:\openmarker\.worktrees\ga-meta-heuristic commit -m "feat(ga): run_ga island driver" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `auto_layout_polygon` GA params + validation

**Files:**
- Modify: `engine/core/layout/heuristic.py` (signature, docstring, validation only)
- Test: `engine/tests/unit/test_heuristic.py`

- [ ] **Step 1: Write the failing test** (append to `engine/tests/unit/test_heuristic.py`; reuse that file's existing piece-builder/imports — match the helper already present there, e.g. a local `_p`/`_make_piece`; if none, add the `_p` helper from `test_ga.py`)

```python
import pytest
from core.layout.heuristic import auto_layout_polygon


def test_ga_negative_generations_raises():
    with pytest.raises(ValueError, match="ga_generations must be >= 0"):
        auto_layout_polygon([_p("0")], 1651.0, "bi", 90.0, ga_generations=-1)


def test_ga_with_clustering_raises():
    with pytest.raises(ValueError, match="cannot be combined with disable_clustering"):
        auto_layout_polygon([_p("0")], 1651.0, "bi", 90.0,
                            ga_generations=5, disable_clustering=False)


def test_ga_and_sa_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        auto_layout_polygon([_p("0")], 1651.0, "bi", 90.0,
                            ga_generations=5, sa_iterations=5)


def test_ga_max_time_s_must_be_positive():
    with pytest.raises(ValueError, match="ga_max_time_s must be > 0"):
        auto_layout_polygon([_p("0")], 1651.0, "bi", 90.0,
                            ga_generations=5, ga_max_time_s=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "ga_"`
Expected: FAIL — `auto_layout_polygon() got an unexpected keyword argument 'ga_generations'`.

- [ ] **Step 3: Write minimal implementation** in `engine/core/layout/heuristic.py`

3a. Add the GA import to the existing sa import line (`heuristic.py:19`):
```python
from core.layout.sa import WarmStart, run_sa, NO_GRAINLINE_ROTATION_CAP, SAConfig
from core.layout.ga import GAConfig, run_ga
```

3b. Add params to the `auto_layout_polygon` signature, immediately after `sa_config` (`heuristic.py:796`):
```python
    sa_config: "SAConfig | None" = None,
    ga_generations: int = 0,
    ga_max_time_s: float | None = None,
    ga_seed: int = 0,
    ga_config: "GAConfig | None" = None,
) -> tuple[list[Placement], float, float]:
```

3c. Add to the docstring (after the `sa_seed` paragraph, before the closing `"""` at `heuristic.py:862`):
```python
    `ga_generations`: when > 0, run an island-model Genetic Algorithm on top of
    the best-of-4 sort-strategies result instead of SA. K = _worker_count(effort)
    independent populations evolve `ga_generations` generations each; the best
    individual across islands (and the retained warm-start) wins. Default 0 (GA
    disabled). Mutually exclusive with both `disable_clustering=False` and
    `sa_iterations > 0` — raises ValueError. GA does not use cross-island pruning,
    so results are deterministic per `ga_seed`. See PERFORMANCE.md § 4.7 and
    engine/core/layout/ga.py.

    `ga_max_time_s`: optional wall-clock cap per GA island in seconds. Must be > 0
    when set. Default None (generation-cap only).

    `ga_seed`: base RNG seed for GA. Island k uses `ga_seed + k`. Default 0.
```

3d. Add validation immediately after the SA validation block (`heuristic.py:874`, after the `sa_max_time_s` check):
```python
    if ga_generations < 0:
        raise ValueError(f"ga_generations must be >= 0, got {ga_generations}")
    if ga_generations > 0 and not disable_clustering:
        raise ValueError(
            "ga_generations > 0 cannot be combined with disable_clustering=False; "
            "see PERFORMANCE.md § 4.7 for the future-work note."
        )
    if ga_generations > 0 and sa_iterations > 0:
        raise ValueError(
            "ga_generations > 0 and sa_iterations > 0 are mutually exclusive; "
            "run one meta-heuristic per call."
        )
    if ga_max_time_s is not None and ga_max_time_s <= 0:
        raise ValueError(f"ga_max_time_s must be > 0 when set, got {ga_max_time_s}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "ga_"`
Expected: PASS (4 validation tests).

- [ ] **Step 5: Commit**

```
git -C D:\openmarker\.worktrees\ga-meta-heuristic add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git -C D:\openmarker\.worktrees\ga-meta-heuristic commit -m "feat(ga): auto_layout_polygon ga_* params + validation" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: GA orchestration (worker plumbing + `_run_ga_phase` + wiring)

**Files:**
- Modify: `engine/core/layout/heuristic.py`
- Test: `engine/tests/unit/test_heuristic.py`

- [ ] **Step 1: Write the failing test** (append to `test_heuristic.py`)

```python
def _grained_rect(piece_id, w=200.0, h=120.0):
    return _p(piece_id, w, h)  # grainline_direction_deg=0.0 from the helper


def test_ga_opt_in_returns_valid_layout_not_worse_than_baseline():
    pieces = [_grained_rect(str(i)) for i in range(6)]
    base = auto_layout_polygon(pieces, 1651.0, "bi", 90.0, effort=5)
    ga_res = auto_layout_polygon(pieces, 1651.0, "bi", 90.0, effort=5,
                                 ga_generations=5, ga_seed=1,
                                 ga_config=GAConfig(population_size=8))
    placements, marker, util = ga_res
    assert len(placements) == len(pieces)        # all pieces placed
    assert marker <= base[1] + 1e-6              # GA never worse than warm-start


def test_ga_default_off_is_identical_to_baseline():
    pieces = [_grained_rect(str(i)) for i in range(6)]
    a = auto_layout_polygon(pieces, 1651.0, "bi", 90.0, effort=5)
    b = auto_layout_polygon(pieces, 1651.0, "bi", 90.0, effort=5)  # no ga_* kwargs
    assert a[1] == b[1] and a[2] == b[2]


def test_ga_parallel_is_deterministic_per_seed():
    pieces = [_grained_rect(str(i)) for i in range(6)]
    kw = dict(effort=5, ga_generations=6, ga_seed=7,
              ga_config=GAConfig(population_size=8))
    r1 = auto_layout_polygon(pieces, 1651.0, "bi", 90.0, **kw)
    r2 = auto_layout_polygon(pieces, 1651.0, "bi", 90.0, **kw)
    assert r1[1] == r2[1]                         # identical marker across runs
```

Add the import at the top of `test_heuristic.py` if absent: `from core.layout.ga import GAConfig`.

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "ga_opt_in or ga_default_off or ga_parallel"`
Expected: FAIL — GA params accepted but ignored, so `ga_opt_in` likely returns the baseline yet `_run_ga_phase` is never called; the parallel-determinism/all-placed assertions exercise the missing wiring. (At minimum, GA has no effect.)

- [ ] **Step 3: Write minimal implementation** in `heuristic.py`

3a. Add GA worker globals immediately after the SA worker globals block (`heuristic.py:96`, after `_worker_sa_config`):
```python
# ---------------------------------------------------------------------------
# GA worker globals — set by _init_ga_worker, read by _run_ga_chain.
# (No shared_best: GA does not prune — spec §7.)
# ---------------------------------------------------------------------------
_worker_ga_warm_starts: list[WarmStart] = []
_worker_ga_blf_input: list[Piece] = []
_worker_ga_fabric_width_mm: float = 0.0
_worker_ga_fabric_grain_deg: float = 0.0
_worker_ga_allowed_rotations: list[list[float]] = []
_worker_ga_disable_nfp_cache: bool = False
_worker_ga_config: "GAConfig | None" = None


def _init_ga_worker(
    warm_starts,
    blf_input,
    fabric_width_mm,
    fabric_grain_deg,
    allowed_rotations_per_piece,
    disable_nfp_cache,
    ga_config,
):
    global _worker_ga_warm_starts, _worker_ga_blf_input, _worker_ga_fabric_width_mm
    global _worker_ga_fabric_grain_deg, _worker_ga_allowed_rotations
    global _worker_ga_disable_nfp_cache, _worker_ga_config
    _worker_ga_warm_starts = warm_starts
    _worker_ga_blf_input = blf_input
    _worker_ga_fabric_width_mm = fabric_width_mm
    _worker_ga_fabric_grain_deg = fabric_grain_deg
    _worker_ga_allowed_rotations = allowed_rotations_per_piece
    _worker_ga_disable_nfp_cache = disable_nfp_cache
    _worker_ga_config = ga_config


def _run_ga_chain(worker_index: int, generations: int,
                  max_time_s: float | None, seed: int):
    """Module-level entry for ProcessPoolExecutor. Picks a warm-start, builds the
    evaluator closure, calls ga.run_ga. Returns GAResult or None."""
    from core.layout.ga import run_ga

    if not _worker_ga_warm_starts:
        return None
    chosen = _worker_ga_warm_starts[worker_index % len(_worker_ga_warm_starts)]

    pid_to_index = {p.id: i for i, p in enumerate(_worker_ga_blf_input)}
    warm_order = [pid_to_index[p.id] for p in chosen.sorted_pieces]
    warm_rot = [0.0] * len(_worker_ga_blf_input)
    for sorted_idx, p in enumerate(chosen.sorted_pieces):
        warm_rot[pid_to_index[p.id]] = chosen.rotations_used[sorted_idx]

    nfp_cache: NfpCache = {}

    def evaluator(pieces_in_order, per_piece_rotations):
        cache = {} if _worker_ga_disable_nfp_cache else nfp_cache
        try:
            return _blf_pack_nfp(
                pieces_in_order,
                _worker_ga_fabric_width_mm,
                chosen.mode,
                _worker_ga_fabric_grain_deg,
                nfp_cache=cache,
                override_rotations=per_piece_rotations,
                presorted=True,
                skip_validation=True,
            )
        except _PrunedRun:  # no shared cutoff is passed, so this cannot fire;
            raise ValueError("pruned")  # defensive translation for run_ga.

    return run_ga(
        warm_start_order=warm_order,
        warm_start_rotations=warm_rot,
        pieces=_worker_ga_blf_input,
        allowed_rotations_per_piece=_worker_ga_allowed_rotations,
        generations=generations,
        max_time_s=max_time_s,
        seed=seed,
        evaluator=evaluator,
        config=_worker_ga_config,
    )
```

3b. Add `_run_ga_phase` immediately after `_run_sa_phase` ends (find the end of `_run_sa_phase`, around `heuristic.py:1002`+, after its final `return`):
```python
def _run_ga_phase(
    warm_start_best: tuple[list[Placement], float, float],
    warm_starts: list[WarmStart],
    blf_input: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    ga_generations: int,
    ga_max_time_s: float | None,
    ga_seed: int,
    effort: int,
    disable_nfp_cache: bool,
    clusters: list,
    ga_config: "GAConfig | None" = None,
) -> tuple[list[Placement], float, float]:
    """Run K island GAs and aggregate with warm_start_best retained. GA never
    regresses below the warm-start. No shared-cutoff pruning (deterministic)."""
    cfg = GAConfig() if ga_config is None else ga_config

    warm_starts_sorted = sorted(warm_starts, key=lambda ws: ws.marker)
    if not warm_starts_sorted:
        if clusters:
            placements, marker_length, utilization = warm_start_best
            placements = _expand_clustered_placements(placements, clusters)
            return placements, marker_length, utilization
        return warm_start_best

    allowed_rotations_per_piece: list[list[float]] = []
    for p in blf_input:
        rots = allowed_rotations(grain_mode, fabric_grain_deg, p.grainline_direction_deg)
        if len(rots) > cfg.no_grainline_rotation_cap:
            step = 360.0 / cfg.no_grainline_rotation_cap
            rots = [step * i for i in range(cfg.no_grainline_rotation_cap)]
        allowed_rotations_per_piece.append(rots)

    workers = _worker_count(effort)
    ga_use_pool = workers > 1 and ga_generations >= 1

    # (GAResult, worker_index) pairs.
    chain_results: list = []

    if not ga_use_pool:
        _init_ga_worker(
            warm_starts_sorted, blf_input, fabric_width_mm, fabric_grain_deg,
            allowed_rotations_per_piece, disable_nfp_cache, cfg,
        )
        result = _run_ga_chain(0, ga_generations, ga_max_time_s, ga_seed)
        if result is not None:
            chain_results.append((result, 0))
    else:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_ga_worker,
            initargs=(
                warm_starts_sorted, blf_input, fabric_width_mm, fabric_grain_deg,
                allowed_rotations_per_piece, disable_nfp_cache, cfg,
            ),
        ) as pool:
            _set_current_executor(pool)
            try:
                futures = {
                    pool.submit(_run_ga_chain, k, ga_generations, ga_max_time_s, ga_seed + k): k
                    for k in range(workers)
                }
                try:
                    for f in as_completed(futures):
                        k = futures[f]
                        result = f.result()
                        if result is not None:
                            chain_results.append((result, k))
                except BrokenProcessPool as e:
                    raise CancellationError("GA cancelled (workers terminated).") from e
            finally:
                _set_current_executor(None)

    # Aggregate. warm_start_best always retained; deterministic tie-break by
    # (marker, worker_index) with warm-start at index -1 so it wins exact ties.
    best_placements, best_marker, best_util = warm_start_best
    best_key = (best_marker, -1)
    for result, k in chain_results:
        if result.best_placements and (result.best_marker, k) < best_key:
            best_marker = result.best_marker
            best_util = result.best_util
            best_placements = result.best_placements
            best_key = (result.best_marker, k)

    if clusters:
        best_placements = _expand_clustered_placements(best_placements, clusters)
    return best_placements, best_marker, best_util
```

3c. Widen the warm-start retention guard in BOTH paths so GA also collects warm-starts. Serial (`heuristic.py:916`) and parallel (`heuristic.py:981`): change
```python
                if sa_iterations > 0:
```
to
```python
                if sa_iterations > 0 or ga_generations > 0:
```
(serial, indented under the sort loop) and the parallel one:
```python
                    if sa_iterations > 0 or ga_generations > 0:
```

3d. Add the GA phase call in BOTH return sites, immediately after each SA `if sa_iterations > 0: return _run_sa_phase(...)` block.

Serial path (after `heuristic.py:926`):
```python
        if ga_generations > 0:
            return _run_ga_phase(
                best, warm_starts, blf_input, fabric_width_mm, grain_mode,
                fabric_grain_deg, ga_generations, ga_max_time_s, ga_seed,
                effort, disable_nfp_cache, clusters, ga_config,
            )
```

Parallel path (after `heuristic.py:997`):
```python
    if ga_generations > 0:
        return _run_ga_phase(
            best, warm_starts, blf_input, fabric_width_mm, grain_mode,
            fabric_grain_deg, ga_generations, ga_max_time_s, ga_seed,
            effort, disable_nfp_cache, clusters, ga_config,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py engine/tests/unit/test_ga.py -v`
Expected: PASS (GA integration + all unit tests). Then run the full suite to confirm no regression:
`D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit -v`
Expected: all green.

- [ ] **Step 5: Commit**

```
git -C D:\openmarker\.worktrees\ga-meta-heuristic add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git -C D:\openmarker\.worktrees\ga-meta-heuristic commit -m "feat(ga): island orchestration + auto_layout_polygon wiring" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `bench_ga.py` — acceptance gates G1–G5

**Files:**
- Create: `engine/tests/bench_ga.py`
- Reference: `engine/tests/bench_sa.py` (mirror its structure, fixture loading, and CLI).

- [ ] **Step 1: Write the bench** (no unit test; the bench *is* the executable check). Mirror `bench_sa.py`: walk up for `examples/input/sample_2.dxf`, parse+normalize, expand to 10 copies, then:
```python
"""GA acceptance bench on the canonical workload. Mirrors bench_sa.py.

Run: D:\\openmarker\\engine\\.venv\\Scripts\\python.exe engine/tests/bench_ga.py
Gates G1-G5; exits 1 on failure.
"""
# --- imports, fixture discovery, _load_workload(): copy verbatim from bench_sa.py ---
# (parse_dxf -> normalize_piece -> expand to 10 copies, fabric_width_mm=1651,
#  grain_mode="bi", FABRIC_GRAIN_DEG, effort=5)

from core.layout.grain import FABRIC_GRAIN_DEG
from core.layout.heuristic import auto_layout_polygon

BAR = 11699.0
FABRIC = 1651.0


def main() -> int:
    pieces = _load_workload()  # 190 pieces
    base = auto_layout_polygon(pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, effort=5)
    warm_marker = base[1]
    print(f"warm-start: L={warm_marker:.1f} U={base[2]:.2f}%")

    failures = []
    results = {}
    for gens in (20, 40, 60):
        placements, marker, util = auto_layout_polygon(
            pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, effort=5,
            ga_generations=gens, ga_seed=42,
        )
        results[gens] = (placements, marker, util)
        print(f"ga gens={gens:3d}  L={marker:.1f}  U={util:.2f}%  placed={len(placements)}")

    # G1: all pieces placed at the largest budget.
    if len(results[60][0]) != len(pieces):
        failures.append("G1 not all pieces placed")
    # G2: monotone vs warm-start (never worse).
    if any(results[g][1] > warm_marker + 1e-6 for g in results):
        failures.append("G2 GA regressed below warm-start")
    # G3: same-seed determinism — EXACT (GA has no shared-cutoff non-determinism).
    rerun = auto_layout_polygon(pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, effort=5,
                                ga_generations=40, ga_seed=42)
    if rerun[1] != results[40][1]:
        failures.append(f"G3 nondeterministic: {rerun[1]} != {results[40][1]}")
    # G4: default (no ga_*) == warm-start baseline.
    default = auto_layout_polygon(pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, effort=5)
    if default[1] != warm_marker:
        failures.append("G4 default changed")
    # G5: beat the bar strictly (best across the swept budgets).
    best_marker = min(results[g][1] for g in results)
    if best_marker < BAR:
        print(f"G5 PASS: best GA {best_marker:.1f} < bar {BAR}")
    else:
        # Demoted to informational until the sweep (Task 9) finds a winning config
        # or the gap analysis is documented. Do NOT add to failures yet.
        print(f"G5 INFO: best GA {best_marker:.1f} did NOT beat bar {BAR}")

    print("GATES:", "FAIL " + "; ".join(failures) if failures else "G1-G4 PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

> G5 starts informational. Task 9 promotes it to PR-blocking (add to `failures`) **if** the sweep finds a config that beats the bar; otherwise it stays informational and the gap analysis is documented.

- [ ] **Step 2: Run the bench**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe engine/tests/bench_ga.py`
Expected: prints warm-start + 3 GA rows; G1–G4 PASS. G5 may be INFO at the default hyperparameters (Task 9 tunes).

- [ ] **Step 3: Commit**

```
git -C D:\openmarker\.worktrees\ga-meta-heuristic add engine/tests/bench_ga.py
git -C D:\openmarker\.worktrees\ga-meta-heuristic commit -m "test(ga): bench_ga.py acceptance gates G1-G5" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `bench_ga_sweep.py` — hyperparameter sweep (TTL + always-report)

**Files:**
- Create: `engine/tests/bench_ga_sweep.py`
- Reference: `engine/tests/bench_sa_sweep.py` (copy the harness wholesale; swap the axes).

- [ ] **Step 1: Write the sweep.** Reuse `bench_sa_sweep.py`'s skeleton verbatim — `SWEEP_TTL_S = 3 * 3600`, `PER_ROW_CAP_S = 900` (passed as `ga_max_time_s`), `_TTLExceeded` checked between rows, per-row JSONL streaming to `_ga_sweep_results.jsonl`, `_write_report()` in a `finally` block → `_ga_sweep_report.md`, `--smoke`/`--ttl` flags. Only the per-row call and the axes change:
```python
from core.layout.ga import GAConfig

def _run_row(label, pieces, *, generations, seed, **cfg_kwargs):
    cfg = GAConfig(**cfg_kwargs)
    placements, marker, util = auto_layout_polygon(
        pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, effort=5,
        ga_generations=generations, ga_seed=seed, ga_max_time_s=PER_ROW_CAP_S,
        ga_config=cfg,
    )
    return {"label": label, "marker": marker, "util": util,
            "generations": generations, "seed": seed, **cfg_kwargs}

# Phases (highest-value first so a TTL cutoff still yields signal):
#  Phase 0: baseline ga=0 (warm-start) + current-defaults row.
#  Phase 1: single-axis screen — population_size {16,30,50},
#           crossover_rate {0.7,0.9}, mutation_rate {0.1,0.2,0.4},
#           generations {20,40,60}, mutation_move_weights (rot-heavy vs uniform).
#  Phase 2: combine the best-improving value per axis.
#  Phase 3: multi-seed validation of the best config on seeds {42,7,13,21,99}.
```

- [ ] **Step 2: Smoke-test the harness** (fast, proves it runs + always writes a report)

Run: `D:\openmarker\engine\.venv\Scripts\python.exe engine/tests/bench_ga_sweep.py --smoke`
Expected: a handful of tiny rows complete; `_ga_sweep_report.md` is written even on `--smoke`. Confirm the report exists and has a results table.

- [ ] **Step 3: Commit** (commit the harness only; the run artifacts are git-ignored / deleted later)

```
git -C D:\openmarker\.worktrees\ga-meta-heuristic add engine/tests/bench_ga_sweep.py
git -C D:\openmarker\.worktrees\ga-meta-heuristic commit -m "test(ga): bench_ga_sweep.py (TTL + always-writes-a-report)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Run the sweep, decide outcome, bake default, write docs

**Files:**
- Modify: `engine/core/layout/ga.py` (only if a winning config is found — update the constants/`GAConfig` defaults)
- Modify: `engine/tests/bench_ga.py` (promote G5 to PR-blocking only on a win)
- Modify: `docs/planning/PERFORMANCE.md`, `docs/planning/BACKLOG.md`

- [ ] **Step 1: Run the full sweep in the background** (TTL-bounded; always writes a report)

Run (background): `D:\openmarker\engine\.venv\Scripts\python.exe engine/tests/bench_ga_sweep.py`
Wait for completion (≤ 3 h TTL). Read `engine/tests/_ga_sweep_report.md`.

- [ ] **Step 2: Decide the outcome from the report**
  - **If a config beats 11699 mm strictly on ≥3 seeds:** update `ga.py` module constants (and therefore `GAConfig` defaults) to that config. Re-run `bench_ga.py` to confirm G5 passes at the new default; **promote G5 to PR-blocking** (move it into `failures`).
  - **If nothing beats the bar:** keep the starting defaults; **G5 stays informational**. The deliverable is the gap analysis.

- [ ] **Step 3: Update `bench_ga.py` G5 disposition** per Step 2, then run it once more:

Run: `D:\openmarker\engine\.venv\Scripts\python.exe engine/tests/bench_ga.py`
Expected: G1–G4 PASS; G5 PASS (win) or INFO (gap).

- [ ] **Step 4: Write docs.**
  - `PERFORMANCE.md`: add **§4.7 "GA meta-heuristic (`ga_generations > 0`)"** mirroring §4.6 (code map, opt-in invocation, constants, tests, bench). Add a **§6 `[2026-06-05]` GA entry** (What / Why / Result table / Decision / Mechanism-at). Update the §5.B SA/GA row: change "GA half deferred" to shipped, with the win-or-gap result. If a win, add a §1 headline row.
  - `BACKLOG.md`: check off the GA follow-up under Phase 6.

- [ ] **Step 5: Final full-suite run**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit -v`
Expected: all green (including the new GA tests).

- [ ] **Step 6: Commit**

```
git -C D:\openmarker\.worktrees\ga-meta-heuristic add engine/core/layout/ga.py engine/tests/bench_ga.py docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git -C D:\openmarker\.worktrees\ga-meta-heuristic commit -m "feat(ga): bake swept default (or gap analysis) + docs" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## After all tasks

- Dispatch a final code review over the whole branch.
- Use **superpowers:finishing-a-development-branch** (verify the full suite is green, then present the merge/PR options). Do not push without explicit user approval.

---

## Self-Review (author checklist — completed)

**Spec coverage:** §3 genome → Tasks 1/4; §4 seeding → Task 3/4; §5 operators → Tasks 2/3; §6 run_ga → Task 4; §7 no-pruning/determinism → Task 4 (no shared_best) + Task 6 (`_run_ga_chain` passes no cutoff) + G3 exact determinism (Tasks 6/7); §8 orchestration → Task 6; §9 API+GAConfig → Tasks 1/5; §10 bench/sweep/done → Tasks 7/8/9; §11 testing → Tasks 1-6; §12 docs → Task 9. All covered.

**Placeholder scan:** every code step has complete code; bench_ga.py/bench_ga_sweep.py reference the SA equivalents to copy structure (fixture-loading + TTL harness are large and already exist) but specify exactly what changes — acceptable since the source files are in-tree.

**Type consistency:** `GAConfig`/`GAResult` field names identical across Tasks 1/4/6; `run_ga` signature identical in Task 4 (def) and Task 6 (call); `_run_ga_phase` signature (no `disable_pruning`) matches its call sites in Task 6 §3d; `_init_ga_worker` initargs tuple matches the param order in both the serial and pool branches.
