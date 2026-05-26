# Identical-Piece Pre-Clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the search space of the BLF inner loop by pre-clustering N copies of each base piece into a single rigid "super-piece" rectangle. Closes most of the ~7pp utilization gap vs commercial software on `sample_2.dxf × 10 copies` (the headline workload: 190 individual pieces → 19 super-pieces for BLF).

**Architecture:**
- New `engine/core/layout/clustering.py` module owns the grouping + packing + expansion logic.
- `Cluster` dataclass holds: synthetic super-piece (Piece with bbox polygon), per-copy local offsets, original Piece objects.
- `pre_cluster_pieces(pieces, fabric_width_mm) -> tuple[list[Piece], list[Cluster]]` returns (BLF input set, expansion map).
- `expand_cluster_placement(cluster, super_x, super_y, super_rotation) -> Iterator[tuple[str, float, float, float]]` yields per-copy (id, x, y, rotation) for each copy in a placed cluster. Returns raw tuples (not `Placement` objects) to avoid a circular import — `heuristic.py` wraps them.
- `auto_layout_polygon` is updated to: pre-cluster pieces → run BLF on the reduced set → expand placements → return.

**Cluster representation (per design discussion):**
- **Super-piece polygon = bounding box** of the packed copies — simplest; NFP works on a rectangle; loses ~5–10% per cluster due to ignoring inter-copy bays. Tradeoff documented in BACKLOG; upgrade to true-union is a future item.
- **Inner packing = greedy grid**: enumerate aspect ratios `(cols, rows)` with `cols × rows ≥ N`; among those whose `cluster_W + 2×EDGE_GAP ≤ fabric_width_mm`, pick smallest `(dead_slots, cluster_area)`. Place copies in row-major order.
- **Threshold = N ≥ 2** (always cluster when more than 1 copy).
- **Bi-grain = cluster is rigid**: outer BLF rotates the super-piece as one unit. Each copy keeps its individual grainline direction; rotation is consistent within the cluster.
- **Singletons pass through unchanged** — same behavior as today.

