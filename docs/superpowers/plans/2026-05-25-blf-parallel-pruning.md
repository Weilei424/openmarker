# BLF Parallel Branch Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the branch-pruning behavior we shipped in PR #7 (serial path) to the parallel path of `auto_layout_polygon`. Parallel workers learn about each other's completed-strategy results via a shared `multiprocessing.Value` and prune their own intra-strategy execution when their partial marker length already meets/exceeds the global best.

**Architecture:** Approach **B** from the brainstorm — shared atomic cutoff, no serial scout phase.

- Main process creates `multiprocessing.Value('d', float('inf'))` before pool dispatch.
- `ProcessPoolExecutor(initializer=_init_worker, initargs=(shared_best,))` injects the Value into each worker's module-level global at spawn time.
- `_run_one_strategy` (the worker entrypoint) reads the worker-global Value and passes it as a new `shared_best_value` kwarg to `_blf_pack_nfp`.
- Inside `_blf_pack_nfp`, the existing per-placement prune check is extended: it takes `min(best_marker_so_far_kwarg, shared_best_value.value)` as the effective cutoff. Each `.value` read acquires the Value's internal lock (~1–5 µs on Windows; negligible vs the placement work).
- Main process uses `concurrent.futures.as_completed` to harvest results. After each successful result, it publishes `min(current_shared, result.marker_length)` under the Value's lock. `_PrunedRun` raised in a worker propagates through `future.result()` and is caught + `continue`'d.

**Result quality:** identical to no-prune baseline (proven in PR #7 — pruning is provably safe by the monotone-bound argument and never changes the chosen layout). The benefit is reduced wall-clock at `effort > 1`.

**Scope:**
- Serial path (`use_pool == False`) is unchanged — already does the optimal thing.
- Parallel path (`use_pool == True`) gets the shared-Value treatment.
- The existing `best_marker_so_far` kwarg keeps its meaning (caller-supplied initial cutoff); it composes with `shared_best_value` via min.

**Tech Stack:** Python 3.11, `multiprocessing.Value`, `concurrent.futures.ProcessPoolExecutor`, pytest. Touches `engine/core/layout/heuristic.py` and tests; no API, frontend, or schema changes.

---

### Task 1: Add `shared_best_value` parameter to `_blf_pack_nfp`

**Files:**
- Modify: `engine/core/layout/heuristic.py` (`_blf_pack_nfp` signature + per-placement read)
- Test: `engine/tests/unit/test_heuristic.py` (new tests appended)

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/unit/test_heuristic.py`:

```python
# --- shared-cutoff (parallel pruning) tests ---

def test_blf_shared_value_none_behaves_like_serial():
    """When shared_best_value is None, behavior is identical to the serial path."""
    from core.layout.heuristic import _blf_pack_nfp
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    _, length_serial, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0
    )
    _, length_shared, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        shared_best_value=None,
    )
    assert length_serial == length_shared


def test_blf_shared_value_infinity_does_not_prune():
    """A Value initialized to infinity (no cutoff yet) must not trigger pruning."""
    import multiprocessing
    from core.layout.heuristic import _blf_pack_nfp
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    shared = multiprocessing.Value("d", float("inf"))
    placements, length, _ = _blf_pack_nfp(
        pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
        shared_best_value=shared,
    )
    assert len(placements) == 3
    assert length > 0


def test_blf_shared_value_tight_cutoff_prunes():
    """A shared Value with a tight cutoff must raise _PrunedRun mid-run."""
    import multiprocessing
    from core.layout.heuristic import _blf_pack_nfp, _PrunedRun
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    shared = multiprocessing.Value("d", 1.0)  # any non-trivial placement exceeds this
    with pytest.raises(_PrunedRun):
        _blf_pack_nfp(
            pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
            shared_best_value=shared,
        )


