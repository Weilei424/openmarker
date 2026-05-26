from __future__ import annotations

import multiprocessing
import os
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import NamedTuple

import pyclipper
import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon, box as shapely_box
from shapely.ops import unary_union

from core.layout.cancellation import CancellationError, is_cancelled
from core.models.piece import Piece


# ---------------------------------------------------------------------------
# Parallel-cancel plumbing
# ---------------------------------------------------------------------------
# Tracks the in-flight ProcessPoolExecutor (if any) so /cancel-layout can
# terminate its worker children. Without this, parallel strategies run to
# completion after the user clicks Stop because the module-level cancellation
# flag only reaches the SERIAL hot loop — child processes never check it.
_executor_lock = threading.Lock()
_current_executor: ProcessPoolExecutor | None = None


def _set_current_executor(ex: ProcessPoolExecutor | None) -> None:
    global _current_executor
    with _executor_lock:
        _current_executor = ex


def kill_current_executor() -> None:
    """Forcibly terminate any in-flight ProcessPoolExecutor workers. Called by
    /cancel-layout so parallel strategies abort ASAP rather than running to
    completion. No-op when no executor is active or in serial mode.

    Touches ProcessPoolExecutor._processes — an internal attribute. If a future
    Python release removes it the except-Exception falls through gracefully and
    the executor still gets shutdown(cancel_futures=True), which prevents NEW
    submissions but doesn't kill the in-flight ones.
    """
    with _executor_lock:
        ex = _current_executor
    if ex is None:
        return
    try:
        for proc in list(ex._processes.values()):
            try:
                proc.terminate()
            except Exception:
                pass
    except Exception:
        # _processes is implementation-detail; if it disappears, fall through.
        pass
    try:
        ex.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Cross-worker shared cutoff (parallel pruning)
# ---------------------------------------------------------------------------
# Set in each worker process by `_init_worker` at pool spawn time. The main
# process publishes completed-strategy marker lengths into this Value as a
# running min, and workers read it during BLF to prune their own execution
# (see `shared_best_value` in `_blf_pack_nfp`).
_worker_shared_best = None


def _init_worker(value) -> None:
    """ProcessPoolExecutor initializer. Stashes the shared `Value` in a
    worker-process module global so `_run_one_strategy` can pass it down."""
    global _worker_shared_best
    _worker_shared_best = value


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


class _PrunedRun(Exception):
    """Internal: raised by `_blf_pack_nfp` when its partial marker length
    already meets or exceeds `best_marker_so_far`. The serial caller in
    `auto_layout_polygon` catches this and skips to the next strategy.

    The check is sound because BLF's partial marker length is monotone
    non-decreasing in the number of placed pieces — placing more can only
    push the bottom edge further down, never bring it up.
    """


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


def _base_id(piece_id: str) -> str:
    """Strip the frontend's '__c{n}' copy suffix.

    Two pieces sharing a base id have identical polygons, so an NFP computed for
    one is reusable for the other.
    """
    idx = piece_id.find("__c")
    return piece_id if idx < 0 else piece_id[:idx]


# Per-layout NFP cache. Key: (base_id_a, rot_a, base_id_b, rot_b). Value: NFP
# polygons in "A-at-origin" coordinates. Translate by A's placement offset on use.
NfpCache = dict[tuple[str, float, str, float], list[ShapelyPolygon]]


def _get_or_compute_nfp(
    cache: NfpCache,
    piece_a: Piece, rot_a: float,
    piece_b: Piece, rot_b: float,
) -> list[ShapelyPolygon]:
    """Memoized NFP between piece_a (stationary, at origin) and piece_b (orbiting,
    at origin), each rotated. Keyed by base id so multiple copies of the same
    shape and multiple sort strategies all share results.

    Uses the identity NFP(B, A) = -NFP(A, B) (reflected through origin) to
    serve a reverse-direction request from a cached forward result without
    re-running pyclipper.MinkowskiSum. Doubles effective hit rate across sort
    strategies that visit piece pairs in different orders.
    """
    base_a = _base_id(piece_a.id)
    base_b = _base_id(piece_b.id)
    key = (base_a, rot_a, base_b, rot_b)
    hit = cache.get(key)
    if hit is not None:
        return hit

    reverse_key = (base_b, rot_b, base_a, rot_a)
    reverse = cache.get(reverse_key)
    if reverse is not None:
        flipped = [
            shapely.affinity.scale(p, xfact=-1, yfact=-1, origin=(0, 0))
            for p in reverse
        ]
        cache[key] = flipped
        return flipped

    a_coords = _polygon_at_origin(piece_a, rot_a)
    b_coords = _polygon_at_origin(piece_b, rot_b)
    polys = _compute_nfp_polygons(a_coords, b_coords)
    cache[key] = polys
    return polys


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


