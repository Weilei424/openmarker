"""Periodic-lattice and banded warm-start layout generators (Ultra-tier seed spike).

Spec: docs/superpowers/specs/2026-07-04-lattice-warmstart-design.md
(PERFORMANCE.md § 5.B "Periodic-lattice warm-start generator").

Both public functions mirror auto_layout_polygon's return
(placements, marker_length_mm, utilization_pct) and produce layouts that pass
separation._validate_layout, so the Ultra warm-start converter
(_placements_to_jagua) consumes them directly. NOT wired into production — the
spike (engine/tests/spike_lattice_warmstart.py) is the only caller until a GO
verdict.

Frames: lattice math happens in the NFP frame (polygon rotated CW about (0, 0),
then translated by t — matching _polygon_at_origin / _get_or_compute_nfp).
Emitted Placements use the engine convention (x, y) = rotated-polygon bbox-min,
the frame _placed_polygon expects.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import shapely
import shapely.affinity
from shapely.geometry import LineString, Polygon as ShapelyPolygon
from shapely.ops import unary_union

from core.layout.clustering import group_pieces_by_base_id
from core.layout.heuristic import (
    NfpCache,
    Placement,
    _blf_pack_nfp,
    _compute_metrics,
    _get_or_compute_nfp,
    _has_area_overlap,
    _layout_rotations,
    _placed_polygon,
    _polygon_dims,
    _validate_pieces_fit,
    auto_layout_polygon,
)
from core.models.piece import Piece

# Search-resolution knobs (spec § 4). Module constants, not public API.
STAGGER_SAMPLES = 8        # v1 stagger candidates per (cell, d): sx = i * w0 / 8
D_CANDIDATE_CAP = 200      # max pair offsets per NFP part after dedup
SEGMENT_MM = 50.0          # NFP edge densification for edge-interior contacts
SETTLE_STEP_MM = 2.0       # band settle probe step
SETTLE_MAX_STEPS = 1000    # safety cap = 2 m of slide per band
_MIN_PERIOD = 0.5          # mm — reject degenerate lattice vectors below this
_EPS = 1e-6


@dataclass
class _Band:
    """One per-shape-group band, in band-local coords (y starts at 0)."""
    placements: list[Placement]
    length: float              # band y-extent = its marker-length contribution
    sort_area: float           # representative piece area — stacking order key


def _raw_rotated(piece: Piece, rotation_deg: float) -> ShapelyPolygon:
    """Piece polygon rotated CW (screen frame) about (0, 0), NOT translated —
    the frame the NFPs from _get_or_compute_nfp live in."""
    return shapely.affinity.rotate(
        ShapelyPolygon(piece.polygon), rotation_deg, origin=(0, 0), use_radians=False)


def _shape_groups(pieces: list[Piece]) -> list[list[Piece]]:
    """Base-id groups, merged when representatives are exact duplicates (same
    grainline + vertex count + area, topological equality — vertex-order-
    insensitive). Duplicated block shapes (e.g. sample_2 piece_0 == piece_1)
    then share one band; a missed merge is harmless — the shapes just band
    separately (spec § 2 'Band unit')."""
    merged: list[tuple[Piece, ShapelyPolygon, list[Piece]]] = []
    for members in group_pieces_by_base_id(pieces).values():
        rep = members[0]
        poly = ShapelyPolygon(rep.polygon)
        for mrep, mpoly, mlist in merged:
            if (mrep.grainline_direction_deg == rep.grainline_direction_deg
                    and len(mrep.polygon) == len(rep.polygon)
                    and abs(mrep.area - rep.area) < 1e-6
                    and mpoly.equals(poly)):
                mlist.extend(members)
                break
        else:
            merged.append((rep, poly, list(members)))
    return [mlist for _, _, mlist in merged]


def _build_blf_band(group: list[Piece], fabric_width_mm: float, grain_mode: str,
                    fabric_grain_deg: float, cache: NfpCache) -> _Band | None:
    """Arm-B band: NFP-BLF over just this group's copies at full fabric width.
    Copies are identical, so sorting is meaningless -> presorted=True."""
    rep = group[0]
    rotset = _layout_rotations(grain_mode, fabric_grain_deg, rep.grainline_direction_deg)
    try:
        placements, marker, _util = _blf_pack_nfp(
            list(group), fabric_width_mm, grain_mode, fabric_grain_deg,
            nfp_cache=cache, override_rotations=list(rotset), presorted=True)
    except ValueError:
        return None
    return _Band(placements, marker, rep.area)


def _band_collides(trial: list[ShapelyPolygon], placed: list[ShapelyPolygon],
                   placed_bounds: list[tuple[float, float, float, float]]) -> bool:
    for t in trial:
        tb = t.bounds
        for p, pb in zip(placed, placed_bounds):
            if tb[2] < pb[0] or pb[2] < tb[0] or tb[3] < pb[1] or pb[3] < tb[1]:
                continue
            if _has_area_overlap(t, p):
                return True
    return False


def _settle_shift(polys: list[ShapelyPolygon], placed: list[ShapelyPolygon],
                  placed_bounds: list[tuple[float, float, float, float]]) -> float:
    """Largest safe downward (-y) slide for a band: bbox fast-forward to the
    nearest possible contact, then SETTLE_STEP_MM polygon probes until first
    contact. The start position is clear (guaranteed by _stack_and_settle's
    frontier invariant), so 'last clear step' is well-defined; the floor y >= 0
    is a hard stop (spec § 4.6)."""
    floor = min(p.bounds[1] for p in polys)          # distance to y = 0
    gap = floor
    for a in polys:
        ab = a.bounds
        for pb in placed_bounds:
            if ab[2] < pb[0] or pb[2] < ab[0]:
                continue                             # no x overlap -> no constraint
            if pb[3] <= ab[1] + _EPS:
                gap = min(gap, ab[1] - pb[3])        # vertical bbox gap
            else:
                gap = 0.0                            # bboxes already interleaved
    gap = max(0.0, gap)
    cur = [shapely.affinity.translate(p, yoff=-gap) for p in polys] if gap else list(polys)
    shift = gap
    for _ in range(SETTLE_MAX_STEPS):
        if shift + SETTLE_STEP_MM > floor + _EPS:
            break
        trial = [shapely.affinity.translate(p, yoff=-SETTLE_STEP_MM) for p in cur]
        if _band_collides(trial, placed, placed_bounds):
            break
        cur, shift = trial, shift + SETTLE_STEP_MM
    return shift


def _stack_and_settle(bands: list[_Band], pieces_by_id: dict[str, Piece]) -> list[Placement]:
    """Stack bands big-pieces-first along +y, settling each band toward y = 0
    against the already-settled ones (spec § 4.6). Each band starts at the
    settled FRONTIER — max y over all settled pieces — so its start position is
    clear by construction even when an earlier band settled deeper than its own
    extent (a plain running offset would drag the start back inside band 1)."""
    ordered = sorted(bands, key=lambda b: -b.sort_area)
    out: list[Placement] = []
    placed: list[ShapelyPolygon] = []
    placed_bounds: list[tuple[float, float, float, float]] = []
    y_off = 0.0
    for band in ordered:
        polys = [_placed_polygon(pieces_by_id[p.piece_id], p.x, p.y + y_off, p.rotation_deg)
                 for p in band.placements]
        shift = _settle_shift(polys, placed, placed_bounds) if placed else 0.0
        for p, poly in zip(band.placements, polys):
            out.append(Placement(p.piece_id, p.x, round(p.y + y_off - shift, 4),
                                 p.rotation_deg))
            settled = shapely.affinity.translate(poly, yoff=-shift) if shift else poly
            placed.append(settled)
            placed_bounds.append(settled.bounds)
        y_off = max(pb[3] for pb in placed_bounds)   # frontier, never retreats
    return out


def _layout(pieces: list[Piece], fabric_width_mm: float, grain_mode: str,
            fabric_grain_deg: float, band_builders, ladder_log):
    """Shared banded pipeline. band_builders = ordered fallback ladder of
    (rung_name, builder) tried per shape group; a group with no band at all
    drops the WHOLE layout to plain Fast-BLF (spec § 4.5)."""
    if not pieces:
        raise ValueError("no pieces to lay out")
    _validate_pieces_fit(pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
                         _polygon_dims)
    cache: NfpCache = {}
    bands: list[_Band] = []
    for group in _shape_groups(pieces):
        band, rung = None, None
        for name, builder in band_builders:
            band = builder(group, fabric_width_mm, grain_mode, fabric_grain_deg, cache)
            if band is not None:
                rung = name
                break
        if band is None:
            if ladder_log is not None:
                ladder_log.append((group[0].id, "fast-blf-fallback"))
            return auto_layout_polygon(pieces, fabric_width_mm, grain_mode,
                                       fabric_grain_deg, effort=1)
        if ladder_log is not None:
            ladder_log.append((group[0].id, rung))
        bands.append(band)
    placements = _stack_and_settle(bands, {p.id: p for p in pieces})
    marker, util = _compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims)
    return placements, marker, util


def banded_blf_layout(pieces: list[Piece], fabric_width_mm: float, grain_mode: str,
                      fabric_grain_deg: float,
                      ladder_log: list[tuple[str, str]] | None = None,
                      ) -> tuple[list[Placement], float, float]:
    """Arm B: per-shape-group BLF bands, stacked + settled. Deterministic."""
    return _layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
                   [("blf", _build_blf_band)], ladder_log)


# ---------------------------------------------------------------------------
# Lattice bands (arm A) — spec § 4
# ---------------------------------------------------------------------------

@dataclass
class _Cell:
    """One lattice cell. Members are (engine rotation, t) with t the NFP-frame
    translation of the raw-rotated polygon; bbox_* describe the member union."""
    rotations: list[float]
    offsets: list[tuple[float, float]]
    x_extent: float
    y_extent: float
    bbox_min: tuple[float, float]


def _make_cell(piece: Piece, rotations: list[float],
               offsets: list[tuple[float, float]]) -> _Cell:
    bounds = [
        shapely.affinity.translate(_raw_rotated(piece, r), xoff=tx, yoff=ty).bounds
        for r, (tx, ty) in zip(rotations, offsets)
    ]
    minx = min(b[0] for b in bounds)
    miny = min(b[1] for b in bounds)
    maxx = max(b[2] for b in bounds)
    maxy = max(b[3] for b in bounds)
    return _Cell(rotations, offsets, maxx - minx, maxy - miny, (minx, miny))


def _forbidden_set(piece: Piece, cell: _Cell, cache: NfpCache):
    """F = { t : cell overlaps (cell + t) } = union over member pairs (i, j) of
    NFP(shape@rot_i, shape@rot_j) translated by (t_i - t_j)  (spec § 4.2)."""
    parts = []
    for ri, ti in zip(cell.rotations, cell.offsets):
        for rj, tj in zip(cell.rotations, cell.offsets):
            for nfp in _get_or_compute_nfp(cache, piece, ri, piece, rj):
                parts.append(shapely.affinity.translate(
                    nfp, xoff=ti[0] - tj[0], yoff=ti[1] - tj[1]))
    return unary_union(parts)


def _exit_along_x(F) -> float:
    """Rightmost crossing of F with the +x axis = smallest safe horizontal
    period w0. Any m*w0 (m >= 1) lies beyond every crossing on that line, so a
    whole row is overlap-free by construction (spec § 4.3)."""
    line = LineString([(0.0, 0.0), (F.bounds[2] + 1.0, 0.0)])
    hit = F.intersection(line)
    return 0.0 if hit.is_empty else hit.bounds[2]


def _top_crossing(F, cx: float) -> float:
    """Topmost crossing (y >= 0) of F with the vertical line x = cx; 0.0 when
    the line is clear. Points at/beyond the topmost crossing are outside F
    along that line — the conservative 'outermost exit' rule (holes in F are
    skipped, a noted spec refinement)."""
    top = F.bounds[3]
    if top <= 0.0:
        return 0.0
    hit = F.intersection(LineString([(cx, 0.0), (cx, top + 1.0)]))
    return 0.0 if hit.is_empty else max(0.0, hit.bounds[3])


def _v1_height(F, w0: float, sx: float) -> float | None:
    """Smallest safe row advance h1 for stagger sx: at/beyond the topmost
    F-crossing of every realized inter-row column x = j*sx + m*w0 (m in Z),
    for every row distance j while j*h1 is within F's y-extent. Constraints
    are one-sided (>= a column's top crossing), so growing h1 never invalidates
    an earlier j. The caps trade exhaustiveness for speed — the assembled
    band's exact overlap check is the backstop (spec § 4.5)."""
    fminx, _, fmaxx, fmaxy = F.bounds
    if (fmaxx - fminx) / w0 > 64:
        return None                           # degenerate: too many columns

    def columns(dx: float) -> list[float]:
        m_lo = math.floor((fminx - dx) / w0)
        m_hi = math.ceil((fmaxx - dx) / w0)
        return [dx + m * w0 for m in range(m_lo, m_hi + 1)]

    h1 = max((_top_crossing(F, cx) for cx in columns(sx)), default=0.0)
    if h1 < _MIN_PERIOD:
        return None
    j = 2
    while j * h1 < fmaxy + _EPS and j <= 64:
        req = max((_top_crossing(F, cx) for cx in columns(j * sx)), default=0.0)
        h1 = max(h1, req / j)
        j += 1
    return h1


def _band_plan(cell: _Cell, w0: float, sx: float, h1: float, copies: int,
               fabric_width_mm: float) -> tuple[int, int, float] | None:
    """(k, rows, band_length) for the best feasible column count, or None.
    Row j sits at x-offset (j*sx) % w0 (columns are w0-periodic), so k must fit
    at the WORST row offset. Feasibility is monotone in k (fewer rows -> offset
    set shrinks) and band length is non-increasing in k, so the largest
    feasible k wins (spec § 4.4)."""
    cells_needed = math.ceil(copies / len(cell.rotations))
    k_cap = int((fabric_width_mm - cell.x_extent + _EPS) // w0) + 1
    for k in range(min(k_cap, cells_needed), 0, -1):
        rows = math.ceil(cells_needed / k)
        max_off = max((j * sx) % w0 for j in range(rows))
        if max_off + (k - 1) * w0 + cell.x_extent <= fabric_width_mm + _EPS:
            return k, rows, (rows - 1) * h1 + cell.y_extent
    return None


def _assemble_band(group: list[Piece], cell: _Cell, w0: float, sx: float,
                   h1: float, k: int, fabric_width_mm: float,
                   ) -> tuple[list[Placement], float] | None:
    """Place the group's copies row-major (partial cell/row last) and run the
    exact backstop: pairwise area-overlap + width bounds. Returns band-local
    (placements, length) or None -> caller falls to the next ladder rung."""
    n_mem = len(cell.rotations)
    ordered = sorted(group, key=lambda p: p.id)
    placements: list[Placement] = []
    polys: list[ShapelyPolygon] = []
    for idx, piece in enumerate(ordered):
        cell_i, mem_i = divmod(idx, n_mem)
        row, col = divmod(cell_i, k)
        tx = (row * sx) % w0 + col * w0 + (cell.offsets[mem_i][0] - cell.bbox_min[0])
        ty = row * h1 + (cell.offsets[mem_i][1] - cell.bbox_min[1])
        rot = cell.rotations[mem_i]
        poly = shapely.affinity.translate(_raw_rotated(piece, rot), xoff=tx, yoff=ty)
        b = poly.bounds
        placements.append(Placement(piece.id, round(b[0], 4), round(b[1], 4), rot))
        polys.append(poly)
    for i in range(len(polys)):
        bi = polys[i].bounds
        if bi[0] < -0.5 or bi[2] > fabric_width_mm + 0.5:
            return None
        for j in range(i + 1, len(polys)):
            bj = polys[j].bounds
            if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                continue
            if _has_area_overlap(polys[i], polys[j]):
                return None
    min_y = min(p.bounds[1] for p in polys)
    max_y = max(p.bounds[3] for p in polys)
    shifted = [Placement(p.piece_id, p.x, round(p.y - min_y, 4), p.rotation_deg)
               for p in placements]
    return shifted, max_y - min_y


def _pair_offset_candidates(nfp: ShapelyPolygon) -> list[tuple[float, float]]:
    """d candidates on the RAW NFP boundary: vertices + per-edge midpoints +
    SEGMENT_MM densification, 1mm-deduped, stride-capped. Midpoints are
    load-bearing (a right triangle's perfect pair offset is an edge MIDPOINT);
    raw boundary only — simplifying can cut inside the NFP and create overlap
    far beyond the 0.5mm² tolerance (spec § 4.1)."""
    ring = list(nfp.exterior.coords)[:-1]
    mids = [((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])]
    dense = list(shapely.segmentize(nfp, SEGMENT_MM).exterior.coords)[:-1]
    cands, seen = [], set()
    for dx, dy in [*ring, *mids, *dense]:
        key = (round(dx), round(dy))               # 1mm dedup grid
        if key not in seen:
            seen.add(key)
            cands.append((dx, dy))
    stride = max(1, len(cands) // D_CANDIDATE_CAP)
    return cands[::stride]


def _build_lattice_band(group: list[Piece], fabric_width_mm: float, grain_mode: str,
                        fabric_grain_deg: float, cache: NfpCache) -> _Band | None:
    """Arm-A band: densest strip-aligned lattice of single / Kuperberg-pair
    cells, minimizing the group's exact finite-N band length (spec § 4).
    Single-cell menus come first: they are cheap, set the pruning baseline, and
    win ties (rectangle case)."""
    rep = group[0]
    rotset = _layout_rotations(grain_mode, fabric_grain_deg, rep.grainline_direction_deg)
    if len(rotset) == 1:
        menus = [[rotset[0]]]
    elif len(rotset) == 2:
        menus = [[rotset[0]], [rotset[0], rotset[1]]]
    else:  # no grainline data -> cardinals (spec § 4.1)
        menus = [[0.0], [90.0], [0.0, 180.0], [90.0, 270.0]]

    best: tuple[float, _Cell, float, float, float, int] | None = None
    for menu in menus:
        if len(menu) == 1:
            cells = [_make_cell(rep, [menu[0]], [(0.0, 0.0)])]
        else:
            cells = [
                _make_cell(rep, [menu[0], menu[1]], [(0.0, 0.0), d])
                for nfp in _get_or_compute_nfp(cache, rep, menu[0], rep, menu[1])
                for d in _pair_offset_candidates(nfp)
            ]
        cells.sort(key=lambda c: c.y_extent)
        for cell in cells:
            if best is not None and cell.y_extent >= best[0] - _EPS:
                break               # sorted ascending: no later cell can win
            if cell.x_extent > fabric_width_mm + _EPS:
                continue
            F = _forbidden_set(rep, cell, cache)
            if F.is_empty:
                continue
            w0 = _exit_along_x(F)
            if w0 < _MIN_PERIOD:
                continue
            for si in range(STAGGER_SAMPLES):
                sx = si * w0 / STAGGER_SAMPLES
                h1 = _v1_height(F, w0, sx)
                if h1 is None:
                    continue
                plan = _band_plan(cell, w0, sx, h1, len(group), fabric_width_mm)
                if plan is None:
                    continue
                k, _rows, band_len = plan
                if best is None or band_len < best[0] - _EPS:
                    best = (band_len, cell, w0, sx, h1, k)
    if best is None:
        return None
    _band_len, cell, w0, sx, h1, k = best
    assembled = _assemble_band(group, cell, w0, sx, h1, k, fabric_width_mm)
    if assembled is None:
        return None
    placements, length = assembled
    return _Band(placements, length, rep.area)


def lattice_layout(pieces: list[Piece], fabric_width_mm: float, grain_mode: str,
                   fabric_grain_deg: float,
                   ladder_log: list[tuple[str, str]] | None = None,
                   ) -> tuple[list[Placement], float, float]:
    """Arm A: per-shape-group Kuperberg-pair lattice bands with per-group BLF
    fallback, stacked + settled. Deterministic."""
    return _layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
                   [("lattice", _build_lattice_band), ("blf", _build_blf_band)],
                   ladder_log)
