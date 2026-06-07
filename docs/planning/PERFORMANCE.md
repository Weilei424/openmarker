# Nesting Performance Log

> Living document for algorithm + performance work on OpenMarker's NFP-BLF
> layout engine. Tracks design decisions, measurements, opt-in mechanisms, and
> open follow-ups. `BACKLOG.md` keeps high-level progress only and references
> this doc for detail. All new perf-related findings and design decisions
> should be added here.

---

## 0. Optimization priorities (binding)

When trade-offs arise, optimize in this strict order:

1. **Lower marker length (mm)** — primary metric. Directly tied to fabric
   saved per cut, which is what the tool exists for.
2. **Higher utilization (%)** — derived from marker length on a fixed
   workload but reported separately for readability.
3. **Layout operation duration (ms)** — distant third. Never sacrifice
   marker length to win on time.

Concretely: a 5% marker-length improvement that doubles layout time is
*acceptable*; a 5% speedup that costs even 1% on marker length is **not**.
This rule applies retroactively — if the bench-vs-GUI variance investigation
(§ 5.C) reveals that any of PR #7 / PR #8's pruning regresses marker length
in some configuration, the pruning behavior must be re-evaluated under this
rule, regardless of the speedup it delivers.

**Update (2026-06-04):** the § 5.C investigation resolved the variance to a
benchmark grain-config divergence (`fabric_grain_deg` 0 vs 90), **not** pruning.
PR #7/#8 pruning is confirmed result-preserving and is exonerated.

---

## 1. Headline benchmark

Canonical real-workload benchmark used for all gain comparisons:

`examples/input/sample_2.dxf × 10 copies` at `fabric_width_mm=1651`,
`grain_mode="bi"`, `fabric_grain_deg=90.0` (the locked production grain — see
§ 5.C; 190 pieces total — 19 distinct base pieces × 10 identical copies each).

| Source                                                | Marker length (mm) | Utilization | Notes                                                        |
| ----------------------------------------------------- | ------------------ | ----------- | ------------------------------------------------------------ |
| Commercial reference                                  | 10599              | 86.1%       | Out-of-scope aspirational target. ~9% better than the bar.   |
| **OpenMarker pre-PR-#7 baseline (the bar to beat)**   | **11699**          | **79.4%**   | **Historical best on this workload — and what the 2026-05-30 manual GUI run reproduced exactly. All future algorithm changes must hit ≤ 11699mm marker / ≥ 79.4% utilization on this workload to count as a win.** |
| Current bench unclustered NFP-BLF (effort=5)          | 11699.4            | 79.39%      | At the locked 90° grain the bench now matches the GUI and the bar (§ 5.C). Was 12249/75.83% at the erroneous grain=0. |
| **OpenMarker SA-tuned (rotation-flip 3:1, opt-in)**   | **11578.5**        | **80.22%**  | **Beats the bar ~1.0% — best of the 2026-06-05 grain=90 SA sweep; < bar on ≥3 seeds. Opt-in via `sa_iterations>0`; see § 4.6 + § 6 [2026-06-05].** |
| **OpenMarker GA-tuned (uniform-weight, opt-in)**      | **11412.5**        | **81.39%**  | **`bench_ga.py` gens=12 — beats the bar ~2.5% and SA's best (11517) by ~0.9%. The time-capped sweep's multi-seed best is 11426.6, < bar on 5/5 seeds (11426–11485). Opt-in via `ga_generations>0`; see § 4.7 + § 6 [2026-06-05].** |
| Clustering — bbox path (off by default, opt-in)       | 24649.7            | 37.68%      | +110.7% vs the bar. Mechanism shipped opt-in; see §4. (Re-measured at grain=90.) |
| Clustering — union path (off by default, opt-in)      | 23591.6            | 39.37%      | +101.6% vs the bar. Beats bbox by ~4% but still loses. See §4. (Re-measured at grain=90.) |

**Bench script:** `engine/tests/bench_clustering.py`. Run with:

```
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\bench_clustering.py
```

Prints a 3-column off/bbox/union matrix on 4 scenarios (identical rects,
two-groups, singletons, `sample_2.dxf × 10` serial + parallel). 6 programmatic
acceptance gates; exits 1 on failure. Run this whenever the algorithm changes
— it's the fastest way to confirm no regression on either disabled path.

---

## 2. Shipped improvements

### PR #7 — Serial branch pruning

Aborts sort-strategies whose partial marker length already meets or exceeds
the best complete result. The monotone-bound argument: BLF's partial marker
length is non-decreasing in the number of placed pieces — placing more can
only push the bottom edge further down, never bring it up — so once a
partial passes the cutoff, the run cannot win.

**Measured speedup:** 1.04×–1.65× on synthetic inputs, 1.18× on the
sample_2.dxf × 10 real workload (190 pieces, bi grain).

**Code:** `engine/core/layout/heuristic.py::_blf_pack_nfp` raises
`_PrunedRun` when `current_max_bottom + EDGE_GAP >= effective_cutoff`. The
serial driver in `auto_layout_polygon` catches and skips to the next
strategy. `disable_pruning: bool = False` on `auto_layout_polygon` turns it
off for A/B benchmarking (mirrors `disable_nfp_cache`).

### PR #8 — Parallel branch pruning (shared `multiprocessing.Value`)

Cross-worker pruning in the `ProcessPoolExecutor` path: workers share a
`multiprocessing.Value('d', float('inf'))` cutoff. Main process publishes
completed-strategy marker lengths into it as a running min via
`as_completed`; workers read it during BLF and self-abort once their partial
passes the cutoff. Result identical to serial mode.

**Measured wall-clock on sample_2.dxf × 10 (190 pieces, bi grain):**

| Mode                          | Wall-clock | Notes                                  |
| ----------------------------- | ---------- | -------------------------------------- |
| Serial, pruning on            | 25.7s      | Pre-parallel baseline.                 |
| Parallel effort=5, pruning on | 11.3s      | 2.3× speedup from parallelism.         |
| Parallel effort=5, no pruning | 12.5s      | Pruning contributes ~10% within parallel. |

`/cancel-layout` terminates worker children via
`kill_current_executor()` so parallel strategies abort ASAP rather than
running to completion. The resulting `BrokenProcessPool` from
`future.result()` is translated to `CancellationError`.

### PR #9 — Identical-piece clustering MECHANISM (bbox path, opt-in)

Groups copies by base id, packs each group into a rigid bbox super-piece,
expands placements after BLF. Implementation correct (17 unit tests cover
grouping, packing, expansion, grain-rotation feasibility, bi-grain
expansion, oversized-group passthrough).

