# Periodic-lattice warm-start generator — spike (Ultra tier seed A/B)

> Design spec. Status: **approved** (brainstorm 2026-07-04). Owner: engine (layout).
> Extends: `docs/superpowers/specs/2026-06-07-separation-engine-phase2-design.md` (Ultra tier)
> and the round-2 warm-start work (PERFORMANCE.md § 6 [2026-06-12 round 2]).
> Origin: PERFORMANCE.md § 5.B "Periodic-lattice warm-start generator" row + § 6 [2026-07-04] survey, Find B.

## 1. Context

Cold sparrow plateaus ~10715mm on the canonical workload at every budget; the
shipped Fast-BLF warm start is what makes budget productive (production seed-42
@600s = 10597.8mm, first sub-commercial marker; solo mean across seeds 10614.3 —
still above the 10599mm commercial target). Sparrow's paper names the weakness the
warm start exploits: it "lacks a mechanism to repeat compact local patterns" on
homogeneous instances — and the canonical workload is exactly that (19 base
pieces × 10 copies). The Fast-BLF seed injects *accidental* row structure; this
spike tests whether a *deliberately periodic* seed — per-type densest-lattice
bands of Kuperberg 180° pairs — shifts the curve further. It is the one remaining
lever with a mechanism argument (rebuild A/B closed the throughput lever: quality
is not compute-bound at 600s).

Theory anchors: Kuperberg & Kuperberg 1990 (*double lattice* = two lattices
interchanged by a 180° rotation — exactly the bi-grain `{θ, θ+180}` set, no
mirroring); Milenkovic 2002 (densest translational lattice of k polygons,
motivated by garment marker making); Costa–Gomes–Oliveira (EJOR, NFP-derived
lattice vectors). NestingLattice (GitHub) has NO license — reimplement from the
papers, never copy. Full Milenkovic CG-to-MP is **rejected** for this spike: weeks
of MP work, and its asymptotic-density objective ignores the finite-N /
fixed-width boundary effects that dominate at 10 copies per type.

Workload facts (measured 2026-07-04): all 19 sample_2 pieces carry grainlines
(90°/180°/315° — the 315° bias strips exercise non-axis-aligned pairs); several
ids are duplicate shapes (piece_0≡piece_1, 2≡3, 6≡7, 9≡10, 15≡18, 16≡17);
perfect-density floor = 9288.2mm.

## 2. Decisions (brainstorm 2026-07-04)

| Decision | Choice |
|---|---|
| Arms | **3-arm** (user choice): control = Fast-BLF seed (production warm start), lattice = NFP-slide Kuperberg-pair lattice, banded = per-type BLF bands (mechanism ablation) |
| Protocol | Canonical workload (sample_2 ×10, 1651mm, bi @90°), 600s, matched seeds 42/43/44, strictly sequential, quiet box (~1h40m wall) |
| Seed semantics | Generator runs as an add-on prelude in every arm; sparrow always gets the full 600s (matches production warm-start semantics) |
| Lattice objective | Minimize **exact finite-N band length** at fabric width — not asymptotic lattice density |
| Band unit | **Identical-shape group** (equal normalized polygon + grainline), not base id: 13 bands instead of 19 on the canonical workload (6 duplicate pairs), double-size bands for duplicated shapes. Duplicate test = Shapely `equals` (topological, vertex-order-insensitive) behind grainline / vertex-count / area prefilters |
| Contact math | NFP-boundary / line intersections only (exact); **no** binary search on the non-monotone overlap predicate |
| Hard constraints | Unchanged: no mirroring, no tilt (user-excluded), grain enforced both ways, edges touchable (EDGE_GAP removed), `_validate_layout` is the gate for seeds AND finals |
| Code fate | `engine/core/layout/lattice.py` is written product-grade with unit tests; merges on GO (unreferenced by production until a follow-up PR), deleted on NO-GO with code preserved in the plan doc |
| Production changes during spike | **None** — the spike composes existing private helpers from `separation.py` |

## 3. Module layout

**New: `engine/core/layout/lattice.py`**

```python
def lattice_layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg)
    -> tuple[list[Placement], float, float]   # arm A
def banded_blf_layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg)
    -> tuple[list[Placement], float, float]   # arm B
```

