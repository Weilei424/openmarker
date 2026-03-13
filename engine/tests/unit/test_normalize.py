# Unit tests for engine/core/geometry/normalize.py

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
