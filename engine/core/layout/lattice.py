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