Both mirror `auto_layout_polygon`'s return `(placements, marker_length_mm,
utilization_pct)` so `_placements_to_jagua` consumes them directly. Raise
`ValueError` when no orientation of some piece fits the fabric width (mirrors
`_validate_pieces_fit`). Deterministic — no RNG anywhere.

Internals (shared pipeline; only band construction differs between arms):
`_shape_groups` (band unit detection) → `_build_lattice_band` / `_build_blf_band`
→ `_stack_bands` (big-pieces-first, bbox offsets along y) → `_settle_bands`
(seam-waste recovery) → `_compute_metrics`.

**New: `engine/tests/spike_lattice_warmstart.py`** (throwaway, deleted at verdict).
Round-2/rebuild spike pattern: `smoke` / `run` / `evaluate` subcommands; kill-safe
incremental JSON+MD report rewritten after EVERY run; TTL-bound; resume skips
already-valid (arm, seed) pairs and re-runs invalid ones; seed-major arm
interleaving (control s42, lattice s42, banded s42, control s43, …). Reports in
gitignored `tools/lattice-spike/reports/`. Sparrow is driven exactly as
`_build_warm_start` does it: `_group_to_items` → `_instance_json` → generator
placements → `_placements_to_jagua(items, pieces, placements, marker)` →
`{**instance, "solution": {"strip_width": marker + 1.0, "layout":
{"container_id": 0, "placed_items": …, "density": 0.0}, "density": 0.0,
"run_time_sec": 0}}` → `_run_sparrow` → `_reconstruct` → `_validate_layout` →
`_compute_metrics`. Per-run workdirs persist `output/log.txt` + `sols_*/`
snapshots.

## 4. Lattice construction (arm A)

Engine frame: x = width ∈ [0, W=1651], y = length (minimized); placement (x, y) =
rotated-polygon bbox-min (matches `_placed_polygon`).

**Per shape group** (copies n, allowed engine rotations R from
`_layout_rotations`):

1. **Cell candidates.**
   - *Pair cells* (bi + grainline, R = {θ, θ+180}): P@θ at origin, P@(θ+180) at
     offset **d**; d ranges over the RAW exterior boundary of NFP(P@θ, P@θ+180)
     (existing `_get_or_compute_nfp`): vertices ∪ per-edge midpoints ∪ 50mm
     segmentize points, 1mm-deduped and stride-subsampled to ≤200 per part.
     Midpoints are load-bearing — the perfect pair offset for a right triangle
     is an NFP edge MIDPOINT, not a vertex. Raw boundary only — simplifying the
     NFP first can cut INSIDE it, and a candidate 0.5mm inside along a long
     contact edge creates overlap far beyond the 0.5mm² validator tolerance.
     This is the
     Kuperberg pair; θ from `_layout_rotations` makes every emitted rotation
     grain-legal by construction.
   - *Single cells*: {P@θ} (covers grain_mode="single", and beats pairing on
     rectangle-like pieces where the pair adds parasitic gaps). For bi, evaluate
     the single cell too and let the objective pick.
   - *No-grainline* (R = cardinals; absent from the canonical workload): pairs
     {0,180} and {90,270} plus singles {0} and {90}.

2. **Forbidden set.** F = ⋃ᵢⱼ (NFPᵢⱼ ⊕ (pᵢ − pⱼ)) over the cell's pieces — the
   translations t under which cell and cell+t overlap. Built from ≤4 pairwise
   NFPs (Shapely translate + union; may be a MultiPolygon).

3. **Lattice vectors** (strip-aligned restricted search):
   - **v0 = (w0, 0)** across the width: w0 = the rightmost crossing of F with the
     +x axis (Shapely line intersection). Any m·w0 (m ≥ 1) lies beyond that
     crossing on the same line, so a full row is overlap-free by construction.
   - **v1 = (sx, h1)** along the length: stagger samples sx ∈ {i·w0/8, i=0..7};
     h1 = the smallest y > 0 clear of F along ALL vertical lines
     x = sx + m·w0 for the column offsets m ∈ ℤ with |sx + m·w0| ≤ F's x-extent,
     and additionally clear for row-pairs j·v1 (j = 2, 3, …) while j·h1 < F's
     y-extent (guards row-skipping overlaps in deep interlocks). Each check is a
     topmost-crossing line intersection; taking the outermost exit never places
     inside F (holes in F are skipped conservatively — noted future refinement).

4. **Selection.** For each (cell, d, sx): row j sits at x-offset (j·sx) mod w0
   (columns are w0-periodic, so wrapping preserves the lattice); k = cells per
   row such that EVERY row fits, i.e. max_row_offset + (k−1)·w0 + cell x-extent
   ≤ W (k ≥ 1 required); cells = ⌈n / cell_size⌉; rows = ⌈cells / k⌉; exact band
   length = (rows−1)·h1 + cell y-extent (the partial last row sits at the same
   y as a full one). All formulaic from the chosen positions — no geometry in
   the inner loop. Argmin over all candidates wins.

5. **Assembly + fallback ladder.** Winning construction → band placements
   (row-major, partial row last) → full Shapely overlap + width validation of the
   band. On any failure (k = 0, invalid band, degenerate NFP): the group falls
   back to `_build_blf_band`; if that fails too, the entire layout falls back to
   plain Fast-BLF (`auto_layout_polygon`, effort=1). The spike logs which rung
   fired per group.

6. **Stack + settle.** Bands sorted by descending piece area; each band starts
   at the settled FRONTIER (max y over all settled pieces — never retreats,
   even when a band settles deeper than its own extent), then settles: slide
   toward y=0 in 2mm steps until first contact (start is clear by the frontier
   invariant, so "last clear step" is well-defined and safe; 1000-step safety
   cap = 2m — a deep partial-row notch in the previous band can absorb far more
   than a token slide), recovering seam waste from ragged band edges. Settle is
   shared by arms A and B.

Expected prelude cost: seconds (19 types × ≤~300 d-candidates × cheap line
intersections; NFPs memoized via the existing cache).

## 5. Banded-BLF (arm B)

Identical pipeline; each group's band is `_blf_pack_nfp` on that group's copies
alone at full width with `override_rotations` = the group's allowed set (flat
`list[float]` form) and `presorted=True` (copies identical — sorting is
meaningless). Zero new geometry. Interpretation: if lattice ≈ banded, the win is
grouping/repetition and the cheap construction ships; if lattice > banded, true
lattice density is doing real work.

## 6. Bench protocol & telemetry

- Per run: arm, seed, marker, util, wall, validator verdict, snapshot count
  (`sols_*/` SVGs), log-line count (`output/log.txt`), workdir path.
- Per arm (once): **seed-layout marker length** (pre-sparrow) — tests
  Milenkovic's premise directly (is the lattice seed denser than Fast-BLF's
  11393.2mm?), plus per-group ladder-rung log for arm A.
- Every kept run: the **seed** passes `_validate_layout` (arms must differ only
  in seed structure, and production seeds are valid by construction) AND the
  **final** reconstruction passes `_validate_layout`. Invalid/crashed runs are
  re-run via resume, never silently averaged.
- Noise anchors: cold mean 10722.7mm spread 120mm (n=21); fresh 2026-07-04
  control (vendored exe, warm @600s) = 10604.8 / 10693.3 / 10650.5, mean 10649.5.

## 7. Gates & verdict

- **G1 (validity):** all seeds and all finals validator-clean.
- **G2 (paired quality), per treatment arm vs control on matched seeds:**
  - GO: paired mean delta ≤ **−25mm** AND wins ≥ 2/3 seeds.
  - NO-GO: mean delta > 0 or wins ≤ 1/3.
  - Borderline (mean in (−25, 0] with ≥2 wins): extend ALL arms to seeds 45/46
    (matched) before the verdict.
  - Scale rationale: rebuild round showed +17…+43mm reads as noise at n=3; the
    real cold→warm mechanism effect was −74mm.
- **DECISIVE flag** (reported, not a gate): all 3 seeds < 10599mm — the project
  goal.
- **G3 (regression guard, GO only):** winning arm on `sample_4.dxf` ×6 @600s
  seed 42 vs its own control run. Worse by > 40mm ⇒ productization must be
  per-workload (build both seeds, pick the better pre-sparrow) rather than
  unconditional default. sample_4 is where the Fast-BLF seed measured neutral,
  so this bounds harm on structurally-unfavourable workloads.
- **Verdict = user checkpoint** with full tables (per-seed markers, paired
  deltas, seed-layout lengths, ladder logs) before any merge/ship action.

## 8. Testing

Unit tests for `lattice.py` (deterministic, no sparrow, synthetic shapes: rect,
L-shape, right triangle, 315°-grainline strip):

- Grain legality: every output rotation ∈ the allowed engine set for bi / single
  / no-grainline inputs.
- Validity: output passes `_validate_layout`; all copies placed, ids preserved;
  within width.
- Determinism: identical input → identical output.
- Fallback: a piece wider than the fabric in all orientations → `ValueError`;
  a group whose lattice construction degenerates → BLF-band rung fires.
- Mechanism: right-triangle pair band beats its single-cell band by ≥ 20%
  (two 180° triangles tile a rectangle = 100% density, while the best
  translational single-triangle lattice is 2/3 — the assert leaves margin for
  the 8-sample stagger discretization and finite-N boundary effects); rectangle
  pair does NOT beat its single cell by more than epsilon (pairing two
  rectangles side-by-side reduces to the single lattice).
- `banded_blf_layout`: same contract tests.
- Shape grouping: duplicate shapes share a band even when their rings start at
  different vertices; near-duplicates that miss the equality test fall back to
  separate bands (both valid).
- Existing 250-test engine suite stays green (spike touches no production
  module).

## 9. Deliverables & merge protocol

Worktree + feature branch (user creates at execution start, per convention;
fixtures `sample_2.dxf`/`sample_4.dxf` copied in — not in git). Commits on the
branch only.

- **GO:** `lattice.py` + tests merge (engine module, unreferenced by production);
  spike script deleted with its code preserved in the plan doc; follow-up PR
  planned separately to wire `run_separation_layout` (seed source selection,
  composition with best-of-N — decided with the data in hand).
- **NO-GO:** docs-only merge (protocol record); `lattice.py` and spike deleted,
  both preserved in the plan doc.
- Both paths: PERFORMANCE.md § 6 dated entry + § 5.B row status flip, BACKLOG
  outcome line, memory update.

## 10. Out of scope

- Productization wiring in `separation.py` / API / GUI (follow-up PR on GO).
- Mirroring and tilt tolerance (user-excluded, hard manufacturing constraint).
- Full Milenkovic CG-to-MP global optimum (rejected above).
- Interlocking across band seams beyond the translate-only settle pass.
- Multi-type cells (mixing different shapes in one lattice cell).
- NFP-hole interlock candidates (outermost-exit rule skips them; noted as a
  refinement if the spike lands borderline).
