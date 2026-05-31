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

---

## 1. Headline benchmark

Canonical real-workload benchmark used for all gain comparisons:

`examples/input/sample_2.dxf × 10 copies` at `fabric_width_mm=1651`,
`grain_mode="bi"`, `fabric_grain_deg=0.0` (190 pieces total — 19 distinct base
pieces × 10 identical copies each).

| Source                                                | Marker length (mm) | Utilization | Notes                                                        |
| ----------------------------------------------------- | ------------------ | ----------- | ------------------------------------------------------------ |
| Commercial reference                                  | 10599              | 86.1%       | Out-of-scope aspirational target. ~9% better than the bar.   |
| **OpenMarker pre-PR-#7 baseline (the bar to beat)**   | **11699**          | **79.4%**   | **Historical best on this workload — and what the 2026-05-30 manual GUI run reproduced exactly. All future algorithm changes must hit ≤ 11699mm marker / ≥ 79.4% utilization on this workload to count as a win.** |
| Current bench unclustered NFP-BLF (effort=5)          | 12249              | 75.83%      | Known regression vs the bar (+4.7% marker, −3.6pp util). Likely tied to the bench-vs-GUI variance (§ 5.C) — under investigation. **Not** the bar to beat; do not use this as a comparison anchor for new work. |
| Clustering — bbox path (off by default, opt-in)       | 29958              | 31.00%      | +156% regression vs the bar. Mechanism shipped opt-in; see §4. |
| Clustering — union path (off by default, opt-in)      | 27336              | 33.98%      | +134% regression vs the bar. Beats bbox by ~8% but still loses. See §4. |

**Bench script:** `engine/tests/bench_clustering.py`. Run with:

```
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\bench_clustering.py
```

Prints a 3-column off/bbox/union matrix on 4 scenarios (identical rects,
two-groups, singletons, `sample_2.dxf × 10` serial + parallel). 5 programmatic
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
| **GA / SA meta-heuristic wrapper** — wrap the existing NFP-BLF as the fitness function inside a genetic or simulated-annealing search over piece-ordering permutations and per-piece rotation choices. Iterative — runs BLF many times with budget bounded by a time/iteration cap. Composes naturally with the other items (they all become inner-loop primitives the meta-heuristic explores). | High — adds an outer search loop; needs parallelization design | 3–8pp (biggest swing) |

### 5.C Pruning meta-improvements (compose with PRs #7/#8)

- [ ] **Smart strategy ordering.** Run the historically-best sort strategy
  first so the cutoff tightens sooner for the remaining runs. Needs
  telemetry on which sort wins most often (currently no data).
- [ ] **Cutoff slack.** Accept runs within `epsilon` of best for diversity
  (e.g., to keep "almost as good" results for future export/comparison).
  Not needed today; filed so it's not lost.
- [ ] **Bench-vs-GUI variance on the unclustered path (filed 2026-05-30).**
  `bench_clustering.py off` returns 12249.1mm on `sample_2.dxf × 10` at
  `effort=1` and `effort=5` (deterministic). A 2026-05-30 manual GUI run on
  the same workload + effort=Max returned 11699mm. Both paths invoke
  `auto_layout_polygon(disable_clustering=True)` and should produce identical
  results. Likely suspects: (1) bench's `_load_dxf_pieces`
  (`engine/tests/bench_clustering.py:70`) vs the API's
  `parse_dxf` + `normalize_piece` may yield subtly different `Piece.polygon`
  lists (vertex ordering, normalization tolerance, grainline angle);
  (2) PR #8's "result identical to serial mode" claim may not hold across
  all worker counts; (3) the `POST /auto-layout` cache
  (`engine/api/main.py:179`) could have served a stale entry. Repro starting
  point: call `auto_layout_polygon` directly with effort=Max-equivalent and
  diff against a `requests.post('/auto-layout', ...)` result on the same
  pieces — vertex-by-vertex polygon diff first.

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
