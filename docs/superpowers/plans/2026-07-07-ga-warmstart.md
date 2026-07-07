# GA-Layout Warm-Start Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A/B the GA layout (the only seed denser than Fast-BLF) as sparrow's warm start at equal total time, under the established noise-floor protocol.

**Architecture:** One throwaway spike script (adapted from the preserved lattice-round runner) drives three arms that differ by `(seed_source, sparrow_budget)` against the vendored `sparrow.exe` through the production warm-start converter. Zero production or engine-module changes; the deliverable is a verdict + protocol record.

**Tech Stack:** Python 3.11 (engine venv), existing `auto_layout_polygon` (Fast + GA tiers), `separation.py` private helpers, vendored `sparrow.exe`.

**Spec:** `docs/superpowers/specs/2026-07-06-ga-warmstart-design.md` (approved 2026-07-06).

## Global Constraints

- Canonical protocol: `sample_2.dxf` ×10 copies, fabric **1651.0mm**, grain **bi @90°**, matched seeds **42,43,44**, strictly sequential runs on a quiet box.
- Arms (equal-envelope design): `prod` = Fast seed + **600s** sparrow (~626s envelope); `ctl780` = Fast seed + **754s** sparrow (~780s envelope); `ga` = GA Better-tier seed (~180s prelude) + **600s** sparrow (~780s envelope). Same vendored exe everywhere; arms differ ONLY by the `-i` instance's embedded seed and the `-t` budget.
- GA seed = the production Better tier verbatim: `auto_layout_polygon(pieces, 1651.0, "bi", 90.0, effort=4, ga_generations=12, ga_max_time_s=180.0, ga_seed=42)` — deterministic; time binds on the canonical workload (prelude ≈ 180s). Fast seed = `effort=1`.
- Each seed SOURCE built ONCE per invocation, validator-gated (**G1 applies to seeds**), shared across arms/runs (`prod` and `ctl780` share one instance file).
- Hard constraints unchanged: no mirroring, no tilt, grain enforced both ways, edges touchable; `separation._validate_layout` gates seeds AND finals.
- **No production module changes**; the only file this branch adds to `engine/` is the spike script, deleted at verdict on BOTH paths (spec §6).
- Gates (spec §5): **G2-product (PRIMARY, ships/kills)** = `ga` vs `ctl780`: GO at paired mean ≤ **−25.0mm** AND wins ≥ 2/3; NO-GO at mean > 0 or wins ≤ 1/3; borderline → extend ALL arms to seeds 45,46. **G2-mechanism (secondary, reported)** = `ga` vs `prod`, same thresholds, gates nothing. **DECISIVE** = all `ga` finals < **10599.0mm**. **G3** (GO only) = `ga` vs `prod` on `sample_4.dxf` ×6 @600s seed 42, FAIL if worse by > **40.0mm**.
- Interpretation grid (spec §5): product-GO ⇒ ship path; product-NO-GO + mechanism-GO ⇒ file "cheaper GA prelude (60–90s `ga_max_time_s` cap)" follow-up; both-NO-GO ⇒ lever closed.
- Reference anchors: `prod` finals ≈ 2026-07-05 fresh control (10584.2/10638.5/10624.4, mean 10615.7); GA seed ≈ 11232.3mm; Fast seed 11393.2mm; cold plateau 10722.7mm ± 120 (n=21); commercial 10599mm.
- Reports/workdirs under `tools/ga-warmstart-spike/` — covered by the repo's blanket `tools/` gitignore line; **no `.gitignore` edit** (lattice-round correction). Per-run workdirs keep `output/log.txt` (the real log — stderr is empty) + `output/sols_*/` **SVG** snapshots.
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Context for implementers