def test_blf_shared_value_takes_min_with_kwarg():
    """When both best_marker_so_far and shared_best_value are provided, the
    effective cutoff is the minimum (the tighter of the two prunes)."""
    import multiprocessing
    from core.layout.heuristic import _blf_pack_nfp, _PrunedRun
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    # Kwarg is loose (1e9). Shared is tight (1.0). Effective = 1.0 → prune.
    shared = multiprocessing.Value("d", 1.0)
    with pytest.raises(_PrunedRun):
        _blf_pack_nfp(
            pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
            best_marker_so_far=1e9,
            shared_best_value=shared,
        )

    # Inverted: kwarg tight, shared loose → still prune via kwarg.
    shared_loose = multiprocessing.Value("d", float("inf"))
    with pytest.raises(_PrunedRun):
        _blf_pack_nfp(
            pieces, fabric_width_mm=500, grain_mode="single", fabric_grain_deg=0.0,
            best_marker_so_far=1.0,
            shared_best_value=shared_loose,
        )
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v -k "shared_value"`

Expected: all four FAIL with `TypeError: _blf_pack_nfp() got an unexpected keyword argument 'shared_best_value'`.

- [ ] **Step 3: Add `shared_best_value` to `_blf_pack_nfp`**

In `engine/core/layout/heuristic.py`:

Update the signature of `_blf_pack_nfp` (add `shared_best_value` as the last kwarg):

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
) -> tuple[list[Placement], float, float]:
```

Replace the existing per-placement prune block (the one at the bottom of the `for piece in sorted_pieces:` loop, just after `placed.append(_Placed(...))`) with this version:

```python
        # Branch pruning. `candidate_poly.bounds[3]` is the bottom edge of the
        # bbox in screen-y-down coords (= top + height because _placed_polygon
        # aligns minx/miny to the requested top-left). Partial marker length is
        # monotone non-decreasing — once it meets the cutoff, this run cannot win.
        if candidate_poly.bounds[3] > current_max_bottom:
            current_max_bottom = candidate_poly.bounds[3]
        # Effective cutoff = min(caller-supplied initial, shared cross-worker).
        # `.value` reads through the Value's internal lock (~1-5µs on Windows);
        # negligible vs the placement work done above.
        effective_cutoff = best_marker_so_far
        if shared_best_value is not None:
            sv = shared_best_value.value
            if effective_cutoff is None or sv < effective_cutoff:
                effective_cutoff = sv
        if effective_cutoff is not None and current_max_bottom + EDGE_GAP >= effective_cutoff:
            raise _PrunedRun()
```

- [ ] **Step 4: Run all heuristic tests**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py -v`

Expected: every test PASSES — the 11 pre-existing + 5 from PR #7 + 4 new = 20 tests.

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git commit -m "perf(engine): _blf_pack_nfp accepts shared_best_value for cross-worker pruning"
```

---

### Task 2: Wire shared Value through the parallel path

**Files:**
- Modify: `engine/core/layout/heuristic.py` (parallel branch of `auto_layout_polygon`; `_run_one_strategy`; new `_init_worker` + `_worker_shared_best` module global)
- Test: `engine/tests/unit/test_heuristic.py` (parallel-result equivalence test)

- [ ] **Step 1: Write the failing test**

Append to `engine/tests/unit/test_heuristic.py`:

```python
def test_auto_layout_parallel_pruning_matches_serial():
    """Parallel mode with shared-Value pruning must produce the same chosen
    layout as the serial path. Result quality must never depend on whether
    pruning is on or off, or on the worker count."""
    # Pieces are mixed-size rects — different sort strategies diverge,
    # so multiple workers are exercised and at least one is prunable.
    pieces = [_make_rect(f"p{i}", 80 + i * 10, 100 + (i % 3) * 30) for i in range(6)]
    serial = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0, effort=1
    )
    parallel = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="bi", fabric_grain_deg=0.0, effort=5
    )
    assert serial[1] == parallel[1]  # marker length
    assert serial[2] == parallel[2]  # utilization
```

