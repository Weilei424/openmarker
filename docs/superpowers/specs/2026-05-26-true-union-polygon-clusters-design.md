# True-Union Polygon Clusters — Design Spec

**Date:** 2026-05-26
**Author:** Claude (Opus 4.7) + Mason Wang
**Target:** Engine — `engine/core/layout/clustering.py`, `engine/core/layout/heuristic.py`
**Predecessor:** PR #9 (`feat(engine): identical-piece clustering mechanism (opt-in, bbox limitation documented)`)
**BACKLOG item:** `Layout improvements — algorithm` → `Identical-piece pre-clustering (true-union polygon clusters)`

---

## Outcome (recorded after implementation — read me first)

**Status:** SHIPPED OPT-IN, default not flipped.

The mechanism specified below was implemented correctly and validated by 28 clustering + 11 heuristic-integration tests. Union beats bbox by ~8% on the headline workload (sample_2.dxf × 10 at fabric=1651mm bi-grain): union=27336mm vs bbox=29958mm. But the design's central acceptance bar (§1, Q1) — strictly beat unclustered BLF (12249mm) — was NOT met.

Root cause is structural, not a bug in the union mechanism:
- The garment workload has 19 base pieces × 10 copies each. Every base id has copies.
- Every group gets clustered. No singletons remain to slot into cluster perimeter bays.
- The union polygon's bay-exposure benefit (the whole point of replacing bbox) is unrealized.
- Rigid clusters (whether bbox or union exterior) still block row interleaving.

