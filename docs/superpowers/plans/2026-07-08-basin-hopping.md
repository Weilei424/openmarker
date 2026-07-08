# Segment-Chained Basin Hopping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A/B segment-chained basin hopping (K fresh sparrow processes re-seeded from the validated best-so-far) against a continuous run at 2500s equal wall, under the established protocol.

**Architecture:** One throwaway spike script — the preserved budget-curve runner with the execution mode generalized to `name:chainK:budget` — chains K sparrow segments through the production converter round-trip (`_reconstruct` → `_validate_layout` → `_placements_to_jagua`), keeping the best valid marker explicitly. `cont` ≡ `chain1` through the same code path. Zero engine-module changes.

**Tech Stack:** Python 3.11 (engine venv), `auto_layout_polygon` Fast tier, `separation.py` private helpers, vendored `sparrow.exe`.

**Spec:** `docs/superpowers/specs/2026-07-08-basin-hopping-design.md` (approved 2026-07-08).

## Global Constraints

- Canonical protocol: `sample_2.dxf` ×10 copies, fabric **1651.0mm**, grain **bi @90°**, matched seeds **42,43,44**, strictly sequential, quiet box (~6h20m wall — overnight; TTL 9h).
- Arms: `cont:chain1:2500`, `chain2:chain2:2500`, `chain5:chain5:2500`. Segment 1 of every arm starts from ONE shared production Fast warm-start instance (built once, G1-gated).
- Chain step (spec §2): segment `final_*.json` → `_reconstruct` → `_validate_layout` → `_compute_metrics` → if best valid so far, `_placements_to_jagua` + `strip_width = marker + 1.0` → next segment's `{**instance, "solution": …}`. Segment j (1-based) runs `-s seed + 1000·(j−1)`, `-t budget//K` (remainder to the last segment). **Keep-best explicit**: arm result = min valid marker across segments. Failure ladder: invalid segment → log + continue from prior best; segment 1 invalid → the (arm, seed) row is invalid (resume re-runs).
- Hard constraints unchanged: no mirroring, no tilt, grain both ways, edges touchable; `_validate_layout` gates the seed, every segment, and every final.
- **No production module changes**; the spike is deleted at verdict on BOTH paths.
- Gates (spec §3): **G2** per chain arm vs `cont`, paired: GO = mean ≤ **−25.0mm** AND wins ≥ 2/3; NO-GO = mean > 0 or wins ≤ 1/3; borderline (mean in (−25, 0] with ≥2 wins) → extend the involved arms + `cont` to seeds 45,46. **TARGET readout** per arm: mean vs 10599.0 + n-below; **DECISIVE** = any arm with all 3 seeds < 10599.0. **Segment telemetry**: a GO must show improvement in segments ≥ 2 to confirm the mechanism (segment-1-only improvement = budget artifact — call it out). **G3** (GO only): winning arm vs `cont` on `sample_4.dxf` ×6 @2500s seed 42, FAIL if worse by > **40.0mm**.
- Anchors: Fast seed 11393.2mm (~27s prelude); budget-curve 2500s row 10558.6/10612.6/10599.6 (mean 10590.3) — `cont` should land nearby; commercial 10599; all-time best single 10558.6; cold plateau 10722.7 ± 120. Per-segment `wall_s` ≈ its `-t` + a few seconds.
- Reports/workdirs under gitignored `tools/basin-hopping/` (blanket `tools/` line; NO `.gitignore` edit); per-segment workdirs `runs/<arm>_s<seed>/seg<j>/` keep `output/log.txt` + `sols_*/` SVGs.
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Context for implementers

