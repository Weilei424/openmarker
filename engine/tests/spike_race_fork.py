"""Race + fork — THROWAWAY spike (delete after the §6 entry lands).

Protocol + gates: docs/superpowers/specs/2026-07-09-race-fork-design.md.
Two policies at equal 7500s wall, replicated on fresh seed blocks:
  seq3     = sequential best-of-3 full production warm runs (-t 2500 each)
  racefork = 4 explore-only probes x450s -> winner explore rerun 2000s
             (from scratch; explore is rung-deterministic per seed)
             -> K=7 compress-only forks x500s from the rerun's end state.

  ...python.exe engine\\tests\\spike_race_fork.py smoke
  ...python.exe engine\\tests\\spike_race_fork.py run [--workload sample_2.dxf --copies 10] \
        [--arms seq3,racefork] [--blocks "51,52,53,54;61,62,63,64;71,72,73,74"] [--ttl-hours 14]
  ...python.exe engine\\tests\\spike_race_fork.py evaluate --report <r.json> \
        [--report2 <g3.json> --winner racefork]

Resume: re-running `run` keeps valid (arm, rep) rows and re-runs the rest.
Reports rewritten ATOMICALLY after every run. Exit: 0 all-valid, 1 some-invalid, 2 TTL.
"""
from __future__ import annotations
import argparse, glob, json, math, os, re, shutil, subprocess, sys, time
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
CONT_ANCHOR_MM = 10585.5          # pooled warm cont@2500s, n=6 (PERFORMANCE.md §6 [2026-07-09])
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
REPORTS = os.path.join(REPO, "tools", "race-fork", "reports")
DEFAULT_BLOCKS = "51,52,53,54;61,62,63,64;71,72,73,74"
SEQ_N, SEQ_BUDGET_S = 3, 2500
PROBE_S, EXPLORE_S, K_FORKS, COMPRESS_S = 450, 2000, 7, 500
EXPL_LINE = re.compile(
    r"\[(\d+):(\d+):(\d+)\].*\[EXPL\] feasible solution found! \(width: ([\d.]+)")


def _parse_blocks(spec: str, seq_n: int) -> list[list[int]]:
    """'51,52,53,54;61,...' -> [[51,52,53,54], ...]; each block feeds seq3
    (first seq_n seeds) and racefork (ALL seeds as probes, so len >= 2)."""
    blocks: list[list[int]] = []
    for part in spec.split(";"):
        seeds = [int(s) for s in part.split(",") if s.strip()]
        if len(seeds) < max(seq_n, 2):
            raise SystemExit(f"block {part!r} too small (need >= max(seq_n, 2) seeds)")
        blocks.append(seeds)
    if not blocks:
        raise SystemExit("no seed blocks given")
    return blocks


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


def _width_of(ext: dict) -> float:
    """Strip width of a sparrow ExtSPOutput dict (final_*.json shape)."""
    return float(ext["solution"]["strip_width"])


def _spawn(exe: str, cli: list[str], workdir: str) -> None:
    os.makedirs(workdir, exist_ok=True)
    with open(os.path.join(workdir, "sparrow.stderr.log"), "wb") as logf:
        proc = subprocess.Popen([exe] + cli, cwd=workdir,
                                stdout=subprocess.DEVNULL, stderr=logf)
        proc.wait()
    if proc.returncode != 0:
        raise ValueError(f"sparrow exited {proc.returncode} (see {workdir})")


def _read_final(workdir: str):
    """(path, parsed dict) of output/final_*.json — a full ExtSPOutput
    (name/items/strip_height/solution), reusable directly as a -i input."""
    outdir = os.path.join(workdir, "output")
    finals = [x for x in os.listdir(outdir) if x.startswith("final_") and x.endswith(".json")] \
        if os.path.isdir(outdir) else []
    if not finals:
        raise ValueError(f"no final_*.json in {outdir}")
    fpath = os.path.join(outdir, finals[0])
    with open(fpath, encoding="utf-8") as f:
        return fpath, json.load(f)


def _log_stats(workdir: str):
    outdir = os.path.join(workdir, "output")
    logtxt = os.path.join(outdir, "log.txt")
    log_lines = sum(1 for _ in open(logtxt, "rb")) if os.path.isfile(logtxt) else 0
    snapshots = len(glob.glob(os.path.join(outdir, "sols_*", "*.svg")))
    return log_lines, snapshots


