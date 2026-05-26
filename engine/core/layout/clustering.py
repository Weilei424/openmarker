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
from shapely.ops import unary_union

from core.models.piece import Piece, BoundingBox

# Must match heuristic.EDGE_GAP. Duplicated here to keep clustering.py
# importable without pulling in heuristic.py (which would create a cycle).
EDGE_GAP = 10.0

# Maximum exterior vertex count for a union cluster polygon. Beyond this we
# simplify; if still over cap, the union candidate is rejected and pre_cluster_pieces
# falls back to pack_cluster_bbox for that group.
VERTEX_CAP = 200

# Shapely.simplify tolerance (mm) applied when exterior vertex count > VERTEX_CAP.
# 0.5 mm matches engine's `_has_area_overlap` eps = 0.5 mm² (frontend SAT tolerance);
# vertices closer than this are below pixel render noise anyway.
SIMPLIFY_TOL_MM = 0.5


@dataclass
class Cluster:
    """A pre-packed group of identical pieces, ready to be placed as a super-piece.

    Attributes:
        super_piece: Synthetic Piece whose polygon represents the packed cluster
            (bbox rectangle for `pack_cluster_bbox`; union exterior for
            `pack_cluster_union`). Its `area` field is the SUM of original copy
            areas (so utilization math stays correct downstream).
        copy_offsets: For each copy, its (dx, dy) in cluster-local coords
            (top-left of the copy's rotated bbox in cluster-local frame).
        copy_local_rotations: For each copy, its local rotation in degrees within
            the cluster. Bbox path uses zeros (copies all at outer rotation).
            Union path may use {0, 180} (bi-mode) or {0, 90, 180, 270} (no-grain).
        original_pieces: Original Piece objects in the same order as
            copy_offsets/copy_local_rotations — used to look up id/polygon/area
            for expansion.
    """
    super_piece: Piece
    copy_offsets: list[tuple[float, float]]
    copy_local_rotations: list[float]
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


