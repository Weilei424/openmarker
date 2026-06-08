"""Separation nesting engine — the "Ultra" quality tier.

Converts pieces to grain-aligned jagua-rs JSON, shells out to the bundled
`sparrow` binary (overlap-and-separate strip nester), then reconstructs and
validates the result into engine Placements. See
docs/superpowers/specs/2026-06-07-separation-engine-phase2-design.md and
docs/superpowers/notes/2026-06-07-jagua-schema.md (axis map).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass

import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon

from core.models.piece import Piece
from core.layout.cancellation import CancellationError, is_cancelled
from core.layout.clustering import group_pieces_by_base_id
from core.layout.heuristic import (
    EDGE_GAP,
    Placement,
    _compute_metrics,
    _has_area_overlap,
    _layout_rotations,
    _placed_polygon,
    _polygon_dims,
)

_VENDORED = os.path.join(os.path.dirname(__file__), "..", "..", "vendor", "sparrow", "sparrow.exe")


def _resolve_sparrow_path() -> str:
    """Locate the bundled sparrow binary. Search order:
    1. OPENMARKER_SPARROW_PATH env override
    2. vendored engine/vendor/sparrow/sparrow.exe (committed, offline)
    3. PyInstaller bundle dir (sys._MEIPASS — future packaging)
    4. dev build tools/sparrow/target/release/sparrow.exe (walk up to repo root)
    """
    candidates: list[str] = []
    env = os.environ.get("OPENMARKER_SPARROW_PATH")
    if env:
        candidates.append(env)
    candidates.append(os.path.abspath(_VENDORED))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "vendor", "sparrow", "sparrow.exe"))
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidates.append(os.path.join(here, "tools", "sparrow", "target", "release", "sparrow.exe"))
        here = os.path.dirname(here)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "sparrow binary not found. Set OPENMARKER_SPARROW_PATH, or vendor it at "
        "engine/vendor/sparrow/sparrow.exe (see the Phase 2 spec §10)."
    )


@dataclass
class _SepItem:
    index: int
    piece_ids: list[str]         # expanded "__cN" ids, in placement-assignment order
    base_angle: float            # engine pre-rotation reference (engine_set[0])
    emitted: ShapelyPolygon      # grain-aligned + 90deg axis-mapped, origin-normalized
    allowed_offsets: list[float] # jagua allowed_orientations = engine_set - base_angle


def _emit_shape(piece: Piece, base_angle: float) -> ShapelyPolygon:
    """Grain-align (base) + 90deg axis swap; origin-normalize bbox-min -> (0,0)."""
    poly = shapely.affinity.rotate(
        ShapelyPolygon(piece.polygon), base_angle + 90.0, origin=(0, 0), use_radians=False)
    minx, miny = poly.bounds[0], poly.bounds[1]
    return shapely.affinity.translate(poly, xoff=-minx, yoff=-miny)


def _group_to_items(pieces: list[Piece], grain_mode: str, fabric_grain_deg: float) -> list[_SepItem]:
    """Collapse expanded pieces to base groups and build one jagua item per group.

    allowed_offsets follows the grain table (single -> [0]; bi -> [0,180];
    no-grainline -> [0,90,180,270]) by re-expressing _layout_rotations relative
    to base_angle. base_angle (= engine_set[0]) is folded into the final rotation
    on reconstruction, so net engine rotation lands exactly in the engine set.
    """
    groups = group_pieces_by_base_id(pieces)
    items: list[_SepItem] = []
    for index, members in enumerate(groups.values()):
        rep = members[0]
        engine_set = _layout_rotations(grain_mode, fabric_grain_deg, rep.grainline_direction_deg)
        base = engine_set[0]
        items.append(_SepItem(
            index=index,
            piece_ids=[p.id for p in members],
            base_angle=base,
            emitted=_emit_shape(rep, base),
            allowed_offsets=[round((a - base) % 360.0, 6) for a in engine_set],
        ))
    return items


def _instance_json(items: list[_SepItem], strip_height: float, name: str = "openmarker") -> dict:
    return {
        "name": name,
        "strip_height": float(strip_height),
        "items": [
            {
                "id": it.index,
                "demand": len(it.piece_ids),
                "allowed_orientations": [float(o) for o in it.allowed_offsets],
                "shape": {
                    "type": "simple_polygon",
                    "data": [[float(x), float(y)] for x, y in it.emitted.exterior.coords[:-1]],
                },
            }
            for it in items
        ],
    }


def _reconstruct(solution: dict, items: list[_SepItem], fabric_width_mm: float) -> list[Placement]:
    """Invert the axis map and build engine Placements.

    For each placed copy: rebuild its jagua-frame polygon (rotate emitted by r,
    translate by t), rotate the WHOLE layout by -90deg (axis-swap inverse), then
    shift bbox-min -> (EDGE_GAP, EDGE_GAP). rotation_deg = (base + r) lands exactly
    in the engine grain set; (x, y) = rotated-bbox-min so the existing
    _placed_polygon reproduces the polygon for metrics/validation/render.
    """
    by_index = {it.index: it for it in items}
    counters: dict[int, int] = {it.index: 0 for it in items}
    raw: list[tuple[str, float, ShapelyPolygon]] = []  # (piece_id, rotation_deg, engine_poly)
    for pi in solution["solution"]["layout"]["placed_items"]:
        it = by_index[pi["item_id"]]
        r = float(pi["transformation"]["rotation"]) % 360.0
        t = pi["transformation"]["translation"]
        jpoly = shapely.affinity.translate(
            shapely.affinity.rotate(it.emitted, r, origin=(0, 0), use_radians=False),
            xoff=float(t[0]), yoff=float(t[1]))
        epoly = shapely.affinity.rotate(jpoly, -90.0, origin=(0, 0), use_radians=False)
        j = counters[it.index]
        counters[it.index] += 1
        raw.append((it.piece_ids[j], round((it.base_angle + r) % 360.0, 6), epoly))

    if not raw:
        return []
    dx = EDGE_GAP - min(p.bounds[0] for _, _, p in raw)
    dy = EDGE_GAP - min(p.bounds[1] for _, _, p in raw)
    placements: list[Placement] = []
    for piece_id, rotation_deg, epoly in raw:
        shifted = shapely.affinity.translate(epoly, xoff=dx, yoff=dy)
        placements.append(Placement(piece_id, round(shifted.bounds[0], 4),
                                    round(shifted.bounds[1], 4), rotation_deg))
    return placements
