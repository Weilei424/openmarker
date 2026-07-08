"""Warm-start budget curve — THROWAWAY spike (delete after the §6 entry lands).

Protocol + decision rules: docs/superpowers/specs/2026-07-07-budget-curve-design.md.
CHARACTERIZATION, not an A/B: every arm uses the production Fast warm start and
differs only by sparrow budget (-t):
  b600:fast:600, b1200:fast:1200, b2500:fast:2500

  ...python.exe engine\\tests\\spike_budget_curve.py smoke
  ...python.exe engine\\tests\\spike_budget_curve.py run [--workload sample_2.dxf --copies 10] \
        [--arms b600:fast:600,b1200:fast:1200,b2500:fast:2500] [--seeds 42,43,44] [--ttl-hours 6]
  ...python.exe engine\\tests\\spike_budget_curve.py evaluate --report <r.json>

Resume: re-running `run` keeps valid (arm, seed) rows and re-runs the rest —
this is also how the optional 1800s backfill and seed-45/46 borderline
extensions work (add the arm / extend --seeds; completed pairs are skipped).
Reports rewritten ATOMICALLY after every run. Exit: 0 all-valid, 1 some-invalid, 2 TTL.
"""
from __future__ import annotations
import argparse, glob, json, os, subprocess, sys, time
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
BORDERLINE_MM = 15.0
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
REPORTS = os.path.join(REPO, "tools", "budget-curve", "reports")
SEED_SOURCES = ("fast",)
DEFAULT_ARMS = "b600:fast:600,b1200:fast:1200,b2500:fast:2500"


def _parse_arms(spec: str) -> list[tuple[str, str, int]]:
    """'name:source:budget_s,...' -> [(name, source, budget_s)], validated."""
    arms: list[tuple[str, str, int]] = []
    for part in spec.split(","):
        try:
            name, source, budget = part.split(":")
        except ValueError:
            raise SystemExit(f"bad arm spec {part!r} (want name:source:budget)")
        if source not in SEED_SOURCES:
            raise SystemExit(f"unknown seed source {source!r} (choose from {SEED_SOURCES})")
        arms.append((name, source, int(budget)))
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


def _seed_layout(source: str, pieces):
    """Production Fast tier — the only seed source this round."""
    t0 = time.perf_counter()
    placements, marker, util = auto_layout_polygon(
        pieces, FABRIC, GRAIN_MODE, GRAIN_DEG, effort=1)
    return placements, marker, util, round(time.perf_counter() - t0, 1)


def _prepare_instances(pieces, sources, out_dir):
    """One merged warm-start instance file per seed SOURCE (all arms share it;
    the budget lives in the CLI -t). G1 applies to the seed: abort loudly."""
    items = _group_to_items(pieces, GRAIN_MODE, GRAIN_DEG)
    inst = _instance_json(items, FABRIC)
    paths, seeds_meta = {}, {}
    for source in sources:
        try:
            placements, marker, util, prelude = _seed_layout(source, pieces)
            _validate_layout(placements, pieces, FABRIC, GRAIN_MODE, GRAIN_DEG)
            placed_items = _placements_to_jagua(items, pieces, placements, marker)
        except Exception as e:
            raise SystemExit(f"seed[{source}] failed G1: {e}")
        sol = {"strip_width": float(marker) + 1.0,
               "layout": {"container_id": 0, "placed_items": placed_items, "density": 0.0},
               "density": 0.0, "run_time_sec": 0}
        ipath = os.path.join(out_dir, f"instance_{source}.json")
        with open(ipath, "w", encoding="utf-8") as f:
            json.dump({**inst, "solution": sol}, f)
        paths[source] = ipath
        seeds_meta[source] = {"seed_marker_mm": round(marker, 1),
                              "seed_util_pct": round(util, 2), "prelude_s": prelude}
        print(f"seed[{source}]: marker={marker:.1f}mm util={util:.2f}% "
              f"prelude={prelude}s", flush=True)
    return items, paths, seeds_meta


def _run_one(exe: str, ipath: str, budget_s: int, seed: int, workdir: str) -> dict:
    """Mirror of production _run_sparrow with a persistent workdir keeping
    output/log.txt (the real log — stderr is empty) + sols_ SVG snapshots."""
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