- [ ] **Step 2: Run the new test on the pre-change code**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/unit/test_heuristic.py::test_auto_layout_parallel_pruning_matches_serial -v`

Expected: PASS (the existing parallel path already produces identical results — this pins that behavior). If it fails, **stop** — there's a pre-existing parallel/serial discrepancy that this PR shouldn't paper over.

- [ ] **Step 3: Add the worker-global + initializer**

In `engine/core/layout/heuristic.py`, near the top (just below the existing parallel-cancel plumbing — around the `_current_executor` block), add:

```python
# ---------------------------------------------------------------------------
# Cross-worker shared cutoff (parallel pruning)
# ---------------------------------------------------------------------------
# Set in each worker process by `_init_worker` at pool spawn time. The main
# process publishes completed-strategy marker lengths into this Value as a
# running min, and workers read it during BLF to prune their own execution
# (see `shared_best_value` in `_blf_pack_nfp`).
_worker_shared_best = None


def _init_worker(value) -> None:
    """ProcessPoolExecutor initializer. Stashes the shared `Value` in a
    worker-process module global so `_run_one_strategy` can pass it down."""
    global _worker_shared_best
    _worker_shared_best = value
```

- [ ] **Step 4: Thread the shared Value through `_run_one_strategy`**

Update `_run_one_strategy` to read the worker global and pass it to `_blf_pack_nfp`:

```python
def _run_one_strategy(
    pieces: list[Piece],
    fabric_width_mm: float,
    mode: str,
    fabric_grain_deg: float,
    sort_index: int,
) -> tuple[list[Placement], float, float]:
    """Module-level entry for ProcessPoolExecutor. sort_index selects from
    _SORT_STRATEGIES so we don't have to pickle the callable across the
    process boundary. Reads `_worker_shared_best` (set by `_init_worker`)
    so this strategy can prune via the cross-worker shared cutoff."""
    sort_key = _SORT_STRATEGIES[sort_index]
    return _blf_pack_nfp(
        pieces, fabric_width_mm, mode, fabric_grain_deg,
        sort_key=sort_key,
        shared_best_value=_worker_shared_best,
    )
```

- [ ] **Step 5: Update the parallel branch of `auto_layout_polygon`**

Replace the parallel branch (the `# Parallel path...` comment block through to `return best`, after the `if not use_pool:` block). New version:

```python
    # Parallel path. Each worker rebuilds its own NFP cache (lost cross-strategy
    # reuse) but we get N-way parallelism. /cancel-layout terminates the worker
    # processes via kill_current_executor (see module top); the resulting
    # BrokenProcessPool from future.result() is translated to CancellationError.
    #
    # Cross-worker pruning: a shared `multiprocessing.Value` carries a running
    # min of completed-strategy marker lengths. Workers read it per placement
    # and abort (raise _PrunedRun) once their partial passes the cutoff. Main
    # process publishes via as_completed so the cutoff tightens as workers finish.
    import multiprocessing
    from concurrent.futures import as_completed
    shared_best = multiprocessing.Value("d", float("inf"))

    best: tuple[list[Placement], float, float] | None = None
    futures = []
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_worker,
        initargs=(shared_best,),
    ) as pool:
        _set_current_executor(pool)
        try:
            for mode in modes:
                for sort_index in range(len(_SORT_STRATEGIES)):
                    futures.append(pool.submit(
                        _run_one_strategy,
                        pieces, fabric_width_mm, mode, fabric_grain_deg, sort_index,
                    ))
            try:
                for f in as_completed(futures):
                    try:
                        result = f.result()
                    except _PrunedRun:
                        continue  # worker self-aborted via the shared cutoff; ignore
                    # Publish under the Value's lock so concurrent completers
                    # can't overwrite each other's lower value.
                    with shared_best.get_lock():
                        if result[1] < shared_best.value:
                            shared_best.value = result[1]
                    best = _shorter(best, result)
            except BrokenProcessPool as e:
                raise CancellationError("Auto-layout cancelled (workers terminated).") from e
        finally:
            _set_current_executor(None)

    assert best is not None
    return best
```

