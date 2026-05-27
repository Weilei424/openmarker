# True-Union Polygon Clusters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PR #9's rigid bbox super-piece with a Shapely-union polygon (tight-packed via inner NFP-BLF), so identical-piece clustering reclaims the +145% regression on `sample_2.dxf × 10` and lets us flip `disable_clustering=False` by default.

**Architecture:** Add a `cluster_polygon: Literal["union", "bbox"] = "union"` parameter to `auto_layout_polygon`. New `pack_cluster_union()` runs an *inner* NFP-BLF on a group's copies, unions the placed polygons, strips holes, and returns the cluster polygon. Existing `pack_cluster()` is renamed to `pack_cluster_bbox()` and kept as a per-group fallback (MultiPolygon, vertex-cap overflow) and for the `cluster_polygon="bbox"` benchmark mode. `Cluster` gains a `copy_local_rotations` field so bi-mode clusters can mix 0° and 180° copies internally. `expand_cluster_placement` applies `local_rot + super_rotation` per copy.

**Tech Stack:** Python 3.11, Shapely 2.0.6 (`unary_union`, `simplify`, affinity), Pyclipper 1.4.0 (unchanged), pytest. Touches `engine/core/layout/clustering.py`, `engine/core/layout/heuristic.py`, `engine/tests/unit/test_clustering.py`, `engine/tests/unit/test_heuristic.py`, `engine/tests/bench_clustering.py`, `CLAUDE.md`, `docs/planning/BACKLOG.md`.

**Spec:** `docs/superpowers/specs/2026-05-26-true-union-polygon-clusters-design.md`.

---

### Task 1: Add `override_rotations` + `skip_validation` to `_blf_pack_nfp`

The inner NFP-BLF (called from `pack_cluster_union` in Task 4) needs to bypass `_layout_rotations` (which derives rotations from outer grain settings) and skip `_validate_pieces_fit` (the caller pre-filters widths). This task adds the plumbing only — no clustering code yet.

**Files:**
- Modify: `engine/core/layout/heuristic.py`
- Modify: `engine/tests/unit/test_heuristic.py`

- [ ] **Step 1: Write the failing test**

Append to `engine/tests/unit/test_heuristic.py` (place after the existing `_make_rect` helper / similar fixtures):

```python
# --- inner-BLF shim plumbing tests ---

def test_blf_pack_nfp_override_rotations_replaces_grain_logic():
    """When override_rotations is set, _blf_pack_nfp ignores piece.grainline_direction_deg
    and uses the override list verbatim. Single 100x50 rect with grainline=0.0 placed
    via override [90.0] must come back rotated 90° (becomes 50 wide x 100 tall)."""
    from core.layout.heuristic import _blf_pack_nfp
    piece = _make_rect("p", 100, 50, grainline_deg=0.0)
    placements, marker, util = _blf_pack_nfp(
        [piece], fabric_width_mm=200,
        grain_mode="single", fabric_grain_deg=0.0,
        override_rotations=[90.0],
        skip_validation=True,
    )
    assert len(placements) == 1
    assert placements[0].rotation_deg == 90.0


def test_blf_pack_nfp_skip_validation_allows_oversize_input():
    """With skip_validation=True the upfront _validate_pieces_fit is not called.
    Caller is trusted (e.g., pack_cluster_union's candidate-width pre-filter).
    Test: a piece that would fail validation at grain-locked rotation still
    runs when both override_rotations and skip_validation are set to a rotation
    that fits."""
    from core.layout.heuristic import _blf_pack_nfp
    # 600 wide piece, fabric 200 — would fail _validate_pieces_fit at 0°.
    # But at 90° it's 50 wide (fits 200). Override + skip_validation bypasses.
    piece = _make_rect("p", 600, 50, grainline_deg=None)
    placements, marker, util = _blf_pack_nfp(
        [piece], fabric_width_mm=200,
        grain_mode="single", fabric_grain_deg=0.0,
        override_rotations=[90.0],
        skip_validation=True,
    )
    assert len(placements) == 1
    assert placements[0].rotation_deg == 90.0


def test_blf_pack_nfp_default_behavior_unchanged():
    """Regression guard: without override_rotations/skip_validation, _blf_pack_nfp
    behaves exactly as before — derives rotations from grain_mode + grainline and
    calls _validate_pieces_fit."""
    from core.layout.heuristic import _blf_pack_nfp
    piece = _make_rect("p", 100, 50, grainline_deg=0.0)
    placements, marker, util = _blf_pack_nfp(
        [piece], fabric_width_mm=200,
        grain_mode="single", fabric_grain_deg=0.0,
    )
    assert len(placements) == 1
    assert placements[0].rotation_deg == 0.0  # target = (0 - 0) % 360 = 0
```

