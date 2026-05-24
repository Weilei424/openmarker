from __future__ import annotations

from dataclasses import dataclass

import pyclipper
import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon, box as shapely_box
from shapely.ops import unary_union

from core.layout.cancellation import CancellationError, is_cancelled
from core.models.piece import Piece

# Integer scale for pyclipper. Preserves 3 decimal places of mm precision;
# polygons up to ~2 km square stay within int32 range.
_NFP_SCALE = 1000

# mm — selvedge buffer between piece bbox and fabric edge.
# Pieces may touch each other directly (no inter-piece gap) but stay this far from edges.
EDGE_GAP = 10.0
# Kept as alias for any external callers that previously imported GAP.
GAP = EDGE_GAP


@dataclass
class Placement:
    piece_id: str
    x: float
    y: float
    rotation_deg: float


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _placed_polygon(piece: Piece, x: float, y: float, rotation_deg: float) -> ShapelyPolygon:
    """Return the piece polygon rotated CW by rotation_deg (screen) and translated to (x, y).

    Our piece coords are screen (y down). Shapely is +angle = CCW in math.
    Because flipping y inverts the rotation direction, Shapely +angle = CW in screen.
    """
    poly = ShapelyPolygon(piece.polygon)
    rotated = shapely.affinity.rotate(poly, rotation_deg, origin=(0, 0), use_radians=False)
    minx, miny = rotated.bounds[0], rotated.bounds[1]
    return shapely.affinity.translate(rotated, xoff=-minx + x, yoff=-miny + y)


def _polygon_dims(piece: Piece, rotation_deg: float) -> tuple[float, float]:
    """Return (width, height) from actual rotated polygon bounds."""
    poly = ShapelyPolygon(piece.polygon)
    rotated = shapely.affinity.rotate(poly, rotation_deg, origin=(0, 0), use_radians=False)
    minx, miny, maxx, maxy = rotated.bounds
    return maxx - minx, maxy - miny


def _has_area_overlap(a: ShapelyPolygon, b: ShapelyPolygon, eps: float = 0.5) -> bool:
    """Return True only if polygons overlap with positive area > eps mm².

    eps is intentionally generous (0.5 mm²) — it matches the frontend's
    SAT_OVERLAP_TOLERANCE_MM so what the engine accepts as "touching" the
    frontend also renders without a red collision highlight. Slivers below
    0.5 mm² come from NFP polygon rounding and Konva render float noise,
    not real piece overlap.
    """
    if not a.intersects(b):
        return False
    return a.intersection(b).area > eps


def _layout_rotations(
    grain_mode: str,
    fabric_grain_deg: float,
    piece_grainline_deg: float | None,
) -> list[float]:
    """Discrete rotation set for layout search.

    Pieces with no grainline data: fall back to cardinal angles (production
    markers only use cardinal rotations; 360 candidates wastes search).
    """
    if piece_grainline_deg is None:
        return [0.0, 90.0, 180.0, 270.0]
    target = (fabric_grain_deg - piece_grainline_deg) % 360
    if grain_mode == "single":
        return [target]
    if grain_mode == "bi":
        return [target, (target + 180) % 360]
    raise ValueError(f"Unknown grain_mode: {grain_mode!r}")


def _compute_metrics(
    placements: list[Placement],
    pieces: list[Piece],
    fabric_width_mm: float,
    dim_fn,
) -> tuple[float, float]:
    """Return (marker_length_mm, utilization_pct).

    Marker length = lowest Y bottom edge across all placements + edge gap.
    Y is the "length" direction we minimize (X is fabric width, fixed).
    """
    if not placements:
        return 0.0, 0.0
    piece_map = {p.id: p for p in pieces}
    marker_length = max(
        pl.y + dim_fn(piece_map[pl.piece_id], pl.rotation_deg)[1]
        for pl in placements
    ) + EDGE_GAP
    total_area = sum(p.area for p in pieces)
    utilization = round(total_area / (marker_length * fabric_width_mm) * 100, 2)
    return round(marker_length, 2), utilization


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------

def _validate_pieces_fit(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    dim_fn,
) -> None:
    for piece in pieces:
        rotations = _layout_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg)
        min_w = min(dim_fn(piece, r)[0] for r in rotations)
        if min_w + 2 * EDGE_GAP > fabric_width_mm:
            raise ValueError(
                f"Piece '{piece.name}' minimum width {min_w:.1f} mm cannot fit within "
                f"usable fabric width {fabric_width_mm - 2 * EDGE_GAP:.1f} mm at any allowed rotation."
            )


# ---------------------------------------------------------------------------
# Bottom-Left-Fill (polygon mode) — gap-aware packing
# ---------------------------------------------------------------------------

