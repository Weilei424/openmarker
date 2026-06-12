"""Ultra-vs-GA bench + time-curve, via the PRODUCTION separation module.

    ...python.exe engine\\tests\\bench_separation.py [--sample S --copies N --budgets 60,180,300,420,600]
"""
from __future__ import annotations
import argparse, os, sys, time
HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from dataclasses import replace
from core.dxf import parse_dxf
from core.geometry import normalize_piece
from core.layout.separation import run_separation_layout

FABRIC = 1651.0
GA_REF = {"sample_2.dxf": 11412.5, "sample_3.dxf": None, "sample_4.dxf": 5121.6}


def _find(sample):
    here = os.path.abspath(HERE)
    for _ in range(8):
        c = os.path.join(here, "examples", "input", sample)
        if os.path.isfile(c):
            return c
        here = os.path.dirname(here)
    return None


def _load(sample, copies):
    path = _find(sample)
    if not path:
        print(f"SKIP: {sample} not found"); sys.exit(0)
    with open(path, "rb") as f:
        raw = parse_dxf(f.read())
    base = []
    for i, r in enumerate(raw):
        try:
            base.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    return [replace(b, id=f"{b.id}__c{c}") for c in range(copies) for b in base]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="sample_2.dxf")
    ap.add_argument("--copies", type=int, default=10)
    ap.add_argument("--budgets", default="600")
    args = ap.parse_args()
    pieces = _load(args.sample, args.copies)
    ref = GA_REF.get(args.sample)
    print(f"workload {args.sample} x{args.copies}: {len(pieces)} pieces, fabric={FABRIC:.0f}, "
          f"GA_ref={ref}", flush=True)
    for budget in [int(b) for b in args.budgets.split(",")]:
        t0 = time.perf_counter()
        placements, marker, util = run_separation_layout(pieces, FABRIC, "bi", 90.0, budget_s=budget, seed=42)
        dt = time.perf_counter() - t0
        gate = ""
        if ref:
            pct = (ref - marker) / ref * 100.0
            gate = f"  vs GA {pct:+.2f}%  {'PASS>=3%' if marker <= ref * 0.97 else 'below-gate'}"
        print(f"  @ {budget:>3}s:  marker={marker:.1f}mm  util={util:.2f}%  "
              f"valid({len(placements)} placed)  wall={dt:.1f}s{gate}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
