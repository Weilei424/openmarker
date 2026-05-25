# BLF Branch Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `auto_layout_polygon` skip strategy runs that cannot beat the current best marker length. Strictly faster, identical results.

**Architecture:** Thread a `best_marker_so_far: float | None` parameter into `_blf_pack_nfp`. After each piece is placed, compare a running `current_max_bottom + EDGE_GAP` against the cutoff. When the partial value meets or exceeds the cutoff, raise an internal `_PrunedRun` exception. The serial loop in `auto_layout_polygon` catches it and moves on. Bi-mode pruning falls out automatically — the same `best` accumulator already spans `mode × strategy` iterations.

**Scope:** Serial path only. Parallel path (`effort > 1`) is unchanged in this PR — workers don't share `best_so_far`, and the IPC needed to share it would dominate the savings on the input sizes where parallel mode is enabled.

**Why pruning is safe (monotone bound):** BLF places pieces sequentially to the lowest-left valid position. The marker length after `k` placements is `max(y + height) + EDGE_GAP` and is non-decreasing in `k`: adding more pieces can only push the bottom edge down, never up. So the partial value is a lower bound on the final value. If it already meets/exceeds the best complete result, this run cannot improve on it.

**Tech Stack:** Python 3.11, pytest. Code touches `engine/core/layout/heuristic.py` and tests; no API, frontend, or schema changes.

---

### Task 1: Add `_PrunedRun` exception + `best_marker_so_far` parameter to `_blf_pack_nfp`

**Files:**
- Modify: `engine/core/layout/heuristic.py` (`_blf_pack_nfp` signature + per-iteration check; new `_PrunedRun` class near top of file)
- Test: `engine/tests/unit/test_heuristic.py` (new tests appended)

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/unit/test_heuristic.py`:

```python
# --- branch pruning tests ---

def test_blf_default_no_pruning_behavior_unchanged():
    """Without best_marker_so_far, _blf_pack_nfp behaves exactly as before."""
    from core.layout.heuristic import _blf_pack_nfp
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    placements, length, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0
    )
    assert len(placements) == 3
    assert length > 0


def test_blf_high_cutoff_runs_to_completion():
    """A cutoff above any plausible result should not trigger pruning."""
    from core.layout.heuristic import _blf_pack_nfp
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    placements, length, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        best_marker_so_far=1e9,
    )
    assert len(placements) == 3
    assert length > 0


def test_blf_tight_cutoff_raises_pruned_run():
    """A cutoff at zero must trigger _PrunedRun before completion."""
    from core.layout.heuristic import _blf_pack_nfp, _PrunedRun
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    with pytest.raises(_PrunedRun):
        _blf_pack_nfp(
            pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
            best_marker_so_far=0.0,
        )


def test_blf_cutoff_just_above_optimal_does_not_prune():
    """A cutoff strictly larger than the actual final marker length should
    allow the run to finish. Run once to learn the length, then run again
    with cutoff = length + 1 mm."""
    from core.layout.heuristic import _blf_pack_nfp
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    _, length, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0
    )
    placements2, length2, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        best_marker_so_far=length + 1.0,
    )
    assert len(placements2) == 3
    assert abs(length2 - length) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail with the expected errors**

Run: `engine\.venv\Scripts\pytest engine\tests\unit\test_heuristic.py -v -k "blf_default or high_cutoff or tight_cutoff or just_above_optimal"`

Expected:
- `test_blf_default_no_pruning_behavior_unchanged`: PASS
- The other three: FAIL with `TypeError: _blf_pack_nfp() got an unexpected keyword argument 'best_marker_so_far'` (or `ImportError` on `_PrunedRun` for the third)

This confirms the signature + class don't exist yet.

- [ ] **Step 3: Add `_PrunedRun` and the parameter**

Edit `engine/core/layout/heuristic.py`. Add this class definition just below the existing `Placement` dataclass (around line 81):

