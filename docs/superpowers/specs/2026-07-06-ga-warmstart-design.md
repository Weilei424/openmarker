# GA-layout warm start — spike (Ultra tier seed A/B, lever a)

> Design spec. Status: **approved** (brainstorm 2026-07-06). Owner: engine (layout).
> Extends: `docs/superpowers/specs/2026-06-07-separation-engine-phase2-design.md` (Ultra tier),
> the round-2 warm-start work (PERFORMANCE.md § 6 [2026-06-12 round 2]), and the lattice
> A/B's mechanism finding (PERFORMANCE.md § 6 [2026-07-05]).
> Origin: PERFORMANCE.md § 6 [2026-06-09] follow-up (a) "GA-layout warm start at equal *total* time".

## 1. Context

The lattice A/B (PR #19, NO-GO) sharpened the warm-start rule: sparrow transfers a
seed only when it is already near the reachable cold plateau (10722.7mm ± 120).
The Fast-BLF seed at 11393.2mm (~+6% over the plateau) steers 600s runs to a
10615.7 mean; periodic seeds at +29/+38% were destroyed in early compression and
regressed to cold. The GA layout is the ONLY seed we can build that is *denser*
than Fast-BLF — **11232.3mm / 82.69%** (+4.8% over the plateau) — so it moves the
seed the right direction along the measured dose-response. This spike tests it at
honest time accounting: a GA seed costs ~180s of prelude vs Fast's ~26s, and the
API's own budget notes record that Fast-seed warm-start value grows with sparrow
budget (tie at 180s → −1.11% at 600s), so the 154s difference must be priced in.

Production GA invocation to replicate (the GUI "better" tier, `api/main.py`):
`auto_layout_polygon(pieces, fabric_width_mm, grain_mode, FABRIC_GRAIN_DEG,
effort=4, ga_generations=12, ga_max_time_s=180.0, ga_seed=42)` — deterministic
per seed, generation cap never binds on the canonical workload (time binds →
prelude ≈ 180s).

## 2. Decisions (brainstorm 2026-07-06)

| Decision | Choice |
|---|---|
| Arms | **3-arm equal-envelope** (user choice): `prod` = Fast seed + 600s sparrow (production reference, ~626s envelope); `ctl780` = Fast seed + **754s** sparrow (~780s envelope); `ga` = GA Better-tier seed (~180s) + 600s sparrow (~780s envelope) |
| Primary gate | **G2-product**: `ga` vs `ctl780` paired at the equal 780s envelope — this is the ship decision |
| Secondary readout | **G2-mechanism**: `ga` vs `prod` paired (same 600s sparrow budget; seed is the only difference) — steers follow-ups, does not gate shipping |
| GA seed config | Better tier (180s, `ga_seed=42`, `effort=4`, `ga_generations=12`) — matches the measured 11232.3 reference and keeps the envelope at 780s; a Best-tier (420s) seed variant is a follow-up only if this round lands GO-borderline |
| Protocol | Canonical workload (sample_2 ×10, 1651mm, bi @90°), matched seeds 42/43/44, strictly sequential, quiet box (9 runs ≈ 1h45m incl. preludes) |
| Seed semantics | Each arm's seed built ONCE (deterministic), validator-gated (G1), converted via the production `_placements_to_jagua` path, shared across that arm's three sparrow runs; actual prelude wall recorded as telemetry |
| Code surface | **Spike-only** — zero production/engine-module changes, no new unit tests; the engine suite stays green untouched |
| Hard constraints | Unchanged: no mirroring, no tilt, grain enforced both ways, edges touchable, `_validate_layout` gates seeds AND finals |
| Bonus readout | `ctl780` vs `prod` = the +154s budget dose-response, an anchor for the later budget-curve round |

## 3. Spike runner

**New: `engine/tests/spike_ga_warmstart.py`** (throwaway, deleted at verdict).
Resurrects the preserved lattice-round runner (its full code lives in
`docs/superpowers/plans/2026-07-05-lattice-warmstart.md`, Task 4) with two deltas:

1. **Per-arm `(seed_source, sparrow_budget)`** replaces the shared budget:
   `prod` → (fast, 600), `ctl780` → (fast, 754), `ga` → (ga, 600). Seed sources:
   fast = `auto_layout_polygon(..., effort=1)`; ga = the production Better-tier
   call from § 1. The Fast seed is built once and shared by `prod` and `ctl780`
   (identical instance JSON except the arm's budget lives in the CLI `-t`, not
   the JSON — so those two arms share one instance file).
2. Report dir: gitignored `tools/ga-warmstart-spike/reports/` (blanket `tools/`
   line already covers it — no `.gitignore` change, per the lattice round's
   correction).

Everything else is the proven pattern verbatim: `smoke` / `run` / `evaluate`
subcommands; kill-safe ATOMIC report JSON+MD rewritten after every run;
TTL-bound; resume keeps valid (arm, seed) rows and re-runs the rest; seed-major
arm interleaving; per-run persistent workdirs keeping `output/log.txt` (the real
log) + `output/sols_*/` SVG snapshots; exit codes 0 all-valid / 1 some-invalid /
2 TTL. Sparrow is driven through the production helpers exactly as
`_build_warm_start` does: `_group_to_items` → `_instance_json` → seed placements
→ `_placements_to_jagua(items, pieces, placements, marker)` → `{**instance,
"solution": {"strip_width": marker + 1.0, "layout": {"container_id": 0,
"placed_items": …, "density": 0.0}, "density": 0.0, "run_time_sec": 0}}` →
subprocess `[exe, "-i", ipath, "-t", str(arm_budget), "-s", str(seed)]` →
`_reconstruct` → `_validate_layout` → `_compute_metrics`.

The GA prelude uses `effort=4` (ProcessPoolExecutor) — the runner keeps its
`if __name__ == "__main__"` guard so Windows process spawn is safe.

## 4. Telemetry & anchors

- Per arm (once): seed marker + util + ACTUAL prelude wall (`prelude_s`).
- Per run: arm, seed, marker, util, wall, validator verdict, workdir, snapshot
  count (`sols_*/*.svg`), log-line count (`output/log.txt`).
- Sanity anchors (informational, not gates): `prod` finals should land near the
  2026-07-05 fresh control (10584.2 / 10638.5 / 10624.4, mean 10615.7); the GA
  seed should print ≈ 11232.3mm; the Fast seed 11393.2mm; cold plateau
  10722.7mm ± 120 (n=21); commercial target 10599mm.

## 5. Gates & verdict

- **G1 (validity):** all three seeds and all nine finals validator-clean;
  invalid/crashed runs re-run via resume, never averaged.
- **G2-product (primary, ships or kills):** `ga` vs `ctl780` on matched seeds —
  GO at paired mean ≤ **−25.0mm** AND wins ≥ 2/3; NO-GO at mean > 0 or wins
  ≤ 1/3; borderline (mean in (−25, 0] with ≥2 wins) → extend ALL arms to seeds
  45/46 before the verdict.
- **G2-mechanism (secondary, reported):** `ga` vs `prod`, same thresholds,
  gates nothing. Interpretation grid: product-GO ⇒ ship path; product-NO-GO +
  mechanism-GO ⇒ the seed transfers but is not worth 154s of sparrow — file a
  "cheaper GA prelude (60–90s `ga_max_time_s` cap)" follow-up instead of closing
  the lever; both-NO-GO ⇒ lever closed (seed density gap too small to matter or
  GA structure does not transfer).
- **DECISIVE flag (reported):** all three `ga` finals < 10599.0mm.
- **G3 (regression guard, GO only):** `ga` vs `prod` on `sample_4.dxf` ×6 @600s
  seed 42 — worse by > 40.0mm ⇒ productization must be per-workload
  (build both seeds, pick the better pre-sparrow) rather than unconditional.
- **Verdict = user checkpoint** with full tables (per-seed finals, both paired
  comparisons, seed telemetry, dose-response readout) before any merge action.

## 6. Deliverables & merge protocol

Worktree + feature branch (user creates at execution start; fixtures copied in —
not in git). Commits on the branch only.

- **GO:** spike deleted with its code preserved verbatim in the plan doc;
  protocol record merged; a follow-up spec/plan/PR is filed in BACKLOG to wire
  the seed source into `run_separation_layout` — THAT PR owns the GUI/budget
  semantics (whether the 180s GA prelude lives inside or on top of the user's
  Ultra `ultra_budget_s`), the `warm_start` API surface, and cache-key impact.
- **NO-GO:** docs-only protocol record (rebuild/lattice precedent); spike
  deleted, code preserved in the plan doc.
- Both paths: PERFORMANCE.md § 6 dated entry + § 6 [2026-06-09] follow-up (a)
  status noted in the entry (there is no § 5.B row for this lever — the entry
  IS the record), BACKLOG checklist + outcome line, PR with the merge-note
  about main's uncommitted `.gitignore` edit, reports rescued to the main
  tree's `tools/ga-warmstart-spike/` before worktree removal.

## 7. Out of scope

- Production wiring (`run_separation_layout` seed source, GUI budget semantics,
  cache keys) — the GO follow-up PR.
- Best-tier (420s) GA seeds; cheaper GA preludes (60–90s) — conditional
  follow-ups per the § 5 interpretation grid.
- Mixed seed sources across best-of-N attempts — compose-later product
  decision.
- Segment-chained basin hopping (lever f) — separate spike, independent
  machinery.
- Longer-budget characterization (lever d) — next round, on this round's
  winning seed.
