"""Manual benchmark for identical-piece clustering. Not part of pytest.

Run from the worktree root with:
    D:\\openmarker\\engine\\.venv\\Scripts\\python.exe engine\\tests\\bench_clustering.py

Compares marker_length and utilization (clustering on vs off) on a few
scenarios. The headline row uses examples/input/sample_2.dxf x 10 copies —
the same workload as the commercial-vs-OpenMarker comparison (~7pp gap).
"""
from __future__ import annotations

import dataclasses
import os
import sys
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.models.piece import Piece, BoundingBox
from core.layout import heuristic


def _piece(piece_id: str, w: float, h: float, grainline: float | None = None) -> Piece:
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        validation_notes=[],
        grainline_direction_deg=grainline,
    )


def _find_sample_dxf(filename: str) -> str | None:
    here = os.path.abspath(HERE)
    for _ in range(8):
        candidate = os.path.join(here, "examples", "input", filename)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent
    return None


def _load_dxf_pieces(path: str, copies: int) -> list[Piece]:
    from core.dxf import parse_dxf
    from core.geometry import normalize_piece
    with open(path, "rb") as f:
        raw = parse_dxf(f.read())
    base_pieces: list[Piece] = []
    for i, r in enumerate(raw):
        try:
            base_pieces.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    expanded: list[Piece] = []
    for c in range(copies):
        for p in base_pieces:
            expanded.append(dataclasses.replace(p, id=f"{p.id}__c{c}"))
    return expanded


def _run(pieces, fabric_width_mm, grain_mode, effort, disable_clustering):
    t0 = time.perf_counter()
    placements, length, util = heuristic.auto_layout_polygon(
        pieces, fabric_width_mm=fabric_width_mm,
        grain_mode=grain_mode, fabric_grain_deg=0.0, effort=effort,
        disable_clustering=disable_clustering,
    )
    return time.perf_counter() - t0, length, util


def _bench(name: str, pieces, fabric_width_mm: float, grain_mode: str = "single", effort: int = 1) -> None:
    # Warmup pass — eats import/JIT overhead.
    _run(pieces, fabric_width_mm, grain_mode, effort, disable_clustering=False)

    on_t, on_len, on_util = _run(pieces, fabric_width_mm, grain_mode, effort, disable_clustering=False)
    off_t, off_len, off_util = _run(pieces, fabric_width_mm, grain_mode, effort, disable_clustering=True)

    speedup = off_t / on_t if on_t > 0 else float("inf")
    length_change = (off_len - on_len) / off_len * 100 if off_len > 0 else 0.0
    util_change = on_util - off_util
    regression = on_len > off_len + 1e-6
    status = "REGRESSED" if regression else "OK"
    print(
        f"{name:55s} on=L{on_len:8.1f}/U{on_util:5.2f}%/{on_t*1000:7.1f}ms  "
        f"off=L{off_len:8.1f}/U{off_util:5.2f}%/{off_t*1000:7.1f}ms  "
        f"Δlen={-length_change:+5.2f}%  Δutil={util_change:+5.2f}pp  [{status}]"
    )


if __name__ == "__main__":
    # All-identical rects — clustering's ideal case (no diversity to interleave).
    pieces_identical = [_piece(f"p__c{i}", 100, 50) for i in range(10)]
    _bench("10 identical rects (100x50), fabric=500", pieces_identical, 500.0)

    # Two groups: 6 copies of one + 4 copies of another.
    pieces_two_groups = (
        [_piece(f"a__c{i}", 100, 60) for i in range(6)]
        + [_piece(f"b__c{i}", 120, 40) for i in range(4)]
    )
    _bench("6×(100x60) + 4×(120x40), fabric=500", pieces_two_groups, 500.0)

    # All singletons — clustering should be a no-op.
    pieces_singletons = [_piece(f"piece_{i}", 100 + i * 20, 80 + (i % 3) * 30) for i in range(8)]
    _bench("8 singletons (mixed), fabric=500", pieces_singletons, 500.0)

    # Real workload: sample_2.dxf × 10 copies. THE headline number.
    dxf_path = _find_sample_dxf("sample_2.dxf")
    if dxf_path is None:
        print("[skipped] sample_2.dxf not found — place it in examples/input/ to enable the real-workload bench")
    else:
        pieces_real = _load_dxf_pieces(dxf_path, copies=10)
        _bench(
            f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi",
            pieces_real, 1500.0, "bi",
        )
        # Also at effort=5 to compare against PR #8's parallel baseline.
        _bench(
            f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi [par]",
            pieces_real, 1500.0, "bi", effort=5,
        )
