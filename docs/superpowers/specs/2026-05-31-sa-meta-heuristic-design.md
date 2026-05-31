# SA Meta-Heuristic Wrapper — Design Spec

**Date:** 2026-05-31
**Author:** Claude (Opus 4.7) + Mason Wang
**Target:** Engine — new `engine/core/layout/sa.py`, plus surgical changes to `engine/core/layout/heuristic.py`, new `engine/tests/unit/test_sa.py`, new `engine/tests/bench_sa.py`, integration cases in `engine/tests/unit/test_heuristic.py`.
**Predecessor:** PR #10 (partial clustering — `docs/superpowers/specs/2026-05-30-partial-clustering-design.md`)
**BACKLOG item:** `Phase 6 follow-ups — algorithm performance` → `GA/SA meta-heuristic wrapper` (PERFORMANCE.md § 5.B last row). This spec covers the SA half only; GA is deferred to a follow-up PR per the brainstorm decision.

---

## 1. Goal

Wrap the existing NFP-BLF (`_blf_pack_nfp`) as the fitness function of a Simulated Annealing search over `(piece-ordering × per-piece rotation-choice)`. The aim is to beat the **bar to beat** from PERFORMANCE.md § 1: marker length **≤ 11699mm** on the canonical workload (`sample_2.dxf × 10` at fabric=1651mm, bi-grain), prioritizing marker length and utilization over layout duration per PERFORMANCE.md § 0.

The current best-of-4 sort strategies explore only 4 hand-picked orderings out of N! possibilities and never explore per-piece rotation choices outside what the inner BLF's per-placement rotation sweep happens to pick. SA generalizes both axes.

### Disposition (decided before implementation)

The SA wrapper ships as a permanent opt-in mechanism regardless of whether it beats the bar:

- **If at least one tested iteration count beats `≤ 11699mm`** on the canonical workload, a follow-up PR considers (a) exposing the knob via the HTTP API, (b) surfacing a "Quality" tier in the React UI, and (c) flipping `sa_iterations > 0` default-on for large workloads.
- **If no iteration count wins,** the knob still ships. PERFORMANCE.md § 6 records the result; the SA scaffold becomes the foundation for the deferred GA follow-up and for tuning sweeps (T₀, α, neighbor weights).

This is explicitly NOT an "experiment, then decide whether to keep the code" framing. The wrapper merges either way; only the *default state* and *exposure surface* depend on the bench outcome.

## 2. Scope

### In scope

- New module `engine/core/layout/sa.py` containing the SA driver:
  - `run_sa(...)` — pure function; takes its evaluator as a callable for testability.
  - Module constants for hyperparameters (T₀ factor, α, T_min, reverse-window cap, no-grainline rotation cap, move-type weights).
- Three new parameters on `auto_layout_polygon` (`engine/core/layout/heuristic.py`):
  - `sa_iterations: int = 0` (0 = SA disabled; matches the opt-in pattern of `disable_clustering=True` and `cluster_fraction=1.0`).
  - `sa_max_time_s: float | None = None` (wall-clock cap; `None` = iterations-only).
  - `sa_seed: int = 0` (base seed; per-restart seed = `seed + worker_index`).
- Two surgical changes to `_blf_pack_nfp` (Approach A from the brainstorm):
  - `override_rotations` accepts `list[list[float]]` interpreted as per-piece allowed-rotation lists when `len(override_rotations) == len(pieces)` and the first element is a list. Existing `list[float]` shape is unchanged.
  - New `presorted: bool = False`. When True, skip the internal `sorted(pieces, key=sort_key, reverse=True)` and use the input order verbatim.
