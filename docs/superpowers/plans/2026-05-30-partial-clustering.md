# Partial Clustering (`cluster_fraction`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `cluster_fraction: float = 1.0` opt-in knob to identical-piece pre-clustering that holds back the last `N - floor(N * fraction)` copies of each group as singletons in the outer BLF input, testing the true-union polygon clusters work's (2026-05-26) "singletons in cluster bays" hypothesis.

**Architecture:** Single parameter threaded through two layers (`auto_layout_polygon` → `pre_cluster_pieces`). The per-group split lives inside `pre_cluster_pieces`'s existing loop — `pack_cluster_union` / `pack_cluster_bbox` receive a smaller `cluster_pieces` slice and have no awareness of the split. Default `cluster_fraction=1.0` is bit-identical to current behavior (the new `leftover_pieces.extend()` is a no-op).

**Tech Stack:** Python 3.11 / Shapely / pyclipper / pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-30-partial-clustering-design.md` — read first for full context.

**Commit policy:** This plan's "Commit" steps show suggested `git add` / `git commit` commands. Per the user's global CLAUDE.md (`Never run git commit or git push or git add ... unless project scope CLAUDE.md permitted`), the executing agent must NOT run these directly — instead, propose the exact command and wait for the user to run it or explicitly approve. Each task's commit step shows the file list and a suggested message in the format the user expects ("one concise commit message per changed or newly added file").

**Bench fixture note:** `examples/input/sample_2.dxf` (referenced by Task 7's bench sweep and Task 8's docs update) is not in git but is present in the user's working copy per memory `benchmark_fixture.md`. The bench script already handles missing-fixture gracefully (skips the row with a "[skipped]" message).

---

## File Structure

**Modified:**
- `engine/core/layout/clustering.py` — add `cluster_fraction` param + validation + per-group split logic to `pre_cluster_pieces`.
- `engine/core/layout/heuristic.py` — add `cluster_fraction` param to `auto_layout_polygon`, forward into `pre_cluster_pieces`.
- `engine/tests/unit/test_clustering.py` — append 13 new tests after the existing `pre_cluster_pieces` tests (currently ending around line 496).
- `engine/tests/unit/test_heuristic.py` — append 3 new tests at the end of the existing `cluster_polygon dispatch` section (currently ending around line 660).
- `engine/tests/bench_clustering.py` — add `cluster_fraction` kwarg to `_run`, add `union_f` mode, add fraction-sweep block + new acceptance gate.
- `docs/planning/PERFORMANCE.md` — add § 4.5, update § 5.A item 1, add new dated § 6 entry.
- `docs/planning/BACKLOG.md` — update one bullet under Phase 6 follow-ups.

**Created:** None.

---

## Task 1: Add `cluster_fraction` parameter to `pre_cluster_pieces` with range validation

**Files:**
- Modify: `engine/core/layout/clustering.py:435-475` (`pre_cluster_pieces` function — signature + validation block only; per-group loop body unchanged this task)
- Test: `engine/tests/unit/test_clustering.py` (append after line 496)

- [ ] **Step 1: Write the 4 validation tests**

Append to `engine/tests/unit/test_clustering.py`:

```python
# --- cluster_fraction validation (partial clustering) ---

def test_pre_cluster_pieces_rejects_fraction_zero():
    """cluster_fraction=0.0 is out of the (0.0, 1.0] range."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    with pytest.raises(ValueError, match="cluster_fraction"):
        pre_cluster_pieces(copies, fabric_width_mm=500, cluster_fraction=0.0)


def test_pre_cluster_pieces_rejects_fraction_negative():
    """cluster_fraction=-0.1 is out of the (0.0, 1.0] range."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    with pytest.raises(ValueError, match="cluster_fraction"):
        pre_cluster_pieces(copies, fabric_width_mm=500, cluster_fraction=-0.1)