```python
class _PrunedRun(Exception):
    """Internal: raised by `_blf_pack_nfp` when its partial marker length
    already meets or exceeds `best_marker_so_far`. The serial caller in
    `auto_layout_polygon` catches this and skips to the next strategy.

    The check is sound because BLF's partial marker length is monotone
    non-decreasing in the number of placed pieces — placing more can only
    push the bottom edge further down, never bring it up.
    """
```

Then update `_blf_pack_nfp`'s signature:

```python
def _blf_pack_nfp(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    sort_key=None,
    nfp_cache: NfpCache | None = None,
    best_marker_so_far: float | None = None,
) -> tuple[list[Placement], float, float]:
```

Add a running `current_max_bottom` next to the existing `placements` / `placed` declarations near the top of the function:

```python
    placements: list[Placement] = []
    placed: list[_Placed] = []
    current_max_bottom: float = 0.0
```

And add the per-placement update + check at the very end of the `for piece in sorted_pieces:` loop (after `placed.append(_Placed(...))`):

```python
        # Branch pruning. `candidate_poly.bounds[3]` is the bottom edge of the
        # bbox in screen-y-down coords (= top + height because _placed_polygon
        # aligns minx/miny to the requested top-left). Partial marker length is
        # monotone non-decreasing — once it meets the cutoff, this run cannot win.
        if candidate_poly.bounds[3] > current_max_bottom:
            current_max_bottom = candidate_poly.bounds[3]
        if best_marker_so_far is not None and current_max_bottom + EDGE_GAP >= best_marker_so_far:
            raise _PrunedRun()
```

No `piece_map_local` is needed — the running max avoids the O(N²) re-scan.

- [ ] **Step 4: Run the new tests + the full heuristic suite to verify**

Run: `engine\.venv\Scripts\pytest engine\tests\unit\test_heuristic.py -v`

Expected: all tests PASS (the four new ones plus all existing).

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git commit -m "perf(engine): _blf_pack_nfp accepts best_marker_so_far cutoff for branch pruning"
```

---

### Task 2: Wire the cutoff through `auto_layout_polygon` serial path

**Files:**
- Modify: `engine/core/layout/heuristic.py` (serial branch of `auto_layout_polygon`)
- Test: `engine/tests/unit/test_heuristic.py` (regression: same result with pruning on)

- [ ] **Step 1: Write the regression test**

Append to `engine/tests/unit/test_heuristic.py`:

```python
def test_auto_layout_serial_pruning_gives_same_result():
    """Pruning must not change the chosen layout. The serial path always
    has pruning on after this PR; this test pins identical output across
    two consecutive runs on a deterministic input."""
    pieces = [_make_rect(f"p{i}", 80 + i * 10, 120) for i in range(5)]
    a_placements, a_length, a_util = auto_layout_polygon(
        pieces, fabric_width_mm=600, grain_mode="single", fabric_grain_deg=0.0, effort=1
    )
    b_placements, b_length, b_util = auto_layout_polygon(
        pieces, fabric_width_mm=600, grain_mode="single", fabric_grain_deg=0.0, effort=1
    )
    assert a_length == b_length
    assert a_util == b_util
    assert len(a_placements) == len(b_placements)
    for pa, pb in zip(a_placements, b_placements):
        assert pa.piece_id == pb.piece_id
        assert abs(pa.x - pb.x) < 1e-6
        assert abs(pa.y - pb.y) < 1e-6
        assert pa.rotation_deg == pb.rotation_deg
```

(Two identical calls — this pins determinism so the next step's edit can't silently reorder placements.)

- [ ] **Step 2: Run to verify the baseline is stable**

Run: `engine\.venv\Scripts\pytest engine\tests\unit\test_heuristic.py::test_auto_layout_serial_pruning_gives_same_result -v`

Expected: PASS.

- [ ] **Step 3: Wire the cutoff into the serial loop**

In `engine/core/layout/heuristic.py`, locate the serial branch of `auto_layout_polygon` (the `if not use_pool:` block). Replace the inner loop body so each `_blf_pack_nfp` call receives `best_marker_so_far = best[1] if best else None` and `_PrunedRun` is caught:

```python
    if not use_pool:
        shared_cache: NfpCache = {}
        best: tuple[list[Placement], float, float] | None = None
        for mode in modes:
            for sort_index in range(len(_SORT_STRATEGIES)):
                cache = {} if disable_nfp_cache else shared_cache
                try:
                    result = _blf_pack_nfp(
                        pieces, fabric_width_mm, mode, fabric_grain_deg,
                        sort_key=_SORT_STRATEGIES[sort_index],
                        nfp_cache=cache,
                        best_marker_so_far=best[1] if best is not None else None,
                    )
                except _PrunedRun:
                    continue
                best = _shorter(best, result)
        assert best is not None
        return best
