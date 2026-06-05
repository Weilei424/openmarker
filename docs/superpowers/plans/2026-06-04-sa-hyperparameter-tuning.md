# SA Hyperparameter Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SA's hyperparameters tunable end-to-end (incl. spawned workers), sweep them at the locked grain=90, and either find a config that beats 11699mm (≥3 seeds) or produce a documented gap analysis.

**Architecture:** A picklable `SAConfig` dataclass (defaults = today's module constants) threaded `auto_layout_polygon(sa_config=...)` → `_run_sa_phase` → worker `initargs` → `run_sa`. A new standalone sweep harness with a soft TTL + always-writes-a-report finally block. Outcome branches into "bake the winner" or "gap analysis".

**Tech Stack:** Python 3.11, dataclasses, `ProcessPoolExecutor`, pytest, Shapely/pyclipper.

**Spec:** `docs/superpowers/specs/2026-06-04-sa-hyperparameter-tuning-design.md`. **Same branch/PR:** `feat/bench-grain-fix` → PR #12.

---

## Environment & conventions (read before any step)

- **Worktree (all edits + commits):** `D:\openmarker\.worktrees\perf-followups` (branch `feat/bench-grain-fix`).
- **Shared venv (absolute):** `D:\openmarker\engine\.venv\Scripts\python.exe`. The worktree has no `.venv`.
- **Run tests:** `D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/<path> -v`
- **Run a bench:** `D:/openmarker/engine/.venv/Scripts/python.exe D:/openmarker/.worktrees/perf-followups/engine/tests/<bench>.py`
- **`sample_2.dxf` is git-ignored** — present in the worktree's `examples/input/` (copied there during the grain-fix work). Benches also walk up to the main tree. Verify the sample row isn't `[skipped]`.
- **Git:** `git -C D:/openmarker/.worktrees/perf-followups ...`. Commit per task; one concise line per file in the body; end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. **Do NOT push** (controller handles the final push to PR #12).

## File structure

| File | Change | Responsibility |
| --- | --- | --- |
| `engine/core/layout/sa.py` | Modify | Add `SAConfig`; parameterize move/cooling helpers + `run_sa` to read it. |
| `engine/core/layout/heuristic.py` | Modify | Thread `sa_config` → `_run_sa_phase` → worker `initargs` → `run_sa`. |
| `engine/tests/unit/test_sa.py` | Modify | `SAConfig` + parameterized-operator unit tests. |
| `engine/tests/unit/test_heuristic.py` | Modify | `sa_config` forwarding + None==default regression. |
| `engine/tests/bench_sa_sweep.py` | Create | Sweep harness: TTL, per-row cap, JSONL, always-report. |
| `engine/core/layout/sa.py` + docs | Modify (Task 6) | Bake winner OR record gap analysis. |

---

## Task 1: `SAConfig` + parameterize `sa.py` (TDD)

**Files:**
- Modify: `engine/core/layout/sa.py`
- Test: `engine/tests/unit/test_sa.py`

- [ ] **Step 1: Write failing tests** — append to `engine/tests/unit/test_sa.py`:

```python
def test_saconfig_defaults_match_module_constants():
    cfg = sa.SAConfig()
    assert cfg.t0_factor == sa.T0_FACTOR
    assert cfg.cooling_alpha == sa.COOLING_ALPHA
    assert cfg.t_min == sa.T_MIN
    assert cfg.reverse_window_fraction == sa.REVERSE_WINDOW_FRACTION
    assert cfg.no_grainline_rotation_cap == sa.NO_GRAINLINE_ROTATION_CAP
    assert cfg.move_weights == sa.MOVE_WEIGHTS
    assert cfg.move_weights is not sa.MOVE_WEIGHTS  # independent copy


def test_temperature_at_respects_config_alpha_and_tmin():
    assert sa._temperature_at(100.0, 1, alpha=0.5, t_min=1e-3) == 50.0
    assert sa._temperature_at(100.0, 2, alpha=0.5, t_min=1e-3) == 25.0
    assert sa._temperature_at(100.0, 100, alpha=0.5, t_min=7.0) == 7.0  # floor wins


def test_sample_move_type_respects_weights():
    rng = random.Random(0)
    picks = {sa._sample_move_type(rng, {"swap": 1.0, "reverse": 0.0, "rotation_flip": 0.0})
             for _ in range(50)}
    assert picks == {"swap"}


def test_reverse_move_window_fraction_caps_window():
    rng = random.Random(3)
    order = list(range(100))
    new_order = sa._reverse_move(order, rng, window_fraction=0.02)  # cap=2
    diffs = [i for i in range(100) if new_order[i] != order[i]]
    assert len(diffs) <= 2


def test_run_sa_honors_config_move_weights_swap_only():
    """move_weights allowing only 'swap' → evaluator never sees a flipped rotation."""
    pieces = [_p(f"p{i}") for i in range(5)]
    allowed = [[0.0, 180.0] for _ in pieces]  # each piece COULD flip
    seen = []

    def stub(pieces_in_order, per_piece_rots):
        seen.append([r[0] for r in per_piece_rots])
        return [], 1.0, 0.0

    cfg = sa.SAConfig(move_weights={"swap": 1.0, "reverse": 0.0, "rotation_flip": 0.0})
    sa.run_sa(list(range(5)), [0.0] * 5, pieces, allowed,
              iterations=50, max_time_s=None, seed=7, evaluator=stub, config=cfg)
    assert seen  # evaluator was called
    assert all(all(r == 0.0 for r in snap) for snap in seen)  # no 180 ever proposed
```

- [ ] **Step 2: Run tests to verify they FAIL**

Run:
```
D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/unit/test_sa.py -v -k "saconfig or respects or window_fraction or honors_config"
```
Expected: **FAIL** — `AttributeError: module ... has no attribute 'SAConfig'` and `TypeError` for the new operator params.

- [ ] **Step 3: Implement in `sa.py`**

3a. Add to the imports (top of file, near `import math`):
```python
from dataclasses import dataclass, field
```

3b. Immediately after the `MOVE_WEIGHTS` constant block (after its docstring line), add:
```python


@dataclass
class SAConfig:
    """Tunable SA hyperparameters. Field defaults mirror the module constants
    above (single source of truth). Threaded through auto_layout_polygon →
    workers so a sweep can vary them without code edits. Picklable (crosses the
    ProcessPoolExecutor boundary)."""
    t0_factor: float = T0_FACTOR
    cooling_alpha: float = COOLING_ALPHA
    t_min: float = T_MIN
    reverse_window_fraction: float = REVERSE_WINDOW_FRACTION
    no_grainline_rotation_cap: int = NO_GRAINLINE_ROTATION_CAP
    move_weights: dict = field(default_factory=lambda: dict(MOVE_WEIGHTS))
```

3c. Parameterize `_reverse_move` — change its signature and the cap line:
```python
def _reverse_move(order: list[int], rng: _random.Random,
                  window_fraction: float = REVERSE_WINDOW_FRACTION) -> list[int]:
```
and inside, replace `cap = max(2, math.ceil(n * REVERSE_WINDOW_FRACTION))` with:
```python
    cap = max(2, math.ceil(n * window_fraction))
```

3d. Parameterize `_rotation_flip_move`: leave as-is (no globals).

3e. Parameterize `_sample_move_type`:
```python
def _sample_move_type(rng: _random.Random, weights: dict | None = None) -> str:
    """Pick a move type per the weights distribution (defaults to MOVE_WEIGHTS)."""
    if weights is None:
        weights = MOVE_WEIGHTS
    move_types = list(weights.keys())
    w = [weights[m] for m in move_types]
    return rng.choices(move_types, weights=w, k=1)[0]
```

3f. Parameterize `_temperature_at`:
```python
def _temperature_at(T0: float, k: int, alpha: float = COOLING_ALPHA,
                    t_min: float = T_MIN) -> float:
    """Geometric cooling with a t_min floor."""
    return max(t_min, T0 * (alpha ** k))
```

3g. In `run_sa`, add a `config` parameter (after `clock`):
```python
    clock: Callable[[], float] = time.perf_counter,
    config: "SAConfig | None" = None,
```
and at the very top of the body (before `rng = _random.Random(seed)`):
```python
    cfg = SAConfig() if config is None else config
```
Then replace the four global reads:
- `T0 = max(T_MIN, T0_FACTOR * init_marker)` → `T0 = max(cfg.t_min, cfg.t0_factor * init_marker)`
- `move_type = _sample_move_type(rng)` → `move_type = _sample_move_type(rng, cfg.move_weights)`
- `new_order = _reverse_move(current_order, rng)` → `new_order = _reverse_move(current_order, rng, cfg.reverse_window_fraction)`
- `T_k = _temperature_at(T0, iteration)` → `T_k = _temperature_at(T0, iteration, cfg.cooling_alpha, cfg.t_min)`

- [ ] **Step 4: Run the new tests + the full `test_sa.py` to verify GREEN**

Run:
```
D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/unit/test_sa.py -v
```
Expected: **all PASS** — new tests pass; the existing 19 SA tests still pass (operators keep working via their default args; `run_sa(config=None)` reproduces prior behavior).

- [ ] **Step 5: Commit**

```
git -C D:/openmarker/.worktrees/perf-followups add engine/core/layout/sa.py engine/tests/unit/test_sa.py
git -C D:/openmarker/.worktrees/perf-followups commit -m "feat(engine): SAConfig dataclass + parameterize SA hyperparameters

- core/layout/sa.py: add SAConfig (defaults = module constants); _reverse_move/_sample_move_type/_temperature_at + run_sa read from config
- tests/unit/test_sa.py: SAConfig defaults + parameterized-operator + move-weights-forwarding tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Thread `sa_config` through `heuristic.py` (TDD)

**Files:**
- Modify: `engine/core/layout/heuristic.py` (import :19; worker globals ~:88-95; `_init_sa_worker` :98; `_run_sa_chain` :158; `auto_layout_polygon` sig :778-792 + call sites :917, :988; `_run_sa_phase` sig :1024 + cap use :1055)
- Test: `engine/tests/unit/test_heuristic.py`

- [ ] **Step 1: Write failing tests** — append to `engine/tests/unit/test_heuristic.py`:

```python
def test_auto_layout_sa_config_none_matches_explicit_default():
    """sa_config=None must be bit-identical to sa_config=SAConfig() (serial SA)."""
    from core.layout.heuristic import auto_layout_polygon
    from core.layout.sa import SAConfig
    p = _two_simple_pieces()
    _, m_none, _ = auto_layout_polygon(
        p, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0,
        effort=1, sa_iterations=20, sa_seed=5, sa_config=None)
    _, m_def, _ = auto_layout_polygon(
        p, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0,
        effort=1, sa_iterations=20, sa_seed=5, sa_config=SAConfig())
    assert m_none == m_def


def test_auto_layout_sa_config_deterministic_parallel():
    """A custom SAConfig is forwarded to workers and used deterministically
    (parallel SA path: sa_iterations>=50 + effort=5)."""
    from core.layout.heuristic import auto_layout_polygon
    from core.layout.sa import SAConfig
    cfg = SAConfig(t0_factor=0.1, cooling_alpha=0.90,
                   move_weights={"swap": 2.0, "reverse": 1.0, "rotation_flip": 3.0})
    p = _two_simple_pieces()
    _, m1, _ = auto_layout_polygon(p, 500, "bi", 0.0, effort=5,
                                   sa_iterations=50, sa_seed=11, sa_config=cfg)
    _, m2, _ = auto_layout_polygon(p, 500, "bi", 0.0, effort=5,
                                   sa_iterations=50, sa_seed=11, sa_config=cfg)
    assert m1 == m2
```

- [ ] **Step 2: Run tests to verify they FAIL**

Run:
```
D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/unit/test_heuristic.py -v -k "sa_config"
```
Expected: **FAIL** — `TypeError: auto_layout_polygon() got an unexpected keyword argument 'sa_config'`.

- [ ] **Step 3: Implement in `heuristic.py`**

3a. Line 19 — extend the sa import:
```python
from core.layout.sa import WarmStart, run_sa, NO_GRAINLINE_ROTATION_CAP, SAConfig
```

3b. Add a worker global beside the other `_worker_sa_*` (after line 95 `_worker_sa_disable_pruning: bool = False`):
```python
_worker_sa_config: "SAConfig | None" = None
```

3c. `_init_sa_worker` — add a `sa_config` parameter (end of signature) and store it:
```python
def _init_sa_worker(
    shared_best_value,
    warm_starts,
    blf_input,
    fabric_width_mm,
    fabric_grain_deg,
    allowed_rotations_per_piece,
    disable_nfp_cache,
    disable_pruning,
    sa_config,
):
    global _worker_sa_shared_best, _worker_sa_warm_starts, _worker_sa_blf_input
    global _worker_sa_fabric_width_mm, _worker_sa_fabric_grain_deg
    global _worker_sa_allowed_rotations, _worker_sa_disable_nfp_cache
    global _worker_sa_disable_pruning, _worker_sa_config
    _worker_sa_shared_best = shared_best_value
    _worker_sa_warm_starts = warm_starts
    _worker_sa_blf_input = blf_input
    _worker_sa_fabric_width_mm = fabric_width_mm
    _worker_sa_fabric_grain_deg = fabric_grain_deg
    _worker_sa_allowed_rotations = allowed_rotations_per_piece
    _worker_sa_disable_pruning = disable_pruning
    _worker_sa_disable_nfp_cache = disable_nfp_cache
    _worker_sa_config = sa_config
```

3d. `_run_sa_chain` — pass the config into `run_sa` (the final call, currently ends `shared_best_value=_worker_sa_shared_best,`):
```python
    return run_sa(
        initial_order=initial_order,
        initial_rotations=initial_rotations,
        pieces=_worker_sa_blf_input,
        allowed_rotations_per_piece=_worker_sa_allowed_rotations,
        iterations=iterations,
        max_time_s=max_time_s,
        seed=seed,
        evaluator=evaluator,
        shared_best_value=_worker_sa_shared_best,
        config=_worker_sa_config,
    )
```

3e. `auto_layout_polygon` — add the parameter (after `sa_seed: int = 0,` at line 791):
```python
    sa_config: "SAConfig | None" = None,
```

3f. Both `_run_sa_phase` call sites (lines 917-921 and 988-992) — add `sa_config` as the final argument. Replace each:
```python
            return _run_sa_phase(
                best, warm_starts, blf_input, fabric_width_mm, grain_mode,
                fabric_grain_deg, sa_iterations, sa_max_time_s, sa_seed,
                effort, disable_nfp_cache, disable_pruning, clusters,
            )
```
with (identical except the trailing `sa_config,`):
```python
            return _run_sa_phase(
                best, warm_starts, blf_input, fabric_width_mm, grain_mode,
                fabric_grain_deg, sa_iterations, sa_max_time_s, sa_seed,
                effort, disable_nfp_cache, disable_pruning, clusters, sa_config,
            )
```
(Apply to both occurrences — the serial path ~917 and the parallel path ~988. They are byte-identical, so do them one at a time or use the indentation to disambiguate.)

3g. `_run_sa_phase` signature — add `sa_config` as the last parameter (after `clusters: list,` at line 1037):
```python
    clusters: list,
    sa_config: "SAConfig | None" = None,
) -> tuple[list[Placement], float, float]:
```
Then near the top of `_run_sa_phase` body (before the `allowed_rotations_per_piece` loop at line 1052), add:
```python
    cfg = SAConfig() if sa_config is None else sa_config
```
Replace the three `NO_GRAINLINE_ROTATION_CAP` uses (lines 1055-1058) with `cfg.no_grainline_rotation_cap`:
```python
        if len(rots) > cfg.no_grainline_rotation_cap:
            step = 360.0 / cfg.no_grainline_rotation_cap
            rots = [step * i for i in range(cfg.no_grainline_rotation_cap)]
```
Finally, pass `cfg` into BOTH `_init_sa_worker` calls (the serial branch ~line 1080 and the parallel `initargs` ~line 1100) by appending `cfg` as the final argument in each:
- serial: `_init_sa_worker(sa_shared_best, warm_starts_sorted, blf_input, fabric_width_mm, fabric_grain_deg, allowed_rotations_per_piece, disable_nfp_cache, disable_pruning, cfg)`
- parallel `initargs=(... disable_nfp_cache, disable_pruning, cfg)`

- [ ] **Step 4: Run the new tests + full `test_heuristic.py` to verify GREEN**

Run:
```
D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/unit/test_heuristic.py -v
```
Expected: **all PASS** — new `sa_config` tests pass; all existing tests (incl. `test_auto_layout_default_sa_params_unchanged_behavior`, SA validation, parallel determinism) still pass.

- [ ] **Step 5: Commit**

```
git -C D:/openmarker/.worktrees/perf-followups add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git -C D:/openmarker/.worktrees/perf-followups commit -m "feat(engine): thread sa_config through auto_layout_polygon to SA workers

- core/layout/heuristic.py: sa_config param on auto_layout_polygon; forwarded via _run_sa_phase + _init_sa_worker initargs to run_sa; _run_sa_phase uses config.no_grainline_rotation_cap
- tests/unit/test_heuristic.py: sa_config None==default regression + parallel forwarding determinism

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Sweep harness `bench_sa_sweep.py` (create + smoke)

**Files:**
- Create: `engine/tests/bench_sa_sweep.py`

- [ ] **Step 1: Write the harness** — create `engine/tests/bench_sa_sweep.py` with exactly:

```python
"""Manual SA hyperparameter sweep at grain=90. Not part of pytest.

ALWAYS writes a report (engine/tests/_sweep_report.md) even if stopped by the
soft TTL or interrupted — see the finally block. Per-row results also stream to
engine/tests/_sweep_results.jsonl as they complete, so a hard kill loses at most
the in-flight row.

Run (background):  ...python engine\\tests\\bench_sa_sweep.py
Smoke (fast):      ...python engine\\tests\\bench_sa_sweep.py --smoke
Override TTL:      ...python engine\\tests\\bench_sa_sweep.py --ttl 7200
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.layout.heuristic import auto_layout_polygon
from core.layout.grain import FABRIC_GRAIN_DEG
from core.layout.sa import SAConfig

FABRIC_WIDTH_MM = 1651
GRAIN_MODE = "bi"
COPIES = 10
EFFORT = 5
BAR_MM = 11699.0
SWEEP_TTL_S = 3 * 3600
PER_ROW_CAP_S = 900.0  # per-row sa_max_time_s; bounds a single config so it can't hang past a TTL check
RESULTS_PATH = os.path.join(HERE, "_sweep_results.jsonl")
REPORT_PATH = os.path.join(HERE, "_sweep_report.md")


class _TTLExceeded(Exception):
    pass


def _find_sample_dxf() -> str | None:
    here = os.path.abspath(HERE)
    for _ in range(8):
        candidate = os.path.join(here, "examples", "input", "sample_2.dxf")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent
    return None


def _load_pieces(path: str, copies: int):
    from dataclasses import replace
    from core.dxf import parse_dxf
    from core.geometry import normalize_piece
    with open(path, "rb") as f:
        raw = parse_dxf(f.read())
    base = []
    for i, r in enumerate(raw):
        try:
            base.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    return [replace(bp, id=f"{bp.id}__c{c}") for c in range(copies) for bp in base]


def _rows(smoke: bool):
    """(label, SAConfig, sa_iterations, sa_seed), highest-value first.
    Phase 3 (multi-seed of the best) is appended dynamically in main()."""
    base = SAConfig()
    n = 5 if smoke else 50
    rows = [
        ("baseline sa=0", base, 0, 42),
        ("current-constants", base, n, 42),
    ]
    for t0 in [0.02, 0.1, 0.2]:
        rows.append((f"t0={t0}", dataclasses.replace(base, t0_factor=t0), n, 42))
    for a in [0.90, 0.98]:
        rows.append((f"alpha={a}", dataclasses.replace(base, cooling_alpha=a), n, 42))
    for rw in [0.15, 0.40]:
        rows.append((f"revwin={rw}", dataclasses.replace(base, reverse_window_fraction=rw), n, 42))
    rows.append(("rot-heavy", dataclasses.replace(
        base, move_weights={"swap": 1.0, "reverse": 1.0, "rotation_flip": 3.0}), n, 42))
    rows.append(("order-heavy", dataclasses.replace(
        base, move_weights={"swap": 2.0, "reverse": 2.0, "rotation_flip": 1.0}), n, 42))
    return rows


def _run_row(label, cfg, iters, seed, pieces, started_at, ttl, results):
    if time.perf_counter() - started_at >= ttl:
        raise _TTLExceeded()
    t0 = time.perf_counter()
    max_t = None if iters == 0 else PER_ROW_CAP_S
    _, marker, util = auto_layout_polygon(
        pieces, FABRIC_WIDTH_MM, GRAIN_MODE, FABRIC_GRAIN_DEG, effort=EFFORT,
        sa_iterations=iters, sa_seed=seed, sa_max_time_s=max_t, sa_config=cfg,
    )
    row = {
        "label": label, "seed": seed, "iters": iters,
        "marker": round(marker, 2), "util": round(util, 2),
        "time_s": round(time.perf_counter() - t0, 1),
        "config": dataclasses.asdict(cfg),
    }
    results.append(row)
    with open(RESULTS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
    flag = "  <-- BEATS BAR" if row["marker"] < BAR_MM else ""
    print(f"  {label:18s} seed={seed:<4d} sa={iters:<4d} "
          f"L={row['marker']:9.1f} U={row['util']:5.2f}% t={row['time_s']:6.1f}s{flag}", flush=True)
    return row


def _build_combo(results):
    """Phase 2: from the single-axis screening rows, adopt each axis's
    best-IMPROVING value (one that beat the current-constants baseline)."""
    default = dataclasses.asdict(SAConfig())
    base_rows = [r for r in results if r["config"] == default and r["iters"] > 0]
    baseline = min((r["marker"] for r in base_rows), default=float("inf"))
    adopted = dict(default)
    for key in ["t0_factor", "cooling_alpha", "reverse_window_fraction", "move_weights"]:
        # rows that varied ONLY this key vs the default config
        varied = [r for r in results if r["iters"] > 0
                  and r["config"][key] != default[key]
                  and all(r["config"][k] == default[k] for k in default if k != key)]
        if not varied:
            continue
        best = min(varied, key=lambda r: r["marker"])
        if best["marker"] < baseline:
            adopted[key] = best["config"][key]
    return SAConfig(**adopted)


def _write_report(results, started_at, stopped_reason):
    completed = sorted(results, key=lambda r: r["marker"])
    out = [
        "# SA sweep report", "",
        f"- workload: sample_2.dxf x{COPIES}, fabric={FABRIC_WIDTH_MM}, "
        f"grain={GRAIN_MODE}@{FABRIC_GRAIN_DEG}, effort={EFFORT}",
        f"- bar to beat (strictly <): {BAR_MM:.0f}mm",
        f"- rows completed: {len(results)}",
        f"- elapsed: {time.perf_counter() - started_at:.0f}s",
        f"- stopped: {stopped_reason}", "",
    ]
    if completed:
        best = completed[0]
        out += [
            f"- **best: {best['marker']:.1f}mm / {best['util']:.2f}% "
            f"({best['label']}, seed {best['seed']}, sa={best['iters']})**",
            f"- beats bar? **{'YES' if best['marker'] < BAR_MM else 'no'}**", "",
            "| rank | marker | util | label | seed | sa | t0 | alpha | revwin | move_weights | t(s) |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(completed, 1):
            c = r["config"]
            out.append(
                f"| {i} | {r['marker']:.1f} | {r['util']:.2f} | {r['label']} | {r['seed']} | "
                f"{r['iters']} | {c['t0_factor']} | {c['cooling_alpha']} | "
                f"{c['reverse_window_fraction']} | {c['move_weights']} | {r['time_s']:.0f} |")
    else:
        out.append("- (no rows completed)")
    out.append("")
    text = "\n".join(out)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print("\n" + text, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ttl", type=float, default=SWEEP_TTL_S)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    dxf = _find_sample_dxf()
    if dxf is None:
        print("SKIP: sample_2.dxf not found.", flush=True)
        return 0
    pieces = _load_pieces(dxf, COPIES)
    # Fresh results file each run.
    if os.path.exists(RESULTS_PATH):
        os.remove(RESULTS_PATH)
    print(f"sample_2.dxf x{COPIES} ({len(pieces)} pieces), grain=90, effort={EFFORT}, "
          f"ttl={args.ttl:.0f}s, smoke={args.smoke}", flush=True)

    results: list = []
    started_at = time.perf_counter()
    stopped_reason = "completed"
    try:
        # Phases 0-1 (static single-axis screening).
        for label, cfg, iters, seed in _rows(args.smoke):
            _run_row(label, cfg, iters, seed, pieces, started_at, args.ttl, results)
        final_iters = 5 if args.smoke else 100
        # Phase 2: combine the best-improving value from each axis, at final_iters.
        combo = _build_combo(results)
        _run_row("combo", combo, final_iters, 42, pieces, started_at, args.ttl, results)
        # Phase 3: multi-seed the overall best config (iters>0) at final_iters.
        scored = [r for r in results if r["iters"] > 0]
        if scored:
            best = min(scored, key=lambda r: r["marker"])
            best_cfg = SAConfig(**best["config"])
            seeds = [7, 13] if args.smoke else [7, 13, 21, 99, 123]
            for seed in seeds:
                _run_row(f"best({best['label']})", best_cfg, final_iters, seed,
                         pieces, started_at, args.ttl, results)
    except _TTLExceeded:
        stopped_reason = f"TTL reached ({args.ttl:.0f}s)"
    except KeyboardInterrupt:
        stopped_reason = "KeyboardInterrupt"
    except Exception as e:  # noqa: BLE001 — always finalize a report
        stopped_reason = f"exception: {type(e).__name__}: {e}"
    finally:
        _write_report(results, started_at, stopped_reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Syntax-check**

Run:
```
D:/openmarker/engine/.venv/Scripts/python.exe -m py_compile D:/openmarker/.worktrees/perf-followups/engine/tests/bench_sa_sweep.py
```
Expected: exit 0, no output.

- [ ] **Step 3: Smoke run (verifies the always-report path end-to-end)**

Run (≈1-3 min — tiny iterations):
```
D:/openmarker/engine/.venv/Scripts/python.exe D:/openmarker/.worktrees/perf-followups/engine/tests/bench_sa_sweep.py --smoke --ttl 120
```
Expected: prints rows incrementally and ends with a rendered report; `engine/tests/_sweep_report.md` exists and contains a "best:" line + a results table; `engine/tests/_sweep_results.jsonl` has one line per completed row. (Optional TTL-stop check: re-run with `--smoke --ttl 1` → report still written with "stopped: TTL reached".)

- [ ] **Step 4: Commit** (the `_sweep_*.md/.jsonl` artifacts are NOT committed)

```
git -C D:/openmarker/.worktrees/perf-followups add engine/tests/bench_sa_sweep.py
git -C D:/openmarker/.worktrees/perf-followups commit -m "test(bench): SA hyperparameter sweep harness with TTL + always-report

- tests/bench_sa_sweep.py: grain=90 sweep over SAConfig axes; soft TTL, per-row sa_max_time_s cap, streaming _sweep_results.jsonl, finally-block _sweep_report.md (survives TTL stop / interrupt)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4 (controller): Run the full sweep in the background

No file changes. Controller-run (not a subagent — it's a ~2-3 hr background job).

- [ ] **Step 1:** Ensure `_sweep_*` artifacts from the smoke run are removed/ignored, then launch in the background:
```
D:/openmarker/engine/.venv/Scripts/python.exe D:/openmarker/.worktrees/perf-followups/engine/tests/bench_sa_sweep.py
```
(3 h soft TTL; self-finalizes and writes `_sweep_report.md` regardless.)

- [ ] **Step 2:** On completion (or TTL), read `engine/tests/_sweep_report.md`. Record: best marker/util, the config that produced it, and whether it beats 11699 across the multi-seed rows. This decides Task 5's branch.

---

## Task 5 (controller): Outcome handling

Branch on Task 4's report. Exactly one of 5A / 5B.

### 5A — A config beats 11699 across ≥3 seeds (WIN)
- [ ] Update `engine/core/layout/sa.py` module constants (and thus `SAConfig` defaults) to the winning values. Re-run `test_sa.py` (defaults test will now assert the new values — update it to match).
- [ ] Flip `engine/tests/bench_sa.py` G5 expectation to an expected pass; update its sweep iteration list/seed if the winner needs it.
- [ ] PERFORMANCE.md: §1 SA row → now beats bar (drop "superseded"); §4.6 record the tuned constants + `bench_sa_sweep.py`; §5.B SA row → win; new §6 entry with the sweep table. BACKLOG SA line → tuning win.
- [ ] Re-run `bench_sa.py` to confirm G5 passes at the new defaults.
- [ ] Commit (one message per changed file in the body).

### 5B — No config beats 11699 (GAP ANALYSIS)
- [ ] Leave `sa.py` constants at their current values (or, if a config was strictly better than current-constants but still > bar, optionally adopt it — note the decision). Do NOT change defaults if no improvement.
- [ ] PERFORMANCE.md: new §6 entry (2026-06-04) with the grain=90 sweep table, the headroom finding (warm-start already at bar; SA's order×rotation moves can't break below it), and recommended next levers (GA half, concave-bay fill, grain-compatible mirroring, more sort strategies). Update §4.6 (add `SAConfig` + `bench_sa_sweep.py` to the code map) and §5.B SA row (sweep done; gap analysis filed). BACKLOG SA line → "tuning swept, gap analysis filed".
- [ ] Commit.

(`SAConfig` + the sweep harness ship either way — reusable scaffolding for the GA follow-up.)

---

## Task 6 (controller): Full-suite verification + push

- [ ] **Step 1:** Full suite:
```
D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/unit D:/openmarker/.worktrees/perf-followups/engine/tests/integration -q
```
Expected: all pass.

- [ ] **Step 2:** Confirm tree clean (`_sweep_*` artifacts untracked/ignored, not staged), review the log:
```
git -C D:/openmarker/.worktrees/perf-followups status --short
git -C D:/openmarker/.worktrees/perf-followups log --oneline 7bf96be..HEAD
```

- [ ] **Step 3:** With the user's OK, push to update PR #12:
```
git -C D:/openmarker/.worktrees/perf-followups push
```

---

## Self-review notes (author)

- **Spec coverage:** SAConfig+threading (Tasks 1-2), sweep harness w/ TTL+always-report (Task 3), full sweep run (Task 4), win/gap-analysis disposition (Task 5A/5B), tests (Tasks 1-2), docs (Task 5), suite+push (Task 6). Acceptance criteria 1→Task 2 regression test, 2→Task 3 smoke, 3→Task 5, 4→Task 6.
- **Placeholders:** none. Task 5's two branches are both concrete; execution selects one from Task 4's measured report (an empirical decision, not a placeholder). The sweep's bbox/winner numbers are produced by Task 4 by design.
- **Type/name consistency:** `SAConfig`, `sa_config`, `_worker_sa_config`, fields `t0_factor`/`cooling_alpha`/`t_min`/`reverse_window_fraction`/`no_grainline_rotation_cap`/`move_weights` — consistent across sa.py, heuristic.py, tests, and the harness.