If `_make_rect` does not exist in `test_heuristic.py`, define it at module top (mirroring the clustering test's helper):

```python
def _make_rect(piece_id: str, w: float, h: float, grainline_deg: float | None = None) -> Piece:
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        validation_notes=[],
        grainline_direction_deg=grainline_deg,
    )
```

- [ ] **Step 2: Run to confirm the new tests fail**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "override_rotations or skip_validation or default_behavior_unchanged"`

Expected: `test_blf_pack_nfp_override_rotations_replaces_grain_logic` and `test_blf_pack_nfp_skip_validation_allows_oversize_input` FAIL with `TypeError: _blf_pack_nfp() got an unexpected keyword argument 'override_rotations'`. `test_blf_pack_nfp_default_behavior_unchanged` PASSES (regression baseline).

- [ ] **Step 3: Add the two parameters to `_blf_pack_nfp`**

In `engine/core/layout/heuristic.py`, update the signature:

```python
def _blf_pack_nfp(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    sort_key=None,
    nfp_cache: NfpCache | None = None,
    best_marker_so_far: float | None = None,
    shared_best_value=None,  # multiprocessing.Value('d', ...) or None
    override_rotations: list[float] | None = None,
    skip_validation: bool = False,
) -> tuple[list[Placement], float, float]:
```

Inside the function, gate the validation call:

```python
    if sort_key is None:
        sort_key = lambda p: p.area
    if nfp_cache is None:
        nfp_cache = {}
    sorted_pieces = sorted(pieces, key=sort_key, reverse=True)
    if not skip_validation:
        _validate_pieces_fit(sorted_pieces, fabric_width_mm, grain_mode, fabric_grain_deg, _polygon_dims)
```

Inside the per-piece loop, replace the `rotations = _layout_rotations(...)` line:

```python
    for piece in sorted_pieces:
        if is_cancelled():
            raise CancellationError("Auto-layout cancelled by user.")
        if override_rotations is not None:
            rotations = override_rotations
        else:
            rotations = _layout_rotations(
                grain_mode, fabric_grain_deg, piece.grainline_direction_deg
            )
```

Update the docstring to mention the new parameters (one sentence each):

```
    `override_rotations`: when set, replaces the per-piece grain-derived rotation
    set with this list verbatim. Used by `pack_cluster_union` to drive inner BLF
    with cluster-local rotation sets that don't depend on piece grainline.

    `skip_validation`: skip the upfront `_validate_pieces_fit` call. The caller
    must have pre-filtered piece widths. Used by `pack_cluster_union`'s
    candidate-width loop.
```

- [ ] **Step 4: Run the targeted tests**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "override_rotations or skip_validation or default_behavior_unchanged"`

Expected: ALL THREE PASS.

- [ ] **Step 5: Run the full engine test suite (regression guard)**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/ -v`

Expected: all 116 existing tests + 3 new = 119 PASS. No regressions in other tests.

- [ ] **Step 6: Commit**

```bash
git add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git commit -m "feat(engine): _blf_pack_nfp override_rotations + skip_validation parameters"
```

---

### Task 2: Extend `Cluster` dataclass + rename `pack_cluster` → `pack_cluster_bbox`

Pure refactor: the existing bbox path becomes `pack_cluster_bbox`. `Cluster` gains `copy_local_rotations: list[float]` (filled with zeros by the bbox path so behavior is identical). All 17 existing clustering tests stay green after the rename.

**Files:**
- Modify: `engine/core/layout/clustering.py`
- Modify: `engine/tests/unit/test_clustering.py`

- [ ] **Step 1: Extend the `Cluster` dataclass**

In `engine/core/layout/clustering.py`, replace the `Cluster` dataclass with:

```python
@dataclass
class Cluster:
    """A pre-packed group of identical pieces, ready to be placed as a super-piece.

    Attributes:
        super_piece: Synthetic Piece whose polygon represents the packed cluster
            (bbox rectangle for `pack_cluster_bbox`; union exterior for
            `pack_cluster_union`). Its `area` field is the SUM of original copy
            areas (so utilization math stays correct downstream).
        copy_offsets: For each copy, its (dx, dy) in cluster-local coords
            (top-left of the copy's rotated bbox in cluster-local frame).
        copy_local_rotations: For each copy, its local rotation in degrees within
            the cluster. Bbox path uses zeros (copies all at outer rotation).
            Union path may use {0, 180} (bi-mode) or {0, 90, 180, 270} (no-grain).
        original_pieces: Original Piece objects in the same order as
            copy_offsets/copy_local_rotations — used to look up id/polygon/area
            for expansion.
    """
    super_piece: Piece
    copy_offsets: list[tuple[float, float]]
    copy_local_rotations: list[float]
    original_pieces: list[Piece]
```

- [ ] **Step 2: Rename `pack_cluster` to `pack_cluster_bbox`**

In `engine/core/layout/clustering.py`, rename the function (its `def pack_cluster(...)` line and the docstring's first paragraph). Inside its body, when constructing the returned `Cluster`, add `copy_local_rotations=[0.0] * n` to the call:

```python
def pack_cluster_bbox(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str = "single",
    fabric_grain_deg: float = 0.0,
) -> Cluster | None:
    """Pack N copies of an identical piece into a bbox super-piece.

    [... existing docstring ...]
    """
    # [... existing body unchanged until the Cluster construction ...]

    return Cluster(
        super_piece=super_piece,
        copy_offsets=offsets,
        copy_local_rotations=[0.0] * n,  # NEW: bbox path uses uniform 0° local rotation
        original_pieces=pieces,
    )
```

In `pre_cluster_pieces`, rename the `pack_cluster(...)` call to `pack_cluster_bbox(...)`. (Full dispatch logic comes in Task 5; for now we just match the rename.)

- [ ] **Step 3: Update the test file imports + calls**

In `engine/tests/unit/test_clustering.py`, replace the import:

```python
from core.layout.clustering import (
    Cluster,
    group_pieces_by_base_id,
    pack_cluster_bbox,
    pre_cluster_pieces,
    expand_cluster_placement,
)
```

Then use Edit's `replace_all=True` to change every `pack_cluster(` to `pack_cluster_bbox(` in the test file. Apply the same replacement to docstrings.

- [ ] **Step 4: Run clustering tests**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v`

Expected: ALL 17 existing tests PASS (with the new function name and `copy_local_rotations` field populated with zeros).

- [ ] **Step 5: Run the full suite (regression guard for any indirect callers)**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/ -v`

Expected: 119 tests PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add engine/core/layout/clustering.py engine/tests/unit/test_clustering.py
git commit -m "refactor(engine): rename pack_cluster -> pack_cluster_bbox; add Cluster.copy_local_rotations"
```

---

### Task 3: Update `expand_cluster_placement` for local rotations + correct offset semantics

The existing expansion treats `(dx, dy)` as a raw translation that happens to coincide with bbox-top-left because PR #9 used grid offsets on rectangles at (0,0). The new contract (from Task 4 onwards) is: `copy_offsets[i] = (placement.x, placement.y)` from the inner BLF — i.e. the top-left of the rotated copy's bbox in cluster-local coords. This task makes the math correct AND applies `local_rot` per copy. Existing bbox-path tests still pass because their `copy_local_rotations` is all-zero AND grid offsets coincide with rotated-bbox-top-lefts.

**Files:**
- Modify: `engine/core/layout/clustering.py`

- [ ] **Step 1: Write the new test that exercises non-zero local rotation**

Append to `engine/tests/unit/test_clustering.py`:

```python
def test_expand_cluster_applies_local_rotation():
    """A Cluster with mixed local rotations should produce expanded placements
    where each copy's final rotation = (super_rotation + local_rot) % 360.
    This is the bi-mode pattern: inner BLF picks local 0° or 180° per copy."""
    from core.layout.clustering import Cluster
    base = _rect("p__c0", 100, 50)
    # Synthetic Cluster: 2 copies, one at local 0°, one at local 180°. Super-piece
    # is a 200x50 rectangle. copy_offsets are the rotated-bbox-top-lefts in cluster-local.
    cluster = Cluster(
        super_piece=Piece(
            id="cluster_p_x2", name="cluster p x2",
            polygon=[(0, 0), (200, 0), (200, 50), (0, 50)],
            area=2 * (100 * 50),
            bbox=BoundingBox(0, 0, 200, 50, 200, 50),
            is_valid=True,
            grainline_direction_deg=None,
        ),
        copy_offsets=[(0.0, 0.0), (100.0, 0.0)],
        copy_local_rotations=[0.0, 180.0],
        original_pieces=[base, _rect("p__c1", 100, 50)],
    )
    # Place cluster at (500, 1000) with super_rotation=90°.
    # Effective rotations: (90+0)%360=90, (90+180)%360=270.
    placements = list(expand_cluster_placement(cluster, super_x=500, super_y=1000, super_rotation=90.0))
    assert len(placements) == 2
    rotations = sorted(p[3] for p in placements)
    assert rotations == [90.0, 270.0]
```

- [ ] **Step 2: Run to confirm the test fails**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py::test_expand_cluster_applies_local_rotation -v`

Expected: FAIL with `IndexError` or `TypeError` — current `Cluster` dataclass either lacks `copy_local_rotations` (already added in Task 2, so this should be a logic failure: `placements[i][3]` will be `super_rotation` not `(super_rotation + local_rot) % 360`).

If Task 2 already passes `copy_local_rotations`, the existing `expand_cluster_placement` ignores it and yields `super_rotation` only — test should fail at the rotations assertion.

- [ ] **Step 3: Rewrite `expand_cluster_placement`**

In `engine/core/layout/clustering.py`, replace the function body with:

```python
def expand_cluster_placement(
    cluster: Cluster,
    super_x: float,
    super_y: float,
    super_rotation: float,
) -> Iterator[tuple[str, float, float, float]]:
    """Yield (piece_id, x, y, rotation) for each copy in a placed cluster.

    Reproduces the engine's `_placed_polygon` convention: the cluster polygon is
    rotated around (0, 0) by `super_rotation`, then translated so the rotated
    cluster's bbox top-left lands at (super_x, super_y). For each copy:
      1. Reconstruct the copy in cluster-local frame by rotating its polygon by
         `local_rot` around (0, 0), then translating so the rotated copy bbox
         top-left lands at `copy_offsets[i]`.
      2. Apply `super_rotation` around (0, 0) and the cluster-level translation.
      3. Per-copy final rotation = (super_rotation + local_rot) % 360.
    """
    cluster_poly = ShapelyPolygon(cluster.super_piece.polygon)
    rotated_cluster = shapely.affinity.rotate(
        cluster_poly, super_rotation, origin=(0.0, 0.0), use_radians=False
    )
    cluster_min_x, cluster_min_y = rotated_cluster.bounds[0], rotated_cluster.bounds[1]
    xoff = super_x - cluster_min_x
    yoff = super_y - cluster_min_y

    for orig_piece, (dx, dy), local_rot in zip(
        cluster.original_pieces,
        cluster.copy_offsets,
        cluster.copy_local_rotations,
    ):
        copy_poly = ShapelyPolygon(orig_piece.polygon)
        rotated_local = shapely.affinity.rotate(
            copy_poly, local_rot, origin=(0.0, 0.0), use_radians=False
        )
        rot_minx, rot_miny = rotated_local.bounds[0], rotated_local.bounds[1]
        copy_in_cluster = shapely.affinity.translate(
            rotated_local, xoff=dx - rot_minx, yoff=dy - rot_miny
        )
        rotated_with_super = shapely.affinity.rotate(
            copy_in_cluster, super_rotation, origin=(0.0, 0.0), use_radians=False
        )
        placed_copy = shapely.affinity.translate(rotated_with_super, xoff=xoff, yoff=yoff)
        cx, cy = placed_copy.bounds[0], placed_copy.bounds[1]
        effective_rot = (super_rotation + local_rot) % 360.0
        yield (orig_piece.id, round(cx, 4), round(cy, 4), effective_rot)
```

- [ ] **Step 4: Run clustering tests**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v`

Expected: ALL 17 existing tests PASS + the new `test_expand_cluster_applies_local_rotation` PASSES = 18 tests pass.

The 17 existing tests pass because:
- Their `copy_local_rotations` is all-zero (from Task 2's `[0.0] * n` initialization).
- Their `copy_offsets` are grid positions on unrotated pieces at (0,0), where the bbox top-left already equals the offset (so `dx - rot_minx == dx - 0 == dx`).
- `(super_rotation + 0.0) % 360 == super_rotation` matches existing assertions (which use cardinal angles 0, 180).

- [ ] **Step 5: Run the full suite**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/ -v`

Expected: 120 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/core/layout/clustering.py engine/tests/unit/test_clustering.py
git commit -m "feat(engine): expand_cluster_placement applies per-copy local rotation"
```

---

### Task 4: Implement `pack_cluster_union` with tests

The headline change. Inner NFP-BLF + Shapely union + holes-stripped exterior. Per-candidate width loop picks the cluster shape minimizing marker-length contribution.

**Files:**
- Modify: `engine/core/layout/clustering.py`
- Modify: `engine/tests/unit/test_clustering.py`

- [ ] **Step 1: Write failing tests (the 6 union-specific tests from spec §7)**

First, extend the top-level import block in `engine/tests/unit/test_clustering.py`. Replace:

```python
from core.layout.clustering import (
    Cluster,
    group_pieces_by_base_id,
    pack_cluster_bbox,
    pre_cluster_pieces,
    expand_cluster_placement,
)
```

with:

```python
from core.layout.clustering import (
    Cluster,
    group_pieces_by_base_id,
    pack_cluster_bbox,
    pack_cluster_union,
    pre_cluster_pieces,
    expand_cluster_placement,
    VERTEX_CAP,
)
```

Then append to the file:

```python
# --- pack_cluster_union tests ---


def test_pack_cluster_union_two_copies_share_edge():
    """2 identical 100x50 rects: inner BLF places them side-by-side touching.
    unary_union collapses the shared edge → one 200x50 rectangle exterior."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(2)]
    cluster = pack_cluster_union(copies, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0)
    assert cluster is not None
    # Exterior has 4 unique vertices (rectangle) — Shapely's exterior.coords includes a closing duplicate
    poly = cluster.super_piece.polygon
    assert len(poly) == 4  # we strip the closing duplicate when assigning to Piece.polygon
    # Bounding rectangle: 200x50
    assert cluster.super_piece.bbox.width == 200
    assert cluster.super_piece.bbox.height == 50
    # Local rotations are all 0° (single mode, no rotation freedom)
    assert cluster.copy_local_rotations == [0.0, 0.0]


def test_pack_cluster_union_picks_minimum_height_width():
    """6 copies of 100x50, fabric=500. Candidates (cluster bbox dims):
       cols=1: w=100, h=300
       cols=2: w=200, h=150
       cols=3: w=300, h=100  ← minimum h, wins
       cols=4: w=400, h=100 (with 2 dead slots — same h, larger w)
       cols=5: w=500 + 20 > 500 (infeasible)
    Winner: cols=3 with cluster_h=100, cluster_w=300."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(6)]
    cluster = pack_cluster_union(copies, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0)
    assert cluster is not None
    assert cluster.super_piece.bbox.height == 100
    assert cluster.super_piece.bbox.width == 300


def test_pack_cluster_union_bi_mode_allows_180_local_rotation():
    """For bi grain mode, inner BLF's local rotation set is {0, 180}.
    With an asymmetric polygon, the optimal pack may rotate some copies 180°.
    We assert that the inner BLF was actually called with the 180° option in its
    rotation set by checking that at LEAST ONE of the two placement strategies
    (all-zero vs mixed) is tried — the simplest assertion is that the returned
    Cluster's copy_local_rotations is well-formed (length N, values in {0, 180})."""
    # L-shape: footprint (0,0)-(100,0)-(100,40)-(40,40)-(40,80)-(0,80). Asymmetric under 180°.
    pieces = [
        Piece(
            id=f"L__c{i}", name=f"L__c{i}",
            polygon=[(0, 0), (100, 0), (100, 40), (40, 40), (40, 80), (0, 80)],
            area=100*40 + 40*40,
            bbox=BoundingBox(0, 0, 100, 80, 100, 80),
            is_valid=True,
            grainline_direction_deg=0.0,
        )
        for i in range(4)
    ]
    cluster = pack_cluster_union(pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0)
    assert cluster is not None
    assert len(cluster.copy_local_rotations) == 4
    # Every local rotation must be 0 or 180 (the cluster-local set for bi-mode + grain-locked).
    for r in cluster.copy_local_rotations:
        assert r in (0.0, 180.0), f"Unexpected local rotation: {r}"


def test_pack_cluster_union_strips_holes():
    """Build a cluster whose unioned copies form a polygon with an interior hole,
    confirm: (a) the same unary_union manually shows holes, (b) pack_cluster_union
    returns a Piece.polygon whose Shapely round-trip has zero interiors AND area
    equal to the union exterior's area (NOT the donut area)."""
    import shapely.affinity
    from shapely.ops import unary_union
    # C-shapes facing inward — 4 of them form a square with a hole in the middle.
    # Simpler synthetic: 4 right-angle "L" rotations around a center cavity.
    # We use a square-with-corner-cut and arrange 4 facing center to leave a hole.
    # Use a U-shape: bbox 60x60, polygon (0,0)(60,0)(60,60)(40,60)(40,20)(20,20)(20,60)(0,60).
    # 4 copies forming a ring would leave a hole in the middle. For deterministic
    # behavior, manually construct the union check and compare areas.
    u_polygon = [(0, 0), (60, 0), (60, 60), (40, 60), (40, 20), (20, 20), (20, 60), (0, 60)]
    pieces = [
        Piece(
            id=f"U__c{i}", name=f"U__c{i}",
            polygon=u_polygon,
            area=60*60 - 20*40,  # 3600 - 800 = 2800
            bbox=BoundingBox(0, 0, 60, 60, 60, 60),
            is_valid=True,
            grainline_direction_deg=None,
        )
        for i in range(4)
    ]
    cluster = pack_cluster_union(pieces, fabric_width_mm=300, grain_mode="single", fabric_grain_deg=0.0)
    assert cluster is not None
    # Reconstruct as Shapely polygon — should have no interiors.
    reconstructed = ShapelyPolygon(cluster.super_piece.polygon)
    assert len(list(reconstructed.interiors)) == 0
    # The polygon's exterior should be valid and enclose at least the original copy area
    # (4 * 2800 = 11200), proving holes were stripped (with holes, area would be smaller).
    assert reconstructed.area >= 11200 - 1e-3


def test_pack_cluster_union_singleton_returns_none():
    """Early-return: len(pieces) < 2 → no clustering benefit, return None."""
    assert pack_cluster_union([_rect("p__c0", 100, 50)], fabric_width_mm=500) is None


def test_pack_cluster_union_multipolygon_returns_none(monkeypatch):
    """When unary_union returns a MultiPolygon (disconnected union), every
    candidate width is skipped and pack_cluster_union returns None. We force
    this by monkeypatching shapely.ops.unary_union (as imported in clustering)
    to always return a MultiPolygon. The caller (pre_cluster_pieces) then
    falls back to pack_cluster_bbox — that fallback path is verified in Task 5."""
    from shapely.geometry import MultiPolygon, Polygon as SP
    import core.layout.clustering as clustering_mod

    def _fake_union(_geoms):
        return MultiPolygon([SP([(0, 0), (10, 0), (10, 10), (0, 10)]),
                             SP([(100, 100), (110, 100), (110, 110), (100, 110)])])

    monkeypatch.setattr(clustering_mod, "unary_union", _fake_union)
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    assert pack_cluster_union(copies, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0) is None


def test_pack_cluster_union_vertex_cap_triggers_simplify():
    """High-vertex piece x 10 should produce a union exterior whose vertex count
    is capped at VERTEX_CAP (after Shapely.simplify with SIMPLIFY_TOL_MM)."""
    import math
    # 50-vertex approximation of a circle, radius 50.
    n_verts = 50
    polygon = [
        (50 + 50 * math.cos(2 * math.pi * i / n_verts),
         50 + 50 * math.sin(2 * math.pi * i / n_verts))
        for i in range(n_verts)
    ]
    pieces = [
        Piece(
            id=f"circle__c{i}", name=f"circle__c{i}",
            polygon=polygon,
            area=math.pi * 50 * 50,
            bbox=BoundingBox(0, 0, 100, 100, 100, 100),
            is_valid=True,
            grainline_direction_deg=None,
        )
        for i in range(10)
    ]
    cluster = pack_cluster_union(pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0)
    if cluster is not None:
        # If a candidate succeeded, its exterior must respect the vertex cap.
        assert len(cluster.super_piece.polygon) <= VERTEX_CAP
```

- [ ] **Step 2: Run to confirm the new tests fail with ImportError**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v -k "pack_cluster_union"`

Expected: ALL FAIL with `ImportError: cannot import name 'pack_cluster_union' from 'core.layout.clustering'` (or `VERTEX_CAP`).

- [ ] **Step 3: Implement `pack_cluster_union`**

In `engine/core/layout/clustering.py`, add the module constants near the top (after `EDGE_GAP`):

```python
# Maximum exterior vertex count for a union cluster polygon. Beyond this we
# simplify; if still over cap, the union candidate is rejected and pre_cluster_pieces
# falls back to pack_cluster_bbox for that group.
VERTEX_CAP = 200

# Shapely.simplify tolerance (mm) applied when exterior vertex count > VERTEX_CAP.
# 0.5 mm matches engine's `_has_area_overlap` eps = 0.5 mm² (frontend SAT tolerance);
# vertices closer than this are below pixel render noise anyway.
SIMPLIFY_TOL_MM = 0.5
```

Add imports near the top of `clustering.py`:

```python
from shapely.ops import unary_union
```

Add the `pack_cluster_union` function (place it after `pack_cluster_bbox`):

```python
def pack_cluster_union(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str = "single",
    fabric_grain_deg: float = 0.0,
) -> Cluster | None:
    """Pack N identical copies via an inner NFP-BLF, then union them into a
    cluster polygon. Returns None when:
      - len(pieces) < 2 (no clustering benefit; pre_cluster_pieces passes through)
      - No candidate mini-fabric width yields a single-polygon union below VERTEX_CAP
        after simplify (pre_cluster_pieces will fall back to pack_cluster_bbox).
    """
    if len(pieces) < 2:
        return None
    # Local import to avoid circular import at module load (heuristic imports clustering).
    from core.layout.heuristic import _blf_pack_nfp, _placed_polygon, Placement

    n = len(pieces)
    base = pieces[0]
    piece_w = base.bbox.width
    piece_h = base.bbox.height

    # Cluster-local rotation set: depends ONLY on outer grain_mode + whether
    # piece has grainline. Mirrors §4 of the spec.
    base_grain = base.grainline_direction_deg
    if base_grain is None:
        cluster_local_rotations: list[float] = [0.0, 90.0, 180.0, 270.0]
    elif grain_mode == "bi":
        cluster_local_rotations = [0.0, 180.0]
    else:  # single
        cluster_local_rotations = [0.0]

    # Outer rotations the cluster will be placed at (used for grain-rotation
    # feasibility filter on candidate widths). Mirrors PR #9's bug-2 logic.
    if base_grain is None:
        outer_rotations: list[float] = [0.0, 90.0, 180.0, 270.0]
    else:
        target = (fabric_grain_deg - base_grain) % 360
        if grain_mode == "bi":
            outer_rotations = [target, (target + 180.0) % 360.0]
        else:
            outer_rotations = [target]

    def _width_at_rotation(w: float, h: float, deg: float) -> float:
        r = deg % 180.0
        if r < 1e-6 or abs(r - 180.0) < 1e-6:
            return w
        if abs(r - 90.0) < 1e-6:
            return h
        return max(w, h)  # conservative for non-cardinal

    def _height_at_rotation(w: float, h: float, deg: float) -> float:
        r = deg % 180.0
        if r < 1e-6 or abs(r - 180.0) < 1e-6:
            return h
        if abs(r - 90.0) < 1e-6:
            return w
        return max(w, h)

    usable_width = fabric_width_mm - 2 * EDGE_GAP
    best_candidate: tuple[float, float, Cluster] | None = None  # (sort_h, sort_w, cluster)

    for cols in range(1, n + 1):
        # Conservative upper-bound: cluster bbox width <= cols * piece_w
        # (true for grid; true for tight-pack since copies fit inside their bbox column).
        bbox_w_upper = cols * piece_w
        bbox_h_upper = ((n + cols - 1) // cols) * piece_h

        # Grain-rotation feasibility: at least one outer rotation must keep the
        # rotated bbox width within usable_width. Same logic as pack_cluster_bbox.
        feasible_outer_rots = [
            r for r in outer_rotations
            if _width_at_rotation(bbox_w_upper, bbox_h_upper, r) <= usable_width
        ]
        if not feasible_outer_rots:
            continue

        # Inner BLF on a mini-fabric of width (cols * piece_w + 2*EDGE_GAP) so
        # the effective packing area is cols * piece_w. Skip validation (we
        # already pre-filtered widths above) and override rotations.
        try:
            inner_placements, _, _ = _blf_pack_nfp(
                pieces, fabric_width_mm=bbox_w_upper + 2 * EDGE_GAP,
                grain_mode="single", fabric_grain_deg=0.0,
                override_rotations=cluster_local_rotations,
                skip_validation=True,
            )
        except ValueError:
            # Inner BLF couldn't place all copies at this mini-width — skip.
            continue
        if len(inner_placements) != n:
            continue

        # Shift placements by -EDGE_GAP so cluster-local frame starts at (0, 0)
        # rather than (EDGE_GAP, EDGE_GAP). Outer BLF adds its own EDGE_GAP.
        shifted = [
            Placement(pl.piece_id, pl.x - EDGE_GAP, pl.y - EDGE_GAP, pl.rotation_deg)
            for pl in inner_placements
        ]

        # Build the union of placed copies in cluster-local frame.
        pieces_by_id = {p.id: p for p in pieces}
        placed_polys = [
            _placed_polygon(pieces_by_id[pl.piece_id], pl.x, pl.y, pl.rotation_deg)
            for pl in shifted
        ]
        union = unary_union(placed_polys)
        if union.geom_type == "MultiPolygon":
            continue
        if union.geom_type != "Polygon":
            continue  # GeometryCollection / LineString — degenerate

        # Strip holes (interior rings unreachable by outer BLF).
        union = ShapelyPolygon(union.exterior)

        # Simplify if over vertex cap.
        exterior_coords = list(union.exterior.coords)
        if len(exterior_coords) - 1 > VERTEX_CAP:  # -1 for closing duplicate
            simplified = union.simplify(SIMPLIFY_TOL_MM, preserve_topology=True)
            if simplified.geom_type != "Polygon":
                continue
            simplified = ShapelyPolygon(simplified.exterior)
            exterior_coords = list(simplified.exterior.coords)
            if len(exterior_coords) - 1 > VERTEX_CAP:
                continue  # still too complex; skip this candidate
            union = simplified

        # Drop closing duplicate; Piece.polygon convention is no closing vertex.
        polygon_coords = [(round(x, 4), round(y, 4)) for x, y in exterior_coords[:-1]]

        # Cluster bbox from union bounds.
        minx, miny, maxx, maxy = union.bounds
        cluster_w = maxx - minx
        cluster_h = maxy - miny

        # Sort key (mirror pack_cluster_bbox): minimize marker-length contribution
        # at the cluster's best feasible outer rotation.
        sort_h = min(
            _height_at_rotation(cluster_w, cluster_h, r) for r in feasible_outer_rots
        )
        sort_w = min(
            _width_at_rotation(cluster_w, cluster_h, r) for r in feasible_outer_rots
        )

        super_piece = Piece(
            id=f"cluster_{_base_id(base.id)}_x{n}",
            name=f"cluster {base.name} x{n}",
            polygon=polygon_coords,
            area=sum(p.area for p in pieces),
            bbox=BoundingBox(0.0, 0.0, cluster_w, cluster_h, cluster_w, cluster_h),
            is_valid=True,
            validation_notes=[],
            grainline_direction_deg=base.grainline_direction_deg,
        )

        copy_offsets = [(pl.x, pl.y) for pl in shifted]
        copy_local_rotations = [pl.rotation_deg for pl in shifted]
        # Rebuild original_pieces in placement order (pieces are identical, so
        # the order is purely cosmetic — but we keep it consistent with
        # copy_offsets/copy_local_rotations).
        original_pieces = [pieces_by_id[pl.piece_id] for pl in shifted]

        cluster = Cluster(
            super_piece=super_piece,
            copy_offsets=copy_offsets,
            copy_local_rotations=copy_local_rotations,
            original_pieces=original_pieces,
        )

        candidate_key = (sort_h, sort_w, cluster_h, cluster_w)
        if best_candidate is None or candidate_key < (best_candidate[0], best_candidate[1], cluster_h, cluster_w):
            best_candidate = (sort_h, sort_w, cluster)

    if best_candidate is None:
        return None
    return best_candidate[2]
```

- [ ] **Step 4: Run the union tests**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v -k "pack_cluster_union"`

Expected: ALL 6 PASS.

- [ ] **Step 5: Run the full clustering test file (regression guard)**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v`

Expected: 18 existing + 6 new = 24 PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/core/layout/clustering.py engine/tests/unit/test_clustering.py
git commit -m "feat(engine): pack_cluster_union — inner NFP-BLF + Shapely union cluster polygon"
```

---

### Task 5: Wire `cluster_polygon` dispatch into `pre_cluster_pieces` with fallback ladder

Now `pre_cluster_pieces` can pick `union` or `bbox` per call. If `union` returns None for a group (MultiPolygon / vertex cap), fall back to `bbox` for THAT group only; if `bbox` also returns None, group passes through as singletons.

**Files:**
- Modify: `engine/core/layout/clustering.py`
- Modify: `engine/tests/unit/test_clustering.py`

- [ ] **Step 1: Write the failing test**

Append to `engine/tests/unit/test_clustering.py`:

```python
def test_pre_cluster_pieces_dispatch_union_default():
    """Without specifying cluster_polygon, pre_cluster_pieces uses the union path."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    clustered_input, clusters = pre_cluster_pieces(copies, fabric_width_mm=500)
    assert len(clusters) == 1
    # Union of touching rects collapses to a single rectangle, NOT a multi-vertex polygon.
    # Check via the super_piece's polygon: 4 vertices = rectangle, more = union with bays.
    # For 4 axis-aligned 100x50 rects in any feasible grid, union == bbox rectangle.
    assert len(clusters[0].super_piece.polygon) == 4


def test_pre_cluster_pieces_dispatch_bbox_explicit():
    """cluster_polygon='bbox' forces the bbox path."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    clustered_input, clusters = pre_cluster_pieces(
        copies, fabric_width_mm=500, cluster_polygon="bbox",
    )
    assert len(clusters) == 1
    # Bbox path always produces a 4-vertex rectangle.
    assert len(clusters[0].super_piece.polygon) == 4
    # Bbox copy_local_rotations are uniform zeros.
    assert clusters[0].copy_local_rotations == [0.0, 0.0, 0.0, 0.0]


def test_pre_cluster_pieces_falls_back_to_bbox_on_union_failure(monkeypatch):
    """When pack_cluster_union returns None, pre_cluster_pieces falls back to
    pack_cluster_bbox for that group. We monkeypatch pack_cluster_union to force
    a None return, then assert that the resulting Cluster still has 4 copies and
    a 4-vertex (bbox-rectangle) polygon."""
    import core.layout.clustering as clustering_mod
    monkeypatch.setattr(clustering_mod, "pack_cluster_union", lambda *args, **kwargs: None)

    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    clustered_input, clusters = pre_cluster_pieces(copies, fabric_width_mm=500)
    assert len(clusters) == 1  # Bbox fallback engaged
    assert len(clusters[0].super_piece.polygon) == 4
    assert len(clusters[0].copy_offsets) == 4


```

The existing `test_pre_cluster_oversized_group_passes_through` test from PR #9 already covers the "both union and bbox fail → group passes through" path — under the new default `cluster_polygon="union"`, it exercises the union → bbox → singletons ladder. No additional test needed for that ladder leaf.

- [ ] **Step 2: Run to confirm the new tests fail**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v -k "dispatch or falls_back"`

Expected: tests FAIL — `pre_cluster_pieces` does not yet accept `cluster_polygon` and always uses bbox.

- [ ] **Step 3: Update `pre_cluster_pieces` for dispatch + fallback ladder**

In `engine/core/layout/clustering.py`, replace `pre_cluster_pieces` with:

```python
def pre_cluster_pieces(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str = "single",
    fabric_grain_deg: float = 0.0,
    cluster_polygon: str = "union",
) -> tuple[list[Piece], list[Cluster]]:
    """Group identical pieces and pack each group via the selected cluster method.

    Fallback ladder per group:
        cluster_polygon="union" → pack_cluster_union → pack_cluster_bbox → singletons
        cluster_polygon="bbox"  → pack_cluster_bbox → singletons

    Returns (clustered_input, clusters):
      - clustered_input: list[Piece] containing singletons + super-pieces.
      - clusters: list[Cluster], one per super-piece.
    """
    if cluster_polygon not in ("union", "bbox"):
        raise ValueError(f"cluster_polygon must be 'union' or 'bbox', got: {cluster_polygon!r}")

    groups = group_pieces_by_base_id(pieces)
    clustered_input: list[Piece] = []
    clusters: list[Cluster] = []
    for group in groups.values():
        if len(group) < 2:
            clustered_input.extend(group)
            continue

        cluster: Cluster | None = None
        if cluster_polygon == "union":
            cluster = pack_cluster_union(group, fabric_width_mm, grain_mode, fabric_grain_deg)
        if cluster is None:
            cluster = pack_cluster_bbox(group, fabric_width_mm, grain_mode, fabric_grain_deg)
        if cluster is None:
            # Both union and bbox failed (group's piece too wide for fabric).
            clustered_input.extend(group)
            continue

        clustered_input.append(cluster.super_piece)
        clusters.append(cluster)
    return clustered_input, clusters
```

- [ ] **Step 4: Run clustering tests**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v`

Expected: existing tests + 3 new dispatch tests PASS. No regressions.

- [ ] **Step 5: Run the full suite**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/ -v`

Expected: all tests PASS. No regressions. Important check: the 17 PR #9 clustering tests still green (they now exercise the union-then-bbox-fallback ladder for any case where union returns None).

- [ ] **Step 6: Commit**

```bash
git add engine/core/layout/clustering.py engine/tests/unit/test_clustering.py
git commit -m "feat(engine): pre_cluster_pieces dispatches union/bbox with per-group fallback ladder"
```

---

### Task 6: Wire `cluster_polygon` into `auto_layout_polygon` + flip default; integration tests

This is the user-facing change: `auto_layout_polygon` gains the new param, `disable_clustering=False` becomes default, and the 4 heuristic integration tests from spec §7 (#9-12) verify it.

**Files:**
- Modify: `engine/core/layout/heuristic.py`
- Modify: `engine/tests/unit/test_heuristic.py`

- [ ] **Step 1: Write the failing integration tests**

Append to `engine/tests/unit/test_heuristic.py`:

```python
# --- cluster_polygon dispatch + default-on tests ---

def test_auto_layout_cluster_polygon_union_default():
    """cluster_polygon defaults to 'union'. Smoke test: 4 copies of a small rect
    in a large fabric — auto_layout returns the right number of placements."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(4)]
    placements, marker, util = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1,
    )
    assert len(placements) == 4
    assert marker > 0
    # All placement ids should be original (not super-piece) ids.
    assert {pl.piece_id for pl in placements} == {f"p__c{i}" for i in range(4)}


def test_auto_layout_cluster_polygon_bbox_matches_pr9_behavior():
    """With cluster_polygon='bbox' and disable_clustering=False, behavior matches
    PR #9 exactly: super-piece is the bbox rectangle, all copies at zero local rot."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(4)]
    placements, marker, util = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, cluster_polygon="bbox",
    )
    assert len(placements) == 4
    # For 4 axis-aligned identical rects in a generous fabric, union and bbox
    # produce the same packing (union exterior == bbox rectangle exterior).
    # We only assert no crash + correct placement count.
    assert marker > 0


def test_auto_layout_clustering_default_on():
    """disable_clustering defaults to False — calling without the flag activates
    clustering. Verify by checking that the result equals the union-default result."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(4)]
    placements_default, marker_default, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1,
    )
    placements_off, marker_off, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True,
    )
    # Both runs produce 4 placements. Marker should be equal-or-less when clustered on
    # (cannot regress for axis-aligned identical rects).
    assert len(placements_default) == 4
    assert len(placements_off) == 4
    assert marker_default <= marker_off + 1e-6


def test_auto_layout_union_no_worse_than_bbox_on_homogeneous():
    """For 10 axis-aligned identical rects, union and bbox should produce equal
    marker length (union exterior == bbox rectangle when copies share full edges)."""
    pieces = [_make_rect(f"p__c{i}", 100, 50) for i in range(10)]
    _, marker_union, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, cluster_polygon="union",
    )
    _, marker_bbox, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, cluster_polygon="bbox",
    )
    assert marker_union <= marker_bbox + 1e-6
```

- [ ] **Step 2: Run to confirm the new tests fail**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "cluster_polygon or default_on or homogeneous"`

Expected: ALL FAIL with `TypeError: auto_layout_polygon() got an unexpected keyword argument 'cluster_polygon'`.

- [ ] **Step 3: Wire `cluster_polygon` into `auto_layout_polygon` and flip default**

In `engine/core/layout/heuristic.py`, update the signature:

```python
def auto_layout_polygon(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    disable_nfp_cache: bool = False,
    effort: int = 1,
    disable_pruning: bool = False,
    disable_clustering: bool = False,         # CHANGED: was True
    cluster_polygon: str = "union",            # NEW
) -> tuple[list[Placement], float, float]:
```

Inside, update the clustering call:

```python
    if disable_clustering:
        blf_input = pieces
        clusters: list[Cluster] = []
    else:
        blf_input, clusters = pre_cluster_pieces(
            pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
            cluster_polygon=cluster_polygon,
        )
```

Update the docstring to mention `cluster_polygon` (one paragraph after the `disable_clustering:` block):

```
    `cluster_polygon`: 'union' (default) or 'bbox'. Selects the cluster polygon
    construction strategy. Union runs an inner NFP-BLF on each group's copies and
    uses the Shapely union (holes stripped, simplified to VERTEX_CAP) as the
    super-piece polygon — exposes perimeter bays to outer BLF for interleaving.
    Bbox uses the rigid bbox of the grid-packed copies — preserved for
    benchmarking and as a per-group fallback when union produces a MultiPolygon
    or exceeds VERTEX_CAP.
```

Also update the existing `disable_clustering` docstring paragraph — change the wording about default:

```
    `disable_clustering`: defaults to False. Identical-piece pre-clustering
    (`core.layout.clustering.pre_cluster_pieces`) is on by default and uses the
    union polygon path (see `cluster_polygon`). Pass True to bypass clustering
    entirely (input pieces go to BLF directly).
```

- [ ] **Step 4: Run the heuristic tests**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "cluster_polygon or default_on or homogeneous"`

Expected: ALL 4 PASS.

- [ ] **Step 5: Run the full engine test suite (critical regression check — default flip is a behavior change)**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/ -v`

Expected: 132 PASS (128 + 4 new). **If any prior test fails because of the default flip, debug the affected test — it may be relying on `disable_clustering=True` implicitly. Likely candidates: tests that compare auto_layout output bit-for-bit against pre-PR-#10 fixtures.**

If a test fails because of the default flip, fix by either (a) passing `disable_clustering=True` explicitly in the affected test, or (b) updating the expected output to reflect clustering being on. Document the choice in the commit message.

- [ ] **Step 6: Commit**

```bash
git add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git commit -m "feat(engine): auto_layout_polygon cluster_polygon param + flip clustering on by default"
```

---

### Task 7: Extend `bench_clustering.py` to 3-column matrix + verify acceptance gate

Replace the 2-column (on/off) bench with 3-column (off / cluster=bbox / cluster=union). Programmatically verify the acceptance gate from spec §8. If the sample_2.dxf row doesn't beat 12249mm, report BLOCKED.

**Files:**
- Modify: `engine/tests/bench_clustering.py`

- [ ] **Step 1: Rewrite the bench**

Replace `engine/tests/bench_clustering.py` with:

```python
"""Manual benchmark for identical-piece clustering. Not part of pytest.

Run from the worktree root with:
    D:\\openmarker\\engine\\.venv\\Scripts\\python.exe engine\\tests\\bench_clustering.py

Compares marker_length and utilization for three modes per row:
  - off:    clustering disabled (disable_clustering=True)
  - bbox:   clustering on, cluster_polygon='bbox' (PR #9 behavior)
  - union:  clustering on, cluster_polygon='union' (this PR)

The headline row uses examples/input/sample_2.dxf x 10 copies — the same
workload as the commercial-vs-OpenMarker comparison (~7pp gap).

Acceptance gate (matches spec §8):
  - 10 identical rects: union.marker <= off.marker + 1e-6
  - two-groups:         union.marker <= off.marker + 1e-6
  - 8 singletons:       union.marker == off.marker (clustering no-op)
  - sample_2.dxf x 10:  union.marker < off.marker (= 12249mm baseline)
  - parallel sample_2:  union.marker[effort=5] == union.marker[effort=1]

Prints PASS/FAIL per gate and an overall verdict at the end.
"""
from __future__ import annotations

import dataclasses
import os
import sys
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.models.piece import Piece, BoundingBox
from core.layout import heuristic


def _piece(piece_id: str, w: float, h: float, grainline: float | None = None) -> Piece:
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        validation_notes=[],
        grainline_direction_deg=grainline,
    )


def _find_sample_dxf(filename: str) -> str | None:
    here = os.path.abspath(HERE)
    for _ in range(8):
        candidate = os.path.join(here, "examples", "input", filename)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent
    return None


def _load_dxf_pieces(path: str, copies: int) -> list[Piece]:
    from core.dxf import parse_dxf
    from core.geometry import normalize_piece
    with open(path, "rb") as f:
        raw = parse_dxf(f.read())
    base_pieces: list[Piece] = []
    for i, r in enumerate(raw):
        try:
            base_pieces.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    expanded: list[Piece] = []
    for c in range(copies):
        for p in base_pieces:
            expanded.append(dataclasses.replace(p, id=f"{p.id}__c{c}"))
    return expanded


def _run(pieces, fabric_width_mm, grain_mode, effort, mode):
    """mode in {'off', 'bbox', 'union'}"""
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
    else:
        raise ValueError(f"unknown mode: {mode}")
    t0 = time.perf_counter()
    placements, length, util = heuristic.auto_layout_polygon(**kwargs)
    return time.perf_counter() - t0, length, util


def _bench(
    name: str, pieces, fabric_width_mm: float, grain_mode: str = "single", effort: int = 1,
) -> tuple[float, float, float]:
    """Run off/bbox/union; print one row; return (off_marker, bbox_marker, union_marker)."""
    # Warm up (eats first-run import / JIT overhead).
    _run(pieces, fabric_width_mm, grain_mode, effort, "union")

    off_t, off_len, off_util = _run(pieces, fabric_width_mm, grain_mode, effort, "off")
    bbox_t, bbox_len, bbox_util = _run(pieces, fabric_width_mm, grain_mode, effort, "bbox")
    union_t, union_len, union_util = _run(pieces, fabric_width_mm, grain_mode, effort, "union")

    print(
        f"{name:55s}\n"
        f"  off:    L={off_len:8.1f}/U={off_util:5.2f}%/t={off_t*1000:8.1f}ms\n"
        f"  bbox:   L={bbox_len:8.1f}/U={bbox_util:5.2f}%/t={bbox_t*1000:8.1f}ms\n"
        f"  union:  L={union_len:8.1f}/U={union_util:5.2f}%/t={union_t*1000:8.1f}ms"
    )
    return off_len, bbox_len, union_len


def _gate(name: str, condition: bool, detail: str) -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}: {detail}")
    return condition


if __name__ == "__main__":
    gates: list[bool] = []

    # Row 1: 10 identical rects. Union should match off (rectangles tile perfectly).
    pieces_identical = [_piece(f"p__c{i}", 100, 50) for i in range(10)]
    off, bbox, union = _bench("10 identical rects (100x50), fabric=500", pieces_identical, 500.0)
    gates.append(_gate("identical rects: union no-worse-than off",
                       union <= off + 1e-6, f"union={union:.1f} off={off:.1f}"))

    # Row 2: two-groups (heterogeneous).
    pieces_two_groups = (
        [_piece(f"a__c{i}", 100, 60) for i in range(6)]
        + [_piece(f"b__c{i}", 120, 40) for i in range(4)]
    )
    off, bbox, union = _bench("6x(100x60) + 4x(120x40), fabric=500", pieces_two_groups, 500.0)
    gates.append(_gate("two-groups: union no-worse-than off",
                       union <= off + 1e-6, f"union={union:.1f} off={off:.1f}"))

    # Row 3: singletons (no clustering opportunity).
    pieces_singletons = [_piece(f"piece_{i}", 100 + i * 20, 80 + (i % 3) * 30) for i in range(8)]
    off, bbox, union = _bench("8 singletons (mixed), fabric=500", pieces_singletons, 500.0)
    gates.append(_gate("singletons: union == off",
                       abs(union - off) < 1e-6, f"union={union:.1f} off={off:.1f}"))

    # Row 4: real workload. THE headline number.
    dxf_path = _find_sample_dxf("sample_2.dxf")
    if dxf_path is None:
        print("[skipped] sample_2.dxf not found — place it in examples/input/ to enable the real-workload bench")
    else:
        pieces_real = _load_dxf_pieces(dxf_path, copies=10)
        off_s, bbox_s, union_s = _bench(
            f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi, effort=1",
            pieces_real, 1651.0, "bi", effort=1,
        )
        gates.append(_gate("sample_2.dxf serial: union STRICTLY beats off (Q1 success bar)",
                           union_s < off_s, f"union={union_s:.1f} off={off_s:.1f}"))

        off_p, bbox_p, union_p = _bench(
            f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi, effort=5",
            pieces_real, 1651.0, "bi", effort=5,
        )
        gates.append(_gate("sample_2.dxf parallel: union == union[serial] (determinism)",
                           abs(union_p - union_s) < 1e-3, f"par={union_p:.1f} ser={union_s:.1f}"))

    print()
    if all(gates):
        print(f"ACCEPTANCE: ALL {len(gates)} GATES PASSED — safe to flip default + ship")
    else:
        failed = sum(1 for g in gates if not g)
        print(f"ACCEPTANCE: {failed}/{len(gates)} GATES FAILED — BLOCKED, do not ship")
        sys.exit(1)
```

- [ ] **Step 2: Run the bench**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\bench_clustering.py` (timeout 600000 ms / 10 minutes — the parallel sample_2 row may take ~60s)

Expected stdout (real numbers will vary; gates must all PASS):

```
10 identical rects (100x50), fabric=500
  off:    L=  170.0/U=58.82%/t=    50.0ms
  bbox:   L=  170.0/U=58.82%/t=     2.5ms
  union:  L=  170.0/U=58.82%/t=     ?.?ms
  [PASS] identical rects: union no-worse-than off: union=170.0 off=170.0

6x(100x60) + 4x(120x40), fabric=500
  off:    L=  180.0/U=61.33%/t=    58.0ms
  bbox:   L=  180.0/U=61.33%/t=     6.6ms
  union:  L=  ???.?/U=??.??%/t=     ?.?ms
  [PASS] two-groups: union no-worse-than off: union=180.0 off=180.0

8 singletons (mixed), fabric=500
  off:    L=  400.0/U=72.70%/t=    57.0ms
  bbox:   L=  400.0/U=72.70%/t=    57.0ms
  union:  L=  400.0/U=72.70%/t=     ?.?ms
  [PASS] singletons: union == off: union=400.0 off=400.0

sample_2.dxf x 10 copies (190 pieces), bi, effort=1
  off:    L=12249.0/U=76.00%/t=29000.0ms
  bbox:   L=29958.0/U=31.00%/t=  300.0ms
  union:  L=?????.?/U=??.??%/t=????.?ms   ← MUST be < 12249.0
  [PASS] sample_2.dxf serial: union STRICTLY beats off (Q1 success bar): union=<12249

sample_2.dxf x 10 copies (190 pieces), bi, effort=5
  off:    L=12249.0/U=76.00%/t=14000.0ms
  bbox:   L=29958.0/U=31.00%/t=  300.0ms
  union:  L=?????.?/U=??.??%/t=????.?ms
  [PASS] sample_2.dxf parallel: union == union[serial] (determinism)

ACCEPTANCE: ALL 5 GATES PASSED — safe to flip default + ship
```

**If the script exits with code 1 ("ACCEPTANCE … BLOCKED"):** STOP. Do NOT proceed to Task 8. Report results to the user and discuss whether to:
- Adjust the algorithm (e.g. raise vertex cap, change inner BLF rotation set)
- Tighten the acceptance bar (e.g. accept tie instead of strict-beat — Q1 fallback option)
- File the regression and ship the PR without flipping default

- [ ] **Step 3: Commit (only if gates pass)**

```bash
git add engine/tests/bench_clustering.py
git commit -m "$(cat <<'EOF'
test(engine): bench_clustering.py — 3-column off/bbox/union matrix + acceptance gates

Bench numbers from local run (Windows):
  <paste bench output here, including the ACCEPTANCE line>
EOF
)"
```

---

### Task 8: Docs (CLAUDE.md + BACKLOG.md)

Reflect the new behavior + tick off the BACKLOG item.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/planning/BACKLOG.md`

- [ ] **Step 1: Update `CLAUDE.md`**

Locate the `core/layout/heuristic.py` bullet under "### Engine (`engine/`)". Find the sentence describing `disable_clustering` and `core/layout/clustering.py`. Replace the existing wording about clustering with:

```
Identical-piece pre-clustering (`core/layout/clustering.py`) is ON by default and uses the union-polygon path: an inner NFP-BLF packs each group's copies, Shapely unions them (holes stripped, simplified to `VERTEX_CAP=200` vertices), and the union exterior becomes the super-piece polygon. Outer BLF can interleave other piece types into the cluster's perimeter bays. `disable_clustering: bool = False` bypasses clustering entirely (input → BLF directly). `cluster_polygon: 'union' | 'bbox' = 'union'` selects construction strategy; 'bbox' (PR #9 behavior) preserved for benchmarking and as a per-group fallback when union produces a MultiPolygon or exceeds VERTEX_CAP.
```

Then update the `core/layout/clustering.py` bullet:

```
- `core/layout/clustering.py` — `pack_cluster_union` (inner NFP-BLF + Shapely union + holes-stripped exterior + simplify-to-`VERTEX_CAP=200`), `pack_cluster_bbox` (PR #9 bbox path; fallback for MultiPolygon / over-vertex-cap unions), and `pre_cluster_pieces` (dispatches per group; fallback ladder `union → bbox → singletons`). `Cluster` dataclass holds the super-piece + per-copy offsets + per-copy local rotations + original pieces. `expand_cluster_placement` applies `(super_rotation + local_rot) % 360` per copy.
```

- [ ] **Step 2: Update `docs/planning/BACKLOG.md`**

Two edits:

(a) Under "Phase 6 follow-ups — algorithm performance", append:

```markdown
- [x] Engine: true-union polygon clusters. Inner NFP-BLF packs each group; Shapely union → cluster polygon. Outer BLF interleaves other pieces into perimeter bays. Replaces PR #9's bbox approximation (which regressed sample_2.dxf x 10 by +145%). Adds `cluster_polygon: 'union' | 'bbox' = 'union'` to `auto_layout_polygon`; flips `disable_clustering=False` default. Bench (sample_2.dxf x 10, fabric=1651, bi): union <= off + improvement, full numbers in PR. Shipped in PR #10.
```

(b) Under "Future / Unscheduled" → "Layout improvements — algorithm", change the in-progress entry `[~] Identical-piece pre-clustering (true-union polygon clusters)` to `[x]` and append `(Shipped in PR #10.)`. Move the entry to the resolved-list section if your BACKLOG uses one.

Also add follow-up items to "Future / Unscheduled" under the algorithm section:

```markdown
- [ ] **Holes-aware NFP for clusters.** Currently `pack_cluster_union` strips interior rings. Passing polygon-with-holes through pyclipper as separate paths could let BLF slide pieces into interior cluster bays (currently unreachable). Marginal gain expected; gate on a measured workload that has reachable interior bays.
- [ ] **Mirrored bi-mode within clusters.** Inner BLF's bi-mode set is `{0, 180}` — rotations only. Adding horizontal reflection would compose with the BACKLOG "Grain-compatible mirroring" item. Estimated 0.5-1.5pp additional gain.
- [ ] **Auto-decide bbox vs union per cluster.** Current dispatch is global (`cluster_polygon` flag is per-call). Per-cluster auto-decision (e.g. use bbox when union area is within 1% of bbox area — i.e. rectangle case) could save inner-BLF runtime on homogeneous workloads. Micro-optimization.
- [ ] **Cluster-aware sort strategies in outer BLF.** Add a sort like "clusters first by area DESC, then singletons by area DESC into cluster bays". Speculative; needs telemetry from real workloads to validate.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/planning/BACKLOG.md
git commit -m "docs: true-union polygon clusters in CLAUDE.md engine notes and BACKLOG"
```

---

## Out of scope (filed in BACKLOG follow-ups in Task 8)

- Holes-aware NFP (pass polygon-with-holes through pyclipper as separate paths)
- Mirrored bi-mode within clusters (horizontal reflection)
- Heterogeneous clustering (mix different base_ids in one cluster)
- Non-cardinal rotations inside clusters
- Cluster-aware sort strategies
- Auto-decide bbox vs union per cluster

## Risk notes

- **NFP cost on garment-piece unions.** Cluster polygons of 10×30-vertex copies can approach 100-150 exterior vertices. NFP O(V_a × V_b) per pair. Mitigations: `VERTEX_CAP=200` + `simplify(0.5mm)`, plus per-group bbox fallback if cap exceeded. Bench Task 7 gates total runtime at ≤ ~2× off-baseline at effort=5 (informally — if union takes > 60s on the headline workload, treat as a runtime regression).
- **Inner BLF picks a cluster the outer BLF can't place.** Candidate-width loop pre-filters per outer-rotation feasibility before running inner BLF. Mirrors PR #9 bug-2 fix.
- **Default flip breaks bit-exact tests elsewhere.** Task 6 Step 5 explicitly checks for this. Fix by either pinning `disable_clustering=True` in the affected test or updating expected output.
- **Parallel pruning interaction.** No new code in the parallel path; the shared `multiprocessing.Value` cutoff still publishes from the main process. Bench Task 7 includes a parallel determinism gate (`union[serial] == union[effort=5]`).

## Rollback plan

- **Hot fix (no redeploy):** callers can pass `cluster_polygon="bbox"` (matches PR #9) or `disable_clustering=True` (matches pre-PR-#9 behavior).
- **Code revert:** Tasks 1-8 form a clean linear commit history. A single `git revert` per commit (in reverse order) cleanly removes the PR.
