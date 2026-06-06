"""Manual benchmark for the GA meta-heuristic wrapper. Not part of pytest.

Run from the worktree engine dir with:
    D:\\openmarker\\engine\\.venv\\Scripts\\python.exe engine\\tests\\bench_ga.py

Uses the canonical workload (sample_2.dxf x 10 at fabric=1651mm, bi-grain,
effort=5). Smoke mode (--smoke) uses a tiny 2-gen / 6-pop config that finishes
in ~1-2 min.

PR-blocking acceptance gates:
  G1 (all placed):   ga run places every piece
  G2 (monotone):     ga marker <= warm-start marker
  G3 (determinism):  two runs with same ga_seed and fixed gens yield same marker
                     (skipped in --smoke; only valid without ga_max_time_s since
                     time-capped runs execute a timing-dependent number of gens)
  G4 (default unchanged): no-ga-arg call matches warm-start
  G5 (beat the bar): GA beats 11699mm (info-only, not PR-blocking when missed)

Exits 1 on G1-G4 failure.
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.layout.grain import FABRIC_GRAIN_DEG
from core.layout.ga import GAConfig
from core.layout.heuristic import auto_layout_polygon

SAMPLE_DXF_RELPATH = ["examples", "input", "sample_2.dxf"]
FABRIC = 1651.0
GRAIN_MODE = "bi"
COPIES = 10
EFFORT = 5
BAR = 11699.0


def _find_sample_dxf() -> str | None:
    here = os.path.abspath(HERE)
    for _ in range(8):
        candidate = os.path.join(here, *SAMPLE_DXF_RELPATH)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent
    return None


def _load_workload() -> list:
    """Discover sample_2.dxf, parse+normalize, expand to 10 copies.

    Returns the 190-piece list (19 base pieces × 10 copies). Exits 0 with a
    SKIP message if the fixture is absent (bench is optional)."""
    from dataclasses import replace
    from core.dxf import parse_dxf
    from core.geometry import normalize_piece

    path = _find_sample_dxf()
    if path is None:
        print(f"SKIP: sample_2.dxf not found (looked under {SAMPLE_DXF_RELPATH}).", flush=True)
        print("      This bench requires the canonical fixture. Skipping gracefully.", flush=True)
        sys.exit(0)

    with open(path, "rb") as f:
        raw = parse_dxf(f.read())
    base_pieces = []
    for i, r in enumerate(raw):
        try:
            base_pieces.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    expanded = [replace(bp, id=f"{bp.id}__c{c}")
                for c in range(COPIES) for bp in base_pieces]
    return expanded


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="tiny fast config to verify the script + gate logic")
    ap.add_argument("--gens", type=int, default=12)
    ap.add_argument("--pop", type=int, default=30)
    args = ap.parse_args()

    pieces = _load_workload()
    print(f"workload: {len(pieces)} pieces; smoke={args.smoke}", flush=True)

    base = auto_layout_polygon(pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, effort=EFFORT)
    warm = base[1]
    print(f"warm-start: L={warm:.1f} U={base[2]:.2f}%", flush=True)

    gens, pop = (2, 6) if args.smoke else (args.gens, args.pop)
    pl, marker, util = auto_layout_polygon(
        pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, effort=EFFORT,
        ga_generations=gens, ga_seed=42,
        ga_config=GAConfig(population_size=pop),
    )
    print(f"ga gens={gens} pop={pop}: L={marker:.1f} U={util:.2f}% placed={len(pl)}", flush=True)

    failures = []
    if len(pl) != len(pieces):
        failures.append(f"G1 placed {len(pl)} != {len(pieces)}")
    if marker > warm + 1e-6:
        failures.append(f"G2 GA {marker:.1f} > warm {warm:.1f}")
    default = auto_layout_polygon(pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, effort=EFFORT)
    if default[1] != warm:
        failures.append(f"G4 default {default[1]:.1f} != warm {warm:.1f}")

    # G3 determinism: fixed small gens, NO time cap (time-capped runs do a
    # timing-dependent number of generations and are not reproducible). Skip in smoke.
    if not args.smoke:
        d_kw = dict(effort=EFFORT, ga_generations=4, ga_seed=42,
                    ga_config=GAConfig(population_size=16))
        a = auto_layout_polygon(pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, **d_kw)
        b = auto_layout_polygon(pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, **d_kw)
        if a[1] != b[1]:
            failures.append(f"G3 nondeterministic {a[1]:.4f} != {b[1]:.4f}")
        else:
            print(f"G3 PASS: deterministic at {a[1]:.1f}", flush=True)

    if marker < BAR:
        print(f"G5 PASS: GA {marker:.1f} < bar {BAR}", flush=True)
    elif args.smoke:
        print(f"G5 INFO (smoke config too small to judge): GA {marker:.1f} vs bar {BAR}", flush=True)
    else:
        # PR-blocking since the 2026-06-05 sweep: uniform-weights GA beats the bar
        # on 5/5 seeds (11426-11485mm). A full-config run that misses it is a regression.
        failures.append(f"G5 GA {marker:.1f} did not beat bar {BAR}")

    print("GATES:", ("FAIL: " + "; ".join(failures)) if failures else "G1-G4 PASS", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
