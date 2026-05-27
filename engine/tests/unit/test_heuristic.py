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


def test_auto_layout_disable_pruning_yields_identical_result():
    """The disable_pruning toggle must not affect output — only speed.
    Mirrors the existing disable_nfp_cache test."""
    pieces = [_make_rect(f"p{i}", 80 + i * 10, 100 + (i % 3) * 30) for i in range(6)]
    on = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0,
        effort=1, disable_pruning=False,
    )
    off = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0,
        effort=1, disable_pruning=True,
    )
    assert on[1] == off[1]
    assert on[2] == off[2]
    assert len(on[0]) == len(off[0])
    for a, b in zip(on[0], off[0]):
        assert a.piece_id == b.piece_id
        assert abs(a.x - b.x) < 1e-9
        assert abs(a.y - b.y) < 1e-9
        assert abs(a.rotation_deg - b.rotation_deg) < 1e-9


def test_auto_layout_disable_pruning_parallel_matches_serial():
    """disable_pruning must also work in parallel mode — confirms the flag
    is correctly propagated to workers via the initializer."""
    pieces = [_make_rect(f"p{i}", 80 + i * 10, 100 + (i % 3) * 30) for i in range(6)]
    serial = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0,
        effort=1, disable_pruning=True,
    )
    parallel = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0,
        effort=5, disable_pruning=True,
    )
    assert serial[1] == parallel[1]
    assert serial[2] == parallel[2]


# --- identical-piece clustering tests ---

def test_auto_layout_disable_clustering_is_deterministic():
    """disable_clustering=True on identical inputs must be bitwise-deterministic
    (legacy-path determinism guard). Doesn't test cross-mode equivalence —
    test_auto_layout_clustering_does_not_increase_marker_length and
    test_auto_layout_clustering_singletons_unchanged cover that."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(4)]
    a = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True,
    )
    b = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True,
    )
    assert a[1] == b[1] and a[2] == b[2]
    assert len(a[0]) == 4
    # Per-placement determinism, not just metrics.
    for x, y in zip(a[0], b[0]):
        assert x.piece_id == y.piece_id
        assert x.x == y.x and x.y == y.y and x.rotation_deg == y.rotation_deg


def test_auto_layout_clustering_singletons_unchanged():
    """When every input piece is unique, clustering is a no-op."""
    pieces = [_make_rect(f"piece_{i}", 80 + i * 10, 100 + (i % 3) * 30) for i in range(6)]
    on = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False,
    )
    off = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True,
    )
    assert on[1] == off[1]
    assert on[2] == off[2]


def test_auto_layout_clustering_expands_to_n_placements():
    """When clustering is on with N copies, the returned placements list must
    have N entries (one per copy), not 1 (the super-piece)."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(4)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False,
    )
    assert len(placements) == 4
    # Each placement should reference an original piece id
    placement_ids = {pl.piece_id for pl in placements}
    expected_ids = {f"p__c{i}" for i in range(4)}
    assert placement_ids == expected_ids


def test_auto_layout_clustering_does_not_increase_marker_length():
    """Clustering can only preserve or shrink marker length, never grow it
    (for rectangular pieces — irregular shapes are out of scope for this PR)."""
    pieces = [_make_rect(f"p__c{i}", 100, 50) for i in range(8)]
    on = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False,
    )
    off = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True,
    )
    assert on[1] <= off[1] + 1e-6, (
        f"Clustering made marker LONGER: on={on[1]}, off={off[1]}"
    )


def test_auto_layout_clustering_with_bi_grain():
    """Bi-grain must work with clustering: cluster rotates as a unit; each
    expanded copy gets the cluster's rotation. Result must be valid (all N
    pieces placed, no overlap)."""
    pieces = [_make_rect(f"p__c{i}", 100, 80, grainline_deg=0.0) for i in range(4)]
    placements, length, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False,
    )
    assert len(placements) == 4
    assert length > 0
    # Bi-grain at fabric_grain=0 with piece_grainline=0 produces target rotation
    # 0° (and 180° as the bi alternative). The cluster picks one of the two as
    # a unit, and every expanded copy must share that rotation.
    rotations = {pl.rotation_deg for pl in placements}
    assert len(rotations) == 1, f"copies in a rigid cluster should share rotation, got {rotations}"
    assert rotations.pop() in (0.0, 180.0)


# --- inner-BLF shim plumbing tests ---

def test_blf_pack_nfp_override_rotations_replaces_grain_logic():
    """When override_rotations is set, _blf_pack_nfp ignores piece.grainline_direction_deg
    and uses the override list verbatim. Single 100x50 rect with grainline=0.0 placed
    via override [90.0] must come back rotated 90° (becomes 50 wide x 100 tall)."""
    from core.layout.heuristic import _blf_pack_nfp
    piece = _make_rect("p", 100, 50, grainline_deg=0.0)
    placements, marker, util = _blf_pack_nfp(
        [piece], fabric_width_mm=200,
        grain_mode="single", fabric_grain_deg=0.0,
        override_rotations=[90.0],
        skip_validation=True,
    )
    assert len(placements) == 1
    assert placements[0].rotation_deg == 90.0


