# GA meta-heuristic wrapper — design spec (2026-06-05)

**Status:** approved (brainstorming) → ready for implementation plan.

**Goal:** Add an opt-in Genetic Algorithm meta-heuristic that wraps the NFP-BLF
packer as its fitness function, sitting alongside the already-shipped SA
meta-heuristic. Engine-Python-only, off by default. Must beat the bar
(11699 mm / 79.4 % on the canonical workload) — ideally beat SA's best
(~11517 mm) — across ≥3 seeds, **or** ship with a documented gap analysis
explaining why GA underperforms SA on this workload.

**Non-goals (this PR):** memetic/local-search refinement of offspring; cross-island
migration; multi-warm-start island seeding; API/UI exposure; grain-compatible
mirroring. All are future-work items (see §11).

---

## 1. Context

The engine already has an opt-in SA meta-heuristic (`engine/core/layout/sa.py`
+ orchestration in `engine/core/layout/heuristic.py`). After the 2026-06-04
grain lock, the warm-start (best-of-4 sort strategies) is already 11699.4 mm —
the bar — so any meta-heuristic has to improve on an already-good start. SA's
win came specifically from per-piece **rotation-flip** local moves
(`MOVE_WEIGHTS rotation_flip=3.0`, see PERFORMANCE.md §6 [2026-06-05]).

GA reuses the SA scaffolding wherever possible:
- **Fitness:** `heuristic.py::_blf_pack_nfp(pieces_in_order, fabric_width_mm,
  mode, fabric_grain_deg, nfp_cache=…, override_rotations=…, presorted=True,
  skip_validation=True) → (placements, marker, util)` — the exact evaluator SA
  chains call (`heuristic.py:146-159`).
- **Seed material:** the `WarmStart` list (best-of-4 sort strategies), sorted by
  marker — the same pool SA chains initialize from.
- **Parallelism:** the existing `ProcessPoolExecutor` + `initializer`/`initargs`
  worker pattern. `_run_sa_phase` / `_run_sa_chain` / `_init_sa_worker` are the
  templates.

## 2. Decisions (locked in brainstorming)

1. **Pure GA** (selection + crossover + mutation + elitism). Memetic refinement
   is a documented follow-up, not in this PR.
2. **Island model:** K independent populations, one per worker
   (K = `_worker_count(effort)`), each with its own RNG seed. Mirrors SA's K
   independent chains. No cross-island migration.
3. **Budget API:** `ga_generations` is the on-switch + generation cap (mirrors
   `sa_iterations`); `ga_max_time_s` + `ga_seed` mirror SA. `population_size`
   and all rates live in a `GAConfig` dataclass (mirrors `SAConfig`).
4. **No cross-island shared-cutoff pruning** (refinement during spec-writing —
   see §7). GA fitness evals are always full → GA is **deterministic per seed**.

## 3. Genome (individual)

Identical to SA's runtime state:

- `order: list[int]` — a permutation of `[0, N)`, indices into `blf_input`.
- `rotations: list[float]` — length N; `rotations[i]` is the rotation applied to
  `blf_input[i]`, constrained to `allowed_rotations_per_piece[i]`.

**Indexing convention (must match SA):** `rotations` is indexed by piece position
in the *unsorted* `blf_input`, NOT by position in `order`. The evaluator is
called with parallel arrays built positionally from `order`:

```python
pieces_in_order = [pieces[idx] for idx in order]
per_piece_rots  = [[rotations[idx]] for idx in order]   # singleton lists (forced rotation)
placements, marker, util = evaluator(pieces_in_order, per_piece_rots)
```

Fitness = `marker` (lower is better). All N pieces are placed by BLF; an
infeasible evaluation surfaces as `ValueError` → treated as `+inf` fitness.

## 4. Initial population (per island)

Island `i` (worker index `i`) seeds from `warm_starts_sorted[i % len(warm_starts_sorted)]`
— same selection rule as `_run_sa_chain` (`heuristic.py:133`). Mode bypass: the
evaluator passes the warm-start's `mode` to `_blf_pack_nfp`, but `override_rotations`
+ `skip_validation=True` bypass grain logic, so rotations are applied verbatim
(identical to SA).