```

- [ ] **Step 4: Run the full engine test suite**

Run: `engine\.venv\Scripts\pytest engine\tests\ -v`

Expected: every test passes — 82 + the 5 new ones = 87.

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git commit -m "perf(engine): serial auto-layout prunes strategies that can't beat current best"
```

---

### Task 3: Benchmark script

**Files:**
- Create: `engine/tests/bench_branch_pruning.py`

- [ ] **Step 1: Write the benchmark**

Create `engine/tests/bench_branch_pruning.py`. The script monkey-patches `_blf_pack_nfp` to ignore `best_marker_so_far` for the "off" baseline so we can A/B compare on identical input. It includes a real-workload scenario backed by `examples/input/sample_2.dxf` (19 pieces × 10 copies — same workload used in the commercial vs OpenMarker comparison) and skips it gracefully if the DXF isn't present (it's git-ignored).

```python
"""Manual benchmark for the BLF branch-pruning change. Not part of pytest.

Run from the worktree root with:
    engine\\.venv\\Scripts\\python engine\\tests\\bench_branch_pruning.py

Prints (pruning-on, pruning-off, speedup) for a few representative inputs.
The real-workload row uses examples/input/sample_2.dxf if available — the
same fixture compared against commercial nesting software (~7pp utilization
gap on the 10-copies workload). Synthetic rows still run if the DXF is
missing.
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
    """Walk up from this script looking for examples/input/<filename>.
    Returns absolute path or None if not found. The file is git-ignored,
    so it only exists in the user's main repo, not in worktree copies."""
    here = os.path.abspath(HERE)
    for _ in range(8):  # generous depth limit
        candidate = os.path.join(here, "examples", "input", filename)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent
    return None


def _load_dxf_pieces(path: str, copies: int) -> list[Piece]:
    """Parse + normalize a DXF the same way the /import-dxf endpoint does,
    then expand each piece to `copies` instances (id suffix __c{n})."""
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
    for p in base_pieces:
        for c in range(copies):
            expanded.append(dataclasses.replace(p, id=f"{p.id}__c{c}"))
    return expanded


def _run(pieces, fabric_width_mm, grain_mode):
    t0 = time.perf_counter()
    result = heuristic.auto_layout_polygon(
        pieces, fabric_width_mm=fabric_width_mm,
        grain_mode=grain_mode, fabric_grain_deg=0.0, effort=1,
    )
    return time.perf_counter() - t0, result[1]  # (seconds, marker_length)


def _bench(name: str, pieces, fabric_width_mm: float, grain_mode: str = "single") -> None:
    on_t, on_len = _run(pieces, fabric_width_mm, grain_mode)

    original = heuristic._blf_pack_nfp
    def no_prune(*args, **kwargs):
        kwargs.pop("best_marker_so_far", None)
        return original(*args, **kwargs)
    heuristic._blf_pack_nfp = no_prune
    try:
        off_t, off_len = _run(pieces, fabric_width_mm, grain_mode)
    finally:
        heuristic._blf_pack_nfp = original

    speedup = off_t / on_t if on_t > 0 else float("inf")
    same = "same" if abs(on_len - off_len) < 1e-6 else f"DIFFER on={on_len:.2f} off={off_len:.2f}"
    print(f"{name:50s} on={on_t*1000:8.1f}ms  off={off_t*1000:8.1f}ms  speedup={speedup:5.2f}x  result={same}")


if __name__ == "__main__":
    # Many small same-size rects on a narrow strip — sort strategies should
    # diverge in quality, so pruning has real wins.
    pieces_small = [_piece(f"s{i}", 80, 60) for i in range(20)]
    _bench("20 small rects (80x60), fabric=300", pieces_small, 300.0)

    # Mixed sizes — area, max-dim, height, width sorts produce different orders.
    pieces_mixed = [_piece(f"m{i}", 100 + i * 20, 80 + (i % 3) * 40) for i in range(8)]
    _bench("8 mixed rects, fabric=400", pieces_mixed, 400.0)

    # Bi mode — exercises both `bi` and the `single` fallback. Single should
    # prune early once bi establishes a tight cutoff (or vice versa).
    pieces_bi = [_piece(f"b{i}", 100, 200 if i % 2 else 80, grainline=0.0) for i in range(8)]
    _bench("8 mixed rects, bi grain, fabric=400", pieces_bi, 400.0, "bi")

    # Real workload: same fixture as the commercial-vs-ours comparison.
    dxf_path = _find_sample_dxf("sample_2.dxf")
    if dxf_path is None:
        print("[skipped] sample_2.dxf not found — place it in examples/input/ to enable the real-workload bench")
    else:
        pieces_real = _load_dxf_pieces(dxf_path, copies=10)
        _bench(f"sample_2.dxf × 10 copies ({len(pieces_real)} pieces), fabric=1500, bi", pieces_real, 1500.0, "bi")
```