- Multi-warm-start: keep all up-to-8 warm-start runs (currently the heuristic discards 7 of the 8); SA chain *k* starts from warm-start at rank `k mod len(warm_starts)`.
- Per-worker NFP cache reused across SA iterations within a worker.
- Cross-worker pruning via the existing `multiprocessing.Value("d", float("inf"))` scaffold — no new shared-memory primitives.
- Cancellation propagation: `is_cancelled()` checked between SA iterations; `kill_current_executor()` continues to terminate worker processes.
- Mutual-exclusion guard: `sa_iterations > 0` combined with `disable_clustering=False` raises `ValueError`. Documented explicitly.
- 12 unit tests in `engine/tests/unit/test_sa.py` (deterministic, stub evaluator).
- 6 integration tests in `engine/tests/unit/test_heuristic.py` (real `auto_layout_polygon` calls; small synthetic inputs).
- New `engine/tests/bench_sa.py` with a `sa_iterations` sweep on the canonical workload and 4 PR-blocking acceptance gates plus 1 aspirational gate.
- Doc updates: PERFORMANCE.md § 2 (new subsection), § 4 (new § 4.6 code map + opt-in invocation), § 5.B (tick the SA half), § 6 (chronological 2026-05-31 entry); BACKLOG.md (new `[x]` line); CLAUDE.md (engine module list + `heuristic.py` param mention).

### Out of scope

- **GA (genetic algorithm).** Deferred to a follow-up PR per the brainstorm scope decision. The SA scaffold (`run_sa`, evaluator shape, warm-start handling, parallelism) is designed to make a future GA driver mechanical to add, but no GA code lands in this PR.
- **HTTP API exposure.** `POST /auto-layout` does not learn about `sa_*` parameters. Cache dedup key in `engine/core/layout/cache.py::find_by_settings` is unchanged. Same engine-Python-only opt-in policy as PERFORMANCE.md § 4.3.
- **Frontend UI exposure.** `useAutoLayout.ts`, `App.tsx` Advanced sidebar, and the Parallel-effort radio are unchanged. No "Quality" tier in this PR.
- **SA + clustering combined.** Mutual exclusion enforced by `ValueError`. Combining them is a future-work entry in PERFORMANCE.md § 4.6.
- **Hyperparameter exposure.** T₀ factor, α, T_min, neighbor weights, reverse-window cap, no-grainline rotation cap all live as module-level constants in `sa.py`. No public-API tunables for these in this PR. A follow-up can expose any that bench sweeps show are worth user control.
- **Reheating / restart-within-chain.** A single SA chain runs straight-line cooling to termination. Reheat strategies (e.g., when accept rate drops below threshold) are deferred.
- **Adaptive neighbor weights.** Move-type weights (`swap`/`reverse`/`rotation-flip`) are fixed at compile time. Adaptive selection (favor whichever operator is producing improvements) is deferred.
- **GA-style crossover preview.** Not in this PR.
- **Bench beyond the canonical workload.** No SA sweeps on the synthetic bench rows in `bench_clustering.py` — they're too small for SA to behave meaningfully different from warm-start.
- **Variance investigation from PERFORMANCE.md § 5.C.** Separate concern; SA's correctness gates compare against the warm-start the SA chain itself produces, not against any bench-recorded "off" number.

## 3. Architecture changes

### `engine/core/layout/sa.py` (new file)

Single public function plus private helpers.

```python
def run_sa(
    initial_order: list[int],            # piece indices, length N
    initial_rotations: list[float],       # length N
    pieces: list[Piece],                  # length N; indexed by initial_order entries
    allowed_rotations_per_piece: list[list[float]],  # outer len N; inner = piece's allowed set
    iterations: int,
    max_time_s: float | None,
    seed: int,
    evaluator: Callable[[list[Piece], list[list[float]]], tuple[list[Placement], float, float]],
    shared_best_value: Synchronized | None = None,
    clock: Callable[[], float] = time.perf_counter,  # injected for testability
) -> SAResult:
    ...
```

`SAResult` (named tuple): `(best_order, best_rotations, best_placements, best_marker, best_util, iterations_executed, accept_count, improve_count)`.