def _run_sparrow_t(exe: str, ipath: str, budget_s: int, seed: int, workdir: str) -> dict:
    """One production-form run (-t) in a persistent workdir."""
    t0 = time.perf_counter()
    _spawn(exe, ["-i", ipath, "-t", str(int(budget_s)), "-s", str(int(seed))], workdir)
    wall = time.perf_counter() - t0
    fpath, ext = _read_final(workdir)
    log_lines, snapshots = _log_stats(workdir)
    return {"final_path": fpath, "ext": ext, "wall_s": round(wall, 1),
            "snapshots": snapshots, "log_lines": log_lines}


def _run_sparrow_ec(exe: str, ipath: str, e_s: int, c_s: int, seed: int, workdir: str) -> dict:
    """Explore/compress-budgeted run (-e/-c, no -t). A zero budget falls back to
    1s ONCE (spec §2 CLI fallbacks); a failure after fallback raises — that is
    the escalation path, not noise."""
    attempts = [(int(e_s), int(c_s))]
    if e_s == 0 or c_s == 0:
        attempts.append((max(1, int(e_s)), max(1, int(c_s))))
    last_err: Exception | None = None
    for e_try, c_try in attempts:
        shutil.rmtree(os.path.join(workdir, "output"), ignore_errors=True)
        t0 = time.perf_counter()
        try:
            _spawn(exe, ["-i", ipath, "-e", str(e_try), "-c", str(c_try),
                         "-s", str(int(seed))], workdir)
            fpath, ext = _read_final(workdir)
        except ValueError as err:
            last_err = err
            continue
        wall = time.perf_counter() - t0
        log_lines, snapshots = _log_stats(workdir)
        return {"final_path": fpath, "ext": ext, "wall_s": round(wall, 1),
                "snapshots": snapshots, "log_lines": log_lines,
                "e_s_used": e_try, "c_s_used": c_try}
    raise ValueError(f"sparrow -e/-c failed after fallback: {last_err}")


def _validated_metrics(ext: dict, items, pieces):
    """Production G1 round-trip: ExtSPOutput -> Placements -> validator -> metrics."""
    placements = _reconstruct(ext, items, FABRIC)
    _validate_layout(placements, pieces, FABRIC, GRAIN_MODE, GRAIN_DEG)
    return _compute_metrics(placements, pieces, FABRIC, _polygon_dims)