def test_pre_cluster_pieces_rejects_fraction_above_one():
    """cluster_fraction=1.5 is out of the (0.0, 1.0] range."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    with pytest.raises(ValueError, match="cluster_fraction"):
        pre_cluster_pieces(copies, fabric_width_mm=500, cluster_fraction=1.5)


def test_pre_cluster_pieces_accepts_fraction_one():
    """cluster_fraction=1.0 (the default) must not raise."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(4)]
    clustered_input, clusters = pre_cluster_pieces(copies, fabric_width_mm=500, cluster_fraction=1.0)
    assert len(clusters) == 1
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v -k "fraction"`
Expected: 4 FAILS, all with `TypeError: pre_cluster_pieces() got an unexpected keyword argument 'cluster_fraction'`.

- [ ] **Step 3: Add the parameter + validation to `pre_cluster_pieces`**

In `engine/core/layout/clustering.py`, modify `pre_cluster_pieces`'s signature and validation block:

```python
def pre_cluster_pieces(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str = "single",
    fabric_grain_deg: float = 0.0,
    cluster_polygon: str = "union",
    cluster_fraction: float = 1.0,
) -> tuple[list[Piece], list[Cluster]]:
    """Group identical pieces and pack each group via the selected cluster method.

    Fallback ladder per group:
        cluster_polygon="union" → pack_cluster_union → pack_cluster_bbox → singletons
        cluster_polygon="bbox"  → pack_cluster_bbox → singletons

    `cluster_fraction` (default 1.0) holds back the last N - floor(N * fraction)
    copies of each group as singletons in the outer BLF input. When the computed
    cluster size is < 2, the whole group passes through as singletons (no cluster
    is constructed). Must be in (0.0, 1.0]; out-of-range raises ValueError.

    Returns (clustered_input, clusters):
      - clustered_input: list[Piece] containing singletons + super-pieces.
      - clusters: list[Cluster], one per super-piece.
    """
    if cluster_polygon not in ("union", "bbox"):
        raise ValueError(f"cluster_polygon must be 'union' or 'bbox', got: {cluster_polygon!r}")
    if not (0.0 < cluster_fraction <= 1.0):
        raise ValueError(f"cluster_fraction must be in (0.0, 1.0], got: {cluster_fraction!r}")

    groups = group_pieces_by_base_id(pieces)
    clustered_input: list[Piece] = []
    clusters: list[Cluster] = []
    for group in groups.values():
        if len(group) < 2:
            clustered_input.extend(group)
            continue
        # ... existing loop body unchanged (per-group split lands in Task 2) ...
        cluster: Cluster | None = None
        if cluster_polygon == "union":
            cluster = pack_cluster_union(group, fabric_width_mm, grain_mode, fabric_grain_deg)
        if cluster is None:
            cluster = pack_cluster_bbox(group, fabric_width_mm, grain_mode, fabric_grain_deg)
        if cluster is None:
            clustered_input.extend(group)
            continue

        clustered_input.append(cluster.super_piece)
        clusters.append(cluster)
    return clustered_input, clusters
```

(The loop body shown here is the *current* loop body, unchanged. Task 2 replaces it.)

- [ ] **Step 4: Run the validation tests to verify they pass**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v -k "fraction"`
Expected: 4 PASS.

- [ ] **Step 5: Run the full clustering test file to confirm no regression**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v`
Expected: all existing tests still PASS (the param defaults to 1.0 and is otherwise unused), plus the 4 new validation tests PASS.

- [ ] **Step 6: Commit (propose to user; do not run)**

Suggested:
```
git add engine/core/layout/clustering.py engine/tests/unit/test_clustering.py
git commit -m "feat(engine): add cluster_fraction param to pre_cluster_pieces (validation only)"
```

---

## Task 2: Implement per-group split + min-cluster promotion

**Files:**
- Modify: `engine/core/layout/clustering.py` (`pre_cluster_pieces`'s per-group loop body only — same function as Task 1)
- Test: `engine/tests/unit/test_clustering.py` (append after Task 1's tests)

This is the core behavioral change. Six tests drive the implementation: three for split math (incl. first-k determinism), three for the min-cluster promotion branch.

- [ ] **Step 1: Write the 6 split + promotion tests**

Append to `engine/tests/unit/test_clustering.py`:

```python
# --- cluster_fraction split logic (partial clustering) ---

def test_partial_cluster_fraction_one_matches_full_cluster():
    """cluster_fraction=1.0 (default) is bit-identical to current behavior:
    every copy enters the cluster, no leftover singletons appended."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(10)]
    clustered_input, clusters = pre_cluster_pieces(copies, fabric_width_mm=2000, cluster_fraction=1.0)
    assert len(clusters) == 1
    assert len(clusters[0].original_pieces) == 10
    # clustered_input has exactly 1 super_piece, no extra singletons.
    assert len(clustered_input) == 1
    assert clustered_input[0] is clusters[0].super_piece


def test_partial_cluster_fraction_half_splits_5_5():
    """cluster_fraction=0.5 on N=10: floor(10 * 0.5) = 5 in cluster, 5 leftover.
    clustered_input should have 1 super-piece + 5 singletons = 6 elements."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(10)]
    clustered_input, clusters = pre_cluster_pieces(copies, fabric_width_mm=2000, cluster_fraction=0.5)
    assert len(clusters) == 1
    assert len(clusters[0].original_pieces) == 5
    # 1 super-piece + 5 leftover singletons
    assert len(clustered_input) == 6


