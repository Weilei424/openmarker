import pytest
from core.models.piece import Piece, BoundingBox
from core.layout.clustering import (
    Cluster,
    group_pieces_by_base_id,
    pack_cluster,
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
    assert pack_cluster([_rect("p__c0", 100, 50)], fabric_width_mm=300) is None


def test_pack_cluster_perfect_grid():
    """4 copies of 100×50 in fabric=300 → 2×2 grid is feasible (200 + 2*EDGE_GAP=20 ≤ 300)
    and is more compact than 1×4 (50 + 20 ≤ 300, height 200) or 4×1 (400 + 20 > 300, infeasible).
    Of feasible aspect ratios, 2×2 wins via the cluster-height tiebreaker:
    1×4 area = 2×2 area = 20000, but cluster_h=100 < 200, so 2×2 is preferred."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    cluster = pack_cluster(copies, fabric_width_mm=300)
    assert cluster is not None
    assert cluster.super_piece.bbox.width == 200
    assert cluster.super_piece.bbox.height == 100
    assert len(cluster.copy_offsets) == 4
    # Area is sum of original piece areas (NOT bbox area)
    assert cluster.super_piece.area == 4 * (100 * 50)


def test_pack_cluster_narrow_fabric_forces_single_column():
    """4 copies of 100×50 in fabric=150 → only 1 column fits (100 + 20 ≤ 150)."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    cluster = pack_cluster(copies, fabric_width_mm=150)
    assert cluster is not None
    assert cluster.super_piece.bbox.width == 100
    assert cluster.super_piece.bbox.height == 200


def test_pack_cluster_too_big_returns_none():
    """A copy wider than fabric (minus selvedge) → no aspect ratio fits → None."""
    copies = [_rect(f"p__c{i}", 200, 50) for i in range(4)]
    cluster = pack_cluster(copies, fabric_width_mm=150)
    assert cluster is None


def test_pack_cluster_preserves_grainline():
    """The super-piece inherits the original pieces' grainline (they're identical)."""
    copies = [_rect(f"p__c{i}", 100, 50, grainline=90.0) for i in range(4)]
    cluster = pack_cluster(copies, fabric_width_mm=300)
    assert cluster is not None
    assert cluster.super_piece.grainline_direction_deg == 90.0


def test_pack_cluster_prime_count_picks_strip():
    """7 copies of 100×50: aspect ratios (1,7) and (7,1) have no dead space; both have area 7*100*50.
    (2,4)=8 slots wastes 1 slot. Prefer (1,7) or (7,1)."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(7)]
    cluster = pack_cluster(copies, fabric_width_mm=1000)
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
    """When a group's piece is too wide to cluster at any aspect ratio,
    pre_cluster_pieces passes the group through as individual pieces."""
    pieces = [_rect(f"toobig__c{i}", 200, 50) for i in range(3)]
    clustered_input, clusters = pre_cluster_pieces(pieces, fabric_width_mm=150)
    # Group passes through as 3 singletons, no cluster created.
    assert len(clustered_input) == 3
    assert len(clusters) == 0
    assert {p.id for p in clustered_input} == {f"toobig__c{i}" for i in range(3)}


# --- expand_cluster_placement ---

def test_expand_cluster_at_rotation_zero():
    """At rotation 0°, copies expand to their local offsets translated by (super_x, super_y)."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    cluster = pack_cluster(copies, fabric_width_mm=300)  # 2×2 grid
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
    cluster = pack_cluster(copies, fabric_width_mm=500)  # 2×1 grid, bbox 200×50
    # Place super-piece at (0, 0) with rotation 180°
    placements = list(expand_cluster_placement(cluster, super_x=0, super_y=0, super_rotation=180.0))
    assert len(placements) == 2
    for p in placements:
        assert p[3] == 180.0  # all copies have rotation 180°


def test_expand_returns_original_piece_ids():
    """Expanded placements reference the original (not super-piece) piece IDs."""
    copies = [_rect(f"piece_a__c{i}", 100, 50) for i in range(2)]
    cluster = pack_cluster(copies, fabric_width_mm=300)
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
    cluster = pack_cluster(pieces, fabric_width_mm=300)
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
