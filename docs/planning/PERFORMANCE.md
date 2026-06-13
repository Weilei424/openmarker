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

> **⚠️ Regime change (2026-06-12): `EDGE_GAP` removed — pieces now touch the
> fabric edges (no 10mm selvedge buffer, no marker head/tail).** Every marker /
> utilization figure measured *before* this date — the entire "historical" table
> below and the § 6 entries through 2026-06-09 — assumes the old 10mm buffer and
> is **superseded**. The "pre-PR-#7 baseline = 11699mm" stays the historical
> milestone the narrative refers to; current numbers are lower. See § 6 [2026-06-12].

**Current — no edge gap (2026-06-12, canonical workload):**

| Tier                                   | Marker (mm) | Utilization | Prior (10mm gap)  |
| -------------------------------------- | ----------- | ----------- | ----------------- |
| Commercial reference (external)        | 10599       | 86.1%       | external          |
| Fast — unclustered NFP-BLF (effort=5)  | **11393.2** | **81.52%**  | 11699.4 / 79.39%  |
| GA — uniform-weight, opt-in (gens=12)  | **11232.3** | **82.69%**  | 11412.5 / 81.39%  |
| **Ultra — separation (sparrow) @600s, warm-started** | **10597.8** | **87.64%**  | 10819.5 / 85.85%  |

Removing the buffer dropped every tier's marker (~10mm tail + 20mm more usable
width): Fast −306mm (~2.6%), GA −180mm (~1.6%), Ultra −103mm (~0.9%, then a
further −119mm from warm-start). **As of 2026-06-12 round 2 the Ultra tier is
warm-started from the Fast NFP-BLF layout at budgets ≥360s** (§6 [round 2]); at
the 600s default that takes the canonical marker to **10597.8mm / 87.64%** —
OpenMarker's first marker *below* the external commercial reference (10599mm /
86.1%). (Cold sparrow without warm-start is 10716.7mm / 86.67% at 600s — still
past the commercial utilization, but warm-start is what crosses the marker.)

**Historical — 10mm selvedge buffer (DEPRECATED 2026-06-12):**

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
| **Compaction post-pass (translate-only)** — settle placed pieces down-then-left into BLF's leftover gaps (fixpoint or N-pass). Hard-constraint-safe by construction: translate-only preserves grain / rotation allowance / handedness. Entry point to the separation family. Reimplement (Shapely). **SHELVED — spiked 2026-06-07, measured ≈0 (§ 6).** | Medium | ≈0 (0 to −13mm, <0.1pp) |
| **Overlap-and-separate + Guided Local Search** — drop pieces into a too-short strip (overlaps allowed), then GLS-weighted local search nudges colliding pieces apart to feasibility; shrink strip; repeat. The academic SOTA paradigm (Umetani 2009 → sparrow 2025) for irregular **strip** packing — directly targets the ordering-brittleness wall our SA/GA-over-BLF hit. Restricted rotations ({0°,180°}) + no-flip are first-class, so manufacturing-compatible. Reimplement in Python from the papers, or wrap Rust jagua-rs/sparrow (MIT/MPL-2.0 — packaging cost). **EVALUATED 2026-06-07 → GO (§ 6).** | High | **MEASURED: sample_2×10 = 10916.5mm / 85.08% (−4.35% vs GA, valid, 180s); sample_4 −9.6%** |
| **LP compaction / separation (Li–Milenkovic 1995)** — rigorous version of the compaction post-pass: solve for new non-overlapping positions via linear programming. Originally invented for garment **marker making** (fixed-width cloth, minimize length — our exact problem). Needs an LP solver (scipy). **SHELVED — spiked 2026-06-07, measured ≈0 (§ 6).** | Medium-High | ≈0 (−2 to −12mm, <0.1pp) |

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
- **Decision (measured 2026-06-07):** Spiked BOTH tiers — throwaway
  `engine/tests/spike_compaction.py` (greedy translate-only) and
  `spike_compaction_lp.py` (scipy simultaneous-LP, Li–Milenkovic style). **Both
  recover ≈0 on every workload and baseline, all valid:** greedy warm-start −7.7mm,
  GA −12.7mm, sample_3 −2.8mm, sample_4 0.0mm; LP warm-start −5.8 to −12.3mm, GA
  −1.7mm (all < 0.1pp). Root cause is structural — BLF already packs to a tight local
  optimum, and compaction only refines *within the same arrangement*; the 287mm GA
  gain comes from different piece *orderings*, which compaction cannot reach. The
  cooperative LP (its one edge over greedy) bought a few mm then jammed (trust-region
  step t→0). **Compaction SHELVED (both tiers); scipy NOT added to production.** The
  real headroom is the **overlap-and-separate paradigm** (Umetani 2009 → sparrow
  2025), which generates *new* arrangements — now the active direction (evaluating the
  Rust `sparrow` SOTA on our workload; see the separation-engine spec). The throwaway spikes have been removed; their
  numbers and method are preserved in this entry.