- `WT` = the worktree root the user created (e.g. `D:\openmarker\.worktrees\openmarker-basin-hop`), branch `feat/basin-hopping`; main tree stays on `main` at `D:\openmarker`.
- Engine venv ONLY in the main tree: `D:\openmarker\engine\.venv\Scripts\python.exe`; pytest as `python -m pytest` with CWD `WT\engine`.
- Fixtures are NOT in git — Task 1 copies all of `D:\openmarker\examples\input\`.
- The base runner is the budget-curve script (preserved in `docs/superpowers/plans/2026-07-07-budget-curve.md` Task 2); Task 2 below embeds the COMPLETE chained variant — transcribe from here.

---

### Task 1: Worktree preflight + docs on branch

**Files:**
- Create (copy in, gitignored): all of `WT\examples\input\`
- Create (committed): `WT\docs\superpowers\specs\2026-07-08-basin-hopping-design.md`, `WT\docs\superpowers\plans\2026-07-08-basin-hopping.md` (copied from the main tree)
- Modify: `WT\docs\planning\BACKLOG.md` (append execution checklist)

**Interfaces:**
- Consumes: nothing.
- Produces: verified worktree; spec/plan/BACKLOG committed on `feat/basin-hopping`.

- [ ] **Step 1: Verify worktree + branch**

```powershell
cd WT
git rev-parse --abbrev-ref HEAD
git status --short
```
Expected: `feat/basin-hopping`, clean. If missing, STOP and ask the user to create it.

- [ ] **Step 2: Copy fixtures**

```powershell
New-Item -ItemType Directory -Force WT\examples\input
Copy-Item D:\openmarker\examples\input\* WT\examples\input\ -Force
```

- [ ] **Step 3: Baseline test run**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: 259 passed. Any failure = pre-existing breakage — STOP and report.

- [ ] **Step 4: Copy spec + plan into the worktree**

```powershell
Copy-Item D:\openmarker\docs\superpowers\specs\2026-07-08-basin-hopping-design.md WT\docs\superpowers\specs\
Copy-Item D:\openmarker\docs\superpowers\plans\2026-07-08-basin-hopping.md WT\docs\superpowers\plans\
```

- [ ] **Step 5: Append the execution checklist at the end of `WT\docs\planning\BACKLOG.md`**

```markdown
### Basin-hopping round (spec 2026-07-08) Execution Checklist

- [ ] P1: Worktree preflight + spec/plan/BACKLOG committed on branch
- [ ] P2: Spike runner + smoke (chain plumbing on 1 copy)
- [ ] P3: Matrix — cont/chain2/chain5 × seeds 42/43/44 @2500s (~6h20m)
- [ ] P4: Gate evaluation + verdict [USER CHECKPOINT]
- [ ] P5: Conditional GO: sample_4×6 G3 guard @2500s
- [ ] P6: Cleanup — delete spike (both paths), rescue reports
- [ ] P7: Docs (PERFORMANCE §6 entry), BACKLOG outcome, PR, final review
```

- [ ] **Step 6: Commit**

```powershell
cd WT
git add docs/superpowers/specs/2026-07-08-basin-hopping-design.md docs/superpowers/plans/2026-07-08-basin-hopping.md docs/planning/BACKLOG.md
git commit -m "docs: spec + plan + BACKLOG checklist for the basin-hopping round

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Spike runner + smoke

**Files:**
- Create: `WT\engine\tests\spike_basin_hopping.py` (throwaway; deleted in Task 6)

**Interfaces:**
- Consumes: `auto_layout_polygon(..., effort=1)`; `separation._group_to_items / _instance_json / _placements_to_jagua / _reconstruct / _resolve_sparrow_path / _validate_layout`; `heuristic._compute_metrics / _polygon_dims`.
- Produces: `tools/basin-hopping/reports/<workload>_x<copies>/report.json` with per-run rows `{"arm", "seed", "k", "budget_s", "marker_mm", "util_pct", "wall_s", "valid", "error?", "segments": [{"seg", "budget_s", "marker_mm?", "wall_s", "snapshots", "log_lines", "improved", "error?"}], "workdir"}` + `report.md`; subcommands `smoke`/`run`/`evaluate` (with `--report2`/`--winner` for G3). Exit codes 0/1/2.

- [ ] **Step 1: Write the spike script**

```python
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
```

- [ ] **Step 2: Smoke run (~2–3 min: Fast prelude + 15s + 2×8s + 5×6s of sparrow + chain overhead)**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_basin_hopping.py smoke
```
Expected: one `seed[fast]` line, three run lines — `cont`'s with one segment marker, `chain2`'s with two, `chain5`'s with five (each `segs=[...]` entry a ~1140mm value, first always `*`) — then `SMOKE PASS`, exit 0. Then exercise the evaluator end-to-end:

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_basin_hopping.py evaluate --report tools\basin-hopping\reports\sample_2_x1\report.json
```
Expected: TARGET lines for all three arms, G2 lines for chain2/chain5 vs cont (single-seed, so INCOMPLETE or 1-seed pairing — fine at smoke), segment traces with `late-segment improvements: <n>`, no crash. Sanity-check `report.json`: chain5's row has 5 `segments` entries with per-segment workdirs `runs\chain5_s42\seg1..seg5` on disk, and `git status --short` shows nothing under `tools/`.

- [ ] **Step 3: Commit**

