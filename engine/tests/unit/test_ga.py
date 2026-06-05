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
    # rotation_flip favored, matching SA's tuning win (spec section 5.4).
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
    warm_rot = [180.0] * 8                       # 8 flips -> warm marker 36
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