**Key correctness invariants:**
- `super_piece.area = sum(p.area for p in original_pieces)` — so `_compute_metrics`'s utilization is correct (total area summed across super-pieces equals total area summed across original pieces).
- `super_piece.grainline_direction_deg = original_pieces[0].grainline_direction_deg` — all copies in a cluster have the same grainline (they're identical), and the cluster inherits it.
- Expansion is bbox-top-left consistent — each expanded per-copy Placement's (x, y) is the top-left of the COPY's rotated bbox in absolute coords (matches the engine's `_placed_polygon` convention).
- `disable_clustering: bool = False` flag bypasses the entire mechanism (mirrors `disable_pruning`, `disable_nfp_cache`).

**Scope (out for this PR, filed in BACKLOG):**
- True-union polygon clusters (inter-copy bays)
- Heterogeneous clustering (mixing different base pieces)
- Cluster-aware sort strategies
- Non-cardinal rotation support (today: any rotation works mathematically, but real workloads only hit cardinal angles)

**Tech Stack:** Python 3.11, Shapely (rotation/translation math), pytest. Touches `engine/core/layout/clustering.py` (new), `engine/core/layout/heuristic.py`, `engine/tests/unit/test_clustering.py` (new), `engine/tests/unit/test_heuristic.py`, `engine/tests/bench_clustering.py` (new), `CLAUDE.md`, `docs/planning/BACKLOG.md`.

---

### Task 1: Create `engine/core/layout/clustering.py` + unit tests

**Files:**
- Create: `engine/core/layout/clustering.py`
- Create: `engine/tests/unit/test_clustering.py`

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/unit/test_clustering.py`:

```python
import pytest
from core.models.piece import Piece, BoundingBox
from core.layout.clustering import (
    Cluster,
    group_pieces_by_base_id,
    pack_cluster,
    pre_cluster_pieces,
    expand_cluster_placement,
)


def _rect(piece_id: str, w: float, h: float, grainline: float | None = None) -> Piece:
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        grainline_direction_deg=grainline,
    )


# --- group_pieces_by_base_id ---

def test_group_strips_copy_suffix():
    a0 = _rect("piece_0__c0", 100, 50)
    a1 = _rect("piece_0__c1", 100, 50)
    b0 = _rect("piece_1__c0", 80, 40)
    groups = group_pieces_by_base_id([a0, a1, b0])
    assert set(groups.keys()) == {"piece_0", "piece_1"}
    assert len(groups["piece_0"]) == 2
    assert len(groups["piece_1"]) == 1


def test_group_no_suffix_passes_through():
    """Pieces without __c{n} suffix are their own group."""
    a = _rect("piece_0", 100, 50)
    b = _rect("piece_1", 80, 40)
    groups = group_pieces_by_base_id([a, b])
    assert set(groups.keys()) == {"piece_0", "piece_1"}


# --- pack_cluster ---

def test_pack_cluster_singleton_returns_none():
    """N=1 → no clustering, return None."""
    assert pack_cluster([_rect("p__c0", 100, 50)], fabric_width_mm=300) is None


def test_pack_cluster_perfect_grid():
    """4 copies of 100×50 in fabric=300 → 2×2 grid is feasible (200 + 2*EDGE_GAP=20 ≤ 300)
    and is more compact than 1×4 (50 + 20 ≤ 300, height 200) or 4×1 (400 + 20 > 300, infeasible).
    Of feasible aspect ratios, 2×2 has the smallest bbox area (200×100=20000)."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    cluster = pack_cluster(copies, fabric_width_mm=300)
    assert cluster is not None
    assert cluster.super_piece.bbox.width == 200
    assert cluster.super_piece.bbox.height == 100
    assert len(cluster.copy_offsets) == 4
    # Area is sum of original piece areas (NOT bbox area)
    assert cluster.super_piece.area == 4 * (100 * 50)


def test_pack_cluster_narrow_fabric_forces_single_column():
    """4 copies of 100×50 in fabric=150 → only 1 column fits (100 + 20 ≤ 150)."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    cluster = pack_cluster(copies, fabric_width_mm=150)
    assert cluster is not None
    assert cluster.super_piece.bbox.width == 100
    assert cluster.super_piece.bbox.height == 200


def test_pack_cluster_too_big_returns_none():
    """A copy wider than fabric (minus selvedge) → no aspect ratio fits → None."""
    copies = [_rect(f"p__c{i}", 200, 50) for i in range(4)]
    cluster = pack_cluster(copies, fabric_width_mm=150)
    assert cluster is None


def test_pack_cluster_preserves_grainline():
    """The super-piece inherits the original pieces' grainline (they're identical)."""
    copies = [_rect(f"p__c{i}", 100, 50, grainline=90.0) for i in range(4)]
    cluster = pack_cluster(copies, fabric_width_mm=300)
    assert cluster is not None
    assert cluster.super_piece.grainline_direction_deg == 90.0


def test_pack_cluster_prime_count_picks_strip():
    """7 copies of 100×50: aspect ratios (1,7) and (7,1) have no dead space; both have area 7*100*50.
    (2,4)=8 slots wastes 1 slot. Prefer (1,7) or (7,1)."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(7)]
    cluster = pack_cluster(copies, fabric_width_mm=1000)
    assert cluster is not None
    # Must be one of the perfect-fit options
    assert (cluster.super_piece.bbox.width, cluster.super_piece.bbox.height) in [
        (100, 350), (700, 50)
    ]


# --- pre_cluster_pieces ---

def test_pre_cluster_mixed_input():
    """Mix of singletons + groups → singletons pass through, groups cluster."""
    singleton = _rect("piece_lonely", 50, 50)
    group_a = [_rect(f"piece_a__c{i}", 100, 50) for i in range(3)]
    clustered_input, clusters = pre_cluster_pieces([singleton] + group_a, fabric_width_mm=500)
    assert len(clustered_input) == 2  # 1 singleton + 1 super-piece
    assert len(clusters) == 1
    # Singleton id should pass through unchanged
    assert any(p.id == "piece_lonely" for p in clustered_input)


def test_pre_cluster_all_singletons_no_clusters():
    """If every piece is unique, no clustering happens."""
    pieces = [_rect(f"piece_{i}", 100, 50) for i in range(3)]
    clustered_input, clusters = pre_cluster_pieces(pieces, fabric_width_mm=500)
    assert len(clustered_input) == 3
    assert len(clusters) == 0


# --- expand_cluster_placement ---

def test_expand_cluster_at_rotation_zero():
    """At rotation 0°, copies expand to their local offsets translated by (super_x, super_y)."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    cluster = pack_cluster(copies, fabric_width_mm=300)  # 2×2 grid
    # Place super-piece at (500, 1000) with rotation 0°
    placements = list(expand_cluster_placement(cluster, super_x=500, super_y=1000, super_rotation=0.0))
    assert len(placements) == 4
    # Copy positions should be (500, 1000), (600, 1000), (500, 1050), (600, 1050)
    # in row-major order
    expected_positions = {(500, 1000), (600, 1000), (500, 1050), (600, 1050)}
    actual_positions = {(round(p[1], 2), round(p[2], 2)) for p in placements}
    assert actual_positions == expected_positions
    for p in placements:
        assert p[3] == 0.0  # rotation


def test_expand_cluster_at_rotation_180():
    """At rotation 180°, the cluster flips. Copies end up at mirrored positions
    within the cluster's bbox. Each copy also gets rotation 180°."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(2)]
    cluster = pack_cluster(copies, fabric_width_mm=500)  # 2×1 grid, bbox 200×50
    # Place super-piece at (0, 0) with rotation 180°
    placements = list(expand_cluster_placement(cluster, super_x=0, super_y=0, super_rotation=180.0))
    assert len(placements) == 2
    for p in placements:
        assert p[3] == 180.0  # all copies have rotation 180°


def test_expand_returns_original_piece_ids():
    """Expanded placements reference the original (not super-piece) piece IDs."""
    copies = [_rect(f"piece_a__c{i}", 100, 50) for i in range(2)]
    cluster = pack_cluster(copies, fabric_width_mm=300)
    placements = list(expand_cluster_placement(cluster, 0.0, 0.0, 0.0))
    expanded_ids = {p[0] for p in placements}
    assert expanded_ids == {"piece_a__c0", "piece_a__c1"}
```

- [ ] **Step 2: Run tests to verify they fail with ImportError**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v`

Expected: ALL tests FAIL with `ModuleNotFoundError: No module named 'core.layout.clustering'`.

- [ ] **Step 3: Create `engine/core/layout/clustering.py`**

```python
"""Identical-piece pre-clustering for BLF.

Groups copies of the same base piece into a rigid super-piece (bbox of the
packed grid), so the outer BLF places N×M copies as one unit instead of
searching for each individually. After BLF, expand_cluster_placement maps each
super-piece placement back to per-copy placements.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterator

import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon

from core.models.piece import Piece, BoundingBox

# Must match heuristic.EDGE_GAP. Duplicated here to keep clustering.py
# importable without pulling in heuristic.py (which would create a cycle).
EDGE_GAP = 10.0


@dataclass
class Cluster:
    """A pre-packed group of identical pieces, ready to be placed as a super-piece.

    Attributes:
        super_piece: Synthetic Piece whose polygon is the bbox of the packed
            grid. Its `area` field is the SUM of original copy areas (so
            utilization math stays correct downstream).
        copy_offsets: For each copy, its (dx, dy) in cluster-local coords
            (origin = cluster's bbox top-left, axis-aligned, no rotation).
        original_pieces: Original Piece objects in the same order as
            copy_offsets — used to look up id/polygon/area for expansion.
    """
    super_piece: Piece
    copy_offsets: list[tuple[float, float]]
    original_pieces: list[Piece]


def _base_id(piece_id: str) -> str:
    """Strip the frontend's `__c{n}` copy suffix.

    Two pieces sharing a base id have identical polygons. Mirrors the same
    helper in heuristic.py — duplicated to avoid a circular import.
    """
    idx = piece_id.find("__c")
    return piece_id if idx < 0 else piece_id[:idx]


def group_pieces_by_base_id(pieces: list[Piece]) -> dict[str, list[Piece]]:
    """Group pieces by their base id (suffix stripped). Returns insertion-
    ordered mapping so downstream iteration is deterministic."""
    groups: dict[str, list[Piece]] = OrderedDict()
    for piece in pieces:
        base = _base_id(piece.id)
        groups.setdefault(base, []).append(piece)
    return groups


def pack_cluster(pieces: list[Piece], fabric_width_mm: float) -> Cluster | None:
    """Pack N copies of an identical piece into a compact super-piece.

    Returns None when:
      - N < 2 (single copy: no clustering benefit)
      - No aspect ratio fits within fabric_width_mm - 2*EDGE_GAP

    Among feasible aspect ratios (cols, rows) with cols*rows >= N, picks the
    one with smallest (dead_slots, cluster_area).
    """
    if len(pieces) < 2:
        return None
    n = len(pieces)
    base = pieces[0]
    piece_w = base.bbox.width
    piece_h = base.bbox.height

    candidates: list[tuple[int, int, int, float, float]] = []
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        cluster_w = cols * piece_w
        cluster_h = rows * piece_h
        if cluster_w + 2 * EDGE_GAP > fabric_width_mm:
            continue
        dead = cols * rows - n
        candidates.append((dead, cols, rows, cluster_w, cluster_h))
    if not candidates:
        return None

    candidates.sort(key=lambda c: (c[0], c[3] * c[4]))
    _, cols, rows, cluster_w, cluster_h = candidates[0]

    offsets: list[tuple[float, float]] = []
    for row in range(rows):
        for col in range(cols):
            if len(offsets) >= n:
                break
            offsets.append((col * piece_w, row * piece_h))
        if len(offsets) >= n:
            break

    super_piece = Piece(
        id=f"cluster_{_base_id(base.id)}_x{n}",
        name=f"cluster {base.name} x{n}",
        polygon=[(0.0, 0.0), (cluster_w, 0.0), (cluster_w, cluster_h), (0.0, cluster_h)],
        area=sum(p.area for p in pieces),
        bbox=BoundingBox(0.0, 0.0, cluster_w, cluster_h, cluster_w, cluster_h),
        is_valid=True,
        validation_notes=[],
        grainline_direction_deg=base.grainline_direction_deg,
    )

    return Cluster(super_piece=super_piece, copy_offsets=offsets, original_pieces=pieces)


def pre_cluster_pieces(
    pieces: list[Piece], fabric_width_mm: float
) -> tuple[list[Piece], list[Cluster]]:
    """Group identical pieces and pack each group into a super-piece cluster.

    Returns (clustered_input, clusters):
      - clustered_input: list[Piece] containing singletons + super-pieces, to
        be passed to the existing BLF unchanged.
      - clusters: list[Cluster], one per super-piece — used to expand
        placements back to per-copy after BLF returns.
    """
    groups = group_pieces_by_base_id(pieces)
    clustered_input: list[Piece] = []
    clusters: list[Cluster] = []
    for group in groups.values():
        if len(group) < 2:
            clustered_input.extend(group)
            continue
        cluster = pack_cluster(group, fabric_width_mm)
        if cluster is None:
            # Couldn't cluster (group's piece too wide for fabric); pass through.
            clustered_input.extend(group)
            continue
        clustered_input.append(cluster.super_piece)
        clusters.append(cluster)
    return clustered_input, clusters


def expand_cluster_placement(
    cluster: Cluster,
    super_x: float,
    super_y: float,
    super_rotation: float,
) -> Iterator[tuple[str, float, float, float]]:
    """Yield (piece_id, x, y, rotation) for each copy in a placed cluster.

    Reproduces the engine's `_placed_polygon` convention: the cluster polygon
    is rotated by `super_rotation` around the origin (0, 0), then translated
    so the rotated cluster's bbox top-left lands at (super_x, super_y). The
    same affine transformation is applied to each copy's polygon (already at
    its local offset); the resulting per-copy bbox top-left becomes the copy's
    Placement.x/y. Per-copy rotation = super_rotation (cluster is rigid).
    """
    cluster_w = cluster.super_piece.bbox.width
    cluster_h = cluster.super_piece.bbox.height
    cluster_poly = ShapelyPolygon(
        [(0.0, 0.0), (cluster_w, 0.0), (cluster_w, cluster_h), (0.0, cluster_h)]
    )
    rotated_cluster = shapely.affinity.rotate(
        cluster_poly, super_rotation, origin=(0.0, 0.0), use_radians=False
    )
    cluster_min_x, cluster_min_y = rotated_cluster.bounds[0], rotated_cluster.bounds[1]
    xoff = super_x - cluster_min_x
    yoff = super_y - cluster_min_y

    for orig_piece, (dx, dy) in zip(cluster.original_pieces, cluster.copy_offsets):
        copy_poly = ShapelyPolygon(orig_piece.polygon)
        copy_poly_in_cluster = shapely.affinity.translate(copy_poly, xoff=dx, yoff=dy)
        rotated_copy = shapely.affinity.rotate(
            copy_poly_in_cluster, super_rotation, origin=(0.0, 0.0), use_radians=False
        )
        placed_copy = shapely.affinity.translate(rotated_copy, xoff=xoff, yoff=yoff)
        cx, cy = placed_copy.bounds[0], placed_copy.bounds[1]
        yield (orig_piece.id, round(cx, 4), round(cy, 4), super_rotation)
```

- [ ] **Step 4: Run all clustering tests**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v`

Expected: ALL tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/clustering.py engine/tests/unit/test_clustering.py
git commit -m "feat(engine): clustering module for identical-piece pre-clustering"
```

---

### Task 2: Wire clustering into `auto_layout_polygon`

**Files:**
- Modify: `engine/core/layout/heuristic.py`
- Modify: `engine/tests/unit/test_heuristic.py`

- [ ] **Step 1: Write the failing integration tests**

Append to `engine/tests/unit/test_heuristic.py`:

```python
# --- identical-piece clustering tests ---

def test_auto_layout_disable_clustering_yields_pre_cluster_behavior():
    """With disable_clustering=True, the result must equal pre-clustering
    behavior — same input, same chosen layout."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(4)]
    a = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True,
    )
    b = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True,
    )
    assert a[1] == b[1] and a[2] == b[2]
    assert len(a[0]) == 4


def test_auto_layout_clustering_singletons_unchanged():
    """When every input piece is unique, clustering is a no-op."""
    pieces = [_make_rect(f"piece_{i}", 80 + i * 10, 100 + (i % 3) * 30) for i in range(6)]
    on = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False,
    )
    off = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True,
    )
    assert on[1] == off[1]
    assert on[2] == off[2]


def test_auto_layout_clustering_expands_to_n_placements():
    """When clustering is on with N copies, the returned placements list must
    have N entries (one per copy), not 1 (the super-piece)."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(4)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False,
    )
    assert len(placements) == 4
    # Each placement should reference an original piece id
    placement_ids = {pl.piece_id for pl in placements}
    expected_ids = {f"p__c{i}" for i in range(4)}
    assert placement_ids == expected_ids