def _blf_pack(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    sort_key=None,
) -> tuple[list[Placement], float, float]:
    """Bottom-Left-Fill placement using polygon collision detection.

    For each piece (largest first by sort_key), pick the (x, y) position with
    the smallest y (then smallest x) where the rotated polygon does not
    positive-area-overlap any placed piece and stays within the fabric width.

    Candidate (x, y) values are derived from placed pieces' right/bottom edges
    so a new piece can nestle into gaps above shorter neighbors — the failure
    mode of pure shelf-packing.

    Touching boundaries does NOT count as collision (per cutting-room rule).
    Reference: Burke et al., "A new bottom-left-fill heuristic algorithm for
    the two-dimensional irregular packing problem" (Op. Research, 2006).
    """
    if sort_key is None:
        sort_key = lambda p: p.area
    sorted_pieces = sorted(pieces, key=sort_key, reverse=True)
    _validate_pieces_fit(sorted_pieces, fabric_width_mm, grain_mode, fabric_grain_deg, _polygon_dims)

    placements: list[Placement] = []
    placed_polys: list[ShapelyPolygon] = []

    for piece in sorted_pieces:
        if is_cancelled():
            raise CancellationError("Auto-layout cancelled by user.")
        rotations = _layout_rotations(
            grain_mode, fabric_grain_deg, piece.grainline_direction_deg
        )
        best: tuple[float, float, float, ShapelyPolygon] | None = None

        for rot in rotations:
            # Candidate positions: fabric top-left + every placed piece's right/bottom edge.
            # No inter-piece gap — pieces may touch.
            candidate_xs = {EDGE_GAP}
            candidate_ys = {EDGE_GAP}
            for pp in placed_polys:
                candidate_xs.add(pp.bounds[2])
                candidate_ys.add(pp.bounds[3])

            for y in sorted(candidate_ys):
                # Pruning: any candidate with y > best.y cannot improve.
                if best is not None and y > best[0]:
                    break

                for x in sorted(candidate_xs):
                    # Pruning: same y, x >= best.x cannot improve.
                    if best is not None and y == best[0] and x >= best[1]:
                        break

                    candidate = _placed_polygon(piece, x, y, rot)

                    if candidate.bounds[2] > fabric_width_mm - EDGE_GAP:
                        continue
                    if any(_has_area_overlap(candidate, pp) for pp in placed_polys):
                        continue

                    best = (y, x, rot, candidate)
                    # x is sorted ascending; no smaller-x position remains at this y.
                    break

        if best is None:
            raise ValueError(
                f"Cannot place piece '{piece.name}' — no valid BLF position found "
                f"(should be impossible after _validate_pieces_fit)."
            )

        y, x, rot, candidate = best
        placements.append(Placement(piece.id, round(x, 4), round(y, 4), rot))
        placed_polys.append(candidate)

    marker_length, utilization = _compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims)
    return placements, marker_length, utilization


# ---------------------------------------------------------------------------
# No-Fit Polygon (NFP) helpers — exact touching positions via pyclipper
# ---------------------------------------------------------------------------

def _polygon_at_origin(piece: Piece, rotation_deg: float) -> list[tuple[float, float]]:
    """Return the piece polygon rotated CW (screen) around (0, 0).

    Coordinates are NOT translated — they may include negative values.
    The closing duplicate vertex is stripped.
    """
    poly = ShapelyPolygon(piece.polygon)
    rotated = shapely.affinity.rotate(poly, rotation_deg, origin=(0, 0), use_radians=False)
    coords = list(rotated.exterior.coords)
    if coords and coords[0] == coords[-1]:
        coords = coords[:-1]
    return coords


def _compute_nfp_polygons(
    stationary_coords: list[tuple[float, float]],
    orbiting_coords: list[tuple[float, float]],
) -> list[ShapelyPolygon]:
    """Compute the NFP(stationary, orbiting) as Shapely polygons.

    NFP(A, B) = {(x, y) : placing B's reference point (origin) at (x, y)
                makes B and A overlap (or just touch on the boundary)}.

    Implemented as the Minkowski sum of A and B reflected through the origin
    (Burke 2006). pyclipper computes the Minkowski sum on integer-scaled
    coordinates; we convert back to floats afterward.
    """
    if not stationary_coords or not orbiting_coords:
        return []

    stationary_int = [
        (int(round(x * _NFP_SCALE)), int(round(y * _NFP_SCALE)))
        for x, y in stationary_coords
    ]
    neg_orbiting_int = [
        (-int(round(x * _NFP_SCALE)), -int(round(y * _NFP_SCALE)))
        for x, y in orbiting_coords
    ]

    try:
        nfp_paths = pyclipper.MinkowskiSum(stationary_int, neg_orbiting_int, True)
    except pyclipper.ClipperException:
        return []

    result: list[ShapelyPolygon] = []
    for path in nfp_paths or []:
        if len(path) < 3:
            continue
        coords = [(v[0] / _NFP_SCALE, v[1] / _NFP_SCALE) for v in path]
        try:
            poly = ShapelyPolygon(coords)
            if poly.is_valid and not poly.is_empty:
                result.append(poly)
        except Exception:
            continue
    return result


