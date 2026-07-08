# Warm-Start Budget Curve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Characterize warm-started sparrow's marker mean vs budget (600/1200/2500s × 3 matched seeds) to find where the mean crosses the 10599mm commercial target and where the curve flattens.

**Architecture:** One throwaway spike script — the preserved GA-round runner with three deltas (reports dir, arms, characterization `evaluate`) — drives per-budget arms that all share ONE Fast warm-start instance file against the vendored `sparrow.exe`. Zero production/engine-module changes; the deliverable is a curve + protocol record.

**Tech Stack:** Python 3.11 (engine venv), `auto_layout_polygon` Fast tier, `separation.py` private helpers, vendored `sparrow.exe`.

**Spec:** `docs/superpowers/specs/2026-07-07-budget-curve-design.md` (approved 2026-07-07).

## Global Constraints

- Canonical protocol: `sample_2.dxf` ×10 copies, fabric **1651.0mm**, grain **bi @90°**, matched seeds **42,43,44**, strictly sequential, quiet box (~3h40m wall; overnight-friendly; TTL 6h).
- Arms: `b600:fast:600`, `b1200:fast:1200`, `b2500:fast:2500` — ALL production Fast warm start (`auto_layout_polygon(..., effort=1)`), solo runs; the seed is built ONCE, validator-gated (G1), ONE instance file shared by every run; arms differ only by `-t`.
- Seed-major interleave: each seed's 600→1200→2500 trio runs consecutively.
- Hard constraints unchanged: no mirroring, no tilt, grain both ways, edges touchable; `separation._validate_layout` gates the seed AND all finals.
- **No production module changes**; the only engine file added is the spike script, deleted at verdict on BOTH paths.
- Decision rules (spec §3): **CROSSED at B** := mean(B) < **10599.0** AND ≥2/3 seeds < 10599.0 (arm must have all n seeds valid); smallest crossed B → proposed new Ultra default (follow-up mini-PR, out of scope); **DECISIVE** = any budget crossed; **borderline** = |mean(B) − 10599| ≤ 15.0 → extend THAT budget to seeds 45,46 before declaring; **flattening readout** = Δmean/100s per consecutive pair (informational; single-run spreads on record ~45–120mm).
- Reference anchors: Fast seed 11393.2mm (~27s prelude); fresh 600s control means 10615.7 (PR #19 round) / 10651.4 (PR #20 round); PR #20 ctl780 754s → mean 10621.2; cold plateau 10722.7 ± 120; commercial 10599. Wall sanity: each run's `wall_s` ≈ `-t` + a few seconds.
- Reports/workdirs under `tools/budget-curve/` — covered by the blanket `tools/` gitignore line; NO `.gitignore` edit. Workdirs keep `output/log.txt` + `sols_*/` SVGs.
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Context for implementers

- `WT` = the worktree root the user created (e.g. `D:\openmarker\.worktrees\openmarker-budget-curve`), branch `feat/budget-curve`; main tree stays on `main` at `D:\openmarker`.
- Engine venv ONLY in the main tree: `D:\openmarker\engine\.venv\Scripts\python.exe`; pytest as `python -m pytest` with CWD `WT\engine`.
- Fixtures `sample_2.dxf`/`sample_4.dxf` are NOT in git — Task 1 copies them (sample_4 only for suite parity; this round is single-workload).
- The runner is the GA-round script (preserved in `docs/superpowers/plans/2026-07-07-ga-warmstart.md` Task 2) with three deltas; Task 2 below embeds the COMPLETE final script — transcribe from here, not from the old plan.

---

### Task 1: Worktree preflight + docs on branch

**Files:**
- Create (copy in, gitignored): `WT\examples\input\sample_2.dxf`, `WT\examples\input\sample_4.dxf` (plus any other fixture the baseline suite needs — copy all of `D:\openmarker\examples\input\` if 259 doesn't reproduce)
- Create (committed): `WT\docs\superpowers\specs\2026-07-07-budget-curve-design.md`, `WT\docs\superpowers\plans\2026-07-07-budget-curve.md` (copied from the main tree)
- Modify: `WT\docs\planning\BACKLOG.md` (append execution checklist)

**Interfaces:**
- Consumes: nothing.
- Produces: verified worktree; spec/plan/BACKLOG committed on `feat/budget-curve`.

- [ ] **Step 1: Verify worktree + branch**

```powershell
cd WT
git rev-parse --abbrev-ref HEAD
git status --short
```
Expected: `feat/budget-curve`, clean. If missing, STOP and ask the user to create it.

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
Copy-Item D:\openmarker\docs\superpowers\specs\2026-07-07-budget-curve-design.md WT\docs\superpowers\specs\
Copy-Item D:\openmarker\docs\superpowers\plans\2026-07-07-budget-curve.md WT\docs\superpowers\plans\
```

- [ ] **Step 5: Append the execution checklist at the end of `WT\docs\planning\BACKLOG.md`**

```markdown
### Budget-curve round (spec 2026-07-07) Execution Checklist

- [ ] P1: Worktree preflight + spec/plan/BACKLOG committed on branch
- [ ] P2: Spike runner + smoke (3 arms × 15s × 1 copy)
- [ ] P3: Curve matrix — b600/b1200/b2500 × seeds 42/43/44 (~3h40m)
- [ ] P4: Curve evaluation + verdict [USER CHECKPOINT]
- [ ] P5: Cleanup — delete spike (both paths), rescue reports
- [ ] P6: Docs (PERFORMANCE §6 entry), BACKLOG outcome, PR, final review
```

- [ ] **Step 6: Commit**

```powershell
cd WT
git add docs/superpowers/specs/2026-07-07-budget-curve-design.md docs/superpowers/plans/2026-07-07-budget-curve.md docs/planning/BACKLOG.md
git commit -m "docs: spec + plan + BACKLOG checklist for the budget-curve round

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Spike runner + smoke

**Files:**
- Create: `WT\engine\tests\spike_budget_curve.py` (throwaway; deleted in Task 5)

**Interfaces:**
- Consumes: `auto_layout_polygon(..., effort=1)`; `separation._group_to_items / _instance_json / _placements_to_jagua / _reconstruct / _resolve_sparrow_path / _validate_layout`; `heuristic._compute_metrics / _polygon_dims`.
- Produces: `tools/budget-curve/reports/<workload>_x<copies>/report.json` (same schema as the GA round: meta.arms as `[name, source, budget_s]` triples, meta.seeds_meta per source, per-run rows with `seed_source`/`budget_s`/`workdir`) + `report.md`; subcommands `smoke`/`run`/`evaluate`. Exit codes 0/1/2.

- [ ] **Step 1: Write the spike script**

```python
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
```

- [ ] **Step 2: Smoke run (3 arms × 15s × 1 copy, ~2 min)**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_budget_curve.py smoke
```
Expected: one `seed[fast]` line, three `marker=… util=… wall=…` lines, `SMOKE PASS`, exit 0. Sanity-check `WT\tools\budget-curve\reports\sample_2_x1\report.json` (all rows valid; `budget_s` = 15/20/25 per arm) and `git status --short` (nothing under `tools/`). Also run the evaluator against the smoke report to exercise its code path end-to-end:

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_budget_curve.py evaluate --report tools\budget-curve\reports\sample_2_x1\report.json
```
Expected: three per-arm lines (each arm shows its single seed → `1/1 below 10599` and a CROSSED flag — expected at 1 copy, where markers are ~1140mm; the rule is only meaningful at ×10), a 2-row marginal table with real +5s deltas, and a DECISIVE line — no crash, no NaN. (The rate guard prints `n/a (equal budgets)` if arms share a budget.)

- [ ] **Step 3: Commit**

```powershell
cd WT
git add engine/tests/spike_budget_curve.py
git commit -m "test(engine): throwaway spike runner for the warm-start budget curve

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Curve matrix — b600/b1200/b2500 × seeds 42/43/44 (~3h40m)

**Files:** none (produces `WT\tools\budget-curve\reports\sample_2_x10\report.{json,md}` — gitignored).

**Interfaces:**
- Consumes: Task 2's `run`.
- Produces: the curve report consumed by Task 4.

- [ ] **Step 1: Preflight — quiet box, long window**

Confirm ~4 quiet hours (sparrow `-t` is wall-clock). Overnight is ideal.

- [ ] **Step 2: Launch in the background**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_budget_curve.py run --workload sample_2.dxf --copies 10 --arms b600:fast:600,b1200:fast:1200,b2500:fast:2500 --seeds 42,43,44 --ttl-hours 6
```
Check the first line: `seed[fast]` ≈ 11393.2mm. Then one run lands every 10/20/42 minutes (per-seed trio ≈ 72 min). Wall sanity per row: `wall_s` ≈ `-t` + a few seconds; a large excess means a loaded box — re-run those pairs later via resume.

- [ ] **Step 3: On completion, verify**

```powershell
Get-Content WT\tools\budget-curve\reports\sample_2_x10\report.md
```
Expected: 9 rows, all `valid: True`, exit 0. Exit 1 → inspect `error`, re-run (resume). Exit 2 → re-run the same command to finish.

---

### Task 4: Curve evaluation + verdict  **[USER CHECKPOINT]**

**Files:** none.

**Interfaces:**
- Consumes: Task 3's report; Task 2's `evaluate`.
- Produces: the crossing/flattening verdict that selects Task 6's docs branch (and possibly extensions).

- [ ] **Step 1: Evaluate**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_budget_curve.py evaluate --report tools\budget-curve\reports\sample_2_x10\report.json
```

- [ ] **Step 2: If any budget prints BORDERLINE — extend that budget's seeds first**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_budget_curve.py run --workload sample_2.dxf --copies 10 --arms b600:fast:600,b1200:fast:1200,b2500:fast:2500 --seeds 42,43,44,45,46 --ttl-hours 8
```
Resume skips all completed pairs; this adds up to 6 runs. If only ONE budget is borderline and wall time matters, narrow `--arms` to just that arm (plus none others) for the extension — the report merges. Re-run Step 1; with n=5 the crossing needs ≥4/5 below (the evaluator's `3*below >= 2*len` handles it: for len=5 it requires below ≥ 4).

- [ ] **Step 3: If the 1200→2500 shape is surprising (non-monotone or sharp bend) — optional 1800s backfill (~1h30m)**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_budget_curve.py run --workload sample_2.dxf --copies 10 --arms b600:fast:600,b1200:fast:1200,b1800:fast:1800,b2500:fast:2500 --seeds 42,43,44 --ttl-hours 3
```

- [ ] **Step 4: Present the verdict to the user — STOP and wait**

Present: the curve table (per-seed + means + n-below per budget, with PR #20's 754s point 10621.2 as an interpolation cross-check), the marginal-value table, the CROSSED/DECISIVE outcome, and the flattening reading (lever (f)'s proposed test budget). The user chooses:
- **CROSSED** at some B → Task 5 + Task 6 with the crossed docs (default-budget follow-up filed in BACKLOG).
- **Not crossed** → Task 5 + Task 6 with the not-crossed docs (curve recorded; (f) test budget named; no follow-up).

---

### Task 5: Cleanup — delete the spike (BOTH paths), rescue reports

**Files:**
- Delete: `WT\engine\tests\spike_budget_curve.py`

- [ ] **Step 1: Delete**

```powershell
cd WT
git rm engine/tests/spike_budget_curve.py
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
git commit -m "chore(engine): remove budget-curve spike after verdict (code preserved in the plan doc)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Rescue reports**

```powershell
New-Item -ItemType Directory -Force D:\openmarker\tools\budget-curve\reports
Copy-Item WT\tools\budget-curve\reports\* D:\openmarker\tools\budget-curve\reports\ -Recurse -Force
```
Verify `D:\openmarker\tools\budget-curve\reports\sample_2_x10\report.json` exists.

---

### Task 6: Docs + BACKLOG + PR

**Files:**
- Modify: `WT\docs\planning\PERFORMANCE.md` (§ 6 entry — the record; no § 5.B row), `WT\docs\planning\BACKLOG.md` (ticks + outcome + conditional follow-up)

- [ ] **Step 1: PERFORMANCE.md § 6 entry** (append at the end of § 6; fill every `<...>` from the report):

```markdown
### <YYYY-MM-DD> — Warm-start budget curve (600/1200/2500s): <CROSSED at <B>s / NOT CROSSED>

- **What / why:** Characterized follow-up (d) of § 6 [2026-06-09] warm (the old
  "600→1200 = +0.39pp, diminishing" was a COLD-era measurement), motivated by
  the GA round's +154s = −30.3mm (3/3) dose-response. All arms = production
  Fast warm start, solo runs, matched seeds <seeds>, seed-major trios,
  validator-gated seed + finals.
- **Seed:** fast <mm>mm / <util>% (prelude <s>s).
- **Curve (final markers, mm):**

| budget | s42 | s43 | s44 | mean | below 10599 |
| --- | --- | --- | --- | --- | --- |
| 600s | <mm> | <mm> | <mm> | <mm> | <n>/3 |
| 1200s | <mm> | <mm> | <mm> | <mm> | <n>/3 |
| 2500s | <mm> | <mm> | <mm> | <mm> | <n>/3 |

  (754s cross-check from § 6 [2026-07-07 GA A/B]: mean 10621.2 — <fits/deviates
  from> the interpolation.)
- **Marginal value:** 600→1200: <±mm> (<±mm>/100s); 1200→2500: <±mm>
  (<±mm>/100s). Flattest segment: <which> → lever (f) test budget <B>s.
- **Decision rules:** CROSSED = mean < 10599 AND ≥2/3 seeds below; borderline
  ±15mm → extend seeds. Outcome: <the crossing/DECISIVE result; borderline
  extensions run or not>.
- **Decision:** <CROSSED at <B>s → default-budget follow-up mini-PR filed
  (QUALITY_BUDGETS_S["ultra"] + GUI default) / NOT CROSSED → curve recorded;
  lever (f) next at <B>s>. Spike deleted, code preserved in
  `docs/superpowers/plans/2026-07-07-budget-curve.md`; reports under
  `tools/budget-curve/reports/` (gitignored, local-only).
```

- [ ] **Step 2: BACKLOG.md** — tick executed items (P-numbers per the actual path; annotate skips), add the outcome line:

```markdown
- Outcome: <CROSSED at <B>s / NOT CROSSED> — means 600s <mm> / 1200s <mm> /
  2500s <mm>; marginal <±mm>/100s then <±mm>/100s; DECISIVE: <yes/no>;
  lever (f) test budget: <B>s. See PERFORMANCE.md § 6.
```

If CROSSED, also append:

```markdown
- [ ] Follow-up (CROSSED): bump the Ultra DEFAULT budget to <B>s —
  QUALITY_BUDGETS_S["ultra"] + frontend QualityPanel default (+ tests, cache-key
  unchanged: budget already in the dedup key) — small product PR.
```

- [ ] **Step 3: Commit docs**

```powershell
cd WT
git add docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git commit -m "docs(perf): warm-start budget curve protocol record (<OUTCOME>)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Hand back to the controller** for the final whole-branch review, push, `gh pr create` (results table + the standing `.gitignore` merge note + 🤖 attribution), and the established merge choreography on the user's word.

---

## Verdict paths (summary)

- **CROSSED:** Tasks 1–4 + 5 + 6 (crossed docs; default-budget follow-up filed).
- **NOT CROSSED:** Tasks 1–4 + 5 + 6 (curve recorded; lever (f) budget named; no follow-up).
- **BORDERLINE / surprising shape:** resolved inside Task 4 (seed extension / 1800s backfill) before the verdict.
