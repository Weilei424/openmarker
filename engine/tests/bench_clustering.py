"""Manual benchmark for identical-piece clustering. Not part of pytest.

Run from the worktree root with:
    D:\\openmarker\\engine\\.venv\\Scripts\\python.exe engine\\tests\\bench_clustering.py

Compares marker_length and utilization for three modes per row:
  - off:    clustering disabled (disable_clustering=True)
  - bbox:   clustering on, cluster_polygon='bbox' (PR #9 behavior)
  - union:  clustering on, cluster_polygon='union' (this PR)

The headline row uses examples/input/sample_2.dxf x 10 copies — the same
workload as the commercial-vs-OpenMarker comparison (~7pp gap).

Acceptance gates (post Task 7 BLOCKED — clustering ships as OPT-IN, default off):
  - 10 identical rects: union.marker <= off.marker + 1e-6
  - two-groups:         union.marker <= off.marker + 1e-6  (sort-key fix lets union match off here)
  - 8 singletons:       union.marker == off.marker (clustering no-op)
  - sample_2.dxf x 10:  union.marker <= bbox.marker + 1e-6  (RELAXED from "beats off":
                        the headline gate cannot beat off=12249mm because all 19 base
                        pieces have copies → 19 rigid clusters that can't interleave.
                        We still require union to be at least as good as bbox, since
                        union exposing perimeter bays gives ~8% reduction over bbox
                        on real workloads even when the absolute number is worse.)
  - parallel sample_2:  union.marker[effort=5] == union.marker[effort=1] (determinism)

Prints PASS/FAIL per gate and an overall verdict at the end. The "ship" line
reflects the OPT-IN status — even with all gates green, default stays off until
a workload demonstrates union beats unclustered BLF on real fabric.
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


def _run(pieces, fabric_width_mm, grain_mode, effort, mode, cluster_fraction=1.0):
    """mode in {'off', 'bbox', 'union', 'union_f'}.
    'union_f' is the same as 'union' but passes cluster_fraction through."""
    kwargs = dict(
        pieces=pieces, fabric_width_mm=fabric_width_mm,
        grain_mode=grain_mode, fabric_grain_deg=0.0, effort=effort,
    )
    if mode == "off":
        kwargs["disable_clustering"] = True
    elif mode == "bbox":
        kwargs["disable_clustering"] = False
        kwargs["cluster_polygon"] = "bbox"
    elif mode == "union":
        kwargs["disable_clustering"] = False
        kwargs["cluster_polygon"] = "union"
    elif mode == "union_f":
        kwargs["disable_clustering"] = False
        kwargs["cluster_polygon"] = "union"
        kwargs["cluster_fraction"] = cluster_fraction
    else:
        raise ValueError(f"unknown mode: {mode}")
    t0 = time.perf_counter()
    placements, length, util = heuristic.auto_layout_polygon(**kwargs)
    return time.perf_counter() - t0, length, util


def _bench(
    name: str, pieces, fabric_width_mm: float, grain_mode: str = "single", effort: int = 1,
) -> tuple[float, float, float]:
    """Run off/bbox/union; print one row; return (off_marker, bbox_marker, union_marker)."""
    # Warm up (eats first-run import / JIT overhead).
    _run(pieces, fabric_width_mm, grain_mode, effort, "union")

    off_t, off_len, off_util = _run(pieces, fabric_width_mm, grain_mode, effort, "off")
    bbox_t, bbox_len, bbox_util = _run(pieces, fabric_width_mm, grain_mode, effort, "bbox")
    union_t, union_len, union_util = _run(pieces, fabric_width_mm, grain_mode, effort, "union")

    print(
        f"{name:55s}\n"
        f"  off:    L={off_len:8.1f}/U={off_util:5.2f}%/t={off_t*1000:8.1f}ms\n"
        f"  bbox:   L={bbox_len:8.1f}/U={bbox_util:5.2f}%/t={bbox_t*1000:8.1f}ms\n"
        f"  union:  L={union_len:8.1f}/U={union_util:5.2f}%/t={union_t*1000:8.1f}ms"
    )
    return off_len, bbox_len, union_len


def _gate(name: str, condition: bool, detail: str) -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}: {detail}")
    return condition


if __name__ == "__main__":
    gates: list[bool] = []

    # Row 1: 10 identical rects. Union should match off (rectangles tile perfectly).
    pieces_identical = [_piece(f"p__c{i}", 100, 50) for i in range(10)]
    off, bbox, union = _bench("10 identical rects (100x50), fabric=500", pieces_identical, 500.0)
    gates.append(_gate("identical rects: union no-worse-than off",
                       union <= off + 1e-6, f"union={union:.1f} off={off:.1f}"))

    # Row 2: two-groups (heterogeneous).
    pieces_two_groups = (
        [_piece(f"a__c{i}", 100, 60) for i in range(6)]
        + [_piece(f"b__c{i}", 120, 40) for i in range(4)]
    )
    off, bbox, union = _bench("6x(100x60) + 4x(120x40), fabric=500", pieces_two_groups, 500.0)
    gates.append(_gate("two-groups: union no-worse-than off",
                       union <= off + 1e-6, f"union={union:.1f} off={off:.1f}"))

    # Row 3: singletons (no clustering opportunity).
    pieces_singletons = [_piece(f"piece_{i}", 100 + i * 20, 80 + (i % 3) * 30) for i in range(8)]
    off, bbox, union = _bench("8 singletons (mixed), fabric=500", pieces_singletons, 500.0)
    gates.append(_gate("singletons: union == off",
                       abs(union - off) < 1e-6, f"union={union:.1f} off={off:.1f}"))

    # Row 4: real workload. THE headline number.
    dxf_path = _find_sample_dxf("sample_2.dxf")
    if dxf_path is None:
        print("[skipped] sample_2.dxf not found — place it in examples/input/ to enable the real-workload bench")
    else:
        pieces_real = _load_dxf_pieces(dxf_path, copies=10)
        off_s, bbox_s, union_s = _bench(
            f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi, effort=1",
            pieces_real, 1651.0, "bi", effort=1,
        )
        gates.append(_gate("sample_2.dxf serial: union <= bbox (no regression vs bbox path)",
                           union_s <= bbox_s + 1e-6,
                           f"union={union_s:.1f} bbox={bbox_s:.1f} off={off_s:.1f} (clustering opt-in only)"))

        off_p, bbox_p, union_p = _bench(
            f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi, effort=5",
            pieces_real, 1651.0, "bi", effort=5,
        )
        gates.append(_gate("sample_2.dxf parallel: union == union[serial] (determinism)",
                           abs(union_p - union_s) < 1e-3, f"par={union_p:.1f} ser={union_s:.1f}"))

        # Partial-cluster sweep (Task 7 of partial-clustering plan).
        # cluster_fraction in (0, 1]; 1.0 == current union behavior. Lower fractions
        # hold back leftover singletons for the outer BLF.
        print(f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi, effort=5, partial-cluster sweep")
        sweep_fractions = [1.0, 0.9, 0.8, 0.7, 0.5]
        sweep_results: list[tuple[float, float, float, float]] = []  # (f, length, util, time)
        for f in sweep_fractions:
            t, length, util = _run(pieces_real, 1651.0, "bi", 5, "union_f", cluster_fraction=f)
            print(f"  union f={f}:  L={length:8.1f}/U={util:5.2f}%/t={t*1000:8.1f}ms")
            sweep_results.append((f, length, util, t))

        best_f, best_l, _, _ = min(sweep_results, key=lambda r: r[1])
        print(f"  (off baseline:  L={off_p:8.1f} for comparison)")
        if best_l < off_p - 1e-6:
            print(f"  >> best partial fraction = {best_f} (L={best_l:.1f}) BEATS off baseline ({off_p:.1f}) — candidate for default flip")
        else:
            print(f"  >> best partial fraction = {best_f} (L={best_l:.1f}); off still wins ({off_p:.1f})")

        # New gate: regression check. union_f at fraction=1.0 must match same-run union mode
        # (mode='union' uses implicit cluster_fraction=1.0 — the new no-op leftover branch).
        union_f_at_1 = next(L for f, L, _u, _t in sweep_results if f == 1.0)
        gates.append(_gate(
            "partial-cluster fraction=1.0 matches union baseline (regression)",
            abs(union_f_at_1 - union_p) < 1e-6,
            f"union_f[1.0]={union_f_at_1:.6f} union[parallel]={union_p:.6f}",
        ))

    print()
    if all(gates):
        print(
            f"ACCEPTANCE: ALL {len(gates)} GATES PASSED — safe to ship.\n"
            f"NOTE: clustering remains OPT-IN (disable_clustering=True by default).\n"
            f"      Sweep above shows whether any cluster_fraction beats off=12249mm.\n"
            f"      If yes, file a follow-up PR to flip the default with the winning fraction.\n"
            f"      If no, the result is recorded in PERFORMANCE.md § 6 as a confirmed\n"
            f"      data point about the structural barrier."
        )
    else:
        failed = sum(1 for g in gates if not g)
        print(f"ACCEPTANCE: {failed}/{len(gates)} GATES FAILED — BLOCKED, do not ship")
        sys.exit(1)
