# Segment-chained basin hopping — spike (lever f, 2500s equal-wall A/B)

> Design spec. Status: **approved** (brainstorm 2026-07-08). Owner: engine (layout).
> Extends: the warm-start line (PERFORMANCE.md § 6 [2026-06-12 r2] → [2026-07-05] →
> [2026-07-07] → [2026-07-08 budget curve]).
> Origin: the "drive-sparrow-better" family; test budget fixed by the budget curve
> (§ 6 [2026-07-08]): the 1200→2500s marginal flattens to −2.16mm/100s and the 2500s
> mean (10590.3) sits a coin-flip around the 10599mm target.

## 1. Context

A continuous warm sparrow run is ONE trajectory: one RNG stream, one evolving set
of GLS penalty weights, one strip-shrink schedule. The budget curve shows that
trajectory still paying at 2500s but flattening — the stagnation signature
perturbation-restarts attack. Basin hopping from outside the process: split the
same wall budget into K segments, each a FRESH sparrow process seeded via `-i`
from the validated best-so-far layout with a decorrelated RNG seed. Per segment,
the penalty weights / shrink schedule / trajectory reset (the perturbation);
the best layout carries (the hop's starting point). Evidence for: trajectory
diversity measurably pays (best-of-N ≈ −35–50mm at equal wall, § 6 [2026-06-12
r2]) and a chain segment's seed is by construction the nearest-to-plateau seed
that exists (the § 6 [2026-07-05] transfer rule maximally satisfied). Evidence
of risk: each cut discards in-flight explore state, and at 600s the trajectory
was NOT yet stagnant — which is why the test runs at 2500s, where it is.

Everything runs through proven machinery: the budget-curve runner (preserved in
`docs/superpowers/plans/2026-07-07-budget-curve.md`) plus the production
converter round-trip for the chain step. Zero engine-module changes. On GO, the
chain machinery is verbatim the plumbing for the filed "best-so-far on Stop" +
"Continue refining" product follow-ups.

## 2. Decisions (brainstorm 2026-07-08)

| Decision | Choice |
|---|---|
| Arms | **3-arm** (user choice): `cont` = `chain1:2500` (continuous — production behavior, fresh control), `chain2` = 2×1250s, `chain5` = 5×500s. K bracket: deep-segments vs aggressive restarts |
| Protocol | Canonical workload (sample_2 ×10, 1651mm, bi @90°), 2500s per arm, matched seeds 42/43/44, seed-major trios, strictly sequential, quiet box (~6h20m; overnight; TTL 9h) |
| Warm start | Production Fast seed (`effort=1`), built ONCE, G1-gated, one shared instance file — segment 1 of every arm starts from it |
| Chain step | Validated engine round-trip: segment `final_*.json` → `_reconstruct` → `_validate_layout` → `_compute_metrics` → (if best valid so far) `_placements_to_jagua` + `strip_width = marker + 1.0` → next segment's `{**instance, "solution": …}`. Every segment seed is production-grade clean (pure-translation guard included) |
| Segment RNG | Segment j (1-based) runs `-s seed + 1000·(j−1)` — decorrelated from the matched seed set (42/43/44 → 1042…4044, no collisions) |
| Keep-best | Explicit: next seed = best VALID marker so far; arm result = min valid marker across segments — a bad segment can never worsen the arm |
| Time accounting | Each segment gets `-t = budget/K` (integer seconds; remainder to the last segment). Chain arms pay their own orchestration overhead (~2–5s per boundary) on top — disadvantages only the treatment (conservative). Per-segment walls in telemetry |
| Failure ladder | Segment result invalid → log, chain continues from prior best; segment 1 invalid → the (arm, seed) row is invalid (resume re-runs it) |
| Code surface | Spike-only: budget-curve runner with mode generalized to `name:chainK:budget` (K ≥ 1; `cont` ≡ `chain1` through the same code path). No engine-module changes, no new unit tests |
| Hard constraints | Unchanged: no mirroring, no tilt, grain both ways, edges touchable; `_validate_layout` gates everything |

## 3. Gates & readouts

- **G1 (validity):** the Fast seed, every segment reconstruction, and every arm
  final validator-clean; invalid (arm, seed) rows re-run via resume, never
  averaged.
- **G2 (primary, per chain arm vs `cont`, paired on matched seeds):** GO =
  paired mean ≤ **−25.0mm** AND wins ≥ 2/3; NO-GO = mean > 0 or wins ≤ 1/3;
  borderline (mean in (−25, 0] with ≥2 wins) → extend the involved arms (and
  `cont`) to seeds 45/46 before declaring (~2500s per added run).
- **TARGET readout (reported per arm):** mean vs 10599.0 and n-below;
  **DECISIVE flag** if any arm has all 3 seeds < 10599.0. (`cont` is expected
  near the budget curve's 2500s mean 10590.3 / 1 of 3 below.)
- **Segment telemetry (mechanism observable):** per chain run, the sequence of
  segment markers + which segments improved on their seed. A GO with most
  improvement in segments ≥ 2 confirms the restart mechanism; a GO driven
  entirely by segment 1 would be a budget artifact and must be called out.
- **G3 (regression guard, GO only):** winning arm vs `cont` on `sample_4.dxf`
  ×6 @2500s seed 42 (2 runs ≈ 1h25m) — worse by > **40.0mm** ⇒ productization
  must be per-workload rather than unconditional.
- **Verdict = user checkpoint** with paired tables, target readout, and the
  per-segment improvement traces.

## 4. Telemetry & anchors

- Per run: arm, seed, budget_s, K, final marker/util, total wall, validator
  verdict, workdir, plus `segments: [{seg, marker_mm, wall_s, improved}]`;
  snapshots/log-lines recorded per segment workdir (`runs/<arm>_s<seed>/seg<j>/`).
- Anchors: Fast seed 11393.2mm (~27s prelude); budget-curve 2500s row
  10558.6/10612.6/10599.6 (mean 10590.3) — `cont` should land nearby;
  commercial 10599; all-time best single 10558.6; cold plateau 10722.7 ± 120.
  Wall sanity: per-segment `wall_s` ≈ its `-t` + a few seconds.
- Reports/workdirs under gitignored `tools/basin-hopping/` (blanket `tools/`
  line — no `.gitignore` edit).

## 5. Spike runner deltas (vs the preserved budget-curve runner)

1. `REPORTS = .../tools/basin-hopping/reports/`; `DEFAULT_ARMS =
   "cont:chain1:2500,chain2:chain2:2500,chain5:chain5:2500"`; arm parser accepts
   `name:chainK:budget` with K ≥ 1 parsed from the mode token.
2. `_run_one` → `_run_chain(exe, items, pieces, instance, k, budget_s, seed,
   workdir)`: loops K segments; per-segment `-t = budget_s // k` (+ remainder on
   the last); segment 1 uses the shared Fast-warm instance file, later segments
   write `seg<j>\instance.json` seeded from the best-so-far via the § 2 chain
   step; returns the best valid solution + the segments list.
3. `evaluate`: GA-round paired-gate structure (`_gate_g2(report, arm, "cont",
   n, label)`) for `chain2` and `chain5`, the TARGET readout per arm, the
   DECISIVE flag, and a per-run segment-improvement print. `--report2` = G3
   (winning arm vs `cont`, mean ≤ 40.0).
4. Everything else verbatim: `smoke`/`run`/`evaluate`, atomic kill-safe
   reports, resume on valid (arm, seed) pairs, TTL, exit codes 0/1/2,
   `__main__` guard.
5. Smoke: 1 copy, seed 42, arms `cont:chain1:15,chain2:chain2:16,chain5:chain5:30`
   (distinct budgets; chain5's 30s → 5×6s segments exercises the full chain
   plumbing incl. best-so-far reseeding on a real multi-segment run — 6s is the
   floor we trust sparrow to emit a final solution in; if a tiny segment still
   yields no `final_*.json`, that surfaces as a smoke failure to escalate, not
   something to paper over).

## 6. Deliverables & merge protocol

Worktree + feature branch (user creates; fixtures copied in). Spike deleted at
verdict on BOTH paths (full runner preserved in this round's plan doc).
PERFORMANCE.md § 6 dated entry is the record (no § 5.B row — lever (f) was
filed in the § 6 [2026-07-04] survey close-outs and the [2026-07-08] curve
entry); BACKLOG checklist + outcome; PR with the standing merge note (main's
uncommitted `.gitignore` edit; untracked spec/plan copies → commit on main
first per the established choreography); reports rescued to the main tree's
`tools/basin-hopping/` before worktree removal.

- **GO:** follow-up PR filed in BACKLOG — wire chaining into
  `run_separation_layout` (segment scheduling inside `ultra_budget_s`,
  cancellation across segments via the existing kill registry, and the
  "best-so-far on Stop" / "Continue refining" features that fall out of the
  same converter machinery).
- **NO-GO:** docs-only protocol record; with the seed-side and chaining levers
  then all closed, the remaining measured lever is best-of-N composition at
  2500s (lever c).

## 7. Out of scope

- Productization (API/GUI/cancellation wiring) — the GO follow-up PR.
- K tuning beyond {2, 5}; adaptive/Luby restart schedules; perturbation
  operators beyond RNG-reseed (e.g., explicit layout jitter).
- Mixing chain segments with best-of-N attempts — compose-later.
- sample_4×6 beyond the G3 guard.