def test_partial_cluster_fraction_holds_back_last_copies():
    """The cluster takes group[:k] (first k copies); leftover is group[k:]
    (last N - k copies). Determinism guard: relied on for bench run-to-run stability."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(10)]
    clustered_input, clusters = pre_cluster_pieces(copies, fabric_width_mm=2000, cluster_fraction=0.7)
    assert len(clusters) == 1
    # Cluster has the first 7 copies (by input order).
    assert [p.id for p in clusters[0].original_pieces] == [f"p__c{i}" for i in range(7)]
    # Leftover singletons are the last 3 copies, appended after the super-piece.
    leftover_ids = [p.id for p in clustered_input if not p.id.startswith("cluster_")]
    assert leftover_ids == [f"p__c{i}" for i in range(7, 10)]


def test_partial_cluster_promotes_when_k_below_two():
    """cluster_fraction=0.1 on N=10: floor(10 * 0.1) = 1 < 2.
    Whole group passes through as 10 singletons; no cluster constructed."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(10)]
    clustered_input, clusters = pre_cluster_pieces(copies, fabric_width_mm=2000, cluster_fraction=0.1)
    assert clusters == []
    assert len(clustered_input) == 10
    assert all(p.id.startswith("p__c") for p in clustered_input)


def test_partial_cluster_promotes_small_group():
    """cluster_fraction=0.5 on N=3: floor(3 * 0.5) = 1 < 2.
    Whole group passes through as 3 singletons; no cluster."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(3)]
    clustered_input, clusters = pre_cluster_pieces(copies, fabric_width_mm=2000, cluster_fraction=0.5)
    assert clusters == []
    assert len(clustered_input) == 3


def test_partial_cluster_promotes_pair():
    """cluster_fraction=0.5 on N=2: floor(2 * 0.5) = 1 < 2.
    Whole group passes through as 2 singletons; no cluster (regression case)."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(2)]
    clustered_input, clusters = pre_cluster_pieces(copies, fabric_width_mm=2000, cluster_fraction=0.5)
    assert clusters == []
    assert len(clustered_input) == 2
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v -k "partial_cluster"`
Expected: `fraction_one_matches_full_cluster` PASSES (default 1.0 still clusters everything via existing code path). The 5 other tests FAIL with assertions on cluster/clustered_input contents — the existing loop doesn't honor `cluster_fraction`.

(Specifically: `fraction_half_splits_5_5` will see `len(clustered_input) == 1` instead of 6 because the unchanged loop still clusters all 10 copies. Promotion tests will see `len(clusters) == 1` instead of 0 because the loop never checks `k < 2`.)

- [ ] **Step 3: Replace the per-group loop body with the split + promotion logic**

In `engine/core/layout/clustering.py`, modify the `pre_cluster_pieces` per-group loop. Add `import math` at the top of the file if not already imported (it is — line 10).

Replace the entire `for group in groups.values():` block with:

```python
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
            # Both pack paths failed on the k-slice. Whole group (k + leftover)
            # falls back to singletons.
            clustered_input.extend(group)
            continue

        clustered_input.append(cluster.super_piece)
        clusters.append(cluster)
        clustered_input.extend(leftover_pieces)
```

- [ ] **Step 4: Run the partial-cluster tests to verify they pass**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v -k "partial_cluster"`
Expected: 6 PASS.

