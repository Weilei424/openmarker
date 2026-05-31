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
