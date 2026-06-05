"""Unit tests for the SA meta-heuristic driver. Uses stub evaluators
(no real BLF) so tests are deterministic and <50ms each."""
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.layout import sa
from core.models.piece import Piece, BoundingBox


def _p(piece_id: str, w: float = 100, h: float = 50) -> Piece:
    """Build a minimal Piece for tests. Polygon/area irrelevant for stub-evaluator tests."""
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True, validation_notes=[], grainline_direction_deg=0.0,
    )


def test_sa_module_exports():
    """The sa module must export the public surface used by heuristic.py."""
    assert callable(sa.run_sa)
    assert hasattr(sa, "WarmStart")
    assert hasattr(sa, "SAResult")
    # Hyperparameter constants
    assert isinstance(sa.T0_FACTOR, float)
    assert isinstance(sa.COOLING_ALPHA, float)
    assert isinstance(sa.T_MIN, float)
    assert isinstance(sa.REVERSE_WINDOW_FRACTION, float)
    assert isinstance(sa.NO_GRAINLINE_ROTATION_CAP, int)
    assert isinstance(sa.MOVE_WEIGHTS, dict)
    # Sanity bounds on defaults
    assert 0.0 < sa.T0_FACTOR < 1.0
    assert 0.0 < sa.COOLING_ALPHA < 1.0
    assert sa.T_MIN > 0.0
    assert 0.0 < sa.REVERSE_WINDOW_FRACTION <= 1.0
    assert sa.NO_GRAINLINE_ROTATION_CAP >= 2
    assert set(sa.MOVE_WEIGHTS.keys()) == {"swap", "reverse", "rotation_flip"}


import random


def test_swap_move_preserves_permutation_validity():
    """Swap must keep order as a valid permutation of [0, N)."""
    rng = random.Random(42)
    order = list(range(20))
    new_order = sa._swap_move(order, rng)
    assert sorted(new_order) == list(range(20))  # still a permutation
    assert new_order != order  # actually changed something


def test_swap_move_changes_exactly_two_positions():
    """Swap exchanges two indices; everything else stays put."""
    rng = random.Random(1)
    order = list(range(20))
    new_order = sa._swap_move(order, rng)
    diffs = [i for i in range(20) if new_order[i] != order[i]]
    assert len(diffs) == 2
    # The two values at those positions must be swaps of each other.
    i, j = diffs
    assert new_order[i] == order[j]
    assert new_order[j] == order[i]


def test_reverse_move_preserves_permutation_validity():
    """Reverse must keep order as a valid permutation of [0, N)."""
    rng = random.Random(42)
    order = list(range(20))
    new_order = sa._reverse_move(order, rng)
    assert sorted(new_order) == list(range(20))


def test_reverse_move_respects_window_cap():
    """The reverse window is capped at ceil(N * REVERSE_WINDOW_FRACTION).
    For N=20 and 0.25 → cap=5. The contiguous reversed slice must be
    at most 5 long."""
    import math
    cap = math.ceil(20 * sa.REVERSE_WINDOW_FRACTION)
    rng = random.Random(7)
    for _ in range(100):
        order = list(range(20))
        new_order = sa._reverse_move(order, rng)
        # Find the diff window: leftmost and rightmost positions that changed.
        diffs = [i for i in range(20) if new_order[i] != order[i]]
        if not diffs:
            continue  # No-op (window of length < 2 won't change anything)
        window_len = max(diffs) - min(diffs) + 1
        assert window_len <= cap, f"window {window_len} exceeded cap {cap}"


def test_rotation_flip_picks_from_allowed():
    """Rotation flip for piece p must pick a value from allowed_per_piece[p]
    that is NOT the current rotations[p]."""
    rng = random.Random(0)
    rotations = [0.0, 90.0, 180.0, 0.0]
    allowed = [[0.0, 180.0], [90.0, 270.0], [180.0, 0.0], [0.0, 180.0]]
    new_rotations, flipped_piece = sa._rotation_flip_move(rotations, allowed, rng)
    # Exactly one piece's rotation changed.
    diffs = [i for i in range(len(rotations)) if new_rotations[i] != rotations[i]]
    assert len(diffs) == 1
    assert diffs[0] == flipped_piece
    # The new value is in allowed[flipped_piece] and differs from the old.
    assert new_rotations[flipped_piece] in allowed[flipped_piece]
    assert new_rotations[flipped_piece] != rotations[flipped_piece]