- [ ] **Step 5: Run the full clustering test file to confirm no regression**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v`
Expected: all existing tests still PASS (the `cluster_fraction=1.0` default makes `k = n`, `leftover = []`, and the new `extend(leftover_pieces)` is a no-op). All new validation + split tests PASS. Test count ≈ 30 → 40.

- [ ] **Step 6: Commit (propose to user; do not run)**

Suggested:
```
git add engine/core/layout/clustering.py engine/tests/unit/test_clustering.py
git commit -m "feat(engine): pre_cluster_pieces honors cluster_fraction with first-k split + min-cluster promotion"
```

---

## Task 3: Heterogeneous-group regression test

**Files:**
- Test: `engine/tests/unit/test_clustering.py` (append after Task 2's tests)

The Task 2 implementation iterates `groups.values()` and computes `k` independently per group. This test guards against a future refactor that accidentally couples groups together.

- [ ] **Step 1: Write the heterogeneous-group test**

Append to `engine/tests/unit/test_clustering.py`:

```python
def test_partial_cluster_per_group_fractions():
    """cluster_fraction=0.7 on a mixed input with one group of N=10 and one of N=3:
    each group computes its own k independently.
      - Group A (N=10): floor(10 * 0.7) = 7 in cluster, 3 leftover.
      - Group B (N=3):  floor(3 * 0.7)  = 2 in cluster, 1 leftover.
    Two clusters total, 4 leftover singletons total."""
    group_a = [_rect(f"a__c{i}", 100, 50) for i in range(10)]
    group_b = [_rect(f"b__c{i}", 120, 40) for i in range(3)]
    clustered_input, clusters = pre_cluster_pieces(
        group_a + group_b, fabric_width_mm=2000, cluster_fraction=0.7,
    )
    assert len(clusters) == 2
    # Verify per-group sizes (groups preserve input order via OrderedDict in
    # group_pieces_by_base_id).
    cluster_sizes = sorted(len(c.original_pieces) for c in clusters)
    assert cluster_sizes == [2, 7]
    # 2 super-pieces + (3 + 1) leftover singletons = 6 total in clustered_input.
    assert len(clustered_input) == 6
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py::test_partial_cluster_per_group_fractions -v`
Expected: PASS (Task 2's per-group loop already handles this correctly).

- [ ] **Step 3: Commit (propose to user; do not run)**

Suggested:
```
git add engine/tests/unit/test_clustering.py
git commit -m "test(engine): partial-cluster heterogeneous-group regression guard"
```

---

## Task 4: Fallback ladder test (monkeypatched)

**Files:**
- Test: `engine/tests/unit/test_clustering.py` (append after Task 3's test)

Spec § 4: "If `pack_cluster_union` returns `None` for the first k, `pack_cluster_bbox` is tried on the same first k. Only if BOTH fail does the **whole group** (k + leftover) go to singletons."

- [ ] **Step 1: Write the fallback test**

Append to `engine/tests/unit/test_clustering.py`:

```python
def test_partial_cluster_falls_back_on_pack_failure(monkeypatch):
    """When BOTH pack_cluster_union and pack_cluster_bbox return None on the
    k-slice, the WHOLE group (k + leftover) falls back to singletons.
    Monkeypatched to force both to None so the test doesn't depend on geometry
    that actually breaks both pack paths."""
    import core.layout.clustering as clustering_mod
    monkeypatch.setattr(clustering_mod, "pack_cluster_union", lambda *args, **kwargs: None)
    monkeypatch.setattr(clustering_mod, "pack_cluster_bbox", lambda *args, **kwargs: None)

    copies = [_rect(f"p__c{i}", 100, 50) for i in range(10)]
    clustered_input, clusters = pre_cluster_pieces(
        copies, fabric_width_mm=2000, cluster_fraction=0.7,
    )
    # No cluster constructed; whole group (k=7 + leftover=3) = 10 singletons.
    assert clusters == []
    assert len(clustered_input) == 10
    assert all(p.id.startswith("p__c") for p in clustered_input)
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py::test_partial_cluster_falls_back_on_pack_failure -v`
Expected: PASS (Task 2's `if cluster is None: clustered_input.extend(group)` branch handles this).

- [ ] **Step 3: Commit (propose to user; do not run)**

Suggested:
```
git add engine/tests/unit/test_clustering.py
git commit -m "test(engine): partial-cluster falls back to singletons on pack failure"
```

---

## Task 5: bbox-path coverage test

**Files:**
- Test: `engine/tests/unit/test_clustering.py` (append after Task 4's test)

The split lives in `pre_cluster_pieces` (before path dispatch), so the knob applies equally to `cluster_polygon="bbox"` and `cluster_polygon="union"`. Lock this in with an explicit test.

- [ ] **Step 1: Write the bbox-path test**

Append to `engine/tests/unit/test_clustering.py`:

```python
def test_partial_cluster_bbox_path_splits_correctly():
    """cluster_polygon="bbox" + cluster_fraction=0.7 on N=10:
    7 copies in bbox cluster + 3 leftover singletons. Same split behavior as
    union path — the knob lives in pre_cluster_pieces, before path dispatch."""
    copies = [_rect(f"p__c{i}", 100, 50) for i in range(10)]
    clustered_input, clusters = pre_cluster_pieces(
        copies, fabric_width_mm=2000, cluster_polygon="bbox", cluster_fraction=0.7,
    )
    assert len(clusters) == 1
    assert len(clusters[0].original_pieces) == 7
    # bbox cluster polygon is always a 4-vertex rectangle.
    assert len(clusters[0].super_piece.polygon) == 4
    # 1 super-piece + 3 leftover singletons
    assert len(clustered_input) == 4
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py::test_partial_cluster_bbox_path_splits_correctly -v`
Expected: PASS.

- [ ] **Step 3: Run the full clustering test file as a checkpoint**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_clustering.py -v`
Expected: ALL clustering tests pass. New test count: 13 partial-clustering tests added on top of the existing ~28 → ~41 total in this file.

- [ ] **Step 4: Commit (propose to user; do not run)**

Suggested:
```
git add engine/tests/unit/test_clustering.py
git commit -m "test(engine): partial-cluster knob applies to bbox path too"
```

---

## Task 6: Add `cluster_fraction` to `auto_layout_polygon` + integration tests

**Files:**
- Modify: `engine/core/layout/heuristic.py:665-723` (`auto_layout_polygon` signature + docstring + forwarding)
- Test: `engine/tests/unit/test_heuristic.py` (append after line 660 at the end of the existing `cluster_polygon dispatch` section)

- [ ] **Step 1: Write the 3 integration tests**

Append to `engine/tests/unit/test_heuristic.py`:

```python
# --- cluster_fraction (partial clustering) integration tests ---

def test_auto_layout_polygon_default_cluster_fraction_is_one():
    """The cluster_fraction parameter defaults to 1.0 (current behavior).
    Verified via signature inspection."""
    import inspect
    sig = inspect.signature(auto_layout_polygon)
    assert sig.parameters["cluster_fraction"].default == 1.0


def test_auto_layout_polygon_cluster_fraction_passes_through():
    """Plumbing test: with disable_clustering=False, lowering cluster_fraction
    causes leftover singletons to enter the BLF input. We verify the placement
    count is the same (all original pieces still get placed) and the marker
    length CAN differ because the split changes BLF's input."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(6)]
    placements_full, marker_full, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False, cluster_polygon="union", cluster_fraction=1.0,
    )
    placements_partial, marker_partial, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=False, cluster_polygon="union", cluster_fraction=0.5,
    )
    # Both paths place all 6 pieces.
    assert len(placements_full) == 6
    assert len(placements_partial) == 6
    # The split changes the BLF input (1 super + 3 singletons vs 1 super of 6),
    # which can change marker length. We only assert the call doesn't crash and
    # all pieces are placed — the actual marker comparison is workload-dependent.
    assert marker_full > 0
    assert marker_partial > 0


def test_auto_layout_polygon_cluster_fraction_ignored_when_clustering_disabled():
    """With disable_clustering=True, cluster_fraction has no effect — the
    pre_cluster_pieces call is skipped entirely in auto_layout_polygon."""
    pieces = [_make_rect(f"p__c{i}", 100, 80) for i in range(6)]
    _, marker_default, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True, cluster_fraction=1.0,
    )
    _, marker_low, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        effort=1, disable_clustering=True, cluster_fraction=0.5,
    )
    # Bit-identical: cluster_fraction is moot when clustering is off.
    assert marker_default == marker_low
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "cluster_fraction"`
Expected: 3 FAILS — `signature.parameters["cluster_fraction"]` raises `KeyError`; the other two raise `TypeError: auto_layout_polygon() got an unexpected keyword argument 'cluster_fraction'`.

- [ ] **Step 3: Add the parameter + forwarding in `auto_layout_polygon`**

In `engine/core/layout/heuristic.py`, modify `auto_layout_polygon`'s signature, docstring, and the `pre_cluster_pieces` call:

```python
def auto_layout_polygon(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str = "single",
    fabric_grain_deg: float = 0.0,
    disable_nfp_cache: bool = False,
    effort: int = 1,
    disable_pruning: bool = False,
    disable_clustering: bool = True,
    cluster_polygon: str = "union",
    cluster_fraction: float = 1.0,
) -> tuple[list[Placement], float, float]:
    """..."""
    # ... (existing docstring lines) ...

    # Add this paragraph to the docstring, parallel to the existing cluster_polygon paragraph:
    #
    # `cluster_fraction`: float in (0.0, 1.0], default 1.0. Holds back the last
    # N - floor(N * fraction) copies of each group as singletons in the outer BLF
    # input, allowing them to potentially slot into cluster perimeter bays. When
    # the computed cluster size is < 2, the whole group passes through as
    # singletons. Out-of-range values raise ValueError from pre_cluster_pieces.
    # Has no effect when disable_clustering=True (the pre_cluster_pieces call is
    # skipped entirely). See PERFORMANCE.md § 4.5.

    if disable_clustering:
        blf_input = pieces
        clusters: list[Cluster] = []
    else:
        blf_input, clusters = pre_cluster_pieces(
            pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
            cluster_polygon=cluster_polygon,
            cluster_fraction=cluster_fraction,
        )

    # ... rest of function unchanged ...
```

The docstring text is inserted as a new paragraph after the existing `cluster_polygon` paragraph (around line 715). Place it before the bench-numbers paragraph that closes the docstring.

- [ ] **Step 4: Run the integration tests to verify they pass**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "cluster_fraction"`
Expected: 3 PASS.

- [ ] **Step 5: Run the FULL engine test suite to confirm no regression**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/ 2>&1 | Select-Object -Last 10`
Expected: 146 pass + 4 pre-existing failures (the test_dxf_parser.py fixture failures noted in MEMORY.md — unrelated). 130 was the prior baseline; +13 unit + +3 integration = 146.

- [ ] **Step 6: Commit (propose to user; do not run)**

Suggested:
```
git add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git commit -m "feat(engine): auto_layout_polygon forwards cluster_fraction to pre_cluster_pieces"
```

---

## Task 7: Extend bench — `union_f` mode, fraction sweep, new acceptance gate

**Files:**
- Modify: `engine/tests/bench_clustering.py` (`_run` signature + new mode branch; sweep block + new gate inserted after the existing effort=5 row)

- [ ] **Step 1: Add `cluster_fraction` kwarg + `union_f` mode to `_run`**

In `engine/tests/bench_clustering.py`, modify `_run`'s signature and mode handling:

```python
def _run(pieces, fabric_width_mm, grain_mode, effort, mode, cluster_fraction=1.0):
    """mode in {'off', 'bbox', 'union', 'union_f'}.
    'union_f' is the same as 'union' but passes cluster_fraction through."""
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
    t0 = time.perf_counter()
    placements, length, util = heuristic.auto_layout_polygon(**kwargs)
    return time.perf_counter() - t0, length, util
```

- [ ] **Step 2: Add the fraction-sweep block + new acceptance gate**

