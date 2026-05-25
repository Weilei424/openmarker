import pytest
from core.models.piece import Piece, BoundingBox
from core.layout.heuristic import auto_layout_polygon, Placement


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


# --- polygon mode tests ---

def test_polygon_single_piece_placed():
    pieces = [_make_square("p0", 100)]
    placements, length, utilization = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0
    )
    assert len(placements) == 1
    assert length > 0
    assert utilization > 0


def test_polygon_three_squares_all_placed():
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0
    )
    assert len(placements) == 3


def test_polygon_no_overlaps():
    """Placed polygons may touch but must not have positive-area overlap."""
    pieces = [_make_rect(f"p{i}", 80 + i * 10, 120) for i in range(5)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=600, grain_mode="single", fabric_grain_deg=0.0
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
                # Engine permits sub-mm² overlaps (matches frontend SAT tolerance).
                # Anything larger indicates a real placement bug.
                overlap_area = a.intersection(b).area if a.intersects(b) else 0.0
                assert overlap_area < 0.5, f"Pieces {i} and {j} overlap by {overlap_area:.4f} mm²"


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
        [a, b, c], fabric_width_mm=300, grain_mode="single", fabric_grain_deg=0.0
    )

    pl_c = next(pl for pl in placements if pl.piece_id == "C")
    # Below A's bottom edge (which is ~210) would mean a new shelf. BLF must
    # find the gap above A's bottom — piece C must sit at y < 200.
    assert pl_c.y < 200, (
        f"BLF failed to fill the gap above the shorter neighbor; "
        f"piece C ended up at y={pl_c.y} (expected < 200)"
    )


def test_polygon_nfp_triangles_nest_diagonally():
    """NFP-BLF should pack right triangles much tighter than bbox shelf-packing
    can, because two triangles fit inside one rectangle's bbox when their
    hypotenuses meet. Bbox-strip-pack treats each triangle as a full rectangle
    and wastes ~half the space."""
    def tri(name, w, h):
        return Piece(
            id=name, name=name,
            polygon=[(0, 0), (w, 0), (0, h)],
            area=w * h / 2,
            bbox=BoundingBox(0, 0, w, h, w, h),
            is_valid=True,
            grainline_direction_deg=None,
        )

    # 8 right triangles in a 500mm fabric. Each triangle: area = 100*200/2 = 10000 mm².
    # Bbox-shelf would treat each as a 100*200 rectangle (4 per row of 500mm,
    # 2 rows → length ~410mm → util ~40%). NFP-BLF should nest pairs of
    # triangles into shared 100*200 rectangles (one 0°, one 180° per pair) and
    # reach much higher utilization.
    pieces = [tri(f"t{i}", 100, 200) for i in range(8)]
    placements, length, util = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0
    )
    assert len(placements) == 8
    assert util > 60.0, (
        f"NFP-BLF should achieve >60% utilization on right triangles via "
        f"diagonal nesting; got {util}% (length={length}mm). Bbox-shelf "
        f"typically gets ~35% on this input."
    )


def test_polygon_touching_is_not_collision():
    """Two squares placed edge-to-edge with no inter-piece gap should both
    succeed (touching boundaries is allowed; only positive-area overlap is rejected)."""
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=350, grain_mode="single", fabric_grain_deg=0.0
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


def test_polygon_disable_nfp_cache_yields_identical_result():
    """The disable_nfp_cache toggle must not affect output — only speed."""
    pieces = [_make_rect(f"p{i}", 100, 80) for i in range(3)]
    on = auto_layout_polygon(
        pieces, fabric_width_mm=1500, grain_mode="single", fabric_grain_deg=90.0,
        disable_nfp_cache=False,
    )
    off = auto_layout_polygon(
        pieces, fabric_width_mm=1500, grain_mode="single", fabric_grain_deg=90.0,
        disable_nfp_cache=True,
    )
    assert on[1] == off[1]  # marker length
    assert on[2] == off[2]  # utilization
    assert len(on[0]) == len(off[0])
    for a, b in zip(on[0], off[0]):
        assert a.piece_id == b.piece_id
        assert abs(a.x - b.x) < 1e-9
        assert abs(a.y - b.y) < 1e-9
        assert abs(a.rotation_deg - b.rotation_deg) < 1e-9


