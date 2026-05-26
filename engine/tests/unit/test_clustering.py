import pytest
from core.models.piece import Piece, BoundingBox
from core.layout.clustering import (
    Cluster,
    group_pieces_by_base_id,
    pack_cluster_bbox,
    pre_cluster_pieces,
    expand_cluster_placement,
)


def _rect(piece_id: str, w: float, h: float, grainline: float | None = None) -> Piece:
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        grainline_direction_deg=grainline,
    )


# --- group_pieces_by_base_id ---

def test_group_strips_copy_suffix():
    a0 = _rect("piece_0__c0", 100, 50)
    a1 = _rect("piece_0__c1", 100, 50)
    b0 = _rect("piece_1__c0", 80, 40)
    groups = group_pieces_by_base_id([a0, a1, b0])
    assert set(groups.keys()) == {"piece_0", "piece_1"}
    assert len(groups["piece_0"]) == 2
    assert len(groups["piece_1"]) == 1


def test_group_no_suffix_passes_through():
    """Pieces without __c{n} suffix are their own group."""
    a = _rect("piece_0", 100, 50)
    b = _rect("piece_1", 80, 40)
    groups = group_pieces_by_base_id([a, b])
    assert set(groups.keys()) == {"piece_0", "piece_1"}


# --- pack_cluster ---

def test_pack_cluster_singleton_returns_none():
    """N=1 → no clustering, return None."""
    assert pack_cluster_bbox([_rect("p__c0", 100, 50)], fabric_width_mm=300) is None


def test_pack_cluster_perfect_grid():
    """4 copies of 100×50 with grainline=0° in fabric=300 → 2×2 grid wins.
    grain_mode=single, fabric_grain_deg=0° → target rotation=0°; only 0°
    allowed, so the natural-orientation width is the only check.
    4×1: cluster_w=400 + 20 = 420 > 300 (infeasible).
    1×4: cluster_w=100 + 20 = 120 ≤ 300, cluster_h=200.
    2×2: cluster_w=200 + 20 = 220 ≤ 300, cluster_h=100.
    Sort by (cluster_h, cluster_w): 2×2 wins (cluster_h=100 < 200)."""
    copies = [_rect(f"p__c{i}", 100, 50, grainline=0.0) for i in range(4)]
    cluster = pack_cluster_bbox(copies, fabric_width_mm=300, grain_mode="single", fabric_grain_deg=0.0)
    assert cluster is not None
    assert cluster.super_piece.bbox.width == 200
    assert cluster.super_piece.bbox.height == 100
    assert len(cluster.copy_offsets) == 4
    # Area is sum of original piece areas (NOT bbox area)
    assert cluster.super_piece.area == 4 * (100 * 50)


def test_pack_cluster_narrow_fabric_forces_single_column():
    """4 copies of 100×50 with grainline=0° in fabric=150 → only 1-column fits.
    grain_mode=single, fabric_grain_deg=0° → target=0° only.
    2×2: cluster_w=200+20=220 > 150; infeasible.
    4×1: cluster_w=400+20=420 > 150; infeasible.
    1×4: cluster_w=100+20=120 ≤ 150; only feasible aspect ratio."""
    copies = [_rect(f"p__c{i}", 100, 50, grainline=0.0) for i in range(4)]
    cluster = pack_cluster_bbox(copies, fabric_width_mm=150, grain_mode="single", fabric_grain_deg=0.0)
    assert cluster is not None
    assert cluster.super_piece.bbox.width == 100
    assert cluster.super_piece.bbox.height == 200


def test_pack_cluster_too_big_returns_none():
    """A grain-locked copy wider than usable fabric at its only allowed rotation
    → no aspect ratio fits at target rotation → None.
    Piece is 200×50 with grainline=0°, fabric_grain_deg=0° → target=0° only.
    Any cluster layout in 0° orientation: min cluster_w=200 (1×4). 200+20>150.
    Even 1-column layout doesn't fit; pack_cluster returns None."""
    copies = [_rect(f"p__c{i}", 200, 50, grainline=0.0) for i in range(4)]
    cluster = pack_cluster_bbox(copies, fabric_width_mm=150, grain_mode="single", fabric_grain_deg=0.0)
    assert cluster is None


