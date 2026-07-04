"""SIMD/target-cpu rebuild A/B — THROWAWAY spike (delete after the §6 entry lands).

Protocol + gates: docs/superpowers/specs/2026-07-04-sparrow-simd-rebuild-design.md.
Reuses PRODUCTION separation helpers; shells candidate exes directly so each run's
stderr log + sols_ snapshots survive in a persistent workdir.

  ...python.exe engine\\tests\\spike_simd_rebuild.py smoke
  ...python.exe engine\\tests\\spike_simd_rebuild.py run --workload sample_2.dxf --copies 10 \
        --budget 600 --seeds 42,43,44 --arms control,v2,v3,native [--ttl-hours 5]
  ...python.exe engine\\tests\\spike_simd_rebuild.py evaluate --report <r1.json> \
        [--report2 <r2.json> --candidates v2,v3]
"""
from __future__ import annotations
import argparse, glob, hashlib, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from dataclasses import replace
from core.dxf import parse_dxf
from core.geometry import normalize_piece
from core.layout.heuristic import _compute_metrics, _polygon_dims
from core.layout.separation import (_build_warm_start, _group_to_items, _instance_json,
                                    _reconstruct, _resolve_sparrow_path, _validate_layout)

FABRIC, GRAIN_MODE, GRAIN_DEG = 1651.0, "bi", 90.0
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
BUILDS = os.path.join(REPO, "tools", "sparrow-rebuild", "builds")
REPORTS = os.path.join(REPO, "tools", "sparrow-rebuild", "reports")
ARM_EXE = {"control": None,  # None -> production resolver (vendored exe)
           "v2": os.path.join(BUILDS, "sparrow_v2.exe"),
           "v3": os.path.join(BUILDS, "sparrow_v3.exe"),
           "native": os.path.join(BUILDS, "sparrow_native.exe")}


def _find_fixture(sample: str) -> str:
    here = REPO
    p = os.path.join(here, "examples", "input", sample)
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


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _prepare_instance(pieces, out_dir: str) -> tuple[list, str]:
    """Build items + instance + warm start ONCE; serialize the merged instance.
    The protocol REQUIRES the warm arm — abort loudly if the warm start fails."""
    items = _group_to_items(pieces, GRAIN_MODE, GRAIN_DEG)
    instance = _instance_json(items, FABRIC)
    ws = _build_warm_start(items, pieces, FABRIC, GRAIN_MODE, GRAIN_DEG)
    if ws is None:
        raise SystemExit("warm start failed — protocol requires warm arms; investigate first")
    merged = {**instance, "solution": ws}
    ipath = os.path.join(out_dir, "instance_warm.json")
    with open(ipath, "w", encoding="utf-8") as f:
        json.dump(merged, f)
    return items, ipath


def _run_one(exe: str, ipath: str, budget_s: int, seed: int, workdir: str) -> dict:
    """Mirror of production _run_sparrow, but with a persistent workdir that keeps
    stderr log + output/sols_ snapshots for throughput inspection."""
    os.makedirs(workdir, exist_ok=True)
    log_path = os.path.join(workdir, "sparrow.stderr.log")
    t0 = time.perf_counter()
    with open(log_path, "wb") as logf:
        proc = subprocess.Popen([exe, "-i", ipath, "-t", str(int(budget_s)), "-s", str(int(seed))],
                                cwd=workdir, stdout=subprocess.DEVNULL, stderr=logf)
        proc.wait()
    wall = time.perf_counter() - t0
    if proc.returncode != 0:
        raise ValueError(f"sparrow exited {proc.returncode} (see {log_path})")
    outdir = os.path.join(workdir, "output")
    finals = [x for x in os.listdir(outdir) if x.startswith("final_") and x.endswith(".json")] \
        if os.path.isdir(outdir) else []
    if not finals:
        raise ValueError(f"no final_*.json in {outdir}")
    with open(os.path.join(outdir, finals[0]), encoding="utf-8") as f:
        solution = json.load(f)
    snapshots = len(glob.glob(os.path.join(outdir, "sols_*", "*")))
    real_log = os.path.join(outdir, "log.txt")
    if os.path.isfile(real_log):
        with open(real_log, "rb") as f:
            log_lines = f.read().count(b"\n")
    else:
        log_lines = sum(1 for _ in open(log_path, "rb"))
    return {"solution": solution, "wall_s": round(wall, 1),
            "snapshots": snapshots, "log_lines": log_lines, "log": log_path}