```powershell
cd WT
git add engine/tests/spike_basin_hopping.py
git commit -m "test(engine): throwaway spike runner for segment-chained basin hopping

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Matrix — cont/chain2/chain5 × seeds 42/43/44 @2500s (~6h20m)

**Files:** none (produces `WT\tools\basin-hopping\reports\sample_2_x10\report.{json,md}` — gitignored).

- [ ] **Step 1: Preflight — quiet box, overnight window**

Confirm ~7 quiet hours. This is the longest bench of the series.

- [ ] **Step 2: Launch in the background**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_basin_hopping.py run --workload sample_2.dxf --copies 10 --arms cont:chain1:2500,chain2:chain2:2500,chain5:chain5:2500 --seeds 42,43,44 --ttl-hours 9
```
First line: `seed[fast]` ≈ 11393.2mm. Each seed's trio ≈ 2h05m (cont ~42min, chain2 ~42min, chain5 ~42min + chain overhead). Per-segment wall sanity: ≈ its `-t` + a few seconds. `cont` should land near the budget-curve 2500s row (10558.6/10612.6/10599.6).

- [ ] **Step 3: On completion, verify**

```powershell
Get-Content WT\tools\basin-hopping\reports\sample_2_x10\report.md
```
Expected: 9 rows, all `valid: True`, exit 0; chain rows carry their segment-marker traces. Exit 1 → inspect `error`, re-run (resume). Exit 2 → re-run to finish.

---

### Task 4: Gate evaluation + verdict  **[USER CHECKPOINT]**

**Files:** none.

- [ ] **Step 1: Evaluate**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_basin_hopping.py evaluate --report tools\basin-hopping\reports\sample_2_x10\report.json
```

- [ ] **Step 2: If a G2 verdict is BORDERLINE — extend the involved arms + cont**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_basin_hopping.py run --workload sample_2.dxf --copies 10 --arms cont:chain1:2500,chain2:chain2:2500,chain5:chain5:2500 --seeds 42,43,44,45,46 --ttl-hours 10
```
(Resume skips completed pairs; narrow `--arms` to the borderline arm + `cont` if wall time matters — each added (arm, seed) pair costs ~42min.) Re-run Step 1; n=5 GO needs wins ≥ 4.

- [ ] **Step 3: Present the verdict to the user — STOP and wait**

Present: the 3×3 finals table, both paired comparisons vs `cont`, the TARGET readout (with the DECISIVE flag if any arm has all seeds < 10599), the segment traces with late-segment improvement counts (mechanism confirmation: a GO must show improvement beyond segment 1 — a segment-1-only GO is a budget artifact and must be called out), and `cont`'s agreement with the budget-curve anchor. The user chooses:
- any chain arm **GO** → Task 5 (G3), then Task 6+7 with the GO docs (productization follow-up incl. best-so-far-on-Stop / Continue-refining filed).
- all **NO-GO** → Task 6+7 with the NO-GO docs (remaining measured lever: best-of-N composition at 2500s).

---

### Task 5: G3 regression guard on sample_4 ×6 @2500s  **[conditional: GO]**

**Files:** none (produces `WT\tools\basin-hopping\reports\sample_4_x6\report.{json,md}`).

- [ ] **Step 1: Run the guard (2 × 2500s ≈ 1h25m; substitute the actual winner)**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_basin_hopping.py run --workload sample_4.dxf --copies 6 --arms cont:chain1:2500,chain2:chain2:2500 --seeds 42 --ttl-hours 2
```

- [ ] **Step 2: Evaluate both reports**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_basin_hopping.py evaluate --report tools\basin-hopping\reports\sample_2_x10\report.json --report2 tools\basin-hopping\reports\sample_4_x6\report.json --winner chain2
```
Expected: `G3[...] -> PASS` or `FAIL (...)`. FAIL ⇒ Task 7's docs state productization as per-workload.

---

### Task 6: Cleanup — delete the spike (BOTH paths), rescue reports

**Files:**
- Delete: `WT\engine\tests\spike_basin_hopping.py`

- [ ] **Step 1: Delete**

```powershell
cd WT
git rm engine/tests/spike_basin_hopping.py
```

- [ ] **Step 2: Suite green**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: 259 passed.

- [ ] **Step 3: Commit**

