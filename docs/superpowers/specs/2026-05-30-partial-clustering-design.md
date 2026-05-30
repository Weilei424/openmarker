# Partial Clustering (`cluster_fraction`) — Design Spec

**Date:** 2026-05-30
**Author:** Claude (Opus 4.7) + Mason Wang
**Target:** Engine — `engine/core/layout/clustering.py`, `engine/core/layout/heuristic.py`, `engine/tests/bench_clustering.py`
**Predecessor:** PR #10 (`docs: PR #10 true-union polygon clusters`) — `docs/superpowers/specs/2026-05-26-true-union-polygon-clusters-design.md`
**BACKLOG item:** `Phase 6 follow-ups — algorithm performance` → `Algorithm follow-ups` (PERFORMANCE.md § 5.A item 1, "Partial clustering")

---

## 1. Goal

Test PR #10's central hypothesis — that singletons in the outer BLF can slot into cluster perimeter bays and recover the clustering regression — by adding a `cluster_fraction` knob that holds back some copies of each group as singletons instead of pulling all N into a rigid cluster.

PR #10's structural finding (PERFORMANCE.md § 6, 2026-05-26 entry): on `sample_2.dxf × 10`, every base id has 10 copies, so every group gets clustered, and there are no singletons left to slot into the union polygon's bays. Partial clustering directly addresses this by leaving a configurable fraction of each group as singletons in the outer BLF input.

### Disposition (decided before implementation)

This work ships as a permanent opt-in knob. We keep the parameter regardless of bench result:

- **If a fraction beats `off=12249mm`** on `sample_2.dxf × 10`, a follow-up PR flips `disable_clustering=False` with that fraction as the new default. PERFORMANCE.md § 4.4's "when to re-enable by default" gate becomes achievable.
- **If no fraction wins,** the knob still ships; the bench sweep becomes a recorded data point showing the structural barrier holds at every tested fraction. Filed in PERFORMANCE.md § 6 as evidence.

This is explicitly *not* the "experiment-then-decide" framing where we'd revert on a loss. The knob is shippable in either outcome.

## 2. Scope

### In scope

- New `cluster_fraction: float = 1.0` parameter on:
  - `pre_cluster_pieces` in `engine/core/layout/clustering.py`
  - `auto_layout_polygon` in `engine/core/layout/heuristic.py` (forwarded to `pre_cluster_pieces`)
- Per-group split logic inside `pre_cluster_pieces`: `k = floor(N * cluster_fraction)`; first k copies cluster, remaining `N - k` become singletons in the outer BLF input.
- Min-cluster promotion: when `k < 2`, the whole group passes through as singletons (no cluster constructed).
- Fraction range validation: `cluster_fraction` must be in `(0.0, 1.0]`; out-of-range raises `ValueError`.
- 13 new unit tests in `engine/tests/unit/test_clustering.py` + 3 integration tests in `engine/tests/unit/test_heuristic.py` (16 new tests total).
- Bench extension in `engine/tests/bench_clustering.py`: fraction sweep `[1.0, 0.9, 0.8, 0.7, 0.5]` on `sample_2.dxf × 10` at `effort=5`, plus a regression gate that `cluster_fraction=1.0` matches the pre-change union baseline.
- Docs: PERFORMANCE.md gets a new § 4.5, updated § 5.A item 1, and a new § 6 dated entry (Result + Decision lines filled in after bench runs). BACKLOG.md updates the matching follow-up bullet.

### Out of scope

- HTTP API exposure. Engine-Python knob only, matching the existing `disable_clustering` / `cluster_polygon` policy (PERFORMANCE.md § 4.3).
- Frontend UI exposure. Same reason.
- Default flip of `disable_clustering`. That is a separate follow-up PR contingent on bench results.
- Heterogeneous clustering (mixing different base_ids in one cluster) — separate PERFORMANCE.md § 5.A item 2.
- Cluster-aware outer sort — separate PERFORMANCE.md § 5.A item 3.
- Alternative knob shapes (`cluster_leftover: int`, `cluster_size: int`). Considered and rejected during brainstorming in favor of the per-group float fraction.
- Alternative split policies (different rounding rule, different "which copies are held back" rule). Locked to `floor(N * fraction)` and "first k copies" by input order.
- Sweep on effort=1 or on the three synthetic bench rows. Synthetic rows are too small for partial clustering to behave differently from full clustering; effort=1 doesn't add signal over effort=5.