The PR shipped:
1. `cluster_polygon: 'union' | 'bbox' = 'union'` parameter on `auto_layout_polygon`.
2. `disable_clustering: bool = True` (PR #9 default preserved — opt-in).
3. Bench gate relaxed to `union ≤ bbox` (the realistic floor given the structural issue).
4. Follow-up items filed in BACKLOG: heterogeneous clustering, partial clustering, cluster-aware outer sort.

The design below is preserved as the planning record. Sections that turned out to be premature optimism: §1 acceptance bar (not met), §6 (default flip planning — reverted), §8 acceptance gate criteria (relaxed before merge). Everything else (architecture, algorithm, data flow) is what shipped.

---

## 1. Goal

Reclaim the regression PR #9's bbox clustering left on real garment workloads by replacing the cluster's rigid bbox super-piece with a Shapely-union polygon. The union exposes perimeter bays so BLF can interleave other piece types into shared rows, instead of having to place rigid rectangles that block the fabric.

### Headline workload acceptance bar (Q1)

`examples/input/sample_2.dxf × 10 copies` at `fabric_width_mm=1651`, `grain_mode="bi"`, `fabric_grain_deg=0.0`:

| Path | Marker length (mm) | Utilization | Source |
|---|---|---|---|
| Unclustered NFP-BLF | 12249 | ~76% | Today's default |
| Bbox clustering (PR #9) | 29958 | ~31% | +145% regression |
| Commercial reference | 10599 | ~86% | Out of scope for this PR |
| **Union clustering (this PR target)** | **< 12249** | **> 76%** | **Must strictly beat unclustered to flip default ON** |

## 2. Scope

### In scope
- New `cluster_polygon: Literal["union", "bbox"] = "union"` parameter on `auto_layout_polygon` and `pre_cluster_pieces`. Both code paths coexist; the flag dispatches.
- New `pack_cluster_union()` in `clustering.py` that runs an *inner* NFP-BLF on a group's copies, unions them, returns a `Cluster` whose `super_piece.polygon` is the union exterior.
- Existing `pack_cluster()` renamed to `pack_cluster_bbox()`. Same logic; serves the `cluster_polygon="bbox"` path and the per-group fallback when union fails.
- Default flip: `disable_clustering=False` once the bench acceptance gate passes.
- Per-copy local rotation tracking on `Cluster` (bi-mode lets copies face 0° or 180° within a cluster).
- Per-group fallback ladder: `union` → `bbox` → singletons.
- New unit tests (~12) + extended bench (3-column on/bbox/union matrix per row).

### Out of scope (filed in BACKLOG follow-ups)
- Holes-aware NFP (pass polygon-with-holes through pyclipper as separate paths). Interior bays unreachable by BLF anyway.
- Mirrored bi-mode (horizontal reflection of pieces). Composes with the existing "Grain-compatible mirroring" BACKLOG item.
- Heterogeneous clustering (mix different base_ids in one cluster). Combinatorial search; separate spec.
- Non-cardinal rotations inside clusters. Math works via Shapely affinity; no current workload needs it.
- Cluster-aware sort strategies. Speculative; separate PR.
- Auto-decide bbox vs union per cluster (e.g. if union area ≈ bbox area). Micro-optimization for the rectangle-only case.

## 3. Architecture changes

### `engine/core/layout/clustering.py`
- Add `VERTEX_CAP: int = 200` and `SIMPLIFY_TOL_MM: float = 0.5` module constants.
- Add `pack_cluster_union(pieces, fabric_width_mm, grain_mode, fabric_grain_deg) -> Cluster | None`. Internals in §4.
- Rename `pack_cluster` → `pack_cluster_bbox` (same logic, no behavior change). Serves the `cluster_polygon="bbox"` path and the per-group fallback.
- Replace `pre_cluster_pieces` signature to accept `cluster_polygon: Literal["union", "bbox"] = "union"`. Dispatches per group; falls back `union → bbox → singletons` if a step returns `None`.
- Extend `Cluster` dataclass with `copy_local_rotations: list[float]`. Bbox path uses `[0.0] * N` (backward compatible).

### `engine/core/layout/heuristic.py`
- Add `cluster_polygon: Literal["union", "bbox"] = "union"` to `auto_layout_polygon` signature (after `disable_clustering`).
- Flip `disable_clustering=False` default.
- Forward `cluster_polygon` into `pre_cluster_pieces`.
- No changes to `_blf_pack_nfp`, `_polygon_at_origin`, `_compute_nfp_polygons`, NFP cache, parallel pruning, or `_validate_pieces_fit`. They already handle arbitrary polygons.

### `expand_cluster_placement` change
Apply `local_rot + super_rotation` per copy instead of just `super_rotation`. Bbox-path Clusters still expand correctly because their `copy_local_rotations` is uniform zeros.

### No changes to
Frontend code. Engine API. NFP cache implementation. Cancellation. Layout cache. Tests guarding non-clustering behavior.

## 4. `pack_cluster_union` internals

### Inner-BLF rotation set (cluster-local)

The cluster's local rotation set is decided by the outer `grain_mode` AND each piece's grainline:

| Outer grain_mode | Piece has grainline | Inner rotation set (local) |
|---|---|---|
| `single` | yes | `[0.0]` |
| `bi` | yes | `[0.0, 180.0]` |
| any | no | `[0.0, 90.0, 180.0, 270.0]` |

These are **cluster-local** rotations. The outer BLF later applies its own rotation `R_outer` to the whole cluster. A copy's screen rotation = `R_outer + R_local`.

### Inner-BLF shim

The inner NFP-BLF call needs to bypass `_layout_rotations` (which derives rotations from outer grain_mode + per-piece grainline). Cleanest approach: add `override_rotations: list[float] | None = None` and `skip_validation: bool = False` parameters to `_blf_pack_nfp`. When `override_rotations` is set, the inner loop iterates that list verbatim; when `skip_validation=True`, `_validate_pieces_fit` is not called (the candidate-width loop in `pack_cluster_union` already pre-filters widths via its own min_w check, mirroring PR #9's bug-2 logic). Outer BLF calls use neither parameter — default behavior preserved.

### Candidate mini-fabric widths

Enumerate `cols ∈ {1, 2, …, N}` and `mini_w = cols × piece_bbox_w`. Filter to widths where the resulting cluster fits at the outer's allowed rotations (mirrors PR #9's bug-2 grain-rotation feasibility check).

Per candidate:
1. Run inner NFP-BLF: `_blf_pack_nfp(pieces, mini_w, grain_mode="single", fabric_grain_deg=0.0, override_rotations=cluster_local_set, skip_validation=True)`. (`grain_mode` and `fabric_grain_deg` are ignored when `override_rotations` is set.)
2. Union the placed polygons: `union = unary_union([_placed_polygon(p, pl.x, pl.y, pl.rotation_deg) for pl, p in zip(placements, pieces_in_placement_order)])`.
3. If `union.geom_type == "MultiPolygon"` → skip this candidate.
4. If `union.geom_type == "Polygon"` → strip holes: `union = ShapelyPolygon(union.exterior)`.
5. If `len(union.exterior.coords) > VERTEX_CAP` → `union = union.simplify(SIMPLIFY_TOL_MM, preserve_topology=True)`. Re-check vertex count; if still over cap, skip this candidate.
6. Compute `cluster_w, cluster_h` from `union.bounds` (= `(maxx - minx, maxy - miny)`). Sort key matches PR #9: `(sort_h, sort_w, cluster_h, cluster_w)` where `sort_h = min(height_at(r) for r in outer_rotations)`.

### Winner selection

Pick the candidate with smallest sort key. If no candidate survives, `pack_cluster_union` returns `None`; `pre_cluster_pieces` falls back to `pack_cluster_bbox` for that group.

### Return value

A `Cluster` with:
- `super_piece.polygon = list(union.exterior.coords[:-1])` (drop closing duplicate, matching `Piece.polygon` convention)
- `super_piece.bbox` = bounds of the union
- `super_piece.area = sum(p.area for p in pieces)` (preserves utilization math)
- `super_piece.grainline_direction_deg = pieces[0].grainline_direction_deg` (cluster inherits)
- `super_piece.id = f"cluster_{base_id}_x{N}"` (unique per call; safe for NFP cache)
- `copy_offsets = [(pl.x, pl.y) for pl in inner_placements]` (top-left of each copy's rotated bbox in cluster-local coords)
- `copy_local_rotations = [pl.rotation_deg for pl in inner_placements]`
- `original_pieces = pieces` (in inner-BLF placement order, so offsets line up)

## 5. `expand_cluster_placement` change

`copy_offsets[i] = (placement.x, placement.y)` from the inner BLF — i.e. the **top-left of the rotated copy's bbox** in cluster-local coords, NOT a raw translation offset. To reconstruct the copy in cluster-local space we mirror `_placed_polygon`: rotate around origin, then translate so the rotated bbox top-left lands at the recorded offset.

```python
def expand_cluster_placement(cluster, super_x, super_y, super_rotation):
    # Apply super_rotation to the cluster polygon, then compute the translation
    # that lands its rotated bbox top-left at (super_x, super_y).
    cluster_poly = ShapelyPolygon(cluster.super_piece.polygon)
    rotated_cluster = shapely.affinity.rotate(cluster_poly, super_rotation, origin=(0.0, 0.0))
    cluster_min_x, cluster_min_y = rotated_cluster.bounds[:2]
    xoff = super_x - cluster_min_x
    yoff = super_y - cluster_min_y

    for orig_piece, (dx, dy), local_rot in zip(
        cluster.original_pieces,
        cluster.copy_offsets,
        cluster.copy_local_rotations,
    ):
        # Place the copy in cluster-local frame (mirror `_placed_polygon`).
        copy_poly = ShapelyPolygon(orig_piece.polygon)
        rotated_local = shapely.affinity.rotate(copy_poly, local_rot, origin=(0.0, 0.0))
        rot_minx, rot_miny = rotated_local.bounds[:2]
        copy_in_cluster = shapely.affinity.translate(
            rotated_local, xoff=dx - rot_minx, yoff=dy - rot_miny,
        )
        # Apply super_rotation + cluster-level translation.
        rotated_with_super = shapely.affinity.rotate(
            copy_in_cluster, super_rotation, origin=(0.0, 0.0),
        )
        placed_copy = shapely.affinity.translate(rotated_with_super, xoff=xoff, yoff=yoff)
        cx, cy = placed_copy.bounds[0], placed_copy.bounds[1]
        effective_rot = (super_rotation + local_rot) % 360.0
        yield (orig_piece.id, round(cx, 4), round(cy, 4), effective_rot)
```

Bbox path: `copy_local_rotations = [0.0] * N`, so `effective_rot = super_rotation % 360.0` — equivalent to PR #9 (PR #9 didn't normalize, but all its callers feed cardinal angles already, so the modulo is a no-op for existing tests).

## 6. Outer BLF integration

Zero new code in `_blf_pack_nfp`. It already calls `_polygon_at_origin(super_piece, rot)` which works on any polygon. NFP cost scales with vertex count; cache amortizes across rotations of the same super-piece (keyed by `_base_id(super_piece.id)`, which is `cluster_{base}_x{N}` — unique per cluster, so each cluster's NFP is computed once per rotation pair).

## 7. Tests

### Clustering unit tests (additions to `test_clustering.py`; existing 17 untouched)

1. `test_pack_cluster_union_two_copies_share_edge` — union of 2×(100×50) rects collapses to one rectangle exterior.
2. `test_pack_cluster_union_picks_minimum_height_width` — 6×(100×50), fabric=500: 3-col winner (h=100).
3. `test_pack_cluster_union_bi_mode_allows_180_local_rotation` — asymmetric (L-shape) piece, bi mode: at least one `copy_local_rotations[i] == 180.0`.
4. `test_pack_cluster_union_strips_holes` — synthetic input whose unioned copies form a polygon with an interior hole (e.g. 4 right-angle "C" shapes facing inward). Build the same union manually with `unary_union`; assert it has ≥1 interior ring (proves the input genuinely produces holes). Then assert `pack_cluster_union(...).super_piece.polygon` has no interior info (it's a flat coord list, but verify by reconstructing `ShapelyPolygon(super_piece.polygon).area == ShapelyPolygon(union_with_holes.exterior).area`).
5. `test_pack_cluster_union_multipolygon_returns_none` — copies that can't connect → `pack_cluster_union(...) is None`.
6. `test_pack_cluster_union_vertex_cap_triggers_simplify` — high-vertex piece × 10; assert exterior vertex count ≤ `VERTEX_CAP` after simplify.
7. `test_pre_cluster_pieces_falls_back_to_bbox_on_union_none` — group that fails union; resulting Cluster has 4-vertex rectangle polygon (bbox fallback engaged).
8. `test_expand_cluster_applies_local_rotation` — `copy_local_rotations = [0.0, 180.0]`, outer rotation 90°: expanded rotations = `[90.0, 270.0]`.

### Heuristic integration tests (additions to `test_heuristic.py`)

9. `test_auto_layout_cluster_polygon_union_default` — `cluster_polygon` defaults to `"union"`; smoke test, correct piece count.
10. `test_auto_layout_cluster_polygon_bbox_matches_pr9_behavior` — `cluster_polygon="bbox", disable_clustering=False` matches PR #9 exactly (regression guard for the bbox path).
11. `test_auto_layout_clustering_default_on` — `disable_clustering` defaults to `False`.
12. `test_auto_layout_union_no_worse_than_bbox_on_homogeneous` — 10 identical rects: `union.marker <= bbox.marker + 1e-6`.

**Suite expectation:** 116 → ~128 tests; all pass.

## 8. Benchmark — `engine/tests/bench_clustering.py`

Extend the existing bench from 2-column (on/off) to 3-column (off/bbox/union) per row. Re-use the existing scenarios + a parallel-mode sample_2.dxf row.

### Acceptance gate (all must pass before flipping default `disable_clustering=False`)

| Row | Required |
|---|---|
| 10 identical rects (100×50), fabric=500 | `union.marker ≤ off.marker + 1e-6` (no regression) |
| 6×(100×60) + 4×(120×40), fabric=500 | `union.marker ≤ off.marker + 1e-6` |
| 8 singletons (mixed), fabric=500 | `union.marker == off.marker` (no-op for singletons) |
| sample_2.dxf × 10, bi, fabric=1651, effort=1 | **`union.marker < off.marker = 12249mm`** (Q1 success bar) |
| sample_2.dxf × 10, bi, fabric=1651, effort=5 | `union.marker == union.marker[effort=1]` (parallel ≡ serial) |

Wall-clock budget: union total runtime ≤ 1.5× `cluster=off` baseline at effort=5. If > 2×, tighten `VERTEX_CAP` / `SIMPLIFY_TOL_MM` before re-running.

**Failure handling:** if the headline row doesn't beat 12249mm → STOP and file BLOCKED. PR fails its purpose; we'd file follow-up rather than ship a "no worse" default flip.

## 9. Risks

1. **NFP cost explodes on garment-piece unions.** 10 copies × 30-vertex piece → ~100-150 exterior vertices. NFP O(V_a×V_b) ≈ 15-22k ops per pair. Mitigation: `VERTEX_CAP=200` + `simplify(0.5mm)`; bbox fallback if exceeded. Bench gates runtime at ≤ 1.5×.
2. **Inner BLF picks a cluster shape the outer BLF can't place.** Grain-locked clusters have one outer rotation; cluster width must fit at that rotation. Mitigation: candidate-width loop pre-filters via the same `_validate_pieces_fit`-style check PR #9 added.
3. **Union polygon non-determinism.** Shapely's `unary_union` vertex ordering can vary; NFP cache key uses `_base_id`, not coords — drift is contained to per-call uniqueness.
4. **Parallel pruning correctness.** Workers rebuild caches; shared `multiprocessing.Value` cutoff is per-strategy. No new code there. Bench's effort=5 row exercises this.

## 10. Rollback plan

- **Hot fix (no redeploy):** caller passes `cluster_polygon="bbox", disable_clustering=True` to restore pre-PR-#10 behavior bit-for-bit.
- **Code revert:** single PR touching `clustering.py`, `heuristic.py`, two test files, the bench, CLAUDE.md, BACKLOG.md. Clean single-commit revert is safe.

## 11. Domain compliance notes (from `openmarker-nesting` skill)

| Concern | Status |
|---|---|
| Grainline respected | **Hard manufacturing constraint** — inner BLF's rotation set is derived from outer `grain_mode` + per-piece grainline. Each copy's effective screen rotation = `R_outer + R_local`, which lands on the same grain-allowed angle as if it were placed individually. Confirmed in §4 derivation. |
| One-way / nap fabric | Not addressed (no nap flag in `Piece` today). Bi-mode 180° rotation is allowed for the current spec; would need to be gated if nap support is added later. **Assumption needing SME validation** if a future PR adds nap support — but unchanged by this PR. |
| Mirrored / paired pieces | Not addressed (no mirror flag in `Piece` today). Inner BLF does not introduce reflections; only rotations. Mirroring is filed separately in BACKLOG. |
| Cutting-room tolerance | EDGE_GAP between fabric edge and pieces preserved (10mm selvedge). Intra-cluster pieces touch directly, matching current engine convention (`_has_area_overlap` eps = 0.5 mm²). No change. |
| Inter-piece bays | The whole point of this PR — exposes them to BLF via the union polygon. **Soft optimization objective** that the bench gate validates. |
| Defect zones / stripe matching | Not in scope for the engine yet. No impact. |

Classification: §1-8 are **implementation choices** the spec pins down. §9 risks and §10 rollback ensure no **hard constraint** can be violated even if the bench shows unexpected results.