def _sorted_vertices(region) -> list[tuple[float, float]]:
    """Return all boundary vertices of a polygon region sorted by (y, x).

    Works on Polygon or MultiPolygon. Returns [] for other geometry types
    (LineString, GeometryCollection) — those indicate a degenerate valid region.
    """
    if region.is_empty:
        return []
    if region.geom_type == "Polygon":
        polys = [region]
    elif region.geom_type == "MultiPolygon":
        polys = list(region.geoms)
    else:
        return []

    seen: set[tuple[float, float]] = set()
    verts: list[tuple[float, float]] = []
    for poly in polys:
        for vx, vy in poly.exterior.coords:
            key = (round(vx, 4), round(vy, 4))
            if key not in seen:
                seen.add(key)
                verts.append((vx, vy))
        for interior in poly.interiors:
            for vx, vy in interior.coords:
                key = (round(vx, 4), round(vy, 4))
                if key not in seen:
                    seen.add(key)
                    verts.append((vx, vy))

    verts.sort(key=lambda p: (p[1], p[0]))
    return verts


def _blf_pack_nfp(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    sort_key=None,
) -> tuple[list[Placement], float, float]:
    """Bottom-Left-Fill using polygon set algebra over NFPs.

    For each piece + rotation, build:
      - IFP (Inner-Fit Polygon): the rectangle of valid reference-point
        positions that keep the rotated piece inside the usable fabric width
        and below the top selvedge.
      - NFP union: positions where the rotated piece would overlap any
        placed piece.
    Valid placements = IFP \\ NFP_union. Pick the lowest-then-leftmost vertex
    of that region as the reference-point position, then translate to bbox
    top-left and record the placement. This naturally finds positions on NFP
    edges (e.g., two squares packed side-by-side on the same shelf), not
    just NFP corner vertices.

    Touching is allowed — Shapely's difference produces the open valid region;
    its boundary vertices are exactly the touching positions.
    """
    if sort_key is None:
        sort_key = lambda p: p.area
    sorted_pieces = sorted(pieces, key=sort_key, reverse=True)
    _validate_pieces_fit(sorted_pieces, fabric_width_mm, grain_mode, fabric_grain_deg, _polygon_dims)

    # Finite IFP height: piece heights stacked tallest-on-tallest as a hard upper bound.
    max_y_search = sum(max(p.bbox.width, p.bbox.height) for p in pieces) + EDGE_GAP

    placements: list[Placement] = []
    placed_polys: list[ShapelyPolygon] = []

    for piece in sorted_pieces:
        if is_cancelled():
            raise CancellationError("Auto-layout cancelled by user.")
        rotations = _layout_rotations(
            grain_mode, fabric_grain_deg, piece.grainline_direction_deg
        )
        best: tuple[float, float, float, ShapelyPolygon] | None = None

        for rot in rotations:
            new_coords = _polygon_at_origin(piece, rot)
            new_poly_origin = ShapelyPolygon(new_coords)
            if not new_poly_origin.is_valid or new_poly_origin.is_empty:
                continue
            minx, miny, maxx, maxy = new_poly_origin.bounds

            nfx_min = EDGE_GAP - minx
            nfx_max = fabric_width_mm - EDGE_GAP - maxx
            nfy_min = EDGE_GAP - miny
            nfy_max = nfy_min + max_y_search

            if nfx_min > nfx_max:
                continue

            ifp = shapely_box(nfx_min, nfy_min, nfx_max, nfy_max)

            nfp_polys: list[ShapelyPolygon] = []
            for placed_poly in placed_polys:
                placed_coords = list(placed_poly.exterior.coords)
                if placed_coords and placed_coords[0] == placed_coords[-1]:
                    placed_coords = placed_coords[:-1]
                nfp_polys.extend(_compute_nfp_polygons(placed_coords, new_coords))

            if nfp_polys:
                try:
                    nfp_union = unary_union(nfp_polys)
                    valid_region = ifp.difference(nfp_union)
                except Exception:
                    continue
            else:
                valid_region = ifp

            if valid_region.is_empty:
                continue

            # Try ALL boundary vertices, not just the first — numerical noise can
            # put a vertex on the wrong side of an NFP, so we walk down the list.
            for nfx, nfy in _sorted_vertices(valid_region):
                bbox_tl_x = nfx + minx
                bbox_tl_y = nfy + miny

                # Cross-rotation pruning.
                if best is not None:
                    if bbox_tl_y > best[0] + 1e-6:
                        break  # later vertices have even larger y
                    if abs(bbox_tl_y - best[0]) < 1e-6 and bbox_tl_x >= best[1] - 1e-6:
                        continue

                candidate_poly = _placed_polygon(piece, bbox_tl_x, bbox_tl_y, rot)

                # Sanity guards.
                if candidate_poly.bounds[2] > fabric_width_mm - EDGE_GAP + 1e-3:
                    continue
                if candidate_poly.bounds[0] < EDGE_GAP - 1e-3:
                    continue
                if candidate_poly.bounds[1] < EDGE_GAP - 1e-3:
                    continue
                if any(_has_area_overlap(candidate_poly, pp) for pp in placed_polys):
                    continue

                best = (bbox_tl_y, bbox_tl_x, rot, candidate_poly)
                break  # vertices sorted ascending; first valid is best at this rotation

        # Fallback: if NFP found nothing usable, force a "new shelf" placement
        # below every placed piece at the first rotation whose width fits.
        # The candidate sits strictly below max_placed_bottom + EDGE_GAP, so by
        # construction it cannot overlap any placed piece — no overlap check.
        if best is None:
            max_placed_bottom = (
                max((pp.bounds[3] for pp in placed_polys), default=EDGE_GAP)
            )
            fallback_y = max_placed_bottom + EDGE_GAP
            for rot in rotations:
                pw, _ = _polygon_dims(piece, rot)
                if pw + 2 * EDGE_GAP > fabric_width_mm:
                    continue
                candidate_poly = _placed_polygon(piece, EDGE_GAP, fallback_y, rot)
                best = (fallback_y, EDGE_GAP, rot, candidate_poly)
                break

        if best is None:
            raise ValueError(
                f"Cannot place piece '{piece.name}' — no rotation fits "
                f"within fabric width {fabric_width_mm:.0f} mm."
            )

        bbox_tl_y, bbox_tl_x, rot, candidate_poly = best
        placements.append(Placement(piece.id, round(bbox_tl_x, 4), round(bbox_tl_y, 4), rot))
        placed_polys.append(candidate_poly)

    marker_length, utilization = _compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims)
    return placements, marker_length, utilization