Move the imports to the file's top-level import block (alongside the existing `from concurrent.futures import ProcessPoolExecutor`):

```python
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
```

Then delete the function-local `import multiprocessing` and `from concurrent.futures import as_completed` lines from the snippet above — the parallel branch uses the top-level imports.

Notes:
- The `assert best is not None` is sound because at least one worker always completes successfully: the first worker to finish saw `shared_best == infinity` and could not have been pruned.

- [ ] **Step 6: Run the full engine test suite**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest engine/tests/ -v`

Expected: every test passes — 87 (post-PR-#7) + 4 from Task 1 + 1 from Task 2 = 92.

- [ ] **Step 7: Commit**

```bash
git add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git commit -m "perf(engine): parallel auto-layout prunes via shared multiprocessing.Value cutoff"
```

---

### Task 3: Extend benchmark to cover parallel pruning

**Files:**
- Modify: `engine/tests/bench_branch_pruning.py` (add a worker-count parameter; add parallel scenarios)

- [ ] **Step 1: Update the benchmark**

The current `_run` calls `auto_layout_polygon(..., effort=1)`. Generalize it to accept `effort`, and add `_bench` parameters so we can run scenarios at both serial and parallel effort levels. Add a worker-count detection helper for the scenario label.

In `engine/tests/bench_branch_pruning.py`:

Change `_run`:

```python
def _run(pieces, fabric_width_mm, grain_mode, effort):
    t0 = time.perf_counter()
    result = heuristic.auto_layout_polygon(
        pieces, fabric_width_mm=fabric_width_mm,
        grain_mode=grain_mode, fabric_grain_deg=0.0, effort=effort,
    )
    return time.perf_counter() - t0, result[1]
```

Change `_bench` to accept and forward `effort`:

```python
def _bench(name: str, pieces, fabric_width_mm: float, grain_mode: str = "single", effort: int = 1) -> None:
    # Warmup pass — eats import/JIT overhead.
    _run(pieces, fabric_width_mm, grain_mode, effort)

    on_t, on_len = _run(pieces, fabric_width_mm, grain_mode, effort)

    original = heuristic._blf_pack_nfp
    def no_prune(*args, **kwargs):
        kwargs.pop("best_marker_so_far", None)
        kwargs.pop("shared_best_value", None)
        return original(*args, **kwargs)
    heuristic._blf_pack_nfp = no_prune
    try:
        off_t, off_len = _run(pieces, fabric_width_mm, grain_mode, effort)
    finally:
        heuristic._blf_pack_nfp = original

    speedup = off_t / on_t if on_t > 0 else float("inf")
    same = "same" if abs(on_len - off_len) < 1e-6 else f"DIFFER on={on_len:.2f} off={off_len:.2f}"
    print(f"{name:55s} on={on_t*1000:8.1f}ms  off={off_t*1000:8.1f}ms  speedup={speedup:5.2f}x  result={same}")
```

(Note the `kwargs.pop("shared_best_value", None)` addition — the monkey-patched baseline must strip BOTH cutoff kwargs so workers see no pruning at all.)

Update the `__main__` block to add parallel scenarios. Keep the existing four serial scenarios and append:

```python
    # --- parallel scenarios (effort=5 = all cores) ---
    print()  # blank line for readability
    print("Parallel mode (effort=5):")

    _bench("8 mixed rects, bi grain, fabric=400 [par]", pieces_bi, 400.0, "bi", effort=5)

    if dxf_path is not None:
        _bench(
            f"sample_2.dxf x 10 copies ({len(pieces_real)} pieces), bi [par]",
            pieces_real, 1500.0, "bi", effort=5,
        )
```

The real-workload parallel row is the headline number — it tests the same workload as the serial row but at effort=5, so the speedup column directly answers "does parallel pruning save wall-clock on the workload we care about?"

- [ ] **Step 2: Run the benchmark and capture numbers**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\bench_branch_pruning.py`