In `engine/tests/bench_clustering.py`, find the existing parallel-effort row (the `_bench` call with `effort=5` for sample_2.dxf, near the end of `if __name__ == "__main__":`). Immediately after the existing parallel gate (`gates.append(_gate("sample_2.dxf parallel: ...", ...))`), insert this sweep block. It runs only when sample_2.dxf was found.

Inside the existing `if dxf_path is None: ... else: ...` block, after the parallel-bench gate, add:

```python
        # Partial-cluster sweep (Task 6 of partial-clustering plan).
        # cluster_fraction in (0, 1]; 1.0 == current union behavior. Lower fractions
        # hold back leftover singletons for the outer BLF.
        print(f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi, effort=5, partial-cluster sweep")
        sweep_fractions = [1.0, 0.9, 0.8, 0.7, 0.5]
        sweep_results: list[tuple[float, float, float, float]] = []  # (f, length, util, time)
        for f in sweep_fractions:
            t, length, util = _run(pieces_real, 1651.0, "bi", 5, "union_f", cluster_fraction=f)
            print(f"  union f={f}:  L={length:8.1f}/U={util:5.2f}%/t={t*1000:8.1f}ms")
            sweep_results.append((f, length, util, t))

        best_f, best_l, _, _ = min(sweep_results, key=lambda r: r[1])
        print(f"  (off baseline:  L={off_p:8.1f} for comparison)")
        if best_l < off_p - 1e-6:
            print(f"  >> best partial fraction = {best_f} (L={best_l:.1f}) BEATS off baseline ({off_p:.1f}) — candidate for default flip")
        else:
            print(f"  >> best partial fraction = {best_f} (L={best_l:.1f}); off still wins ({off_p:.1f})")

        # New gate: regression check. union_f at fraction=1.0 must match same-run union mode
        # (mode='union' uses implicit cluster_fraction=1.0 — the new no-op leftover branch).
        union_f_at_1 = next(L for f, L, _u, _t in sweep_results if f == 1.0)
        gates.append(_gate(
            "partial-cluster fraction=1.0 matches union baseline (regression)",
            abs(union_f_at_1 - union_p) < 1e-6,
            f"union_f[1.0]={union_f_at_1:.6f} union[parallel]={union_p:.6f}",
        ))
```

(`off_p` and `union_p` are the local variables from the existing effort=5 parallel-bench call, both already in scope at this point in the file.)

- [ ] **Step 3: Update the bottom-of-bench "ACCEPTANCE" note**

In `engine/tests/bench_clustering.py`, in the success-print block at the end (the `if all(gates): print(...)` lines), update the note text to mention the sweep:

```python
    if all(gates):
        print(
            f"ACCEPTANCE: ALL {len(gates)} GATES PASSED — safe to ship.\n"
            f"NOTE: clustering remains OPT-IN (disable_clustering=True by default).\n"
            f"      Sweep above shows whether any cluster_fraction beats off=12249mm.\n"
            f"      If yes, file a follow-up PR to flip the default with the winning fraction.\n"
            f"      If no, the result is recorded in PERFORMANCE.md § 6 as a confirmed\n"
            f"      data point about the structural barrier."
        )
```

- [ ] **Step 4: Run the bench to verify gates + capture sweep output**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\bench_clustering.py 2>&1 | Tee-Object -FilePath partial_cluster_bench_output.txt`
Expected:
- Exit code 0.
- `ACCEPTANCE: ALL 6 GATES PASSED` (the existing 5 + the new regression gate).
- A new printed block "sample_2.dxf x 10 copies (190 pieces), bi, effort=5, partial-cluster sweep" with 5 lines of f-values, plus a `>> best partial fraction = X.X` summary line.

Capture the output (in `partial_cluster_bench_output.txt`) for Task 8's docs update.

- [ ] **Step 5: Commit (propose to user; do not run)**

Suggested:
```
git add engine/tests/bench_clustering.py
git commit -m "test(engine): bench_clustering — partial-cluster fraction sweep + regression gate"
```

(Do NOT commit `partial_cluster_bench_output.txt` — it's a working file consumed by Task 8 and not meant for the repo.)

---

## Task 8: Capture bench results into documentation

**Files:**
- Modify: `docs/planning/PERFORMANCE.md` (add § 4.5, update § 5.A item 1, add new § 6 dated entry)
- Modify: `docs/planning/BACKLOG.md` (update one bullet)
- Delete (after use): `partial_cluster_bench_output.txt` (Task 7's working file)

This is the only task whose content depends on Task 7's bench output. The exact marker-length numbers come from the captured `partial_cluster_bench_output.txt`. The doc updates have placeholders in *this plan* that the executing engineer fills in with the actual measured values.

- [ ] **Step 1: Read the captured bench output**

Read `partial_cluster_bench_output.txt` and extract:
- The 5 sweep rows (one per fraction): marker length, utilization, time.
- The "best partial fraction" line.
- Whether best beats `off=12249mm`.

- [ ] **Step 2: Add new § 4.5 to PERFORMANCE.md**

In `docs/planning/PERFORMANCE.md`, append a new subsection after the existing § 4.4 ("When to re-enable by default"). Insert before the `---` separator that closes § 4:

```markdown
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
- **Bench:** `engine/tests/bench_clustering.py` sweeps `[1.0, 0.9, 0.8, 0.7, 0.5]` on `sample_2.dxf × 10` at `effort=5`. Best fraction reported in § 6's [DATE] entry below.
```

- [ ] **Step 3: Update § 5.A item 1 in PERFORMANCE.md**

Find the existing § 5.A first bullet (around line 223 in PERFORMANCE.md):

```markdown
- [ ] **Partial clustering (`cluster_fraction < 1.0`).** Cluster only N-k of
  each group's copies; leave k as singletons. The k singletons can slot
  into cluster bays. Trade-off: smaller cluster vs more singletons in outer
  BLF. Easiest of the three; add as a `cluster_fraction: float = 1.0` knob
  on `pack_cluster_union`. **Low-medium effort.**