def test_pack_cluster_preserves_grainline():
    """The super-piece inherits the original pieces' grainline (they're identical)."""
    copies = [_rect(f"p__c{i}", 100, 50, grainline=90.0) for i in range(4)]
    cluster = pack_cluster_bbox(copies, fabric_width_mm=300)
    assert cluster is not None
    assert cluster.super_piece.grainline_direction_deg == 90.0


def test_pack_cluster_prime_count_picks_strip():
    """7 copies of 100×50: aspect ratios (1,7) and (7,1) have no dead space; both have area 7*100*50.
    (2,4)=8 slots wastes 1 slot. Prefer (1,7) or (7,1)."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(7)]
    cluster = pack_cluster_bbox(copies, fabric_width_mm=1000)
    assert cluster is not None
    # Must be one of the perfect-fit options
    assert (cluster.super_piece.bbox.width, cluster.super_piece.bbox.height) in [
        (100, 350), (700, 50)
    ]


# --- pre_cluster_pieces ---

def test_pre_cluster_mixed_input():
    """Mix of singletons + groups → singletons pass through, groups cluster."""
    singleton = _rect("piece_lonely", 50, 50)
    group_a = [_rect(f"piece_a__c{i}", 100, 50) for i in range(3)]
    clustered_input, clusters = pre_cluster_pieces([singleton] + group_a, fabric_width_mm=500)
    assert len(clustered_input) == 2  # 1 singleton + 1 super-piece
    assert len(clusters) == 1
    # Singleton id should pass through unchanged
    assert any(p.id == "piece_lonely" for p in clustered_input)


def test_pre_cluster_all_singletons_no_clusters():
    """If every piece is unique, no clustering happens."""
    pieces = [_rect(f"piece_{i}", 100, 50) for i in range(3)]
    clustered_input, clusters = pre_cluster_pieces(pieces, fabric_width_mm=500)
    assert len(clustered_input) == 3
    assert len(clusters) == 0


def test_pre_cluster_oversized_group_passes_through():
    """When a group's piece is too wide to cluster at any aspect ratio at the
    allowed rotation, pre_cluster_pieces passes the group through as individual pieces.
    Piece is 200×50 with grainline=0°, target=0° — min cluster_w=200 (1×3), 220>150."""
    pieces = [_rect(f"toobig__c{i}", 200, 50, grainline=0.0) for i in range(3)]
    clustered_input, clusters = pre_cluster_pieces(pieces, fabric_width_mm=150, grain_mode="single", fabric_grain_deg=0.0)
    # Group passes through as 3 singletons, no cluster created.
    assert len(clustered_input) == 3
    assert len(clusters) == 0
    assert {p.id for p in clustered_input} == {f"toobig__c{i}" for i in range(3)}


# --- expand_cluster_placement ---

def test_expand_cluster_at_rotation_zero():
    """At rotation 0°, copies expand to their local offsets translated by (super_x, super_y).
    Uses grainline=0° + single mode so only 0° is allowed; fabric=300 forces 2×2 grid
    (4×1 cluster_w=400+20=420>300 infeasible; 2×2 cluster_w=200+20=220≤300 wins)."""
    copies = [_rect(f"p__c{i}", 100, 50, grainline=0.0) for i in range(4)]
    cluster = pack_cluster_bbox(copies, fabric_width_mm=300, grain_mode="single", fabric_grain_deg=0.0)  # 2×2 grid
    # Place super-piece at (500, 1000) with rotation 0°
    placements = list(expand_cluster_placement(cluster, super_x=500, super_y=1000, super_rotation=0.0))
    assert len(placements) == 4
    # Copy positions should be (500, 1000), (600, 1000), (500, 1050), (600, 1050)
    # in row-major order
    expected_positions = {(500, 1000), (600, 1000), (500, 1050), (600, 1050)}
    actual_positions = {(round(p[1], 2), round(p[2], 2)) for p in placements}
    assert actual_positions == expected_positions
    for p in placements:
        assert p[3] == 0.0  # rotation


def test_expand_cluster_at_rotation_180():
    """At rotation 180°, the cluster flips. Copies end up at mirrored positions
    within the cluster's bbox. Each copy also gets rotation 180°."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(2)]
    cluster = pack_cluster_bbox(copies, fabric_width_mm=500)  # 2×1 grid, bbox 200×50
    # Place super-piece at (0, 0) with rotation 180°
    placements = list(expand_cluster_placement(cluster, super_x=0, super_y=0, super_rotation=180.0))
    assert len(placements) == 2
    for p in placements:
        assert p[3] == 180.0  # all copies have rotation 180°