def test_rotation_flip_handles_single_allowed_piece():
    """When ALL pieces have 1 allowed rotation, rotation flip cannot change
    anything. The function must return rotations unchanged and flipped_piece=None
    rather than infinite-looping. (The caller — Task 6 — falls back to a
    different move type when this happens.)"""
    rng = random.Random(0)
    rotations = [0.0, 90.0, 180.0]
    allowed = [[0.0], [90.0], [180.0]]
    new_rotations, flipped_piece = sa._rotation_flip_move(rotations, allowed, rng)
    assert new_rotations == rotations
    assert flipped_piece is None


def test_sample_move_type_uses_weights():
    """_sample_move_type returns one of the configured move types per the
    MOVE_WEIGHTS distribution. With equal weights, the empirical distribution
    over 3000 draws should be roughly uniform (±50 per bucket = 3σ on a
    binomial with p=1/3, n=3000)."""
    rng = random.Random(123)
    counts = {"swap": 0, "reverse": 0, "rotation_flip": 0}
    for _ in range(3000):
        counts[sa._sample_move_type(rng)] += 1
    for move_type, count in counts.items():
        assert 900 < count < 1100, f"{move_type}: {count} (expected ~1000 ± 100)"


import math as _math


def test_temperature_schedule():
    """T_k = max(T_MIN, T0 * COOLING_ALPHA ** k) within float epsilon."""
    T0 = 100.0
    for k in [0, 1, 10, 50, 100]:
        expected_unfloored = T0 * (sa.COOLING_ALPHA ** k)
        expected = max(sa.T_MIN, expected_unfloored)
        actual = sa._temperature_at(T0, k)
        assert _math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9), \
            f"T at k={k}: expected {expected}, got {actual}"


def test_temperature_floored_at_t_min():
    """At very high k, T should clamp to T_MIN, not go to 0."""
    T0 = 100.0
    actual = sa._temperature_at(T0, k=10_000)
    assert actual == sa.T_MIN


def test_metropolis_accepts_all_improvements():
    """Strictly better neighbors are accepted unconditionally."""
    rng = random.Random(0)
    for _ in range(100):
        assert sa._metropolis_accept(delta=-1.0, T=1.0, rng=rng) is True
        assert sa._metropolis_accept(delta=-100.0, T=0.001, rng=rng) is True


def test_metropolis_accepts_equal():
    """Zero-delta neighbors accepted (allows lateral exploration)."""
    rng = random.Random(0)
    for _ in range(100):
        assert sa._metropolis_accept(delta=0.0, T=1.0, rng=rng) is True


def test_metropolis_accept_rates_at_t0_and_tmin():
    """At T0 with delta = 0.05 * T0 (i.e. ratio = 1/20 = e^-0.05),
    accept probability is exp(-0.05) ≈ 0.951 — accept-rate over 2000
    deterministic trials should land near that.
    At T_MIN with the same delta, accept probability ≈ 0 (delta/T_MIN huge)."""
    rng = random.Random(123)
    T0 = 100.0
    delta = 5.0  # delta/T0 = 0.05
    accepts = sum(1 for _ in range(2000)
                  if sa._metropolis_accept(delta, T0, rng))
    # exp(-0.05) ≈ 0.9512; over 2000 trials, 3σ ≈ ±29
    assert 1880 < accepts < 1950, f"accept rate at T0: {accepts}/2000"

    rng2 = random.Random(456)
    accepts_tmin = sum(1 for _ in range(2000)
                       if sa._metropolis_accept(delta, sa.T_MIN, rng2))
    assert accepts_tmin == 0, f"accept rate at T_MIN: {accepts_tmin}/2000"


def test_run_sa_zero_iterations_returns_warmstart_unchanged():
    """iterations=0 → SA must not call the evaluator. Return the initial
    state as best-seen."""
    pieces = [_p(f"p{i}") for i in range(5)]
    initial_order = [0, 1, 2, 3, 4]
    initial_rotations = [0.0] * 5
    allowed = [[0.0, 180.0]] * 5
    call_count = {"n": 0}

    def stub_evaluator(pieces_in_order, per_piece_rotations):
        call_count["n"] += 1
        return ([], 999.0, 0.0)  # would-be result; should never be called

    result = sa.run_sa(
        initial_order=initial_order,
        initial_rotations=initial_rotations,
        pieces=pieces,
        allowed_rotations_per_piece=allowed,
        iterations=0,
        max_time_s=None,
        seed=42,
        evaluator=stub_evaluator,
    )
    assert call_count["n"] == 0
    assert result.best_order == initial_order
    assert result.best_rotations == initial_rotations
    assert result.iterations_executed == 0