## 3. Architecture changes

### `engine/core/layout/clustering.py`

- Add `cluster_fraction: float = 1.0` parameter to `pre_cluster_pieces`, after `cluster_polygon`.
- Add range validation: raise `ValueError` if `not (0.0 < cluster_fraction <= 1.0)`. Mirrors the existing `cluster_polygon` validation pattern at the top of `pre_cluster_pieces`.
- Modify the per-group loop body to compute `k = floor(n * cluster_fraction)` and branch on `k < 2`; see § 4 for the algorithm.
- No changes to `pack_cluster_union`, `pack_cluster_bbox`, `Cluster`, `group_pieces_by_base_id`, `expand_cluster_placement`, or any module constants. The pack functions receive a smaller `cluster_pieces` slice and have no awareness of the split.

### `engine/core/layout/heuristic.py`

- Add `cluster_fraction: float = 1.0` parameter to `auto_layout_polygon`, after `cluster_polygon`.
- Forward `cluster_fraction` into the existing `pre_cluster_pieces` call (the only call site, inside the `if disable_clustering: ... else: ...` block).
- Docstring: add a paragraph describing `cluster_fraction` and the `k < 2` promotion rule. Parallel structure to the existing `cluster_polygon` paragraph.
- No changes to `_blf_pack_nfp`, parallel pruning, `_validate_pieces_fit`, NFP cache, or any other heuristic-internal logic. The outer BLF receives a different `blf_input` list (super_pieces + leftover singletons instead of only super_pieces) but doesn't distinguish them.

### `engine/tests/bench_clustering.py`

- Add a `cluster_fraction` kwarg to `_run`, handled in a new `"union_f"` mode branch.
- Add a fraction-sweep block on the `sample_2.dxf × 10` effort=5 row, iterating over `[1.0, 0.9, 0.8, 0.7, 0.5]`.
- Add one new acceptance gate: `union[fraction=1.0]` marker length matches the pre-change union baseline (regression check). The existing union-vs-bbox and parallel-vs-serial gates stay as-is, using `cluster_fraction=1.0` implicitly.
- Update the bottom-of-bench note to report the best partial-cluster fraction and whether it beat `off=12249mm`.

## 4. Algorithm (the splitting math)

Inside `pre_cluster_pieces`, the per-group loop becomes:

```python
import math

for group in groups.values():
    n = len(group)
    if n < 2:
        clustered_input.extend(group)
        continue

    k = math.floor(n * cluster_fraction)
    if k < 2:
        # Cluster would be degenerate (< 2 copies). Promote whole group to singletons.
        clustered_input.extend(group)
        continue

    cluster_pieces = group[:k]
    leftover_pieces = group[k:]   # may be empty when k == n (cluster_fraction == 1.0)

    cluster: Cluster | None = None
    if cluster_polygon == "union":
        cluster = pack_cluster_union(cluster_pieces, fabric_width_mm, grain_mode, fabric_grain_deg)
    if cluster is None:
        cluster = pack_cluster_bbox(cluster_pieces, fabric_width_mm, grain_mode, fabric_grain_deg)
    if cluster is None:
        # Both pack paths failed on the k-slice. Whole group (k + leftover) falls back to singletons.
        clustered_input.extend(group)
        continue

    clustered_input.append(cluster.super_piece)
    clusters.append(cluster)
    clustered_input.extend(leftover_pieces)
```

### Properties

- **Bit-identical to current behavior at `cluster_fraction=1.0`.** `k = n`, leftover is `[]`, the new `extend(leftover_pieces)` is a no-op, and `cluster_pieces` is `group` exactly. Every existing test passes unchanged.
- **First-k determinism.** The cluster takes `group[:k]`; the leftover is `group[k:]`. Slicing by input order is deterministic, which matters for bench run-to-run stability. Copies of the same base are geometrically identical, so the choice has no correctness impact.
- **Fallback applies to the cluster slice only.** If `pack_cluster_union` returns `None` for the first k, `pack_cluster_bbox` is tried on the same first k (existing fallback ladder). Only if BOTH fail does the **whole group** (k + leftover) go to singletons. We do *not* try smaller k values — that would explode the search space and would silently override the user's chosen fraction.
- **Min-cluster promotion.** `k < 2` ⇒ whole group passes through as singletons. Catches:
  - Small groups with aggressive fractions (`N=3, fraction=0.5` → `k=1`).
  - Any group with `fraction=0.1` on `N<20`.
  - The user-visible behavior is "fraction too small to form a real cluster for this group → no cluster" — predictable and matches the existing `if len(pieces) < 2: return None` pattern in the pack functions.