- **Individual 0** = the warm-start verbatim (`order` from `sorted_pieces`,
  `rotations` from `rotations_used`, remapped to `blf_input` indices exactly as
  `_run_sa_chain` does at `heuristic.py:137-141`).
- **Individuals 1..P−1** = mutated copies of individual 0 (apply 1–3 random
  moves via the §5 mutation operator) for initial diversity.

This guarantees the island's best can never regress below its warm-start
(individual 0 is always evaluable and is protected by elitism).

Per-island RNG: `random.Random(ga_seed + worker_index)`.

## 5. Operators

All operators are pure (no input mutation) and live in `ga.py`. RNG is passed in.

### 5.1 Selection — tournament
```python
def _tournament_select(pop_indices, fitnesses, k, rng):
    contenders = rng.sample(range(len(pop_indices)), min(k, len(pop_indices)))
    return min(contenders, key=lambda j: fitnesses[j])   # lowest marker wins
```
Default `tournament_size = 3`. Works directly on marker length (minimization);
no fitness scaling needed.

### 5.2 Crossover — Order Crossover (OX) on `order`
Applied with probability `crossover_rate` (default 0.9); else the child copies
the first selected parent.
```python
def _order_crossover(p1_order, p2_order, rng):
    n = len(p1_order)
    a, b = sorted(rng.sample(range(n), 2))
    child = [None] * n
    child[a:b+1] = p1_order[a:b+1]
    taken = set(p1_order[a:b+1])
    fill = [g for g in p2_order if g not in taken]
    f = 0
    for i in range(n):
        if child[i] is None:
            child[i] = fill[f]; f += 1
    return child   # always a valid permutation
```

### 5.3 Crossover — uniform per-gene on `rotations`
```python
def _uniform_rotation_crossover(r1, r2, rng):
    return [r1[i] if rng.random() < 0.5 else r2[i] for i in range(len(r1))]
```
Both parents carry valid rotations per piece, so the child is valid. Independent
of OX because rotations are piece-indexed, not position-indexed.