- **Key sources:** Bennell & Oliveira 2008, "The geometry of nesting problems: A
  tutorial" (EJOR 184(2):397–415); Umetani et al. 2009, "Solving the irregular strip
  packing problem via guided local search for overlap minimization" (ITOR); Li &
  Milenkovic 1995, "Compaction and separation algorithms for non-convex polygons"
  (EJOR 84(3):539–561); sparrow paper, arXiv:2509.13329 (2025). Full URL list in the
  2026-06-07 research conversation.

### 2026-06-07 — Separation engine (sparrow) EVALUATED: beats GA → Phase-1 GO

- **What:** Built + ran the Rust SOTA nester `sparrow` (MIT, on MPL-2.0 `jagua-rs`)
  on our workloads to measure the overlap-and-separate paradigm's ceiling on garment
  markers. Lean end-to-end harness `engine/tests/bench_sparrow.py` (on the
  `feat/separation-engine` worktree): pieces → `jagua-rs` JSON (grain-aligned + 90°
  axis-map so cross-grain width → jagua `strip_height` = fabric width;
  `allowed_orientations:[0,180]`) → run `sparrow` → reconstruct + validate (grain /
  overlap / within-width) → marker length vs GA.
- **Grain (hard constraint) honored:** `jagua-rs` items take per-item
  `allowed_orientations` (deg) and have NO flip field; feeding `[0,180]` yields output
  rotations of only 0/−180, zero mirroring. Every measured layout passed validation
  (grain ∈ {0,180}, no overlaps, within fabric width). Schema + axis-map:
  `docs/superpowers/notes/2026-06-07-jagua-schema.md` (on the branch).
- **Result (seed 42, all markers validated):**

  | workload | sparrow | GA (our best) | vs GA |
  | --- | --- | --- | --- |
  | `sample_2.dxf ×10` @180s | **10916.5mm / 85.08%** | 11412.5 / 81.39% | **−4.35%** |
  | `sample_4.dxf ×6` @20s | 4628.8mm / 79.09% | 5121.6 | −9.6% |

  `sample_2×10` clears the ≥3% gate (≤ 11070mm) and approaches the commercial reference
  (10599mm / 86.1%) — at only 180s of a 600s-capable budget. `sparrow` even enforces a
  small inter-item separation our engine does NOT require, so the win is structural, not
  a tolerance artifact.
- **Why it works where compaction failed:** compaction only refines the existing BLF
  arrangement (measured ≈0); `sparrow`'s overlap-and-separate explores *new* arrangements
  — exactly where the gain lives, per the literature's thesis.
- **Decision: GO.** Phase 2 (productionize as a bundled OFFLINE sidecar + GUI "Ultra"
  tier, gated at ≥3% — see the spec) is justified. Phase 2 is a separate build: write its
  plan before starting. Eval code lives on `feat/separation-engine`
  (`engine/tests/bench_sparrow.py`, schema notes, Phase-0/1 plan).
- **Spec:** `docs/superpowers/specs/2026-06-07-separation-engine-design.md`.
- **Caveats / next:** lean spike compares marker = `strip_width + 2·EDGE_GAP` vs our GA
  metric — small convention diffs, but ±20mm ≪ the 496mm win. Phase-2 build needs the
  rigorous per-placement parser into engine `Placement`s + the sidecar/cancellation/cache
  wiring. Longer budgets (up to 600s) and cross-import (sample_3) likely improve further.

