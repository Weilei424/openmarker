"""Segment-chained basin hopping — THROWAWAY spike (delete after the §6 entry lands).

Protocol + gates: docs/superpowers/specs/2026-07-08-basin-hopping-design.md.
Arms = name:chainK:budget — K fresh sparrow processes at budget//K each, every
segment after the first re-seeded via -i from the VALIDATED best-so-far layout
with RNG seed+1000*(j-1). cont == chain1 (the production behavior).

  ...python.exe engine\\tests\\spike_basin_hopping.py smoke
  ...python.exe engine\\tests\\spike_basin_hopping.py run [--workload sample_2.dxf --copies 10] \
        [--arms cont:chain1:2500,chain2:chain2:2500,chain5:chain5:2500] [--seeds 42,43,44] [--ttl-hours 9]
  ...python.exe engine\\tests\\spike_basin_hopping.py evaluate --report <r.json> \
        [--report2 <g3.json> --winner chain2]

Resume: re-running `run` keeps valid (arm, seed) rows and re-runs the rest.
Reports rewritten ATOMICALLY after every run. Exit: 0 all-valid, 1 some-invalid, 2 TTL.
"""
from __future__ import annotations
import argparse, glob, json, math, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from dataclasses import replace
from core.dxf import parse_dxf
from core.geometry import normalize_piece
from core.layout.heuristic import auto_layout_polygon, _compute_metrics, _polygon_dims
from core.layout.separation import (_group_to_items, _instance_json, _placements_to_jagua,
                                    _reconstruct, _resolve_sparrow_path, _validate_layout)

FABRIC, GRAIN_MODE, GRAIN_DEG = 1651.0, "bi", 90.0
COMMERCIAL_MM = 10599.0
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
REPORTS = os.path.join(REPO, "tools", "basin-hopping", "reports")
DEFAULT_ARMS = "cont:chain1:2500,chain2:chain2:2500,chain5:chain5:2500"


def _parse_arms(spec: str) -> list[tuple[str, int, int]]:
    """'name:chainK:budget_s,...' -> [(name, k, budget_s)], validated."""
    arms: list[tuple[str, int, int]] = []
    for part in spec.split(","):
        try:
            name, mode, budget = part.split(":")
        except ValueError:
            raise SystemExit(f"bad arm spec {part!r} (want name:chainK:budget)")
        if not mode.startswith("chain"):
            raise SystemExit(f"unknown mode {mode!r} (want chainK, K >= 1)")
        try:
            k = int(mode[5:])
        except ValueError:
            raise SystemExit(f"bad K in mode {mode!r}")
        if k < 1:
            raise SystemExit(f"K must be >= 1 in {part!r}")
        arms.append((name, k, int(budget)))
    if len({a[0] for a in arms}) != len(arms):
        raise SystemExit("duplicate arm names")
    return arms


def _find_fixture(sample: str) -> str:
    p = os.path.join(REPO, "examples", "input", sample)
    if not os.path.isfile(p):
        raise SystemExit(f"fixture missing: {p} (copy it into the worktree)")
    return p


def _load(sample: str, copies: int):
    with open(_find_fixture(sample), "rb") as f:
        raw = parse_dxf(f.read())
    base = []
    for i, r in enumerate(raw):
        try:
            base.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    return [replace(b, id=f"{b.id}__c{c}") for c in range(copies) for b in base]


def _solution_json(items, pieces, placements, marker: float) -> dict:
    """Engine placements -> jagua warm-start solution dict (production shape)."""
    placed_items = _placements_to_jagua(items, pieces, placements, marker)
    return {"strip_width": float(marker) + 1.0,
            "layout": {"container_id": 0, "placed_items": placed_items, "density": 0.0},
            "density": 0.0, "run_time_sec": 0}


def _prepare_instance(pieces, out_dir):
    """Build the shared jagua instance + the ONE Fast warm-start file (G1-gated)."""
    items = _group_to_items(pieces, GRAIN_MODE, GRAIN_DEG)
    inst = _instance_json(items, FABRIC)
    t0 = time.perf_counter()
    try:
        placements, marker, util = auto_layout_polygon(
            pieces, FABRIC, GRAIN_MODE, GRAIN_DEG, effort=1)
        _validate_layout(placements, pieces, FABRIC, GRAIN_MODE, GRAIN_DEG)
        sol = _solution_json(items, pieces, placements, marker)
    except Exception as e:
        raise SystemExit(f"seed[fast] failed G1: {e}")
    prelude = round(time.perf_counter() - t0, 1)
    ipath = os.path.join(out_dir, "instance_fast.json")
    with open(ipath, "w", encoding="utf-8") as f:
        json.dump({**inst, "solution": sol}, f)
    seeds_meta = {"fast": {"seed_marker_mm": round(marker, 1),
                           "seed_util_pct": round(util, 2), "prelude_s": prelude}}
    print(f"seed[fast]: marker={marker:.1f}mm util={util:.2f}% prelude={prelude}s", flush=True)
    return items, inst, ipath, seeds_meta


