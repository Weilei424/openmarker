# Ultra sidecar rebuild — SIMD + target-cpu A/B (`sparrow.exe` codegen)

> Design spec. Status: **approved** (brainstorm 2026-07-04). Owner: engine (vendored binary + resolver).
> Extends: `docs/superpowers/specs/2026-06-07-separation-engine-phase2-design.md` (the Ultra tier).
> Origin: PERFORMANCE.md § 5.B "SIMD + target-cpu rebuild" row + § 6 [2026-07-04] survey, Find A.

## 1. Context

The vendored `sparrow.exe` was built with plain stable `cargo build --release`
(PROVENANCE.md). The pinned `Cargo.toml` declares **no default features**, so the
`simd` feature is OFF in the shipped binary, and no `-C target-cpu` codegen was set
(the release profile is already `opt-level=3, lto="fat"` — codegen flags are the
only headroom). Upstream's documented fast build: **nightly** + `--features=simd` +
`RUSTFLAGS='-C target-cpu=native'`. sparrow is an anytime optimizer — at a fixed
wall budget, quality is iteration-bound, so codegen throughput converts to marker
length; the effect compounds with warm start (whose win grows with budget). Every
config-*constant* knob was NO-GO (§ 6 [2026-06-12]); codegen is the remaining
binary-side lever.

## 2. Decisions (brainstorm 2026-07-04)

| Decision | Choice |
|---|---|
| Source pin | **Keep `a4bfbbe`** (upstream delta = dep bumps only; isolates the codegen variable) |
| Toolchain | **Date-pinned nightly**, start `nightly-2026-05-07` (adjacent to the pin date); walk forward on API drift; last resort = stable without `simd`, documented as a descope |
| Features | **`simd` only** — NOT `only_final_svg` (keeps `sols_` snapshots for the Stop follow-up), NOT `live_svg` |
| Candidates | `x86-64-v2`, `x86-64-v3`, `native` (**native = bench-only ceiling, never ships**) |
| Bench depth | **Full matrix** (user choice; ~4h wall) |
| Ship model | **Dual-binary, runtime-selected**: fallback exe keeps the name `sparrow.exe`; v3 ships as `sparrow-avx2.exe` picked by an AVX2 probe. No user-facing option, no installer logic (fleet CPUs unknown; disk images get cloned) |
| Gate thresholds | Dual-ship margin **15mm** paired mean; sample_4 regression guard **10mm** (user-approved judgment values; 15 ≈ ⅛ of the 120mm noise spread) |

## 3. Build matrix (scratch `tools/sparrow-rebuild/`, gitignored)

Clone upstream → checkout `a4bfbbe` → `rustup toolchain install nightly-2026-05-07`.
Three builds, differing only in `RUSTFLAGS="-C target-cpu={x86-64-v2|x86-64-v3|native}"`:
`cargo +nightly-2026-05-07 build --release --features=simd`. Copy artifacts to
`tools/sparrow-rebuild/builds/sparrow_{v2,v3,native}.exe`. Smoke-test each on a tiny
instance (runs, output parses, marker valid). Record per exe: `rustc -V`, RUSTFLAGS,
features, SHA-256, size — feeds the PROVENANCE rewrite.

## 4. Bench harness (`engine/tests/spike_simd_rebuild.py`, throwaway)

- Round-2 spike pattern: reuse the production helpers (`_group_to_items`,
  `_instance_json`, `_build_warm_start`, `_reconstruct`, `_validate_layout`,
  `_compute_metrics`) but shell each exe directly (`-i <json> -t 600 -s <seed>`)
  so the spike controls the workdir and keeps stderr logs + `sols_` dirs per run.
- **Warm start built ONCE per workload** from the Fast NFP-BLF layout
  (`auto_layout_polygon`, production-default args) and shared byte-identically
  across all arms × seeds — removes prelude variance; sparrow still gets the full
  600s, matching production.
- Per-run record: arm, seed, marker, util, wall, validator verdict, log path.
- Throughput parsed opportunistically from logs (iterations / improvements; else
  `sols_` snapshot count) — **informational only, never a gate**.
- Resilience per the long-running-script convention: TTL-bound, report (JSON + MD)
  rewritten after EVERY run so a kill loses nothing.