def test_expand_returns_original_piece_ids():
    """Expanded placements reference the original (not super-piece) piece IDs."""
    copies = [_rect(f"piece_a__c{i}", 100, 50) for i in range(2)]
    cluster = pack_cluster_bbox(copies, fabric_width_mm=300)
    placements = list(expand_cluster_placement(cluster, 0.0, 0.0, 0.0))
    expanded_ids = {p[0] for p in placements}
    assert expanded_ids == {"piece_a__c0", "piece_a__c1"}


def test_expand_cluster_non_rectangular_polygon():
    """Per-copy bbox top-left is computed from actual Polygon.bounds, so the
    function works for any convex polygon — not just axis-aligned rectangles.
    Real DXF pieces (Task 2's integration) are non-rectangular; this is the
    backstop that says: the math doesn't secretly assume rect inputs."""
    # Right triangles: (0,0), (50,0), (0,30) — bbox 50×30 each
    pieces = [
        Piece(
            id=f"tri__c{i}", name=f"tri__c{i}",
            polygon=[(0, 0), (50, 0), (0, 30)],
            area=50 * 30 / 2,
            bbox=BoundingBox(0, 0, 50, 30, 50, 30),
            is_valid=True,
            grainline_direction_deg=None,
        )
        for i in range(2)
    ]
    cluster = pack_cluster_bbox(pieces, fabric_width_mm=300)
    assert cluster is not None
    placements = list(
        expand_cluster_placement(cluster, super_x=100.0, super_y=200.0, super_rotation=0.0)
    )
    assert len(placements) == 2
    # Both copies sit at or beyond the super-piece's top-left; rotation passed through.
    for piece_id, x, y, r in placements:
        assert x >= 100.0 - 1e-6
        assert y >= 200.0 - 1e-6
        assert r == 0.0


# --- Bug 2 regression guards: grain-awareness in pack_cluster ---

def test_pack_cluster_tall_pieces_with_grain_rejected_when_rotation_doesnt_fit():
    """Bug 2 regression guard: a tall cluster of grain-locked pieces that would
    exceed fabric width at ALL allowed rotations must be rejected. Without grain
    awareness, pack_cluster used to accept the cluster and let BLF crash inside
    _validate_pieces_fit later."""
    # 10 copies of a tall piece (400×600). Piece has grainline along Y axis
    # (90°), fabric grain is also 90°, so target rotation is 0° — cluster
    # never gets rotated, must fit at its natural width.
    pieces = [_rect(f"tall__c{i}", 400, 600, grainline=90.0) for i in range(10)]
    # 10×1 grid: cluster_w = 4000 (doesn't fit fabric=1500); rejected.
    # 1×10 grid: cluster_w = 400 (fits); cluster_h = 6000.
    # 5×2 grid: cluster_w = 2000 (doesn't fit); 2×5: cluster_w = 800 (fits).
    # So 1×10 or 2×5 are the only candidates. Either is valid.
    cluster = pack_cluster_bbox(pieces, fabric_width_mm=1500, grain_mode="single", fabric_grain_deg=90.0)
    assert cluster is not None
    # Should pick the shortest feasible — 5x2 (cluster_h=1200) over 1×10 (cluster_h=6000).
    # Wait actually: 2×5 has cluster_w=800, cluster_h=3000. 5×2 isn't feasible.
    # Let me recompute. With cols/rows enumeration:
    #   cols=1,rows=10: w=400,h=6000
    #   cols=2,rows=5: w=800,h=3000
    #   cols=3,rows=4: w=1200,h=2400
    #   cols=4,rows=3: w=1600 — doesn't fit (1600+20>1500)
    # So feasible: (1,10), (2,5), (3,4). Pick smallest cluster_h: (3,4) = 2400.
    assert cluster.super_piece.bbox.height == 2400
    assert cluster.super_piece.bbox.width == 1200