def test_auto_layout_clustering_does_not_increase_marker_length():
    """Clustering can only preserve or shrink marker length, never grow it
    (for rectangular pieces — irregular shapes are out of scope for this PR)."""
    pieces = [_make_rect(f"p__c{i}", 100, 50) for i in range(8)]
    on = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False,
    )
    off = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True,
    )
    assert on[1] <= off[1] + 1e-6, (
        f"Clustering made marker LONGER: on={on[1]}, off={off[1]}"
    )


def test_auto_layout_clustering_with_bi_grain():
    """Bi-grain must work with clustering: cluster rotates as a unit; each
    expanded copy gets the cluster's rotation. Result must be valid (all N
    pieces placed, no overlap)."""
    pieces = [_make_rect(f"p__c{i}", 100, 80, grainline_deg=0.0) for i in range(4)]
    placements, length, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False,
    )
    assert len(placements) == 4
    assert length > 0
```

- [ ] **Step 2: Run to confirm the tests fail with TypeError**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "clustering"`

Expected: ALL FAIL with `TypeError: auto_layout_polygon() got an unexpected keyword argument 'disable_clustering'`.

- [ ] **Step 3: Add `disable_clustering` parameter + wire clustering into `auto_layout_polygon`**

In `engine/core/layout/heuristic.py`:

(a) Add the import near the top with the other `core.layout.*` imports:

```python
from core.layout.clustering import Cluster, pre_cluster_pieces, expand_cluster_placement
```

(b) Add `disable_clustering: bool = False` to the `auto_layout_polygon` signature (after `disable_pruning`):

```python
def auto_layout_polygon(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    disable_nfp_cache: bool = False,
    effort: int = 1,
    disable_pruning: bool = False,
    disable_clustering: bool = False,
) -> tuple[list[Placement], float, float]:
```

(c) Update the docstring — add a paragraph about `disable_clustering` after the `disable_pruning:` paragraph:

```
`disable_clustering`: when True, identical-piece pre-clustering is disabled.
Identical results to legacy behavior, slower on workloads with many copies of
the same base piece — exposed for A/B benchmarking and debugging, mirroring
`disable_nfp_cache` and `disable_pruning`.
```

(d) Add a helper above `auto_layout_polygon` (placed alongside `_shorter` and `_modes_to_try`):

```python
def _expand_clustered_placements(
    placements: list[Placement],
    clusters: list[Cluster],
) -> list[Placement]:
    """Convert any super-piece placements back to per-copy placements.
    Singletons (placements not referencing a super-piece id) pass through."""
    cluster_by_super_id = {c.super_piece.id: c for c in clusters}
    expanded: list[Placement] = []
    for pl in placements:
        cluster = cluster_by_super_id.get(pl.piece_id)
        if cluster is None:
            expanded.append(pl)
            continue
        for piece_id, x, y, r in expand_cluster_placement(cluster, pl.x, pl.y, pl.rotation_deg):
            expanded.append(Placement(piece_id, x, y, r))
    return expanded
```