- `WT` below = the worktree root the user created (e.g. `D:\openmarker\.worktrees\openmarker-ga-warm`), branch `feat/ga-warmstart`. The main tree stays on `main` at `D:\openmarker`.
- The engine venv lives ONLY in the main tree: `D:\openmarker\engine\.venv\Scripts\python.exe`. Run pytest as `python -m pytest` with CWD `WT\engine`.
- Fixtures `sample_2.dxf` / `sample_4.dxf` are NOT in git — Task 1 copies them in.
- Key existing interfaces (do not modify): `separation._group_to_items / _instance_json / _placements_to_jagua / _reconstruct / _validate_layout / _resolve_sparrow_path` and `heuristic.auto_layout_polygon / _compute_metrics / _polygon_dims` — exactly as used by `_build_warm_start` / the previous spikes (the full proven runner is preserved in `docs/superpowers/plans/2026-07-05-lattice-warmstart.md`, Task 4).
- The GA prelude uses `effort=4` (ProcessPoolExecutor) — the runner's `if __name__ == "__main__"` guard keeps Windows process spawn safe.

---

### Task 1: Worktree preflight + docs on branch

**Files:**
- Create (copy in, gitignored): `WT\examples\input\sample_2.dxf`, `WT\examples\input\sample_4.dxf`
- Create (committed): `WT\docs\superpowers\specs\2026-07-06-ga-warmstart-design.md`, `WT\docs\superpowers\plans\2026-07-07-ga-warmstart.md` (copied from the main tree)
- Modify: `WT\docs\planning\BACKLOG.md` (append execution checklist)

**Interfaces:**
- Consumes: nothing.
- Produces: a verified worktree; spec/plan/BACKLOG committed on `feat/ga-warmstart`.

- [ ] **Step 1: Verify worktree + branch**

```powershell
cd WT
git rev-parse --abbrev-ref HEAD
git status --short
```
Expected: `feat/ga-warmstart`, clean tree. If the worktree doesn't exist, STOP and ask the user to create it.

- [ ] **Step 2: Copy fixtures (not in git)**

```powershell
New-Item -ItemType Directory -Force WT\examples\input
Copy-Item D:\openmarker\examples\input\sample_2.dxf WT\examples\input\ -Force
Copy-Item D:\openmarker\examples\input\sample_4.dxf WT\examples\input\ -Force
```

- [ ] **Step 3: Baseline test run**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: 259 passed (the vendored sparrow integration tests included). Any failure = pre-existing breakage — STOP and report.

- [ ] **Step 4: Copy spec + plan into the worktree**

```powershell
Copy-Item D:\openmarker\docs\superpowers\specs\2026-07-06-ga-warmstart-design.md WT\docs\superpowers\specs\
Copy-Item D:\openmarker\docs\superpowers\plans\2026-07-07-ga-warmstart.md WT\docs\superpowers\plans\
```

- [ ] **Step 5: Append the execution checklist at the end of `WT\docs\planning\BACKLOG.md`**

```markdown
### GA warm-start spike (spec 2026-07-06) Execution Checklist

- [ ] P1: Worktree preflight + spec/plan/BACKLOG committed on branch
- [ ] P2: Spike runner + smoke (3 arms × 15s × 1 copy)
- [ ] P3: Canonical matrix — prod/ctl780/ga × seeds 42/43/44 (~1h45m)
- [ ] P4: Gate evaluation + verdict [USER CHECKPOINT]
- [ ] P5: Conditional GO: sample_4×6 G3 guard
- [ ] P6: Cleanup — delete spike (both paths), rescue reports
- [ ] P7: Docs (PERFORMANCE §6 entry), BACKLOG outcome, PR, final review
```

- [ ] **Step 6: Commit**

