# Unit tests for engine/core/geometry/normalize.py

import math
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.dxf.parser import RawPiece
from core.geometry.normalize import normalize_piece


def make_raw(points, layer="TEST") -> RawPiece:
    return RawPiece(layer=layer, points=points, is_closed=True)


def test_normalize_rectangle():
    # Offset rectangle at (50, 30), 100x80
    pts = [(50, 30), (150, 30), (150, 110), (50, 110)]
    piece = normalize_piece(make_raw(pts), "piece_0")
    assert piece.bbox.min_x == pytest.approx(0.0)
    assert piece.bbox.min_y == pytest.approx(0.0)
    assert piece.bbox.width == pytest.approx(100.0)
    assert piece.bbox.height == pytest.approx(80.0)
    assert piece.id == "piece_0"
    assert piece.name == "TEST"


def test_normalize_area_correct():
    # Right triangle with base=100, height=80 -> area=4000
    pts = [(0, 0), (100, 0), (0, 80)]
    piece = normalize_piece(make_raw(pts), "piece_0")
    assert piece.area == pytest.approx(4000.0, rel=1e-5)


def test_self_intersecting_repaired():
    # Bowtie / figure-8: self-intersecting polygon
    pts = [(0, 0), (100, 100), (100, 0), (0, 100)]
    piece = normalize_piece(make_raw(pts), "piece_0")
    assert piece.is_valid is True
    assert len(piece.validation_notes) > 0


def test_too_few_points_raises():
    pts = [(0, 0), (100, 0)]
    with pytest.raises(ValueError):
        normalize_piece(make_raw(pts), "piece_0")


def test_polygon_is_origin_translated():
    # Arbitrary polygon far from origin
    pts = [(500, 300), (600, 300), (600, 400), (500, 400)]
    piece = normalize_piece(make_raw(pts), "piece_0")
    xs = [x for x, _ in piece.polygon]
    ys = [y for _, y in piece.polygon]
    assert min(xs) == pytest.approx(0.0, abs=1e-6)
    assert min(ys) == pytest.approx(0.0, abs=1e-6)


def test_y_flip_triangle_orientation():
    """A triangle with positive DXF Y-coords should have Y-coords flipped after normalization."""
    # Triangle in DXF space (Y-up): tip at top
    raw = RawPiece(
        layer="test",
        points=[(0.0, 0.0), (50.0, 100.0), (100.0, 0.0)],
        is_closed=True,
    )
    piece = normalize_piece(raw, "p0")
    # After Y-flip: (0,0)→(0,0), (50,100)→(50,-100), (100,0)→(100,0)
    # min_y = -100 → translate yoff=+100
    # Expected coords: (0,100), (50,0), (100,100) — tip now at bottom (y=0)
    ys = [pt[1] for pt in piece.polygon]
    # The minimum y in the normalized polygon should be 0
    assert min(ys) == pytest.approx(0.0, abs=1e-3)
    # The tip (originally at y=100 in DXF) should now be at the minimum y
    # i.e., the DXF "high" point becomes the canvas "low" point
    tip_x = 50.0
    tip_point = next(pt for pt in piece.polygon if abs(pt[0] - tip_x) < 0.01)
    assert tip_point[1] == pytest.approx(0.0, abs=1e-3)


def test_grainline_horizontal_gives_0_degrees():
    """A horizontal grainline (pointing right in DXF) → 0° in canvas space."""
    raw = RawPiece(
        layer="test",
        points=[(0.0, 0.0), (100.0, 0.0), (100.0, 200.0), (0.0, 200.0)],
        is_closed=True,
        grainline=((10.0, -50.0), (90.0, -50.0)),  # horizontal, both y same
    )
    piece = normalize_piece(raw, "p0")
    assert piece.grainline_direction_deg is not None
    assert piece.grainline_direction_deg == pytest.approx(0.0, abs=0.01)


def test_grainline_vertical_in_dxf_gives_270_degrees():
    """
    A vertical DXF grainline pointing upward (start_y < end_y in DXF Y-up space)
    becomes 270° in canvas Y-down space (pointing upward on screen).
    """
    raw = RawPiece(
        layer="test",
        points=[(0.0, -200.0), (100.0, -200.0), (100.0, 200.0), (0.0, 200.0)],
        is_closed=True,
        # Grainline in DXF: start lower, end higher (pointing UP in DXF Y-up)
        grainline=((50.0, -100.0), (50.0, 100.0)),
    )
    piece = normalize_piece(raw, "p0")
    assert piece.grainline_direction_deg is not None
    # After Y-flip: start_y=100, end_y=-100 → dy = -200 → atan2(-200,0) = -90° → 270°
    assert piece.grainline_direction_deg == pytest.approx(270.0, abs=0.01)


def test_grainline_absent_gives_none():
    raw = RawPiece(
        layer="test",
        points=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        is_closed=True,
        grainline=None,
    )
    piece = normalize_piece(raw, "p0")
    assert piece.grainline_direction_deg is None