def _run_sparrow_once(exe: str, ipath: str, budget_s: int, seed: int, workdir: str) -> dict:
    """One sparrow process in a persistent workdir (output/log.txt + sols_ SVGs)."""
    os.makedirs(workdir, exist_ok=True)
    t0 = time.perf_counter()
    with open(os.path.join(workdir, "sparrow.stderr.log"), "wb") as logf:
        proc = subprocess.Popen([exe, "-i", ipath, "-t", str(int(budget_s)), "-s", str(int(seed))],
                                cwd=workdir, stdout=subprocess.DEVNULL, stderr=logf)
        proc.wait()
    wall = time.perf_counter() - t0
    if proc.returncode != 0:
        raise ValueError(f"sparrow exited {proc.returncode} (see {workdir})")
    outdir = os.path.join(workdir, "output")
    finals = [x for x in os.listdir(outdir) if x.startswith("final_") and x.endswith(".json")] \
        if os.path.isdir(outdir) else []
    if not finals:
        raise ValueError(f"no final_*.json in {outdir}")
    with open(os.path.join(outdir, finals[0]), encoding="utf-8") as f:
        solution = json.load(f)
    logtxt = os.path.join(outdir, "log.txt")
    log_lines = sum(1 for _ in open(logtxt, "rb")) if os.path.isfile(logtxt) else 0
    snapshots = len(glob.glob(os.path.join(outdir, "sols_*", "*.svg")))
    return {"solution": solution, "wall_s": round(wall, 1),
            "snapshots": snapshots, "log_lines": log_lines}