### 5.4 Mutation — reuse SA's move operators
Applied with probability `mutation_rate` (default 0.2) per offspring. One move
per mutation event, sampled via `sa._sample_move_type(rng, cfg.mutation_move_weights)`:
- `swap` → `sa._swap_move(order, rng)`
- `reverse` → `sa._reverse_move(order, rng)` (uses sa's default window fraction)
- `rotation_flip` → `sa._rotation_flip_move(rotations, allowed_rotations_per_piece, rng)`
  (returns unchanged + `None` when no piece has ≥2 options; treat as no-op)

`mutation_move_weights` defaults to `{"swap":1.0,"reverse":1.0,"rotation_flip":3.0}`
— rotation_flip favored, matching SA's tuning win on this workload. Reusing
`sa.py`'s operators is the primary scaffold reuse.

### 5.5 Elitism
The top `elitism_count` (default 2) individuals by fitness are carried to the
next generation unchanged. Guarantees the island best is monotone non-worsening
across generations.

## 6. `run_ga` driver (`ga.py`)

Pure-functional, evaluator injected (testable with a stub), mirroring
`sa.run_sa`.

```python
def run_ga(
    warm_start_order: list[int],
    warm_start_rotations: list[float],
    pieces: list[Piece],
    allowed_rotations_per_piece: list[list[float]],
    generations: int,
    max_time_s: float | None,
    seed: int,
    evaluator: Callable[[list[Piece], list[list[float]]],
                        tuple[list["Placement"], float, float]],
    clock: Callable[[], float] = time.perf_counter,
    config: "GAConfig | None" = None,
) -> GAResult:
```

Loop:
```
cfg = config or GAConfig()
rng = Random(seed); start = clock()
if generations == 0:                      # fast path; phase aggregator keeps warm_start_best
    return GAResult(warm_start_order, warm_start_rotations, [], inf, 0.0, 0, 0)

population = [warm_start] + [mutate(warm_start) for _ in range(P-1)]
fitnesses, placements = evaluate_all(population)      # P BLF evals; ValueError → +inf
best = argmin(fitnesses)
gens_done = 0; evals = P
for gen in range(generations):
    if is_cancelled(): break
    if max_time_s is not None and clock()-start >= max_time_s: break
    elites = top elitism_count individuals (by fitness)
    next_pop = list(elites)
    while len(next_pop) < P:
        p1 = tournament(); p2 = tournament()
        if rng.random() < crossover_rate:
            child_order = OX(p1.order, p2.order)
            child_rot   = uniform_rot(p1.rot, p2.rot)
        else:
            child_order, child_rot = copy(p1.order), copy(p1.rot)
        if rng.random() < mutation_rate:
            child_order, child_rot = mutate(child_order, child_rot)
        f, pl = evaluate(child_order, child_rot)         # ValueError → +inf; evals += 1
        next_pop.append((child_order, child_rot, f, pl))
    population = next_pop
    update best; gens_done += 1
return GAResult(best.order, best.rot, best.placements, best.marker, best.util, gens_done, evals)
```

`GAResult` (NamedTuple): `best_order, best_rotations, best_placements,
best_marker, best_util, generations_executed, evaluations`.

Infeasible evals: the evaluator may raise `ValueError` (BLF could not place) —
caught per individual, fitness = `+inf`, placements = `[]`. Such an individual
stays in the population for that generation but is never selected as elite and
loses tournaments; it is regenerated next generation.

## 7. Determinism & the no-pruning decision

SA passes a shared `multiprocessing.Value` cutoff into `_blf_pack_nfp`, which
aborts (`_PrunedRun`) once a placement's partial marker reaches the cutoff. BLF
partial marker is monotone non-decreasing and the final marker is its max, so
that pruning only ever fires on runs whose **final marker ≥ the current global
best**.

For a *population* method this is harmful: offspring slightly worse than the
global best are exactly the recombination stepping-stones GA depends on.
Pruning them to `+inf` would collapse each island to its elites and stall the
search. Therefore **GA does not pass `shared_best_value` to the evaluator** —
every offspring gets a full BLF eval.

Consequences:
- **GA is deterministic per seed.** Warm-starts are deterministic (pruning is
  result-preserving, PERFORMANCE.md §5.C), each island is `Random(ga_seed+i)`
  with no timing-dependent shared state, and aggregation is order-independent
  (min by marker, tie-break by lowest worker index). This fixes SA's documented
  non-determinism wart for GA — G3 can assert exact reproducibility.
- `auto_layout_polygon(disable_pruning=…)` has no effect on GA results (GA never
  prunes its own evals; the warm-start phase's pruning is result-preserving).
- The `multiprocessing.Value` cutoff plumbing is **not** part of `_run_ga_phase`.

## 8. Orchestration (`heuristic.py`)

New symbols, each mirroring its SA counterpart:

- **GA worker globals** (module-level, set by `_init_ga_worker`): warm_starts,
  blf_input, fabric_width_mm, fabric_grain_deg, allowed_rotations_per_piece,
  disable_nfp_cache, ga_config. (No shared_best.)
- **`_init_ga_worker(warm_starts, blf_input, fabric_width_mm, fabric_grain_deg,
  allowed_rotations_per_piece, disable_nfp_cache, ga_config)`** — sets the globals.
- **`_run_ga_chain(worker_index, generations, max_time_s, seed) -> GAResult|None`**
  — picks `warm_starts[worker_index % len]`, remaps order/rotations to blf_input
  indices, builds the evaluator closure (per-worker `nfp_cache` reused across
  evals; `_blf_pack_nfp(..., override_rotations=…, presorted=True,
  skip_validation=True)`; **no** `shared_best_value`; `_PrunedRun` cannot occur
  but is defensively translated to `ValueError`), calls `run_ga`.
- **`_run_ga_phase(warm_start_best, warm_starts, blf_input, fabric_width_mm,
  grain_mode, fabric_grain_deg, ga_generations, ga_max_time_s, ga_seed, effort,
  disable_nfp_cache, clusters, ga_config=None)`** — mirrors `_run_sa_phase`:
  1. `cfg = ga_config or GAConfig()`
  2. sort warm_starts by marker; defensive empty-list passthrough (expand
     clusters on `warm_start_best` if `clusters`).
  3. compute `allowed_rotations_per_piece` from the user's `grain_mode`, capping
     no-grainline pieces to `cfg.no_grainline_rotation_cap` evenly-spaced angles
     (identical to `_run_sa_phase:1060-1067`).
  4. `workers = _worker_count(effort)`; `use_pool = workers > 1 and ga_generations >= 1`.
  5. **serial:** `_init_ga_worker(...); result = _run_ga_chain(0, …, ga_seed)`.
     **parallel:** `ProcessPoolExecutor(initializer=_init_ga_worker, initargs=…)`,
     submit K chains (`seed = ga_seed + k`), collect via `as_completed`. Reuse
     `_set_current_executor` + `BrokenProcessPool → CancellationError` handling
     exactly as `_run_sa_phase`. (No shared-Value updates.)
  6. **aggregate:** start from `warm_start_best` (always retained); take the best
     of {warm_start_best} ∪ island results by `(marker, worker_index)`. Expand
     clusters on the chosen placements if `clusters` is non-empty.

`auto_layout_polygon` wiring (mirrors the two SA call sites at
`heuristic.py:921-925` and `:992-996`): after warm-start completes, if
`ga_generations > 0`, build `warm_starts` (already built for SA path; reuse the
same retention) and call `_run_ga_phase(...)`. The warm-start retention block
(`heuristic.py:901, 945`) currently keys off `sa_iterations > 0`; widen it to
`sa_iterations > 0 or ga_generations > 0`.

## 9. Public API + `GAConfig`

`auto_layout_polygon` gains (after the SA params):
```python
ga_generations: int = 0,
ga_max_time_s: float | None = None,
ga_seed: int = 0,
ga_config: "GAConfig | None" = None,
```

Validation (alongside the existing SA checks at `heuristic.py:866-870`):
- `ga_generations < 0` → `ValueError`.
- `ga_generations > 0 and not disable_clustering` → `ValueError` (mirrors SA;
  combining a meta-heuristic with clustering is future work).
- `ga_generations > 0 and sa_iterations > 0` → `ValueError` (one meta-heuristic
  per call).

`GAConfig` (`ga.py`; field defaults = module constants, single source of truth,
picklable so it crosses the `ProcessPoolExecutor` boundary via `initargs`):
```python
@dataclass
class GAConfig:
    population_size: int = POPULATION_SIZE              # 30
    crossover_rate: float = CROSSOVER_RATE             # 0.9
    mutation_rate: float = MUTATION_RATE               # 0.2
    tournament_size: int = TOURNAMENT_SIZE             # 3
    elitism_count: int = ELITISM_COUNT                 # 2
    no_grainline_rotation_cap: int = NO_GRAINLINE_ROTATION_CAP   # 4 (reuse sa's value)
    mutation_move_weights: dict = field(default_factory=lambda: dict(MUTATION_MOVE_WEIGHTS))
                                                       # {"swap":1.0,"reverse":1.0,"rotation_flip":3.0}
```
Engine-Python-only — not exposed via `POST /auto-layout` or the React UI.
Default (`ga_generations=0`) is bit-identical to today's behavior.

> The numeric defaults (population 30, crossover 0.9, mutation 0.2, generations
> bench values) are **starting points**; §10's sweep tunes them and bakes the
> winning default before merge.

## 10. Success criterion, bench & sweep

- **`engine/tests/bench_ga.py`** (mirrors `bench_sa.py`) on the canonical
  workload — sample_2.dxf × 10, fabric=1651, bi-grain @ `FABRIC_GRAIN_DEG`,
  effort=5. PR-blocking gates:
  - **G1** result valid, all 190 pieces placed.
  - **G2** GA best ≤ warm-start (monotone, never regresses).
  - **G3** same-seed determinism — **exact** equality across two runs (stronger
    than SA's caveated G3, thanks to §7).
  - **G4** default (no `ga_*` kwarg) == warm-start baseline (GA off by default).
  - **G5** beat the bar (11699 mm) **strictly**.
- **`engine/tests/bench_ga_sweep.py`** — reuses `bench_sa_sweep.py`'s harness
  (soft `SWEEP_TTL_S` checked between rows, `PER_ROW_CAP_S` via `ga_max_time_s`,
  per-row JSONL streaming, `_write_report` in a `finally` block, `--smoke`/`--ttl`
  flags). Phases: single-axis screening (population_size, crossover_rate,
  mutation_rate, generations, mutation_move_weights) → combine bests → multi-seed
  validation (≥3 seeds).
- **Definition of done:** GA beats 11699 mm (ideally beats SA's ~11517 mm)
  strictly on ≥3 seeds → bake the winning `GAConfig` default and make G5
  PR-blocking. **OR** GA cannot beat the bar → ship opt-in with G5 demoted to
  informational and a **documented gap analysis** in PERFORMANCE.md §6 (what was
  swept, best achieved, and why GA trails SA — most likely: SA's targeted
  rotation-flip hill-climb exploits this workload's narrow per-piece grain choice
  more efficiently than GA's broader recombination at equal eval budget).

## 11. Testing

- **`engine/tests/unit/test_ga.py`** (stub evaluator, fast):
  - OX produces a valid permutation (no dupes/omissions); slice preserved.
  - uniform rotation crossover yields only values present in the parents (⊆ allowed).
  - tournament selection returns the lowest-marker contender.
  - elitism preserves the best individual across a generation.
  - mutation dispatches to the sa move operators per `mutation_move_weights`.
  - `GAConfig` defaults == module constants; `GAConfig()` picklable.
  - `run_ga` best is monotone non-worsening vs the seeded warm-start.
  - `generations=0` fast path returns without evaluator calls.
  - `max_time_s` terminates early; `is_cancelled()` breaks the loop.
  - determinism: two `run_ga` calls, same seed/inputs → identical `GAResult`.
- **`engine/tests/unit/test_heuristic.py`** (integration, real BLF, tiny input):
  - opt-in GA path returns a valid layout; ≤ warm-start.
  - default-off regression guard (no `ga_*` → identical to baseline).
  - both `ValueError` exclusions (`ga_generations>0` with clustering; with `sa_iterations>0`).
  - parallel GA determinism: same `ga_seed` → identical marker across two calls.

## 12. Docs

- PERFORMANCE.md: new **§4.7** (GA code map + opt-in invocation, mirroring §4.6);
  **§6 [2026-06-05]** entry (what/why/result/decision); flip the §5.B row's "GA
  half deferred" note to shipped (win or gap analysis).
- BACKLOG.md: check off the GA follow-up under Phase 6.

## 13. File manifest

**Create:**
- `engine/core/layout/ga.py` — constants, `GAConfig`, `GAResult`, operators, `run_ga`.
- `engine/tests/unit/test_ga.py`
- `engine/tests/bench_ga.py`
- `engine/tests/bench_ga_sweep.py`
- `docs/superpowers/specs/2026-06-05-ga-meta-heuristic-design.md` (this file)

**Modify:**
- `engine/core/layout/heuristic.py` — GA worker globals, `_init_ga_worker`,
  `_run_ga_chain`, `_run_ga_phase`, `auto_layout_polygon` params + validation +
  wiring + widened warm-start retention.
- `engine/tests/unit/test_heuristic.py` — GA integration tests.
- `docs/planning/PERFORMANCE.md`, `docs/planning/BACKLOG.md`.

## 14. Out of scope / future work

- **Memetic GA** (SA-style local search on offspring) — the most likely path to
  beat SA if pure GA falls short. Reuses this scaffolding + sa.py moves.
- **Cross-island migration** (periodic best-individual exchange).
- **Multi-warm-start island seeding** (mixed-mode initial populations).
- **GA exposure via API/UI.**
- **Grain-compatible mirroring** as an extra rotation candidate (PERFORMANCE.md §5.B).