def test_run_sa_returns_best_seen_not_final():
    """SA must track best-seen separately. Stub fitness landscape:
    iteration 1 returns marker=5 (improvement); iterations 2-9 return
    marker=50 (worse). Final state is at marker=50 but best is marker=5."""
    pieces = [_p(f"p{i}") for i in range(5)]
    initial_order = [0, 1, 2, 3, 4]
    initial_rotations = [0.0] * 5
    allowed = [[0.0, 180.0]] * 5

    iteration = {"n": 0}

    # We need initial evaluation too — run_sa evaluates the initial state once
    # (to get the marker for T0 calibration). That's iteration 0.
    def stub_eval_with_init(pieces_in_order, per_piece_rotations):
        iteration["n"] += 1
        if iteration["n"] == 1:
            return ([("init",)], 100.0, 0.05)  # initial marker -> T0 = 5.0
        if iteration["n"] == 2:
            return ([("gold",)], 5.0, 0.95)
        return ([("bad",)], 50.0, 0.1)

    result = sa.run_sa(
        initial_order=initial_order,
        initial_rotations=initial_rotations,
        pieces=pieces,
        allowed_rotations_per_piece=allowed,
        iterations=10,
        max_time_s=None,
        seed=42,
        evaluator=stub_eval_with_init,
    )
    assert result.best_marker == 5.0
    assert ("gold",) in result.best_placements


def test_run_sa_monotone_non_worsening():
    """Across 50 random seeds, best_marker <= initial_marker always."""
    pieces = [_p(f"p{i}") for i in range(10)]
    initial_order = list(range(10))
    initial_rotations = [0.0] * 10
    allowed = [[0.0, 180.0]] * 10

    def random_marker_evaluator(pieces_in_order, per_piece_rotations):
        # Marker proportional to a stable hash of the candidate so SA has
        # a real landscape to descend. Initial state (first call) gets a
        # known-large marker.
        key = tuple(p.id for p in pieces_in_order)
        h = abs(hash(key)) % 1000
        return ([], 100.0 + h, 0.5)  # range [100, 1099]

    for seed in range(50):
        result = sa.run_sa(
            initial_order=initial_order,
            initial_rotations=initial_rotations,
            pieces=pieces,
            allowed_rotations_per_piece=allowed,
            iterations=20,
            max_time_s=None,
            seed=seed,
            evaluator=random_marker_evaluator,
        )
        # Initial marker = 100 + hash(initial order tuple) % 1000.
        # Best must be <= that.
        initial_key = tuple(pieces[i].id for i in initial_order)
        initial_marker = 100.0 + (abs(hash(initial_key)) % 1000)
        assert result.best_marker <= initial_marker, \
            f"seed {seed}: best {result.best_marker} > initial {initial_marker}"


def test_run_sa_terminates_at_max_time_with_injected_clock():
    """With an injected clock that jumps to 1.0s after the 3rd call,
    run_sa must terminate after iteration 3 even if iterations=10000."""
    pieces = [_p(f"p{i}") for i in range(5)]
    allowed = [[0.0, 180.0]] * 5

    # run_sa calls clock() once at start (iteration 0) and once at the top of
    # each while-loop iteration (for the max_time_s check). Returning 0.0 for
    # the first 4 calls keeps SA running through iterations 1-3; the 5th call
    # returns 1.0, which is over max_time_s=0.5 and triggers termination.
    clock_calls = {"n": 0}
    def fake_clock():
        clock_calls["n"] += 1
        if clock_calls["n"] <= 4:
            return 0.0
        return 1.0

    def stub_evaluator(pieces_in_order, per_piece_rotations):
        return ([], 50.0, 0.5)

    result = sa.run_sa(
        initial_order=list(range(5)),
        initial_rotations=[0.0] * 5,
        pieces=pieces,
        allowed_rotations_per_piece=allowed,
        iterations=10_000,
        max_time_s=0.5,
        seed=1,
        evaluator=stub_evaluator,
        clock=fake_clock,
    )
    # Iteration count cap not hit; time cap fired after iteration 3.
    assert result.iterations_executed < 10
    assert result.iterations_executed >= 1


