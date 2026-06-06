# Expose the GA Optimizer to the GUI — Design

- **Date:** 2026-06-06
- **Branch:** `feat/expose-optimizer`
- **Status:** Approved (design) — pending spec review
- **Related:** PERFORMANCE.md § 4.6 (SA), § 4.7 (GA), § 6 [2026-06-05]; BACKLOG.md
  "Phase 6 follow-ups — algorithm performance" (the "Expose SA/GA to the GUI" item).

## 1. Problem & goal

The GA meta-heuristic (PR #13) reaches **11412.5mm / 81.39%** on the canonical
workload — a ~2.5% fabric saving over the warm-start (~11699mm) the app shows
today. But the win is unreachable from the app: `POST /auto-layout` never passes
`ga_generations`/`ga_max_time_s`, so every GUI run returns the warm-start.

**Goal:** let a non-technical Windows factory user opt into the stronger
optimizer from the app, with a time budget and a working Stop, and get a result
that beats the warm-start. **Default (unchanged request) must be bit-identical to
today.**

**Success criterion:** from the app, a user picks a layout quality, runs Auto
Layout, sees an elapsed timer, can Stop, and gets a result that beats the
warm-start; omitting the new field reproduces today's behavior exactly.

This is **API + frontend wiring + long-running-op UX**, not a new nesting
algorithm. The engine knobs already exist and are merged.

## 2. Background — current state

- `engine/api/main.py::_do_layout` (~L201) calls
  `auto_layout_polygon(pieces, fabric_width_mm, grain_mode, FABRIC_GRAIN_DEG,
  disable_nfp_cache=..., effort=effort)` — **no optimizer knobs**.
- `auto_layout_polygon` (heuristic.py ~L864) already accepts
  `ga_generations` / `ga_max_time_s` / `ga_seed` / `ga_config` (and the `sa_*`
  equivalents). GA ⊥ SA ⊥ clustering are enforced per-call via `ValueError`.
- `/cancel-layout` (main.py ~L259) sets the cancellation flag **and** calls
  `kill_current_executor()`, terminating the GA/SA process pool. `_run_ga_phase`
  translates the resulting `BrokenProcessPool` → `CancellationError`; the endpoint
  currently maps that to **HTTP 499 and discards everything**.
- `useAutoLayout.abort()` (frontend) posts `/cancel-layout` **and** aborts the
  fetch — the cancel plumbing is complete end-to-end.
- The cache dedup key (`cache.py::find_by_settings`) is
  `(filename, grain_mode, copies, fabric_width_mm)` — **no quality dimension**.
- Timing reality (190-piece canonical workload): warm-start ~14s; one BLF eval
  ~3.4s → one GA generation (pop 30) ≈ ~100s/island. PERFORMANCE.md's full sweep
  beat the bar at a **400s per-island cap** (11426.6mm). GA's time cap is checked
  **at the top of each generation** (`ga.py` ~L224) and the **initial population
  evaluates unconditionally first** (~L206–211) — so GA has a hard **~100s/island
  floor** on this workload regardless of budget. SA has no such floor (it improves
  one eval at a time from the warm-start).

## 3. Non-goals (YAGNI — notes for later, not this PR)

- **SA exposure.** SA stays fully intact in the engine (callable, tested,
  documented) but is **not** wired to the GUI — GA strictly beats it on real
  workloads (11426 vs 11517). If a "Better = SA" tier is ever wanted, the engine
  is already ready; it would be pure additional wiring.
- **Live best-so-far / % progress.** Requires per-generation progress reporting
  across the process pool plus a poll/stream endpoint. Out of scope; we show an
  elapsed timer only.
- **User-editable time budgets.** Budgets are fixed per tier (named engine
  constants), not surfaced to end users.
- **Export** (Phase 7) and any change to clustering/SA defaults.

## 4. Decisions (locked with the user 2026-06-06)

1. **Control UX:** a single **Fast / Better / Best** quality radio group
   (styled like the existing Parallel-effort radios).
2. **Tier mapping:** **GA-only, two budgets.** Better and Best both run GA,
   differing only by time budget. SA is not exposed.
3. **Stop semantics:** Stop returns the **warm-start best-so-far** (= the Fast
   result), not nothing.
4. **Progress:** **elapsed timer + indeterminate** ("Optimizing (Best)… M:SS
   elapsed"); no engine progress machinery.

## 5. API contract — `POST /auto-layout`

One new **optional** request field:

```
quality: "fast" | "better" | "best"   // default "fast"
```

- `"fast"` (or omitted) → the engine call is **identical to today** — no GA knobs
  are passed. This is the bit-identical-default guarantee.
- Invalid values → HTTP 422 (mirrors the existing `grain_mode` / `effort`
  validation style).

One new **optional** response field:

```
stopped: boolean   // default false
```

- `true` when a Better/Best run was cancelled and the engine fell back to the
  warm-start (see § 7). Frontend uses it for the status message.

Rationale: a single `quality` enum (not raw `ga_generations`/`ga_max_time_s` from
the frontend) keeps the quality→knob mapping in one place (engine), so tuning
budgets never touches the frontend and the "omitted = unchanged" contract stays
crisp.

## 6. Engine wiring (`engine/api/main.py::_do_layout`)

`_do_layout` maps `quality` → `auto_layout_polygon` arguments:

| quality | ga_generations | ga_max_time_s | effort |
| --- | --- | --- | --- |
| `fast`   | — (not passed) | — | user's `effort` radio (unchanged) |
| `better` | `GA_GENERATIONS_CAP` (12) | `BETTER_BUDGET_S` (180) | all-but-one core |
| `best`   | `GA_GENERATIONS_CAP` (12) | `BEST_BUDGET_S` (420) | all-but-one core |

Notes:

- **Generation cap = 12** (the proven acceptance value from `bench_ga.py`) so
  *small* jobs stop early when converged; the time budget binds on big jobs.
- **Time cap is a soft cap** (checked between generations) — on the 190-piece
  workload it overshoots by up to ~1 generation (~100s). The UI hint is written
  to set expectations ("takes minutes"). Better ≈ initial population + ~1 gen;
  Best ≈ initial population + ~4 gens.
- **Optimized tiers pass `effort=4`** (the existing "High (all but one)" level),
  overriding the Advanced effort radio; **Fast** still passes the user's radio
  value. More islands ⇒ better result, and wall-time doesn't grow because islands
  run in parallel; leaving one core free keeps the machine responsive during the
  multi-minute run. On low-core machines `_worker_count(4)` may resolve to 1 — GA
  then runs as a single serial island, which is correct and still beats the
  warm-start.
- **Fixed `ga_seed`** (`GA_GUI_SEED = 42`, matching the docs/acceptance bench) —
  deterministic per (input, quality), which makes cache dedup meaningful.
- Budget constants live as named module-level constants in `api/main.py` (or a
  small `optimizer_tiers.py` helper) so they are trivially tunable.

The mapping is the **only** new branching in `_do_layout`; the existing call
shape (pieces, fabric, grain, `FABRIC_GRAIN_DEG`, `disable_nfp_cache`) is
preserved.

### 6.1 Budget validation (implementation gate)

`BETTER_BUDGET_S` / `BEST_BUDGET_S` (180 / 420) are estimates from the 400s
sweep. During implementation, run a quick bench on `examples/input/sample_2.dxf`
× 10 (fabric=1651, bi-grain, all-but-one core) to confirm:

- **Best** reproduces the documented win (≤ 11699, ideally ~11430).
- **Better** still beats the bar (< 11699) within its budget.

Lock the two constants to the validated values. (Fixtures are git-ignored and
absent in the worktree — copy `examples/input/` in before benching.)

## 7. Stop semantics (warm-start fallback)

- In `auto_layout_polygon`, wrap the GA-phase call so cancellation yields the
  already-computed warm-start instead of propagating. Recommended mechanism: a
  dedicated exception that **carries the warm-start payload**, so the normal path
  keeps its `tuple[list[Placement], float, float]` return shape and only the
  cancel path is special:

  ```python
  # new, in cancellation.py (next to CancellationError):
  class StoppedWithWarmStart(Exception):
      def __init__(self, result): self.result = result  # (placements, marker, util)

  # in auto_layout_polygon, both the serial and parallel GA branches:
  if ga_generations > 0:
      try:
          return _run_ga_phase(best, warm_starts, ...)
      except CancellationError:
          # warm-start `best` is computed BEFORE the GA phase; GA never clusters,
          # so `best` is directly returnable.
          raise StoppedWithWarmStart(best)
  ```

  `_do_layout` catches `StoppedWithWarmStart` → unpack `e.result`, set
  `stopped=True`; catches bare `CancellationError` (Stop before warm-start
  existed) → 499 as today. The plan may pick a different shape, but the contract
  is fixed: **the API layer can distinguish a stopped-fallback from a completed
  run, and gets the warm-start payload on the former.** Note both the serial
  (~L1041) and parallel (~L1119) GA branches need the wrapper.
- The endpoint maps a stopped fallback to **HTTP 200** with `stopped=true` (not
  499).
- **Edge case (accepted):** if Stop arrives during the first ~15s *before* the
  warm-start exists, there is nothing to return → behaves like today (discard /
  499). Documented in the UI as "best so far," which is honest.
- **SA path unchanged:** this fallback applies to the GA path only (the only one
  the GUI uses). The SA path's existing cancel behavior is untouched.

## 8. Cache / dedup (`engine/core/layout/cache.py` + `main.py`)

- Add `quality` to the dedup key:
  `(filename, grain_mode, copies, fabric_width_mm, quality)`. Without this, a
  Best run would wrongly return a cached Fast result. With it, re-running Best
  (deterministic per seed) instantly returns the cached Best.
- **Stopped runs are cached under `quality="fast"`** — a stopped Better/Best run
  *is* the warm-start, which *is* the Fast result. So it (a) shows as a normal
  tab (the frontend's canvas is driven by cache entries), (b) dedups as Fast, and
  (c) does **not** shadow a future real Best run. The endpoint chooses the cache
  key's quality from the *actual* result (fast when stopped), not the request.
- Composes with the existing `include_effort_in_key` TEMP bench flag (quality is
  added unconditionally; effort remains conditional).

## 9. Frontend

- **New control:** `components/sidebar/QualityPanel.tsx`, rendered in its own
  `Section title="Layout quality"` in `App.tsx` (placed near the Auto Layout
  button). A Fast/Better/Best radio group mirroring the existing effort-radio
  styling, with time hints ("instant" / "~3 min" / "~7 min") and a one-line note:
  "Better/Best take a few minutes; click Stop to keep the best result so far."
- **State:** `App.tsx` holds `quality` (`"fast" | "better" | "best"`, default
  `"fast"`). `types/engine.ts` gains a `LayoutQuality` type and `quality` on the
  request + `stopped` on `AutoLayoutResponse`.
- **`useAutoLayout.runAutoLayout`** gains a `quality` argument, included in the
  POST body.
- **Progress:** while `autoStatus === "loading"`, show
  "Optimizing ({quality})… M:SS elapsed" next to the existing Stop button
  (frontend ticks from request start via a small interval). Fast runs finish too
  fast to matter; the timer is mainly for Better/Best.
- **Status messages:** success → marker/util as today; `stopped` →
  "Stopped — showing best result so far."
- The canvas remains read-only and engine-driven (unchanged).

## 10. Testing

**Engine**

- `_do_layout` quality mapping: `fast`/omitted passes **no** GA knobs (regression
  guard on the bit-identical default); `better`/`best` pass the expected
  `ga_generations` / `ga_max_time_s` / effort / seed (assert via a spy/monkeypatch
  on `auto_layout_polygon`).
- Invalid `quality` → 422.
- Stopped GA run returns the warm-start with `stopped=true` (HTTP 200), and is
  cached under `quality="fast"`.
- Cache dedup includes `quality`: Best and Fast with otherwise-identical settings
  do not collide; same-quality re-run dedups.
- Budget-validation bench (§ 6.1) — a `bench_*` script (soft TTL +
  always-emit-a-report, per the long-running-script-resilience pattern), not a
  PR-blocking unit test, but its numbers lock the constants.

**Frontend**

- `QualityPanel` renders all three options and reports selection.
- `useAutoLayout` includes `quality` in the request body.
- `App` wiring: default `quality="fast"`; stopped response → the stopped status
  message.

## 11. Touched modules (summary)

- `engine/api/main.py` — parse `quality`, map to knobs in `_do_layout`, handle
  the stopped fallback + `stopped` in the response, thread `quality` into the
  cache key.
- `engine/core/layout/heuristic.py` — catch `CancellationError` around the GA
  phase, return the warm-start as a stopped fallback.
- `engine/core/layout/cache.py` — `quality` in `find_by_settings` + on the cache
  entry.
- `engine/tests/...` — mapping/regression/stopped/cache tests + budget bench.
- `frontend/src/components/sidebar/QualityPanel.tsx` (new) + `.test.tsx`.
- `frontend/src/app/App.tsx` — `quality` state, QualityPanel section, elapsed
  timer, stopped status.
- `frontend/src/hooks/useAutoLayout.ts` — `quality` arg + body field.
- `frontend/src/types/engine.ts` — `LayoutQuality`, request/response field types.
- `docs/planning/PERFORMANCE.md` + `docs/planning/BACKLOG.md` — mark the item done
  and record the locked budgets.

## 12. Risks

- **Better may underdeliver.** Given the ~100s GA floor, a 180s budget yields
  ~1 generation. Mitigation: § 6.1 validates Better beats the bar; if it cannot
  within a tolerable wait, fall back to a two-tier (Fast/Best) shipment — a small
  frontend edit, no architectural change.
- **Long runs on modest hardware.** Mitigated by all-but-one-core and a clear
  "takes minutes + Stop" affordance that always returns a usable result.
- **Cache-key migration.** Adding `quality` to the key is backward-safe (old
  entries simply never match a new keyed lookup; FIFO evicts them normally).