```

Replace with (one of two options based on bench result — pick the one matching Task 8 Step 1's finding):

**If the best fraction BEAT off=12249mm:**
```markdown
- [x] **Partial clustering (`cluster_fraction < 1.0`).** Shipped opt-in; see § 4.5. Best fraction `X.X` on `sample_2.dxf × 10` produces `LLLL.Lmm` (beats off=12249mm). Follow-up PR will flip `disable_clustering=False` default with `cluster_fraction=X.X`.
```

**If no fraction beat off=12249mm:**
```markdown
- [x] **Partial clustering (`cluster_fraction < 1.0`).** Shipped opt-in; see § 4.5. Bench sweep on `sample_2.dxf × 10` confirms no fraction beats off=12249mm — structural barrier holds. Filed for posterity in § 6 [DATE] entry.
```

Fill in `X.X`, `LLLL.L`, and `[DATE]` from Task 8 Step 1's findings.

- [ ] **Step 4: Add new § 6 dated entry to PERFORMANCE.md**

At the bottom of PERFORMANCE.md (after the existing `### 2026-05-26 — Union clusters don't beat unclustered BLF...` entry), append:

```markdown
### YYYY-MM-DD — Partial clustering shipped opt-in

- **What:** Added `cluster_fraction: float = 1.0` knob to `pre_cluster_pieces` (and forwarded through `auto_layout_polygon`). Per-group split: `k = floor(N * cluster_fraction)` copies cluster; remaining `N - k` join outer BLF as singletons. Min-cluster promotion: `k < 2` → whole group becomes singletons.
- **Why:** The 2026-05-26 § 6 entry's structural finding ("on `sample_2.dxf × 10`, every base id has 10 copies → no singletons left to fill cluster bays") implies that holding back some copies as singletons might let the outer BLF interleave them into the cluster perimeter bays.
- **Result:** Bench sweep on `sample_2.dxf × 10` at fabric=1651mm bi-grain, effort=5:

  | `cluster_fraction` | Marker length (mm) | Utilization | Time (ms) |
  |---|---|---|---|
  | 1.0 (= existing union baseline) | LLLLL | UU.UU% | TTTT |
  | 0.9 | LLLLL | UU.UU% | TTTT |
  | 0.8 | LLLLL | UU.UU% | TTTT |
  | 0.7 | LLLLL | UU.UU% | TTTT |
  | 0.5 | LLLLL | UU.UU% | TTTT |

  Best fraction: `X.X` at `LLLLLmm`. `off` baseline (unclustered) = 12249mm.

- **Decision:**
  - **If best beats off:** filed follow-up to flip `disable_clustering=False` default with `cluster_fraction=X.X`.
  - **If no fraction beats off:** structural barrier confirmed at all tested fractions. The knob remains opt-in. Future workloads with mixed copy counts (some base ids with copies, some without — exposing real singletons) may still benefit.
- **Mechanism preserved at:** `engine/core/layout/clustering.py::pre_cluster_pieces` (split logic) + `engine/core/layout/heuristic.py::auto_layout_polygon` (parameter forwarding). Opt-in instructions in § 4.5.
```

Replace `YYYY-MM-DD` with today's date. Replace each `LLLLL` / `UU.UU` / `TTTT` with the actual numbers from the bench output (Task 8 Step 1). Replace `X.X` with the best fraction. Keep only the relevant branch of the **Decision** bullet (delete the other "If" branch).

- [ ] **Step 5: Update BACKLOG.md bullet**

In `docs/planning/BACKLOG.md`, find the bullet (around line 170) under `### Phase 6 follow-ups — algorithm performance`:

```markdown
- [ ] Algorithm follow-ups (clustering structural-barrier + general wins + pruning meta-improvements). Ranked list in PERFORMANCE.md § 5.
```

Replace with:

```markdown
- [~] Algorithm follow-ups — partial clustering (`cluster_fraction` knob) shipped opt-in; remaining items in PERFORMANCE.md § 5.
```