- [ ] **Step 2: Run it and capture the numbers**

Run: `engine\.venv\Scripts\python engine\tests\bench_branch_pruning.py`

Expected output: three synthetic lines plus (if `sample_2.dxf` is in the user's main repo) one real-workload line. Each line shows `on`, `off`, `speedup`, `result=same`. Speedup should be ≥ 1.0x on every line and noticeably greater than 1.0 on at least one. If `result=DIFFER` on any line, **stop and investigate** — pruning has introduced a bug.

Record the numbers in the commit message for future reference.

- [ ] **Step 3: Commit**

```bash
git add engine/tests/bench_branch_pruning.py
git commit -m "$(cat <<'EOF'
test(engine): bench script for BLF branch-pruning speedup

Numbers from local run (Windows, single-threaded, effort=1):
  <paste the bench output lines here (3 synthetic + sample_2.dxf if present)>
EOF
)"
```

---

### Task 4: Docs

**Files:**
- Modify: `CLAUDE.md` (engine architecture section)
- Modify: `docs/planning/BACKLOG.md` (add a Phase 6 follow-ups section)

- [ ] **Step 1: Update `CLAUDE.md`**

In `CLAUDE.md`, locate the description of `core/layout/heuristic.py` (under "### Engine (`engine/`)"). After the existing line ending with "4 sort strategies tried; best wins." append:

```
Serial path (effort=1) prunes strategies whose partial marker length already
meets/exceeds the best complete result so far — sound because BLF's partial
marker length is monotone non-decreasing in the number of placed pieces.
Parallel path (effort>1) does not prune; workers don't share state.
```

- [ ] **Step 2: Update `docs/planning/BACKLOG.md`**

Add a new section between the existing "Phase 6 — Fixes, performance, and UI improvements" and "Phase 7 — Export":

```markdown
### Phase 6 follow-ups — algorithm performance

- [x] Engine: branch pruning in serial `auto_layout_polygon` — abort strategies whose partial marker length already meets/exceeds the best complete result. Monotone-bound argument: BLF's partial marker length is non-decreasing in the number of placed pieces.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/planning/BACKLOG.md
git commit -m "docs: branch pruning in CLAUDE.md engine notes and BACKLOG follow-ups"
```

---

## Out of scope for this PR

- **Parallel-path pruning** — needs a shared cutoff via `multiprocessing.Value` or a tournament-staging scheme. Defer until benchmarks show whether it's worth the IPC cost on real workloads.
- **Smart strategy ordering** — running the historically-best sort first would tighten the cutoff sooner. Possible follow-up after we collect telemetry on which sort wins most often.
- **Cutoff slack** — accepting runs within `epsilon` of best (e.g., to keep diverse "almost as good" results for future tab restoration). Not needed today.
