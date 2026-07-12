# Sequential best-of-N Ultra — productization (GO follow-up from PR #23)

> Design spec. Status: **approved** (brainstorm 2026-07-12). Owner: engine (layout) + api + frontend.
> Origin: PR #23 (§ 6 [2026-07-10]) — the seq3 policy (sequential best-of-3 warm runs
> @2500s, keep best) DECISIVELY crossed the 10599mm commercial target (mean 10542.3,
> 3/3 fresh-seed reps below). This round wires that policy into the product.
> **Round record: `docs/planning/BACKLOG.md` section ONLY — no PERFORMANCE.md entry**
> (feature round, not experiment round; per user 2026-07-12).

## 1. Context

Production Ultra today runs best-of-N attempts **in parallel** (`run_separation_layout`,
`ThreadPoolExecutor`, N ≤ 4 processes × 3 rayon threads): heavy on a factory PC,
subject to core contention, and **not** the configuration the campaign validated.
Worse, a cancel **discards completed attempts** (`if cancelled: raise` precedes the
keep-best) and the frontend aborts the HTTP request on Stop, so no partial could
reach the user anyway — while the QualityPanel hint already promises "Click Stop to
keep the best result so far."

This round replaces parallel with the measured-decisive **sequential** orchestration
(one 3-thread process at a time, each member at full budget), makes Stop return the
best completed member, and gives multi-hour runs real progress. No algorithm change —
it composes already-measured pieces, so **no benches**; test-driven feature work only.

## 2. Decisions (brainstorm 2026-07-12)

