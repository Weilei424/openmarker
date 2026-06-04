# Bench Grain Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the fabric grain to a single 90° constant, stop the API from accepting a variable grain direction, and fix the benchmark + PERFORMANCE.md so they measure the real (90°) configuration — closing the documented 550mm bench-vs-GUI gap with no algorithm change.

**Architecture:** Add one named constant `FABRIC_GRAIN_DEG = 90.0` in `engine/core/layout/grain.py` as the single source of truth. The API (`main.py`) imports it and always passes it to `auto_layout_polygon`, ignoring any `grain_direction_deg` in the request. The engine's `fabric_grain_deg` parameter and all grain logic stay intact (capability retained, not externally driven). All benches reference the constant. PERFORMANCE.md is corrected and the SA tables annotated as superseded.

**Tech Stack:** Python 3.11, FastAPI, pytest + pytest-asyncio + httpx ASGITransport, Shapely/pyclipper.

**Spec:** `docs/superpowers/specs/2026-06-04-bench-grain-fix-design.md`

---

## Environment & conventions (read before any step)

- **Worktree root:** `D:\openmarker\.worktrees\perf-followups` (branch `feat/bench-grain-fix`). All edits and commits happen here.
- **Shared venv (absolute path — the worktree has no `.venv`):** `D:\openmarker\engine\.venv\Scripts\python.exe`. Always invoke it by absolute path; `engine/.venv/...` relative to the worktree does **not** exist.
- **Run tests against worktree code:**
  `D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/<path> -v`
  (test files do their own `sys.path.insert` from `__file__`, so they import the worktree's `api`/`core`.)
- **Run a bench against worktree code:**
  `D:/openmarker/engine/.venv/Scripts/python.exe D:/openmarker/.worktrees/perf-followups/engine/tests/<bench>.py`
- **`sample_2.dxf` is git-ignored** and lives only in the main tree at `D:\openmarker\examples\input\sample_2.dxf`. The benches' `_find_sample_dxf` walks up ≤8 levels and reaches it from the worktree. **Verify** each bench prints the `sample_2.dxf x 10` row and does **not** print `[skipped] sample_2.dxf not found`. If it skips, copy the file into the worktree (`cp D:/openmarker/examples/input/sample_2.dxf D:/openmarker/.worktrees/perf-followups/examples/input/`) — it stays git-ignored.
- **Git:** run from the worktree, e.g. `git -C D:/openmarker/.worktrees/perf-followups ...`.
- **Commit messages:** one concise line per changed file in the commit body (user convention). End every commit message with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.
- **Do NOT push** — the user must approve pushing.

## File structure

| File | Change | Responsibility |
| --- | --- | --- |
| `engine/core/layout/grain.py` | Modify | Add `FABRIC_GRAIN_DEG = 90.0` — single source of truth for the locked grain. |
| `engine/api/main.py` | Modify | Stop reading `grain_direction_deg`; always pass `FABRIC_GRAIN_DEG`. |
| `engine/tests/integration/test_api_cache.py` | Modify | New test proving the API ignores `grain_direction_deg`. |
| `engine/tests/bench_clustering.py` | Modify | Use the constant; refresh stale `12249` comments. |
| `engine/tests/bench_branch_pruning.py` | Modify | Use the constant. |
| `engine/tests/bench_sa.py` | Modify | Use the constant (two call sites). |
| `engine/tests/bench_nfp_cache.py` | Modify | Route its hardcoded `90.0` through the constant (behavior-neutral). |
| `docs/planning/PERFORMANCE.md` | Modify | Correct § 0/§ 1/§ 5.C; add § 6 entry; annotate SA tables. |
| `docs/planning/BACKLOG.md` | Modify | One-line progress entry under "Phase 6 follow-ups — algorithm performance". |

---

## Task 1: Lock grain to a constant + disable API direction input (TDD)

**Files:**
- Modify: `engine/core/layout/grain.py`
- Modify: `engine/api/main.py` (drop read at `:129`, call site at `:203`, docstring at `:100`)
- Test: `engine/tests/integration/test_api_cache.py`

- [ ] **Step 1: Write the failing test**

Append to the end of `engine/tests/integration/test_api_cache.py`:

```python
def _grained_rect(piece_id: str = "g0", w: float = 400.0, h: float = 100.0,
                  grainline: float = 0.0) -> dict:
    """A 4:1 rectangle WITH a grainline. Unlike _square_piece (grainline=None →
    cardinal rotations regardless of grain), this piece reorients with
    fabric_grain_deg, so it detects whether the API honors or ignores
    grain_direction_deg."""
    return {
        "id": piece_id,
        "name": piece_id,
        "polygon": [[0, 0], [w, 0], [w, h], [0, h]],
        "area": w * h,
        "bbox": {"min_x": 0, "min_y": 0, "max_x": w, "max_y": h,
                 "width": w, "height": h},
        "is_valid": True,
        "validation_notes": [],
        "grainline_direction_deg": grainline,
    }


@pytest.mark.asyncio
async def test_auto_layout_ignores_grain_direction_deg():
    """Grain is locked at FABRIC_GRAIN_DEG (90°); the request field is ignored.

    A 400x100 piece with a 0° grainline in single mode orients to its long side
    at fabric_grain=0 (rotation 0 → height 100) but to its short side at
    fabric_grain=90 (rotation 90 → height 400). If the API honored
    grain_direction_deg the two marker lengths would differ; locked at 90 they
    must be identical."""
    base = {
        "pieces": [_grained_rect()],
        "fabric_width_mm": 1500,
        "grain_mode": "single",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Distinct filenames so cache dedup doesn't return the first result.
        r0 = await client.post("/auto-layout", json={
            **base, "filename": "grain0.dxf", "grain_direction_deg": 0})
        r90 = await client.post("/auto-layout", json={
            **base, "filename": "grain90.dxf", "grain_direction_deg": 90})
    assert r0.status_code == 200
    assert r90.status_code == 200
    assert r0.json()["marker_length_mm"] == r90.json()["marker_length_mm"]
```

- [ ] **Step 2: Run the test to verify it FAILS**

Run:
```
D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/integration/test_api_cache.py::test_auto_layout_ignores_grain_direction_deg -v
```
Expected: **FAIL** — `AssertionError` comparing two different `marker_length_mm` (≈ small vs ≈ large), because the current API honors `grain_direction_deg`.

- [ ] **Step 3: Add the constant to `grain.py`**

In `engine/core/layout/grain.py`, immediately after `from __future__ import annotations` (line 1) and before `def allowed_rotations(`, insert:

```python


# Fabric grain is fixed at 90°: the grain (warp) runs along the fabric roll
# length — the +Y axis BLF minimizes as marker length — matching standard
# cutting-room markers. Single source of truth for the locked value; the
# frontend mirrors it (frontend/src/app/App.tsx). The engine still accepts an
# arbitrary `fabric_grain_deg` for internal/test flexibility, but all production
# callers (API, benches) use this constant. See docs/planning/PERFORMANCE.md §5.C.
FABRIC_GRAIN_DEG = 90.0
```

- [ ] **Step 4: Wire the constant into the API and drop the variable read**

In `engine/api/main.py`:

4a. Add the import after the existing heuristic import (line 26 `from core.layout.heuristic import auto_layout_polygon`):
```python
from core.layout.grain import FABRIC_GRAIN_DEG
```

4b. Update the docstring request-example line (currently `        "grain_direction_deg": 0,`):
```python
        "grain_direction_deg": 0,   // IGNORED — grain is locked at 90° (FABRIC_GRAIN_DEG)
```

4c. Delete the variable read (currently line 129):
```python
    grain_direction_deg = float(body.get("grain_direction_deg", 0.0))
```
(Remove the entire line. `grain_direction_deg` is referenced nowhere else once Step 4d lands.)

4d. In `_do_layout`, change the 4th positional argument from `grain_direction_deg` to the constant:
```python
    def _do_layout():
        return auto_layout_polygon(
            pieces, fabric_width_mm, grain_mode, FABRIC_GRAIN_DEG,
            disable_nfp_cache=disable_nfp_cache,
            effort=effort,
        )
```

- [ ] **Step 5: Run the new test + the full integration & grain suites to verify GREEN**

Run:
```
D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/integration -v
D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/unit/test_grain.py -v
```
Expected: **PASS** — `test_auto_layout_ignores_grain_direction_deg` passes; all existing integration tests still pass (they send `grain_direction_deg: 90`, which now matches the locked value); `test_grain.py` unchanged and green.

- [ ] **Step 6: Commit**

```
git -C D:/openmarker/.worktrees/perf-followups add engine/core/layout/grain.py engine/api/main.py engine/tests/integration/test_api_cache.py
git -C D:/openmarker/.worktrees/perf-followups commit -m "feat(engine): lock fabric grain to 90°, disable API direction input

- core/layout/grain.py: add FABRIC_GRAIN_DEG = 90.0 single-source constant
- api/main.py: ignore grain_direction_deg; always lay out at FABRIC_GRAIN_DEG
- tests/integration/test_api_cache.py: assert API ignores grain_direction_deg

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Point all benches at the constant

**Files:** `bench_clustering.py`, `bench_branch_pruning.py`, `bench_sa.py`, `bench_nfp_cache.py` (all under `engine/tests/`).

- [ ] **Step 1: `bench_clustering.py`**

1a. After line 42 (`from core.layout import heuristic`) add:
```python
from core.layout.grain import FABRIC_GRAIN_DEG
```
1b. Line 93 — change `fabric_grain_deg=0.0` to the constant:
```python
        grain_mode=grain_mode, fabric_grain_deg=FABRIC_GRAIN_DEG, effort=effort,
```
1c. Refresh stale `12249` references (now ≈11699 at the locked grain). In the module docstring gate list, change:
```
  - sample_2.dxf x 10:  union.marker <= bbox.marker + 1e-6  (RELAXED from "beats off":
                        the headline gate cannot beat off=12249mm because all 19 base
```
to:
```
  - sample_2.dxf x 10:  union.marker <= bbox.marker + 1e-6  (RELAXED from "beats off":
                        the headline gate cannot beat off (~11699mm at the locked 90°
                        grain) because all 19 base
```
And in the final acceptance print block, change the line:
```python
            f"      Sweep above shows whether any cluster_fraction beats off=12249mm.\n"
```
to:
```python
            f"      Sweep above shows whether any cluster_fraction beats off (~11699mm).\n"
```

- [ ] **Step 2: `bench_branch_pruning.py`**

2a. After line 24 (`from core.layout import heuristic`) add:
```python
from core.layout.grain import FABRIC_GRAIN_DEG
```
2b. Line 80 — change `fabric_grain_deg=0.0` to the constant:
```python
        grain_mode=grain_mode, fabric_grain_deg=FABRIC_GRAIN_DEG, effort=effort,
```

- [ ] **Step 3: `bench_sa.py`**

3a. After line 32 (`from core.layout.heuristic import auto_layout_polygon`) add:
```python
from core.layout.grain import FABRIC_GRAIN_DEG
```
3b. Line 79 — change the 4th positional `0.0` to the constant:
```python
        pieces, FABRIC_WIDTH_MM, GRAIN_MODE, FABRIC_GRAIN_DEG, effort=EFFORT, **kwargs,
```
3c. Line 126 — same change in the default run:
```python
        pieces, FABRIC_WIDTH_MM, GRAIN_MODE, FABRIC_GRAIN_DEG, effort=EFFORT,
```

- [ ] **Step 4: `bench_nfp_cache.py`** (behavior-neutral: it already uses 90.0)

4a. After line 20 (`from core.layout import heuristic`) add:
```python
from core.layout.grain import FABRIC_GRAIN_DEG
```
4b. Line 84 — replace literal `90.0`:
```python
    heuristic.auto_layout_polygon(pieces, fabric, grain, FABRIC_GRAIN_DEG)
```
4c. Line 95 — replace literal `90.0`:
```python
        heuristic.auto_layout_polygon(pieces, fabric, grain, FABRIC_GRAIN_DEG)
```

- [ ] **Step 5: Syntax-check all four benches**

Run:
```
D:/openmarker/engine/.venv/Scripts/python.exe -m py_compile D:/openmarker/.worktrees/perf-followups/engine/tests/bench_clustering.py D:/openmarker/.worktrees/perf-followups/engine/tests/bench_branch_pruning.py D:/openmarker/.worktrees/perf-followups/engine/tests/bench_sa.py D:/openmarker/.worktrees/perf-followups/engine/tests/bench_nfp_cache.py
```
Expected: no output, exit code 0 (all compile).

- [ ] **Step 6: Commit**

```
git -C D:/openmarker/.worktrees/perf-followups add engine/tests/bench_clustering.py engine/tests/bench_branch_pruning.py engine/tests/bench_sa.py engine/tests/bench_nfp_cache.py
git -C D:/openmarker/.worktrees/perf-followups commit -m "test(bench): use FABRIC_GRAIN_DEG constant for the locked 90° grain

- tests/bench_clustering.py: grain 0.0 -> FABRIC_GRAIN_DEG; refresh stale 12249 notes
- tests/bench_branch_pruning.py: grain 0.0 -> FABRIC_GRAIN_DEG
- tests/bench_sa.py: grain 0.0 -> FABRIC_GRAIN_DEG (two call sites)
- tests/bench_nfp_cache.py: route hardcoded 90.0 through FABRIC_GRAIN_DEG

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Re-run the clustering bench at grain=90 and capture the numbers

No file changes — this gathers the data Task 4 writes into § 1.

- [ ] **Step 1: Run the clustering bench (a few minutes; effort=5 + partial sweep)**

Run:
```
D:/openmarker/engine/.venv/Scripts/python.exe D:/openmarker/.worktrees/perf-followups/engine/tests/bench_clustering.py
```
Expected:
- The `sample_2.dxf x 10 copies (190 pieces)` rows print for both `effort=1` and `effort=5` (NOT `[skipped]`).
- The `off:` line on both shows `L=11699.4 / U=79.39%` (matches the GUI and the § 1 bar — this is the headline confirmation).
- Final line: `ACCEPTANCE: ALL N GATES PASSED — safe to ship.`

- [ ] **Step 2: Record the numbers for Task 4**

From the `sample_2.dxf x 10 ... effort=5` block, copy down the three values: `off` L/U (expect 11699.4 / 79.39%), `bbox` L/U, and `union` L/U. These feed the § 1 table in Task 4.

- [ ] **Step 3: Checkpoint — if any gate FAILS, stop**

If the bench prints `ACCEPTANCE: ... GATES FAILED` (e.g., `union <= bbox` no longer holds at grain=90), do **not** proceed to docs. Capture the full output and surface it — that is a real finding about clustering at the locked grain and needs discussion, not a silent doc edit.

---

## Task 4: Correct PERFORMANCE.md

**File:** Modify `docs/planning/PERFORMANCE.md`.

- [ ] **Step 1: § 0 — exonerate pruning**

After the paragraph ending `...regardless of the speedup it delivers.` (the retroactive-rule note), add:
```markdown

**Update (2026-06-04):** the § 5.C investigation resolved the variance to a
benchmark grain-config divergence (`fabric_grain_deg` 0 vs 90), **not** pruning.
PR #7/#8 pruning is confirmed result-preserving and is exonerated.
```

- [ ] **Step 2: § 1 — fix the canonical benchmark + the unclustered row**

2a. In the headline paragraph, change `fabric_grain_deg=0.0` to `fabric_grain_deg=90.0` (the locked value; mirrors the GUI).

2b. Replace the "Current bench unclustered NFP-BLF (effort=5)" table row:
```
| Current bench unclustered NFP-BLF (effort=5)          | 12249              | 75.83%      | Known regression vs the bar (+4.7% marker, −3.6pp util). Likely tied to the bench-vs-GUI variance (§ 5.C) — under investigation. **Not** the bar to beat; do not use this as a comparison anchor for new work. |
```
with:
```
| Current bench unclustered NFP-BLF (effort=5)          | 11699.4            | 79.39%      | At the locked 90° grain the bench now matches the GUI and the bar (§ 5.C). Was 12249/75.83% at the erroneous grain=0. |
```

2c. Update the two clustering rows' marker/util with the Task 3 effort=5 numbers, and recompute each "vs bar" percentage as `marker/11699 − 1`:
```
| Clustering — bbox path (off by default, opt-in)       | <bbox L from Task 3>   | <bbox U>%   | +<recomputed>% vs the bar. Mechanism shipped opt-in; see §4. (Re-measured at grain=90.) |
| Clustering — union path (off by default, opt-in)      | <union L from Task 3>  | <union U>%  | +<recomputed>% vs the bar. See §4. (Re-measured at grain=90.) |
```

- [ ] **Step 3: § 5.C — replace the open bullet with the resolution**

Replace the entire `- [ ] **Bench-vs-GUI variance on the unclustered path (filed 2026-05-30).** ...` bullet with:
```markdown
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
```

- [ ] **Step 4: § 6 — add the dated entry**

After the `### 2026-05-31 — Simulated annealing wrapper shipped opt-in` section (at the end of § 6), add:
```markdown
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
  PR #7/#8 pruning is exonerated.
- **Decision:** Grain is no longer a variable feature. The engine keeps the
  `fabric_grain_deg` parameter (and `test_grain.py` still exercises it across
  angles), but no production caller varies it. The prior clustering and SA
  numbers were measured at grain=0 and are superseded; SA is re-baselined at
  grain=90 in the SA-tuning follow-up.
- **Mechanism at:** `engine/core/layout/grain.py` (constant), `engine/api/main.py`
  (locked call). Spec/plan: `docs/superpowers/specs/2026-06-04-bench-grain-fix-design.md`,
  `docs/superpowers/plans/2026-06-04-bench-grain-fix.md`.
```

- [ ] **Step 5: Annotate the SA tables as grain=0 / superseded**

5a. In § 2's "This PR — Simulated annealing" bench table, add a sentence right above the table:
```markdown
> Note (2026-06-04): these SA numbers were measured at the erroneous
> `fabric_grain_deg=0`. Superseded — the SA-tuning follow-up re-baselines at the
> locked 90° grain. See § 6 [2026-06-04].
```
5b. In § 4.6 under **Bench:**, append: `These figures predate the 90° grain lock (§ 6 [2026-06-04]) and are superseded.`
5c. In § 5.B's SA row, append to the cell: ` (measured at grain=0; superseded — re-baseline at grain=90 pending.)`

- [ ] **Step 6: BACKLOG one-line entry**

In `docs/planning/BACKLOG.md`, under `### Phase 6 follow-ups — algorithm performance`, right after the SA wrapper line (`- [x] SA meta-heuristic wrapper (opt-in)...`), add:
```markdown
- [x] Lock fabric grain at 90° + fix bench/docs (resolves §5.C bench-vs-GUI variance). See PERFORMANCE.md § 5.C + § 6 [2026-06-04].
```

- [ ] **Step 7: Commit**

```
git -C D:/openmarker/.worktrees/perf-followups add docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git -C D:/openmarker/.worktrees/perf-followups commit -m "docs(perf): resolve §5.C variance — fabric grain locked at 90°

- docs/planning/PERFORMANCE.md: §0 pruning exonerated; §1 canonical benchmark
  and unclustered row corrected to grain=90 (11699.4/79.39%); clustering rows
  re-measured; §5.C marked resolved with experiment table; §6 2026-06-04 entry;
  SA tables annotated as grain=0/superseded
- docs/planning/BACKLOG.md: one-line entry for the grain lock under Phase 6 follow-ups

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Full-suite verification

- [ ] **Step 1: Run the full unit + integration suites against worktree code**

Run:
```
D:/openmarker/engine/.venv/Scripts/python.exe -m pytest D:/openmarker/.worktrees/perf-followups/engine/tests/unit D:/openmarker/.worktrees/perf-followups/engine/tests/integration -v
```
Expected: all tests **PASS** (no failures, no errors). Confirms the engine behavior is unchanged for grained/None-grain pieces and the API change broke nothing.

- [ ] **Step 2: Confirm the tree is clean and review the log**

Run:
```
git -C D:/openmarker/.worktrees/perf-followups status --short
git -C D:/openmarker/.worktrees/perf-followups log --oneline -5
```
Expected: clean working tree; three new commits (Task 1, Task 2, Task 4) plus the earlier spec commit. **Do not push** — report the branch state and wait for the user's OK to open PR #1.

---

## Self-review notes (author)

- **Spec coverage:** constant (Task 1.3), API lock + ignore (Task 1.4 + test 1.1), engine untouched (no task modifies `heuristic.py`/`grain.py` logic; `test_grain.py` left as-is), benches (Task 2), docs §0/§1/§5.C/§6 + SA annotations (Task 4), re-baseline run (Task 3), out-of-scope items deliberately have no task (frontend, clustering internals, SA re-run). Acceptance criteria 1–4 map to Task 3.1, Task 1.5, Task 5.1, Task 4.
- **Empirical fills:** § 1 bbox/union cells are pasted from Task 3's measured output (cannot be known until the bench runs); the `off` value (11699.4/79.39%) is already confirmed.
- **Type/name consistency:** constant is `FABRIC_GRAIN_DEG` everywhere; helper `_grained_rect`; test `test_auto_layout_ignores_grain_direction_deg`.