# ---------------------------------------------------------------------------
# Sort strategies — try several orderings and keep the best.
# ---------------------------------------------------------------------------

_SORT_STRATEGIES = [
    lambda p: p.area,                                    # largest area first
    lambda p: max(p.bbox.width, p.bbox.height),          # longest dim first
    lambda p: p.bbox.height,                             # tallest first
    lambda p: p.bbox.width,                              # widest first
]


def _best_of_strategies(run_one) -> tuple[list[Placement], float, float]:
    """Run the packer with each sort strategy; return the shortest-length result."""
    best: tuple[list[Placement], float, float] | None = None
    for sort_key in _SORT_STRATEGIES:
        result = run_one(sort_key)
        if best is None or result[1] < best[1]:
            best = result
    assert best is not None
    return best


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _shorter(a: tuple[list[Placement], float, float] | None,
             b: tuple[list[Placement], float, float]) -> tuple[list[Placement], float, float]:
    """Return whichever layout has the shorter marker length."""
    if a is None or b[1] < a[1]:
        return b
    return a


def _modes_to_try(grain_mode: str) -> list[str]:
    """Bi mode's rotation set is a strict superset of single's. A greedy BLF
    can therefore produce a worse bi layout than single (a locally-good rotation
    leaves a worse global gap). To guarantee bi >= single, run both and keep
    the shorter result."""
    if grain_mode == "bi":
        return ["bi", "single"]
    return [grain_mode]


def auto_layout_polygon(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
) -> tuple[list[Placement], float, float]:
    """No-Fit-Polygon-based Bottom-Left-Fill (slow mode, accurate).

    Computes exact touching positions between the new piece and each placed
    piece via pyclipper.MinkowskiSum, then picks the lowest-leftmost candidate
    that fits within the fabric and doesn't positive-area-overlap any placed
    piece. Touching boundaries is allowed.

    Returns (placements, marker_length_mm, utilization_pct).
    Raises ValueError if any piece cannot fit at any allowed rotation.
    """
    best: tuple[list[Placement], float, float] | None = None
    for mode in _modes_to_try(grain_mode):
        def run_one(sort_key, _mode=mode):
            return _blf_pack_nfp(
                pieces, fabric_width_mm, _mode, fabric_grain_deg,
                sort_key=sort_key,
            )
        best = _shorter(best, _best_of_strategies(run_one))
    assert best is not None
    return best
