"""Budget-validation bench for the GUI optimizer tiers (Better / Best).

Not part of pytest. Run from the worktree engine dir with the main venv:
    D:\\openmarker\\engine\\.venv\\Scripts\\python.exe tests\\bench_optimizer_tiers.py

Confirms api.main.QUALITY_BUDGETS_S on the canonical workload: Best must beat the
bar (11699mm); Better must beat it within its shorter budget. Writes a JSON report
to engine/tests/_reports/ after each tier so a kill still leaves partial results.
Soft TTL via BENCH_TTL_S env (default 1500s).
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.layout.grain import FABRIC_GRAIN_DEG
from core.layout.heuristic import auto_layout_polygon
from bench_ga import _load_workload, FABRIC, BAR
from api.main import (
    QUALITY_BUDGETS_S, GA_GENERATIONS_CAP, GA_GUI_SEED, OPTIMIZED_EFFORT,
)

REPORT_DIR = os.path.join(HERE, "_reports")
SOFT_TTL_S = float(os.environ.get("BENCH_TTL_S", "1500"))


def _write_report(rows, note=""):
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "optimizer_tiers.json")
    with open(path, "w") as f:
        json.dump({"bar": BAR, "rows": rows, "note": note}, f, indent=2)
    print(f"report -> {path}", flush=True)


def main() -> int:
    pieces = _load_workload()  # SKIPs (exit 0) if the fixture is absent
    print(f"workload: {len(pieces)} pieces; budgets={QUALITY_BUDGETS_S}", flush=True)
    start = time.monotonic()
    rows = []

    base = auto_layout_polygon(pieces, FABRIC, "bi", FABRIC_GRAIN_DEG,
                               effort=OPTIMIZED_EFFORT)
    rows.append({"tier": "fast", "marker": round(base[1], 1), "util": round(base[2], 2)})
    print(f"fast (warm-start): L={base[1]:.1f} U={base[2]:.2f}%", flush=True)
    _write_report(rows, "warm-start only so far")

    for tier in ("better", "best"):
        if time.monotonic() - start > SOFT_TTL_S:
            _write_report(rows, f"TTL hit before {tier}")
            print(f"TTL hit; stopping before {tier}", flush=True)
            return 0
        budget = QUALITY_BUDGETS_S[tier]
        t0 = time.monotonic()
        pl, marker, util = auto_layout_polygon(
            pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, effort=OPTIMIZED_EFFORT,
            ga_generations=GA_GENERATIONS_CAP, ga_max_time_s=budget, ga_seed=GA_GUI_SEED,
        )
        wall = time.monotonic() - t0
        rows.append({"tier": tier, "budget_s": budget, "marker": round(marker, 1),
                     "util": round(util, 2), "wall_s": round(wall, 1), "placed": len(pl)})
        print(f"{tier} budget={budget}s: L={marker:.1f} U={util:.2f}% "
              f"wall={wall:.0f}s placed={len(pl)}", flush=True)
        _write_report(rows)

    best_row = next(r for r in rows if r["tier"] == "best")
    better_row = next(r for r in rows if r["tier"] == "better")
    failures = []
    if best_row["marker"] > BAR:
        failures.append(f"BEST {best_row['marker']:.1f} did not beat bar {BAR}")
    if better_row["marker"] >= BAR:
        failures.append(f"BETTER {better_row['marker']:.1f} did not beat bar {BAR}")
    _write_report(rows, ("FAIL: " + "; ".join(failures)) if failures else "PASS")
    print("GATES:", ("FAIL: " + "; ".join(failures)) if failures else "PASS", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
