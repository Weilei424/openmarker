# Race + fork — spike (race explore probes, fork the compress lottery; equal-wall A/B vs sequential best-of-N)

> Design spec. Status: **approved** (brainstorm 2026-07-09). Owner: engine (layout).
> Extends: the drive-sparrow-better line (PERFORMANCE.md § 6 [2026-06-12 r2] →
> [2026-07-05] → [2026-07-07] → [2026-07-08] → [2026-07-09 basin hopping]).
> Origin: the 2026-07-09 trajectory-mining study (zero new compute; script +
> findings in gitignored `tools/trajectory-mining/`), run against the rescued
> logs of the six production-arm warm 2500s runs.

## 1. Context

The mining decomposed a warm 2500s sparrow run (`-t 2500` splits 2000s explore
/ 500s compress) into two regimes with opposite characters:

1. **Explore is near-deterministic per RNG seed.** It descends a 0.1%-shrink
   width ladder, and same-seed replicates across rounds hit bit-identical
   rungs at every checkpoint. Between-seed SD of finals: 30.2mm. Consequence:
   a short probe measures a seed's whole explore trajectory faithfully, and a
   from-scratch rerun of the winning seed reproduces its probe exactly — a
   race needs no mid-explore state handoff.
2. **Compress is a lottery.** Gains +26.0..+73.3mm in its 500s; same-seed
   pairs entering compress from the *identical* explore-end state landed
   28.1mm apart; all six runs were still improving at cutoff. Within-seed SD:
   12.1mm. Consequence: extra 500s compress attempts from one explore-end
   state are cheap independent tickets in that lottery.
3. **Sequential best-of-N at 2500s already predicts a crossing.** Resampling
   the six finals (mean 10585.5): best-of-3 E[min] ≈ 10559–10564 with 87–95%
   of resamples below the 10599 commercial target.

The composed policy — **race** P explore-only probes across seeds, rerun the
winner's explore in full, then **fork** K compress attempts from its
explore-end state — attacks both variance components at once, sequentially
(one 3-thread sparrow at a time, hardware-flat). This round A/Bs it against
the simple fallback (sequential best-of-3 full runs) at equal wall. It does
not contradict the basin-hopping NO-GO: chaining re-entered *explore* from a
*compressed* layout (paying re-separation K times); race-by-rerun never cuts
explore, and the only `-i` handoff left (explore-end → compress) mirrors what
sparrow does in-process at that exact boundary.

CLI feasibility verified: sparrow exposes independent `-e` (exploration) and
`-c` (compression) time limits alongside `-t`, and `-i` accepts a solution
JSON (its own output format). Production passes only `-t`
(`separation.py:251`). Converter fidelity audited: full-resolution polygons;
the only loss is sparrow-internal jagua-rs simplification capped at ~0.1%
area (a few mm worst case — dismissed as unmeasurable vs noise).

## 2. Decisions (brainstorm 2026-07-09)

| Decision | Choice |
|---|---|
| Arms | **2-arm, equal 7500s wall** (user choice): `seq3` = sequential best-of-3 full production warm runs @2500s; `racefork` = 4 probes ×450s + winner explore rerun 2000s + **K=7** compress forks ×500s (≈7300s + orchestration, ≤7500 — the treatment pays its own overhead; conservative) |
| Racefork mechanics | **Race-by-rerun** (approach 1): probes `-e 450 -c 0 -s b_i` from the shared warm start; winner = min probe width (final-JSON strip width), ties → lowest block index; winner reruns `-e 2000 -c 0 -s b_win` **from scratch** (explore determinism makes the rerun faithful; the 450s re-tread is deliberate — zero mid-explore handoffs); forks `-e 0 -c 500 -i <explore_end.json> -s b_win + 1000·j` (j = 1..7); arm final = min VALID fork. No `-t` passed when `-e`/`-c` are used |
| Protocol | Canonical workload (sample_2 ×10, 1651mm, bi @90°), **3 replications**, strictly sequential, quiet box (~12.5h total; resumable across nights; TTL 14h) |
| Seeds | **Fresh blocks, no 42/43/44 recycling** (s42 won 5/5 historical cohorts — recycling would flatter both arms and contaminate DECISIVE): rep1 {51,52,53,54}, rep2 {61,62,63,64}, rep3 {71,72,73,74}. `seq3` uses the first 3 of each block; `racefork` probes all 4 — unequal seed counts are *the policy difference under test*; equal wall is the fairness criterion |
| Warm start | Production Fast seed (`effort=1`), built ONCE for the whole matrix, G1-gated, one shared instance file — every probe, rerun, and seq member starts from it |
| Explore-end validation | The rerun's final JSON round-trips `_reconstruct` → `_validate_layout` BEFORE forking. Invalid → retry the rerun with the runner-up probe seed; second failure → the (arm, rep) row is invalid (resume re-runs it). The ORIGINAL sparrow JSON (not a rebuild) feeds the forks — no conversion loss |
| CLI fallbacks (smoke-gated) | `-c 0` rejected → `-c 1`; `-e 0` rejected → `-e 1`; explore-only run emits no final JSON → design assumption broken, **escalate** (do not paper over) |
| Failure ladder | Invalid seq member / fork → excluded from the arm min; all members / all forks invalid → (arm, rep) invalid, resume re-runs. Probes are ranking-only artifacts — not validated |
| Code surface | Spike-only: `engine/tests/spike_race_fork.py`, evolved from the basin-hopping runner skeleton (kill-safe atomic reports, resume on valid (arm, rep), TTL, exit codes 0/1/2, `__main__` guard). `_run_seq(seeds, budget_s)` + `_run_racefork(seeds, probe_s, explore_s, k, compress_s)`. No engine-module changes, no new unit tests |
| Hard constraints | Unchanged: no mirroring, no tilt, grain both ways, edges touchable; `_validate_layout` gates everything |

