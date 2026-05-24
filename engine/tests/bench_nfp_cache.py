"""Manual benchmark for the Phase 6 NFP cache. Not part of pytest.

Run from the worktree root with:
    engine\\.venv\\Scripts\\python engine\\tests\\bench_nfp_cache.py

Prints (cached, uncached, speedup) for a few representative inputs.
"""
from __future__ import annotations

import os
import sys
import time

# Path setup so this script works the same way as the integration tests.
HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.models.piece import Piece, BoundingBox
from core.layout import heuristic


def _piece(piece_id: str, w: float, h: float, grainline: float | None = None) -> Piece:
    """Convex rect — a stand-in for "any piece"."""
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        validation_notes=[],
        grainline_direction_deg=grainline,
    )


def _complex_piece(piece_id: str, scale: float, grainline: float | None = None) -> Piece:
    """16-vertex irregular convex-ish shape — closer to real garment piece cost."""
    import math
    n = 16
    polygon = []
    for i in range(n):
        theta = (i / n) * 2 * math.pi
        # Wobble the radius for an irregular outline.
        r = scale * (1.0 + 0.25 * math.sin(3 * theta))
        polygon.append((r * math.cos(theta) + scale, r * math.sin(theta) + scale))
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
    # Approx area (shoelace).
    area = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    area = abs(area) / 2.0
    return Piece(
        id=piece_id, name=piece_id,
        polygon=polygon, area=area,
        bbox=BoundingBox(minx, miny, maxx, maxy, maxx - minx, maxy - miny),
        is_valid=True, validation_notes=[],
        grainline_direction_deg=grainline,
    )


def _expand(base_pieces: list[Piece], copies: int) -> list[Piece]:
    """Mirror App.tsx: append '__c{n}' suffix for each copy."""
    out: list[Piece] = []
    for c in range(copies):
        for p in base_pieces:
            out.append(Piece(
                id=f"{p.id}__c{c}", name=p.name,
                polygon=p.polygon, area=p.area, bbox=p.bbox,
                is_valid=p.is_valid, validation_notes=p.validation_notes,
                grainline_direction_deg=p.grainline_direction_deg,
            ))
    return out


def _time_once(pieces: list[Piece], fabric: float, grain: str) -> tuple[float, float]:
    """Run auto_layout_polygon once with the shared cache (current behavior),
    then again with a fresh cache per strategy (simulating no cache)."""
    # Cached: current production path.
    t0 = time.perf_counter()
    heuristic.auto_layout_polygon(pieces, fabric, grain, 90.0)
    cached_s = time.perf_counter() - t0

    # Uncached: monkey-patch _blf_pack_nfp to force a fresh cache per call.
    orig = heuristic._blf_pack_nfp
    def no_cache(*args, **kwargs):
        kwargs["nfp_cache"] = {}
        return orig(*args, **kwargs)
    heuristic._blf_pack_nfp = no_cache
    try:
        t0 = time.perf_counter()
        heuristic.auto_layout_polygon(pieces, fabric, grain, 90.0)
        uncached_s = time.perf_counter() - t0
    finally:
        heuristic._blf_pack_nfp = orig

    return cached_s, uncached_s


def main() -> None:
    scenarios = [
        # (label, base_pieces, copies, fabric_width, grain_mode)
        ("rects: 3 × 1, single  ", [_piece(f"p{i}", 200 + 30 * i, 150 + 20 * i) for i in range(3)], 1, 1500, "single"),
        ("rects: 3 × 4, single  ", [_piece(f"p{i}", 200 + 30 * i, 150 + 20 * i) for i in range(3)], 4, 1500, "single"),
        ("rects: 5 × 4, single  ", [_piece(f"p{i}", 150 + 20 * i, 120 + 15 * i) for i in range(5)], 4, 1500, "single"),
        ("rects: 3 × 4, bi      ", [_piece(f"p{i}", 200 + 30 * i, 150 + 20 * i) for i in range(3)], 4, 1500, "bi"),
        ("16-vert: 3 × 1, single", [_complex_piece(f"q{i}", 80 + 20 * i) for i in range(3)], 1, 1500, "single"),
        ("16-vert: 3 × 4, single", [_complex_piece(f"q{i}", 80 + 20 * i) for i in range(3)], 4, 1500, "single"),
        ("16-vert: 3 × 4, bi    ", [_complex_piece(f"q{i}", 80 + 20 * i) for i in range(3)], 4, 1500, "bi"),
    ]

    print(f"{'scenario':<32}  {'cached':>9}  {'uncached':>9}  speedup")
    print("-" * 72)
    for label, base, copies, fabric, grain in scenarios:
        pieces = _expand(base, copies)
        # Discard the first iteration (JIT/cache warmup) by running once and ignoring.
        _time_once(pieces, fabric, grain)
        cached, uncached = _time_once(pieces, fabric, grain)
        speedup = uncached / cached if cached > 0 else float("inf")
        print(f"{label:<32}  {cached*1000:>7.1f}ms  {uncached*1000:>7.1f}ms  {speedup:>5.2f}x")


if __name__ == "__main__":
    main()