### What this looks like on `sample_2.dxf × 10` (190 pieces, 19 base ids × 10 copies)

| `cluster_fraction` | Per-group split | Total clusters | Total singletons fed to outer BLF |
|---|---|---|---|
| 1.0 (default) | 10 cluster / 0 leftover | 19 | 0 |
| 0.9 | 9 cluster / 1 leftover | 19 | 19 |
| 0.8 | 8 cluster / 2 leftover | 19 | 38 |
| 0.7 | 7 cluster / 3 leftover | 19 | 57 |
| 0.5 | 5 cluster / 5 leftover | 19 | 95 |

At `fraction=0.5` the outer BLF sees 19 cluster super-pieces plus 95 individual pieces — closer to (but not identical to) the unclustered case, with the cluster super-pieces still providing some grouping benefit.

## 5. Test plan

### Unit tests in `engine/tests/unit/test_clustering.py` (~12)

Range validation:

- `test_pre_cluster_pieces_rejects_fraction_zero` — `cluster_fraction=0.0` raises `ValueError`.
- `test_pre_cluster_pieces_rejects_fraction_negative` — `cluster_fraction=-0.1` raises `ValueError`.
- `test_pre_cluster_pieces_rejects_fraction_above_one` — `cluster_fraction=1.5` raises `ValueError`.
- `test_pre_cluster_pieces_accepts_fraction_one` — `cluster_fraction=1.0` runs without raising.

Split math (10-copy group of identical rects):

- `test_partial_cluster_fraction_one_matches_full_cluster` — `cluster_fraction=1.0` produces a `Cluster` with `len(original_pieces) == 10` and no extra singletons in `clustered_input`.
- `test_partial_cluster_fraction_half_splits_5_5` — `cluster_fraction=0.5` produces a `Cluster` with `len(original_pieces) == 5` and 5 leftover singletons appended to `clustered_input`.
- `test_partial_cluster_fraction_holds_back_last_copies` — leftover singleton ids match `group[k:]` in input order.

Min-cluster promotion:

- `test_partial_cluster_promotes_when_k_below_two` — `cluster_fraction=0.1` on `N=10` ⇒ `floor=1 < 2` ⇒ no cluster, all 10 pieces in `clustered_input` as singletons.
- `test_partial_cluster_promotes_small_group` — `cluster_fraction=0.5` on `N=3` ⇒ `floor=1 < 2` ⇒ no cluster, all 3 pieces in `clustered_input` as singletons.
- `test_partial_cluster_promotes_pair` — `cluster_fraction=0.5` on `N=2` ⇒ `floor=1 < 2` ⇒ no cluster, both pieces in `clustered_input` as singletons.

Heterogeneous groups:

- `test_partial_cluster_per_group_fractions` — `cluster_fraction=0.7` on a mixed input with groups of sizes 10 and 3 ⇒ group A gets cluster=7+leftover=3, group B gets cluster=2+leftover=1 (each computed independently).

Fallback ladder interaction:

- `test_partial_cluster_falls_back_on_pack_failure` — monkeypatched `pack_cluster_union` and `pack_cluster_bbox` both return `None` on the k-slice ⇒ whole group (k + leftover) ends up in `clustered_input` as singletons.

bbox-path coverage (knob applies to both):

- `test_partial_cluster_bbox_path_splits_correctly` — `cluster_polygon="bbox", cluster_fraction=0.7` on `N=10` ⇒ bbox cluster of 7 + 3 singletons appended.

### Integration tests in `engine/tests/unit/test_heuristic.py` (3)

- `test_auto_layout_polygon_default_cluster_fraction_is_one` — call with `disable_clustering=False` and no `cluster_fraction` arg; verify the param default is `1.0` via signature inspection.
- `test_auto_layout_polygon_cluster_fraction_passes_through` — plumbing test: same input, `disable_clustering=False`, run once at `cluster_fraction=1.0` and once at `cluster_fraction=0.5`; assert the placement counts and structure differ (lower fraction ⇒ more individual placements, fewer super-piece placements).
- `test_auto_layout_polygon_cluster_fraction_ignored_when_clustering_disabled` — `cluster_fraction=0.5` with `disable_clustering=True` produces results bit-identical to the `cluster_fraction=1.0` + `disable_clustering=True` run (knob has no effect).

