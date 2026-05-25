"""Manual benchmark for the BLF branch-pruning change. Not part of pytest.

Run from the worktree root with:
    engine\\.venv\\Scripts\\python engine\\tests\\bench_branch_pruning.py

Prints (pruning-on, pruning-off, speedup) for a few representative inputs.
The real-workload row uses examples/input/sample_2.dxf if available — the
same fixture compared against commercial nesting software (~7pp utilization
gap on the 10-copies workload). Synthetic rows still run if the DXF is
missing.
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
    """Walk up from this script looking for examples/input/<filename>.
    Returns absolute path or None if not found. The file is git-ignored,
    so it only exists in the user's main repo, not in worktree copies."""
    here = os.path.abspath(HERE)
    for _ in range(8):  # generous depth limit
        candidate = os.path.join(here, "examples", "input", filename)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent
    return None


def _load_dxf_pieces(path: str, copies: int) -> list[Piece]:
    """Parse + normalize a DXF the same way the /import-dxf endpoint does,
    then expand each piece to `copies` instances (id suffix __c{n})."""
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
    for p in base_pieces:
        for c in range(copies):
            expanded.append(dataclasses.replace(p, id=f"{p.id}__c{c}"))
    return expanded


def _run(pieces, fabric_width_mm, grain_mode):
    t0 = time.perf_counter()
    result = heuristic.auto_layout_polygon(
        pieces, fabric_width_mm=fabric_width_mm,
        grain_mode=grain_mode, fabric_grain_deg=0.0, effort=1,
    )
    return time.perf_counter() - t0, result[1]  # (seconds, marker_length)


def _bench(name: str, pieces, fabric_width_mm: float, grain_mode: str = "single") -> None:
    on_t, on_len = _run(pieces, fabric_width_mm, grain_mode)

    original = heuristic._blf_pack_nfp
    def no_prune(*args, **kwargs):
        kwargs.pop("best_marker_so_far", None)
        return original(*args, **kwargs)
    heuristic._blf_pack_nfp = no_prune
    try:
        off_t, off_len = _run(pieces, fabric_width_mm, grain_mode)
    finally:
        heuristic._blf_pack_nfp = original

    speedup = off_t / on_t if on_t > 0 else float("inf")
    same = "same" if abs(on_len - off_len) < 1e-6 else f"DIFFER on={on_len:.2f} off={off_len:.2f}"
    print(f"{name:50s} on={on_t*1000:8.1f}ms  off={off_t*1000:8.1f}ms  speedup={speedup:5.2f}x  result={same}")


if __name__ == "__main__":
    # Many small same-size rects on a narrow strip — sort strategies should
    # diverge in quality, so pruning has real wins.
    pieces_small = [_piece(f"s{i}", 80, 60) for i in range(20)]
    _bench("20 small rects (80x60), fabric=300", pieces_small, 300.0)

    # Mixed sizes — area, max-dim, height, width sorts produce different orders.
    pieces_mixed = [_piece(f"m{i}", 100 + i * 20, 80 + (i % 3) * 40) for i in range(8)]
    _bench("8 mixed rects, fabric=400", pieces_mixed, 400.0)

    # Bi mode — exercises both `bi` and the `single` fallback. Single should
    # prune early once bi establishes a tight cutoff (or vice versa).
    pieces_bi = [_piece(f"b{i}", 100, 200 if i % 2 else 80, grainline=0.0) for i in range(8)]
    _bench("8 mixed rects, bi grain, fabric=400", pieces_bi, 400.0, "bi")

    # Real workload: same fixture as the commercial-vs-ours comparison.
    dxf_path = _find_sample_dxf("sample_2.dxf")
    if dxf_path is None:
        print("[skipped] sample_2.dxf not found — place it in examples/input/ to enable the real-workload bench")
    else:
        pieces_real = _load_dxf_pieces(dxf_path, copies=10)
        _bench(f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), fabric=1500, bi", pieces_real, 1500.0, "bi")
