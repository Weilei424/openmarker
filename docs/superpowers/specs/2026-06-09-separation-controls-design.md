# Separation controls — strategy relabel + user budget + best-of-N-seeds

> Design spec. Status: **approved** (brainstorm 2026-06-09). Owner: engine + frontend.
> Extends: `docs/superpowers/specs/2026-06-07-separation-engine-phase2-design.md` (the Ultra tier).
> Lands on `feat/separation-phase2` (PR #16, unmerged).

## 1. Context

Phase 2 shipped the Separation ("Ultra") tier with a fixed 600s budget and single seed. The
1200s measurement (PERFORMANCE.md §6 [2026-06-09]) showed budget has diminishing returns, and
that a different *lever* — best-of-N-seeds (sparrow's search is stochastic per `-s`) — is a
better quality-per-minute path. This change exposes the strategy names, a user-set budget, and
best-of-N-seeds in the GUI.

## 2. Decisions (brainstorm 2026-06-09)

| Decision | Choice |
|---|---|
| Strategy labels | **Raw algorithm names** (qualifier only to disambiguate the two GA tiers) |
| GA tiers | **Keep both**, qualified ("— quick" / "— thorough") |
| Best-of-N model | **Parallel**, keep shortest valid marker |
| Budget control | Separation only; **min 360 / max 1500 / default 600** seconds |
| Seeds control | Separation only; **1–4, default 1** |

## 3. QualityPanel labels (display-only; API `quality` keys unchanged)

| `quality` | New label | Engine |
|---|---|---|
| `fast` | **NFP-BLF** | warm-start BLF (no meta-heuristic) |
| `better` | **Genetic Algorithm — quick** | GA, 180s |
| `best` | **Genetic Algorithm — thorough** | GA, 420s |
| `ultra` | **Separation (sparrow)** | sparrow + §4/§5 controls |

Keeping the `quality` enum (`fast/better/best/ultra`) avoids churning the API, cache key, GA
budget map, and existing tests — only the frontend display strings change.

## 4. Separation controls (frontend)

Rendered only when `quality === "ultra"` (a conditional block beneath the radios, styled like the
existing Parallel-effort section):
- **Time budget** — integer-seconds text input. Frontend clamps to `[360, 1500]` on blur/submit;
  default **600**. The API independently validates (422 if out of range).
- **Best-of-N seeds** — radio `1 | 2 | 3 | 4`, default **1**, like the effort radio.

`App.tsx` holds `ultraBudgetS` (default 600) and `ultraSeeds` (default 1) and threads them through
`useAutoLayout` into the POST body. They participate in the request's cache identity.

## 5. Engine — best-of-N + multi-process kill (`core/layout/separation.py`)

- `run_separation_layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, budget_s,
  seed=42, n_seeds=1)`:
  - `n_seeds == 1` → today's behavior (one `_run_sparrow`).
  - `n_seeds > 1` → launch `n_seeds` `_run_sparrow` calls **concurrently** via a
    `ThreadPoolExecutor(max_workers=n_seeds)`, seeds `seed … seed+n_seeds-1` (each call already
    uses its own `TemporaryDirectory`, so no scratch collision). Reconstruct + validate each
    result; **return the shortest-marker VALID** one. If every attempt is invalid/empty → raise
    `ValueError` (aggregate the reasons). `CancellationError` from any worker propagates as
    cancellation.
- **Multi-process kill registry:** replace the single `_current_sparrow: Popen | None` with
  `_current_sparrows: set[Popen]`. `_run_sparrow` adds its `Popen` on start and discards it in
  `finally`; `kill_current_sparrow()` snapshots the set under the lock and `terminate()`s every
  member. This makes Stop kill **all** N concurrent attempts (today it would kill only one).
- The per-attempt validation stays the hard-fail backstop; best-of-N never returns an invalid
  marker (invalid attempts are discarded; if all invalid, it fails loudly).

## 6. API (`engine/api/main.py`)

- New optional body fields (only meaningful for `quality="ultra"`):
  - `ultra_budget_s`: int, **360–1500**, default `QUALITY_BUDGETS_S["ultra"]` (600); 422 if out of range.
  - `ultra_seeds`: int, **1–4**, default 1; 422 if out of range.
- `_do_layout` ultra branch → `run_separation_layout(..., budget_s=ultra_budget_s, seed=GA_GUI_SEED,
  n_seeds=ultra_seeds)`.
- **Cache:** add `ultra_budget_s` + `ultra_seeds` to `CachedLayout` and the `find_by_settings`
  dedup key so requests differing only in budget/seeds get distinct cached entries. Non-ultra
  requests pass the defaults (600, 1), so they remain mutually consistent.
- Cancellation: `/cancel-layout` already calls `kill_current_sparrow()`, which now kills all N.

## 7. Concurrency / UX note

Each sparrow uses 3 worker threads (`jagua-rs`/rayon, compiled default). N=4 → ~12 threads, which
oversubscribes a typical 8-core machine; sparrow time-slices, so wall ≈ the chosen budget (not
N×). Best-of-N is the recommended quality lever over a longer single budget.

## 8. Testing

- **Engine unit:** `run_separation_layout` best-of-N selection — monkeypatch `_run_sparrow` to
  return several canned solutions with different markers; assert the shortest VALID one is
  returned, and that an all-invalid set raises `ValueError`. Multi-kill registry — register two
  dummy procs, assert `kill_current_sparrow()` terminates both.
- **API:** `ultra_budget_s` / `ultra_seeds` validation (422 at 359 / 1501 / 0 / 5), routing passes
  them through (stub `run_separation_layout`, assert args), cache distinguishes differing
  budget/seeds.
- **Frontend (vitest):** Separation selected → budget input + seeds radio render and clamp; other
  tiers → controls hidden. `npm run build` clean.
- **Bench (optional):** N=3 @600s vs N=1 @600s on sample_2×10 to record the seeds lever in
  PERFORMANCE.md.

## 9. Acceptance

From the GUI: the four strategies show their algorithm names; selecting **Separation (sparrow)**
reveals a 360–1500s budget box + a 1–4 seeds selector; a run honors them, returns a valid marker
(best of N), is cancellable (all attempts killed), and caches per (budget, seeds). All engine +
frontend tests green.