| Decision | Choice |
|---|---|
| Execution model | Sequential REPLACES parallel in `run_separation_layout` (the parallel path is deleted). Signature unchanged; `budget_s` stays **per-member** (total = N × budget); member seeds stay `seed..seed+N−1` (API passes seed=42); ONE shared warm start built before the loop (unchanged gating: `budget_s >= WARM_START_MIN_BUDGET_S`) |
| Stop transport | **Synchronous response on cancel** (approach 1): frontend Stop for Ultra posts `/cancel-layout` and KEEPS the fetch open; the engine kills the in-flight child, the loop stops, and `run_separation_layout` returns the best COMPLETED member; the API answers the open request 200 + `stopped_early: true`. Zero completed members → `CancellationError` → 499 (unchanged). Rejected alternatives: cache-mediated partials (racy, poisons the settings-keyed cache), async job API (rewrites every tier's flow — future work if ever needed) |
| Member failure ladder | Member `ValueError` (invalid/empty output) → record, continue to the next member; all members invalid → `ValueError` (unchanged → 400). `n_seeds=1` behaves exactly as today (single attempt; no partial semantics mid-member) |
| Progress | New ~30-line `core/layout/progress.py`: module-level snapshot (`set_progress` / `get_progress` / `clear_progress`), updated by the loop at member boundaries. New `GET /layout-progress`. Single-flight assumption documented (the app already has ONE global cancel flag; the desktop app runs one layout at a time) |
| Cache rule | `stopped_early` results are cached under the **truthful settings key**: the entry is stored with `ultra_seeds = members_completed` — a stop after k of N members is exactly the best-of-k artifact (same seeds `42..42+k−1` a real best-of-k run uses). The requested-N key stays unoccupied (a later full best-of-N re-runs), AND the result stays displayable (the canvas renders from the cache via the returned entry id — an uncached result would be invisible; amendment 2026-07-12, discovered during planning). Edge: if an invalid member made completed < attempted, the truthful-key claim is approximate — acceptable for a session cache. Full-completion caching + dedup key unchanged |
| API validation | Unchanged: `ultra_budget_s` 180–2500 (per member), `ultra_seeds` 1–4 |
| Frontend Stop | `abort()` becomes quality-aware: Ultra → post `/cancel-layout` only (fetch stays open; resolves 200-with-flag or 499→aborted). Other qualities → abort the fetch as today |
| Frontend progress | `useLayoutProgress` hook polls `GET /layout-progress` every 2000ms only while an Ultra run is loading; statusbar shows `Separation run {member} of {n} — {mm:ss} elapsed — best so far {marker} mm` (best-so-far omitted until a member completes) |
| GUI copy | QualityPanel: seeds label → **"Runs (keep best of N)"**; add a computed total-time hint `Total ≈ {N × budget, as m s}` under the runs radio. Stop-with-result statusbar: `Stopped — kept best of {k} completed run(s).` The existing "Click Stop to keep the best result so far" hint becomes true |
| Hard constraints | Unchanged everywhere: grain enforced both ways, no mirror, no tilt, edges touchable, `_validate_layout` gates every member |

## 3. Component design

### 3.1 Engine — `core/layout/separation.py`

`run_separation_layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
budget_s, seed=42, n_seeds=1, warm_start=True)` → `(placements, marker, util)`:

1. Build items + instance + (gated) warm start ONCE — unchanged.
2. `seeds = [seed + k for k in range(max(1, n_seeds))]`.
3. Sequential loop over members: `set_progress(...)` at each member start;
   `_solve_one(...)` (unchanged helper: run → reconstruct → validate → metrics);
   on success update best (min marker) + `members_completed` + `best_marker_mm`;
   on `ValueError` record and continue; on `CancellationError` break.
4. Exit: cancelled AND best exists → **return best**; cancelled AND no best →
   raise `CancellationError`; no valid results → raise `ValueError`; else
   return best. On EVERY exit path the loop's last act is writing a **final
   snapshot** (`active: False`, counts preserved, `stopped_early` set) — it
   never wipes fields, so the API reads the outcome from the snapshot right
   after the call; a fresh run simply overwrites it. (`clear_progress()`
   exists for test isolation only, not called in the run path.)

### 3.2 Engine — `core/layout/progress.py` (new)

Snapshot dict (single module-level reference, atomic swap):
`{"active": bool, "member": int, "n_members": int, "members_completed": int,
"best_marker_mm": float | None, "budget_s": float, "run_started_ts": float,
"member_started_ts": float, "stopped_early": bool}` — timestamps are epoch
seconds; the API endpoint computes `total_elapsed_s` / `member_elapsed_s` at
read time. Idle/fresh state: `{"active": False}` plus whatever the last run
left (harmless; frontend only polls during a run).

### 3.3 API — `engine/api/main.py`

- Ultra branch: after `run_separation_layout` returns, read the final snapshot;
  the success response gains `"stopped_early": bool, "members_completed": int,
  "members_requested": int` (ultra responses only). When `stopped_early`, the
  cache entry is stored with `ultra_seeds = members_completed` (truthful key —
  see § 2 cache rule); otherwise unchanged. 499/400 paths unchanged.
- New route `GET /layout-progress` → the snapshot + computed elapsed fields
  (`{"active": false, ...}` when idle). No auth/state beyond the module var.

### 3.4 Frontend

- `hooks/useAutoLayout.ts`: hold the in-flight quality in a ref;
  `abort()` → if quality === "ultra": POST `/cancel-layout` only; else abort
  controller as today. Outcome gains `stoppedEarly?: boolean` and
  `membersCompleted?: number` mapped from the 200 response; a 499 maps to the
  existing `aborted` outcome.
- `hooks/useLayoutProgress.ts` (new): `useLayoutProgress(active: boolean)` →
  polls every 2000ms while `active`, returns the latest snapshot or null;
  stops polling and clears when `active` flips false.
- `app/App.tsx`: pass quality-awareness to abort; statusbar wiring for the
  progress line and the stop-with-result message
  (`Stopped — kept best of {k} completed run(s).`).
- `components/sidebar/QualityPanel.tsx`: label change + total-time hint
  (derived from `ultraSeeds × ultraBudgetS`, rendered as `Total ≈ {m}m {s}s`).
- `types/engine.ts`: optional `stopped_early` / `members_completed` /
  `members_requested` on `AutoLayoutResponse`.

## 4. Testing

- **Engine unit (stubbed solver — monkeypatch `_solve_one` or `_run_sparrow`):**
  members run sequentially in seed order; keep-best across members; invalid
  member skipped, run continues; cancel mid-run returns best-so-far; cancel
  before any completion raises `CancellationError`; all-invalid raises
  `ValueError`; warm start built exactly once for N members; progress snapshot
  transitions (member indices, members_completed, final `active: False` +
  `stopped_early`).
- **API:** ultra response carries the three new fields (false/N/N on full
  completion); `stopped_early` result cached under `ultra_seeds =
  members_completed` (truthful key: a repeat of the ORIGINAL-N request
  re-runs; a request for N = members_completed HITS the entry); `GET
  /layout-progress` shape idle + mid-run (stubbed); 499 preserved when
  nothing completed; validation unchanged.
- **Frontend (vitest):** ultra abort does NOT abort the fetch (mock fetch
  resolves after `/cancel-layout`); non-ultra abort still does;
  `stopped_early` outcome mapping; QualityPanel total-time hint for
  representative N×budget; `useLayoutProgress` polling with fake timers
  (starts, updates, stops).
- **Integration (real sparrow, marked like the existing three):** one short
  sequential run (n_seeds=2, small budget) → valid marker, sequential wall
  (≈ 2× budget), response fields present.
- Suite grows from the 259 baseline; all existing tests must stay green
  (parallel-specific tests, if any, are updated to the sequential contract).

## 5. Deliverables & merge protocol

Worktree + feature branch (user creates; fixtures copied in). Docs updates:
**BACKLOG section ticks + outcome (the round record — NO PERFORMANCE.md
entry)**, CLAUDE.md architecture blurbs (`separation.py`, api routes,
`useAutoLayout`/`useLayoutProgress`, QualityPanel). PR with the standing merge
note (main's uncommitted `.gitignore` edit; untracked spec/plan copies →
commit on main first) **plus one new hazard: main's `docs/planning/BACKLOG.md`
carries an uncommitted planning-section edit — the branch commits the same
section, so at merge time drop main's local BACKLOG modification (checkout)
before `git pull`; the content arrives via the squash.**

## 6. Out of scope

- Async job API (submit/poll/fetch) — future work if runs outgrow one request.
- Retaining a parallel execution mode or an execution-mode toggle.
- racefork machinery (probes/compress forks) and cross-session "Continue
  refining" — separate follow-ups; this round's Stop semantics are
  within-run only.
- GA (`better`/`best`) and `fast` tier behavior — untouched (their Stop
  semantics stay as today).
- Changing budget/seed validation ranges or the cache key shape.
