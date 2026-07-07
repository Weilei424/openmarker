# Warm-start budget curve — characterization round (lever d)

> Design spec. Status: **approved** (brainstorm 2026-07-07). Owner: engine (layout).
> Extends: the warm-start line (PERFORMANCE.md § 6 [2026-06-12 round 2] → [2026-07-05] → [2026-07-07 GA A/B]).
> Origin: PERFORMANCE.md § 6 [2026-06-09] follow-up (d) "longer budgets"; motivated by the GA
> round's dose-response side-finding (+154s = −30.3mm at 3/3) and the closure of both
> seed-side levers.

## 1. Context

Both seed-side levers are closed (lattice PR #19; GA PR #20). The strongest live
evidence points at budget: warm +154s measured **−30.3mm with 3/3 sign-consistency**,
including a sub-commercial single (ctl780 s42 = 10596.8mm @754s). The only warm
budget data beyond 754s is a single old point (1200s edges past commercial
utilization, § 6 [2026-06-09]) measured before the warm start existed in its
current form; the "600→1200s = +0.39pp, diminishing" conclusion that demoted the
budget lever was a COLD-era measurement. This round re-measures the curve warm,
answering two questions: (1) at what budget does the warm MEAN cross the 10599mm
commercial target (not just a lucky seed)? (2) where does the continuous
trajectory flatten — which is where lever (f) (segment-chained basin hopping)
should be tested, since restarts attack stagnation.

This is a **characterization, not an A/B**: no treatment/control, no paired
gates. The verdict is a curve + two pre-registered readouts.

## 2. Decisions (brainstorm 2026-07-07)

| Decision | Choice |
|---|---|
| Budget points | **600 / 1200 / 2500 s** (user choice; brackets the GUI range at the fewest hours; resume permits an 1800s backfill later if the 1200→2500 shape surprises) |
| Arms | `b600:fast:600`, `b1200:fast:1200`, `b2500:fast:2500` — all production Fast warm start, solo runs (n_seeds=1) |
| Protocol | Canonical workload (sample_2 ×10, 1651mm, bi @90°), matched seeds 42/43/44, strictly sequential, seed-major interleave (each seed's 600→1200→2500 trio runs consecutively), quiet box, ~3h40m wall, TTL 6h |
| Seed | Fast NFP-BLF (`auto_layout_polygon(..., effort=1)`), built ONCE, validator-gated (G1), one instance file shared by ALL runs — arms differ only by `-t` |
| Code surface | Spike-only: resurrect the GA-round runner (preserved in `docs/superpowers/plans/2026-07-07-ga-warmstart.md` Task 2) with three deltas — reports dir `tools/budget-curve/reports/`, new `DEFAULT_ARMS`, `evaluate` rewritten for characterization. No engine-module changes, no new unit tests |
| Hard constraints | Unchanged: no mirroring, no tilt, grain both ways, edges touchable, `_validate_layout` gates seed AND finals |

## 3. Pre-registered decision rules (replace the A/B gates)

- **G1 (validity):** the seed and all 9 finals validator-clean; invalid/crashed
  runs re-run via resume, never averaged.
- **CROSSED at budget B** := mean(B) < **10599.0mm** AND ≥ 2/3 seeds < 10599.0.
  - **Recommendation rule:** the smallest crossed B is proposed as the new Ultra
    DEFAULT budget (`QUALITY_BUDGETS_S["ultra"]` + the GUI default) — filed as a
    follow-up mini-PR in BACKLOG, out of this spike's scope (precedent: spikes
    ship no product changes).
  - **DECISIVE flag:** any budget crossed.
- **Flattening readout:** Δmean per +100s for 600→1200 and 1200→2500; the
  flatter segment names lever (f)'s test budget. (Informational — no threshold.
  Single-run spreads on record are ~45–120mm, so a 3-seed mean is only good to
  a few tens of mm; quote that alongside the marginal table.)
- **Borderline:** if |mean(B) − 10599| ≤ 15mm for any budget B, extend THAT
  budget to seeds 45/46 before declaring it CROSSED or not-crossed (the
  crossing verdict is otherwise one re-draw from flipping). Other budgets
  extend only if the curve needs them.
- **Verdict = user checkpoint** with the curve table, crossing analysis,
  marginal-value table, and the (f)-budget recommendation.

## 4. Telemetry & anchors

- Per run: arm, seed, budget_s, marker, util, wall, validator verdict, workdir,
  snapshots (`sols_*/*.svg`), log-lines (`output/log.txt`).
- Seed telemetry: Fast seed ≈ 11393.2mm, prelude ≈ 27s.
- Sanity anchors (informational): b600 mean should land near the fresh 600s
  control means (10615.7 [PR #19 round] / 10651.4 [PR #20 round]); PR #20's
  ctl780 point (754s → mean 10621.2, singles 10596.8/10625.2/10641.5) should sit
  plausibly on the interpolated curve; cold plateau 10722.7 ± 120; commercial
  10599.
- Wall sanity: each run's `wall_s` ≈ its `-t` + a few s; a large excess flags a
  loaded box (rerun the affected pairs).

## 5. Spike runner deltas (vs the preserved GA runner)

1. `REPORTS = .../tools/budget-curve/reports/`; `DEFAULT_ARMS =
   "b600:fast:600,b1200:fast:1200,b2500:fast:2500"`; the `ga` seed-source branch
   is removed (`SEED_SOURCES = ("fast",)`) — the `seed_source` field stays in
   the schema.
2. `evaluate` prints, per budget (ascending): per-seed markers, mean, and
   `n_below` (count < 10599); then the crossing analysis (CROSSED per the § 3
   rule; smallest crossed B highlighted), the marginal table (Δmean and
   Δmean/100s for consecutive pairs), and the DECISIVE flag. `--report2` is
   dropped (no G3 — single-workload characterization; a budget default is
   workload-independent product policy, and the GUI keeps the user override).
3. Everything else verbatim: `smoke`/`run`/`evaluate`, atomic kill-safe reports,
   resume on valid (arm, seed) pairs, TTL, per-run persistent workdirs, exit
   codes 0/1/2, `if __name__ == "__main__"` guard.
4. Smoke: 3 arms × 15s × 1 copy, seed 42 (validates arm parsing + the shared
   instance file + validator round-trip).

## 6. Deliverables & merge protocol

Worktree + feature branch (user creates; fixtures copied in). Spike deleted at
verdict on BOTH paths (the runner variant's full code is preserved in this
round's plan doc). PERFORMANCE.md § 6 dated entry is the record (no § 5.B row —
this closes/answers follow-up (d) of § 6 [2026-06-09]); BACKLOG checklist +
outcome (+ the default-budget follow-up line if CROSSED); PR with the standing
merge note (main's uncommitted `.gitignore` edit; untracked spec/plan copies →
commit on main first, per the established choreography); reports rescued to the
main tree's `tools/budget-curve/` before worktree removal.

## 7. Out of scope

- The default-budget product change itself (API + GUI + tests) — follow-up
  mini-PR if CROSSED.
- Best-of-N composition at higher budgets (lever c) — separate round.
- Segment-chained basin hopping (lever f) — next round, at the budget this
  curve names.
- An 1800s point — backfill via resume only if the 1200→2500 shape warrants.
