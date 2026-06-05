# SA hyperparameter tuning at grain=90

**Date:** 2026-06-04
**Status:** Approved
**Branch / PR:** `feat/bench-grain-fix` → PR #12 (same PR as the grain-lock fix, per user request)
**Depends on:** the 2026-06-04 grain lock (`FABRIC_GRAIN_DEG = 90`). SA must be benchmarked at the locked grain; prior grain=0 SA numbers are superseded.

---

## Problem / motivation

The SA meta-heuristic (shipped opt-in 2026-05-31) did not beat the bar — best 12077mm at sa=200/seed=42, 11977mm at sa=50/seed=99. **Those runs were at the erroneous `fabric_grain_deg=0` and are superseded.** After the grain lock, the warm-start baseline at grain=90 is already **11699.4mm = the bar**, so SA's job is now to go *strictly below* an already-good baseline.

Two obstacles to tuning:
1. SA's hyperparameters are fixed module constants in `sa.py` (`T0_FACTOR`, `COOLING_ALPHA`, `T_MIN`, `REVERSE_WINDOW_FRACTION`, `NO_GRAINLINE_ROTATION_CAP`, `MOVE_WEIGHTS`) — not tunable without a code edit.
2. SA runs in spawned `ProcessPoolExecutor` workers (Windows spawn → fresh re-import), so monkeypatching module globals in the main process does **not** reach workers. Hyperparameters must be *threaded through* to workers.

Workload note: on the canonical workload every piece has a grainline → exactly 2 allowed rotations each, so `NO_GRAINLINE_ROTATION_CAP` is irrelevant here. The live tunables are `t0_factor`, `cooling_alpha`, `t_min`, `reverse_window_fraction`, `move_weights`, and `sa_iterations`.

## Goal / success criteria

- **Scaffolding:** hyperparameters injectable end-to-end including spawned workers; default reproduces current behavior bit-for-bit.
- **Sweep:** a reproducible results table at grain=90 (full sweep, ~1–2 hr, per user's "full sweep regardless" choice).
- **Outcome:** EITHER a config with marker **< 11699 strictly across ≥3 seeds** (baked into the defaults), OR a documented **gap analysis** explaining why SA in its current form can't, and what would be needed.

## Design

### 1. `SAConfig` + threading (Approach A)

- New `@dataclass SAConfig` in `sa.py` with fields mirroring the six constants; defaults pull from the existing module constants (single source of truth), `move_weights` via `field(default_factory=...)`. Picklable (crosses the process boundary via `initargs`).
- `run_sa(..., config: SAConfig = SAConfig())`. The move/cooling helpers (`_reverse_move`, `_temperature_at`, `_sample_move_type`) gain parameters for the values they need, defaulting to the module constants so existing direct-call unit tests stay green; `run_sa` passes `config.*`.
- Thread an optional `sa_config: SAConfig | None = None` on `auto_layout_polygon` → `_run_sa_phase` → `_init_sa_worker` `initargs` (+ a worker global) → `_run_sa_chain` → `run_sa(config=...)`. `_run_sa_phase` reads `config.no_grainline_rotation_cap` instead of the module global (heuristic.py:1055).
- `sa_config=None` ⇒ `SAConfig()` ⇒ **bit-identical to current behavior** (regression guard).

### 2. Sweep harness — new `engine/tests/bench_sa_sweep.py`

Standalone manual bench (keeps `bench_sa.py` as the PR-gate bench). Loads the canonical workload at grain=90 (`FABRIC_GRAIN_DEG`), runs rows of `(label, SAConfig, sa_iterations, sa_seed)` via `auto_layout_polygon`, prints an incremental (`flush=True`) table — marker / util / wall-clock — and flags any row with marker `< 11699`. Designed to be run in the background.

### 3. Sweep methodology (phased)

- **Phase 0:** baseline `sa=0` (≈11699.4) + current-constants SA reference at the screening iteration count.
- **Phase 1 — single-axis screening** (~sa=50, fixed seed): `t0_factor ∈ {0.02, 0.05, 0.1, 0.2}`, `cooling_alpha ∈ {0.90, 0.95, 0.98}`, `reverse_window_fraction ∈ {0.15, 0.25, 0.40}`, `move_weights ∈ {uniform, rotation-flip-heavy, order-heavy}`.
- **Phase 2 — combine** best-of-each-axis into ~3–5 candidate configs (~sa=100).
- **Phase 3 — multi-seed** validate the top 1–2 configs across **5 seeds** vs the bar. Seeds are first-class: grain=0 evidence showed seed choice mattered more than iteration count (multimodal landscape).
- **Budget:** ≈3.4 s per SA iteration wall-clock at effort=5 → sa=50 ≈ 3 min, sa=100 ≈ 6 min → ~15–20 runs ≈ ~2 hr. The harness prints incrementally so the run can be stopped early.

### 4. Outcome handling

- **Win (marker < 11699 across ≥3 seeds):** bake the winning values into the `SAConfig` field defaults / module constants; flip `bench_sa.py`'s G5 to an expected pass; update PERFORMANCE.md §1 (SA row), §4.6, §5.B, §6 (drop the "superseded" caveat, record the win + sweep table).
- **No win:** documented **gap analysis** in PERFORMANCE.md §6 — the grain=90 sweep table, the headroom finding, and recommended next levers (GA half, concave-bay fill, grain-compatible mirroring, more sort strategies). No algorithm change beyond the now-tunable `SAConfig` scaffolding; the constants stay at their current (or best-found-but-not-bar-beating) values, decision recorded.

### 5. Testing

- `engine/tests/unit/test_sa.py`: `run_sa` honors `SAConfig` via the stub evaluator — e.g. `move_weights={"swap":1.0}` only produces swaps; a different `cooling_alpha`/`t0_factor` changes the temperature schedule (`_temperature_at`); `reverse_window_fraction` caps the reverse window. Plus: default `SAConfig()` matches the module constants.
- `engine/tests/unit/test_heuristic.py`: `auto_layout_polygon(sa_config=...)` forwards the config to workers (a config that changes the result vs default; determinism with a fixed seed); **regression** — `sa_config=None` bit-identical to the no-arg call.
- All existing SA tests stay green.

### 6. Docs

- PERFORMANCE.md §4.6 code map gains `SAConfig` + `bench_sa_sweep.py`; §6 outcome entry (2026-06-04); §1/§5.B SA annotations updated per the outcome.
- BACKLOG: update the SA follow-up line with the tuning result.

## Out of scope (deliberate)

- The GA half (separate follow-up; shares the SA scaffold).
- Any UI / HTTP-API exposure of SA or `SAConfig` (engine-Python-only knob, matching `sa_iterations`/`disable_*`).
- Changes to the warm-start, BLF, clustering, or grain logic.

## Acceptance criteria

1. `SAConfig` threads end-to-end; `auto_layout_polygon(sa_config=None)` is bit-identical to today (regression test passes).
2. `bench_sa_sweep.py` runs at grain=90 and produces the phased results table.
3. A definitive outcome: either a ≥3-seed config beating 11699 (baked in, gates/docs updated) **or** a committed gap analysis with evidence and recommended next levers.
4. Full engine unit + integration suites green.

## Risks

- **SA may have little headroom at grain=90** (warm-start already at the bar) → likely outcome is the gap analysis. Acceptable per the goal; the scaffolding + evidence are still valuable and reusable for the GA follow-up.
- **Sweep wall-clock** is long; mitigated by background execution + incremental output + early-stop.
- **Determinism across seeds** must hold for the multi-seed validation to mean anything (existing G3 covers same-seed determinism).