### 2026-06-08 — Separation engine PRODUCTIONIZED as the "Ultra" GUI tier

- **What:** Phase 2 shipped the separation engine end-to-end as the GUI **Ultra** quality tier
  (spec `docs/superpowers/specs/2026-06-07-separation-engine-phase2-design.md`, plan
  `…/plans/2026-06-07-separation-engine-phase2.md`). New `core/layout/separation.py`: pieces →
  grain-aligned + 90° axis-mapped `jagua-rs` JSON → bundled `sparrow.exe` subprocess → inverse
  axis-map reconstruction → hard-fail validation (grain / overlap / width / coverage) →
  `_compute_metrics`. `POST /auto-layout` routes `quality="ultra"` at a 600s budget;
  `/cancel-layout` kills the child; `QualityPanel` gains an Ultra radio. `sparrow.exe` (MIT, on
  MPL-2.0 `jagua-rs` 0.7.2; upstream `a4bfbbe`, rustc 1.89.0) is committed at
  `engine/vendor/sparrow/` for offline one-click install (a `.gitignore` `*.exe` negation).
- **Grain (hard constraint) honored:** per-item `allowed_orientations` is DERIVED from grain_mode +
  grainline (single → `[0]` no flip; bi → `[0,180]`; no-grainline → cardinals), not hardcoded. The
  output validator re-asserts grain ∈ {target, target+180}, no area-overlap, and within-width on
  every placement; every measured marker passed (190/190, 48/48). 242 tests green, incl. 3
  real-sparrow integration tests (tiny run, cancellation kill, full pipeline).