The evaluator's responsibility is to take the chain's current candidate (a pieces list in chain-chosen order plus a per-piece rotation list) and return the BLF result. Inside `auto_layout_polygon` the evaluator is bound to `_blf_pack_nfp(..., presorted=True, override_rotations=..., nfp_cache=worker_cache, shared_best_value=shared_best, ...)`. In tests the evaluator is a stub.

Module constants:

```python
T0_FACTOR: float = 0.05              # T0 = T0_FACTOR * initial_marker_length
COOLING_ALPHA: float = 0.95          # geometric per iteration
T_MIN: float = 1e-3                  # numerical floor
REVERSE_WINDOW_FRACTION: float = 0.25  # max reverse window = ceil(N * 0.25)
NO_GRAINLINE_ROTATION_CAP: int = 4   # for pieces with allowed_rotations == [0..359]
MOVE_WEIGHTS: dict[str, float] = {"swap": 1.0, "reverse": 1.0, "rotation_flip": 1.0}
```

### `engine/core/layout/heuristic.py`

**Surgical changes to `_blf_pack_nfp`:**

- New parameter `presorted: bool = False`. When True, the existing `sorted(pieces, key=sort_key, reverse=True)` line is skipped and `pieces` is used verbatim. Existing callers default to False — no behavior change.
- `override_rotations` parameter accepts a new polymorphic shape: if `override_rotations is not None and len(override_rotations) == len(pieces) and isinstance(override_rotations[0], list)`, treat it as per-piece allowed-rotation lists (`override_rotations[i]` is the list to use for the piece at position *i* in the sort order). Otherwise the existing `list[float]` uniform shape applies. The internal `_layout_rotations` call sites that consume `override_rotations` get a small dispatch at the top: pick the per-piece list when in per-piece mode, else use the uniform list.
- No other behavior changes. The existing `nfp_cache`, `shared_best_value`, `best_marker_so_far`, `skip_validation` plumbing is untouched.

**New parameters on `auto_layout_polygon`:**

```python
def auto_layout_polygon(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    disable_nfp_cache: bool = False,
    effort: int = 1,
    disable_pruning: bool = False,
    disable_clustering: bool = True,
    cluster_polygon: str = "union",
    cluster_fraction: float = 1.0,
    # --- new in this PR ---
    sa_iterations: int = 0,
    sa_max_time_s: float | None = None,
    sa_seed: int = 0,
) -> tuple[list[Placement], float, float]:
```

**Validation block (top of function, after existing validators):**

```python
if sa_iterations < 0:
    raise ValueError(f"sa_iterations must be >= 0, got {sa_iterations}")
if sa_iterations > 0 and not disable_clustering:
    raise ValueError(
        "sa_iterations > 0 cannot be combined with disable_clustering=False; "
        "see PERFORMANCE.md § 4.6 for the future-work note."
    )
if sa_max_time_s is not None and sa_max_time_s <= 0:
    raise ValueError(f"sa_max_time_s must be > 0 when set, got {sa_max_time_s}")
```

**Control flow branches on `sa_iterations`:**

When `sa_iterations == 0`: **completely unchanged from current behavior.** The existing `_shorter(best, result)` accumulator is used; no warm-start retention list is built. This guarantees G1 (regression gate) by construction — the SA-disabled path executes the same code as today.

When `sa_iterations > 0`:

1. Run the warm-start phase as today, but modify BOTH the serial loop and the parallel `as_completed` handler to **retain ALL completed runs** in a `warm_starts: list[WarmStart]` (named tuple of `mode, sorted_pieces, rotations_used, placements, marker, util` — `mode` is the BLF mode the run used, needed in step 4). Sort ascending by marker. `warm_starts[0]` corresponds to today's `best`. Pruned runs (those that raised `_PrunedRun`) are not added to `warm_starts` — they have no marker length to inherit.
2. Compute `allowed_rotations_per_piece` once from the **user's** `grain_mode` (not per warm-start mode): `[allowed_rotations(grain_mode, fabric_grain_deg, p.grainline_direction_deg) for p in pieces]`. For pieces where `allowed_rotations` returns the full 360-element list (no grainline), keep only `NO_GRAINLINE_ROTATION_CAP` evenly-spaced angles (e.g., `[0, 90, 180, 270]` when cap=4). This list is shared across all chains regardless of which warm-start they inherit from — so a chain from a `mode="single"` warm-start can still explore bi-mode rotations when the user passed `grain_mode="bi"`.
3. Launch K = `_worker_count(effort)` SA chains. Each chain runs in its own worker process (or in-process when K=1). Pool lifecycle: SA always opens its own `ProcessPoolExecutor` after the warm-start pool context-manager exits — no attempt to reuse the warm-start pool. Each chain receives:
   - Its assigned warm-start: `warm_starts[k mod len(warm_starts)]`.
   - `seed = sa_seed + k`.
   - `iterations = sa_iterations`, `max_time_s = sa_max_time_s`.
   - Access to `shared_best` via `_init_sa_worker` (mirrors existing `_init_worker`).
4. Each chain's BLF evaluator passes `mode = effective_mode` (the warm-start's mode, e.g., `"bi"` if the chain inherited a bi warm-start) and `override_rotations` = a per-piece singleton list `[[chain.rotations[order[i]]] for i in range(N)]`. The override fully controls rotation selection — the `mode` parameter affects only fallback paths inside BLF that the override bypasses, so passing the warm-start's mode is the safest choice (matches the warm-start's geometric assumptions).
5. Aggregate: `final_best = min(warm_starts[0], *(sa_result for sa_result in completed_chains), key=marker_length)`. Warm-start always retained → SA cannot regress.
6. Return `final_best` as `(placements, marker_length_mm, utilization_pct)`.

**Serial path (effort=1, K=1) with `sa_iterations > 0`:** the warm-start runs serially (existing behavior); the one SA chain runs in-process after. `shared_best_value=None` is passed through — no cross-worker cutoff applies with a single chain.

### `engine/tests/unit/test_sa.py` (new file)

12 unit tests against `sa.run_sa` with a stub evaluator. Each <50ms.

1. `sa_iterations=0` returns warm-start unchanged; evaluator never called.
2. Best-seen returned, not final state. Stub fitness landscape: monotonically worsens after iteration 10, but iteration 5 found the minimum. SA must return iteration-5 state.
3. Monotone non-worsening: 100 random seeds, `best_marker ≤ initial_marker` always.
4. Swap preserves permutation validity: no duplicate indices, all original indices present.
5. Reverse preserves permutation validity and respects `REVERSE_WINDOW_FRACTION` cap.
6. Rotation-flip never picks a value outside `allowed_rotations_per_piece[i]`.
7. Rotation-flip on a 1-allowed piece eventually picks a different move type (no infinite loop).
8. Metropolis acceptance: at T₀, accept-worse rate over 1000 deterministic stub-bad neighbors is > 50%; at T_min, < 1%.
9. Cooling schedule: `T_k == T0 * COOLING_ALPHA ** k` within float epsilon for k ∈ [0, 100].
10. Termination on iteration count: stops at exactly `iterations` even when evaluator always improves.
11. Termination on `max_time_s`: stops within one iteration of the cap. Uses injected `clock` for determinism (no real `time.perf_counter` calls).
12. Evaluator `ValueError` → neighbor rejected, chain continues from current state, no crash.

### `engine/tests/unit/test_heuristic.py` (existing file, add tests)

6 integration tests with real `auto_layout_polygon`. Each <2s.

