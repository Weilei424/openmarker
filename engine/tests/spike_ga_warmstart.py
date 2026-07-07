"""GA-layout warm-start A/B — THROWAWAY spike (delete after the §6 entry lands).

Protocol + gates: docs/superpowers/specs/2026-07-06-ga-warmstart-design.md.
Arms share the vendored exe; each arm = name:seed_source:sparrow_budget_s:
  prod   = fast seed + 600s   (production reference, ~626s envelope)
  ctl780 = fast seed + 754s   (equal-envelope control, ~780s)
  ga     = GA Better-tier seed + 600s (treatment, ~780s envelope)

  ...python.exe engine\\tests\\spike_ga_warmstart.py smoke
  ...python.exe engine\\tests\\spike_ga_warmstart.py run [--workload sample_2.dxf --copies 10] \
        [--arms prod:fast:600,ctl780:fast:754,ga:ga:600] [--seeds 42,43,44] [--ttl-hours 3.5]
  ...python.exe engine\\tests\\spike_ga_warmstart.py evaluate --report <r1.json> [--report2 <r2.json>]

Resume: re-running `run` keeps valid (arm, seed) rows from an existing report and
re-runs missing/invalid ones. Report JSON+MD rewritten ATOMICALLY after every
run (kill-safe). Exit codes: 0 all-valid, 1 some invalid, 2 TTL hit.
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
REPORTS = os.path.join(REPO, "tools", "ga-warmstart-spike", "reports")
SEED_SOURCES = ("fast", "ga")
DEFAULT_ARMS = "prod:fast:600,ctl780:fast:754,ga:ga:600"


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
    """Build one seed layout. fast = production Fast tier; ga = production
    Better tier verbatim (deterministic; time binds on the canonical workload)."""
    t0 = time.perf_counter()
    if source == "fast":
        placements, marker, util = auto_layout_polygon(
            pieces, FABRIC, GRAIN_MODE, GRAIN_DEG, effort=1)
    else:  # "ga"
        placements, marker, util = auto_layout_polygon(
            pieces, FABRIC, GRAIN_MODE, GRAIN_DEG,
            effort=4, ga_generations=12, ga_max_time_s=180.0, ga_seed=42)
    return placements, marker, util, round(time.perf_counter() - t0, 1)


def _prepare_instances(pieces, sources, out_dir):
    """One merged warm-start instance file per seed SOURCE (arms sharing a
    source share the file; the arm's budget lives in the CLI -t, not the JSON).
    G1 applies to seeds: abort loudly if any seed fails the validator."""
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
    lines = [f"# GA warm-start A/B — {meta['workload']} ×{meta['copies']}",
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
    sources = list(dict.fromkeys(source for _, source, _ in arms))   # ordered unique
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
    for seed in seeds:                # seed-major: arms interleave within each seed
        for name, source, budget in arms:   # so box drift hits all arms of a pair equally
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


def _paired(report: dict, a: str, b: str):
    """(mean of a-b over shared seeds, wins for a, shared seed list)."""
    ma, mb = _markers(report, a), _markers(report, b)
    shared = sorted(set(ma) & set(mb))
    deltas = [ma[s] - mb[s] for s in shared]
    wins = sum(1 for d in deltas if d < 0)
    mean = sum(deltas) / len(deltas) if deltas else float("nan")
    return mean, wins, shared


def _gate_g2(report: dict, arm: str, baseline: str, n_seeds: int, label: str) -> str:
    """Spec §5 G2: GO = mean <= -25 AND wins >= 2/3 of seeds; NO-GO = mean > 0
    or wins <= 1/3; otherwise borderline -> extend seeds."""
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
    return "BORDERLINE (extend all arms to seeds 45,46 and re-evaluate)"


def cmd_evaluate(args) -> int:
    with open(args.report, encoding="utf-8") as f:
        rep = json.load(f)
    n = len(rep["meta"]["seeds"])
    print(f"gates ({rep['meta']['workload']} ×{rep['meta']['copies']}):")
    print("seed layouts (pre-sparrow):")
    for source, sm in rep["meta"].get("seeds_meta", {}).items():
        print(f"  {source}: {sm['seed_marker_mm']}mm ({sm['seed_util_pct']}%, "
              f"prelude {sm['prelude_s']}s)")
    if _markers(rep, "ctl780") and _markers(rep, "prod"):
        mean, wins, shared = _paired(rep, "ctl780", "prod")
        print(f"  dose-response [ctl780 vs prod, +154s]: paired mean {mean:+.1f}mm, "
              f"wins {wins}/{len(shared)} (informational)")
    verdict_mech = verdict_prod = None
    if _markers(rep, "ga") and _markers(rep, "prod"):
        verdict_mech = _gate_g2(rep, "ga", "prod", n, "G2-mechanism (secondary)")
        print(f"  G2-mechanism -> {verdict_mech}")
    if _markers(rep, "ga") and _markers(rep, "ctl780"):
        verdict_prod = _gate_g2(rep, "ga", "ctl780", n, "G2-product (PRIMARY)")
        print(f"  G2-product -> {verdict_prod}")
    ga = _markers(rep, "ga")
    if len(ga) == n:
        decisive = all(v < COMMERCIAL_MM for v in ga.values())
        print(f"  DECISIVE (all ga finals < {COMMERCIAL_MM:.0f}): {'YES' if decisive else 'no'}")
    if verdict_prod == "NO-GO" and verdict_mech == "GO":
        print("  interpretation: seed transfers but is not worth 154s of sparrow "
              "-> file the cheaper-GA-prelude (60-90s cap) follow-up")
    if args.report2:
        with open(args.report2, encoding="utf-8") as f:
            rep2 = json.load(f)
        mean, _wins, shared = _paired(rep2, "ga", "prod")
        if not shared:
            print("G3[ga]: no shared valid seeds -> INCOMPLETE")
        else:
            verdict = "PASS" if mean <= 40.0 else \
                "FAIL (regression >40mm -> productize as per-workload seed pick)"
            print(f"G3[ga] ({rep2['meta']['workload']} ×{rep2['meta']['copies']}): "
                  f"paired mean {mean:+.1f}mm over seeds {shared} -> {verdict}")
    return 0


def cmd_smoke(args) -> int:
    """1-copy sanity of all three arms @15s (the GA prelude finishes early at
    1 copy via the 12-generation cap; expect ~3-6 min total)."""
    args.workload, args.copies = "sample_2.dxf", 1
    args.arms = "prod:fast:15,ctl780:fast:15,ga:ga:15"
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
    p_run.add_argument("--ttl-hours", type=float, default=3.5)
    p_ev = sub.add_parser("evaluate")
    p_ev.add_argument("--report", required=True)
    p_ev.add_argument("--report2")
    sub.add_parser("smoke")
    args = ap.parse_args()
    return {"run": cmd_run, "evaluate": cmd_evaluate, "smoke": cmd_smoke}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