def test_run_sa_invalid_candidate_rejected_without_crash():
    """Evaluator raising ValueError → neighbor rejected, chain continues."""
    pieces = [_p(f"p{i}") for i in range(5)]
    allowed = [[0.0, 180.0]] * 5

    call_count = {"n": 0}
    def flaky_evaluator(pieces_in_order, per_piece_rotations):
        call_count["n"] += 1
        # Iteration 0 (initial): OK. Iteration 1: explode. Iteration 2+: OK with worse marker.
        if call_count["n"] == 1:
            return ([("init",)], 100.0, 0.5)
        if call_count["n"] == 2:
            raise ValueError("synthetic placement failure")
        return ([("ok",)], 110.0, 0.5)

    result = sa.run_sa(
        initial_order=list(range(5)),
        initial_rotations=[0.0] * 5,
        pieces=pieces,
        allowed_rotations_per_piece=allowed,
        iterations=5,
        max_time_s=None,
        seed=1,
        evaluator=flaky_evaluator,
    )
    # No crash; best is the initial (since 110 > 100, descent never finds better).
    assert result.best_marker == 100.0


def test_run_sa_terminates_at_iteration_cap():
    """With max_time_s=None and iterations=5, exactly 5 iterations run."""
    pieces = [_p(f"p{i}") for i in range(5)]
    allowed = [[0.0, 180.0]] * 5

    def stub_evaluator(pieces_in_order, per_piece_rotations):
        return ([], 50.0, 0.5)

    result = sa.run_sa(
        initial_order=list(range(5)),
        initial_rotations=[0.0] * 5,
        pieces=pieces,
        allowed_rotations_per_piece=allowed,
        iterations=5,
        max_time_s=None,
        seed=1,
        evaluator=stub_evaluator,
    )
    assert result.iterations_executed == 5


def test_saconfig_defaults_match_module_constants():
    cfg = sa.SAConfig()
    assert cfg.t0_factor == sa.T0_FACTOR
    assert cfg.cooling_alpha == sa.COOLING_ALPHA
    assert cfg.t_min == sa.T_MIN
    assert cfg.reverse_window_fraction == sa.REVERSE_WINDOW_FRACTION
    assert cfg.no_grainline_rotation_cap == sa.NO_GRAINLINE_ROTATION_CAP
    assert cfg.move_weights == sa.MOVE_WEIGHTS
    assert cfg.move_weights is not sa.MOVE_WEIGHTS  # independent copy


def test_temperature_at_respects_config_alpha_and_tmin():
    assert sa._temperature_at(100.0, 1, alpha=0.5, t_min=1e-3) == 50.0
    assert sa._temperature_at(100.0, 2, alpha=0.5, t_min=1e-3) == 25.0
    assert sa._temperature_at(100.0, 100, alpha=0.5, t_min=7.0) == 7.0  # floor wins


def test_sample_move_type_respects_weights():
    rng = random.Random(0)
    picks = {sa._sample_move_type(rng, {"swap": 1.0, "reverse": 0.0, "rotation_flip": 0.0})
             for _ in range(50)}
    assert picks == {"swap"}


def test_reverse_move_window_fraction_caps_window():
    rng = random.Random(3)
    order = list(range(100))
    new_order = sa._reverse_move(order, rng, window_fraction=0.02)  # cap=2
    diffs = [i for i in range(100) if new_order[i] != order[i]]
    assert len(diffs) <= 2


def test_run_sa_honors_config_move_weights_swap_only():
    """move_weights allowing only 'swap' → evaluator never sees a flipped rotation."""
    pieces = [_p(f"p{i}") for i in range(5)]
    allowed = [[0.0, 180.0] for _ in pieces]  # each piece COULD flip
    seen = []

    def stub(pieces_in_order, per_piece_rots):
        seen.append([r[0] for r in per_piece_rots])
        return [], 1.0, 0.0

    cfg = sa.SAConfig(move_weights={"swap": 1.0, "reverse": 0.0, "rotation_flip": 0.0})
    sa.run_sa(list(range(5)), [0.0] * 5, pieces, allowed,
              iterations=50, max_time_s=None, seed=7, evaluator=stub, config=cfg)
    assert seen  # evaluator was called
    assert all(all(r == 0.0 for r in snap) for snap in seen)  # no 180 ever proposed