- **Result (production `run_separation_layout`, seed 42, all markers validated):**

  | workload | budget | marker | util | vs GA | gate (≤3%) |
  | --- | --- | --- | --- | --- | --- |
  | `sample_2.dxf ×10` | 180s | 10929.2mm | 84.98% | **+4.23%** | PASS |
  | `sample_2.dxf ×10` | **600s (shipped)** | **10819.5mm** | **85.85%** | **+5.20%** | PASS |
  | `sample_2.dxf ×10` | 1200s | 10770.3mm | 86.24% | +5.63% | PASS |
  | `sample_4.dxf ×6` | 600s | 4540.7mm | 80.63% | **+11.34%** | PASS |

  The 600s default clears the ≥3% gate with margin on both workloads and reproduces the Phase-1
  eval (180s → 10929 vs the eval's 10916.5, within convention noise). 600s improves on 180s
  (+5.20% vs +4.23%), so the user-chosen max budget pays off — `sample_2` reaches **85.85%**,
  approaching the commercial 86.1%.
- **Budget sensitivity (2026-06-09):** doubling 600→1200s gains only **+0.39pp** (85.85→86.24%,
  just past the commercial 86.1%) for 2× the wait — steep diminishing returns (sparrow's shrink
  ratio decays linearly with time). 180→600s gained +0.87pp; the marginal rate ~tripled down. So
  600s is a sound default knee; a longer budget (or best-of-N-seeds) is the lever for the last
  fraction of a percent.
- **Stop / offline:** Stop kills sparrow → no marker (consistent with Better/Best; "best-so-far from
  `sols_<name>/` snapshots" filed as a follow-up). Fully offline via the committed binary +
  `_resolve_sparrow_path` ladder (env → vendored → PyInstaller `_MEIPASS` → dev `tools/`).
- **Decision: SHIPPED.** Ultra is now the best quality tier (85.85% on the canonical workload vs
  GA's 81.39%). Bench harness: `engine/tests/bench_separation.py` (production module, not the
  Phase-1 `bench_sparrow.py` spike).

### 2026-06-09 — Separation GUI controls: algorithm names + user budget + best-of-N-seeds

- **What:** Exposed the separation engine's knobs in the GUI (spec
  `docs/superpowers/specs/2026-06-09-separation-controls-design.md`). The QualityPanel now shows
  **algorithm names** (NFP-BLF / Genetic Algorithm — quick / — thorough / Separation (sparrow))
  instead of Fast/Better/Best/Ultra; selecting Separation reveals a **time-budget** box
  (360–1500s, default 600) and a **best-of-N-seeds** selector (1–4, default 1).
- **Best-of-N:** `run_separation_layout(..., n_seeds)` runs N sparrow attempts (seeds 42…42+N−1)
  **in parallel** (ThreadPoolExecutor) and keeps the shortest VALID marker; all-invalid → error;
  any cancelled attempt → `CancellationError` (Stop never returns a partial best-of-N result). The
  kill registry became a set so `/cancel-layout` terminates ALL concurrent attempts. Each sparrow
  uses 3 threads (`jagua-rs`/rayon default), so N=4 ≈ 12 threads — wall stays ≈ budget on a typical
  box. Best-of-N is the recommended quality lever over a longer single budget (per the budget
  sensitivity above).
- **API/cache:** `ultra_budget_s` (360–1500) + `ultra_seeds` (1–4) validated (422 out of range) and
  added to the cache dedup key, so different budget/seeds produce distinct cached tabs. `quality`
  enum unchanged (display-only relabel). Note: raw algorithm names depart from the
  "non-technical operator" UI principle — accepted as an explicit product choice.
- **Tests:** engine unit (best-of-N selection + cancellation precedence + multi-kill registry) +
  API (budget/seeds validation + routing + cache distinction) + frontend (conditional controls,
  clamp) all green.

### 2026-06-12 — EDGE_GAP removed: pieces may touch the fabric edges

- **What:** Removed the 10mm `EDGE_GAP` selvedge buffer entirely — the constant
  plus every arithmetic site — from `heuristic.py`, `clustering.py`, and
  `separation.py`. Pieces may now touch each other (already allowed) AND all four
  fabric edges; marker length is the bottom edge with no head/tail, and usable
  width is the full fabric (1651mm, was 1631mm) on the NFP-BLF, clustering, and
  separation paths. Commit `206f2eb`.
- **Why:** User decision — the 10mm buffer was an inherited default, not a
  validated selvedge requirement. It cost ~1pp of utilization: ~10mm of marker
  tail plus 20mm of usable width the packer could never use.
- **Result (sample_2.dxf ×10, fabric=1651, bi-grain @90, seed 42):**

  | tier | 10mm gap (old) | no gap (new) | Δ marker | Δ util |
  | --- | --- | --- | --- | --- |
  | Fast / warm-start NFP-BLF (effort=5) | 11699.4 / 79.39% | 11393.2 / 81.52% | −306.2mm | +2.13pp |
  | GA (gens=12, pop=30) | 11412.5 / 81.39% | 11232.3 / 82.69% | −180.2mm | +1.30pp |
  | Ultra / separation @600s | 10819.5 / 85.85% | 10716.9 / 86.67% | −102.6mm | +0.82pp |

  Every tier improved. Ultra's utilization (86.67%) now exceeds the external
  commercial reference (86.1%) — though its marker (10716.9mm) is still ~1.1%
  above the commercial 10599mm (the commercial utilization uses a different
  convention, so the two are only loosely comparable). Ultra @600s wall = 601.4s.
- **Validation:** 250 engine tests green, including the 3 real-sparrow
  integration tests (they exercise the new `strip_height = full fabric` +
  shift-to-(0,0) separation round-trip). One bbox-cluster grain test updated: with
  no inset, a cluster whose width-at-rotation equals the full fabric is now
  feasible, so the test correctly picks the 2×5 grid (marker contribution 400mm)
  over the old 3×4 (600mm). The separation validator already tolerated edge
  contact (`±0.5mm` bounds), so it needed no change.
- **Decision: SHIPPED as default** — there is no flag; the buffer is simply gone.
  Deleted the deprecated `bench_sparrow.py` Phase-1 spike (it imported `EDGE_GAP`
  and pointed at a now-absent `tools/sparrow` path; superseded by
  `bench_separation.py`).
- **Note:** the historical "bar = 11699mm" and every pre-2026-06-12 figure /
  formula in this doc (e.g. the § 2 pruning bound `current_max_bottom + EDGE_GAP`)
  assume the old 10mm buffer. § 1 now carries both a current (no-gap) table and
  the deprecated historical table.

### 2026-06-12 — sparrow knob evaluation (explore/compress split · n_workers · inter-item gap): all NO-GO

- **What / why:** Investigated three un-benched sparrow tuning knobs to try to
  shorten the Ultra-tier marker below the shipped 600s baseline. Pure evaluation;
  productionize only a knob that demonstrably wins (≥3 seeds + holds on sample_4×6,
  beating the vendored exe at the same budget). **Result: none won — the vendored
  config (`a4bfbbe`, 3 workers, 0.8/0.2 split) is already at/near the knee.**
- **Method:** throwaway spike `engine/tests/spike_sparrow_knobs.py` (deleted after)
  reusing the PRODUCTION helpers (`_group_to_items` / `_instance_json` /
  `_reconstruct` / `_validate_layout` / `_compute_metrics`) but shelling out with a
  flexible arg list; candidate worker-count binaries built at
  `tools/sparrow/builds/sparrow_w{N}.exe` from the pinned commit (rustc 1.89.0).
  The committed `engine/vendor/sparrow/sparrow.exe` was never touched. All timed
  runs on a quiet 16-physical-core box; builds done first to keep the box quiet
  (sparrow's `-t` is wall-clock — concurrent CPU load corrupts a fixed-budget A/B).
- **Noise floor (must beat to count as a win):** sparrow's result varies run-to-run
  even at a fixed seed (the iteration count that fits the wall budget is
  timing-dependent). Vendored exe, `sample_2×10` @600s, seeds 42/43/44 →
  10664.8 / 10671.8 / 10723.7mm, **mean 10686.7, spread 58.9mm (0.55%)**. The §1
  headline 10716.9 (single seed-42 sample) sits inside this spread.

- **Knob 1 — explore/compress split (no rebuild): NO-GO.** Default is explore
  `0.8` / compress `0.2` (`consts.rs:31-32`); to override, pass BOTH `-e` and `-c`
  and OMIT `-t` (any other combo `bail!`s — `main.rs:38-49`); total = e+c. Swept
  f∈{0.5..0.9} at 600s. Seed-42 triage spanned only 10704.9–10722.1mm (17mm band,
  ≪ noise). 3-seed confirm: **f=0.8 (default) mean 10700.2** vs f=0.6 10708.5 vs
  f=0.5 10729.3. The default is best on the mean; f=0.5 (the seed-42 "leader") is
  worst across seeds — a single-seed-noise trap. Reallocating time between the two
  phases just shuffles within noise at 600s. No `-e`/`-c` plumbing added.

  | split (e/c of 600s) | seed42 | seed43 | seed44 | **mean** |
  | --- | --- | --- | --- | --- |
  | f=0.50 (300/300) | 10716.1 | 10746.8 | 10725.0 | 10729.3 |
  | f=0.60 (360/240) | 10698.6 | 10779.0 | 10648.0 | 10708.5 |
  | **f=0.80 default (480/120)** | 10713.1 | 10711.8 | 10675.5 | **10700.2** |

- **Knob 2 — rayon `n_workers` (rebuild): NO-GO.** Compile-time `n_workers: 3`
  (`config.rs:66`+`:83`); each separator runs N worker clones in parallel per
  iteration and keeps only the best move (`separator.rs:146-178`). On a 16-core box
  the default 3 leaves cores idle, so this looked promising. Built {3,6,8,12,16}.
  180s seed-42 triage was non-monotonic (w3 10732, w6 10829, w8 10901, w12 10771,
  w16 10709 — mid counts WORSE). 600s 3-seed confirm of the best candidate:
  **w16 mean 10686.6 = vendored-w3 baseline 10686.7** (Δ 0.1mm). More workers only
  **tightened variance** (w16 spread 21.7mm vs 58.9mm) — it did not shorten the
  marker. Cause: `move_items_multi` clones the full 190-piece problem to every
  worker each iteration, so more workers = more per-iteration overhead = fewer
  iterations, cancelling the better best-of-N move quality.
  - **Counter-lever (important):** on a multi-core box the already-shipped
    **best-of-N-seeds** *exploits* the 59mm seed variance (keep the shortest of N
    independent trajectories), whereas more workers *suppresses* it. Direct evidence:
    best-of-3 with w3 min **10664.8** < best-of-3 with w16 min **10674.0**. Spending
    cores on more seeds beats spending them on more workers — the shipped design
    already does the better thing. A hardcoded high `n_workers` would also
    *oversubscribe* a small factory box (the offline target); the only safe
    productionization would be runtime `num_cpus::get_physical()` (crate already in
    `bench.rs:59`) — not worth it for a 0mm mean gain.

- **Knob 3 — inter-item separation (rebuild): N/A (already disabled).** The premise
  ("sparrow enforces a small gap we can reduce") is false in the vendored build:
  `min_item_separation: None` (`config.rs:102`); jagua-rs only inflates items when
  it's `Some(f)`, by `f/2` (`import.rs:27,37`). The gap is **already zero — pieces
  may touch** (consistent with the same-day EDGE_GAP removal). Nothing to recover.
  The domain caveat *inverts*: the only move here is *adding* a blade-clearance gap
  (set `min_item_separation` to the kerf), which would **cost** utilization across
  all 190 placements — a cutting-room safety decision for the SME, not an
  optimization. **Flagged to the user; not actioned.**

- **Bonus checks:** (a) **No upstream refresh available** — `a4bfbbe..origin/main`
  = 0 commits; the pin is already at/ahead of upstream `main` (HEAD = "bump
  jagua-rs to v0.7.2"). (b) **Warm-start verified** — `-i` accepts a prior solution
  JSON (`main.rs:78` → `optimizer/mod.rs:39-44` `prob.restore`); this is the
  mechanism for the filed "best-so-far on Stop" follow-up, not a utilization knob.
- **Decision: NO knob productionized.** Ultra's shipped config is confirmed
  well-tuned for this workload at 600s. The real remaining quality levers stay
  **best-of-N-seeds** (shipped; exploits seed variance) and **budget** (diminishing
  — §6 [2026-06-08]). Source map for any future re-investigation: the three knobs
  live at `config.rs:66/83/102` and `consts.rs:31-32` of the pinned sparrow source
  (rebuild recipe in `engine/vendor/sparrow/PROVENANCE.md`).

### 2026-06-12 — Ultra squeeze round 2: 13-variant config sweep + best-of-N quantified + **WARM-START WIN (first sub-commercial marker)**

- **What / why:** Second evaluation cycle on the Ultra tier, per user direction:
  (#1) quantify best-of-N-seeds as a lever, (#4) sweep `poly_simpl_tolerance`,
  (#6) sweep the remaining sparrow hyperparameters, (#7) bounded evaluation of
  alternative algorithms + the warm-start mechanism. Tilt tolerance and mirroring
  explicitly EXCLUDED by user decision. Method mirrors the same-day knob eval:
  throwaway spikes (`spike_sparrow_knobs.py` + `spike_warmstart.py`, on the
  `feat/separation-engine-r2` worktree) reusing the production separation helpers;
  candidate binaries built from the pinned source; vendored exe untouched; all
  timed runs on a quiet 16-core box. **Headline: every config knob is a NO-GO, but
  warm-starting sparrow from our own Fast-tier NFP-BLF layout produced the first
  markers BELOW the commercial reference (10599mm): 10572.3 and 10576.1mm.**

- **Noise floor recalibrated (supersedes the 3-seed 10686.7):** this cycle
  accumulated **21 vendored-config 600s samples** (par≤5, ≤15 rayon threads ≤ 16
  physical cores ⇒ contention negligible): **mean 10722.7mm, range
  10663.1–10783.2 (120mm)**. The earlier 3-seed mean (10686.7) and the §1
  headline single-seed 10716.9 both sit inside this distribution. Any future claim
  on this workload should beat 10722.7 (mean) / clear the 120mm spread.

- **#6 + #4 — 13 config variants: ALL NO-GO.** 180s seed-42 solo triage vs
  default-config control 10732.3 (persist_* triaged at 600s — budget-interacting):

  | variant (edit) | 180s marker | Δ |
  | --- | --- | --- |
  | samp_dbl (per-move samples ×2: 50→100, 25→50) | 10672.4 | **−59.9 (only leader)** |
  | shrink_lo (0.001→0.0005) | 10725.8 | −6.5 |
  | qd5 (quadtree_depth 4→5) | 10734.6 | +2.3 |
  | stddev_lo (0.25→0.1) | 10735.1 | +2.8 |
  | simp_none (no simplification) | 10776.8 | +44.5 |
  | stddev_hi (0.25→0.5) | 10780.2 | +47.9 |
  | samp_half (samples ×0.5) | 10785.4 | +53.1 |
  | gls_hi (decay 0.95→0.98) | 10803.4 | +71.1 |
  | simp_tight (0.001→0.0001) | 10816.5 | +84.2 |
  | gls_lo (decay 0.95→0.90) | 10850.6 | +118.3 |
  | persist_hi @600s (iter_no_imprv 200→400) | 10760.0 | worse |
  | persist_lo @600s (200→100) | 10681.1 | within seed-42 range |

  The sole triage leader, **samp_dbl, inverted at the 600s ×3-seed confirm:
  mean 10717.4 (10645.4/10685.6/10821.1) vs vendored 10686.7** — the same
  single-seed trap as round 1's f=0.5 split. `simp_*` confirmed the
  pre-registered arithmetic bound (max ~9mm recoverable from the 0.1%
  area-inflation tolerance, swamped by slower evals — both directions worse).
  GLS decay and persistence are author-tuned optima. **The shipped binary's
  config is final; no rebuild ships.**

- **#1 — best-of-N quantified: GO as the documented lever; NO cap change.**
  Fresh-draw wall blocks (vendored exe): best-of-4 minima **10663.1** (seeds
  42–45) / **10721.5** (52–55); best-of-5 minima **10685.9** (42–46) /
  **10674.8** (52–56). E[best-of-4] ≈ 10686 vs single-run mean 10722.7 ⇒
  **N=4 saves ~35–50mm (~0.3–0.45%) at identical wall time**. N=5 shows **no
  measurable edge over N=4** (extreme-value flattening) and would push 15 rayon
  threads. Decision: keep the GUI cap at 4 and default at 1 (a higher default
  would oversubscribe small factory boxes); document N=4 as the recommended
  setting on capable hardware. Composes with warm-start (below).

- **#7a — alternative algorithms: NO-GO, evidence-cited.** The sparrow paper
  (arXiv:2509.13329, revised 2026-02) beats all four academic SOTA heuristics
  (ROMA, GCS, FLD, ELS) and the open-source field on all 13 benchmark instances
  — including the garment-like TROUSERS (91.73% vs 90.48%) — and states exact
  methods (MILP / branch-and-bound, e.g. arXiv:2503.21009) "can generally only
  handle a small set of items… impractical for many academic instances, let
  alone complex real-world instances" (we run 190 pieces). RL/quantum/pixel
  approaches are not competitive on strip packing and would fight the offline
  packaging constraint. No upstream sparrow/jagua-rs refresh exists (pin =
  upstream HEAD; no jagua-rs release past 0.7.2). **There is no better engine
  to adopt; gains must come from how we drive sparrow.**

- **#7b — WARM-START from the Fast tier: GO (the cycle's win).** sparrow's `-i`
  accepts a full solution JSON (`ExtSPOutput` = instance fields + `solution`);
  `import_solution` (jagua-rs `spp/io/import.rs:65-80`) consumes only
  `strip_width` + `placed_items` (`container_id`/`density`/`run_time_sec`
  parsed-but-ignored ⇒ production can construct the JSON directly, no template
  solve). Spike converter = exact inverse of `_reconstruct` (+90° axis map,
  shift into `x∈[0,M]`, per-copy rotation offset `r=(rot−base)%360`, translation
  from vertex-0 correspondence with a max-deviation assertion). Fed sparrow our
  **Fast-tier NFP-BLF layout** (11393.2mm) as the start. Results (600s, all
  markers validator-passed — grain/overlap/width/coverage):

  | arm (sample_2×10) | seeds | markers (mm) | mean | min |
  | --- | --- | --- | --- | --- |
  | LBF-init pool (n=21) | various | 10663.1 … 10783.2 | 10722.7 | 10663.1 |
  | **warm-start solo** | 42/43/44 | **10572.3 / 10621.6 / 10648.9** | **10614.3** | **10572.3** |
  | **warm-start best-of-4** | 52–55 | 10576.1 / 10702.5 / 10714.9 / 10734.8 | 10682.1 | **10576.1** |

  Matched-seed comparison (same seed, warm vs LBF-init): 6/7 seeds better, mean
  **−74mm (−0.7%)**; the worst warm-start solo run (10648.9) beats the best of
  21 LBF-init samples (10663.1). **Two independent seed pools produced markers
  below the commercial 10599mm reference: 10572.3 (87.85% util) and 10576.1
  (87.82%)** — OpenMarker's first sub-commercial markers. Budget fairness: the
  Fast layout costs +28–30s on sample_2 (~+2–3mm equivalent on the 600→1200s
  curve) — not the explanation. **Why it works:** the paper's own stated
  weakness — sparrow "lacks a mechanism to repeat compact local patterns" on
  homogeneous instances — and our canonical workload is exactly that (19 base
  pieces ×10). NFP-BLF supplies the garment-row structure sparrow cannot
  discover; sparrow's overlap-and-separate then compresses it far past what
  BLF/GA can reach.
  - **Second workload (sample_4×6): neutral, no regression.** Fresh LBF-init
    baseline 4450.0 mean (4413.6/4465.9/4470.4) vs warm-start 4452.3 mean
    (4439.2/4453.7/4463.9) — a tie within noise. Cause: the Fast layout is
    structurally POOR there (5475.8mm, 23% above sparrow's level, vs 6% above on
    sample_2), so there is no structure worth injecting — and sparrow's explore
    phase discards it at no cost. Also note Fast @effort=1 took **107s** on
    sample_4 (complex outlines) vs ~29s on sample_2 — production budget
    accounting must handle this (reuse a cached Fast result, or carve the cost
    out of the sparrow budget).
  - **Decision: SHIPPED** (PR #17) — `run_separation_layout(warm_start=True)`
    (engine-Python-only; no binary change; offline-safe; built ONCE and shared
    across best-of-N; graceful cold-start fallback; Stop during the prelude
    cancels). `_build_warm_start` constructs the `ExtSPOutput` JSON DIRECTLY (dummy
    `container_id`/`density`; `import_solution` ignores them — confirmed: sparrow
    accepts it), `_placements_to_jagua` = the exact inverse of `_reconstruct` with
    a pure-translation guard. **Production budget curve (seed 42, sample_2×10,
    warm vs cold, both validated):**

    | budget | warm_start=True | warm_start=False | Δ |
    | --- | --- | --- | --- |
    | 180s | 10716.4 | 10713.8 | +2.6 (tie) |
    | 360s | 10682.9 | 10722.2 | **−39.3 (−0.37%)** |
    | 600s | **10597.8** (87.64%, sub-commercial) | 10716.7 | **−118.9 (−1.11%)** |

    Key finding: **cold sparrow plateaus (~10715mm at every budget)** — extra time
    barely helps it; warm-start is what makes the time-budget lever productive (the
    win GROWS with budget as the injected garment-row structure compresses).
    **Budget-gated at `WARM_START_MIN_BUDGET_S = 360.0`** (API): warm-start is ON for
    budgets ≥360s (incl. the 600s default), OFF below — so the new 180s "fast" floor
    isn't taxed by the Fast-layout prelude (~26s sample_2, ~107s sample_4) where it
    only ties. Also lowered the GUI/API budget floor 360→180s. 259 engine + frontend
    tests green.
  - **Follow-ups filed:** (a) GA-layout warm start at equal *total* time;
    (b) periodic-lattice warm starts (the paper's "vastly superior solutions are
    attainable" on homogeneous instances — a structured generator could beat the
    Fast layout as the seed); (c) the previously-filed "best-so-far on Stop" and
    a "Continue refining" button both ride the same converter.