class _Placed(NamedTuple):
    """A successfully placed piece, with the offset that turns its
    "at-origin rotated" coords into its placed coords. The offset lets us
    translate a cached NFP into the placed-piece's reference frame."""
    piece: Piece
    rotation: float
    polygon: ShapelyPolygon
    dx: float
    dy: float


def _blf_pack_nfp(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    sort_key=None,
    nfp_cache: NfpCache | None = None,
    best_marker_so_far: float | None = None,
    shared_best_value=None,  # multiprocessing.Value('d', ...) or None
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

    `nfp_cache` is reused across sort strategies and grain modes within one
    `auto_layout_polygon` call to avoid recomputing Minkowski sums for repeated
    (shape, rotation) pairs — the dominant cost when copies > 1.
    """
    if sort_key is None:
        sort_key = lambda p: p.area
    if nfp_cache is None:
        nfp_cache = {}
    sorted_pieces = sorted(pieces, key=sort_key, reverse=True)
    _validate_pieces_fit(sorted_pieces, fabric_width_mm, grain_mode, fabric_grain_deg, _polygon_dims)

    # Finite IFP height: piece heights stacked tallest-on-tallest as a hard upper bound.
    max_y_search = sum(max(p.bbox.width, p.bbox.height) for p in pieces) + EDGE_GAP

    placements: list[Placement] = []
    placed: list[_Placed] = []
    current_max_bottom: float = 0.0

    for piece in sorted_pieces:
        if is_cancelled():
            raise CancellationError("Auto-layout cancelled by user.")
        rotations = _layout_rotations(
            grain_mode, fabric_grain_deg, piece.grainline_direction_deg
        )
        # best carries: (bbox_tl_y, bbox_tl_x, rot, candidate_poly, orig_minx, orig_miny)
        # orig_minx/orig_miny are needed to derive (dx, dy) on commit so cached
        # NFPs can be shifted to this placement's reference frame later.
        best: tuple[float, float, float, ShapelyPolygon, float, float] | None = None

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
            for rec in placed:
                cached = _get_or_compute_nfp(
                    nfp_cache, rec.piece, rec.rotation, piece, rot
                )
                if not cached:
                    continue
                nfp_polys.extend(
                    shapely.affinity.translate(p, xoff=rec.dx, yoff=rec.dy)
                    for p in cached
                )

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
                if any(_has_area_overlap(candidate_poly, rec.polygon) for rec in placed):
                    continue

                best = (bbox_tl_y, bbox_tl_x, rot, candidate_poly, minx, miny)
                break  # vertices sorted ascending; first valid is best at this rotation

        # Fallback: if NFP found nothing usable, force a "new shelf" placement
        # below every placed piece at the first rotation whose width fits.
        # The candidate sits strictly below max_placed_bottom + EDGE_GAP, so by
        # construction it cannot overlap any placed piece — no overlap check.
        if best is None:
            max_placed_bottom = max(
                (rec.polygon.bounds[3] for rec in placed), default=EDGE_GAP
            )
            fallback_y = max_placed_bottom + EDGE_GAP
            for rot in rotations:
                pw, _ = _polygon_dims(piece, rot)
                if pw + 2 * EDGE_GAP > fabric_width_mm:
                    continue
                candidate_poly = _placed_polygon(piece, EDGE_GAP, fallback_y, rot)
                orig_coords = _polygon_at_origin(piece, rot)
                orig_minx = min(c[0] for c in orig_coords)
                orig_miny = min(c[1] for c in orig_coords)
                best = (fallback_y, EDGE_GAP, rot, candidate_poly, orig_minx, orig_miny)
                break

        if best is None:
            raise ValueError(
                f"Cannot place piece '{piece.name}' — no rotation fits "
                f"within fabric width {fabric_width_mm:.0f} mm."
            )

        bbox_tl_y, bbox_tl_x, rot, candidate_poly, orig_minx, orig_miny = best
        placements.append(Placement(piece.id, round(bbox_tl_x, 4), round(bbox_tl_y, 4), rot))
        dx = candidate_poly.bounds[0] - orig_minx
        dy = candidate_poly.bounds[1] - orig_miny
        placed.append(_Placed(piece, rot, candidate_poly, dx, dy))

        # Branch pruning. `candidate_poly.bounds[3]` is the bottom edge of the
        # bbox in screen-y-down coords (= top + height because _placed_polygon
        # aligns minx/miny to the requested top-left). Partial marker length is
        # monotone non-decreasing — once it meets the cutoff, this run cannot win.
        if candidate_poly.bounds[3] > current_max_bottom:
            current_max_bottom = candidate_poly.bounds[3]
        # Effective cutoff = min(caller-supplied initial, shared cross-worker).
        # `.value` reads through the Value's internal lock (~1-5µs on Windows);
        # negligible vs the placement work done above.
        effective_cutoff = best_marker_so_far
        if shared_best_value is not None:
            sv = shared_best_value.value
            if effective_cutoff is None or sv < effective_cutoff:
                effective_cutoff = sv
        if effective_cutoff is not None and current_max_bottom + EDGE_GAP >= effective_cutoff:
            raise _PrunedRun()

    marker_length, utilization = _compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims)
    return placements, marker_length, utilization


# ---------------------------------------------------------------------------
# Sort strategies — try several orderings and keep the best.
# ---------------------------------------------------------------------------

# Named (module-level) functions so they can be pickled and shipped to
# ProcessPoolExecutor workers; lambdas are NOT picklable.
def _sort_by_area(p: Piece) -> float: return p.area
def _sort_by_max_dim(p: Piece) -> float: return max(p.bbox.width, p.bbox.height)
def _sort_by_height(p: Piece) -> float: return p.bbox.height
def _sort_by_width(p: Piece) -> float: return p.bbox.width

_SORT_STRATEGIES = [_sort_by_area, _sort_by_max_dim, _sort_by_height, _sort_by_width]


def _run_one_strategy(
    pieces: list[Piece],
    fabric_width_mm: float,
    mode: str,
    fabric_grain_deg: float,
    sort_index: int,
) -> tuple[list[Placement], float, float]:
    """Module-level entry for ProcessPoolExecutor. sort_index selects from
    _SORT_STRATEGIES so we don't have to pickle the callable across the
    process boundary. Reads `_worker_shared_best` (set by `_init_worker`)
    so this strategy can prune via the cross-worker shared cutoff."""
    sort_key = _SORT_STRATEGIES[sort_index]
    return _blf_pack_nfp(
        pieces, fabric_width_mm, mode, fabric_grain_deg,
        sort_key=sort_key,
        shared_best_value=_worker_shared_best,
    )


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


def _worker_count(effort: int) -> int:
    """Resolve user-facing effort level (1-5) to a concrete worker count
    based on the local CPU count. Higher levels leave less headroom for
    the UI thread; Max uses every available core.

    effort values outside 1-5 are clamped (>5 → max, <1 → 1). API-level
    validation rejects bad input before it ever reaches this function.
    """
    if effort <= 1:
        return 1
    cpu = os.cpu_count() or 4
    if effort == 2:
        return 2
    if effort == 3:
        return max(2, cpu // 2)
    if effort == 4:
        return max(2, cpu - 1)
    # effort >= 5
    return max(2, cpu)


def auto_layout_polygon(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    disable_nfp_cache: bool = False,
    effort: int = 1,
    disable_pruning: bool = False,
) -> tuple[list[Placement], float, float]:
    """No-Fit-Polygon-based Bottom-Left-Fill (slow mode, accurate).

    Computes exact touching positions between the new piece and each placed
    piece via pyclipper.MinkowskiSum, then picks the lowest-leftmost candidate
    that fits within the fabric and doesn't positive-area-overlap any placed
    piece. Touching boundaries is allowed.

    Returns (placements, marker_length_mm, utilization_pct).
    Raises ValueError if any piece cannot fit at any allowed rotation.

    `disable_nfp_cache`: when True, each strategy run gets a fresh cache and
    no cross-strategy reuse happens. Identical results, slower — exposed for
    A/B comparison and debugging only. Only meaningful on the serial path
    (the parallel path always rebuilds per-worker caches anyway).

    `effort`: user-facing parallel effort level (1=serial, 5=all cores).
    When >1 and the input is large enough to amortize Windows process spawn
    cost, sort strategies and bi-mode's secondary single run are dispatched
    across worker processes via ProcessPoolExecutor. Cancellation is
    best-effort on the parallel path (in-flight workers run to completion).

    `disable_pruning`: when True, branch pruning is disabled in both serial and
    parallel paths. Identical results, slower — exposed for A/B benchmarking and
    debugging only, mirroring `disable_nfp_cache`.
    """
    modes = _modes_to_try(grain_mode)
    total_runs = len(modes) * len(_SORT_STRATEGIES)
    workers = _worker_count(effort)

    # Skip the pool for tiny inputs — Windows spawn cost (~200-500ms per
    # worker) outweighs the parallel win. The threshold is intentionally
    # conservative; benchmarks should refine it but the cost of misjudging
    # is small (a few hundred ms on a job that would have taken <1s anyway).
    use_pool = workers > 1 and total_runs * len(pieces) >= 20

    if not use_pool:
        # Serial path. NFP cache shared across all strategies/modes for max
        # reuse — this is the dominant win when copies > 1.
        shared_cache: NfpCache = {}
        best: tuple[list[Placement], float, float] | None = None
        for mode in modes:
            for sort_index in range(len(_SORT_STRATEGIES)):
                cache = {} if disable_nfp_cache else shared_cache
                cutoff = None if disable_pruning else (best[1] if best is not None else None)
                try:
                    result = _blf_pack_nfp(
                        pieces, fabric_width_mm, mode, fabric_grain_deg,
                        sort_key=_SORT_STRATEGIES[sort_index],
                        nfp_cache=cache,
                        best_marker_so_far=cutoff,
                    )
                except _PrunedRun:
                    continue
                best = _shorter(best, result)
        assert best is not None
        return best

    # Parallel path. Each worker rebuilds its own NFP cache (lost cross-strategy
    # reuse) but we get N-way parallelism. /cancel-layout terminates the worker
    # processes via kill_current_executor (see module top); the resulting
    # BrokenProcessPool from future.result() is translated to CancellationError.
    #
    # Cross-worker pruning: a shared `multiprocessing.Value` carries a running
    # min of completed-strategy marker lengths. Workers read it per placement
    # and abort (raise _PrunedRun) once their partial passes the cutoff. Main
    # process publishes via as_completed so the cutoff tightens as workers finish.
    shared_best = None if disable_pruning else multiprocessing.Value("d", float("inf"))

    best: tuple[list[Placement], float, float] | None = None
    futures = []
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_worker,
        initargs=(shared_best,),
    ) as pool:
        _set_current_executor(pool)
        try:
            for mode in modes:
                for sort_index in range(len(_SORT_STRATEGIES)):
                    futures.append(pool.submit(
                        _run_one_strategy,
                        pieces, fabric_width_mm, mode, fabric_grain_deg, sort_index,
                    ))
            try:
                for f in as_completed(futures):
                    try:
                        result = f.result()
                    except _PrunedRun:
                        continue  # worker self-aborted via the shared cutoff; ignore
                    if shared_best is not None:
                        # Lock so worker-process reads (via shared_best_value.value) can't
                        # see a partial write while the main thread updates the shared cutoff.
                        # as_completed itself is single-threaded, so there are no concurrent
                        # writers — the lock exists solely to serialize against reader workers.
                        with shared_best.get_lock():
                            if result[1] < shared_best.value:
                                shared_best.value = result[1]
                    best = _shorter(best, result)
            except BrokenProcessPool as e:
                raise CancellationError("Auto-layout cancelled (workers terminated).") from e
        finally:
            _set_current_executor(None)

    assert best is not None
    return best