def _write_report(out_dir: str, meta: dict, runs: list[dict]) -> None:
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "runs": runs}, f, indent=1)
    lines = [f"# rebuild A/B — {meta['workload']} ×{meta['copies']} @{meta['budget_s']}s (warm)",
             "", "| arm | seed | marker (mm) | util | wall (s) | valid | snaps | log lines |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in runs:
        lines.append(f"| {r['arm']} | {r['seed']} | {r.get('marker_mm', '—')} | "
                     f"{r.get('util_pct', '—')} | {r.get('wall_s', '—')} | {r['valid']} | "
                     f"{r.get('snapshots', '—')} | {r.get('log_lines', '—')} |")
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def cmd_run(args) -> int:
    arms = args.arms.split(",")
    seeds = [int(s) for s in args.seeds.split(",")]
    deadline = time.monotonic() + args.ttl_hours * 3600.0
    out_dir = os.path.join(REPORTS, f"{args.workload.replace('.dxf', '')}_x{args.copies}")
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "report.json")
    runs: list[dict] = []
    if os.path.isfile(report_path):
        with open(report_path, encoding="utf-8") as f:
            runs = json.load(f)["runs"]
    pieces = _load(args.workload, args.copies)
    items, ipath = _prepare_instance(pieces, out_dir)
    exes = {}
    for a in arms:
        exe = ARM_EXE[a] or _resolve_sparrow_path()
        if not os.path.isfile(exe):
            raise SystemExit(f"arm {a}: missing exe {exe}")
        exes[a] = (exe, _sha256(exe))
    meta = {"workload": args.workload, "copies": args.copies, "budget_s": args.budget,
            "fabric": FABRIC, "grain": [GRAIN_MODE, GRAIN_DEG], "seeds": seeds,
            "arms": {a: exes[a][0] for a in arms}, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    for seed in seeds:                      # seed-major: arms interleave within each seed
        for a in arms:                      # so box drift hits all arms of a pair equally
            idx = next((i for i, r in enumerate(runs) if r["arm"] == a and r["seed"] == seed), None)
            if idx is not None:
                if runs[idx]["valid"]:
                    print(f"  skip {a} seed={seed} (already in report)", flush=True)
                    continue
                del runs[idx]              # invalid row: drop it, the re-run below replaces it
            if time.monotonic() > deadline:
                print("TTL expired — report is complete up to here", flush=True)
                _write_report(out_dir, meta, runs)
                return 2
            row = {"arm": a, "seed": seed, "exe": exes[a][0], "sha256": exes[a][1], "valid": False}
            print(f"[{time.strftime('%H:%M:%S')}] {a} seed={seed} …", flush=True)
            try:
                r = _run_one(exes[a][0], ipath, args.budget, seed,
                             os.path.join(out_dir, "runs", f"{a}_s{seed}"))
                placements = _reconstruct(r["solution"], items, FABRIC)
                _validate_layout(placements, pieces, FABRIC, GRAIN_MODE, GRAIN_DEG)
                marker, util = _compute_metrics(placements, pieces, FABRIC, _polygon_dims)
                row.update(valid=True, marker_mm=round(marker, 1), util_pct=round(util, 2),
                           wall_s=r["wall_s"], snapshots=r["snapshots"],
                           log_lines=r["log_lines"], log=r["log"])
                print(f"    marker={marker:.1f}mm util={util:.2f}% wall={r['wall_s']}s", flush=True)
            except (ValueError, KeyError) as e:
                row["error"] = str(e)[:300]
                print(f"    INVALID/FAILED: {row['error']}", flush=True)
            runs.append(row)
            _write_report(out_dir, meta, runs)   # kill-safe: rewrite after EVERY run
    print(f"done -> {os.path.join(out_dir, 'report.json')}", flush=True)
    return 1 if any(not r["valid"] for r in runs) else 0


def _markers(report: dict, arm: str) -> dict[int, float]:
    return {r["seed"]: r["marker_mm"] for r in report["runs"] if r["arm"] == arm and r["valid"]}


def _paired(report: dict, a: str, b: str) -> tuple[float, int, int]:
    """Return (mean of a-b over shared seeds, wins for a, n)."""
    ma, mb = _markers(report, a), _markers(report, b)
    shared = sorted(set(ma) & set(mb))
    deltas = [ma[s] - mb[s] for s in shared]
    wins = sum(1 for d in deltas if d < 0)
    return (sum(deltas) / len(deltas) if deltas else float("nan"), wins, len(deltas))


def _g1(report: dict, cand: str, n_seeds: int) -> bool:
    ok_all_valid = len(_markers(report, cand)) == n_seeds and len(_markers(report, "control")) == n_seeds
    mean, wins, n = _paired(report, cand, "control")
    print(f"  G1[{cand}]: paired mean {mean:+.1f}mm, wins {wins}/{n}, all-valid={ok_all_valid}")
    return ok_all_valid and n == n_seeds and wins >= 2 and mean < 0


def cmd_evaluate(args) -> int:
    with open(args.report, encoding="utf-8") as f:
        rep = json.load(f)
    n = len(rep["meta"]["seeds"])
    print(f"workload-1 gates ({rep['meta']['workload']} ×{rep['meta']['copies']}):")
    g1_v2, g1_v3 = _g1(rep, "v2", n), _g1(rep, "v3", n)
    nat = _markers(rep, "native")
    if nat:
        mean, wins, nn = _paired(rep, "native", "control")
        print(f"  info[native ceiling]: paired mean {mean:+.1f}mm, wins {wins}/{nn}")
    ship = "NO-GO"
    if g1_v3:
        fallback = "v2" if g1_v2 else "control"
        mean_f, _, _ = _paired(rep, "v3", fallback)
        print(f"  G2: v3 vs fallback[{fallback}] paired mean {mean_f:+.1f}mm (need <= -15.0)")
        if mean_f <= -15.0:
            ship = f"DUAL (fallback={fallback}, avx2=v3)"
        elif g1_v2:
            ship = "V2-ONLY"
    elif g1_v2:
        ship = "V2-ONLY"
    print(f"workload-1 verdict: {ship}")
    if args.report2:
        with open(args.report2, encoding="utf-8") as f:
            rep2 = json.load(f)
        print(f"workload-2 G3 ({rep2['meta']['workload']} ×{rep2['meta']['copies']}):")
        for cand in args.candidates.split(","):
            mean, wins, nn = _paired(rep2, cand, "control")
            if nn == 0 or mean != mean:  # nn==0: no shared valid seeds; mean!=mean: NaN
                print(f"  G3[{cand}]: n/a — no runs for this candidate in report2")
                continue
            verdict = "PASS" if mean <= 10.0 else "FAIL (regression >10mm)"
            print(f"  G3[{cand}]: paired mean {mean:+.1f}mm over {nn} seeds -> {verdict}")
    return 0


def cmd_smoke(args) -> int:
    """15s × 1-copy sanity of every present arm; asserts valid + report written."""
    args.workload, args.copies, args.budget, args.seeds, args.ttl_hours = \
        "sample_2.dxf", 1, 15, "42", 1.0
    args.arms = ",".join(a for a, p in ARM_EXE.items() if p is None or os.path.isfile(p))
    print(f"smoke arms: {args.arms}")
    rc = cmd_run(args)
    out = os.path.join(REPORTS, "sample_2_x1", "report.json")
    with open(out, encoding="utf-8") as f:
        rep = json.load(f)
    bad = [r["arm"] for r in rep["runs"] if not r["valid"]]
    if rc == 0 and not bad:
        print("SMOKE PASS")
        return 0
    print(f"SMOKE FAIL: rc={rc} invalid arms={bad}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--workload", default="sample_2.dxf")
    p_run.add_argument("--copies", type=int, default=10)
    p_run.add_argument("--budget", type=int, default=600)
    p_run.add_argument("--seeds", default="42,43,44")
    p_run.add_argument("--arms", default="control,v2,v3,native")
    p_run.add_argument("--ttl-hours", type=float, default=5.0)
    p_ev = sub.add_parser("evaluate")
    p_ev.add_argument("--report", required=True)
    p_ev.add_argument("--report2")
    p_ev.add_argument("--candidates", default="v2,v3")
    sub.add_parser("smoke")
    args = ap.parse_args()
    return {"run": cmd_run, "evaluate": cmd_evaluate, "smoke": cmd_smoke}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