def _run_chain(exe: str, items, pieces, inst: dict, base_ipath: str, k: int,
               budget_s: int, seed: int, workdir: str):
    """K chained segments with explicit keep-best (spec §2).

    Returns (best_marker, best_util, segments). Raises ValueError only when
    segment 1 yields no valid layout (later invalid segments log + continue
    from the prior best)."""
    seg_budgets = [budget_s // k] * k
    seg_budgets[-1] += budget_s - sum(seg_budgets)
    best = None                       # (marker, util, placements)
    segments: list[dict] = []
    next_ipath = base_ipath
    for j, seg_b in enumerate(seg_budgets, start=1):
        segdir = os.path.join(workdir, f"seg{j}")
        seg_row = {"seg": j, "budget_s": seg_b, "improved": False}
        failed_first = False
        try:
            r = _run_sparrow_once(exe, next_ipath, seg_b, seed + 1000 * (j - 1), segdir)
            seg_row.update(wall_s=r["wall_s"], snapshots=r["snapshots"],
                           log_lines=r["log_lines"])
            placements = _reconstruct(r["solution"], items, FABRIC)
            _validate_layout(placements, pieces, FABRIC, GRAIN_MODE, GRAIN_DEG)
            marker, util = _compute_metrics(placements, pieces, FABRIC, _polygon_dims)
            seg_row["marker_mm"] = round(marker, 1)
            if best is None or marker < best[0]:
                seg_row["improved"] = True
                best = (marker, util, placements)
        except (ValueError, KeyError) as e:
            seg_row["error"] = str(e)[:200]
            if best is None:
                failed_first = True
        segments.append(seg_row)
        if failed_first:
            raise ValueError(f"segment 1 invalid: {seg_row.get('error', '?')}")
        if j < k:                     # reseed next segment from the best-so-far
            sol = _solution_json(items, pieces, best[2], best[0])
            next_ipath = os.path.join(segdir, "next_instance.json")
            with open(next_ipath, "w", encoding="utf-8") as f:
                json.dump({**inst, "solution": sol}, f)
    return best[0], best[1], segments


def _write_report(out_dir: str, meta: dict, runs: list[dict]) -> None:
    tmp = os.path.join(out_dir, "report.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "runs": runs}, f, indent=1)
    os.replace(tmp, os.path.join(out_dir, "report.json"))
    lines = [f"# basin hopping — {meta['workload']} ×{meta['copies']}",
             "", "seed layouts (pre-sparrow):", ""]
    for source, sm in meta.get("seeds_meta", {}).items():
        lines.append(f"- {source}: {sm['seed_marker_mm']}mm / {sm['seed_util_pct']}% "
                     f"(prelude {sm['prelude_s']}s)")
    lines += ["", "| arm | K | budget (s) | seed | marker (mm) | util | wall (s) | valid | segment markers |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in runs:
        segs = " / ".join(f"{s.get('marker_mm', 'ERR')}{'*' if s.get('improved') else ''}"
                          for s in r.get("segments", []))
        lines.append(f"| {r['arm']} | {r.get('k', '—')} | {r.get('budget_s', '—')} | "
                     f"{r['seed']} | {r.get('marker_mm', '—')} | {r.get('util_pct', '—')} | "
                     f"{r.get('wall_s', '—')} | {r['valid']} | {segs} |")
    tmp2 = os.path.join(out_dir, "report.md.tmp")
    with open(tmp2, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp2, os.path.join(out_dir, "report.md"))


def cmd_run(args) -> int:
    arms = _parse_arms(args.arms)
    seeds = [int(s) for s in args.seeds.split(",")]
    deadline = time.monotonic() + args.ttl_hours * 3600.0
    out_dir = os.path.join(REPORTS, f"{args.workload.replace('.dxf', '')}_x{args.copies}")
    os.makedirs(out_dir, exist_ok=True)

    pieces = _load(args.workload, args.copies)
    items, inst, ipath, seeds_meta = _prepare_instance(pieces, out_dir)
    exe = _resolve_sparrow_path()

    done: dict[tuple[str, int], dict] = {}
    rpath = os.path.join(out_dir, "report.json")
    if os.path.isfile(rpath):                    # resume: keep valid rows only
        with open(rpath, encoding="utf-8") as f:
            old = json.load(f)
        done = {(r["arm"], r["seed"]): r for r in old.get("runs", []) if r.get("valid")}
        if done:
            print(f"resume: keeping {len(done)} valid rows", flush=True)

    meta = {"workload": args.workload, "copies": args.copies,
            "fabric": FABRIC, "grain": [GRAIN_MODE, GRAIN_DEG], "seeds": seeds,
            "arms": [list(a) for a in arms], "exe": exe, "seeds_meta": seeds_meta,
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    runs: list[dict] = list(done.values())
    _write_report(out_dir, meta, runs)
    ttl_hit = False
    for seed in seeds:                # seed-major: each seed's arm trio runs consecutively
        for name, k, budget in arms:
            if (name, seed) in done:
                continue
            if time.monotonic() > deadline:
                print("TTL expired — report is complete up to here", flush=True)
                ttl_hit = True
                break
            workdir = os.path.join(out_dir, "runs", f"{name}_s{seed}")
            row = {"arm": name, "seed": seed, "k": k, "budget_s": budget,
                   "valid": False, "workdir": workdir}
            print(f"[{time.strftime('%H:%M:%S')}] {name} seed={seed} (K={k}, {budget}s) …", flush=True)
            try:
                t0 = time.perf_counter()
                marker, util, segments = _run_chain(exe, items, pieces, inst, ipath,
                                                    k, budget, seed, workdir)
                row["segments"] = segments
                row.update(valid=True, marker_mm=round(marker, 1), util_pct=round(util, 2),
                           wall_s=round(time.perf_counter() - t0, 1))
                segs = " / ".join(f"{s.get('marker_mm', 'ERR')}{'*' if s.get('improved') else ''}"
                                  for s in segments)
                print(f"    marker={marker:.1f}mm util={util:.2f}% wall={row['wall_s']}s "
                      f"segs=[{segs}]", flush=True)
            except (ValueError, KeyError) as e:
                row["error"] = str(e)[:300]
                print(f"    INVALID/FAILED: {row['error']}", flush=True)
            runs.append(row)
            _write_report(out_dir, meta, runs)   # kill-safe: rewrite after EVERY run
        if ttl_hit:
            break
    _write_report(out_dir, meta, runs)
    if ttl_hit:
        return 2
    invalid = [(r["arm"], r["seed"]) for r in runs if not r["valid"]]
    if invalid:
        print(f"INVALID RUNS: {invalid}", flush=True)
        return 1
    print(f"done -> {rpath}", flush=True)
    return 0


def _markers(report: dict, arm: str) -> dict[int, float]:
    return {r["seed"]: r["marker_mm"] for r in report["runs"]
            if r["arm"] == arm and r["valid"]}


def _paired(report: dict, a: str, b: str):
    ma, mb = _markers(report, a), _markers(report, b)
    shared = sorted(set(ma) & set(mb))
    deltas = [ma[s] - mb[s] for s in shared]
    wins = sum(1 for d in deltas if d < 0)
    mean = sum(deltas) / len(deltas) if deltas else float("nan")
    return mean, wins, shared


def _gate_g2(report: dict, arm: str, baseline: str, n_seeds: int, label: str) -> str:
    ms = _markers(report, arm)
    mean, wins, shared = _paired(report, arm, baseline)
    n = len(shared)
    print(f"  {label} [{arm} vs {baseline}]: per-seed "
          + ", ".join(f"s{s}={ms[s]:.1f}" for s in shared))
    if n < n_seeds:
        print(f"  {label}: only {n}/{n_seeds} shared valid seeds")
        return "INCOMPLETE"
    print(f"  {label}: paired mean {mean:+.1f}mm, wins {wins}/{n}")
    if mean <= -25.0 and wins >= math.ceil(2 * n / 3):
        return "GO"
    if mean > 0.0 or wins <= n // 3:
        return "NO-GO"
    return "BORDERLINE (extend involved arms + cont to seeds 45,46 and re-evaluate)"


def cmd_evaluate(args) -> int:
    with open(args.report, encoding="utf-8") as f:
        rep = json.load(f)
    n = len(rep["meta"]["seeds"])
    print(f"basin hopping ({rep['meta']['workload']} ×{rep['meta']['copies']}):")
    for source, sm in rep["meta"].get("seeds_meta", {}).items():
        print(f"  seed[{source}]: {sm['seed_marker_mm']}mm ({sm['seed_util_pct']}%, "
              f"prelude {sm['prelude_s']}s)")
    arm_names = [a[0] for a in rep["meta"]["arms"]]
    for arm in arm_names:
        ms = _markers(rep, arm)
        if not ms:
            continue
        vals = [ms[s] for s in sorted(ms)]
        mean = sum(vals) / len(vals)
        below = sum(1 for v in vals if v < COMMERCIAL_MM)
        decisive = len(vals) >= n and below == len(vals)
        print(f"  TARGET [{arm}]: " + ", ".join(f"{v:.1f}" for v in vals)
              + f" -> mean {mean:.1f}, {below}/{len(vals)} below {COMMERCIAL_MM:.0f}"
              + (" DECISIVE(all seeds below)" if decisive else ""))
    for arm in arm_names:
        if arm == "cont" or not _markers(rep, arm):
            continue
        print(f"  G2[{arm}] -> {_gate_g2(rep, arm, 'cont', n, f'G2 {arm}')}")
    print("  segment traces (marker per segment, * = improved on best-so-far):")
    for r in rep["runs"]:
        if r.get("valid") and r.get("k", 1) > 1:
            segs = " / ".join(f"{s.get('marker_mm', 'ERR')}{'*' if s.get('improved') else ''}"
                              for s in r.get("segments", []))
            late = sum(1 for s in r.get("segments", [])[1:] if s.get("improved"))
            print(f"    {r['arm']} s{r['seed']}: [{segs}] late-segment improvements: {late}")
    if args.report2:
        with open(args.report2, encoding="utf-8") as f:
            rep2 = json.load(f)
        mean, _wins, shared = _paired(rep2, args.winner, "cont")
        if not shared:
            print(f"G3[{args.winner}]: no shared valid seeds -> INCOMPLETE")
        else:
            verdict = "PASS" if mean <= 40.0 else \
                "FAIL (regression >40mm -> productize as per-workload)"
            print(f"G3[{args.winner}] ({rep2['meta']['workload']} "
                  f"×{rep2['meta']['copies']}): paired mean {mean:+.1f}mm "
                  f"over seeds {shared} -> {verdict}")
    return 0


def cmd_smoke(args) -> int:
    """1-copy chain-plumbing sanity: cont 15s, chain2 2×8s, chain5 5×6s (~2 min).
    6s is the floor we trust sparrow to emit a final solution in — a missing
    final_*.json here is a real failure to escalate, not to paper over."""
    args.workload, args.copies = "sample_2.dxf", 1
    args.arms = "cont:chain1:15,chain2:chain2:16,chain5:chain5:30"
    args.seeds, args.ttl_hours = "42", 1.0
    rc = cmd_run(args)
    print("SMOKE PASS" if rc == 0 else f"SMOKE FAIL: rc={rc}")
    return 0 if rc == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--workload", default="sample_2.dxf")
    p_run.add_argument("--copies", type=int, default=10)
    p_run.add_argument("--arms", default=DEFAULT_ARMS)
    p_run.add_argument("--seeds", default="42,43,44")
    p_run.add_argument("--ttl-hours", type=float, default=9.0)
    p_ev = sub.add_parser("evaluate")
    p_ev.add_argument("--report", required=True)
    p_ev.add_argument("--report2")
    p_ev.add_argument("--winner", default="chain2")
    sub.add_parser("smoke")
    args = ap.parse_args()
    return {"run": cmd_run, "evaluate": cmd_evaluate, "smoke": cmd_smoke}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