- Runs strictly sequential on a quiet box; all builds finish before benching starts
  (sparrow's `-t` is wall-clock — concurrent load corrupts the A/B).

## 5. Protocol

- **Workload 1 (decision):** `sample_2.dxf ×10`, fabric 1651, bi-grain @90, warm
  start, 600s. Arms {control=vendored, v2, v3, native} × seeds {42, 43, 44} = 12 runs.
- **Workload 2 (regression guard):** `sample_4.dxf ×6`, same settings, control +
  shipping candidate(s) × seeds {42, 43, 44} — a FRESH paired control (don't reuse
  the June baselines; different box state).
- Every marker must pass `_validate_layout` (grain / overlap / width / coverage).
  A validity failure on a codegen-only change is a red flag — stop and investigate,
  don't just disqualify the seed.
- All comparisons are **matched-seed paired** (the round-2 method).

## 6. Decision gates

- **G1 (candidate is shippable):** beats control on ≥2/3 matched seeds AND paired
  mean Δ < 0, with all 3 runs valid.
- **G2 (dual-binary ships):** v3 passes G1 AND beats the *chosen fallback exe* by
  paired mean ≥ 15mm. Fallback = v2 if v2 passed G1, else the current vendored exe.
  If G2 fails but v2 passed G1 → ship v2 alone (binary swap, zero code change).
  If only v3 passes G1 and clears 15mm vs vendored → dual-ship with the vendored
  exe kept as `sparrow.exe` fallback.
- **G3 (regression guard):** each shipping candidate's sample_4×6 paired mean must
  not be worse than control by >10mm; violation drops that candidate (re-apply the
  G2/G1 ladder with what remains, possibly NO-GO).
- **NO-GO:** nothing passes G1 → vendored exe stays; record all numbers (incl. the
  native ceiling + throughput) in PERFORMANCE.md § 6.

## 7. Ship paths

- **(a) v2-only:** replace `engine/vendor/sparrow/sparrow.exe`; resolver untouched;
  PROVENANCE.md rewritten; the 3 real-sparrow integration tests re-run green.
- **(b) Dual-binary:** fallback exe as `sparrow.exe` + v3 as `sparrow-avx2.exe`.
  `separation.py` gains `_has_avx2()` — `sys.platform == "win32"` guard +
  `ctypes.windll.kernel32.IsProcessorFeaturePresent(40)` (PF_AVX2_INSTRUCTIONS_AVAILABLE);
  any exception → `False` (safe side). `_resolve_sparrow_path()` per ladder location:
  prefer `sparrow-avx2.exe` iff `_has_avx2()` and the file exists, else `sparrow.exe`.
  `OPENMARKER_SPARROW_PATH` is unchanged and bypasses the probe (expert escape hatch).
  Unit tests monkeypatch `_has_avx2` + temp dirs for both selection branches.
- **(c) NO-GO:** no repo change beyond docs.
- Either ship path **must restore/extend the `.gitignore` negation**
  (`!engine/vendor/sparrow/*.exe`) — the current working tree removed the
  single-file negation (uncommitted local edit); without it, re-adding the exe(s)
  silently fails past `*.exe`.

## 8. Deliverables

- `engine/vendor/sparrow/PROVENANCE.md` rewrite: toolchain (nightly pin), RUSTFLAGS,
  features, per-variant table (target, SHA-256, size), updated rebuild recipe.
- PERFORMANCE.md: § 6 [2026-07-04 rebuild A/B] results entry (arm × seed table,
  paired deltas, throughput, gate outcomes, decision); § 5.B row status update.
- BACKLOG: one-line entry under the separation follow-ups.
- Spike script deleted after (numbers preserved in § 6); builds stay in gitignored
  `tools/`. Memory updated.

## 9. Execution notes & risks

- Execution on a **user-created worktree** per project convention; copy
  `examples/input/sample_2.dxf` + `sample_4.dxf` in (fixtures aren't in git).
- portable-SIMD API drift vs the pinned source → pin-adjacent nightly, walk forward,
  stable descope as last resort.
- Run-to-run variance → paired seeds, sequential quiet box, gates on paired means.
  3 seeds is the round-1/2 confirm standard; accepted consequence: true effects
  below ~15mm may be missed (consistent with prior rounds).
- AVX2 misprobe → v2/vendored fallback is the default path; probe errors return False.
- Bench box ≠ factory boxes: absolute user-side gains may differ; we measure on the
  dev box and ship conservative ISA floors.
- Wall ≈ 4h end-to-end (~30min builds, ~2h workload 1, ~65min workload 2, analysis);
  TTL + incremental report keep partial results usable.

## 10. Acceptance

Matrix complete with a written report; every comparison paired; gates applied
mechanically; the gate-selected ship path executed (binaries, resolver + tests if
dual, `.gitignore` negation, PROVENANCE); docs updated (§ 6 entry, § 5.B, BACKLOG);
all engine tests green including the real-sparrow integration tests against the
shipped binaries.
