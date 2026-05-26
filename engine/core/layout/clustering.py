"""Identical-piece pre-clustering for BLF.

Groups copies of the same base piece into a rigid super-piece (bbox of the
packed grid), so the outer BLF places N×M copies as one unit instead of
searching for each individually. After BLF, expand_cluster_placement maps each
super-piece placement back to per-copy placements.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterator

import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon

from core.models.piece import Piece, BoundingBox

# Must match heuristic.EDGE_GAP. Duplicated here to keep clustering.py
# importable without pulling in heuristic.py (which would create a cycle).
EDGE_GAP = 10.0


@dataclass
class Cluster:
    """A pre-packed group of identical pieces, ready to be placed as a super-piece.

    Attributes:
        super_piece: Synthetic Piece whose polygon is the bbox of the packed
            grid. Its `area` field is the SUM of original copy areas (so
            utilization math stays correct downstream).
        copy_offsets: For each copy, its (dx, dy) in cluster-local coords
            (origin = cluster's bbox top-left, axis-aligned, no rotation).
        original_pieces: Original Piece objects in the same order as
            copy_offsets — used to look up id/polygon/area for expansion.
    """
    super_piece: Piece
    copy_offsets: list[tuple[float, float]]
    original_pieces: list[Piece]


def _base_id(piece_id: str) -> str:
    """Strip the frontend's `__c{n}` copy suffix.

    Two pieces sharing a base id have identical polygons. Mirrors the same
    helper in heuristic.py — duplicated to avoid a circular import.
    """
    idx = piece_id.find("__c")
    return piece_id if idx < 0 else piece_id[:idx]


def group_pieces_by_base_id(pieces: list[Piece]) -> dict[str, list[Piece]]:
    """Group pieces by their base id (suffix stripped). Returns insertion-
    ordered mapping so downstream iteration is deterministic."""
    groups: dict[str, list[Piece]] = OrderedDict()
    for piece in pieces:
        base = _base_id(piece.id)
        groups.setdefault(base, []).append(piece)
    return groups


def pack_cluster(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str = "single",
    fabric_grain_deg: float = 0.0,
) -> Cluster | None:
    """Pack N copies of an identical piece into a compact super-piece.

    Returns None when:
      - N < 2 (single copy: no clustering benefit)
      - No aspect ratio fits within fabric_width_mm - 2*EDGE_GAP at any
        BLF-allowed rotation

    Among feasible aspect ratios (cols, rows) with cols*rows >= N, picks the
    one with smallest (cluster_h, cluster_w) — minimises marker-length
    contribution first, then horizontal blockage. Dead slots are intentionally
    NOT in the sort key: a taller dead-slot-free cluster contributes more to
    marker length than a shorter cluster with a few dead slots.
    """
    if len(pieces) < 2:
        return None
    n = len(pieces)
    base = pieces[0]
    piece_w = base.bbox.width
    piece_h = base.bbox.height

    # Compute allowed rotations for the cluster (matches BLF's _layout_rotations).
    base_grain = base.grainline_direction_deg
    if base_grain is None:
        rotations: list[float] = [0.0, 90.0, 180.0, 270.0]
    else:
        target = (fabric_grain_deg - base_grain) % 360
        if grain_mode == "bi":
            rotations = [target, (target + 180.0) % 360.0]
        else:
            rotations = [target]

    def _width_at_rotation(w: float, h: float, deg: float) -> float:
        """Return cluster width when rotated by `deg`. Exact for cardinal angles;
        falls back to max(w, h) for non-cardinal (conservative — over-rejects
        rather than allowing infeasible clusters)."""
        r = deg % 180.0
        if r < 1e-6 or abs(r - 180.0) < 1e-6:
            return w
        if abs(r - 90.0) < 1e-6:
            return h
        return max(w, h)

    def _height_at_rotation(w: float, h: float, deg: float) -> float:
        """Return cluster height (marker-length contribution) when rotated."""
        r = deg % 180.0
        if r < 1e-6 or abs(r - 180.0) < 1e-6:
            return h
        if abs(r - 90.0) < 1e-6:
            return w
        return max(w, h)

    candidates: list[tuple[float, float, int, int]] = []
    usable_width = fabric_width_mm - 2 * EDGE_GAP
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        cluster_w = cols * piece_w
        cluster_h = rows * piece_h
        if base_grain is None:
            # No grainline: BLF can freely choose any cardinal rotation. Use the
            # natural-orientation feasibility check (cluster_w fits at 0°) to
            # prevent selecting wide clusters that only fit when rotated 90° —
            # those would be very tall in the marker-length direction and regress.
            # The natural-orientation sort key (cluster_h, cluster_w) is then
            # the marker contribution at 0° (the most likely placed orientation).
            if cluster_w > usable_width:
                continue
            sort_h = cluster_h
            sort_w = cluster_w
        else:
            # Grain-constrained: BLF must place the cluster at one of the
            # allowed grain rotations. Check that AT LEAST ONE makes the cluster
            # narrow enough — mirrors BLF's `_validate_pieces_fit` (min_w across
            # rotations ≤ usable). This is the Bug 2 fix: the old check
            # (cluster_w at 0°) allowed clusters that later crashed
            # `_validate_pieces_fit` when the grain rotation required
            # cluster_h > fabric_width.
            feasible_rots = [
                r for r in rotations
                if _width_at_rotation(cluster_w, cluster_h, r) <= usable_width
            ]
            if not feasible_rots:
                continue
            # Sort key: minimum marker-length contribution across feasible
            # rotations. For a grain-constrained piece (fixed target) this is
            # the height at that rotation, which can differ from cluster_h when
            # the target is 90°/270° (W and H swap). Using the actual height at
            # the feasible rotation prevents selecting a cluster that appears
            # short in natural orientation but is very tall when grain-rotated.
            sort_h = min(_height_at_rotation(cluster_w, cluster_h, r) for r in feasible_rots)
            sort_w = min(_width_at_rotation(cluster_w, cluster_h, r) for r in feasible_rots)
        candidates.append((sort_h, sort_w, cluster_h, cluster_w, cols, rows))
    if not candidates:
        return None

    # Sort: minimize sort_h (marker-length contribution at the best feasible
    # rotation) primary, sort_w (horizontal blockage) secondary.
    # cluster_h and cluster_w are appended as determinism tiebreakers.
    # Dead slots are intentionally NOT in the key — a taller dead-slot-free
    # cluster contributes more to marker length than a shorter cluster with a
    # few dead slots. (Bug 1 fix: old key was (dead, cluster_h, area).)
    candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    _sh, _sw, cluster_h, cluster_w, cols, rows = candidates[0]

    offsets: list[tuple[float, float]] = []
    for row in range(rows):
        for col in range(cols):
            if len(offsets) >= n:
                break
            offsets.append((col * piece_w, row * piece_h))
        if len(offsets) >= n:
            break

    super_piece = Piece(
        id=f"cluster_{_base_id(base.id)}_x{n}",
        name=f"cluster {base.name} x{n}",
        polygon=[(0.0, 0.0), (cluster_w, 0.0), (cluster_w, cluster_h), (0.0, cluster_h)],
        area=sum(p.area for p in pieces),
        bbox=BoundingBox(0.0, 0.0, cluster_w, cluster_h, cluster_w, cluster_h),
        is_valid=True,
        validation_notes=[],
        grainline_direction_deg=base.grainline_direction_deg,
    )

    return Cluster(super_piece=super_piece, copy_offsets=offsets, original_pieces=pieces)


def pre_cluster_pieces(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str = "single",
    fabric_grain_deg: float = 0.0,
) -> tuple[list[Piece], list[Cluster]]:
    """Group identical pieces and pack each group into a super-piece cluster.

    Returns (clustered_input, clusters):
      - clustered_input: list[Piece] containing singletons + super-pieces, to
        be passed to the existing BLF unchanged.
      - clusters: list[Cluster], one per super-piece — used to expand
        placements back to per-copy after BLF returns.
    """
    groups = group_pieces_by_base_id(pieces)
    clustered_input: list[Piece] = []
    clusters: list[Cluster] = []
    for group in groups.values():
        if len(group) < 2:
            clustered_input.extend(group)
            continue
        cluster = pack_cluster(group, fabric_width_mm, grain_mode, fabric_grain_deg)
        if cluster is None:
            # Couldn't cluster (group's piece too wide for fabric); pass through.
            clustered_input.extend(group)
            continue
        clustered_input.append(cluster.super_piece)
        clusters.append(cluster)
    return clustered_input, clusters


def expand_cluster_placement(
    cluster: Cluster,
    super_x: float,
    super_y: float,
    super_rotation: float,
) -> Iterator[tuple[str, float, float, float]]:
    """Yield (piece_id, x, y, rotation) for each copy in a placed cluster.

    Reproduces the engine's `_placed_polygon` convention: the cluster polygon
    is rotated by `super_rotation` around the origin (0, 0), then translated
    so the rotated cluster's bbox top-left lands at (super_x, super_y). The
    same affine transformation is applied to each copy's polygon (already at
    its local offset); the resulting per-copy bbox top-left becomes the copy's
    Placement.x/y. Per-copy rotation = super_rotation (cluster is rigid).
    """
    cluster_w = cluster.super_piece.bbox.width
    cluster_h = cluster.super_piece.bbox.height
    cluster_poly = ShapelyPolygon(
        [(0.0, 0.0), (cluster_w, 0.0), (cluster_w, cluster_h), (0.0, cluster_h)]
    )
    rotated_cluster = shapely.affinity.rotate(
        cluster_poly, super_rotation, origin=(0.0, 0.0), use_radians=False
    )
    cluster_min_x, cluster_min_y = rotated_cluster.bounds[0], rotated_cluster.bounds[1]
    xoff = super_x - cluster_min_x
    yoff = super_y - cluster_min_y

    for orig_piece, (dx, dy) in zip(cluster.original_pieces, cluster.copy_offsets):
        copy_poly = ShapelyPolygon(orig_piece.polygon)
        copy_poly_in_cluster = shapely.affinity.translate(copy_poly, xoff=dx, yoff=dy)
        rotated_copy = shapely.affinity.rotate(
            copy_poly_in_cluster, super_rotation, origin=(0.0, 0.0), use_radians=False
        )
        placed_copy = shapely.affinity.translate(rotated_copy, xoff=xoff, yoff=yoff)
        cx, cy = placed_copy.bounds[0], placed_copy.bounds[1]
        yield (orig_piece.id, round(cx, 4), round(cy, 4), super_rotation)