def _explore_best_at(workdir: str, t_s: int):
    """Best feasible explore width at <= t_s from output/log.txt (telemetry only)."""
    logtxt = os.path.join(workdir, "output", "log.txt")
    if not os.path.isfile(logtxt):
        return None
    best = None
    with open(logtxt, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = EXPL_LINE.search(line)
            if not m:
                continue
            t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            if t <= t_s:
                w = float(m.group(4))
                best = w if best is None or w < best else best
    return best


def _run_seq(exe: str, items, pieces, ipath: str, seeds: list[int],
             budget_s: int, workdir: str):
    """Sequential best-of-N full production runs. Returns (marker, util, members).
    Raises ValueError only when ALL members are invalid."""
    best = None
    members: list[dict] = []
    for i, seed in enumerate(seeds, start=1):
        mdir = os.path.join(workdir, f"m{i}")
        row = {"member": i, "seed": seed, "budget_s": budget_s, "valid": False}
        try:
            r = _run_sparrow_t(exe, ipath, budget_s, seed, mdir)
            row.update(wall_s=r["wall_s"], snapshots=r["snapshots"],
                       log_lines=r["log_lines"])
            marker, util = _validated_metrics(r["ext"], items, pieces)
            row.update(valid=True, marker_mm=round(marker, 1), util_pct=round(util, 2))
            if best is None or marker < best[0]:
                best = (marker, util)
        except (ValueError, KeyError) as e:
            row["error"] = str(e)[:200]
        members.append(row)
    if best is None:
        raise ValueError("all seq members invalid")
    return best[0], best[1], members


def _run_racefork(exe: str, items, pieces, ipath: str, seeds: list[int], probe_s: int,
                  explore_s: int, k: int, compress_s: int, workdir: str):
    """Race explore probes -> winner explore rerun (from scratch) -> K compress forks.

    Probes are ranking-only. The rerun's explore-end state is G1-validated
    BEFORE forking; invalid -> runner-up retry (spec failure ladder). Forks feed
    the rerun's own final_*.json via -i. Returns (marker, util, detail); raises
    ValueError when no valid arm final exists."""
    probes: list[dict] = []
    for seed in seeds:
        pdir = os.path.join(workdir, f"probe_s{seed}")
        row = {"seed": seed, "probe_s": probe_s}
        try:
            r = _run_sparrow_ec(exe, ipath, probe_s, 0, seed, pdir)
            row.update(width_mm=round(_width_of(r["ext"]), 1),
                       wall_s=r["wall_s"], c_s_used=r["c_s_used"])
        except (ValueError, KeyError) as e:
            row["error"] = str(e)[:200]
        probes.append(row)
    ranked = sorted((p for p in probes if "width_mm" in p),
                    key=lambda p: (p["width_mm"], seeds.index(p["seed"])))
    if not ranked:
        raise ValueError("all probes failed")
    rerun = None
    for cand in ranked[:2]:               # winner, then runner-up (spec failure ladder)
        rdir = os.path.join(workdir, f"rerun_s{cand['seed']}")
        try:
            r = _run_sparrow_ec(exe, ipath, explore_s, 0, cand["seed"], rdir)
            _validated_metrics(r["ext"], items, pieces)   # G1 gate on the state
            agree = _explore_best_at(rdir, probe_s)
            rerun = {"seed": cand["seed"], "final_path": r["final_path"],
                     "explore_end_mm": round(_width_of(r["ext"]), 1),
                     "wall_s": r["wall_s"], "c_s_used": r["c_s_used"],
                     "probe_width_mm": cand["width_mm"],
                     "rerun_at_probe_mm": round(agree, 1) if agree is not None else None}
            break
        except (ValueError, KeyError) as e:
            cand["rerun_error"] = str(e)[:150]
    if rerun is None:
        raise ValueError("winner and runner-up explore reruns both invalid")
    forks: list[dict] = []
    best = None
    for j in range(1, k + 1):
        fdir = os.path.join(workdir, f"fork{j}")
        fseed = rerun["seed"] + 1000 * j
        row = {"fork": j, "seed": fseed, "compress_s": compress_s, "valid": False}
        try:
            r = _run_sparrow_ec(exe, rerun["final_path"], 0, compress_s, fseed, fdir)
            row.update(wall_s=r["wall_s"], e_s_used=r["e_s_used"])
            marker, util = _validated_metrics(r["ext"], items, pieces)
            row.update(valid=True, marker_mm=round(marker, 1), util_pct=round(util, 2))
            if best is None or marker < best[0]:
                best = (marker, util)
        except (ValueError, KeyError) as e:
            row["error"] = str(e)[:200]
        forks.append(row)
    detail = {"probes": probes, "rerun": rerun, "forks": forks}
    if best is None:
        raise ValueError("all forks invalid")
    return best[0], best[1], detail


def _write_report(out_dir: str, meta: dict, runs: list[dict]) -> None:
    tmp = os.path.join(out_dir, "report.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "runs": runs}, f, indent=1)
    os.replace(tmp, os.path.join(out_dir, "report.json"))
    lines = [f"# race+fork — {meta['workload']} ×{meta['copies']}", "",
             "seed layouts (pre-sparrow):", ""]
    for source, sm in meta.get("seeds_meta", {}).items():
        lines.append(f"- {source}: {sm['seed_marker_mm']}mm / {sm['seed_util_pct']}% "
                     f"(prelude {sm['prelude_s']}s)")
    lines += ["", "| arm | rep | block | marker (mm) | util | wall (s) | valid | detail |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in runs:
        if r["arm"] == "seq3":
            detail = "members: " + " / ".join(
                str(m.get("marker_mm", "ERR")) for m in r.get("members", []))
        else:
            pw = " / ".join(f"s{p['seed']}={p.get('width_mm', 'ERR')}"
                            for p in r.get("probes", []))
            fw = " / ".join(str(fk.get("marker_mm", "ERR")) for fk in r.get("forks", []))
            win = r.get("rerun", {}).get("seed", "?")
            detail = f"probes[{pw}] win=s{win} forks[{fw}]"
        lines.append(f"| {r['arm']} | {r['rep']} | {','.join(map(str, r.get('block', [])))} | "
                     f"{r.get('marker_mm', '—')} | {r.get('util_pct', '—')} | "
                     f"{r.get('wall_s', '—')} | {r['valid']} | {detail} |")
    tmp2 = os.path.join(out_dir, "report.md.tmp")
    with open(tmp2, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp2, os.path.join(out_dir, "report.md"))


def cmd_run(args) -> int:
    arms = [a.strip() for a in args.arms.split(",")]
    for a in arms:
        if a not in ("seq3", "racefork"):
            raise SystemExit(f"unknown arm {a!r} (want seq3 / racefork)")
    if len(set(arms)) != len(arms):
        raise SystemExit("duplicate arm names")
    blocks = _parse_blocks(args.blocks, args.seq_n)
    deadline = time.monotonic() + args.ttl_hours * 3600.0
    out_dir = os.path.join(REPORTS, f"{args.workload.replace('.dxf', '')}_x{args.copies}")
    os.makedirs(out_dir, exist_ok=True)

    pieces = _load(args.workload, args.copies)
    items, _inst, ipath, seeds_meta = _prepare_instance(pieces, out_dir)
    exe = _resolve_sparrow_path()

    done: dict[tuple[str, int], dict] = {}
    rpath = os.path.join(out_dir, "report.json")
    if os.path.isfile(rpath):                    # resume: keep valid rows only
        with open(rpath, encoding="utf-8") as f:
            old = json.load(f)
        done = {(r["arm"], r["rep"]): r for r in old.get("runs", []) if r.get("valid")}
        if done:
            print(f"resume: keeping {len(done)} valid rows", flush=True)

    meta = {"workload": args.workload, "copies": args.copies,
            "fabric": FABRIC, "grain": [GRAIN_MODE, GRAIN_DEG],
            "arms": arms, "blocks": blocks,
            "params": {"seq_n": args.seq_n, "seq_budget_s": args.seq_budget,
                       "probe_s": args.probe_s, "explore_s": args.explore_s,
                       "k_forks": args.k_forks, "compress_s": args.compress_s},
            "exe": exe, "seeds_meta": seeds_meta,
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    runs: list[dict] = list(done.values())
    _write_report(out_dir, meta, runs)
    ttl_hit = False
    for rep, block in enumerate(blocks, start=1):   # rep-major: both arms per block
        for arm in arms:
            if (arm, rep) in done:
                continue
            if time.monotonic() > deadline:
                print("TTL expired — report is complete up to here", flush=True)
                ttl_hit = True
                break
            workdir = os.path.join(out_dir, "runs", f"{arm}_r{rep}")
            row = {"arm": arm, "rep": rep, "block": block, "valid": False,
                   "workdir": workdir}
            print(f"[{time.strftime('%H:%M:%S')}] {arm} rep={rep} block={block} …", flush=True)
            try:
                t0 = time.perf_counter()
                if arm == "seq3":
                    marker, util, members = _run_seq(
                        exe, items, pieces, ipath, block[:args.seq_n],
                        args.seq_budget, workdir)
                    row["members"] = members
                else:
                    marker, util, detail = _run_racefork(
                        exe, items, pieces, ipath, block, args.probe_s,
                        args.explore_s, args.k_forks, args.compress_s, workdir)
                    row.update(detail)
                row.update(valid=True, marker_mm=round(marker, 1),
                           util_pct=round(util, 2),
                           wall_s=round(time.perf_counter() - t0, 1))
                print(f"    marker={marker:.1f}mm util={util:.2f}% "
                      f"wall={row['wall_s']}s", flush=True)
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
    invalid = [(r["arm"], r["rep"]) for r in runs if not r["valid"]]
    if invalid:
        print(f"INVALID RUNS: {invalid}", flush=True)
        return 1
    print(f"done -> {rpath}", flush=True)
    return 0


def _finals(report: dict, arm: str) -> dict[int, float]:
    return {r["rep"]: r["marker_mm"] for r in report["runs"]
            if r["arm"] == arm and r["valid"]}


def _paired(report: dict, a: str, b: str):
    ma, mb = _finals(report, a), _finals(report, b)
    shared = sorted(set(ma) & set(mb))
    deltas = [ma[r] - mb[r] for r in shared]
    wins = sum(1 for d in deltas if d < 0)
    mean = sum(deltas) / len(deltas) if deltas else float("nan")
    return mean, wins, shared


def _best_of_k_curve(vals_sorted: list[float]) -> dict[int, float]:
    """E[min of a k-subset] for k=1..n over sorted-ascending finals (exact)."""
    n = len(vals_sorted)
    return {k: sum(v * math.comb(n - 1 - i, k - 1) for i, v in enumerate(vals_sorted))
               / math.comb(n, k)
            for k in range(1, n + 1)}


def cmd_evaluate(args) -> int:
    with open(args.report, encoding="utf-8") as f:
        rep = json.load(f)
    n = len(rep["meta"]["blocks"])
    print(f"race+fork ({rep['meta']['workload']} ×{rep['meta']['copies']}):")
    for source, sm in rep["meta"].get("seeds_meta", {}).items():
        print(f"  seed[{source}]: {sm['seed_marker_mm']}mm ({sm['seed_util_pct']}%, "
              f"prelude {sm['prelude_s']}s)")
    decisive: dict[str, bool] = {}
    for arm in rep["meta"]["arms"]:
        ms = _finals(rep, arm)
        if not ms:
            continue
        vals = [ms[r] for r in sorted(ms)]
        mean = sum(vals) / len(vals)
        below = sum(1 for v in vals if v < COMMERCIAL_MM)
        decisive[arm] = len(vals) >= n and below == len(vals)
        print(f"  TARGET [{arm}]: " + ", ".join(f"{v:.1f}" for v in vals)
              + f" -> mean {mean:.1f} ({mean - CONT_ANCHOR_MM:+.1f} vs cont anchor "
              + f"{CONT_ANCHOR_MM}), {below}/{len(vals)} below {COMMERCIAL_MM:.0f}"
              + (" DECISIVE(all reps below)" if decisive[arm] else ""))
    mean, wins, shared = _paired(rep, "racefork", "seq3")
    verdict = "INCOMPLETE"
    if len(shared) >= n:
        print(f"  G2 [racefork vs seq3]: paired mean {mean:+.1f}mm, wins {wins}/{len(shared)}")
        if decisive.get("racefork", False) != decisive.get("seq3", False):
            verdict = ("racefork" if decisive.get("racefork") else "seq3") \
                + " (DECISIVE dominates)"
        elif mean <= -25.0 and wins >= math.ceil(2 * len(shared) / 3):
            verdict = "racefork (G2 margin)"
        elif mean > 0.0 or wins <= len(shared) // 3:
            verdict = "seq3 (racefork NO-GO on G2)"
        else:
            verdict = "BORDERLINE (extend BOTH arms to blocks 81-84, 91-94 and re-evaluate)"
    else:
        print(f"  G2: only {len(shared)}/{n} shared valid reps")
    print(f"  PRODUCTIZATION CANDIDATE -> {verdict}")
    print("  mechanism observables (racefork):")
    for r in rep["runs"]:
        if r["arm"] != "racefork" or not r.get("valid"):
            continue
        rr = r.get("rerun", {})
        agree = rr.get("rerun_at_probe_mm")
        agree_s = f"{agree:.1f}" if isinstance(agree, (int, float)) else "n/a"
        print(f"    r{r['rep']}: probes "
              + " / ".join(f"s{p['seed']}={p.get('width_mm', 'ERR')}" for p in r["probes"])
              + f" | win=s{rr.get('seed')} probe={rr.get('probe_width_mm')} "
              + f"rerun@probe={agree_s} explore_end={rr.get('explore_end_mm')}")
        fks = sorted(fk["marker_mm"] for fk in r.get("forks", []) if fk.get("valid"))
        if fks:
            curve = ", ".join(f"k{k}={v:.1f}" for k, v in _best_of_k_curve(fks).items())
            print(f"      forks({len(fks)} valid) best-of-k E[min]: {curve}")
    members = sorted(m["marker_mm"] for r in rep["runs"]
                     if r["arm"] == "seq3" and r.get("valid")
                     for m in r.get("members", []) if m.get("valid"))
    if members:
        print("  seq3 members (fresh cont@2500 draws for the campaign pool): "
              + ", ".join(f"{v:.1f}" for v in members))
    if args.report2:
        with open(args.report2, encoding="utf-8") as f:
            rep2 = json.load(f)
        mean2, _w2, shared2 = _paired(rep2, args.winner, "seq3")
        if not shared2:
            print(f"G3[{args.winner}]: no shared valid reps -> INCOMPLETE")
        else:
            v = "PASS" if mean2 <= 40.0 else \
                "FAIL (regression >40mm -> productize as per-workload)"
            print(f"G3[{args.winner}] ({rep2['meta']['workload']} "
                  f"×{rep2['meta']['copies']}): paired mean {mean2:+.1f}mm "
                  f"over reps {shared2} -> {v}")
    return 0


def cmd_smoke(args) -> int:
    """Spec §5 smokes on sample_2 ×1 (~5 min): (1) explore-only emits a valid
    state; (2) compress-only from that state runs and does not worsen it;
    (3) two forks with different -s are both valid; (4) mini end-to-end
    pipeline through cmd_run. A missing final_*.json under -e/-c even after
    the 1s fallback is a broken design assumption — escalate, don't paper over."""
    out_dir = os.path.join(REPORTS, "smoke")
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    pieces = _load("sample_2.dxf", 1)
    items, _inst, ipath, _sm = _prepare_instance(pieces, out_dir)
    exe = _resolve_sparrow_path()
    # (1) explore-only emits a valid, G1-clean state
    r1 = _run_sparrow_ec(exe, ipath, 60, 0, 42, os.path.join(out_dir, "s1_explore"))
    w1 = _width_of(r1["ext"])
    _validated_metrics(r1["ext"], items, pieces)
    print(f"smoke1 explore-only: width={w1:.1f} c_used={r1['c_s_used']} OK", flush=True)
    # (2) compress-only from that state; must not worsen it
    r2 = _run_sparrow_ec(exe, r1["final_path"], 0, 60, 43, os.path.join(out_dir, "s2_compress"))
    w2 = _width_of(r2["ext"])
    m2, _u2 = _validated_metrics(r2["ext"], items, pieces)
    assert w2 <= w1 + 0.001, f"compress worsened the state: {w1} -> {w2}"
    print(f"smoke2 compress-only: {w1:.1f} -> {w2:.1f} (marker {m2:.1f}) "
          f"e_used={r2['e_s_used']} OK", flush=True)
    # (3) two forks with different -s, both valid
    r3a = _run_sparrow_ec(exe, r1["final_path"], 0, 15, 1042, os.path.join(out_dir, "s3_forkA"))
    r3b = _run_sparrow_ec(exe, r1["final_path"], 0, 15, 2042, os.path.join(out_dir, "s3_forkB"))
    ma, _ = _validated_metrics(r3a["ext"], items, pieces)
    mb, _ = _validated_metrics(r3b["ext"], items, pieces)
    print(f"smoke3 forks: {ma:.1f} vs {mb:.1f} (divergence expected, not asserted) OK",
          flush=True)
    # (4) mini end-to-end pipeline (block of 2 seeds; tiny budgets)
    args.workload, args.copies = "sample_2.dxf", 1
    args.arms, args.blocks = "seq3,racefork", "42,43"
    args.seq_n, args.seq_budget = 2, 30
    args.probe_s, args.explore_s, args.k_forks, args.compress_s = 15, 30, 2, 15
    args.ttl_hours = 1.0
    rc = cmd_run(args)
    print("SMOKE PASS" if rc == 0 else f"SMOKE FAIL: rc={rc}")
    return 0 if rc == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _run_args(p):
        p.add_argument("--workload", default="sample_2.dxf")
        p.add_argument("--copies", type=int, default=10)
        p.add_argument("--arms", default="seq3,racefork")
        p.add_argument("--blocks", default=DEFAULT_BLOCKS)
        p.add_argument("--seq-n", type=int, default=SEQ_N, dest="seq_n")
        p.add_argument("--seq-budget", type=int, default=SEQ_BUDGET_S, dest="seq_budget")
        p.add_argument("--probe-s", type=int, default=PROBE_S, dest="probe_s")
        p.add_argument("--explore-s", type=int, default=EXPLORE_S, dest="explore_s")
        p.add_argument("--k-forks", type=int, default=K_FORKS, dest="k_forks")
        p.add_argument("--compress-s", type=int, default=COMPRESS_S, dest="compress_s")
        p.add_argument("--ttl-hours", type=float, default=14.0, dest="ttl_hours")

    _run_args(sub.add_parser("run"))
    p_ev = sub.add_parser("evaluate")
    p_ev.add_argument("--report", required=True)
    p_ev.add_argument("--report2")
    p_ev.add_argument("--winner", default="racefork")
    _run_args(sub.add_parser("smoke"))   # smoke overrides these itself
    args = ap.parse_args()
    return {"run": cmd_run, "evaluate": cmd_evaluate, "smoke": cmd_smoke}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