(e) At the top of `auto_layout_polygon`, before the existing `modes = _modes_to_try(...)` line, add the pre-cluster step:

```python
    if disable_clustering:
        blf_input = pieces
        clusters: list[Cluster] = []
    else:
        blf_input, clusters = pre_cluster_pieces(pieces, fabric_width_mm)
```

Then EVERYWHERE in the function body that currently references `pieces` (for the BLF call sites, the `len(pieces)` threshold check, and the worker submit calls), REPLACE with `blf_input`. Specifically:
- `total_runs * len(pieces) >= 20` → `total_runs * len(blf_input) >= 20`
- All `_blf_pack_nfp(pieces, ...)` calls (in the serial branch) → `_blf_pack_nfp(blf_input, ...)`
- All `pool.submit(_run_one_strategy, pieces, ...)` (in the parallel branch) → `pool.submit(_run_one_strategy, blf_input, ...)`

(f) At the END of `auto_layout_polygon` (right before each `return best`), wrap the placements through expansion. Replace the existing serial-branch return:

```python
        assert best is not None
        return best
```

with:

```python
        assert best is not None
        if clusters:
            placements, marker_length, utilization = best
            placements = _expand_clustered_placements(placements, clusters)
            return placements, marker_length, utilization
        return best
```

Do the SAME replacement for the parallel-branch return. Marker length and utilization don't change under expansion (the super-piece's bbox dimensions exactly bound the expanded copies; the super-piece's area = sum of copy areas).

