import pytest
from core.models.piece import Piece, BoundingBox
from core.layout.heuristic import auto_layout_bbox, auto_layout_polygon, Placement


def _make_square(piece_id: str, size: float, grainline_deg: float | None = None) -> Piece:
    """Helper: square piece of given side length."""
    return Piece(
        id=piece_id,
        name=piece_id,
        polygon=[(0, 0), (size, 0), (size, size), (0, size)],
        area=size * size,
        bbox=BoundingBox(0, 0, size, size, size, size),
        is_valid=True,
        grainline_direction_deg=grainline_deg,
    )


def _make_rect(piece_id: str, w: float, h: float, grainline_deg: float | None = None) -> Piece:
    return Piece(
        id=piece_id,
        name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        grainline_direction_deg=grainline_deg,
    )


# --- bbox mode tests ---

def test_bbox_single_piece_placed():
    pieces = [_make_square("p0", 100)]
    placements, length, utilization = auto_layout_bbox(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 1
    assert placements[0].piece_id == "p0"
    assert placements[0].x >= 0
    assert placements[0].y >= 0


def test_bbox_three_equal_squares_single_shelf():
    """3 × 100mm squares should fit on one shelf in a 500mm fabric."""
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    placements, length, utilization = auto_layout_bbox(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 3
    ys = {pl.y for pl in placements}
    assert len(ys) == 1, "All pieces should be on the same shelf"


def test_bbox_pieces_overflow_to_new_shelf():
    """4 × 200mm squares in 500mm fabric: first 2 fit on shelf 1, next 2 on shelf 2."""
    pieces = [_make_square(f"p{i}", 200) for i in range(4)]
    placements, length, utilization = auto_layout_bbox(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 4
    ys = sorted({pl.y for pl in placements})
    assert len(ys) == 2, "Should span exactly 2 shelves"


def test_bbox_no_piece_exceeds_fabric_width():
    pieces = [_make_square(f"p{i}", 100) for i in range(5)]
    placements, length, _ = auto_layout_bbox(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    for pl in placements:
        piece = next(p for p in pieces if p.id == pl.piece_id)
        assert pl.x + piece.bbox.width <= 500 + 0.01


def test_bbox_piece_wider_than_fabric_raises():
    pieces = [_make_square("huge", 600)]
    with pytest.raises(ValueError, match="cannot fit"):
        auto_layout_bbox(pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0)


def test_bbox_single_grain_enforced():
    """piece_grain=270°, fabric=0°, single mode → target=(0-270)%360=90°."""
    pieces = [_make_rect(f"p{i}", 80, 120, grainline_deg=270.0) for i in range(3)]
    placements, _, _ = auto_layout_bbox(
        pieces, fabric_width_mm=800, grain_mode="single", fabric_grain_deg=0.0
    )
    for pl in placements:
        assert pl.rotation_deg == pytest.approx(90.0, abs=0.01)


def test_bbox_utilization_positive():
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    _, _, utilization = auto_layout_bbox(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert 0 < utilization <= 100


# --- polygon mode tests ---

def test_polygon_single_piece_placed():
    pieces = [_make_square("p0", 100)]
    placements, length, utilization = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 1
    assert length > 0
    assert utilization > 0


def test_polygon_three_squares_all_placed():
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 3


def test_polygon_no_overlaps():
    """Placed polygons must not intersect each other."""
    pieces = [_make_rect(f"p{i}", 80 + i * 10, 120) for i in range(5)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=600, grain_mode="none", fabric_grain_deg=0.0
    )
    from shapely.geometry import Polygon as SP
    import shapely.affinity

    placed = []
    for pl in placements:
        piece = next(p for p in pieces if p.id == pl.piece_id)
        poly = SP(piece.polygon)
        rotated = shapely.affinity.rotate(poly, -pl.rotation_deg, origin=(0, 0))
        minx, miny = rotated.bounds[0], rotated.bounds[1]
        placed.append(shapely.affinity.translate(rotated, xoff=-minx + pl.x, yoff=-miny + pl.y))

    for i, a in enumerate(placed):
        for j, b in enumerate(placed):
            if i < j:
                assert not a.intersects(b), f"Pieces {i} and {j} overlap"


def test_polygon_grain_single_enforced():
    """piece_grain=270°, fabric=0°, single mode → target=(0-270)%360=90°."""
    pieces = [_make_rect(f"p{i}", 80, 150, grainline_deg=270.0) for i in range(3)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=900, grain_mode="single", fabric_grain_deg=0.0
    )
    for pl in placements:
        assert pl.rotation_deg == pytest.approx(90.0, abs=0.01)
