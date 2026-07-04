# Sparrow SIMD + target-cpu Rebuild A/B — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the vendored `sparrow.exe` with upstream's documented performance flags (nightly + `simd` + `-C target-cpu`), A/B it against the shipped binary under the noise-floor protocol, and ship the gate-selected outcome (v2 swap, dual-binary runtime-AVX2 dispatch, or NO-GO).

**Architecture:** Pure codegen experiment on the pinned source `a4bfbbe` — no sparrow source edits, no config-constant changes, no engine behavior changes during benching (candidate exes are shelled directly by a throwaway spike that reuses the production separation helpers). Conditional product change only if gates pass: binary swap and/or a variant-selection step in `_resolve_sparrow_path()`.

**Tech Stack:** Rust (rustup, pinned nightly, cargo), Python 3.11 (engine venv), pytest, PowerShell on Windows.

**Spec:** `docs/superpowers/specs/2026-07-04-sparrow-simd-rebuild-design.md` (approved 2026-07-04).

## Global Constraints

- Source pin: `a4bfbbe0bf864a7eaf136f9d06456155b1163195` — never edit the sparrow source.
- Toolchain: `nightly-2026-05-07`; on portable-SIMD API drift try `nightly-2026-06-30`; if that also fails **STOP and report** (stable descope is a user decision).
- Cargo features: `simd` ONLY. Never `only_final_svg` (kills `sols_` snapshots), never `live_svg`.
- Candidates: `x86-64-v2`, `x86-64-v3`, `native`. **native is bench-only and must never be copied into `engine/vendor/`.**
- Bench: warm-start arms, budget **600s**, seeds **42/43/44**, workloads `sample_2.dxf ×10` (decision) and `sample_4.dxf ×6` (regression guard), fabric **1651.0**, grain **bi @90**. All comparisons matched-seed paired.
- Quiet box: builds fully finish before any timed run; timed runs strictly sequential; no other load (sparrow `-t` is wall-clock).
- Every bench marker must pass `_validate_layout`. A validity failure on a codegen-only change = red flag: STOP and investigate.
- Gates (spec § 6): G1 = beats control on ≥2/3 seeds AND paired mean < 0, all valid. G2 = v3 beats its fallback by paired mean ≥ 15mm. G3 = shipped candidate not worse than control on sample_4×6 by > 10mm paired mean.
- Engine python: `D:\openmarker\engine\.venv\Scripts\python.exe` (the venv lives in the MAIN tree; worktrees have none). Run pytest as `python.exe -m pytest` from the **worktree's** `engine\` dir so the worktree's code is imported.
- Commits happen only on the worktree feature branch (project rule). End commit messages with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Throughput numbers are informational only — never a gate.

---

### Task 1: Worktree preflight & baseline sanity

