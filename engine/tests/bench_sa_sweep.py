"""Manual SA hyperparameter sweep at grain=90. Not part of pytest.

ALWAYS writes a report (engine/tests/_sweep_report.md) even if stopped by the
soft TTL or interrupted — see the finally block. Per-row results also stream to
engine/tests/_sweep_results.jsonl as they complete, so a hard kill loses at most
the in-flight row.

Run (background):  ...python engine\\tests\\bench_sa_sweep.py
Smoke (fast):      ...python engine\\tests\\bench_sa_sweep.py --smoke
Override TTL:      ...python engine\\tests\\bench_sa_sweep.py --ttl 7200
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.layout.heuristic import auto_layout_polygon
from core.layout.grain import FABRIC_GRAIN_DEG
from core.layout.sa import SAConfig

FABRIC_WIDTH_MM = 1651
GRAIN_MODE = "bi"
COPIES = 10
EFFORT = 5
BAR_MM = 11699.0
SWEEP_TTL_S = 3 * 3600
PER_ROW_CAP_S = 900.0  # per-row sa_max_time_s; bounds a single config so it can't hang past a TTL check
RESULTS_PATH = os.path.join(HERE, "_sweep_results.jsonl")
REPORT_PATH = os.path.join(HERE, "_sweep_report.md")


class _TTLExceeded(Exception):
    pass


def _find_sample_dxf() -> str | None:
    here = os.path.abspath(HERE)
    for _ in range(8):
        candidate = os.path.join(here, "examples", "input", "sample_2.dxf")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent
    return None


def _load_pieces(path: str, copies: int):
    from dataclasses import replace
    from core.dxf import parse_dxf
    from core.geometry import normalize_piece
    with open(path, "rb") as f:
        raw = parse_dxf(f.read())
    base = []
    for i, r in enumerate(raw):
        try:
            base.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    return [replace(bp, id=f"{bp.id}__c{c}") for c in range(copies) for bp in base]


def _rows(smoke: bool):
    """(label, SAConfig, sa_iterations, sa_seed), highest-value first.
    Phase 3 (multi-seed of the best) is appended dynamically in main()."""
    base = SAConfig()
    n = 5 if smoke else 50
    rows = [
        ("baseline sa=0", base, 0, 42),
        ("current-constants", base, n, 42),
    ]
    for t0 in [0.02, 0.1, 0.2]:
        rows.append((f"t0={t0}", dataclasses.replace(base, t0_factor=t0), n, 42))
    for a in [0.90, 0.98]:
        rows.append((f"alpha={a}", dataclasses.replace(base, cooling_alpha=a), n, 42))
    for rw in [0.15, 0.40]:
        rows.append((f"revwin={rw}", dataclasses.replace(base, reverse_window_fraction=rw), n, 42))
    rows.append(("rot-heavy", dataclasses.replace(
        base, move_weights={"swap": 1.0, "reverse": 1.0, "rotation_flip": 3.0}), n, 42))
    rows.append(("order-heavy", dataclasses.replace(
        base, move_weights={"swap": 2.0, "reverse": 2.0, "rotation_flip": 1.0}), n, 42))
    return rows


def _run_row(label, cfg, iters, seed, pieces, started_at, ttl, results):
    if time.perf_counter() - started_at >= ttl:
        raise _TTLExceeded()
    t0 = time.perf_counter()
    max_t = None if iters == 0 else PER_ROW_CAP_S
    _, marker, util = auto_layout_polygon(
        pieces, FABRIC_WIDTH_MM, GRAIN_MODE, FABRIC_GRAIN_DEG, effort=EFFORT,
        sa_iterations=iters, sa_seed=seed, sa_max_time_s=max_t, sa_config=cfg,
    )
    row = {
        "label": label, "seed": seed, "iters": iters,
        "marker": round(marker, 2), "util": round(util, 2),
        "time_s": round(time.perf_counter() - t0, 1),
        "config": dataclasses.asdict(cfg),
    }
    results.append(row)
    with open(RESULTS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
    flag = "  <-- BEATS BAR" if row["marker"] < BAR_MM else ""
    print(f"  {label:18s} seed={seed:<4d} sa={iters:<4d} "
          f"L={row['marker']:9.1f} U={row['util']:5.2f}% t={row['time_s']:6.1f}s{flag}", flush=True)
    return row


def _build_combo(results):
    """Phase 2: from the single-axis screening rows, adopt each axis's
    best-IMPROVING value (one that beat the current-constants baseline)."""
    default = dataclasses.asdict(SAConfig())
    base_rows = [r for r in results if r["config"] == default and r["iters"] > 0]
    baseline = min((r["marker"] for r in base_rows), default=float("inf"))
    adopted = dict(default)
    for key in ["t0_factor", "cooling_alpha", "reverse_window_fraction", "move_weights"]:
        # rows that varied ONLY this key vs the default config
        varied = [r for r in results if r["iters"] > 0
                  and r["config"][key] != default[key]
                  and all(r["config"][k] == default[k] for k in default if k != key)]
        if not varied:
            continue
        best = min(varied, key=lambda r: r["marker"])
        if best["marker"] < baseline:
            adopted[key] = best["config"][key]
    return SAConfig(**adopted)


def _write_report(results, started_at, stopped_reason):
    completed = sorted(results, key=lambda r: r["marker"])
    out = [
        "# SA sweep report", "",
        f"- workload: sample_2.dxf x{COPIES}, fabric={FABRIC_WIDTH_MM}, "
        f"grain={GRAIN_MODE}@{FABRIC_GRAIN_DEG}, effort={EFFORT}",
        f"- bar to beat (strictly <): {BAR_MM:.0f}mm",
        f"- rows completed: {len(results)}",
        f"- elapsed: {time.perf_counter() - started_at:.0f}s",
        f"- stopped: {stopped_reason}", "",
    ]
    if completed:
        best = completed[0]
        out += [
            f"- **best: {best['marker']:.1f}mm / {best['util']:.2f}% "
            f"({best['label']}, seed {best['seed']}, sa={best['iters']})**",
            f"- beats bar? **{'YES' if best['marker'] < BAR_MM else 'no'}**", "",
            "| rank | marker | util | label | seed | sa | t0 | alpha | revwin | move_weights | t(s) |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(completed, 1):
            c = r["config"]
            out.append(
                f"| {i} | {r['marker']:.1f} | {r['util']:.2f} | {r['label']} | {r['seed']} | "
                f"{r['iters']} | {c['t0_factor']} | {c['cooling_alpha']} | "
                f"{c['reverse_window_fraction']} | {c['move_weights']} | {r['time_s']:.0f} |")
    else:
        out.append("- (no rows completed)")
    out.append("")
    text = "\n".join(out)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print("\n" + text, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ttl", type=float, default=SWEEP_TTL_S)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    dxf = _find_sample_dxf()
    if dxf is None:
        print("SKIP: sample_2.dxf not found.", flush=True)
        return 0
    pieces = _load_pieces(dxf, COPIES)
    # Fresh results file each run.
    if os.path.exists(RESULTS_PATH):
        os.remove(RESULTS_PATH)
    print(f"sample_2.dxf x{COPIES} ({len(pieces)} pieces), grain=90, effort={EFFORT}, "
          f"ttl={args.ttl:.0f}s, smoke={args.smoke}", flush=True)

    results: list = []
    started_at = time.perf_counter()
    stopped_reason = "completed"
    try:
        # Phases 0-1 (static single-axis screening).
        for label, cfg, iters, seed in _rows(args.smoke):
            _run_row(label, cfg, iters, seed, pieces, started_at, args.ttl, results)
        final_iters = 5 if args.smoke else 100
        # Phase 2: combine the best-improving value from each axis, at final_iters.
        combo = _build_combo(results)
        _run_row("combo", combo, final_iters, 42, pieces, started_at, args.ttl, results)
        # Phase 3: multi-seed the overall best config (iters>0) at final_iters.
        scored = [r for r in results if r["iters"] > 0]
        if scored:
            best = min(scored, key=lambda r: r["marker"])
            best_cfg = SAConfig(**best["config"])
            seeds = [7, 13] if args.smoke else [7, 13, 21, 99, 123]
            for seed in seeds:
                _run_row(f"best({best['label']})", best_cfg, final_iters, seed,
                         pieces, started_at, args.ttl, results)
    except _TTLExceeded:
        stopped_reason = f"TTL reached ({args.ttl:.0f}s)"
    except KeyboardInterrupt:
        stopped_reason = "KeyboardInterrupt"
    except Exception as e:  # noqa: BLE001 — always finalize a report
        stopped_reason = f"exception: {type(e).__name__}: {e}"
    finally:
        _write_report(results, started_at, stopped_reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