def test_auto_layout_effort_serial_and_parallel_match():
    """effort=1 (serial) and effort=5 (parallel) must yield identical results."""
    # Use enough pieces to trigger the pool path (total_runs * pieces >= 20).
    # 4 strategies × 1 mode = 4 runs; need >= 5 pieces.
    pieces = [_make_rect(f"p{i}", 100 + i * 5, 80 + i * 3) for i in range(6)]
    serial = auto_layout_polygon(
        pieces, fabric_width_mm=1500, grain_mode="single",
        fabric_grain_deg=90.0, effort=1,
    )
    parallel = auto_layout_polygon(
        pieces, fabric_width_mm=1500, grain_mode="single",
        fabric_grain_deg=90.0, effort=5,
    )
    # Marker length and utilization are deterministic given identical inputs;
    # placements may differ if multiple strategies tie on length, but both
    # are valid "best" choices.
    assert serial[1] == parallel[1]
    assert serial[2] == parallel[2]


def test_auto_layout_effort_out_of_range_clamps_or_raises():
    """Engine treats effort=10 as 'max effort' — clamps to cpu_count. We do
    NOT raise from the heuristic; the API layer handles validation."""
    pieces = [_make_rect(f"p{i}", 100, 80) for i in range(3)]
    # Should not raise.
    auto_layout_polygon(
        pieces, fabric_width_mm=1500, grain_mode="single",
        fabric_grain_deg=90.0, effort=10,
    )



def test_kill_current_executor_no_op_when_none():
    """Calling kill before any layout runs must not raise."""
    from core.layout.heuristic import kill_current_executor
    kill_current_executor()  # should be silent no-op


# --- branch pruning tests ---

def test_blf_default_no_pruning_behavior_unchanged():
    """Two calls with best_marker_so_far=None must produce identical output —
    pins that the default code path is deterministic and unaffected by the
    new parameter."""
    from core.layout.heuristic import _blf_pack_nfp
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    a_pl, a_len, a_util = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0
    )
    b_pl, b_len, b_util = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0
    )
    assert len(a_pl) == 3 and len(b_pl) == 3
    assert a_len == b_len
    assert a_util == b_util
    for pa, pb in zip(a_pl, b_pl):
        assert pa.piece_id == pb.piece_id
        assert pa.x == pb.x and pa.y == pb.y and pa.rotation_deg == pb.rotation_deg


def test_blf_high_cutoff_runs_to_completion():
    """A cutoff above any plausible result should not trigger pruning."""
    from core.layout.heuristic import _blf_pack_nfp
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    placements, length, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        best_marker_so_far=1e9,
    )
    assert len(placements) == 3
    assert length > 0


def test_blf_tight_cutoff_raises_pruned_run():
    """A cutoff at zero must trigger _PrunedRun before completion."""
    from core.layout.heuristic import _blf_pack_nfp, _PrunedRun
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    with pytest.raises(_PrunedRun):
        _blf_pack_nfp(
            pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
            best_marker_so_far=0.0,
        )


def test_blf_cutoff_just_above_optimal_does_not_prune():
    """A cutoff strictly larger than the actual final marker length should
    allow the run to finish. Run once to learn the length, then run again
    with cutoff = length + 1 mm."""
    from core.layout.heuristic import _blf_pack_nfp
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    _, length, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0
    )
    placements2, length2, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        best_marker_so_far=length + 1.0,
    )
    assert len(placements2) == 3
    assert abs(length2 - length) < 1e-6