```powershell
cd WT
git commit -m "chore(engine): remove basin-hopping spike after verdict (code preserved in the plan doc)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Rescue reports**

```powershell
New-Item -ItemType Directory -Force D:\openmarker\tools\basin-hopping\reports
Copy-Item WT\tools\basin-hopping\reports\* D:\openmarker\tools\basin-hopping\reports\ -Recurse -Force
```
Verify `D:\openmarker\tools\basin-hopping\reports\sample_2_x10\report.json` exists.

---

### Task 7: Docs + BACKLOG + PR

**Files:**
- Modify: `WT\docs\planning\PERFORMANCE.md` (§ 6 entry — the record; no § 5.B row), `WT\docs\planning\BACKLOG.md` (ticks + outcome + conditional follow-up)

- [ ] **Step 1: PERFORMANCE.md § 6 entry** (append at the end of § 6; fill every `<...>` from the reports):

```markdown
### <YYYY-MM-DD> — Segment-chained basin hopping (2500s equal wall): <VERDICT>

- **What / why:** Tested lever (f) at the budget the § 6 [2026-07-08] curve
  named (1200→2500s flattens to −2.16mm/100s): K fresh sparrow processes per
  run, each re-seeded via `-i` from the VALIDATED best-so-far layout
  (production converter round-trip, per-segment G1) with RNG seed+1000·(j−1) —
  resetting GLS weights / shrink schedule / trajectory while carrying the best
  layout. Keep-best explicit; cont ≡ chain1; chain arms pay their own
  orchestration overhead (conservative). Matched seeds <seeds>, sequential.
- **Seed:** fast <mm>mm / <util>% (prelude <s>s).
- **Result (final markers, mm):**

| arm | s42 | s43 | s44 | mean | vs cont (paired) | wins | below 10599 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cont | <mm> | <mm> | <mm> | <mm> | — | — | <n>/3 |
| chain2 | <mm> | <mm> | <mm> | <mm> | <±mm> | <n>/3 | <n>/3 |
| chain5 | <mm> | <mm> | <mm> | <mm> | <±mm> | <n>/3 | <n>/3 |

  (cont anchor: budget-curve 2500s row mean 10590.3 — <agrees/deviates>.)
- **Segment mechanism readout:** late-segment (≥2) improvements per chain run:
  <counts per run>; <interpretation: restarts finding new basins vs riding
  segment 1>.
- **Gates:** G1 <all valid — seed, every segment, every final>; G2[chain2]
  <verdict> (<±mm>, <n>/3); G2[chain5] <verdict> (<±mm>, <n>/3); DECISIVE
  (any arm all seeds < 10599): <yes/no — which arm>; G3 (sample_4×6 @2500s,
  GO only): <PASS/FAIL/not run>.
- **Interpretation:** <what the segment traces say about the stagnation
  hypothesis; K=2 vs K=5 direction; composition implications with best-of-N>.
- **Decision:** <GO → productization follow-up filed (chaining in
  run_separation_layout + best-so-far-on-Stop + Continue-refining) / NO-GO →
  lever (f) closed; remaining measured lever = best-of-N at 2500s>. Spike
  deleted, code preserved in `docs/superpowers/plans/2026-07-08-basin-hopping.md`;
  reports under `tools/basin-hopping/reports/` (gitignored, local-only).
```

- [ ] **Step 2: BACKLOG.md** — tick executed items (P5 annotated `(skipped — <reason>)` if not run), add the outcome line:

```markdown
- Outcome: <VERDICT> — chain2 <±mm> (<n>/3), chain5 <±mm> (<n>/3) paired vs
  cont @2500s equal wall; cont mean <mm> (anchor 10590.3); late-segment
  improvements: <summary>; DECISIVE: <yes/no>. See PERFORMANCE.md § 6.
```

On **GO**, also append:

```markdown
- [ ] Follow-up (GO): wire segment chaining into `run_separation_layout`
  (segment scheduling inside ultra_budget_s; cancellation across segments via
  the existing kill registry) + ship best-so-far-on-Stop and "Continue
  refining" from the same converter machinery — separate spec/plan/PR.
```

- [ ] **Step 3: Commit docs**

```powershell
cd WT
git add docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git commit -m "docs(perf): segment-chained basin hopping protocol record (<VERDICT>)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Hand back to the controller** for the final whole-branch review, push, `gh pr create` (results + segment traces + the standing `.gitignore` merge note + 🤖 attribution), and the established merge choreography on the user's word.

---

## Verdict paths (summary)

- **GO:** Tasks 1–5 + 6 + 7 (GO docs; productization + Stop/Continue follow-up filed).
- **NO-GO:** Tasks 1–4 + 6 + 7 (NO-GO docs; best-of-N at 2500s named as the remaining measured lever).
- **BORDERLINE:** resolved inside Task 4 (seed extension on the involved arms + cont) before choosing a path.