13. `sa_iterations=0` is bit-identical to the current default for the same input (no new plumbing introduces side effects).
14. `sa_iterations=50` produces marker ≤ `sa_iterations=0` result for the same seed and input. Monotone via warm-start retention.
15. `sa_iterations=50` + `disable_clustering=False` raises `ValueError` with the documented message substring.
16. `sa_iterations=50` + `disable_pruning=True` runs to completion and produces a valid layout.
17. Parallel path (`effort=2`, `K=2`, `sa_iterations=20`, `sa_seed=42`): two runs produce identical marker length.
18. `sa_max_time_s=0.1` with `sa_iterations=10_000` terminates within 0.2s and returns at minimum the warm-start.

### `engine/tests/bench_sa.py` (new file)

Mirrors the structure of `bench_clustering.py`. Canonical workload only (`sample_2.dxf × 10` at fabric=1651mm, bi-grain, effort=5).

Sweep: `sa_iterations ∈ [0, 100, 500, 1000]`. Each row prints marker length, utilization, wall-clock, iterations actually executed, and the worker index whose chain produced the winning result.

**PR-blocking acceptance gates:**

- **G1 (correctness regression guard):** `sa_iterations=0` returns the same marker as the existing `off` baseline. Failing means the new params introduced a side effect into the default path.
- **G2 (monotone):** For each `sa_iterations ∈ [100, 500, 1000]`, marker ≤ warm-start marker on this workload. Sound by construction (warm-start always retained); the gate catches plumbing bugs.
- **G3 (determinism):** Two runs with identical `sa_seed=42` at effort=5 produce identical marker lengths.
- **G4 (opt-in default unchanged):** `auto_layout_polygon` called without any `sa_*` argument produces the same marker as the historical bench `off` row (or whatever the variance-investigation eventually grounds as the current `off`).

**Aspirational gate (informational, not PR-blocking):**

- **G5 (the real win):** At least one `sa_iterations ∈ [100, 500, 1000]` produces marker **≤ 11699mm** on the canonical workload. If G5 fails, the PR still merges as opt-in mechanism per the disposition statement; PERFORMANCE.md § 6 records the result and files follow-ups.

The bench exits 1 only on G1-G4 failure. G5 status is printed prominently with PASS / FAIL but doesn't affect exit code.

## 4. Algorithm details

### Candidate

```
order:     [int, int, ..., int]    # permutation of [0, 1, ..., N-1]
rotations: [float, float, ..., float]  # one per piece in `pieces`, NOT in `order`
```

Note: `rotations[i]` is the rotation chosen for `pieces[i]`, not for the piece at position *i* in the order. Decoupling rotations from order makes rotation moves O(1) and means a swap move doesn't disturb rotation choices.

### Initial state

From the chain's assigned warm-start (`warm_starts[k mod len(warm_starts)]`):
- `order = [pieces.index(p) for p in warm_start.sorted_pieces]` — the order the winning sort_key produced
- `rotations[i] = warm_start.placement_for_piece_i.rotation_deg`

### Neighbor operators

One uniformly random per iteration (weights from `MOVE_WEIGHTS`):

- **Swap.** Pick `i, j` uniformly at random from `[0, N)` with `i != j`. Swap `order[i]` ↔ `order[j]`.
- **Reverse.** Pick `i` uniformly from `[0, N - 2)`. Pick window length `w` uniformly from `[2, ceil(N * REVERSE_WINDOW_FRACTION)]`. Clip `j = min(i + w, N)`. Reverse `order[i:j]`.
- **Rotation flip.** Pick piece index `p` uniformly from `[0, N)`. Look up `allowed = allowed_rotations_per_piece[p]`. If `len(allowed) == 1`, this move is a no-op; resample move type (max 3 retries; if all 3 hit no-op pieces, fall through and continue — guarantees forward progress). Otherwise sample a new value from `allowed` excluding the current `rotations[p]`.

### Fitness

