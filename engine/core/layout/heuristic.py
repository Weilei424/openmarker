from __future__ import annotations

import math
from dataclasses import dataclass

import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon

from core.layout.grain import allowed_rotations
from core.models.piece import Piece

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

def _rotated_bbox_dims(piece: Piece, rotation_deg: float) -> tuple[float, float]:
    """Return (width, height) of the axis-aligned bbox of the piece rotated CW by rotation_deg."""
    angle_rad = math.radians(rotation_deg)
    cos_a = abs(math.cos(angle_rad))
    sin_a = abs(math.sin(angle_rad))
    w = piece.bbox.width * cos_a + piece.bbox.height * sin_a
    h = piece.bbox.width * sin_a + piece.bbox.height * cos_a
    return w, h


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


def _has_area_overlap(a: ShapelyPolygon, b: ShapelyPolygon, eps: float = 1e-3) -> bool:
    """Return True only if polygons overlap with positive area.

    Touching at a shared edge or vertex produces intersection area == 0,
    so this correctly treats touching as non-collision per the cutting-room rule.
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

    For 'none' mode we use cardinal angles (4 candidates) rather than the 360
    returned by allowed_rotations(): production markers only ever use cardinal
    rotations, and 360 candidates is wasted search across grain-free layouts.
    """
    if grain_mode == "none" or piece_grainline_deg is None:
        return [0.0, 90.0, 180.0, 270.0]
    target = (fabric_grain_deg - piece_grainline_deg) % 360
    if grain_mode == "single":
        return [target]
    elif grain_mode == "bi":
        return [target, (target + 180) % 360]
    else:
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
# Strip-packing (bbox / fast mode) — shelf-based
# ---------------------------------------------------------------------------

def _strip_pack(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    dim_fn,
    fits_fn,
    on_placed=None,
    sort_key=None,
) -> tuple[list[Placement], float, float]:
    if sort_key is None:
        sort_key = lambda p: p.area
    sorted_pieces = sorted(pieces, key=sort_key, reverse=True)
    _validate_pieces_fit(sorted_pieces, fabric_width_mm, grain_mode, fabric_grain_deg, dim_fn)

    placements: list[Placement] = []
    shelf_y = EDGE_GAP
    shelf_h = 0.0
    x_cursor = EDGE_GAP

    def _best_rotation(piece: Piece, x: float, y: float) -> tuple[float, float, float] | None:
        best: tuple[float, float, float] | None = None
        for rot in _layout_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg):
            w, h = dim_fn(piece, rot)
            if fits_fn(piece, x, y, rot, w) and x + w + EDGE_GAP <= fabric_width_mm:
                if best is None or h < best[2]:
                    best = (rot, w, h)
        return best

    def _best_rotation_new_shelf(piece: Piece) -> tuple[float, float, float]:
        best: tuple[float, float, float] | None = None
        for rot in _layout_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg):
            w, h = dim_fn(piece, rot)
            if w + 2 * EDGE_GAP <= fabric_width_mm:
                if best is None or h < best[2]:
                    best = (rot, w, h)
        assert best is not None, "piece passed validation but no rotation fits — invariant violated"
        return best

    for piece in sorted_pieces:
        result = _best_rotation(piece, x_cursor, shelf_y)
        if result is None:
            shelf_y += shelf_h + EDGE_GAP
            shelf_h = 0.0
            x_cursor = EDGE_GAP
            result = _best_rotation_new_shelf(piece)

        rot, w, h = result
        placements.append(Placement(piece.id, round(x_cursor, 4), round(shelf_y, 4), rot))
        if on_placed is not None:
            on_placed(piece, placements[-1], rot)
        x_cursor += w + EDGE_GAP
        shelf_h = max(shelf_h, h)

    marker_length, utilization = _compute_metrics(placements, pieces, fabric_width_mm, dim_fn)
    return placements, marker_length, utilization


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

def auto_layout_bbox(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
) -> tuple[list[Placement], float, float]:
    """Strip-packing using axis-aligned bounding boxes (fast mode).

    Returns (placements, marker_length_mm, utilization_pct).
    Raises ValueError if any piece cannot fit at any allowed rotation.
    """
    def fits_bbox(piece, x, y, rot, w):
        return True

    def run_one(sort_key):
        return _strip_pack(
            pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
            dim_fn=_rotated_bbox_dims,
            fits_fn=fits_bbox,
            sort_key=sort_key,
        )

    return _best_of_strategies(run_one)


def auto_layout_polygon(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
) -> tuple[list[Placement], float, float]:
    """Bottom-Left-Fill using polygon collision detection.

    Better packing for irregular shapes than strip-packing: pieces nestle into
    gaps above shorter neighbors. Touching boundaries is allowed; only positive-
    area overlap is rejected.

    Returns (placements, marker_length_mm, utilization_pct).
    Raises ValueError if any piece cannot fit at any allowed rotation.
    """
    def run_one(sort_key):
        return _blf_pack(
            pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
            sort_key=sort_key,
        )

    return _best_of_strategies(run_one)