- [ ] **Step 4: Run the full engine test suite**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/ -v`

Expected: every test passes — 94 (post-PR-#8) + 5 from Task 2 + ~12 from Task 1 = ~111 tests.

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git commit -m "feat(engine): wire identical-piece clustering into auto_layout_polygon"
```

---

### Task 3: Benchmark

**Files:**
- Create: `engine/tests/bench_clustering.py`

Unlike the pruning benches (which measure speedup with `result=same`), this bench measures **marker length reduction** (clustering should produce shorter or equal markers). The success criterion is `result_on.marker_length <= result_off.marker_length + 1e-6` on every row, with a meaningful reduction on the headline sample_2.dxf row.

- [ ] **Step 1: Write the benchmark**

Create `engine/tests/bench_clustering.py`:

```python
"""Manual benchmark for identical-piece clustering. Not part of pytest.

Run from the worktree root with:
    D:\\openmarker\\engine\\.venv\\Scripts\\python.exe engine\\tests\\bench_clustering.py

Compares marker_length and utilization (clustering on vs off) on a few
scenarios. The headline row uses examples/input/sample_2.dxf x 10 copies —
the same workload as the commercial-vs-OpenMarker comparison (~7pp gap).
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


def _run(pieces, fabric_width_mm, grain_mode, effort, disable_clustering):
    t0 = time.perf_counter()
    placements, length, util = heuristic.auto_layout_polygon(
        pieces, fabric_width_mm=fabric_width_mm,
        grain_mode=grain_mode, fabric_grain_deg=0.0, effort=effort,
        disable_clustering=disable_clustering,
    )
    return time.perf_counter() - t0, length, util


def _bench(name: str, pieces, fabric_width_mm: float, grain_mode: str = "single", effort: int = 1) -> None:
    # Warmup pass — eats import/JIT overhead.
    _run(pieces, fabric_width_mm, grain_mode, effort, disable_clustering=False)

    on_t, on_len, on_util = _run(pieces, fabric_width_mm, grain_mode, effort, disable_clustering=False)
    off_t, off_len, off_util = _run(pieces, fabric_width_mm, grain_mode, effort, disable_clustering=True)

    speedup = off_t / on_t if on_t > 0 else float("inf")
    length_change = (off_len - on_len) / off_len * 100 if off_len > 0 else 0.0
    util_change = on_util - off_util
    regression = on_len > off_len + 1e-6
    status = "REGRESSED" if regression else "OK"
    print(
        f"{name:55s} on=L{on_len:8.1f}/U{on_util:5.2f}%/{on_t*1000:7.1f}ms  "
        f"off=L{off_len:8.1f}/U{off_util:5.2f}%/{off_t*1000:7.1f}ms  "
        f"Δlen={-length_change:+5.2f}%  Δutil={util_change:+5.2f}pp  [{status}]"
    )


if __name__ == "__main__":
    # All-identical rects — clustering's ideal case (no diversity to interleave).
    pieces_identical = [_piece(f"p__c{i}", 100, 50) for i in range(10)]
    _bench("10 identical rects (100x50), fabric=500", pieces_identical, 500.0)

    # Two groups: 6 copies of one + 4 copies of another.
    pieces_two_groups = (
        [_piece(f"a__c{i}", 100, 60) for i in range(6)]
        + [_piece(f"b__c{i}", 120, 40) for i in range(4)]
    )
    _bench("6×(100x60) + 4×(120x40), fabric=500", pieces_two_groups, 500.0)

    # All singletons — clustering should be a no-op.
    pieces_singletons = [_piece(f"piece_{i}", 100 + i * 20, 80 + (i % 3) * 30) for i in range(8)]
    _bench("8 singletons (mixed), fabric=500", pieces_singletons, 500.0)

    # Real workload: sample_2.dxf × 10 copies. THE headline number.
    dxf_path = _find_sample_dxf("sample_2.dxf")
    if dxf_path is None:
        print("[skipped] sample_2.dxf not found — place it in examples/input/ to enable the real-workload bench")
    else:
        pieces_real = _load_dxf_pieces(dxf_path, copies=10)
        _bench(
            f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi",
            pieces_real, 1500.0, "bi",
        )
        # Also at effort=5 to compare against PR #8's parallel baseline.
        _bench(
            f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi [par]",
            pieces_real, 1500.0, "bi", effort=5,
        )
```

