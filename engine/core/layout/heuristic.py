from __future__ import annotations

import math
from dataclasses import dataclass

import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon

from core.layout.grain import allowed_rotations
from core.models.piece import Piece

GAP = 10.0  # mm gap between pieces and from fabric edge


@dataclass
class Placement:
    piece_id: str
    x: float
    y: float
    rotation_deg: float


# ---------------------------------------------------------------------------
# Shared geometry helpers
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


def _compute_metrics(
    placements: list[Placement],
    pieces: list[Piece],
    fabric_width_mm: float,
    dim_fn,
) -> tuple[float, float]:
    """Return (marker_length_mm, utilization_pct).

    Marker length is the lowest Y edge across all placed pieces (the "length"
    direction we're trying to minimize). Fabric width constrains the X axis;
    pieces stack downward into the unlimited length direction.
    """
    if not placements:
        return 0.0, 0.0
    piece_map = {p.id: p for p in pieces}
    marker_length = max(
        pl.y + dim_fn(piece_map[pl.piece_id], pl.rotation_deg)[1]
        for pl in placements
    ) + GAP
    total_area = sum(p.area for p in pieces)
    utilization = round(total_area / (marker_length * fabric_width_mm) * 100, 2)
    return round(marker_length, 2), utilization


# ---------------------------------------------------------------------------
# Validation (shared)
# ---------------------------------------------------------------------------

def _validate_pieces_fit(pieces: list[Piece], fabric_width_mm: float, grain_mode: str, fabric_grain_deg: float, dim_fn) -> None:
    for piece in pieces:
        rotations = allowed_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg)
        min_w = min(dim_fn(piece, r)[0] for r in rotations)
        if min_w + 2 * GAP > fabric_width_mm:
            raise ValueError(
                f"Piece '{piece.name}' minimum width {min_w:.1f} mm cannot fit within "
                f"usable fabric width {fabric_width_mm - 2 * GAP:.1f} mm at any allowed rotation."
            )


# ---------------------------------------------------------------------------
# Strip-packing core (shared structure; dim_fn and fits_fn differ by mode)
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
    shelf_y = GAP
    shelf_h = 0.0
    x_cursor = GAP

    def _best_rotation(piece: Piece, x: float, y: float) -> tuple[float, float, float] | None:
        """(rot, w, h) minimising h that fits at (x, y); None if nothing fits."""
        best: tuple[float, float, float] | None = None
        for rot in allowed_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg):
            w, h = dim_fn(piece, rot)
            if fits_fn(piece, x, y, rot, w) and x + w + GAP <= fabric_width_mm:
                if best is None or h < best[2]:
                    best = (rot, w, h)
        return best

    def _best_rotation_new_shelf(piece: Piece) -> tuple[float, float, float]:
        """(rot, w, h) minimising h on a fresh shelf at x=GAP."""
        best: tuple[float, float, float] | None = None
        for rot in allowed_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg):
            w, h = dim_fn(piece, rot)
            if w + 2 * GAP <= fabric_width_mm:
                if best is None or h < best[2]:
                    best = (rot, w, h)
        assert best is not None, "piece passed validation but no rotation fits — invariant violated"
        return best

    for piece in sorted_pieces:
        result = _best_rotation(piece, x_cursor, shelf_y)
        if result is None:
            shelf_y += shelf_h + GAP
            shelf_h = 0.0
            x_cursor = GAP
            result = _best_rotation_new_shelf(piece)

        rot, w, h = result
        placements.append(Placement(piece.id, round(x_cursor, 4), round(shelf_y, 4), rot))
        if on_placed is not None:
            on_placed(piece, placements[-1], rot)
        x_cursor += w + GAP
        shelf_h = max(shelf_h, h)

    marker_length, utilization = _compute_metrics(placements, pieces, fabric_width_mm, dim_fn)
    return placements, marker_length, utilization


# ---------------------------------------------------------------------------
# Sort strategies — tried in order; best (shortest marker length) wins.
# ---------------------------------------------------------------------------

_SORT_STRATEGIES = [
    lambda p: p.area,                                    # largest area first
    lambda p: max(p.bbox.width, p.bbox.height),          # longest dim first
    lambda p: p.bbox.height,                             # tallest first
    lambda p: p.bbox.width,                              # widest first
]


def _best_of_strategies(run_one) -> tuple[list[Placement], float, float]:
    """Run the packer with each sort strategy and return the result with the
    shortest marker length. `run_one` is a callable taking a sort_key and
    returning (placements, marker_length, utilization)."""
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
    """
    Strip-packing using axis-aligned bounding boxes.
    Fast; no polygon-level collision detection.
    Returns (placements, marker_length_mm, utilization_pct).
    Raises ValueError if any piece cannot fit at any allowed rotation.
    """
    def fits_bbox(piece, x, y, rot, w):
        # Bbox non-overlap is guaranteed by the left-to-right cursor; no extra check needed.
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
    """
    Strip-packing using actual piece polygons for collision detection (Shapely).
    More accurate than bbox mode for irregular pieces; slower for free rotation.
    Returns (placements, marker_length_mm, utilization_pct).
    Raises ValueError if any piece cannot fit at any allowed rotation.
    """
    def run_one(sort_key):
        # Fresh placed_polys list per strategy attempt.
        placed_polys: list[ShapelyPolygon] = []

        def fits_polygon(piece, x, y, rot, w):
            candidate = _placed_polygon(piece, x, y, rot)
            if candidate.bounds[2] + GAP > fabric_width_mm:
                return False
            return not any(candidate.intersects(pp) for pp in placed_polys)

        def on_placed(piece, placement, rot):
            placed_polys.append(_placed_polygon(piece, placement.x, placement.y, rot))

        return _strip_pack(
            pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
            dim_fn=_polygon_dims,
            fits_fn=fits_polygon,
            on_placed=on_placed,
            sort_key=sort_key,
        )

    return _best_of_strategies(run_one)