Expected output: the 4 existing serial rows (unchanged from PR #7's bench), a blank line, and 1–2 parallel rows. Every row must show `result=same`.

If any row shows `DIFFER`, **STOP** — pruning has introduced a result regression.

Record the FULL output verbatim — it goes into the commit message.

- [ ] **Step 3: Commit**

```bash
git add engine/tests/bench_branch_pruning.py
git commit -m "$(cat <<'EOF'
test(engine): extend bench to cover parallel pruning at effort=5

Numbers from local run (Windows):
  <paste full bench output here>
EOF
)"
```

---

### Task 4: Docs

**Files:**
- Modify: `CLAUDE.md` (engine architecture section — extend the pruning paragraph)
- Modify: `docs/planning/BACKLOG.md` (mark parallel pruning shipped)

- [ ] **Step 1: Update `CLAUDE.md`**

Locate the `core/layout/heuristic.py` bullet under "### Engine (`engine/`)". It currently ends with the sentence "Parallel path (effort>1) does not prune; workers don't share state." (added in PR #7). Replace that last sentence with:

```
Parallel path (effort>1) also prunes: workers share a `multiprocessing.Value('d', float('inf'))`
that the main process updates (running min) as each strategy completes via `as_completed`,
and workers read per-placement to abort their own runs when partial >= shared cutoff.
```

- [ ] **Step 2: Update `docs/planning/BACKLOG.md`**

Two edits:

(a) In the "Phase 6 follow-ups — algorithm performance" section, append a second bullet under the existing serial-pruning one:

```markdown
- [x] Engine: parallel-path branch pruning via shared `multiprocessing.Value('d')` cutoff. Main process publishes completed-strategy results via `as_completed`; workers read per placement and self-abort once their partial >= shared cutoff. Result identical to serial mode. Measured wall-clock speedup at effort=5: <paste headline number>x on sample_2.dxf × 10 (bi grain). Shipped in PR #<n>.
```

(Fill in the speedup number and PR number when committing — they're known by the time you write this commit.)

(b) In the "Branch-pruning follow-ups" section (under Future / Unscheduled), CHECK OFF the parallel-pruning bullet that was filed when PR #7 shipped:

Find:
```markdown
- [ ] **Parallel-path pruning.** Workers in `ProcessPoolExecutor` don't share `best_so_far`...
```
Change `[ ]` to `[x]` and append `(Shipped in PR #<n>.)`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/planning/BACKLOG.md
git commit -m "docs: parallel branch pruning in CLAUDE.md engine notes and BACKLOG"
```

---

## Out of scope for this PR

- **Smart strategy ordering** — still deferred; needs telemetry on which sort wins most often before it's worth implementing.
- **Cutoff slack / diverse near-best results** — same deferral as PR #7.
- **Lock contention reduction** — if benchmarks show the per-placement Value read costs more than expected, the optimization is either (a) read every K placements instead of every 1, or (b) switch to `RawValue` (no lock, slightly stale reads are harmless). Don't preemptively optimize; measure first.
- **Pool startup cost amortization for small inputs** — the existing `total_runs * len(pieces) >= 20` threshold gate stays as-is. Could be revisited once we have parallel-pruning measurements.

## Risk notes

- **Windows spawn semantics:** `multiprocessing.Value` works under `spawn` (the only start method on Windows) because `ProcessPoolExecutor` passes the Value through OS-level handle inheritance during pool initialization. Verify by running Task 2's tests — they exercise effort=5 which spawns real processes.
- **Initializer failure:** If `_init_worker` ever raises, ProcessPoolExecutor marks the worker broken and all submitted futures fail. This is the existing behavior for any init failure; the new initializer is trivial (one global assignment) and shouldn't fail.
- **Stale reads:** Workers can read a slightly-stale `shared_best.value` (between a publish from main and the worker's next read). This only ever causes "missed pruning opportunities", never an incorrect result. Safe by construction.
- **PrunedRun across process boundary:** `_PrunedRun(Exception)` is picklable (no slots, no special args). It crosses the process boundary and is re-raised by `future.result()` in the main process. Verified by Task 2's tests.