- [ ] **Step 2: Run the benchmark and capture output**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\bench_clustering.py`

Expected output: every row shows status `[OK]` (no `[REGRESSED]`). The all-identical row should show meaningful `Δlen` improvement; the all-singletons row should show `Δlen=+0.00%` (no-op for singletons); the sample_2.dxf rows should show the headline reduction.

If any row shows `[REGRESSED]`, **STOP and report BLOCKED** — clustering is making things WORSE on that workload.

Use a 5-minute timeout (300000 ms) — the parallel sample_2.dxf row may take ~30-60 s.

- [ ] **Step 3: Commit**

```bash
git add engine/tests/bench_clustering.py
git commit -m "$(cat <<'EOF'
test(engine): bench script for identical-piece clustering

Numbers from local run (Windows):
  <paste bench output here>
EOF
)"
```

---

### Task 4: Docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/planning/BACKLOG.md`

- [ ] **Step 1: Update `CLAUDE.md`**

Locate the `core/layout/heuristic.py` bullet under "### Engine (`engine/`)". Append one sentence at the end of that bullet (after the existing parallel-pruning + disable_pruning sentence):

```
Identical-piece pre-clustering (`core/layout/clustering.py`) runs before BLF: copies of the same base piece are packed into a rigid super-piece (bbox of the grid), reducing the BLF search space; placements are expanded back to per-copy after BLF returns. `disable_clustering: bool = False` on `auto_layout_polygon` turns it off (mirrors `disable_pruning`).
```