def test_auto_layout_serial_pruning_matches_unpruned_best():
    """auto_layout_polygon (with the new pruning wired in) must equal the
    best across all strategies run individually without a cutoff. If pruning
    ever silently discarded the winning run, this would fail."""
    from core.layout.heuristic import _blf_pack_nfp, _SORT_STRATEGIES
    pieces = [_make_rect(f"p{i}", 80 + i * 10, 120) for i in range(5)]
    pruned = auto_layout_polygon(
        pieces, fabric_width_mm=600, grain_mode="single", fabric_grain_deg=0.0, effort=1
    )
    # Independent baseline: every strategy run with no cutoff, take the shortest.
    unpruned_best_length = None
    for sk in _SORT_STRATEGIES:
        _, length, _ = _blf_pack_nfp(
            pieces, fabric_width_mm=600, grain_mode="single", fabric_grain_deg=0.0,
            sort_key=sk,
        )
        if unpruned_best_length is None or length < unpruned_best_length:
            unpruned_best_length = length
    assert pruned[1] == unpruned_best_length


# --- shared-cutoff (parallel pruning) tests ---

def test_blf_shared_value_none_behaves_like_serial():
    """When shared_best_value is None, behavior is bitwise identical to omitting it.
    Compares full placement geometry, not just length, so a regression that
    shifts placements while preserving length would still fail."""
    from core.layout.heuristic import _blf_pack_nfp
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    pa, la, ua = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0
    )
    pb, lb, ub = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        shared_best_value=None,
    )
    assert la == lb
    assert ua == ub
    assert len(pa) == len(pb)
    for x, y in zip(pa, pb):
        assert x.piece_id == y.piece_id
        assert x.x == y.x and x.y == y.y and x.rotation_deg == y.rotation_deg


def test_blf_shared_value_infinity_does_not_prune():
    """A Value initialized to infinity (no cutoff yet) must not trigger pruning."""
    import multiprocessing
    from core.layout.heuristic import _blf_pack_nfp
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    shared = multiprocessing.Value("d", float("inf"))
    placements, length, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        shared_best_value=shared,
    )
    assert len(placements) == 3
    assert length > 0


def test_blf_shared_value_tight_cutoff_prunes():
    """A shared Value with a tight cutoff must raise _PrunedRun mid-run."""
    import multiprocessing
    from core.layout.heuristic import _blf_pack_nfp, _PrunedRun
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    shared = multiprocessing.Value("d", 1.0)  # any non-trivial placement exceeds this
    with pytest.raises(_PrunedRun):
        _blf_pack_nfp(
            pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
            shared_best_value=shared,
        )


def test_blf_shared_value_takes_min_with_kwarg():
    """When both best_marker_so_far and shared_best_value are provided, the
    effective cutoff is the minimum (the tighter of the two prunes)."""
    import multiprocessing
    from core.layout.heuristic import _blf_pack_nfp, _PrunedRun
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    # Kwarg is loose (1e9). Shared is tight (1.0). Effective = 1.0 → prune.
    shared = multiprocessing.Value("d", 1.0)
    with pytest.raises(_PrunedRun):
        _blf_pack_nfp(
            pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
            best_marker_so_far=1e9,
            shared_best_value=shared,
        )

    # Inverted: kwarg tight, shared loose → still prune via kwarg.
    shared_loose = multiprocessing.Value("d", float("inf"))
    with pytest.raises(_PrunedRun):
        _blf_pack_nfp(
            pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
            best_marker_so_far=1.0,
            shared_best_value=shared_loose,
        )

    # Both loose → min(loose, loose) is still loose → no prune, run completes.
    # Guards against a buggy `min` that returns 0 or NaN when both inputs are present.
    shared_loose2 = multiprocessing.Value("d", float("inf"))
    placements, length, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        best_marker_so_far=1e9,
        shared_best_value=shared_loose2,
    )
    assert len(placements) == 3
    assert length > 0


def test_auto_layout_parallel_pruning_matches_serial():
    """Parallel mode with shared-Value pruning must produce the same chosen
    layout as the serial path. Result quality must never depend on whether
    pruning is on or off, or on the worker count."""
    # Pieces are mixed-size rects — different sort strategies diverge,
    # so multiple workers are exercised and at least one is prunable.
    pieces = [_make_rect(f"p{i}", 80 + i * 10, 100 + (i % 3) * 30) for i in range(6)]
    serial = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0, effort=1
    )
    parallel = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0, effort=5
    )
    assert serial[1] == parallel[1]  # marker length
    assert serial[2] == parallel[2]  # utilization