### What is NOT tested

- "Winning fraction" — the bench prints the sweep result; there is no asserted-value test for it. The structural barrier means a winning fraction may not exist, and even if it does, the value is workload-dependent and not a unit-testable property.
- Frontend interaction — knob not exposed there.
- HTTP API contract — knob not exposed there.
- Re-clustering or recursive fallback at smaller k — explicitly out of scope per § 4.

## 6. Bench changes

### `engine/tests/bench_clustering.py` additions

```python
def _run(pieces, fabric_width_mm, grain_mode, effort, mode, cluster_fraction=1.0):
    """Existing modes unchanged. New mode: 'union_f' — union path with a
    configurable cluster_fraction."""
    kwargs = dict(
        pieces=pieces, fabric_width_mm=fabric_width_mm,
        grain_mode=grain_mode, fabric_grain_deg=0.0, effort=effort,
    )
    if mode == "off":
        kwargs["disable_clustering"] = True
    elif mode == "bbox":
        kwargs["disable_clustering"] = False
        kwargs["cluster_polygon"] = "bbox"
    elif mode == "union":
        kwargs["disable_clustering"] = False
        kwargs["cluster_polygon"] = "union"
    elif mode == "union_f":
        kwargs["disable_clustering"] = False
        kwargs["cluster_polygon"] = "union"
        kwargs["cluster_fraction"] = cluster_fraction
    else:
        raise ValueError(f"unknown mode: {mode}")
    ...
```

### New sweep block

Inserted after the existing parallel-effort bench row for `sample_2.dxf × 10`. Iterates `[1.0, 0.9, 0.8, 0.7, 0.5]` at `effort=5`. Reports each fraction's marker length, utilization, and wall-clock time. Closing line identifies the best fraction and whether it beats the `off` baseline.

Expected wall-clock: ~10s per fraction × 5 fractions ≈ 50s on top of the current ~30s bench. Total bench time stays well under 2 minutes.

### Acceptance gates

| Gate | Status | Detail |
|---|---|---|
| 10 identical rects: union no-worse-than off | UNCHANGED | Existing. |
| two-groups: union no-worse-than off | UNCHANGED | Existing. |
| 8 singletons: union == off | UNCHANGED | Existing. |
| sample_2.dxf serial: union <= bbox | UNCHANGED | Existing; runs with implicit `cluster_fraction=1.0`. |
| sample_2.dxf parallel: union == union[serial] (determinism) | UNCHANGED | Existing. |
| **partial-cluster `fraction=1.0` matches union baseline** | **NEW** | Regression check, same-run comparison: `union_f` mode at `cluster_fraction=1.0` produces a marker length within `1e-6` of the same-run `union` mode (which runs implicitly at `cluster_fraction=1.0`). No hardcoded baseline — the two modes are run side-by-side and the lengths must match exactly. |

No new "must win" gate. The bench sweep is informational — its result decides whether a follow-up PR flips the default, but does not block this PR from merging.

## 7. Documentation updates

### `docs/planning/PERFORMANCE.md`

- **New § 4.5 "Partial clustering (`cluster_fraction < 1.0`)"** under § 4 (disabled-by-default approaches). Code map (`pre_cluster_pieces` is the split site), opt-in invocation (`auto_layout_polygon(..., disable_clustering=False, cluster_fraction=0.7)`), test pointers, bench pointer.
- **§ 5.A item 1 "Partial clustering" bullet** rewritten to point to § 4.5 and the new § 6 entry. The "Low-medium effort" tag becomes "DONE — see § 4.5".
- **New § 6 entry "YYYY-MM-DD — Partial clustering shipped opt-in"** with What / Why / Result / Decision sections. `YYYY-MM-DD` is the date the bench is actually run during implementation (not the design date). The Result and Decision lines are filled in *after* the bench runs — the bench produces the data that populates them. The plan must include a step for this.

### `docs/planning/BACKLOG.md`

- **Phase 6 follow-ups — algorithm performance**, the open item:
  ```
  - [ ] Algorithm follow-ups (clustering structural-barrier + general wins + pruning meta-improvements). Ranked list in PERFORMANCE.md § 5.
  ```
  becomes:
  ```
  - [~] Algorithm follow-ups — partial clustering (`cluster_fraction` knob) shipped opt-in; remaining items in PERFORMANCE.md § 5.
  ```