```powershell
cd WT
git add docs/superpowers/specs/2026-07-06-ga-warmstart-design.md docs/superpowers/plans/2026-07-07-ga-warmstart.md docs/planning/BACKLOG.md
git commit -m "docs: spec + plan + BACKLOG checklist for the GA warm-start spike

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Spike runner + smoke

**Files:**
- Create: `WT\engine\tests\spike_ga_warmstart.py` (throwaway; deleted in Task 6)

**Interfaces:**
- Consumes: `auto_layout_polygon` (Fast `effort=1`; GA `effort=4, ga_generations=12, ga_max_time_s=180.0, ga_seed=42`); `separation` helpers as in Global Constraints.
- Produces: `tools/ga-warmstart-spike/reports/<workload>_x<copies>/report.json` with schema `{"meta": {..., "arms": [[name, source, budget_s], ...], "seeds_meta": {source: {seed_marker_mm, seed_util_pct, prelude_s}}}, "runs": [{"arm", "seed", "seed_source", "budget_s", "marker_mm", "util_pct", "wall_s", "valid", "error?", "snapshots", "log_lines", "workdir"}]}` + `report.md`; subcommands `smoke` / `run` / `evaluate`. Exit codes: 0 all-valid, 1 some-invalid, 2 TTL.

- [ ] **Step 1: Write the spike script**

```python
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
```

- [ ] **Step 2: Smoke run (3 arms × 15s × 1 copy; GA prelude generation-capped — expect ~3–6 min)**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_ga_warmstart.py smoke
```
Expected: two `seed[...]` lines (fast, ga — ga's prelude well under 180s at 1 copy), three `marker=… util=… wall=…` run lines, then `SMOKE PASS`, exit 0. Sanity-check `WT\tools\ga-warmstart-spike\reports\sample_2_x1\report.json`: `meta.seeds_meta` has both sources; all three rows `"valid": true`; `git status --short` shows nothing under `tools/` (blanket gitignore).

- [ ] **Step 3: Commit**

```powershell
cd WT
git add engine/tests/spike_ga_warmstart.py
git commit -m "test(engine): throwaway spike runner for the GA warm-start A/B

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Canonical matrix — prod/ctl780/ga × seeds 42/43/44 (~1h45m)

**Files:** none (produces `WT\tools\ga-warmstart-spike\reports\sample_2_x10\report.{json,md}` — gitignored).

**Interfaces:**
- Consumes: Task 2's `run` subcommand.
- Produces: the workload-1 report consumed by Task 4.

- [ ] **Step 1: Preflight — quiet box**

Confirm the box is quiet (sparrow's `-t` is wall-clock; the GA prelude's `effort=4` also wants idle cores). Runs are strictly sequential by construction.

- [ ] **Step 2: Launch the matrix in the background**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_ga_warmstart.py run --workload sample_2.dxf --copies 10 --arms prod:fast:600,ctl780:fast:754,ga:ga:600 --seeds 42,43,44 --ttl-hours 3.5
```
~5862s of sparrow + ~210s of preludes ≈ 1h42m. Check the first lines immediately: the `fast` seed should print ≈11393.2mm and the `ga` seed ≈11232.3mm with prelude ≈180s. **If the GA seed prints ≥ 11393 (no denser than Fast), STOP before burning the matrix** — that contradicts the premise; report to the user.

- [ ] **Step 3: On completion, verify the report**

```powershell
Get-Content WT\tools\ga-warmstart-spike\reports\sample_2_x10\report.md
```
Expected: 9 rows, all `valid: True`, exit 0. Exit 1 → inspect `error` fields, fix, re-run (resume re-runs only invalid pairs). Exit 2 → re-run the same command to finish.

---

### Task 4: Gate evaluation + verdict  **[USER CHECKPOINT]**

**Files:** none.

**Interfaces:**
- Consumes: Task 3's report; Task 2's `evaluate`.
- Produces: the G2-product verdict (+ G2-mechanism readout + interpretation-grid outcome) that selects Task 5 and the docs branch of Task 7.

- [ ] **Step 1: Evaluate**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_ga_warmstart.py evaluate --report tools\ga-warmstart-spike\reports\sample_2_x10\report.json
```
Expected: seed telemetry, the dose-response readout, G2-mechanism, G2-product (PRIMARY), DECISIVE flag, and the interpretation hint when product-NO-GO + mechanism-GO.

- [ ] **Step 2: If G2-product is BORDERLINE — extend seeds first**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_ga_warmstart.py run --workload sample_2.dxf --copies 10 --arms prod:fast:600,ctl780:fast:754,ga:ga:600 --seeds 42,43,44,45,46 --ttl-hours 4.5
```
(Resume skips the 9 completed pairs; +6 runs ≈ 1h5m.) Re-run Step 1; with n=5 GO needs wins ≥ 4.

- [ ] **Step 3: Present the verdict to the user — STOP and wait**

Present: the 3×3 finals table, BOTH paired comparisons (product primary, mechanism secondary), the dose-response readout, seed telemetry (did GA print ≈11232.3?), DECISIVE status, and the interpretation-grid reading. The user chooses:
- G2-product **GO** → Task 5 (G3 guard), then Task 6+7 with the GO docs (follow-up PR filed for `run_separation_layout` wiring).
- G2-product **NO-GO** → Task 6+7 with the NO-GO docs; if mechanism was GO, the docs file the cheaper-GA-prelude follow-up instead of closing the lever.

---

### Task 5: G3 regression guard on sample_4 ×6  **[conditional: G2-product GO]**

**Files:** none (produces `WT\tools\ga-warmstart-spike\reports\sample_4_x6\report.{json,md}`).

**Interfaces:**
- Consumes: Task 2's `run`/`evaluate`.
- Produces: G3 PASS/FAIL shaping Task 7's productization note.

- [ ] **Step 1: Run the guard (2 × 600s + preludes ≈ 25min)**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_ga_warmstart.py run --workload sample_4.dxf --copies 6 --arms prod:fast:600,ga:ga:600 --seeds 42 --ttl-hours 1
```
Expected: 2 valid rows (the GA prelude on sample_4×6 may finish before 180s — its actual `prelude_s` is telemetry).

- [ ] **Step 2: Evaluate both reports**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_ga_warmstart.py evaluate --report tools\ga-warmstart-spike\reports\sample_2_x10\report.json --report2 tools\ga-warmstart-spike\reports\sample_4_x6\report.json
```
Expected: `G3[ga] ... -> PASS` or `FAIL (...)`. FAIL does not kill the GO — Task 7's docs then state productization as "build both seeds, pick the better pre-sparrow".

---

### Task 6: Cleanup — delete the spike (BOTH paths), rescue reports

**Files:**
- Delete: `WT\engine\tests\spike_ga_warmstart.py`

**Interfaces:**
- Consumes: the verdict from Task 4.
- Produces: a docs-only branch (this plan preserves the spike code verbatim above).

- [ ] **Step 1: Delete the spike**

```powershell
cd WT
git rm engine/tests/spike_ga_warmstart.py
```

- [ ] **Step 2: Full suite green**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: 259 passed (baseline — the branch never touched engine modules).

- [ ] **Step 3: Commit**

```powershell
cd WT
git commit -m "chore(engine): remove GA warm-start spike after verdict (code preserved in the plan doc)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Rescue the reports to the main tree**

```powershell
New-Item -ItemType Directory -Force D:\openmarker\tools\ga-warmstart-spike\reports
Copy-Item WT\tools\ga-warmstart-spike\reports\* D:\openmarker\tools\ga-warmstart-spike\reports\ -Recurse -Force
```
Verify `D:\openmarker\tools\ga-warmstart-spike\reports\sample_2_x10\report.json` exists.

---

### Task 7: Docs + BACKLOG + PR

**Files:**
- Modify: `WT\docs\planning\PERFORMANCE.md` (§ 6 new entry — there is no § 5.B row for this lever; the entry IS the record), `WT\docs\planning\BACKLOG.md` (checklist ticks + outcome line)

**Interfaces:**
- Consumes: the verdict + all measured numbers from the report.json files.
- Produces: the merged protocol record; PR on `feat/ga-warmstart`.

- [ ] **Step 1: PERFORMANCE.md § 6 entry** (append at the end of § 6; fill every `<...>` from the reports — never leave one unfilled):

```markdown
### <YYYY-MM-DD> — GA-layout warm-start A/B (equal envelope): <VERDICT>

- **What / why:** Closed follow-up (a) of § 6 [2026-06-09] under the § 6
  [2026-07-05] mechanism rule (seeds transfer in proportion to plateau
  proximity): seeded sparrow from the GA Better-tier layout (the only seed
  denser than Fast-BLF) at honest time accounting. 3 arms: prod (Fast+600s),
  ctl780 (Fast+754s), ga (GA-180s+600s — equal 780s envelope with ctl780).
  Canonical protocol, matched seeds <seeds>, sequential, validator-gated
  seeds AND finals.
- **Seed layouts:** fast <mm>mm / <util>% (prelude <s>s); ga <mm>mm / <util>%
  (prelude <s>s) — vs references 11393.2 / 11232.3.
- **Result (final markers, mm):**

| arm | s42 | s43 | s44 | mean |
| --- | --- | --- | --- | --- |
| prod | <mm> | <mm> | <mm> | <mm> |
| ctl780 | <mm> | <mm> | <mm> | <mm> |
| ga | <mm> | <mm> | <mm> | <mm> |

- **Gates:** G1 <all valid?>; **G2-product [ga vs ctl780]: <verdict>**
  (paired mean <±mm>, wins <n>/3); G2-mechanism [ga vs prod]: <verdict>
  (paired mean <±mm>, wins <n>/3); dose-response [ctl780 vs prod, +154s]:
  <±mm>; DECISIVE (<10599 all ga seeds): <yes/no>; G3 (sample_4×6, GO only):
  <PASS/FAIL/not run>.
- **Interpretation:** <the 2×2 grid outcome: transfer vs cost; what the
  dose-response says about where envelope time is best spent>.
- **Decision:** <ship follow-up filed / cheaper-GA-prelude follow-up filed /
  lever closed>. Spike deleted, code preserved in
  `docs/superpowers/plans/2026-07-07-ga-warmstart.md`; reports under
  `tools/ga-warmstart-spike/reports/` (gitignored, local-only).
```

- [ ] **Step 2: BACKLOG.md** — tick executed checklist items (P5 stays `[ ]` with ` (skipped — <reason>)` if not run) and add the outcome line under the checklist:

```markdown
- Outcome: <VERDICT> — ga vs ctl780 (equal 780s envelope) paired <±mm>, <n>/3
  wins; ga vs prod <±mm>; dose-response +154s = <±mm>; GA seed <mm> vs Fast
  11393.2; DECISIVE: <yes/no>. See PERFORMANCE.md § 6.
```

On a GO (or a mechanism-GO follow-up), also append the follow-up line the verdict selects:

```markdown
- [ ] Follow-up: <wire GA seed source into `run_separation_layout` (budget
  semantics: prelude inside vs on top of ultra_budget_s; cache keys) /
  cheaper GA prelude (60–90s ga_max_time_s cap) re-test> — separate
  spec/plan/PR.
```

- [ ] **Step 3: Commit docs**

```powershell
cd WT
git add docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git commit -m "docs(perf): GA warm-start A/B protocol record (<VERDICT>)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Hand back to the controller** for the final whole-branch review, push, and `gh pr create` (PR body carries the results table + the standing merge note about main's uncommitted `.gitignore` edit + the 🤖 attribution line). Merge is the user's call at the PR.

---

## Verdict paths (summary)

- **G2-product GO:** Tasks 1–5 + 6 + 7 (GO docs; productization follow-up filed).
- **G2-product NO-GO:** Tasks 1–4 + 6 + 7 (NO-GO docs; if G2-mechanism was GO, the cheaper-GA-prelude follow-up is filed instead of closing the lever).
- **BORDERLINE:** resolved inside Task 4 (extend to seeds 45/46) before choosing a path.
