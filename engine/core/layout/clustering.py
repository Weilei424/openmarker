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


def pack_cluster(pieces: list[Piece], fabric_width_mm: float) -> Cluster | None:
    """Pack N copies of an identical piece into a compact super-piece.

    Returns None when:
      - N < 2 (single copy: no clustering benefit)
      - No aspect ratio fits within fabric_width_mm - 2*EDGE_GAP

    Among feasible aspect ratios (cols, rows) with cols*rows >= N, picks the
    one with smallest (dead_slots, cluster_area).
    """
    if len(pieces) < 2:
        return None
    n = len(pieces)
    base = pieces[0]
    piece_w = base.bbox.width
    piece_h = base.bbox.height

    candidates: list[tuple[int, int, int, float, float]] = []
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        cluster_w = cols * piece_w
        cluster_h = rows * piece_h
        if cluster_w + 2 * EDGE_GAP > fabric_width_mm:
            continue
        dead = cols * rows - n
        candidates.append((dead, cols, rows, cluster_w, cluster_h))
    if not candidates:
        return None

    # Sort by: fewest dead slots, then smallest cluster height (minimises marker
    # length), then smallest area (equivalent when pieces are uniform, but kept
    # for safety).
    candidates.sort(key=lambda c: (c[0], c[4], c[3] * c[4]))
    _, cols, rows, cluster_w, cluster_h = candidates[0]

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
    pieces: list[Piece], fabric_width_mm: float
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
        cluster = pack_cluster(group, fabric_width_mm)
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
