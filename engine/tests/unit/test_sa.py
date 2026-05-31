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