def pack_cluster_bbox(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str = "single",
    fabric_grain_deg: float = 0.0,
) -> Cluster | None:
    """Pack N copies of an identical piece into a bbox super-piece.

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

    return Cluster(
        super_piece=super_piece,
        copy_offsets=offsets,
        copy_local_rotations=[0.0] * n,  # bbox path uses uniform 0° local rotation
        original_pieces=pieces,
    )


def pack_cluster_union(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str = "single",
    fabric_grain_deg: float = 0.0,
) -> Cluster | None:
    """Pack N identical copies into a grid, union the placed polygons, and return
    a Cluster whose super_piece.polygon is the union exterior.

    Returns None when:
      - len(pieces) < 2 (no clustering benefit; pre_cluster_pieces passes through)
      - No grid layout yields a connected single-polygon union below VERTEX_CAP
        after simplification (pre_cluster_pieces will fall back to pack_cluster_bbox).

    Copy positions follow the same row-major grid as pack_cluster_bbox; copies
    touch exactly at shared edges so unary_union collapses them. Copy rotations
    use the cluster-local set (all 0° for single mode; 0°/180° for bi + grainline;
    all cardinals otherwise) — but in the grid arrangement all copies are at 0°.
    """
    if len(pieces) < 2:
        return None
    # Local import to avoid circular import at module load (heuristic imports clustering).
    from core.layout.heuristic import _placed_polygon

    n = len(pieces)
    base = pieces[0]
    piece_w = base.bbox.width
    piece_h = base.bbox.height

    # Cluster-local rotation set: derives from outer grain_mode and piece grainline.
    # Single mode → no rotation freedom inside cluster regardless of grainline.
    # Bi mode + grainline → flip only (0/180). Bi or no-mode + no grainline → all cardinals.
    base_grain = base.grainline_direction_deg
    if grain_mode == "single":
        copy_local_rot = 0.0
        cluster_local_rotations_set: list[float] = [0.0]
    elif grain_mode == "bi" and base_grain is not None:
        copy_local_rot = 0.0
        cluster_local_rotations_set = [0.0, 180.0]
    else:
        # bi-mode with no grainline, or grain_mode="none"
        copy_local_rot = 0.0
        cluster_local_rotations_set = [0.0, 90.0, 180.0, 270.0]

    # Outer rotations the cluster will be placed at (used for grain-rotation
    # feasibility filter on candidate widths). Mirrors PR #9's bug-2 logic.
    if base_grain is None:
        outer_rotations: list[float] = [0.0, 90.0, 180.0, 270.0]
    else:
        target = (fabric_grain_deg - base_grain) % 360
        if grain_mode == "bi":
            outer_rotations = [target, (target + 180.0) % 360.0]
        else:
            outer_rotations = [target]

    def _width_at_rotation(w: float, h: float, deg: float) -> float:
        r = deg % 180.0
        if r < 1e-6 or abs(r - 180.0) < 1e-6:
            return w
        if abs(r - 90.0) < 1e-6:
            return h
        return max(w, h)  # conservative for non-cardinal

    def _height_at_rotation(w: float, h: float, deg: float) -> float:
        r = deg % 180.0
        if r < 1e-6 or abs(r - 180.0) < 1e-6:
            return h
        if abs(r - 90.0) < 1e-6:
            return w
        return max(w, h)

    usable_width = fabric_width_mm - 2 * EDGE_GAP
    best_candidate: tuple[float, float, float, float, Cluster] | None = None  # (sort_h, sort_w, cluster_h, cluster_w, cluster)

    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        grid_w = cols * piece_w
        grid_h = rows * piece_h

        # Grain-rotation feasibility: at least one outer rotation must keep the
        # rotated grid width within usable_width. Same logic as pack_cluster_bbox.
        feasible_outer_rots = [
            r for r in outer_rotations
            if _width_at_rotation(grid_w, grid_h, r) <= usable_width
        ]
        if not feasible_outer_rots:
            continue

        # Build row-major grid offsets (copies touch at shared edges).
        grid_offsets: list[tuple[float, float]] = []
        for row in range(rows):
            for col in range(cols):
                if len(grid_offsets) >= n:
                    break
                grid_offsets.append((col * piece_w, row * piece_h))
            if len(grid_offsets) >= n:
                break

        # Compute union of pieces placed at grid positions (all at 0° rotation).
        placed_polys = [
            _placed_polygon(base, dx, dy, copy_local_rot)
            for dx, dy in grid_offsets
        ]
        union = unary_union(placed_polys)
        if union.geom_type == "MultiPolygon":
            continue
        if union.geom_type != "Polygon":
            continue  # GeometryCollection / LineString — degenerate

        # Strip holes (interior rings unreachable by outer BLF).
        union = ShapelyPolygon(union.exterior)

        # Remove collinear points left by unary_union at shared edges.
        # simplify(0) removes co-linear vertices without distorting the polygon.
        decollinear = union.simplify(0)
        if decollinear.geom_type == "Polygon" and not decollinear.is_empty:
            union = ShapelyPolygon(decollinear.exterior)

        # Simplify if over vertex cap.
        exterior_coords = list(union.exterior.coords)
        if len(exterior_coords) - 1 > VERTEX_CAP:  # -1 for closing duplicate
            simplified = union.simplify(SIMPLIFY_TOL_MM, preserve_topology=True)
            if simplified.geom_type != "Polygon":
                continue
            simplified = ShapelyPolygon(simplified.exterior)
            exterior_coords = list(simplified.exterior.coords)
            if len(exterior_coords) - 1 > VERTEX_CAP:
                continue  # still too complex; skip this candidate
            union = simplified

        # Drop closing duplicate; Piece.polygon convention is no closing vertex.
        polygon_coords = [(round(x, 4), round(y, 4)) for x, y in exterior_coords[:-1]]

        # Cluster bbox from union bounds.
        minx, miny, maxx, maxy = union.bounds
        cluster_w = maxx - minx
        cluster_h = maxy - miny

        # Sort key (mirror pack_cluster_bbox): minimize marker-length contribution
        # at the cluster's best feasible outer rotation.
        sort_h = min(
            _height_at_rotation(cluster_w, cluster_h, r) for r in feasible_outer_rots
        )
        sort_w = min(
            _width_at_rotation(cluster_w, cluster_h, r) for r in feasible_outer_rots
        )

        super_piece = Piece(
            id=f"cluster_{_base_id(base.id)}_x{n}",
            name=f"cluster {base.name} x{n}",
            polygon=polygon_coords,
            area=sum(p.area for p in pieces),
            bbox=BoundingBox(0.0, 0.0, cluster_w, cluster_h, cluster_w, cluster_h),
            is_valid=True,
            validation_notes=[],
            grainline_direction_deg=base.grainline_direction_deg,
        )

        cluster = Cluster(
            super_piece=super_piece,
            copy_offsets=grid_offsets,
            copy_local_rotations=[copy_local_rot] * n,
            original_pieces=pieces,
        )

        candidate_key = (sort_h, sort_w, cluster_h, cluster_w)
        if best_candidate is None or candidate_key < (best_candidate[0], best_candidate[1], best_candidate[2], best_candidate[3]):
            best_candidate = (sort_h, sort_w, cluster_h, cluster_w, cluster)

    if best_candidate is None:
        return None
    return best_candidate[4]


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
        cluster = pack_cluster_bbox(group, fabric_width_mm, grain_mode, fabric_grain_deg)
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

    Reproduces the engine's `_placed_polygon` convention: the cluster polygon is
    rotated around (0, 0) by `super_rotation`, then translated so the rotated
    cluster's bbox top-left lands at (super_x, super_y). For each copy:
      1. Reconstruct the copy in cluster-local frame by rotating its polygon by
         `local_rot` around (0, 0), then translating so the rotated copy bbox
         top-left lands at `copy_offsets[i]`.
      2. Apply `super_rotation` around (0, 0) and the cluster-level translation.
      3. Per-copy final rotation = (super_rotation + local_rot) % 360.
    """
    cluster_poly = ShapelyPolygon(cluster.super_piece.polygon)
    rotated_cluster = shapely.affinity.rotate(
        cluster_poly, super_rotation, origin=(0.0, 0.0), use_radians=False
    )
    cluster_min_x, cluster_min_y = rotated_cluster.bounds[0], rotated_cluster.bounds[1]
    xoff = super_x - cluster_min_x
    yoff = super_y - cluster_min_y

    for orig_piece, (dx, dy), local_rot in zip(
        cluster.original_pieces,
        cluster.copy_offsets,
        cluster.copy_local_rotations,
    ):
        copy_poly = ShapelyPolygon(orig_piece.polygon)
        rotated_local = shapely.affinity.rotate(
            copy_poly, local_rot, origin=(0.0, 0.0), use_radians=False
        )
        rot_minx, rot_miny = rotated_local.bounds[0], rotated_local.bounds[1]
        copy_in_cluster = shapely.affinity.translate(
            rotated_local, xoff=dx - rot_minx, yoff=dy - rot_miny
        )
        rotated_with_super = shapely.affinity.rotate(
            copy_in_cluster, super_rotation, origin=(0.0, 0.0), use_radians=False
        )
        placed_copy = shapely.affinity.translate(rotated_with_super, xoff=xoff, yoff=yoff)
        cx, cy = placed_copy.bounds[0], placed_copy.bounds[1]
        effective_rot = (super_rotation + local_rot) % 360.0
        yield (orig_piece.id, round(cx, 4), round(cy, 4), effective_rot)