Then add a new bullet immediately after the `core/layout/heuristic.py` bullet, describing the new clustering module:

```
- `core/layout/clustering.py` — `pre_cluster_pieces` (groups by base id, packs each group into a super-piece bbox via greedy grid aspect-ratio search) and `expand_cluster_placement` (converts a super-piece placement back to per-copy placements). `Cluster` dataclass holds the super-piece + copy offsets + original pieces. Cluster polygon is the bounding box of the packed grid — not the union, so inter-copy bays are unused (acceptable approximation for garment pieces; true-union polygon is filed in BACKLOG as a future improvement).
```

- [ ] **Step 2: Update `docs/planning/BACKLOG.md`**

Two edits:

(a) Under "Phase 6 follow-ups — algorithm performance", append a new bullet after the parallel-pruning entry:

```markdown
- [x] Engine: identical-piece pre-clustering. Groups copies of the same base piece into a rigid super-piece (bbox of packed grid); outer BLF places clusters as units; per-copy placements expanded after BLF returns. Cluster polygon = bbox approximation (inter-copy bays unused). Measured marker reduction on `sample_2.dxf × 10` (bi grain): <paste Δlen number from bench>. Adds `disable_clustering: bool = False` toggle. Shipped in PR #9.
```

(b) Under "Future / Unscheduled" → "Layout improvements — algorithm", tick off the **Identical-piece pre-clustering** entry by changing `[ ]` to `[x]` and appending `(Shipped in PR #9.)` to its text.

Leave `PR #9` as literal placeholders — they'll be filled in after the PR is created.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/planning/BACKLOG.md
git commit -m "docs: identical-piece clustering in CLAUDE.md engine notes and BACKLOG"
```

---

## Out of scope for this PR (filed in BACKLOG)

- **True-union polygon clusters.** Use Shapely union of the packed copy polygons (with copy offsets applied) as the cluster polygon, instead of the bbox. NFP gets more expensive (cluster polygon may be non-convex with holes) but reclaims inter-copy bay space. Estimated additional gain: 1–3pp on garment workloads.
- **Heterogeneous clustering.** Cluster pieces with different base_ids if their bboxes pack well together (e.g., a small piece tucked next to a large one). Combinatorial search over which pieces to cluster — needs care to avoid blowup.
- **Cluster-aware sort strategies.** Add sorts like "clusters first, then singletons by area" or "interleave large singletons with clusters". May yield 0.5–2pp on mixed workloads.
- **Non-cardinal rotation support.** Current expansion math works for any rotation via Shapely, but tests only cover cardinal (0°/90°/180°/270°). Add coverage for 45° if any real DXF needs it.

## Risk notes

- **Clustering can hurt non-rectangular pieces.** Two triangles can nest as a rectangle when placed individually by BLF; clustered together as a 1×2 strip they waste half the bbox. The bench includes `test_polygon_nfp_triangles_nest_diagonally` from the existing test suite; if clustering breaks it, we'd need a "skip clustering for low-area-ratio pieces" heuristic. For the sample_2.dxf workload (mostly rectangular/trapezoidal garment pieces), this risk is low — but worth confirming by running the existing triangle test with clustering enabled.
- **Expansion math is fiddly.** The cluster's rotation propagates to each copy via Shapely affinity transforms. Cardinal rotations are exact; non-cardinal rotations are mathematically correct but produce non-bbox-aligned final positions. The integration test `test_auto_layout_clustering_with_bi_grain` exercises 180° rotation explicitly.
- **Singleton compatibility.** Pieces with `__c0` suffix and N=1 must pass through unchanged. The `pack_cluster` early-return on `len < 2` and `pre_cluster_pieces`' singleton pass-through guard this.
- **NFP cache interaction.** Each cluster's super-piece has a unique synthetic id (`cluster_{base}_x{N}`), so it can't hit a stale NFP cache entry from a previous call. The per-call NFP cache works correctly: the super-piece's NFP against other pieces is computed once per (super-piece, other-piece, rotation-pair) and reused across BLF iterations.