def _write_report(out_dir: str, meta: dict, runs: list[dict]) -> None:
    tmp = os.path.join(out_dir, "report.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "runs": runs}, f, indent=1)
    os.replace(tmp, os.path.join(out_dir, "report.json"))
    lines = [f"# budget curve — {meta['workload']} ×{meta['copies']}",
             "", "seed layouts (pre-sparrow):", ""]
    for source, sm in meta.get("seeds_meta", {}).items():
        lines.append(f"- {source}: {sm['seed_marker_mm']}mm / {sm['seed_util_pct']}% "
                     f"(prelude {sm['prelude_s']}s)")
    lines += ["", "| arm | source | budget (s) | seed | marker (mm) | util | wall (s) | valid | snaps | log lines |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in runs:
        lines.append(f"| {r['arm']} | {r.get('seed_source', '—')} | {r.get('budget_s', '—')} | "
                     f"{r['seed']} | {r.get('marker_mm', '—')} | {r.get('util_pct', '—')} | "
                     f"{r.get('wall_s', '—')} | {r['valid']} | {r.get('snapshots', '—')} | "
                     f"{r.get('log_lines', '—')} |")
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
    sources = list(dict.fromkeys(source for _, source, _ in arms))
    items, ipaths, seeds_meta = _prepare_instances(pieces, sources, out_dir)
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
    for seed in seeds:                # seed-major: each seed's budget trio runs consecutively
        for name, source, budget in arms:
            if (name, seed) in done:
                continue
            if time.monotonic() > deadline:
                print("TTL expired — report is complete up to here", flush=True)
                ttl_hit = True
                break
            workdir = os.path.join(out_dir, "runs", f"{name}_s{seed}")
            row = {"arm": name, "seed": seed, "seed_source": source,
                   "budget_s": budget, "valid": False, "workdir": workdir}
            print(f"[{time.strftime('%H:%M:%S')}] {name} seed={seed} (-t {budget}) …", flush=True)
            try:
                r = _run_one(exe, ipaths[source], budget, seed, workdir)
                placements = _reconstruct(r["solution"], items, FABRIC)
                _validate_layout(placements, pieces, FABRIC, GRAIN_MODE, GRAIN_DEG)
                marker, util = _compute_metrics(placements, pieces, FABRIC, _polygon_dims)
                row.update(valid=True, marker_mm=round(marker, 1), util_pct=round(util, 2),
                           wall_s=r["wall_s"], snapshots=r["snapshots"],
                           log_lines=r["log_lines"])
                print(f"    marker={marker:.1f}mm util={util:.2f}% wall={r['wall_s']}s",
                      flush=True)
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


def cmd_evaluate(args) -> int:
    """Characterization readouts (spec §3): per-budget stats, CROSSED /
    BORDERLINE per the pre-registered rules, marginal-value table, DECISIVE."""
    with open(args.report, encoding="utf-8") as f:
        rep = json.load(f)
    n = len(rep["meta"]["seeds"])
    print(f"budget curve ({rep['meta']['workload']} ×{rep['meta']['copies']}):")
    for source, sm in rep["meta"].get("seeds_meta", {}).items():
        print(f"  seed[{source}]: {sm['seed_marker_mm']}mm ({sm['seed_util_pct']}%, "
              f"prelude {sm['prelude_s']}s)")
    arm_budget = {r["arm"]: r["budget_s"] for r in rep["runs"] if r["valid"]}
    stats = []   # (arm, budget, per-seed values sorted by seed, mean, below, crossed, borderline)
    for arm, budget in sorted(arm_budget.items(), key=lambda kv: kv[1]):
        ms = _markers(rep, arm)
        vals = [ms[s] for s in sorted(ms)]
        mean = sum(vals) / len(vals)
        below = sum(1 for v in vals if v < COMMERCIAL_MM)
        complete = len(vals) >= n
        crossed = complete and mean < COMMERCIAL_MM and 3 * below >= 2 * len(vals)
        borderline = abs(mean - COMMERCIAL_MM) <= BORDERLINE_MM
        stats.append((arm, budget, vals, mean, below, crossed, borderline))
        flags = (" CROSSED" if crossed else "") + \
                (" BORDERLINE(extend this budget to seeds 45,46)" if borderline else "") + \
                ("" if complete else f" INCOMPLETE({len(vals)}/{n})")
        print(f"  {arm} (-t {budget}): " + ", ".join(f"{v:.1f}" for v in vals)
              + f" -> mean {mean:.1f}, {below}/{len(vals)} below {COMMERCIAL_MM:.0f}{flags}")
    print("  marginal value (single-run spreads on record ~45-120mm; "
          "3-seed means good to a few tens of mm):")
    for prev, cur in zip(stats, stats[1:]):
        d = cur[3] - prev[3]
        db = cur[1] - prev[1]
        rate = f"{d / (db / 100.0):+.2f}mm/100s" if db else "n/a (equal budgets)"
        print(f"    {prev[0]}->{cur[0]} (+{db}s): {d:+.1f}mm total, {rate}")
    crossed_arms = [s for s in stats if s[5]]
    if crossed_arms:
        a, b = crossed_arms[0][0], crossed_arms[0][1]
        print(f"  DECISIVE: YES — smallest crossed budget = {a} ({b}s) -> propose as the "
              f"new Ultra default (follow-up mini-PR)")
    else:
        print("  DECISIVE: no — no budget crossed; the flattest marginal segment above "
              "names lever (f)'s test budget")
    return 0


def cmd_smoke(args) -> int:
    """1-copy sanity of all three arms @15s (~2 min incl. the Fast prelude)."""
    args.workload, args.copies = "sample_2.dxf", 1
    args.arms = "b600:fast:15,b1200:fast:20,b2500:fast:25"
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
    p_run.add_argument("--ttl-hours", type=float, default=6.0)
    p_ev = sub.add_parser("evaluate")
    p_ev.add_argument("--report", required=True)
    sub.add_parser("smoke")
    args = ap.parse_args()
    return {"run": cmd_run, "evaluate": cmd_evaluate, "smoke": cmd_smoke}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
