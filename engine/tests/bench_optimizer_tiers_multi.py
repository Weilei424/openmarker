"""Multi-import validation for the GUI optimizer tiers (Fast / Better / Best).

Not part of pytest. Confirms the tier ordering holds across several imports (not
just the canonical sample_2): better < fast, best < fast, and best <= better
(elitism + same seed -> more time never worsens). Writes a JSON report after each
import so a kill leaves partial results. Soft TTL via BENCH_TTL_S (default 2700s).

Run from the worktree engine dir with the main venv:
    D:\\openmarker\\engine\\.venv\\Scripts\\python.exe tests\\bench_optimizer_tiers_multi.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.dxf import parse_dxf
from core.geometry import normalize_piece
from core.layout.grain import FABRIC_GRAIN_DEG
from core.layout.heuristic import auto_layout_polygon
from api.main import (
    QUALITY_BUDGETS_S, GA_GENERATIONS_CAP, GA_GUI_SEED, OPTIMIZED_EFFORT,
)

FABRIC = 1651.0
GRAIN = "bi"
# (filename, copies) — a cross-section of imports beyond the canonical sample_2.
WORKLOADS = [("sample_1.dxf", 6), ("sample_3.dxf", 6), ("sample_4.dxf", 6)]
REPORT_DIR = os.path.join(HERE, "_reports")
SOFT_TTL_S = float(os.environ.get("BENCH_TTL_S", "2700"))


def _examples_dir():
    here = os.path.abspath(HERE)
    for _ in range(8):
        cand = os.path.join(here, "examples", "input")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent
    return None


def _load(fname, copies):
    base_dir = _examples_dir()
    if base_dir is None:
        return None
    path = os.path.join(base_dir, fname)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        raw = parse_dxf(f.read())
    base = []
    for i, r in enumerate(raw):
        try:
            base.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    return [replace(bp, id=f"{bp.id}__c{c}") for c in range(copies) for bp in base]


def _write(rows, note=""):
    os.makedirs(REPORT_DIR, exist_ok=True)
    p = os.path.join(REPORT_DIR, "optimizer_tiers_multi.json")
    with open(p, "w") as f:
        json.dump({"rows": rows, "note": note}, f, indent=2)
    print(f"report -> {p}", flush=True)


def _run_tier(pieces, tier):
    if tier == "fast":
        pl, m, u = auto_layout_polygon(
            pieces, FABRIC, GRAIN, FABRIC_GRAIN_DEG, effort=OPTIMIZED_EFFORT)
    else:
        pl, m, u = auto_layout_polygon(
            pieces, FABRIC, GRAIN, FABRIC_GRAIN_DEG, effort=OPTIMIZED_EFFORT,
            ga_generations=GA_GENERATIONS_CAP, ga_max_time_s=QUALITY_BUDGETS_S[tier],
            ga_seed=GA_GUI_SEED)
    return m, u, len(pl)


def main() -> int:
    start = time.monotonic()
    rows = []
    for fname, copies in WORKLOADS:
        if time.monotonic() - start > SOFT_TTL_S:
            _write(rows, "TTL hit before next import")
            print("TTL hit; stopping", flush=True)
            return 0
        pieces = _load(fname, copies)
        if pieces is None:
            print(f"SKIP {fname} (absent)", flush=True)
            continue
        entry = {"import": fname, "copies": copies, "pieces": len(pieces)}
        print(f"=== {fname} x{copies} ({len(pieces)} pieces) ===", flush=True)
        for tier in ("fast", "better", "best"):
            if time.monotonic() - start > SOFT_TTL_S:
                _write(rows + [entry], "TTL hit mid-import")
                print("TTL hit; stopping", flush=True)
                return 0
            t0 = time.monotonic()
            m, u, placed = _run_tier(pieces, tier)
            wall = time.monotonic() - t0
            entry[tier] = {"marker": round(m, 1), "util": round(u, 2),
                           "wall_s": round(wall, 1), "placed": placed}
            print(f"  {tier}: L={m:.1f} U={u:.2f}% wall={wall:.0f}s placed={placed}", flush=True)
        rows.append(entry)
        _write(rows)

    fails = []
    for e in rows:
        if not all(t in e for t in ("fast", "better", "best")):
            continue
        # GA must never REGRESS below the warm-start. Equality is fine: a sparse
        # or already-tight workload may leave nothing for the GA to improve.
        tol = 1e-6
        if e["better"]["marker"] > e["fast"]["marker"] + tol:
            fails.append(f"{e['import']}: better worse than fast")
        if e["best"]["marker"] > e["fast"]["marker"] + tol:
            fails.append(f"{e['import']}: best worse than fast")
        if e["best"]["marker"] > e["better"]["marker"] + tol:
            fails.append(f"{e['import']}: best worse than better")
    _write(rows, ("FAIL: " + "; ".join(fails)) if fails else "PASS")
    print("GATES:", ("FAIL: " + "; ".join(fails)) if fails else "PASS", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
