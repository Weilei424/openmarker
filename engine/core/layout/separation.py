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