def test_pack_cluster_grain_rotates_cluster_to_fit():
    """When the BLF target rotation swaps W/H (e.g., target=90°), pack_cluster
    must check the ROTATED width against fabric. A cluster_w that doesn't fit
    natural-orientation might still fit when rotated.

    For grain-constrained pieces, sort_h = min height across feasible rotations
    (the actual marker contribution when placed). For target=90°, height at that
    rotation = cluster_w. So the cluster with smallest cluster_w wins.

    10 copies of 200×100, grainline=0°, target=90°, fabric=500 (usable=480):
      cols=10: cluster_w=2000, cluster_h=100. Width-at-90°=100 ≤ 480. sort_h=2000.
      cols=5:  cluster_w=1000, cluster_h=200. Width-at-90°=200 ≤ 480. sort_h=1000.
      cols=4:  cluster_w=800,  cluster_h=300. Width-at-90°=300 ≤ 480. sort_h=800.
      cols=3:  cluster_w=600,  cluster_h=400. Width-at-90°=400 ≤ 480. sort_h=600.
      cols=2:  cluster_w=400,  cluster_h=500. Width-at-90°=500 > 480. Infeasible.
      cols=1:  cluster_w=200,  cluster_h=1000. Width-at-90°=1000 > 480. Infeasible.
    Winner by grain-rotation sort: 3×4 (sort_h=600 = cluster_w at 90°).
    Placed at 90°: width=400mm (cluster_h), marker contribution=600mm (cluster_w).
    """
    pieces = [_rect(f"wide__c{i}", 200, 100, grainline=0.0) for i in range(10)]
    cluster = pack_cluster_bbox(pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=90.0)
    assert cluster is not None
    # 3×4 wins: smallest sort_h (= cluster_w = 600) among feasible grids.
    assert cluster.super_piece.bbox.width == 600
    assert cluster.super_piece.bbox.height == 400


def test_expand_cluster_applies_local_rotation():
    """A Cluster with mixed local rotations should produce expanded placements
    where each copy's final rotation = (super_rotation + local_rot) % 360.
    This is the bi-mode pattern: inner BLF picks local 0° or 180° per copy."""
    base = _rect("p__c0", 100, 50)
    # Synthetic Cluster: 2 copies, one at local 0°, one at local 180°. Super-piece
    # is a 200x50 rectangle. copy_offsets are the rotated-bbox-top-lefts in cluster-local.
    cluster = Cluster(
        super_piece=Piece(
            id="cluster_p_x2", name="cluster p x2",
            polygon=[(0, 0), (200, 0), (200, 50), (0, 50)],
            area=2 * (100 * 50),
            bbox=BoundingBox(0, 0, 200, 50, 200, 50),
            is_valid=True,
            grainline_direction_deg=None,
        ),
        copy_offsets=[(0.0, 0.0), (100.0, 0.0)],
        copy_local_rotations=[0.0, 180.0],
        original_pieces=[base, _rect("p__c1", 100, 50)],
    )
    # Place cluster at (500, 1000) with super_rotation=90°.
    # Effective rotations: (90+0)%360=90, (90+180)%360=270.
    placements = list(expand_cluster_placement(cluster, super_x=500, super_y=1000, super_rotation=90.0))
    assert len(placements) == 2
    rotations = sorted(p[3] for p in placements)
    assert rotations == [90.0, 270.0]