- [ ] **Step 6: Delete the working bench-output file**

Run: `Remove-Item partial_cluster_bench_output.txt`
(Or skip if the executing harness places it elsewhere — the file is a working artifact, not for the repo.)

- [ ] **Step 7: Verify the docs render cleanly**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/ 2>&1 | Select-Object -Last 5`
Expected: 146 pass + 4 pre-existing. (Re-run as a final sanity check before the docs commit.)

- [ ] **Step 8: Commit (propose to user; do not run)**

Suggested:
```
git add docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git commit -m "docs: PERFORMANCE.md § 4.5 + § 6 entry — partial clustering bench results"
```

---

## Task 9: Final verification

**Files:** None modified.

- [ ] **Step 1: Run the full engine test suite**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/ 2>&1 | Select-Object -Last 10`
Expected: 146 passed + 4 pre-existing failures unrelated to this work.

- [ ] **Step 2: Re-run the bench**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\bench_clustering.py 2>&1 | Select-Object -Last 30`
Expected: Exit 0, "ACCEPTANCE: ALL 6 GATES PASSED", sweep block prints 5 fractions + best summary.

- [ ] **Step 3: Verify the spec's acceptance criteria are met**

Cross-check against `docs/superpowers/specs/2026-05-30-partial-clustering-design.md` § 8 ("Acceptance criteria for merging this PR"):

| Criterion | Status |
|---|---|
| 16 new tests pass (13 unit + 3 integration) | Verified in Task 5 Step 3 + Task 6 Step 5 |
| 130 existing engine tests still pass | Verified in Task 6 Step 5 (146 total: 130 prior + 16 new) |
| Bench exits 0 with all 6 gates green | Verified in Task 7 Step 4 + Task 9 Step 2 |
| Bench sweep output captured in PERFORMANCE.md § 6 | Verified in Task 8 Step 4 |
| 4 pre-existing `test_dxf_parser.py` failures unchanged | Verified in Task 6 Step 5 |

If any row is not Verified, return to that task. Otherwise, the PR is ready.

- [ ] **Step 4: Summarize the changeset for the user**

Print a brief summary (no code action needed). The user reviews and decides whether to push / open PR. Format:

```
Partial clustering implementation complete.

Files changed:
  engine/core/layout/clustering.py       (+25 / -8)
  engine/core/layout/heuristic.py        (+10 / -2)
  engine/tests/unit/test_clustering.py   (+135 / 0)
  engine/tests/unit/test_heuristic.py    (+50 / 0)
  engine/tests/bench_clustering.py       (+45 / -5)
  docs/planning/PERFORMANCE.md           (+50 / -5)
  docs/planning/BACKLOG.md               (+1 / -1)

Tests: 146 passing (130 prior + 13 new unit + 3 new integration).
Bench: 6/6 acceptance gates green. Best partial fraction = X.X (LLLLLmm).

Suggested commit messages (per CLAUDE.md commit rule):
  - feat(engine): add cluster_fraction param to pre_cluster_pieces (validation only)
  - feat(engine): pre_cluster_pieces honors cluster_fraction with first-k split + min-cluster promotion
  - test(engine): partial-cluster heterogeneous-group regression guard
  - test(engine): partial-cluster falls back to singletons on pack failure
  - test(engine): partial-cluster knob applies to bbox path too
  - feat(engine): auto_layout_polygon forwards cluster_fraction to pre_cluster_pieces
  - test(engine): bench_clustering — partial-cluster fraction sweep + regression gate
  - docs: PERFORMANCE.md § 4.5 + § 6 entry — partial clustering bench results
```

(The "+X / -Y" line counts are illustrative — the executing engineer fills in actuals.)

---

## Notes for the executing engineer

- **All Bash/PowerShell commands use absolute Windows paths.** The Python interpreter is at `D:\openmarker\engine\.venv\Scripts\python.exe`. Pytest invocations use POSIX-style forward slashes in the test path arg (pytest handles this fine on Windows).
- **The bench is slow.** Each `sample_2.dxf` row at effort=5 takes ~12s; the 5-fraction sweep adds ~50s. The full bench should complete in under 2 minutes.
- **Test file ordering matters.** Place new tests *after* the existing ones in each file (no inserting in the middle of an existing group), so future readers can scan chronologically.
- **The bench gate uses `union_p`**, which is the local variable from the `_bench` call at effort=5. It's the marker length from the parallel `union` mode run in the line immediately preceding the sweep block. Don't accidentally compare against the serial `union_s` instead — that would still pass (parallel == serial determinism is already a separate gate), but it's not what the spec specified.
- **If a bench-only test discovers a real regression** (e.g., `union_f[fraction=1.0] != union[parallel]` by more than `1e-6`), DO NOT relax the gate — that would mean the new code path is not bit-identical at the default fraction, which contradicts the spec's central guarantee. Stop and investigate; the bug is likely in Task 2 Step 3 (the loop body replacement).