```python
def evaluator(pieces_in_order: list[Piece], per_piece_rotations: list[list[float]]) -> tuple[list[Placement], float, float]:
    return _blf_pack_nfp(
        pieces_in_order,
        fabric_width_mm,
        mode,
        fabric_grain_deg,
        presorted=True,
        override_rotations=per_piece_rotations,
        nfp_cache=worker_cache,
        shared_best_value=shared_best,
        # Other params: defaults
    )
```

`per_piece_rotations` here is `[[rotations[order[i]]] for i in range(N)]` — a per-piece *singleton list* containing only the chain's chosen rotation. This forces BLF to use that exact rotation (no internal rotation sweep) so SA fully controls the rotation axis. The list-of-lists shape is what the extended `override_rotations` parameter handles.

### Cooling schedule

```
T0 = T0_FACTOR * initial_marker_length   # e.g. 0.05 * 12249 ≈ 612
T_k = max(T_MIN, T0 * COOLING_ALPHA ** k)
```

`COOLING_ALPHA = 0.95` ⇒ after 100 iterations T ≈ 0.6 · T₀; after 200, T ≈ 0.36 · T₀; after 500, T ≈ 7.7e-12 · T₀ (effectively pure descent).

### Acceptance

```
delta = marker_new - marker_current
if delta < 0:                       accept
elif delta == 0:                    accept (no harm; allows lateral exploration)
else:
    if random() < exp(-delta / T_k): accept
    else:                            reject
```

`current` updates on accept; `best` updates whenever a strictly better marker is seen.

### Termination

```python
start_time = clock()  # captured immediately before the iteration loop
# ...
stop when ANY of:
  iteration_count >= iterations
  (max_time_s is not None) and (clock() - start_time >= max_time_s)
  is_cancelled()
```

`best` is returned regardless of which condition fired. If termination happens before iteration 1 completes (e.g., `max_time_s = 0.0`), `best` is the initial state (= the warm-start) — SA's monotone-non-worsening property still holds.

### Invalid candidates