## 3. Gates & readouts

- **G1 (validity):** the Fast seed, the explore-end state of every racefork
  rep, and every arm-final candidate validator-clean; invalid (arm, rep) rows
  re-run via resume, never averaged.
- **HEADLINE — DECISIVE (per arm):** all 3 reps' arm-finals < **10599.0** ⇒
  that policy decisively crosses the commercial target (the campaign goal).
  Reported alongside: per-rep finals and arm mean.
- **G2 (A/B, paired per seed block):** d_r = racefork_r − seq3_r. DECISIVE
  dominates: if exactly one arm is DECISIVE, it is the productization
  candidate regardless of G2 margin. When both or neither cross, `racefork`
  becomes the candidate only at paired mean ≤ **−25.0mm** AND wins ≥ 2/3;
  otherwise `seq3` (simpler machinery wins ties/noise). Borderline (mean in
  (−25, 0] with ≥2 wins) → extend BOTH arms to reps 4–5 (blocks {81–84},
  {91–94}, ~+7h) before declaring.
- **Context readout:** each arm mean vs the pooled cont@2500 anchor
  (10585.5, n=6): a 3×-wall policy that fails to beat a single run by a
  clear margin (predicted: seq3 −20 to −27mm, racefork −30 to −40mm) fails
  sanity and must be called out.
- **Mechanism observables:** per racefork rep — probe widths per seed,
  probe-vs-rerun rung agreement at 450s (free determinism check), the
  explore-end width, and the 7 fork finals. Evaluate also computes the
  best-of-k fork resampling curve (k = 1..7; post-hoc K tuning for
  productization) and probe-rank fidelity. `seq3`'s 9 member runs double as
  fresh cont@2500 draws (pool 6 → 15).
- **G3 (regression guard, only if `racefork` is the productization arm):**
  racefork@7500 vs seq3@7500 on `sample_4.dxf` ×6, 1 rep, block {51–54}
  (~4.2h) — worse by > **40.0mm** ⇒ productization per-workload rather than
  unconditional. `seq3` needs no G3 (a pure composition of production runs).
- **Verdict = user checkpoint** with paired tables, DECISIVE readout, fork
  curves, and probe-fidelity traces.

## 4. Telemetry & anchors

- Per rep and arm: block seeds, component walls, per-run marker/util/valid,
  workdirs; racefork adds probes (seed, width, wall), winner, rerun
  explore-end width, fork finals; runs under
  `runs/<arm>_r<rep>/(probe_s<seed>|rerun|fork<j>|m<i>)/`.
- Anchors: Fast seed 11393.2mm (~28s prelude); cont@2500 pool n=6 mean
  10585.5 (3/6 below target); all-time best single 10551.9; commercial
  10599; predicted seq3 E ≈ 10559–10564 (87–95% below), racefork point
  estimate ≈ 10545–10555; between-seed SD 30.2mm / within-seed 12.1mm.
  Wall sanity: component `wall_s` ≈ its `-e`+`-c` + a few seconds.
- Reports/workdirs under gitignored `tools/race-fork/` (blanket `tools/`
  line — no `.gitignore` edit).

## 5. Smokes (Phase A, sample_2 ×1 copy, ~4 min, escalate on failure)

1. **Explore-only emits state:** `-e 60 -c 0` → final JSON exists, parses,
   round-trips the production validator (fallback `-c 1`).
2. **Compress-only from state:** `-e 0 -c 60 -i <that JSON>` → runs, final
   width ≤ state width, validates (fallback `-e 1`).
3. **Fork divergence sanity:** 2 compress-only runs from the same state with
   different `-s` → both valid (differing finals expected but not asserted
   at this tiny scale).
4. **Mini end-to-end pipeline:** probes 2×15s → rerun 30s → forks 2×15s,
   plus seq 2×30s — exercises the full runner path incl. report/resume.

## 6. Deliverables & merge protocol

Worktree + feature branch (user creates; fixtures copied in). Spike deleted
at verdict on BOTH paths (full runner preserved in this round's plan doc).
PERFORMANCE.md § 6 dated entry is the record (no § 5.B row); BACKLOG
checklist + outcome; PR with the standing merge note (main's uncommitted
`.gitignore` edit; untracked spec/plan copies → commit on main first per the
established choreography); reports rescued to the main tree's
`tools/race-fork/` before worktree removal.

- **GO:** follow-up PR filed in BACKLOG — wire the winning policy into
  `run_separation_layout` as a sequential orchestration mode (component
  scheduling inside the user budget, cancellation across components via the
  existing kill registry, GUI exposure decided in that spec; the fork
  machinery also serves the filed "best-so-far on Stop" / "Continue
  refining" follow-ups).
- **NO-GO / neither arm crosses:** docs-only protocol record; the measured
  quality-lever list is then empty — next step is a reassessment checkpoint
  (accept near-target, or characterize envelopes beyond 7500s) rather than
  another pre-named spike.

## 7. Out of scope

- Productization (API/GUI/cancellation wiring) — the GO follow-up PR.
- Tuning P / probe length / K beyond the fixed constants (the fork telemetry
  supports post-hoc simulation instead); adaptive racing (Hyperband et al.).
- Mixing race+fork with cross-session "continue refining" — compose later.
- Retuning the `-e`/`-c` split of a plain run (compress-at-cutoff footnote;
  fork dominates extending).
- sample_4×6 beyond the conditional G3 guard.