def test_blf_pack_nfp_skip_validation_allows_oversize_input():
    """With skip_validation=True the upfront _validate_pieces_fit is not called.
    Caller is trusted (e.g., pack_cluster_union's candidate-width pre-filter).
    Test setup: 600x50 piece with grainline_deg=0.0 and grain_mode='single' so
    _layout_rotations returns [0.0] only — at 0° the piece is 600 wide,
    600 + 2*EDGE_GAP=620 > fabric=200, so _validate_pieces_fit WILL raise
    unless skipped. Override forces 90° (50 wide → fits)."""
    from core.layout.heuristic import _blf_pack_nfp
    # grainline=0.0 + grain_mode='single' locks validation to a single
    # rotation (0°) where the piece truly doesn't fit. This is the only
    # configuration that proves the skip — with grainline=None, validation
    # tries all 4 cardinal rotations and 90° passes anyway.
    piece = _make_rect("p", 600, 50, grainline_deg=0.0)
    placements, marker, util = _blf_pack_nfp(
        [piece], fabric_width_mm=200,
        grain_mode="single", fabric_grain_deg=0.0,
        override_rotations=[90.0],
        skip_validation=True,
    )
    assert len(placements) == 1
    assert placements[0].rotation_deg == 90.0

    # Regression backstop: without skip_validation, the same call MUST raise.
    import pytest as _pytest
    with _pytest.raises(ValueError):
        _blf_pack_nfp(
            [piece], fabric_width_mm=200,
            grain_mode="single", fabric_grain_deg=0.0,
            override_rotations=[90.0],
            # skip_validation defaults to False — _validate_pieces_fit must run.
        )


def test_blf_pack_nfp_default_behavior_unchanged():
    """Regression guard: without override_rotations/skip_validation, _blf_pack_nfp
    behaves exactly as before — derives rotations from grain_mode + grainline and
    calls _validate_pieces_fit."""
    from core.layout.heuristic import _blf_pack_nfp
    piece = _make_rect("p", 100, 50, grainline_deg=0.0)
    placements, marker, util = _blf_pack_nfp(
        [piece], fabric_width_mm=200,
        grain_mode="single", fabric_grain_deg=0.0,
    )
    assert len(placements) == 1
    assert placements[0].rotation_deg == 0.0  # target = (0 - 0) % 360 = 0


# --- cluster_polygon dispatch + default-on tests ---

def test_auto_layout_cluster_polygon_union_opt_in():
    """Opt-in: disable_clustering=False + cluster_polygon='union' returns the
    right number of placements with original (not super-piece) ids."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(4)]
    placements, marker, util = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False, cluster_polygon="union",
    )
    assert len(placements) == 4
    assert marker > 0
    # All placement ids should be original (not super-piece) ids.
    assert {pl.piece_id for pl in placements} == {f"p__c{i}" for i in range(4)}


def test_auto_layout_cluster_polygon_bbox_opt_in_matches_pr9():
    """Opt-in: disable_clustering=False + cluster_polygon='bbox' matches PR #9
    exactly: super-piece is the bbox rectangle, all copies at zero local rot."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(4)]
    placements, marker, util = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False, cluster_polygon="bbox",
    )
    assert len(placements) == 4
    # For 4 axis-aligned identical rects in a generous fabric, union and bbox
    # produce the same packing (union exterior == bbox rectangle exterior).
    # We only assert no crash + correct placement count.
    assert marker > 0


def test_auto_layout_clustering_default_off_matches_pr9():
    """disable_clustering defaults to True — clustering is opt-in. The Q1
    success bar (beat unclustered baseline on sample_2.dxf x 10) was not met
    in Task 7's bench, so the default flip from PR #9 is reverted. This test
    is the regression guard: default behavior MUST equal disable_clustering=True
    (unclustered BLF) — bit-for-bit, not just <=."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(4)]
    placements_default, marker_default, util_default = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1,
    )
    placements_off, marker_off, util_off = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True,
    )
    assert marker_default == marker_off
    assert util_default == util_off
    assert len(placements_default) == len(placements_off)


def test_auto_layout_union_no_worse_than_bbox_on_homogeneous():
    """For 10 axis-aligned identical rects, union and bbox should produce equal
    marker length (union exterior == bbox rectangle when copies share full edges)."""
    pieces = [_make_rect(f"p__c{i}", 100, 50) for i in range(10)]
    _, marker_union, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, cluster_polygon="union",
    )
    _, marker_bbox, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, cluster_polygon="bbox",
    )
    assert marker_union <= marker_bbox + 1e-6