**Files:**
- No changes — verification only. Working dir for ALL tasks = the worktree root (referred to as `WT\`), branch `feat/sparrow-simd-rebuild` (user creates the worktree).

**Interfaces:**
- Produces: a worktree where fixtures exist, the vendored exe resolves, and the sidecar integration tests pass — the baseline every later task assumes.

- [ ] **Step 1: Verify worktree + branch**

Run (from `WT\`): `git status; git rev-parse --abbrev-ref HEAD`
Expected: clean tree, branch `feat/sparrow-simd-rebuild`.

- [ ] **Step 2: Copy fixtures (not in git; absent in fresh worktrees)**

```powershell
New-Item -ItemType Directory -Force WT\examples\input
Copy-Item D:\openmarker\examples\input\*.dxf WT\examples\input\
Get-ChildItem WT\examples\input\sample_2.dxf, WT\examples\input\sample_4.dxf
```
Expected: both files listed.

- [ ] **Step 3: Verify toolchain + vendored exe present**

```powershell
rustup --version; cargo --version
Get-ChildItem WT\engine\vendor\sparrow\sparrow.exe
```
Expected: rustup + cargo print versions; exe exists (~2.2MB).

- [ ] **Step 4: Baseline — run the separation unit + sidecar integration tests**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_separation.py tests\integration\test_separation_sidecar.py -v
```
Expected: ALL PASS (the sidecar tests do real tiny sparrow runs; a few minutes).

---

### Task 2: Pinned toolchain + pinned source

**Files:**
- Create: `WT\tools\sparrow-rebuild\src\` (git clone; `tools/` is gitignored)

**Interfaces:**
- Produces: checked-out source at `a4bfbbe` + installed `nightly-2026-05-07` — consumed by Task 3.

- [ ] **Step 1: Install the pinned nightly**

```powershell
rustup toolchain install nightly-2026-05-07
```
Expected: `nightly-2026-05-07-x86_64-pc-windows-msvc installed`.

- [ ] **Step 2: Clone + checkout the pin**

```powershell
New-Item -ItemType Directory -Force WT\tools\sparrow-rebuild
git clone https://github.com/JeroenGar/sparrow WT\tools\sparrow-rebuild\src
cd WT\tools\sparrow-rebuild\src
git checkout a4bfbbe0bf864a7eaf136f9d06456155b1163195
git rev-parse HEAD
```
Expected: last line prints exactly `a4bfbbe0bf864a7eaf136f9d06456155b1163195`.

---

### Task 3: Build the three candidates + BUILDINFO

**Files:**
- Create: `WT\tools\sparrow-rebuild\builds\sparrow_{v2,v3,native}.exe`
- Create: `WT\tools\sparrow-rebuild\builds\BUILDINFO.md`

**Interfaces:**
- Produces: the three exe paths above (consumed by the spike's `ARMS` map, Task 4) and BUILDINFO hash lines (consumed by the PROVENANCE rewrite, Tasks 8/9).

- [ ] **Step 1: Build v2 / v3 / native (separate target dirs; nightly; simd)**

```powershell
cd WT\tools\sparrow-rebuild\src
$env:RUSTUP_TOOLCHAIN = "nightly-2026-05-07"
foreach ($v in @(@("x86-64-v2","v2"), @("x86-64-v3","v3"), @("native","native"))) {
  $env:RUSTFLAGS = "-C target-cpu=$($v[0])"
  $env:CARGO_TARGET_DIR = "..\target-$($v[1])"
  cargo build --release --features=simd
}
New-Item -ItemType Directory -Force ..\builds
foreach ($v in @("v2","v3","native")) {
  Copy-Item "..\target-$v\release\sparrow.exe" "..\builds\sparrow_$v.exe"
}
```
Expected: three `Finished `release` profile [optimized]` lines; three exes in `builds\`.

**Drift fallback:** on compile errors mentioning `portable_simd` / `feature` / `E0658`: set `$env:RUSTUP_TOOLCHAIN = "nightly-2026-06-30"`, `rustup toolchain install nightly-2026-06-30`, rebuild all three. If that fails too — STOP, report to user (stable descope decision), do not proceed.

- [ ] **Step 2: Load smoke (`--help` must run on this box)**

```powershell
foreach ($v in @("v2","v3","native")) { & "WT\tools\sparrow-rebuild\builds\sparrow_$v.exe" --help | Select-Object -First 3 }
```
Expected: usage text ×3, exit code 0 each (catches illegal-instruction immediately).

- [ ] **Step 3: Write BUILDINFO.md**

```powershell
cd WT\tools\sparrow-rebuild\builds
"## sparrow rebuild candidates ($(Get-Date -Format yyyy-MM-dd))",
"- source: a4bfbbe0bf864a7eaf136f9d06456155b1163195",
"- toolchain: $(& cargo +nightly-2026-05-07 --version); rustc: $(& rustc +nightly-2026-05-07 --version)",
"- features: simd; profile: release (opt-level=3, lto=fat, from repo Cargo.toml)" | Out-File -Encoding utf8 BUILDINFO.md
foreach ($v in @("v2","v3","native")) {
  $h = Get-FileHash -Algorithm SHA256 "sparrow_$v.exe"
  "- sparrow_$v.exe  RUSTFLAGS=-C target-cpu=$(@{v2='x86-64-v2';v3='x86-64-v3';native='native'}[$v])  SHA256=$($h.Hash)  size=$((Get-Item "sparrow_$v.exe").Length)" | Out-File -Encoding utf8 -Append BUILDINFO.md
}
Get-Content BUILDINFO.md
```
Expected: header + 3 hash lines printed. (Adjust the toolchain line if the drift fallback changed the nightly.)

---

### Task 4: Spike bench harness + smoke run

**Files:**
- Create: `WT\engine\tests\spike_simd_rebuild.py` (throwaway; deleted in Task 11)

**Interfaces:**
- Consumes: `core.layout.separation` production helpers (`_group_to_items`, `_instance_json`, `_build_warm_start`, `_reconstruct`, `_validate_layout`, `_resolve_sparrow_path`) and `core.layout.heuristic._compute_metrics/_polygon_dims` — signatures as in the current tree.
- Produces: `tools/sparrow-rebuild/reports/<workload>/report.json` with schema `{"meta": {...}, "runs": [{"arm", "seed", "exe", "sha256", "marker_mm", "util_pct", "wall_s", "valid", "error", "log_lines", "snapshots"}]}` + `report.md`; subcommands `smoke` / `run` / `evaluate` (consumed by Tasks 5–7).

- [ ] **Step 1: Write the spike script**

```python
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
    snapshots = len(glob.glob(os.path.join(outdir, "sols_*", "*.json")))
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
    runs: list[dict] = []
    for seed in seeds:                      # seed-major: arms interleave within each seed
        for a in arms:                      # so box drift hits all arms of a pair equally
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
    return 0


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
```

- [ ] **Step 2: Smoke run (all four arms, 15s each, ~2min total + one Fast prelude)**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_simd_rebuild.py smoke
```
Expected: 4 lines `… marker=… util=… wall=…`, then `SMOKE PASS`, exit 0. Reports under `WT\tools\sparrow-rebuild\reports\sample_2_x1\`. Peek at one `runs\v3_s42\sparrow.stderr.log` — note what the log lines look like (informational; no code change needed).

- [ ] **Step 3: Commit the spike**

```powershell
cd WT
git add engine/tests/spike_simd_rebuild.py
git commit -m "test(engine): throwaway spike for sparrow SIMD/target-cpu rebuild A/B

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Workload-1 matrix (12 × 600s ≈ 2h5m)

**Files:**
- Create (generated): `WT\tools\sparrow-rebuild\reports\sample_2_x10\report.{json,md}`

**Interfaces:**
- Consumes: Task 4 spike, Task 3 builds.
- Produces: the decision report for Task 6.

- [ ] **Step 1: Confirm the box is quiet** (no builds running, no other CPU load; close heavyweight apps).

- [ ] **Step 2: Launch the matrix (background, TTL 5h)**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_simd_rebuild.py run --workload sample_2.dxf --copies 10 --budget 600 --seeds 42,43,44 --arms control,v2,v3,native --ttl-hours 5
```
Expected: 12 sequential `arm seed=… marker=…` lines (~10.5min apiece; one ~30s Fast prelude at the start). Exit 0.

- [ ] **Step 3: Completeness check**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe -c "import json; r=json.load(open(r'WT\tools\sparrow-rebuild\reports\sample_2_x10\report.json')); print(len(r['runs']), all(x['valid'] for x in r['runs']))"
```
Expected: `12 True`. Any `False` → STOP (spec red flag), inspect that run's `error` + log before continuing.

---

### Task 6: Gate evaluation + ship-path decision  **[USER CHECKPOINT]**

**Interfaces:**
- Consumes: `sample_2_x10\report.json`.
- Produces: the ship-path decision (`V2-ONLY` / `DUAL` / `NO-GO`) that selects Task 8, 9, or 10 — and the candidate list for Task 7.

- [ ] **Step 1: Evaluate workload-1 gates**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_simd_rebuild.py evaluate --report WT\tools\sparrow-rebuild\reports\sample_2_x10\report.json
```
Expected: `G1[v2]`, `G1[v3]`, `info[native ceiling]`, optional `G2`, then `workload-1 verdict: <PATH>`.

- [ ] **Step 2: Report the full gate printout + report.md table to the user and confirm the ship path before executing Task 7+.** (Gates are mechanical, but a binary swap is product-facing.)

---

### Task 7: Workload-2 regression guard (sample_4×6)

**Files:**
- Create (generated): `WT\tools\sparrow-rebuild\reports\sample_4_x6\report.{json,md}`

**Interfaces:**
- Consumes: ship-path candidates from Task 6 (skip entirely on NO-GO → go to Task 10).
- Produces: G3 verdicts consumed by Tasks 8/9.

- [ ] **Step 1: Run control + shipping candidate(s)** — e.g. for DUAL with fallback=v2 that is `control,v2,v3` (9 runs ≈ 1h35m); for V2-ONLY it is `control,v2` (6 runs ≈ 1h5m). The first run includes a one-time ~107s Fast prelude (complex outlines).

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_simd_rebuild.py run --workload sample_4.dxf --copies 6 --budget 600 --seeds 42,43,44 --arms control,v2,v3 --ttl-hours 4
```
Expected: sequential lines, exit 0, all valid.

- [ ] **Step 2: Evaluate G3**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_simd_rebuild.py evaluate --report WT\tools\sparrow-rebuild\reports\sample_2_x10\report.json --report2 WT\tools\sparrow-rebuild\reports\sample_4_x6\report.json --candidates v2,v3
```
Expected: `G3[v2]: … PASS/FAIL`, `G3[v3]: … PASS/FAIL`. A FAIL drops that candidate and re-applies the spec § 6 ladder (possibly downgrading DUAL→V2-ONLY or to NO-GO). Record the final path.

---

### Task 8: Ship path (a) — V2-ONLY binary swap  **[conditional: verdict V2-ONLY]**

**Files:**
- Modify: `WT\engine\vendor\sparrow\sparrow.exe` (replaced by the v2 build)
- Modify: `WT\engine\vendor\sparrow\PROVENANCE.md`

**Interfaces:**
- Consumes: `builds\sparrow_v2.exe` + BUILDINFO hashes.
- Produces: the shipped binary Task 11 documents.

- [ ] **Step 1: Swap the binary**

```powershell
Copy-Item WT\tools\sparrow-rebuild\builds\sparrow_v2.exe WT\engine\vendor\sparrow\sparrow.exe -Force
Get-FileHash -Algorithm SHA256 WT\engine\vendor\sparrow\sparrow.exe
```
Expected: hash equals BUILDINFO's `sparrow_v2.exe` line.

- [ ] **Step 2: Rewrite PROVENANCE.md** (fill `<SHA256>`/`<size>` from BUILDINFO; adjust nightly if drift fallback fired):

```markdown
# Vendored sparrow binary

`sparrow.exe` is the bundled offline nesting sidecar for the "Ultra" quality tier.
The engine locates it via `core/layout/separation._resolve_sparrow_path()`.

- **Upstream:** https://github.com/JeroenGar/sparrow (MIT)
- **Commit:** `a4bfbbe0bf864a7eaf136f9d06456155b1163195`
- **Built with:** `cargo +nightly-2026-05-07 build --release --features=simd`,
  `RUSTFLAGS="-C target-cpu=x86-64-v2"` (SIMD on; runs on any x86-64-v2 CPU, ~2009+)
- **SHA-256:** `<SHA256>`  · size `<size>` bytes
- **Target:** Windows x64 (floor: x86-64-v2)
- **Built on:** 2026-07-04 — A/B-validated vs the 2026-06-08 stable no-simd build
  (PERFORMANCE.md § 6 [2026-07-04 rebuild A/B])

## Why committed

Offline, one-click install: user machines have no Rust toolchain or network. The
binary ships with the app. Refresh deliberately on upgrade — rebuild from the pinned
commit, replace `sparrow.exe`, and update this file.

## Rebuild

```
git clone https://github.com/JeroenGar/sparrow tools/sparrow-rebuild/src
cd tools/sparrow-rebuild/src && git checkout a4bfbbe
rustup toolchain install nightly-2026-05-07
set RUSTFLAGS=-C target-cpu=x86-64-v2
cargo +nightly-2026-05-07 build --release --features=simd
# copy target/release/sparrow.exe -> engine/vendor/sparrow/sparrow.exe
```

NEVER build with `--features=only_final_svg` (it suppresses the `sols_<name>/`
intermediate solutions the planned best-so-far-on-Stop feature reads).

## Licenses

- **sparrow** — MIT (see the upstream `LICENSE`).
- **jagua-rs** v0.7.2 (the collision engine sparrow links) — MPL-2.0. We ship an
  UNMODIFIED binary, so the MPL-2.0 source-availability notice suffices:
  https://github.com/JeroenGar/jagua-rs
```

- [ ] **Step 3: Full engine test suite against the new binary**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: ALL PASS (includes the 3 real-sparrow integration tests).

- [ ] **Step 4: Commit**

```powershell
cd WT
git add engine/vendor/sparrow/sparrow.exe engine/vendor/sparrow/PROVENANCE.md
git commit -m "feat(engine): rebuild vendored sparrow with nightly+simd, target-cpu=x86-64-v2

A/B-validated on sample_2x10 + sample_4x6 (3 matched seeds, 600s warm).
See PERFORMANCE.md §6 [2026-07-04 rebuild A/B].

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Note: on this branch `.gitignore` still contains `!engine/vendor/sparrow/sparrow.exe`, so `git add` works. If `git add` warns about an ignored file, verify that negation line is present.

---

### Task 9: Ship path (b) — DUAL binary + runtime AVX2 dispatch  **[conditional: verdict DUAL]**

**Files:**
- Modify: `WT\engine\core\layout\separation.py:36-64` (resolver region)
- Test: `WT\engine\tests\unit\test_separation.py` (append)
- Modify: `WT\engine\vendor\sparrow\sparrow.exe` (fallback: v2 build, or UNCHANGED if fallback=control per G2)
- Create: `WT\engine\vendor\sparrow\sparrow-avx2.exe` (v3 build)
- Modify: `WT\.gitignore` (extend the vendored negation)
- Modify: `WT\engine\vendor\sparrow\PROVENANCE.md`

**Interfaces:**
- Consumes: current `_resolve_sparrow_path()` + module constant `_VENDORED` (`separation.py:36-64`).
- Produces: `_has_avx2() -> bool`, `_variant_names() -> list[str]`, `_VENDOR_DIR: str` (module constant), and a variant-aware `_resolve_sparrow_path()` — consumed by nothing else (resolver is internal), but names must match the tests below exactly.

- [ ] **Step 1: Write the failing tests** (append to `engine/tests/unit/test_separation.py`):

```python
class TestResolverAvx2Dispatch:
    """Dual-binary runtime dispatch (spec 2026-07-04-sparrow-simd-rebuild §7b)."""

    def _vendor(self, tmp_path, monkeypatch, names):
        from core.layout import separation
        vend = tmp_path / "vendor"
        vend.mkdir()
        for n in names:
            (vend / n).write_bytes(b"fake-exe")
        monkeypatch.setattr(separation, "_VENDOR_DIR", str(vend))
        monkeypatch.delenv("OPENMARKER_SPARROW_PATH", raising=False)
        return separation, vend

    def test_prefers_avx2_exe_when_cpu_has_avx2(self, tmp_path, monkeypatch):
        sep, vend = self._vendor(tmp_path, monkeypatch, ["sparrow.exe", "sparrow-avx2.exe"])
        monkeypatch.setattr(sep, "_has_avx2", lambda: True)
        assert sep._resolve_sparrow_path() == str(vend / "sparrow-avx2.exe")

    def test_falls_back_without_avx2(self, tmp_path, monkeypatch):
        sep, vend = self._vendor(tmp_path, monkeypatch, ["sparrow.exe", "sparrow-avx2.exe"])
        monkeypatch.setattr(sep, "_has_avx2", lambda: False)
        assert sep._resolve_sparrow_path() == str(vend / "sparrow.exe")

    def test_falls_back_when_avx2_exe_missing(self, tmp_path, monkeypatch):
        sep, vend = self._vendor(tmp_path, monkeypatch, ["sparrow.exe"])
        monkeypatch.setattr(sep, "_has_avx2", lambda: True)
        assert sep._resolve_sparrow_path() == str(vend / "sparrow.exe")

    def test_env_override_beats_probe(self, tmp_path, monkeypatch):
        sep, _ = self._vendor(tmp_path, monkeypatch, ["sparrow.exe", "sparrow-avx2.exe"])
        override = tmp_path / "custom.exe"
        override.write_bytes(b"fake-exe")
        monkeypatch.setenv("OPENMARKER_SPARROW_PATH", str(override))
        monkeypatch.setattr(sep, "_has_avx2", lambda: True)
        assert sep._resolve_sparrow_path() == str(override)

    def test_has_avx2_false_off_windows(self, monkeypatch):
        import sys as _sys
        from core.layout import separation
        monkeypatch.setattr(_sys, "platform", "linux")
        assert separation._has_avx2() is False
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_separation.py::TestResolverAvx2Dispatch -v
```
Expected: 5 failures — `AttributeError: ... has no attribute '_VENDOR_DIR'` / `'_has_avx2'`.

- [ ] **Step 3: Implement** — in `separation.py`, replace the block from the `_VENDORED = …` line (line 36) through the end of `_resolve_sparrow_path()` (line 64) with:

```python
_VENDOR_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "vendor", "sparrow")
_VENDORED = os.path.join(_VENDOR_DIR, "sparrow.exe")   # kept for back-compat references


def _has_avx2() -> bool:
    """True iff the CPU reports AVX2 (Windows only; conservative False elsewhere/on error)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))  # PF_AVX2_INSTRUCTIONS_AVAILABLE
    except Exception:
        return False


def _variant_names() -> list[str]:
    """Preferred exe filenames, best first: the AVX2 build is eligible only when the
    CPU supports it; sparrow.exe is always the universal fallback."""
    return ["sparrow-avx2.exe", "sparrow.exe"] if _has_avx2() else ["sparrow.exe"]


def _resolve_sparrow_path() -> str:
    """Locate the bundled sparrow binary. Search order:
    1. OPENMARKER_SPARROW_PATH env override (exact file; bypasses the AVX2 probe)
    2. vendored engine/vendor/sparrow/ (committed, offline; sparrow-avx2.exe preferred on AVX2 CPUs)
    3. PyInstaller bundle dir (sys._MEIPASS — future packaging)
    4. dev build tools/sparrow/target/release/ (walk up to repo root)
    """
    candidates: list[str] = []
    env = os.environ.get("OPENMARKER_SPARROW_PATH")
    if env:
        candidates.append(env)
    names = _variant_names()
    candidates.extend(os.path.abspath(os.path.join(_VENDOR_DIR, n)) for n in names)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.extend(os.path.join(meipass, "vendor", "sparrow", n) for n in names)
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidates.extend(os.path.join(here, "tools", "sparrow", "target", "release", n) for n in names)
        here = os.path.dirname(here)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "sparrow binary not found. Set OPENMARKER_SPARROW_PATH, or vendor it at "
        "engine/vendor/sparrow/sparrow.exe (see the Phase 2 spec §10)."
    )
```

- [ ] **Step 4: Run the new tests — expect 5 PASS**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_separation.py::TestResolverAvx2Dispatch -v
```

- [ ] **Step 5: Place the binaries** (fallback per Task 6's G2 verdict — `v2` shown; if fallback=control, leave `sparrow.exe` untouched):

```powershell
Copy-Item WT\tools\sparrow-rebuild\builds\sparrow_v2.exe WT\engine\vendor\sparrow\sparrow.exe -Force
Copy-Item WT\tools\sparrow-rebuild\builds\sparrow_v3.exe WT\engine\vendor\sparrow\sparrow-avx2.exe
```

- [ ] **Step 6: Extend the `.gitignore` negation** — in `WT\.gitignore` replace the line `!engine/vendor/sparrow/sparrow.exe` with `!engine/vendor/sparrow/*.exe` (same location, after the `*.exe` ignore). NOTE: the user's MAIN working tree has an uncommitted edit that deletes this negation — flag it at PR time so the merge keeps the negation.

- [ ] **Step 7: PROVENANCE.md** — use Task 8 Step 2's template, replacing the single-binary block with a variants table:

```markdown
| file | RUSTFLAGS | CPU floor | SHA-256 | size |
| --- | --- | --- | --- | --- |
| `sparrow.exe` | `-C target-cpu=x86-64-v2` | any x86-64-v2 (~2009+) | `<SHA256>` | `<size>` |
| `sparrow-avx2.exe` | `-C target-cpu=x86-64-v3` | AVX2 (Haswell 2013+) | `<SHA256>` | `<size>` |

Selected at runtime by `_resolve_sparrow_path()` via `_has_avx2()`
(`kernel32.IsProcessorFeaturePresent(40)`); `sparrow.exe` is the universal fallback.
`OPENMARKER_SPARROW_PATH` bypasses the probe.
```

- [ ] **Step 8: Full suite + forced-fallback integration pass**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
$env:OPENMARKER_SPARROW_PATH = "WT\engine\vendor\sparrow\sparrow.exe"
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\integration\test_separation_sidecar.py -v
Remove-Item Env:OPENMARKER_SPARROW_PATH
```
Expected: ALL PASS both times (first run exercises whichever variant this box's CPU selects; second forces the fallback exe end-to-end).

- [ ] **Step 9: Commit**

```powershell
cd WT
git add engine/core/layout/separation.py engine/tests/unit/test_separation.py engine/vendor/sparrow/ .gitignore
git commit -m "feat(engine): dual sparrow binaries with runtime AVX2 dispatch (simd rebuild)

sparrow.exe = x86-64-v2 universal fallback; sparrow-avx2.exe = x86-64-v3,
picked by IsProcessorFeaturePresent(40). A/B-validated, see PERFORMANCE.md
§6 [2026-07-04 rebuild A/B].

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Ship path (c) — NO-GO  **[conditional: verdict NO-GO]**

**Files:** none (docs happen in Task 11; vendored exe and resolver stay untouched).

- [ ] **Step 1: Confirm no product files changed**

```powershell
cd WT; git status
```
Expected: only the spike (already committed) — no vendor/, no separation.py changes. Proceed to Task 11 with decision "NO-GO".

---

### Task 11: Docs, BACKLOG, cleanup, PR

**Files:**
- Modify: `WT\docs\planning\PERFORMANCE.md` (§ 6 new entry + § 5.B row status)
- Modify: `WT\docs\planning\BACKLOG.md` (flip the rebuild line to `[x]` with the outcome)
- Delete: `WT\engine\tests\spike_simd_rebuild.py`

**Interfaces:**
- Consumes: both `report.json` files + gate printouts + BUILDINFO.

- [ ] **Step 1: PERFORMANCE.md § 6 entry** — append after the [2026-07-04 survey] entry, filling every `<…>` from the reports (arm×seed markers from `report.md`, paired deltas + verdicts from the `evaluate` printout, throughput columns from `snapshots`/`log_lines`):

```markdown
### <date> — Sidecar codegen rebuild A/B (nightly+simd, target-cpu): <VERDICT>

- **What/why:** Rebuilt sparrow.exe from the same pin `a4bfbbe` with upstream's
  documented fast build (nightly-<pin> + `--features=simd` + `-C target-cpu=…`);
  the shipped binary was stable, no-simd, generic x86-64 (§ 6 [2026-07-04] Find A).
  Full matrix per the spec: {control, v2, v3, native} × seeds 42/43/44, 600s warm,
  sample_2×10; control + candidates on sample_4×6 (G3).
- **Result (sample_2×10 @600s warm, marker mm):**

  | arm | s42 | s43 | s44 | paired mean Δ vs control |
  | --- | --- | --- | --- | --- |
  | control (stable, no simd) | <…> | <…> | <…> | — |
  | v2 (x86-64-v2 + simd) | <…> | <…> | <…> | <…> |
  | v3 (x86-64-v3 + simd) | <…> | <…> | <…> | <…> |
  | native (ceiling, bench-only) | <…> | <…> | <…> | <…> |

  G1[v2]=<…>, G1[v3]=<…>, G2=<…>, G3=<…>. Throughput (informational):
  <sols-snapshots/log-lines summary>. sample_4×6 table: <…>.
- **Decision:** <V2-ONLY swap | DUAL runtime-AVX2 dispatch | NO-GO — vendored exe
  stays>. <One sentence on what shipped + PROVENANCE updated.> Spike deleted;
  builds/reports remain in gitignored `tools/sparrow-rebuild/`.
```

- [ ] **Step 2: § 5.B row status** — in the "SIMD + target-cpu rebuild" row, replace `**ADOPTED 2026-07-04 (§ 6) — plan in progress.**` with `**DONE <date> (§ 6 [rebuild A/B]) — <VERDICT>.**` and put the measured paired mean into the "Estimated gain" cell.

- [ ] **Step 3: BACKLOG** — flip the `- [~] Sidecar codegen rebuild A/B …` line to `[x]` and append `Outcome: <VERDICT>, <paired mean> on sample_2×10.`

- [ ] **Step 4: Delete the spike**

```powershell
cd WT
git rm engine/tests/spike_simd_rebuild.py
```

- [ ] **Step 5: Full test suite one last time**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: ALL PASS.

- [ ] **Step 6: Commit docs + cleanup, push, open PR**

```powershell
cd WT
git add docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git commit -m "docs(perf): sparrow simd/target-cpu rebuild A/B results — <VERDICT>

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push -u origin feat/sparrow-simd-rebuild
gh pr create --title "Sparrow sidecar rebuild: nightly+simd+target-cpu (<VERDICT>)" --body "Per docs/superpowers/specs/2026-07-04-sparrow-simd-rebuild-design.md. Full A/B matrix + gates in PERFORMANCE.md §6 [rebuild A/B]. NOTE for merge: main's working tree has an uncommitted .gitignore edit that removes the vendored-exe negation — keep this branch's negation line.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
Expected: PR URL printed.

- [ ] **Step 7: Session owner updates project memory** (MEMORY.md: rebuild outcome, shipped binaries/hashes, verdict) — not a repo file.