If the evaluator raises `ValueError` (some piece can't fit at any rotation in `per_piece_rotations`), the move is rejected without updating `current` or `best`. Cooling still advances (T_k still decreases) so the chain doesn't get stuck in a region of frequent failures. This case is rare on the canonical workload but possible on degenerate inputs.

### Cross-worker pruning

Two integration points with the existing `multiprocessing.Value("d", float("inf"))` cutoff:

1. **Inner-BLF pruning (existing).** Each evaluator call passes `shared_best_value=_worker_shared_best` to `_blf_pack_nfp`, so the existing per-placement pruning fires inside BLF. A chain self-aborts the inner BLF when its candidate's partial marker exceeds the global best. SA treats the resulting `_PrunedRun` exception as "this neighbor is infinitely bad" → reject.
2. **Outer SA-loop pruning (new).** At the top of each SA iteration, after cooling step but before move selection: if `chain.best > shared_best.value` AND `T_k <= T_MIN`, the chain stops early. The bound here is: in the greedy regime (low T), the chain cannot beat its own current best, so if some other chain has already found a better global solution, this chain has no path to win. (At high T the chain may still escape upward and find a better region later, so we only prune in the greedy regime.)

The `disable_pruning=True` opt-out is honored: when set, neither integration point uses `shared_best_value` (`None` is passed through).

## 5. Parallelism, concurrency, cancellation

### Worker count

`K = _worker_count(effort)`. Same mapping as the warm-start phase: effort=1→1, effort=2→2, effort=3→cpu//2, effort=4→cpu-1, effort=5→cpu.

### Pool lifecycle

The warm-start phase keeps its existing pool ownership (opens, runs, exits the context manager). SA always opens its **own** `ProcessPoolExecutor` after warm-start completes — no attempt to reuse the warm-start pool. Rationale: simpler control flow, no entanglement between the two phases' lifecycle, and the spawn cost of K workers is amortized over the entire SA budget (which dominates wall-clock when `sa_iterations >= 100`).

SA opens a pool only when `K > 1 AND sa_iterations >= 50`. Below this threshold, the SA chain runs in-process (single-chain serial SA) regardless of `effort` — the Windows ~200–500ms per-worker spawn cost outweighs the parallelism win at very low iteration counts. The threshold is conservative; benches can refine it later.

### Worker initialization

Mirrors `_init_worker`:

```python
def _init_sa_worker(shared_best_value, warm_starts):
    global _worker_shared_best, _worker_warm_starts
    _worker_shared_best = shared_best_value
    _worker_warm_starts = warm_starts
```

Each worker submits one job: `_run_sa_chain(worker_index, iterations, max_time_s, seed_base + worker_index, fabric_width_mm, mode, fabric_grain_deg, allowed_rotations_per_piece, disable_nfp_cache)`.

`_run_sa_chain` reads `_worker_warm_starts[worker_index mod len(_worker_warm_starts)]`, builds a fresh NFP cache (or `{}` if `disable_nfp_cache`), binds the evaluator closure, and calls `sa.run_sa(...)`.

### NFP cache lifetime

One cache per worker, created at the start of `_run_sa_chain` and passed into every evaluator call. NFPs are keyed on `(base_id_a, rot_a, base_id_b, rot_b)` — none of which SA changes between iterations — so the cache fills over the first few hundred candidates and is fully reused afterwards. Expected per-iteration cost trajectory: ~3–5s cold → ~0.5–1s warm. Memory: the cache is bounded by `|pieces_distinct_base_ids|² × |rotations|²` entries. On the canonical workload (19 base ids, bi-grain → 2 rotations): worst case ~19² × 2² = 1444 entries. Negligible.

### Cancellation

Two levels (both reuse existing infrastructure):

1. **`is_cancelled()` checked between SA iterations.** Fast path: chain returns its current best-seen state immediately. The outer `auto_layout_polygon` still raises `CancellationError` after collecting whatever chains have reported.
2. **`kill_current_executor()` from `POST /cancel-layout`.** Terminates all worker processes. `future.result()` raises `BrokenProcessPool`; the existing translation in `auto_layout_polygon` converts to `CancellationError`. No new code path.

### Aggregation

Main process collects `SAResult` from each chain via `as_completed`. Picks the lowest-marker result; ties broken by lowest worker_index for determinism. The warm-start (`warm_starts[0]`) is always retained as a candidate — if every SA chain happens to never improve over its starting state (possible at very small `sa_iterations` like 1), warm-start is still returned. SA cannot lose to warm-start by construction.

## 6. Documentation updates (all in this PR)

### `docs/planning/PERFORMANCE.md`

- **§ 2 (Shipped improvements):** New subsection `### PR #N (this PR) — Simulated annealing meta-heuristic wrapper (opt-in)`. Mechanism description, opt-in invocation example, hyperparameter constants table, bench numbers (filled after bench runs).
- **§ 4 (Disabled-by-default approaches — code map + opt-in):** New `### 4.6 SA meta-heuristic (`sa_iterations > 0`)` with code pointers, opt-in invocation, the mutual-exclusion rule with clustering, and the constants reference.
- **§ 5.B (General nesting algorithm wins):** Replace the "GA / SA meta-heuristic wrapper" row's checkbox with `[~]` (in progress, SA done, GA pending) and add a row note pointing at § 4.6.
- **§ 6 (Findings + design decisions):** New `### 2026-05-31 — Simulated annealing wrapper shipped opt-in` entry with What/Why/Result/Decision/Mechanism-preserved-at sections. Result line fills in from bench output. Decision line documents whether G5 was hit.

### `docs/planning/BACKLOG.md`

Under "Phase 6 follow-ups — algorithm performance":

```
- [x] SA meta-heuristic wrapper (opt-in). PR #N. See PERFORMANCE.md § 2 + § 4.6 + § 6 [2026-05-31].
```

### `CLAUDE.md` (project root)

- Engine module list: add `core/layout/sa.py — SA driver for the meta-heuristic wrapper. Pure run_sa() function over (permutation × per-piece rotation) candidates; called from auto_layout_polygon when sa_iterations > 0.`
- `core/layout/heuristic.py` paragraph: append a sentence about `sa_iterations`, `sa_max_time_s`, `sa_seed` and the mutual-exclusion with `disable_clustering=False`.

## 7. Open risks

1. **G5 may not pass.** SA on permutation packing is sensitive to neighbor operators and cooling. The chosen defaults (T₀ = 5% of warm-start marker, α = 0.95, mixed-equal-weight moves) are reasonable but not tuned for this specific workload. If G5 fails, the PR still ships per the disposition; tuning becomes follow-up work.
2. **Multi-warm-start could under-perform vs single-warm-start.** Starting some chains from worse warm-starts (rank 4–7) might waste their iteration budget compared to all-chains-from-rank-0 with different seeds. Mitigation: the bench reports per-worker winning chain, so we can see whether non-rank-0 starts ever win; if never, a future PR simplifies to all-from-best.
3. **Wall-clock cap interacts awkwardly with parallel restarts.** If `sa_max_time_s` is set, each chain independently respects it — total wall-clock is approximately the cap (not K × cap). This is correct but might surprise a user expecting "total compute budget." Documented in the docstring.
4. **`override_rotations` polymorphism is fragile.** Detecting per-piece vs uniform shape via `isinstance(override_rotations[0], list)` is correct but brittle if a caller passes a heterogeneous list. Mitigation: the only new caller is SA's evaluator, which always builds the per-piece shape uniformly. Existing callers pass `list[float]` and are covered by regression tests.
5. **Per-piece rotation cap for no-grainline pieces is workload-blind.** `NO_GRAINLINE_ROTATION_CAP = 4` (angles `[0, 90, 180, 270]`) is a reasonable default for ET CAD inputs where grainlines are present on every piece. For inputs with no-grainline pieces (rare in production garment markers but possible), capping to 4 rotations loses search-space depth vs the BLF default (which iterates the full 360-degree set internally). The cap is necessary for SA tractability (otherwise a single rotation-flip move has 360 candidates per piece), but worth re-evaluating if a workload surfaces where no-grainline pieces dominate.

## 8. References

- **Predecessor spec:** `docs/superpowers/specs/2026-05-30-partial-clustering-design.md` (partial clustering, PR #10).
- **PERFORMANCE.md § 0:** binding priority rule (marker length > utilization > duration).
- **PERFORMANCE.md § 1:** the bar to beat (11699mm / 79.4% on `sample_2.dxf × 10` at fabric=1651, bi-grain).
- **PERFORMANCE.md § 5.B:** open follow-up row that this spec covers.
- **PERFORMANCE.md § 5.C:** bench-vs-GUI variance follow-up (related but independent — SA's correctness gates do not depend on the variance being resolved).
- **`engine/core/layout/heuristic.py::_blf_pack_nfp`:** the function SA's evaluator wraps. Existing meta-heuristic-friendly params (`override_rotations`, `shared_best_value`, `best_marker_so_far`, `nfp_cache`, `skip_validation`) inform the design.
- **`engine/core/layout/grain.py::allowed_rotations`:** authoritative source for per-piece allowed rotations; SA's hard-constraint compliance flows from this function.
- **Brainstorm decisions (chronological):**
  - Scope: SA only (not GA, not both with shared scaffolding).
  - Search space: piece-ordering × per-piece rotation from `allowed_rotations()`, with no-grainline rotation cap to 4.
  - Exposure: engine-Python opt-in only (no API, no UI).
  - Budget: iteration count + optional wall-clock cap; whichever fires first.
  - Parallelism: multi-restart with `K = _worker_count(effort)` chains.
  - Evaluator approach: Approach A — extend `_blf_pack_nfp` in place (vs new entry point or owning a separate inline BLF).
