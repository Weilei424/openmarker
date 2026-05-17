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
    """Placed polygons may touch but must not have positive-area overlap."""
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
        rotated = shapely.affinity.rotate(poly, pl.rotation_deg, origin=(0, 0))
        minx, miny = rotated.bounds[0], rotated.bounds[1]
        placed.append(shapely.affinity.translate(rotated, xoff=-minx + pl.x, yoff=-miny + pl.y))

    for i, a in enumerate(placed):
        for j, b in enumerate(placed):
            if i < j:
                # Touching at shared edges yields intersection area = 0 (allowed).
                # Only positive-area overlap is a collision.
                overlap_area = a.intersection(b).area if a.intersects(b) else 0.0
                assert overlap_area < 1e-3, f"Pieces {i} and {j} overlap by {overlap_area:.4f} mm²"


def test_polygon_blf_fills_gap_above_shorter_neighbor():
    """BLF should place a small piece in the gap above a shorter neighbor,
    not start a new shelf below the tallest piece. This is the failure mode
    of pure shelf-packing that BLF specifically fixes."""
    # piece_A: 100x200 (tall). piece_B: 100x100 (short).
    # After placing A at (10, 10) and B at (110, 10), there's an L-shaped
    # gap to the right of B and above A's bottom. piece_C (100x50) fits there
    # at approximately (110, 110) — touching B's bottom and A's right.
    a = _make_rect("A", 100, 200)
    b = _make_rect("B", 100, 100)
    c = _make_rect("C", 100, 50)
    placements, _, _ = auto_layout_polygon(
        [a, b, c], fabric_width_mm=300, grain_mode="none", fabric_grain_deg=0.0
    )

    pl_c = next(pl for pl in placements if pl.piece_id == "C")
    # Below A's bottom edge (which is ~210) would mean a new shelf. BLF must
    # find the gap above A's bottom — piece C must sit at y < 200.
    assert pl_c.y < 200, (
        f"BLF failed to fill the gap above the shorter neighbor; "
        f"piece C ended up at y={pl_c.y} (expected < 200)"
    )


def test_polygon_touching_is_not_collision():
    """Two squares placed edge-to-edge with no inter-piece gap should both
    succeed (touching boundaries is allowed; only positive-area overlap is rejected)."""
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=350, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 3
    # In a 350mm-wide fabric with EDGE_GAP=10 on each side, the usable width is
    # 330mm. Three 100mm squares (3*100=300) need at most 30mm of slack,
    # so they should all land on the same shelf (touching each other).
    ys = {pl.y for pl in placements}
    assert len(ys) == 1, f"expected single shelf with touching pieces; got y-values {ys}"


def test_polygon_grain_single_enforced():
    """piece_grain=270°, fabric=0°, single mode → target=(0-270)%360=90°."""
    pieces = [_make_rect(f"p{i}", 80, 150, grainline_deg=270.0) for i in range(3)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=900, grain_mode="single", fabric_grain_deg=0.0
    )
    for pl in placements:
        assert pl.rotation_deg == pytest.approx(90.0, abs=0.01)