**Result: regresses sample_2.dxf × 10 by +145%** (29958mm vs 12249mm) because
rigid bbox super-pieces can't interleave with other piece types in shared
fabric rows. Shipped off (`disable_clustering: bool = True`); preserved as a
per-group fallback for the union path (the 2026-05-26 work).

See §4 for opt-in instructions; the mechanism is kept in the tree.

### True-union polygon clusters (2026-05-26, opt-in alternative)

Adds `cluster_polygon: 'union' | 'bbox' = 'union'` to `auto_layout_polygon`.
`pack_cluster_union` runs an inner NFP-BLF on each group's copies with
cluster-local rotations, Shapely-unions the placed polygons, strips interior
holes, simplifies to `VERTEX_CAP=200` exterior vertices. `pack_cluster_bbox`
(PR #9 path) kept as per-group fallback when union returns MultiPolygon or
exceeds VERTEX_CAP after simplify. `Cluster` gains `copy_local_rotations`
so bi-mode clusters can mix 0° and 180° copies internally. `_blf_pack_nfp`
gains `override_rotations` + `skip_validation` plumbing for the inner-BLF
call. NFP cache shared across `cols` iterations.

**Result: shipped opt-in, not default.** The acceptance gate (strictly beat
unclustered 12249mm on `sample_2.dxf × 10`) was NOT met: union=27336mm,
bbox=29958mm, off=12249mm. Root cause is structural, not a bug — when every
base_id has copies (the typical garment-marker case), every group gets
clustered, leaving no singletons to slot into cluster perimeter bays. The
union polygon's bay-exposure benefit is unrealized while rigid clusters
still block row interleaving. Union still beats bbox by ~8%, validating
that the union mechanism itself works. Bench gate relaxed from
`union < off` to `union <= bbox` (the realistic floor) before shipping.

**Spec:** `docs/superpowers/specs/2026-05-26-true-union-polygon-clusters-design.md`
**Plan:** `docs/superpowers/plans/2026-05-26-true-union-polygon-clusters.md`

### This PR — Simulated annealing meta-heuristic wrapper (opt-in)

Wraps `_blf_pack_nfp` as the fitness function of a Metropolis SA chain over
`(piece-ordering × per-piece rotation choice)` with multi-restart parallelism
on the existing `ProcessPoolExecutor` scaffold. Three new opt-in params on
`auto_layout_polygon`: `sa_iterations`, `sa_max_time_s`, `sa_seed`.
Engine-Python-only (no API/UI). Mutually exclusive with
`disable_clustering=False`.

Bench result on the canonical workload (sample_2.dxf × 10, fabric=1651mm,
bi-grain, effort=5):

> Note: these SA numbers were measured at the erroneous `fabric_grain_deg=0` and
> are superseded. At the locked 90° grain the SA-tuning follow-up (rotation-flip
> weighted 3:1) beats the bar — 11578.5mm / 80.22%. See § 6 [2026-06-05].

| `sa_iterations` | Marker length (mm) | Utilization | Time (ms) |
|---|---|---|---|
| 0 (warm-start only) | 12249.1 | 75.83% | 12020 |
| 50 (seed 42) | 12176.2 | 76.28% | 190743 |
| 100 (seed 42) | 12164.3 | 76.36% | 353483 |
| 200 (seed 42) | 12077.5 | 76.90% | 678065 |

G5 (beat the bar 11699mm) status: **FAIL**. Best SA marker in the main sweep
was 12077.5mm at sa=200/seed=42 — short of the bar by 378mm (3.2%). A
separate determinism check at sa=50/seed=99 produced 11977mm (short by
278mm / 2.4%), revealing that seed choice matters more than iteration count
at these scales. Filed as a follow-up tuning task (T0_FACTOR sweep,
alternative cooling, adaptive neighbor weights).

**Code:** `engine/core/layout/sa.py` (driver), `engine/core/layout/heuristic.py`
(orchestration + `_blf_pack_nfp` shape extensions). See § 4.6 for the code map.

---

## 3. NFP cache and per-call optimizations (shipped earlier, baseline behavior)

`_blf_pack_nfp` accepts a per-call `nfp_cache` dict keyed by
`(base_id_a, rot_a, base_id_b, rot_b)`. Reuses Minkowski-sum results across
sort strategies and grain modes within one `auto_layout_polygon` call.
`_get_or_compute_nfp` also serves reverse-direction requests by flipping a
cached forward result via `shapely.affinity.scale(..., -1, -1)` (identity
`NFP(B, A) = -NFP(A, B)`), doubling effective hit rate across sort
strategies that visit piece pairs in different orders.

`disable_nfp_cache: bool = False` on `auto_layout_polygon` turns it off for
A/B benchmarking. Only meaningful on the serial path; parallel workers
always rebuild per-worker caches.

---

## 4. Disabled-by-default approaches — code map + opt-in

> Both clustering paths (bbox from PR #9, union from the 2026-05-26 work) are present in
> the engine but disabled by default because neither beats unclustered
> NFP-BLF on the headline workload. The mechanisms are correct, tested, and
> ready to re-enable the moment a workload (or a follow-up algorithm change)
> makes them win. **Do NOT delete these paths** — re-implementing them costs days.

### 4.1 Identical-piece clustering — bbox path (`cluster_polygon="bbox"`)

- **Code:** `engine/core/layout/clustering.py::pack_cluster_bbox` — grid-packs
  N copies, super-piece polygon = bbox rectangle. Helper plumbing: `Cluster`
  dataclass, `group_pieces_by_base_id`, `expand_cluster_placement`. Wired
  through `pre_cluster_pieces` (dispatch + fallback ladder) and
  `auto_layout_polygon` (`disable_clustering` + `cluster_polygon` params).
- **Why disabled:** rigid bbox super-pieces can't interleave with other
  piece types in shared fabric rows. Regresses `sample_2.dxf × 10` by +145%.
- **Opt-in invocation:**
  ```python
  from core.layout.heuristic import auto_layout_polygon
  placements, marker, util = auto_layout_polygon(
      pieces, fabric_width_mm=1651, grain_mode="bi", fabric_grain_deg=0.0,
      disable_clustering=False, cluster_polygon="bbox",
  )
  ```
- **Tests:** `engine/tests/unit/test_clustering.py` (17 tests covering
  grouping, packing, expansion, grain-rotation feasibility, bi-grain
  expansion, oversized-group passthrough).

### 4.2 Identical-piece clustering — union path (`cluster_polygon="union"`)

- **Code:** `engine/core/layout/clustering.py::pack_cluster_union` — runs an
  inner NFP-BLF on each group's copies via
  `_blf_pack_nfp(override_rotations=..., skip_validation=True)`,
  Shapely-unions placed polygons, strips interior rings, simplifies to
  `VERTEX_CAP=200` (`SIMPLIFY_TOL_MM=0.5`). Falls back to bbox per-group
  when union returns MultiPolygon or stays over cap after simplify. Inner-BLF
  shim params live on `engine/core/layout/heuristic.py::_blf_pack_nfp`
  (`override_rotations`, `skip_validation`).
- **Why disabled:** structural — see § 2's true-union polygon clusters entry. Union beats bbox by ~8%
  but still ~2× worse than unclustered BLF on workloads where every
  base_id has copies (no singletons left to slot into cluster bays).
- **Opt-in invocation:**
  ```python
  placements, marker, util = auto_layout_polygon(
      pieces, fabric_width_mm=1651, grain_mode="bi", fabric_grain_deg=0.0,
      disable_clustering=False, cluster_polygon="union",  # union is the default WHEN enabled
  )
  ```
- **Tests:** `engine/tests/unit/test_clustering.py` (11 union-specific tests
  covering share-edge collapse, height-width sort key, bi-mode 0°/180° local
  rotations, holes stripping, singleton early return, monkeypatched
  MultiPolygon fallback, vertex-cap simplify) + `engine/tests/unit/test_heuristic.py`
  (4 integration tests: opt-in union path, opt-in bbox-PR#9-equivalence,
  default-off regression guard, union ≤ bbox on homogeneous).

### 4.3 Frontend / API exposure

Neither `cluster_polygon` nor `disable_clustering` is exposed via the engine
HTTP API or the React UI. To wire them through, add to the `POST /auto-layout`
request body in `engine/api/main.py`, then plumb through
`frontend/src/hooks/useAutoLayout.ts` and surface a control in the Advanced
sidebar. Until a workload demonstrates a win, leave them as engine-Python-only
knobs.

### 4.4 When to re-enable by default

The default flip (`disable_clustering=False`) is gated on a real-workload
bench where `union.marker < off.marker` strictly. The clustering follow-ups
(§5.A — partial clustering, heterogeneous clustering, cluster-aware sort)
each target the structural barrier; landing any one of them and re-running
the bench is the path to flipping the default.

### 4.5 Partial clustering (`cluster_fraction < 1.0`)

- **Code:** `engine/core/layout/clustering.py::pre_cluster_pieces` — per-group split: `k = floor(N * cluster_fraction)` copies enter the cluster, last `N - k` join the outer BLF as singletons. When `k < 2`, the whole group passes through as singletons (no cluster). Applies to both `cluster_polygon="union"` and `cluster_polygon="bbox"` because the split lives in `pre_cluster_pieces`, before path dispatch.
- **Why disabled by default:** `cluster_fraction=1.0` (the default) is bit-identical to pre-PR behavior. Lower values are opt-in.
- **Opt-in invocation:**
  ```python
  placements, marker, util = auto_layout_polygon(
      pieces, fabric_width_mm=1651, grain_mode="bi", fabric_grain_deg=0.0,
      disable_clustering=False, cluster_polygon="union", cluster_fraction=0.7,
  )
  ```
- **Tests:** 13 unit tests in `engine/tests/unit/test_clustering.py` (validation, split math, min-cluster promotion, heterogeneous groups, fallback ladder, bbox-path coverage) + 3 integration tests in `engine/tests/unit/test_heuristic.py`.
- **Bench:** `engine/tests/bench_clustering.py` sweeps `[1.0, 0.9, 0.8, 0.7, 0.5]` on `sample_2.dxf × 10` at `effort=5`. Best fraction reported in § 6's 2026-05-30 entry below.

### 4.6 SA meta-heuristic (`sa_iterations > 0`)

- **Code:** `engine/core/layout/sa.py` — `run_sa` driver + `SAConfig` (tunable
  hyperparameters; field defaults = the module constants). `heuristic.py::_run_sa_phase`
  orchestrates the multi-restart chains; `auto_layout_polygon(sa_config=...)`
  threads a config to the `_init_sa_worker` + `_run_sa_chain` workers (it must
  travel via `initargs` — spawned workers re-import fresh). Sweep harness:
  `engine/tests/bench_sa_sweep.py` (soft TTL + always-writes-a-report).
- **Why opt-in:** First-PR scope per design spec
  (`docs/superpowers/specs/2026-05-31-sa-meta-heuristic-design.md`).
  Same policy as `disable_clustering` / `cluster_fraction` in § 4.3.
- **Opt-in invocation:**
  ```python
  from core.layout.heuristic import auto_layout_polygon
  placements, marker, util = auto_layout_polygon(
      pieces, fabric_width_mm=1651, grain_mode="bi", fabric_grain_deg=0.0,
      effort=5, sa_iterations=200, sa_seed=42,
  )
  ```
- **Mutual exclusion:** `sa_iterations > 0` combined with `disable_clustering=False`
  raises `ValueError`. Combining SA with clustering is a future-work item
  (would need a per-chain decision whether to operate on cluster super-pieces
  or expanded pieces).
- **Constants** (module-level in `sa.py`; also the `SAConfig` field defaults —
  tunable per-call via `auto_layout_polygon(sa_config=...)`, engine-Python-only):
  - `T0_FACTOR = 0.05` — initial temperature as a fraction of warm-start marker
  - `COOLING_ALPHA = 0.95` — geometric cooling per iteration
  - `T_MIN = 1e-3` — temperature floor
  - `REVERSE_WINDOW_FRACTION = 0.25` — reverse-move window cap
  - `NO_GRAINLINE_ROTATION_CAP = 4` — angles `[0, 90, 180, 270]` for no-grainline pieces
  - `MOVE_WEIGHTS = {"swap": 1.0, "reverse": 1.0, "rotation_flip": 3.0}` — rotation_flip
    tuned to 3.0 (2026-06-05 grain=90 sweep — beats the bar; § 6)
- **Tests:** `engine/tests/unit/test_sa.py` (19 unit tests against stub
  evaluator) + `engine/tests/unit/test_heuristic.py` (validation + integration
  tests for monotone non-worsening, parallel determinism, composability with
  `disable_pruning`, `sa_max_time_s` termination).
- **Bench:** `engine/tests/bench_sa.py` sweeps `sa_iterations` on the canonical
  workload — G2–G5 are PR-blocking and G5 (beat the bar) now passes at the tuned
  default. `engine/tests/bench_sa_sweep.py` is the full grain=90 hyperparameter
  sweep that found the win. See § 6 [2026-06-05]. (The grain=0 sweep table above
  is superseded.)

### 4.7 GA meta-heuristic (`ga_generations > 0`)

- **Code:** `engine/core/layout/ga.py` — `run_ga` island driver + `GAConfig`
  (tunable hyperparameters; field defaults = the module constants) + operators
  (`_order_crossover`, `_uniform_rotation_crossover`, `_tournament_select`,
  `_mutate` — the latter reuses `sa.py`'s `_swap_move`/`_reverse_move`/
  `_rotation_flip_move`). `heuristic.py::_run_ga_phase` orchestrates K independent
  island populations (one per worker); `auto_layout_polygon(ga_config=...)` threads
  a config to the `_init_ga_worker` + `_run_ga_chain` workers via `initargs`. Sweep
  harness: `engine/tests/bench_ga_sweep.py` (soft TTL + always-writes-a-report).
- **Island model:** each worker runs a full GA seeded from
  `warm_starts_sorted[worker_index % len]` (deterministic tie-break on
  `(marker, mode, piece-ids)`); the best individual across islands and the retained
  warm-start wins. **No cross-island shared-cutoff pruning** — it would +∞-poison
  the worse-than-best offspring GA recombines from (collapsing the population), so
  GA omits it and is **deterministic per seed** when generations (not
  `ga_max_time_s`) is the binding budget.
- **Why opt-in:** same policy as SA (§ 4.6) — engine-Python-only, off by default.
- **Opt-in invocation:**
  ```python
  from core.layout.heuristic import auto_layout_polygon
  placements, marker, util = auto_layout_polygon(
      pieces, fabric_width_mm=1651, grain_mode="bi", fabric_grain_deg=0.0,
      effort=5, ga_generations=12, ga_seed=42,
  )
  ```
- **Mutual exclusion:** `ga_generations > 0` raises `ValueError` if combined with
  `disable_clustering=False` OR with `sa_iterations > 0` (one meta-heuristic per call).
- **Constants / `GAConfig` fields** (module-level in `ga.py`; tunable per-call via
  `auto_layout_polygon(ga_config=...)`, engine-Python-only):
  - `POPULATION_SIZE = 30`, `CROSSOVER_RATE = 0.9`, `MUTATION_RATE = 0.2`,
    `TOURNAMENT_SIZE = 3`, `ELITISM_COUNT = 2`, `SEED_MUTATION_MOVES = 2`,
    `NO_GRAINLINE_ROTATION_CAP = 4` (reused from `sa.py`).
  - `MUTATION_MOVE_WEIGHTS = {"swap":1, "reverse":1, "rotation_flip":1}` — UNIFORM,
    the 2026-06-05 sweep winner. Uniform beats rotation-flip-heavy for GA because
    the uniform rotation crossover already recombines per-piece rotations, so
    mutation is better spent on order diversity — the **opposite** of SA's tuning. See § 6.
- **Tests:** `engine/tests/unit/test_ga.py` (operators + `run_ga` against a stub
  evaluator: monotone, determinism, time-cap, cancellation, infeasible→+∞) +
  `engine/tests/unit/test_heuristic.py` (validation, opt-in path, default-off guard,
  parallel determinism, GA-phase-invoked spy).
- **Bench:** `engine/tests/bench_ga.py` (G1–G5; G5 beat-the-bar is PR-blocking and
  passes at the uniform default). `engine/tests/bench_ga_sweep.py` is the full
  grain=90 sweep that found the win. See § 6 [2026-06-05].

---

## 5. Open follow-ups (ranked by gain-per-effort)

### 5.A Clustering structural-barrier follow-ups

> The true-union mechanism is shipped opt-in; flipping the default requires
> a workload where union beats unclustered BLF. The fundamental constraint:
> a workload must have BOTH clusters (multi-copy base pieces) AND singletons
> (base pieces with copies=1) so BLF can slot the singletons into the
> cluster perimeter bays. Garment markers fail this — every base piece has
> 10 copies. Three approaches could break the barrier:

- [x] **Partial clustering (`cluster_fraction < 1.0`).** Shipped opt-in; see § 4.5. Bench sweep on `sample_2.dxf × 10` confirms no fraction beats off=12249mm — structural barrier holds. Best fraction `0.5` at `L=13512.3mm` cuts the full-cluster baseline of 27336mm in HALF (and beats bbox's 29958mm by ~55%), but unclustered NFP-BLF still wins. Filed for posterity in § 6 [2026-05-30 entry].
- [ ] **Heterogeneous clustering.** Cluster pieces with *different* base_ids
  together so the marker still has "loose" pieces left over. Combinatorial
  search over which pieces to cluster; needs care to avoid blowup.
  **Medium-high effort.** Replaces the per-base-id grouping in
  `pre_cluster_pieces`.
- [ ] **Cluster-aware outer sort.** When clusters and singletons coexist,
  sort to interleave them (cluster, then small singleton into bay, then
  next cluster). Composes with both other items. **Low effort,** but only
  useful once one of the above is in.

### 5.B General nesting algorithm wins

| Item                                        | Effort      | Estimated gain |
| ------------------------------------------- | ----------- | -------------- |
| **More sort strategies (8–12 instead of 4)** — add perimeter-DESC, diagonal-DESC, aspect-ratio-extremes-first, hilbert-curve ordering. One named function each; benefits compose with parallel pruning. | Low         | 0.5–2pp |
| **Grain-compatible mirroring** — when `grain_mode == "bi"`, allow horizontal reflection of pieces (flip x-coords within bbox center). Adds reflected copies to the rotation candidate set. | Medium      | 1–3pp |
| **Concave-bay fill pass** — post-pass after primary BLF: for each large piece with a concave bay (armhole curves), tuck small unplaced pieces into the bay region. Bays detected via polygon difference of bbox minus polygon. | High — bay-detection geometry + second placement pass | 1–3pp on garment workloads |
| **SA + GA meta-heuristic wrappers** — BOTH SHIPPED OPT-IN; tuned 2026-06-05 (see § 4.6 / § 4.7 + § 6). Wrap NFP-BLF as fitness over (ordering × per-piece rotation); SA = multi-restart Metropolis chains, GA = island-model populations. Both reuse the same `ProcessPoolExecutor` + `WarmStart` scaffolding. | Medium (both shipped) | At grain=90 both beat the bar: rotation-flip-weighted **SA 11578.5mm** (~1.0%); uniform-weight **GA 11426.6mm** (~2.3%, ~0.8% better than SA), < bar on 5/5 seeds. Prior grain=0 figures superseded. |
| **Compaction post-pass (translate-only)** — settle placed pieces down-then-left into BLF's leftover gaps (fixpoint or N-pass). Hard-constraint-safe by construction: translate-only preserves grain / rotation allowance / handedness. Entry point to the separation family. Reimplement (Shapely). See § 6 [2026-06-07]. | Medium | unmeasured — spike first |
| **Overlap-and-separate + Guided Local Search** — drop pieces into a too-short strip (overlaps allowed), then GLS-weighted local search nudges colliding pieces apart to feasibility; shrink strip; repeat. The academic SOTA paradigm (Umetani 2009 → sparrow 2025) for irregular **strip** packing — directly targets the ordering-brittleness wall our SA/GA-over-BLF hit. Restricted rotations ({0°,180°}) + no-flip are first-class, so manufacturing-compatible. Reimplement in Python from the papers, or wrap Rust jagua-rs/sparrow (MIT/MPL-2.0 — packaging cost). See § 6 [2026-06-07]. | High | ~0.3–5% over prior best on academic benchmarks (NOT cross-comparable to our 81.4%) |
| **LP compaction / separation (Li–Milenkovic 1995)** — rigorous version of the compaction post-pass: solve for new non-overlapping positions via linear programming. Originally invented for garment **marker making** (fixed-width cloth, minimize length — our exact problem). Needs an LP solver (scipy). See § 6 [2026-06-07]. | Medium-High | unmeasured |

### 5.C Pruning meta-improvements (compose with PRs #7/#8)

- [ ] **Smart strategy ordering.** Run the historically-best sort strategy
  first so the cutoff tightens sooner for the remaining runs. Needs
  telemetry on which sort wins most often (currently no data).
- [ ] **Cutoff slack.** Accept runs within `epsilon` of best for diversity
  (e.g., to keep "almost as good" results for future export/comparison).
  Not needed today; filed so it's not lost.
- [x] **Bench-vs-GUI variance — RESOLVED (2026-06-04).** Root cause: the bench
  and this doc ran `fabric_grain_deg=0`, but the GUI runs a fixed `90`
  (frontend `App.tsx:18`). `_layout_rotations` shifts every grain-constrained
  piece by +90° between the two, reorienting the whole pack against the fixed
  width. Controlled experiment (bench input held constant, only grain varied,
  clustering off):

  | `fabric_grain_deg` | effort | marker (mm) | utilization |
  | --- | --- | --- | --- |
  | 0.0 (old bench) | 1 & 5 | 12249.1 | 75.83% |
  | 90.0 (GUI)      | 1 & 5 | 11699.4 | 79.39% |

  grain=90 reproduces the GUI/bar exactly. **Not** input ordering (frontend and
  bench expand copies identically, copy-major), **not** pruning (serial and
  parallel agree within each grain), **not** the cache. **Fix:** grain locked at
  90° via `FABRIC_GRAIN_DEG` (`core/layout/grain.py`); the API no longer reads
  `grain_direction_deg`; benches and this doc use the constant.

---

## 6. Findings + design decisions (chronological)

Add new entries here as work progresses. Each entry should record:

- **What:** the algorithm change.
- **Why:** the hypothesis / motivation.
- **Result:** what the bench / tests showed.
- **Decision:** what shipped / what was dropped / what's deferred.

### 2026-05-26 — Union clusters don't beat unclustered BLF on homogeneous garment workloads

- **What:** True-union polygon clusters (2026-05-26). Cluster polygon = Shapely
  union of inner-NFP-BLF-packed copies. Replaces PR #9's rigid bbox
  super-piece with a polygon that exposes perimeter bays.
- **Why:** Bbox clustering (PR #9) regressed garment workloads by +145%.
  Hypothesis: union polygon's perimeter bays would let outer BLF slot
  singleton pieces in, recovering the regression and beating unclustered
  BLF.
- **Result:** Union=27336mm, bbox=29958mm, off=12249mm. Union beats bbox by
  ~8% (mechanism works), but neither beats off (structural — no singletons
  exist on this workload because every base_id has 10 copies).
- **Decision:** Ship opt-in, don't flip default. Filed three follow-ups
  (§5.A) targeting the structural barrier. Bench gate relaxed from
  `union < off` to `union <= bbox`.
- **Mechanism preserved at:** `engine/core/layout/clustering.py::pack_cluster_union`.
  Opt-in instructions in §4.2.

### 2026-05-30 — Partial clustering shipped opt-in; structural barrier confirmed

- **What:** Added `cluster_fraction: float = 1.0` knob to `pre_cluster_pieces` (and forwarded through `auto_layout_polygon`). Per-group split: `k = floor(N * cluster_fraction)` copies cluster; remaining `N - k` join outer BLF as singletons. Min-cluster promotion: `k < 2` → whole group becomes singletons.
- **Why:** The 2026-05-26 § 6 entry's structural finding ("on `sample_2.dxf × 10`, every base id has 10 copies → no singletons left to fill cluster bays") implied that holding back some copies as singletons might let the outer BLF interleave them into the cluster perimeter bays.
- **Result:** Bench sweep on `sample_2.dxf × 10` at fabric=1651mm bi-grain, effort=5:

  | `cluster_fraction` | Marker length (mm) | Utilization | Time (ms) |
  |---|---|---|---|
  | 1.0 (= existing union baseline) | 27336.3 | 33.98% | 10960 |
  | 0.9 | 35842.3 | 25.91% | 29261 |
  | 0.8 | 13688.6 | 67.85% | 28526 |
  | 0.7 | 14705.4 | 63.16% | 27377 |
  | 0.5 | 13512.3 | 68.74% | 27459 |

  Best fraction: `0.5` at `L=13512.3mm`. `off` baseline (unclustered NFP-BLF) = 12249.1mm. **Best partial fraction does NOT beat off.**

  Notable: the curve is non-monotonic — f=0.9 (35842mm) is WORSE than f=1.0 (27336mm). Likely explanation: with only 1 singleton per 9-piece cluster, singletons can't relieve the rigid clustering's row-blocking; instead they add scheduling pressure. By f=0.8 (2 singletons per 8-piece cluster), the outer BLF has enough flexibility to slot them effectively, dropping marker length by ~60%. From f=0.8 onward the curve is roughly flat / mildly improving.

- **Decision:** Structural barrier confirmed at all tested fractions on this workload. The knob remains opt-in. Two interpretations worth noting:
  1. Partial clustering DOES dramatically improve over full clustering (best fraction ~ ½ the f=1.0 marker length), so for workloads where unclustered is somehow infeasible, partial clustering with f=0.5–0.8 is meaningfully better than f=1.0 or bbox.
  2. Future workloads with mixed copy counts (some base ids with copies, some without — exposing real "natural" singletons) may still let some `cluster_fraction` value win. The current finding is specific to homogeneous garment workloads where every base id has the same copy count.

- **Mechanism preserved at:** `engine/core/layout/clustering.py::pre_cluster_pieces` (split logic) + `engine/core/layout/heuristic.py::auto_layout_polygon` (parameter forwarding). Opt-in instructions in § 4.5.

- **Manual GUI verification (2026-05-30):** sample_2 × 10 at fabric=1651mm bi-grain returned 11699mm/79.4% (17s parallel-Max, ~34s Eco serial). This run does **NOT** validate partial clustering — `POST /auto-layout` does not accept `cluster_fraction`/`cluster_polygon`/`disable_clustering` (see § 4.3), so the GUI always hits the unclustered default path. The 11699mm number happens to match the historical "pre-PR-#7 baseline" row in § 1 while diverging from this PR's bench `off`=12249mm on the same parameters. Bench-vs-GUI variance investigation filed as a §5.C bullet.

### 2026-05-31 — Simulated annealing wrapper shipped opt-in

- **What:** Added `sa_iterations`, `sa_max_time_s`, `sa_seed` opt-in params
  on `auto_layout_polygon`. New `engine/core/layout/sa.py` module owns the
  Metropolis SA chain (geometric cooling, mixed swap/reverse/rotation-flip
  neighbors, warm-start seeded T0). Multi-restart parallel on the existing
  ProcessPoolExecutor scaffold (K = `_worker_count(effort)` chains;
  per-chain seed = `sa_seed + worker_index`). Surgical changes to
  `_blf_pack_nfp` (`presorted` flag + per-piece `override_rotations` shape)
  let SA drive ordering + rotation directly.
- **Why:** PERFORMANCE.md § 0 priority is marker length first. Current
  best-of-4 sort strategies explore only 4 hand-picked orderings out of
  N! possibilities and never explore per-piece rotation outside what the
  inner BLF's rotation sweep happens to pick. SA generalizes both axes.
  The 2026-05-30 § 0 framing also flagged the gap between current bench
  baseline (12249mm) and the bar (11699mm) as something to close.
- **Result:** Main sweep (`sa_iterations ∈ [50, 100, 200]` at seed 42):
  marker dropped monotonically from 12176→12164→12077mm. A determinism
  check at sa=50/seed=99 produced 11977mm — better than the sa=200/seed=42
  result of 12077mm. Suggests seed choice matters more than iteration count
  at these scales; SA on this workload is multimodal. **G5 (beat the bar
  11699mm) did NOT pass** — best SA was 12077mm (sa=200/seed=42), short by
  378mm (3.2%); seed-99 sub-run reached 11977mm, still short by 278mm (2.4%).
  G1–G4 (correctness, monotone, determinism, default unchanged) all passed.
- **Decision:** Shipped opt-in per the spec's disposition section regardless
  of G5. Filed follow-ups: (a) hyperparameter tuning sweep (T0_FACTOR,
  cooling rate, neighbor weights); (b) larger iteration counts (sa=500,
  sa=1000) once outer-loop pruning is added to avoid the current ~11min
  wall-clock at sa=200; (c) GA driver on the shared SA scaffolding;
  (d) when K (worker count) exceeds the warm-start pool size (up to 8 on
  bi-grain workloads), chains beyond rank-(len-1) currently modulo-cycle
  and duplicate earlier starts — an even more diverse seeding strategy
  (e.g., random permutation of warm_starts[0] for surplus chains) may
  help when K > 8.
- **Mechanism preserved at:** `engine/core/layout/sa.py` (driver) +
  `engine/core/layout/heuristic.py::_run_sa_phase` (orchestration). Opt-in
  instructions in § 4.6.

- **Manual verification (post-merge sanity, 2026-06-04):** User ran the app
  with example tests and the bench end-to-end. App tests passed.
  Initial concern was post-bench port exhaustion (Windows showed thousands
  of `Bound` sockets after the bench completed); root cause turned out to
  be an unrelated long-running WeChat process leaking ~14,250 sockets over
  several days, NOT our code. With Python no longer running, ZERO sockets
  in any state were attributable to our bench — `ProcessPoolExecutor`
  `with`-block teardown cleaned up workers, pipes, and IPC handles
  correctly on Windows. `multiprocessing.Value("d", ...)` uses
  `CreateFileMapping` (shared memory), so SA's cross-worker cutoff doesn't
  use sockets at all. Repeated pool open/close across the bench's 6 sweep
  entries (~12 pool lifecycle events × ~28 workers) left no accumulating
  damage. Future bench runs could record before/after `Get-NetTCPConnection
  | Group-Object State` snapshots to formalize this guarantee.

### 2026-06-04 — Bench-vs-GUI variance resolved: fabric grain locked at 90°

- **What:** Traced the 550mm bench-vs-GUI gap (§ 5.C) to a benchmark-config
  divergence and locked the fabric grain. Added `FABRIC_GRAIN_DEG = 90.0`
  (`core/layout/grain.py`); `POST /auto-layout` now ignores `grain_direction_deg`
  and always lays out at the constant; all benches reference it.
- **Why:** The bench and § 1 ran `fabric_grain_deg=0`; the GUI hard-codes 90
  (`frontend/src/app/App.tsx:18`). Every piece on the canonical workload has a
  grainline, so the +90° shift reorients the whole pack against the fixed width.
- **Result:** Controlled experiment (same input, only grain varied, clustering
  off): grain=0 → 12249.1mm/75.83%; grain=90 → 11699.4mm/79.39% — the latter
  reproduces the GUI and the § 1 bar exactly, at both effort=1 and effort=5.
  The unclustered path already meets the bar; no algorithm change was needed.
  PR #7/#8 pruning is exonerated. Re-running the clustering bench at grain=90
  also refreshed § 1: bbox 24649.7mm/37.68%, union 23591.6mm/39.37% (both still
  far above the bar — the clustering structural barrier holds; partial-cluster
  best fraction 0.5 = 12630.4mm).
- **Decision:** Grain is no longer a variable feature. The engine keeps the
  `fabric_grain_deg` parameter (and `test_grain.py` still exercises it across
  angles), but no production caller varies it. The prior clustering and SA
  numbers were measured at grain=0 and are superseded; SA is re-baselined at
  grain=90 in the SA-tuning follow-up.
- **Mechanism at:** `engine/core/layout/grain.py` (constant), `engine/api/main.py`
  (locked call). Spec/plan: `docs/superpowers/specs/2026-06-04-bench-grain-fix-design.md`,
  `docs/superpowers/plans/2026-06-04-bench-grain-fix.md`.

### 2026-06-05 — SA hyperparameter tuning at grain=90: rotation-flip-weighted moves beat the bar

- **What:** Made SA's hyperparameters tunable — an `SAConfig` dataclass threaded
  through `auto_layout_polygon(sa_config=...)` to the spawned workers (via
  `initargs`, since workers re-import fresh) — and swept them at the locked
  grain=90 via `engine/tests/bench_sa_sweep.py` (Phases 0–3: single-axis
  screening → combine → multi-seed validation). Baked the winning default.
- **Why:** After the grain lock the warm-start is already 11699.4mm (the bar),
  so SA had to improve on an already-good start. The hyperparameters were fixed
  module constants — untunable without a code edit and unreachable by the
  spawned SA workers via main-process monkeypatch.
- **Result** (sample_2.dxf × 10, fabric=1651, bi-grain, effort=5):

  | config | marker (mm) | util | note |
  | --- | --- | --- | --- |
  | warm-start / current constants | 11699.4 | 79.39% | = bar |
  | `t0_factor=0.1` | 11690.8 | 79.45% | barely |
  | `reverse_window_fraction=0.40` | 11670.4 | 79.59% | |
  | **`rotation_flip=3.0` (rot-heavy)** | **11578.5** | **80.22%** | **best** |

  rot-heavy beats the bar **strictly on seeds 42, 13, 21, 99** (4 of 6; seeds 7
  & 123 found no improvement → 11699.4). Combining the per-axis bests did *not*
  help (the combine candidate returned 11699.4). So the win is the single change
  `MOVE_WEIGHTS rotation_flip 1.0 → 3.0`.
- **Why rotation_flip:** every piece on this workload has a grainline → only two
  rotations (0°/180° vs grain). The 4 sort strategies already cover ordering
  well, but each piece's grain-flip choice is otherwise underexplored — weighting
  that move 3:1 is where the headroom was.
- **Validation** (`bench_sa.py`, tuned default, seed 42, effort=5): sa=50/100/200
  = 11635.4 / 11578.5 / 11517.2mm — all beat the bar; G2–G5 (now PR-blocking)
  pass. **Caveat:** parallel SA's cross-chain cutoff pruning is timing-dependent,
  so an *improving* run's exact marker varies slightly across invocations (e.g.
  sa=50/seed42 was 11578.5mm in the sweep vs 11635.4mm in this validation) — every
  observed run still beats the bar; `disable_pruning=True` yields fully
  deterministic (slower) SA. G3 (same-seed determinism) holds for non-improving
  seeds; the improving path is reproducible only with pruning disabled.
- **Decision:** Baked `rotation_flip=3.0` as the new `MOVE_WEIGHTS` /
  `SAConfig.move_weights` default. `bench_sa.py` G5 (beat the bar) is now
  PR-blocking and passes. SA stays opt-in (`sa_iterations>0`); the GUI path is
  unchanged. `SAConfig` + `bench_sa_sweep.py` are reusable scaffolding for the
  GA follow-up.
- **Mechanism at:** `engine/core/layout/sa.py` (`SAConfig` + `MOVE_WEIGHTS`),
  `engine/core/layout/heuristic.py` (`sa_config` threading),
  `engine/tests/bench_sa_sweep.py` (sweep). Spec/plan:
  `docs/superpowers/specs/2026-06-04-sa-hyperparameter-tuning-design.md`,
  `docs/superpowers/plans/2026-06-04-sa-hyperparameter-tuning.md`.

### 2026-06-05 — GA meta-heuristic shipped opt-in: uniform-weight island GA beats both the bar and SA

- **What:** Added the deferred GA half (§ 5.B). New `engine/core/layout/ga.py` —
  an island-model Genetic Algorithm wrapping `_blf_pack_nfp` as fitness over
  `(piece-ordering × per-piece rotation)`: tournament selection, Order Crossover
  (OX) on the ordering + per-gene uniform crossover on rotations, mutation that
  reuses `sa.py`'s swap/reverse/rotation-flip moves, and elitism.
  `heuristic.py::_run_ga_phase` runs K = `_worker_count(effort)` independent island
  populations on the existing `ProcessPoolExecutor`, each seeded from the
  best-of-4-sort `WarmStart` pool; the best individual across islands (warm-start
  always retained) wins. Opt-in via `auto_layout_polygon(ga_generations>0)` plus
  `ga_max_time_s` / `ga_seed` / `ga_config`. Engine-Python-only; mutually exclusive
  with clustering and with `sa_iterations>0`.
- **Why:** The SA PR deferred a GA driver on the shared scaffolding. GA adds
  population-based *global* recombination, complementing SA's single-trajectory
  local search, over the same two productive axes (ordering + grain choice).
- **Result** (sample_2.dxf × 10, fabric=1651, bi-grain @90, effort=5; full
  `bench_ga_sweep.py`, 17 rows, per-row cap 400s — every row beat the bar):

  | config | marker (mm) | util | note |
  | --- | --- | --- | --- |
  | warm-start (ga=0) | 11699.4 | 79.39% | = bar |
  | rot-heavy (`rotation_flip=3.0`) | 11518.8 | 80.64% | ties SA's floor |
  | **uniform weights (`1:1:1`)** | **11426.6** | **81.29%** | **best — baked default** |
  | combo (all per-axis bests) | 11489.8 | 80.84% | worse than uniform alone |

  Multi-seed validation of uniform weights (seeds 42/7/13/21/99):
  11426.6 / 11456.7 / 11473.7 / 11473.7 / 11485.4 — **5/5 beat the bar AND beat
  SA's floor (11517)**. So GA is the stronger meta-heuristic on this workload
  (~0.8% better than SA, ~2.3% better than the bar). The permanent acceptance
  bench (`bench_ga.py`, gens=12, no time cap) reaches **11412.5mm / 81.39%** at
  seed 42 — slightly better than the time-capped sweep figure since it runs all
  12 generations.
- **Why uniform (not rot-heavy like SA):** GA's *uniform rotation crossover*
  already recombines per-piece grain choices across the population, so a
  rotation-flip-heavy *mutation* is largely redundant; uniform weights spend
  mutation on order diversity (swap/reverse), which complements crossover. SA has
  no crossover, so it needed the rotation-flip-heavy moves. Combining the per-axis
  bests (pop=50, cr=0.7, mr=0.4) with uniform weights did **not** help (11489.8 >
  11426.6), so only the single `MUTATION_MOVE_WEIGHTS` change was baked.
- **Determinism:** GA does **not** pass a shared-cutoff to the evaluator (that
  pruning only fires on worse-than-best offspring — the recombination
  stepping-stones a population method needs). Consequently GA is **deterministic
  per seed** when generations (not `ga_max_time_s`) is the binding budget — a
  stronger guarantee than SA's timing-dependent improving path. `bench_ga.py` G3
  asserts exact reproducibility.
- **Decision:** Shipped opt-in (`ga_generations>0`); baked uniform
  `MUTATION_MOVE_WEIGHTS` / `GAConfig.mutation_move_weights` default; `bench_ga.py`
  G5 (beat the bar) is PR-blocking and passes. Both SA and GA stay opt-in,
  engine-Python-only; the GUI path is unchanged.
- **Mechanism at:** `engine/core/layout/ga.py` (driver + `GAConfig` + operators),
  `engine/core/layout/heuristic.py` (`_run_ga_phase` / `_init_ga_worker` /
  `_run_ga_chain` + `ga_*` wiring), `engine/tests/bench_ga.py` (gates),
  `engine/tests/bench_ga_sweep.py` (sweep). Spec/plan:
  `docs/superpowers/specs/2026-06-05-ga-meta-heuristic-design.md`,
  `docs/superpowers/plans/2026-06-05-ga-meta-heuristic.md`.

### 2026-06-06 — GA optimizer exposed to the GUI (Fast / Better / Best)

- **What:** `POST /auto-layout` gained an optional `quality` field
  (`fast` | `better` | `best`, default `fast` = today's warm-start, bit-identical).
  `_do_layout` maps `better`/`best` to `auto_layout_polygon(ga_generations=12,
  ga_max_time_s=<budget>, ga_seed=42, effort=4)`. Budgets: `better=180s`,
  `best=420s` (`api.main.QUALITY_BUDGETS_S`).
- **Stop:** cancels the run ("Auto layout stopped."), as before. A
  warm-start-on-cancel fallback was prototyped but **dropped** — it can't surface
  in the GUI (the client aborts the HTTP request on Stop, so the engine's
  fallback response is discarded).
- **Cache:** `quality` joined the dedup key (a Best run never returns a cached Fast result).
- **Frontend:** `QualityPanel` radio group + live elapsed timer + indeterminate
  progress bar; the Parallel-effort radio is disabled for Better/Best (they force
  all-but-one core); SA stays engine-only.
- **GUI polish (shipped on the same PR):** window aspect 4:3 → 16:9 (height stays
  ~80.5% of monitor logical height); sidebar width 240 → 360px; left-panel fonts
  scaled ×1.15.
- **Validation** (`bench_optimizer_tiers.py`, sample_2.dxf ×10, fabric=1651, bi-grain @90, effort=4):
  fast=11699.4mm/79.39%; better=11531.9mm/80.54% (~222s wall); best=11456.2mm/81.08%
  (~486s wall) — both beat the bar (11699mm). GATES: PASS.
- **Cross-import** (`bench_optimizer_tiers_multi.py`, ×6 copies, effort=4) — the
  tier ordering best ≤ better ≤ fast holds on every import (GA never regresses):
  sample_3 5530.9 → 5339.6 → 5255.6mm; sample_4 5556.5 → 5182.4 → 5121.6mm (best
  beats fast by 5–8%). sample_1 is a sparse workload (fast=better=best=50.8mm; GA
  correctly finds no improvement). GATES: PASS.
- **Code:** `engine/api/main.py` (tier map),
  `engine/core/layout/cache.py` (quality key),
  `frontend/src/components/sidebar/QualityPanel.tsx`, `frontend/src/app/App.tsx`.
  Spec: `docs/superpowers/specs/2026-06-06-expose-optimizer-gui-design.md`;
  plan: `docs/superpowers/plans/2026-06-06-expose-optimizer-gui.md`.

### 2026-06-07 — Literature + license survey: the field has moved from "construct-then-reorder" to "overlap-and-separate"

- **What:** Surveyed open-source nesting projects and the academic state of the
  art for irregular **strip** packing (fixed width, minimize length — our exact
  problem) to find untried paradigms beyond SA/GA-over-BLF, and to confirm
  Apache-2.0 license compatibility for anything we might adopt. No code adopted
  yet; this is a findings entry feeding the new § 5.B rows.
- **Why:** GA has stalled at 11412.5mm / 81.39%. It optimizes piece *ordering* +
  per-piece grain choice, and the ordering axis is near-maxed. Wanted to know
  whether a fundamentally different paradigm exists, and which code is legally
  reusable in an Apache-2.0 project.
- **License map** (re-verify each project's LICENSE file before copying any
  specific code; algorithm *ideas* from papers are always free to reimplement):
  - **sparrow** (2025 academic SOTA, strip packing) — **MIT** ✅
  - **jagua-rs** (collision-detection engine under sparrow) — **MPL-2.0** ✅ (file-level copyleft; fine to depend on)
  - **SVGnest** (NFP + GA — conceptually what we already do) — **MIT** ✅
  - **Deepnest** (SVGnest-based) — **MIT** ✅ (historically had GPL-referenced files; verify per-file)
  - **libnest2d** (C++, used by PrusaSlicer) — **LGPLv3** ⚠️ avoid vendoring; packaging-sensitive
  - Practical note: sparrow/jagua-rs are Rust, SVGnest/Deepnest are JS. Vendoring
    either fights the Python-engine / PyInstaller / offline-Windows simplicity goal,
    so **reimplement-in-Python from the papers** is the preferred path even where the
    license permits bundling.
- **Algorithmic finding:** The modern SOTA argues construction heuristics (place
  one-by-one, then reorder — i.e. our SA/GA-over-BLF) are fundamentally brittle on
  strip packing because *small ordering changes cause unpredictable quality swings*.
  That is exactly our wall. The alternative paradigm — **overlap-and-separate local
  search** — drops all pieces into a too-short strip (overlaps allowed), runs an
  overlap-minimizing local search (translate colliding pieces) with **Guided Local
  Search** to escape local optima, and shrinks the strip toward feasibility.
  Lineage: Umetani–Yagiura 2009 (GLS overlap-min, strip packing) → sparrow 2025
  (current SOTA). Restricted rotations ({0°,180°} for grain) and no-flip are
  first-class in this framework, so it is manufacturing-compatible.
- **Compaction lineage:** The lighter "compaction post-pass" idea is not a generic
  borrow — Li & Milenkovic 1995 invented LP-based compaction/separation specifically
  for *garment marker making* (packing polygons on fixed-width cloth to minimize
  length). Optimal compaction is NP-complete; they find local minima via LP.
- **Decision / next step:** Compaction (translate-only) is both the cheapest win and
  the on-ramp to the separation paradigm that targets our actual bottleneck. Plan:
  (1) measurement spike — translate-only compactor on the GA output for
  `sample_2.dxf × 10`, measure the marker-length delta; (2) if it pays (≥ 1–2pp),
  escalate toward a fuller overlap-and-separate + GLS engine (the likely route to the
  commercial ~86%). Candidates filed in § 5.B.
- **Key sources:** Bennell & Oliveira 2008, "The geometry of nesting problems: A
  tutorial" (EJOR 184(2):397–415); Umetani et al. 2009, "Solving the irregular strip
  packing problem via guided local search for overlap minimization" (ITOR); Li &
  Milenkovic 1995, "Compaction and separation algorithms for non-convex polygons"
  (EJOR 84(3):539–561); sparrow paper, arXiv:2509.13329 (2025). Full URL list in the
  2026-06-07 research conversation.
