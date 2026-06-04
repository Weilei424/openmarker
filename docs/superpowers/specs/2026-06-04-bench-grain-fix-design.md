# Lock fabric grain to 90° and fix the canonical benchmark

**Date:** 2026-06-04
**Status:** Approved
**Resolves:** PERFORMANCE.md § 5.C — bench-vs-GUI variance on the unclustered path

---

## Problem

The bench (`bench_clustering.py`, calling `auto_layout_polygon` directly) reports
**12249.1mm / 75.83%** on the canonical workload (`sample_2.dxf × 10`,
fabric=1651mm, bi-grain, effort=5). The GUI (`POST /auto-layout`, same workload)
reports **11699mm / 79.4%**, reproduced on 2026-05-30 and 2026-06-04. Both paths
call the same `auto_layout_polygon`. The 550mm / 4.5% gap was unexplained and
filed as a § 5.C follow-up with three suspects: divergent input pieces,
non-result-preserving pruning (PR #7/#8), or a stale `/auto-layout` cache entry.

## Root cause (settled)

The two paths pass a **different `fabric_grain_deg`**:

- Frontend hard-codes `FABRIC_GRAIN_DEG = 90` (`frontend/src/app/App.tsx:18`),
  sent as `grain_direction_deg` → the GUI runs `auto_layout_polygon(..., fabric_grain_deg=90)`.
- Bench hard-codes `fabric_grain_deg=0.0` (`bench_clustering.py:93`), and
  PERFORMANCE.md § 1 documents the canonical benchmark at `0.0`.

`_layout_rotations` computes `target = (fabric_grain_deg - piece_grainline_deg) % 360`,
so switching 0 → 90 rotates every grain-constrained piece by +90°. All 190 pieces
in this workload carry grainlines, so the entire pack reorients against the fixed
1651mm width. `_compute_metrics` minimizes the same Y axis either way, so the two
marker lengths are directly comparable — both valid, different orientations.

**Controlled experiment** (bench's own input held constant, only `fabric_grain_deg`
varied, `disable_clustering=True`):

| `fabric_grain_deg` | effort | marker (mm) | utilization |
| --- | --- | --- | --- |
| 0.0 (bench config) | 1 & 5 | 12249.1 | 75.83% |
| 90.0 (GUI config)  | 1 & 5 | 11699.4 | 79.39% |

grain=90 reproduces the GUI/bar exactly; grain=0 reproduces the bench exactly.
The gap is **100% a benchmark-configuration divergence** — not input ordering
(frontend and bench expand copies identically, copy-major), not pruning (serial
and parallel agree within each grain setting), not the cache. **Pruning (PR #7/#8)
is exonerated.**

Domain note (high confidence): 90° aligns grain with the fabric roll length
(the +Y / marker-length axis), the physically standard marker orientation;
grain=0 ran grain across the bolt width, an orientation no real user produces.

## Decision

Make 90° the locked, single-source-of-truth fabric grain, fix the benchmark and
docs to measure the real configuration, and keep the engine's grain capability
intact (not externally driven):

- **Lock to 90° via a named constant** (no bare `90` literals).
- **Disable the API direction input**: `/auto-layout` stops reading
  `grain_direction_deg` and uses the constant.
- **Keep the engine code**: `fabric_grain_deg` stays a parameter; all grain logic
  remains (capability retained, just not externally variable).
- **Update bench + docs** to grain=90 referencing the constant.

Approved sub-decisions: D1 constant in `grain.py`; D2 re-run the clustering bench
at grain=90 to refresh § 1; D3 update all three benches; D4 silently ignore a
sent `grain_direction_deg` (no 422, keeps the current frontend working).

## Design

### 1. Single source of truth
Add `FABRIC_GRAIN_DEG = 90.0` to `engine/core/layout/grain.py` with a comment:
grain runs along the roll length (+Y, the axis BLF minimizes); fixed, not
user-configurable; the engine retains `fabric_grain_deg` for internal/test
flexibility but all production callers use this constant. Mirrors `App.tsx`.

### 2. API — disable direction input (`engine/api/main.py`)
Remove the `grain_direction_deg` read (`:129`); pass `FABRIC_GRAIN_DEG` into
`auto_layout_polygon` (`:203`). Update the docstring request example (`:100`) to
note grain is fixed. A `grain_direction_deg` in the body is silently ignored.

### 3. Engine — unchanged
`auto_layout_polygon(fabric_grain_deg=...)` and all grain handling stay as-is.
`engine/tests/unit/test_grain.py` stays (still exercises `allowed_rotations`
across 0/90/270… — the capability is retained).

### 4. Benches → reference the constant
`bench_clustering.py:93`, `bench_branch_pruning.py:80`, and `bench_sa.py` switch
`fabric_grain_deg=0.0` → `FABRIC_GRAIN_DEG` (imported from `core.layout.grain`).

### 5. Docs (`docs/planning/PERFORMANCE.md`)
- § 1: canonical benchmark → `fabric_grain_deg=90`; the unclustered "off" row
  becomes 11699.4mm / 79.39% — now meets the bar with **no algorithm change**.
  Re-run the clustering bench at grain=90 to refresh the bbox/union rows.
- § 5.C: replace the open bullet with the resolved finding + the experiment table.
- § 0: record that pruning (PR #7/#8) is exonerated — variance was grain config.
- § 6: new dated entry (2026-06-04) with the investigation and fix.
- SA tables (§ 4.6 / § 5.B / § 6 2026-05-31): annotate "measured at grain=0;
  superseded — Task #2 re-baselines SA at grain=90." (SA is **not** re-run here.)

### 6. Tests
Add to `engine/tests/integration/test_api_cache.py`: post identical pieces twice
with distinct filenames (to dodge cache dedup), once with `grain_direction_deg: 0`
and once with `90`, and assert **identical `marker_length_mm`** — proving the
field is ignored and the API always lays out at the locked grain.

## Out of scope (deliberate)
- Frontend untouched (already sends 90; now harmless/ignored).
- Engine `fabric_grain_deg` parameter not removed.
- `clustering.py` internal `fabric_grain_deg=0.0` defaults left alone (opt-in
  path; always receives the threaded value in practice).
- SA hyperparameter work and SA re-baselining → Task #2.

## Acceptance criteria
1. `bench_clustering.py` "off" on `sample_2.dxf × 10` reports 11699.4mm / 79.39%
   at effort 1 and 5 (matches the GUI and the § 1 bar).
2. `POST /auto-layout` ignores `grain_direction_deg`: the new integration test
   shows identical `marker_length_mm` for 0 vs 90.
3. Engine behavior unchanged; full `engine/tests/unit` + `integration` suites pass.
4. PERFORMANCE.md § 0 / § 1 / § 5.C / § 6 updated; SA tables annotated as
   grain=0 / superseded.

## Risks
- **Re-baselined clustering numbers differ from prior doc values** — expected;
  the old numbers were at the wrong grain. The new run is the honest baseline.
- **Frontend still sends `grain_direction_deg`** — intentionally ignored; no
  behavior change. A future cleanup can drop the send (out of scope here).