### Function docstrings

- `pre_cluster_pieces` docstring gains a paragraph for `cluster_fraction` describing the split + promotion rule, parallel to its `cluster_polygon` paragraph.
- `auto_layout_polygon` docstring gains a paragraph for `cluster_fraction` parallel to its `cluster_polygon` paragraph.

### Not touched

- `CLAUDE.md` — already delegates clustering detail to PERFORMANCE.md; no edit needed.
- Frontend docs, README, install docs — knob not exposed there.

## 8. Acceptance criteria (for merging this PR)

The PR is ready to merge when ALL of the following are true:

1. All 16 new tests pass (13 unit + 3 integration).
2. All 130 existing engine tests still pass (the `cluster_fraction=1.0` default guarantees no behavior change for anything that doesn't set the new param).
3. The bench script exits 0 with all 6 acceptance gates green (5 existing + 1 new regression check).
4. The bench sweep output is captured into PERFORMANCE.md § 6's new entry — both the Result table (per-fraction marker length / utilization / time) and the Decision line (either "best fraction X.X beats off; follow-up PR will flip default" or "no fraction beats off; structural barrier confirmed at all tested fractions").
5. The 4 pre-existing failures in `test_dxf_parser.py` (missing `examples/input/2_pieces_x_2_with_grainline.dxf` fixture) remain pre-existing and unrelated to this work.

The PR does NOT require: a winning fraction. The "shippable knob" disposition (§ 1) is explicit that the parameter ships in either outcome.

## 9. Risks and open questions

### Risks

- **Risk: leftover singletons confuse the outer BLF's sort strategies.** The BLF runs 4 sort strategies (area / max-dim / height / width DESC). Adding leftover singletons changes the sort-ordering input but doesn't change the strategy code. Pruning still applies. Risk is low because the BLF treats super_pieces and individual pieces as opaque polygons — there's no code path that special-cases super_pieces. Mitigation: the `cluster_fraction=1.0` regression check catches any accidental behavior change.
- **Risk: the bench's expected wall-clock estimate (~80s total) is wrong.** Per-fraction time depends on how partial clustering affects BLF runtime — fewer cluster pieces means more outer BLF placements per strategy, which could be slower or faster depending on the workload. Mitigation: bench reports per-run wall-clock; if any single sweep entry exceeds ~60s, we know the estimate was off and can revise the sweep set.
- **Risk: `pack_cluster_union` fails on a smaller k slice that succeeded at k=N.** Possible if the inner BLF's NFP search has size-dependent edge cases. Mitigation: existing fallback ladder (union → bbox → singletons) already handles `pack_cluster_*` returning `None`; the whole-group-to-singletons branch covers the case where both fail.

### Open questions (none blocking; locked during brainstorming)

- *Sweep range:* `[1.0, 0.9, 0.8, 0.7, 0.5]`. Wider/denser sweeps can be added in a follow-up if the initial results suggest a winner near a sweep edge.
- *Effort coverage:* sweep at effort=5 only. effort=1 doesn't add signal over effort=5 for this hypothesis.
- *Synthetic bench rows:* no fraction sweep on the 3 synthetic rows. Too small to behave differently from full clustering.

---

## Appendix — Rejected alternatives (from brainstorming)

| Alternative | Why rejected |
|---|---|
| `cluster_leftover: int` knob | Degenerate behavior on small groups (N ≤ leftover ⇒ whole group becomes singletons, surprising the user). Fraction-based knob handles small groups naturally via the `k < 2` promotion rule. |
| `cluster_size: int` knob | Loses the proportional intuition. "Cluster size 7" means very different things on a group of 10 vs a group of 3. |
| `max(2, floor(N * fraction))` clamping | Silently ignores the user's chosen fraction on small groups (asked for 0.1 → got 0.2 on N=10). Violates the principle that the knob should mean what it says. |
| `max(1, floor(N * fraction))` allowing 1-copy clusters | Wastes overhead on a no-op cluster; muddies the "clusters help" signal in the bench. |
| Split inside `pack_cluster_union` / `pack_cluster_bbox` (Approach B) | Breaking signature change to two functions for the same `floor(N * fraction)` math that isn't pack-strategy-specific. Smells like premature encapsulation. |
| New `split_group_for_clustering` helper (Approach C) | Extra abstraction for ~5 lines of math called from one site. Approach A (split lives directly in `pre_cluster_pieces`) is the right amount of structure. |
