# Periodic-Lattice Warm-Start Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build two deterministic warm-start layout generators (Kuperberg-pair lattice + banded-BLF) and A/B them against the production Fast-BLF seed as sparrow's warm start on the canonical workload, under the established noise-floor protocol.

**Architecture:** New engine module `engine/core/layout/lattice.py` produces full valid layouts shaped like `auto_layout_polygon`'s return; a throwaway spike script feeds each generator's output to the vendored `sparrow.exe` through the existing `-i` warm-start converter (`_placements_to_jagua`) and evaluates paired gates. No production module changes.

**Tech Stack:** Python 3.11 (engine venv), Shapely 2.x, pyclipper (via existing NFP helpers), pytest, vendored `sparrow.exe`.

**Spec:** `docs/superpowers/specs/2026-07-04-lattice-warmstart-design.md` (approved 2026-07-04).

## Global Constraints

- Canonical protocol: `sample_2.dxf` ×10 copies, fabric **1651.0mm**, grain **bi @90°**, budget **600s**, matched seeds **42,43,44**, strictly sequential runs on a quiet box.
- Arms: `control` (Fast NFP-BLF seed = production warm start), `lattice`, `banded` — same vendored exe, arms differ ONLY by the `-i` instance's embedded `"solution"`.
- Seed semantics: generator runs as an add-on prelude; sparrow always gets the full 600s (`-t 600`).
- Hard constraints unchanged: NO mirroring, NO tilt tolerance, grain enforced both ways, fabric edges touchable; `separation._validate_layout` gates **seeds AND finals**.
- **No production module changes**: `heuristic.py`, `separation.py`, `clustering.py`, `api/` stay untouched. `lattice.py` is new and unreferenced by production.
- Generators are deterministic — no RNG anywhere; both mirror `auto_layout_polygon`'s return `(placements, marker_length_mm, utilization_pct)` and raise `ValueError` when a piece fits at no allowed rotation (or on empty input).
- Gates (spec §7): **G1** all seeds + finals validator-clean. **G2** per arm vs control: GO = paired mean ≤ **−25.0mm** AND wins ≥ 2/3 of seeds; NO-GO = mean > 0 or wins ≤ 1/3; borderline = extend ALL arms to seeds 45,46 first. **DECISIVE** flag = all seeds < **10599.0mm**. **G3** (GO only) winner vs control on `sample_4.dxf` ×6 @600s seed 42: FAIL if worse by > **40.0mm**.
- Reference anchors: cold mean 10722.7mm spread 120mm (n=21); fresh 2026-07-04 warm control = 10604.8 / 10693.3 / 10650.5 (mean 10649.5); Fast-BLF seed layout = 11393.2mm; theoretical floor 9288.2mm.
- Reports/workdirs under gitignored `tools/lattice-spike/`; per-run workdirs keep `output/log.txt` (the real log — stderr is empty) + `output/sols_*/` **SVG** snapshots.
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Context for implementers

- `WT` below = the worktree root the user created (e.g. `D:\openmarker\.worktrees\openmarker-lattice`), branch `feat/lattice-warmstart`. The main tree stays on `main` at `D:\openmarker`.
- The engine venv lives ONLY in the main tree: `D:\openmarker\engine\.venv\Scripts\python.exe`. Always run tests as `python -m pytest` with CWD `WT\engine` so `core.*` resolves to the worktree's code.
- Fixtures `sample_2.dxf` / `sample_4.dxf` are NOT in git — Task 1 copies them into the worktree.
- Key existing interfaces (do not modify):
  - `heuristic.Placement(piece_id, x, y, rotation_deg)` — (x, y) = rotated-polygon **bbox-min** (what `_placed_polygon(piece, x, y, rot)` expects).
  - `heuristic._get_or_compute_nfp(cache, piece_a, rot_a, piece_b, rot_b) -> list[ShapelyPolygon]` — NFPs live in the **raw rotated frame**: both polygons rotated CW about (0,0), UNtranslated (`_polygon_at_origin`). A point `t` in the NFP means "B translated by t overlaps A".
  - `heuristic._blf_pack_nfp(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, sort_key=None, nfp_cache=None, best_marker_so_far=None, shared_best_value=None, override_rotations=None, skip_validation=False, presorted=False) -> (placements, marker, util)`.
  - `heuristic._layout_rotations(grain_mode, fabric_grain_deg, grainline) -> list[float]` — bi+grainline → `[θ, θ+180]`; single → `[θ]`; no grainline → `[0, 90, 180, 270]`.
  - `heuristic._compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims) -> (marker, util)`; `heuristic._has_area_overlap(a, b)` (eps 0.5mm²); `heuristic._validate_pieces_fit(...)`; `heuristic.auto_layout_polygon(..., effort=1)` = Fast tier.
  - `clustering.group_pieces_by_base_id(pieces) -> OrderedDict[str, list[Piece]]`.
  - `separation._group_to_items / _instance_json / _placements_to_jagua / _reconstruct / _validate_layout / _resolve_sparrow_path` — exactly as used by `_build_warm_start` / `run_separation_layout`.

---

### Task 1: Worktree preflight + docs on branch

**Files:**
- Create (copy in): `WT\examples\input\sample_2.dxf`, `WT\examples\input\sample_4.dxf` (not committed — gitignored fixtures)
- Create: `WT\docs\superpowers\specs\2026-07-04-lattice-warmstart-design.md`, `WT\docs\superpowers\plans\2026-07-05-lattice-warmstart.md` (copied from the main tree, committed)
- Modify: `WT\docs\planning\BACKLOG.md` (append execution checklist)

**Interfaces:**
- Consumes: nothing.
- Produces: a verified worktree where later tasks run; spec/plan/BACKLOG committed on `feat/lattice-warmstart`.

- [ ] **Step 1: Verify worktree + branch**

```powershell
cd WT
git rev-parse --abbrev-ref HEAD
git status --short
```
Expected: `feat/lattice-warmstart`, clean tree. If the worktree doesn't exist, STOP and ask the user to create it (convention: user creates worktrees).

- [ ] **Step 2: Copy fixtures (not in git)**

```powershell
New-Item -ItemType Directory -Force WT\examples\input
Copy-Item D:\openmarker\examples\input\sample_2.dxf WT\examples\input\ -Force
Copy-Item D:\openmarker\examples\input\sample_4.dxf WT\examples\input\ -Force
```

- [ ] **Step 3: Baseline test run**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: full suite green (≈259 tests; integration sparrow tests use the committed vendored exe). Any failure here = pre-existing breakage — STOP and report.

- [ ] **Step 4: Copy spec + plan into the worktree**

```powershell
Copy-Item D:\openmarker\docs\superpowers\specs\2026-07-04-lattice-warmstart-design.md WT\docs\superpowers\specs\
Copy-Item D:\openmarker\docs\superpowers\plans\2026-07-05-lattice-warmstart.md WT\docs\superpowers\plans\
```

- [ ] **Step 5: Append the execution checklist to `WT\docs\planning\BACKLOG.md`**

Append at the end of the file:

```markdown
### Lattice warm-start spike (spec 2026-07-04) Execution Checklist

- [ ] P1: Worktree preflight + spec/plan/BACKLOG committed on branch
- [ ] P2: lattice.py banded pipeline (shape groups, BLF bands, stack+settle) + tests
- [ ] P3: lattice.py lattice bands (Kuperberg pair cells, NFP lattice vectors) + mechanism tests
- [ ] P4: Spike runner + smoke (3 arms × 15s × 1 copy)
- [ ] P5: Canonical matrix — 3 arms × seeds 42/43/44 @600s (~1h40m)
- [ ] P6: Gate evaluation + verdict [USER CHECKPOINT]
- [ ] P7: Conditional GO path: sample_4×6 G3 guard
- [ ] P8: Conditional NO-GO path: delete lattice.py + tests + spike
- [ ] P9: Docs (PERFORMANCE §6 + §5.B, BACKLOG outcome), PR, final review
```

- [ ] **Step 6: Commit**

```powershell
cd WT
git add docs/superpowers/specs/2026-07-04-lattice-warmstart-design.md docs/superpowers/plans/2026-07-05-lattice-warmstart.md docs/planning/BACKLOG.md
git commit -m "docs: spec + plan + BACKLOG checklist for the lattice warm-start spike

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `lattice.py` — banded pipeline (shape groups, BLF bands, stack + settle, `banded_blf_layout`)

**Files:**
- Create: `WT\engine\core\layout\lattice.py`
- Test: `WT\engine\tests\unit\test_lattice.py`

**Interfaces:**
- Consumes: `heuristic._blf_pack_nfp`, `_layout_rotations`, `_placed_polygon`, `_polygon_dims`, `_compute_metrics`, `_has_area_overlap`, `_validate_pieces_fit`, `auto_layout_polygon`, `Placement`, `NfpCache`; `clustering.group_pieces_by_base_id`; `Piece`.
- Produces (used by Tasks 3–5):
  - `banded_blf_layout(pieces: list[Piece], fabric_width_mm: float, grain_mode: str, fabric_grain_deg: float, ladder_log: list[tuple[str, str]] | None = None) -> tuple[list[Placement], float, float]`
  - `_layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, band_builders, ladder_log)` — shared driver; `band_builders` = ordered ladder of `(rung_name, builder)` where `builder(group, fabric_width_mm, grain_mode, fabric_grain_deg, cache) -> _Band | None`.
  - `_Band(placements: list[Placement], length: float, sort_area: float)`; `_shape_groups(pieces) -> list[list[Piece]]`; `_build_blf_band(...)`; `_raw_rotated(piece, rotation_deg) -> ShapelyPolygon`.

- [ ] **Step 1: Write the failing tests**

Create `WT\engine\tests\unit\test_lattice.py`:

```python
import pytest
from shapely.geometry import Polygon as ShapelyPolygon

from core.layout.lattice import _shape_groups, banded_blf_layout
from core.layout.separation import _validate_layout
from core.models.piece import BoundingBox, Piece

FABRIC_W = 1000.0


def _piece(pid, points, grainline=None):
    poly = ShapelyPolygon(points)
    minx, miny, maxx, maxy = poly.bounds
    return Piece(id=pid, name=pid, polygon=list(points), area=poly.area,
                 bbox=BoundingBox(minx, miny, maxx, maxy, maxx - minx, maxy - miny),
                 is_valid=True, grainline_direction_deg=grainline)


def _rect(pid, w, h, grainline=None):
    return _piece(pid, [(0, 0), (w, 0), (w, h), (0, h)], grainline)


def _rtri(pid, w, h, grainline=None):
    return _piece(pid, [(0, 0), (w, 0), (0, h)], grainline)


def _lshape(pid, grainline=None):
    # bottom bar y 0..80 full width 0..200 + left column x 0..80 up to y 200
    return _piece(pid, [(0, 0), (200, 0), (200, 80), (80, 80), (80, 200), (0, 200)],
                  grainline)


def _notch_l(pid, grainline=None):
    # bottom bar y 0..80 full width 0..200 + RIGHT column x 120..200 up to y 200;
    # free notch = x 0..120, y 80..200
    return _piece(pid, [(0, 0), (200, 0), (200, 200), (120, 200), (120, 80), (0, 80)],
                  grainline)


def _copies(factory, base, n, *args, **kw):
    return [factory(f"{base}__c{i}", *args, **kw) for i in range(n)]


def _mixed_set(n=6):
    return (_copies(_rect, "piece_0", n, 300, 200, grainline=90.0)
            + _copies(_lshape, "piece_1", n, grainline=90.0)
            + _copies(_rtri, "piece_2", n, 250, 180, grainline=90.0))


# --- _shape_groups ---

def test_shape_groups_merges_exact_duplicates_any_ring_start():
    pts_a = [(0, 0), (300, 0), (300, 200), (0, 200)]
    pts_b = [(300, 0), (300, 200), (0, 200), (0, 0)]   # same ring, rotated start
    pieces = (_copies(_piece, "piece_0", 2, pts_a, grainline=90.0)
              + _copies(_piece, "piece_1", 2, pts_b, grainline=90.0)
              + _copies(_rect, "piece_2", 2, 100, 50, grainline=90.0))
    groups = _shape_groups(pieces)
    assert sorted(len(g) for g in groups) == [2, 4]


def test_shape_groups_respects_grainline():
    pieces = (_copies(_rect, "piece_0", 2, 300, 200, grainline=90.0)
              + _copies(_rect, "piece_1", 2, 300, 200, grainline=180.0))
    assert [len(g) for g in _shape_groups(pieces)] == [2, 2]


# --- banded_blf_layout contract ---

def test_banded_valid_and_complete():
    pieces = _mixed_set()
    placements, marker, util = banded_blf_layout(pieces, FABRIC_W, "bi", 90.0)
    _validate_layout(placements, pieces, FABRIC_W, "bi", 90.0)   # raises on violation
    assert {p.piece_id for p in placements} == {p.id for p in pieces}
    assert marker > 0 and 0 < util <= 100


def test_banded_rotations_stay_in_bi_grain_set():
    placements, _, _ = banded_blf_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    for p in placements:
        assert min(p.rotation_deg % 360.0, abs(p.rotation_deg % 360.0 - 180.0),
                   abs(p.rotation_deg % 360.0 - 360.0)) < 1e-6


def test_banded_single_mode_locks_rotation():
    placements, _, _ = banded_blf_layout(
        _copies(_rect, "p", 4, 300, 200, grainline=90.0), FABRIC_W, "single", 90.0)
    assert all(abs(p.rotation_deg % 360.0) < 1e-6 for p in placements)


def test_banded_deterministic():
    a = banded_blf_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    b = banded_blf_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    assert [(p.piece_id, p.x, p.y, p.rotation_deg) for p in a[0]] == \
           [(p.piece_id, p.x, p.y, p.rotation_deg) for p in b[0]]
    assert a[1] == b[1]


def test_banded_too_wide_raises():
    with pytest.raises(ValueError):
        banded_blf_layout(_copies(_rect, "p", 2, 1200, 100, grainline=90.0),
                          FABRIC_W, "bi", 90.0)


def test_banded_empty_raises():
    with pytest.raises(ValueError):
        banded_blf_layout([], FABRIC_W, "bi", 90.0)


def test_banded_ladder_log():
    log = []
    banded_blf_layout(_mixed_set(), FABRIC_W, "bi", 90.0, ladder_log=log)
    assert len(log) == 3 and all(rung == "blf" for _, rung in log)


def test_banded_single_copy_group():
    placements, marker, _ = banded_blf_layout(
        [_rect("p__c0", 300, 200, grainline=90.0)], FABRIC_W, "bi", 90.0)
    assert len(placements) == 1 and marker == pytest.approx(200.0, abs=1e-6)


def test_settle_slides_band_into_notch():
    # Band 1 (bigger area) = notch-L; band 2 = 60x60 rect placed above it, which
    # settles down through the free notch until it rests on the y<=80 bottom bar.
    pieces = [_notch_l("piece_0__c0", grainline=90.0),
              _rect("piece_1__c0", 60, 60, grainline=90.0)]
    placements, marker, _ = banded_blf_layout(pieces, 300.0, "single", 90.0)
    _validate_layout(placements, pieces, 300.0, "single", 90.0)
    # without settle the marker would be 260 (200 + 60); with settle the rect
    # rests at y ~= 80..140 -> marker stays 200 (2mm probe granularity slack)
    assert marker == pytest.approx(200.0, abs=2.1)


def test_stack_frontier_never_retreats_past_earlier_bands():
    # Band 2 settles deeper (120mm) than its own extent (60mm). The stacking
    # frontier must stay at band 1's edge (y=200), not retreat to 140 — a
    # third band starting below the frontier would begin INSIDE band 1's
    # right column and settle would silently accept the overlap.
    pieces = [_notch_l("piece_0__c0", grainline=90.0),
              _rect("piece_1__c0", 60, 60, grainline=90.0),
              _rect("piece_2__c0", 150, 20, grainline=90.0)]
    placements, marker, _ = banded_blf_layout(pieces, 300.0, "single", 90.0)
    _validate_layout(placements, pieces, 300.0, "single", 90.0)
    # rect 150x20 rests on the notch-L column top (y 200..220)
    assert marker == pytest.approx(220.0, abs=2.1)
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_lattice.py -v
```
Expected: collection error — `ModuleNotFoundError: No module named 'core.layout.lattice'`.

- [ ] **Step 3: Create `WT\engine\core\layout\lattice.py`**

```python
"""Periodic-lattice and banded warm-start layout generators (Ultra-tier seed spike).

Spec: docs/superpowers/specs/2026-07-04-lattice-warmstart-design.md
(PERFORMANCE.md § 5.B "Periodic-lattice warm-start generator").

Both public functions mirror auto_layout_polygon's return
(placements, marker_length_mm, utilization_pct) and produce layouts that pass
separation._validate_layout, so the Ultra warm-start converter
(_placements_to_jagua) consumes them directly. NOT wired into production — the
spike (engine/tests/spike_lattice_warmstart.py) is the only caller until a GO
verdict.

Frames: lattice math happens in the NFP frame (polygon rotated CW about (0, 0),
then translated by t — matching _polygon_at_origin / _get_or_compute_nfp).
Emitted Placements use the engine convention (x, y) = rotated-polygon bbox-min,
the frame _placed_polygon expects.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import shapely
import shapely.affinity
from shapely.geometry import LineString, Polygon as ShapelyPolygon
from shapely.ops import unary_union

from core.layout.clustering import group_pieces_by_base_id
from core.layout.heuristic import (
    NfpCache,
    Placement,
    _blf_pack_nfp,
    _compute_metrics,
    _get_or_compute_nfp,
    _has_area_overlap,
    _layout_rotations,
    _placed_polygon,
    _polygon_dims,
    _validate_pieces_fit,
    auto_layout_polygon,
)
from core.models.piece import Piece

# Search-resolution knobs (spec § 4). Module constants, not public API.
STAGGER_SAMPLES = 8        # v1 stagger candidates per (cell, d): sx = i * w0 / 8
D_CANDIDATE_CAP = 200      # max pair offsets per NFP part after dedup
SEGMENT_MM = 50.0          # NFP edge densification for edge-interior contacts
SETTLE_STEP_MM = 2.0       # band settle probe step
SETTLE_MAX_STEPS = 1000    # safety cap = 2 m of slide per band
_MIN_PERIOD = 0.5          # mm — reject degenerate lattice vectors below this
_EPS = 1e-6


@dataclass
class _Band:
    """One per-shape-group band, in band-local coords (y starts at 0)."""
    placements: list[Placement]
    length: float              # band y-extent = its marker-length contribution
    sort_area: float           # representative piece area — stacking order key


def _raw_rotated(piece: Piece, rotation_deg: float) -> ShapelyPolygon:
    """Piece polygon rotated CW (screen frame) about (0, 0), NOT translated —
    the frame the NFPs from _get_or_compute_nfp live in."""
    return shapely.affinity.rotate(
        ShapelyPolygon(piece.polygon), rotation_deg, origin=(0, 0), use_radians=False)


def _shape_groups(pieces: list[Piece]) -> list[list[Piece]]:
    """Base-id groups, merged when representatives are exact duplicates (same
    grainline + vertex count + area, topological equality — vertex-order-
    insensitive). Duplicated block shapes (e.g. sample_2 piece_0 == piece_1)
    then share one band; a missed merge is harmless — the shapes just band
    separately (spec § 2 'Band unit')."""
    merged: list[tuple[Piece, ShapelyPolygon, list[Piece]]] = []
    for members in group_pieces_by_base_id(pieces).values():
        rep = members[0]
        poly = ShapelyPolygon(rep.polygon)
        for mrep, mpoly, mlist in merged:
            if (mrep.grainline_direction_deg == rep.grainline_direction_deg
                    and len(mrep.polygon) == len(rep.polygon)
                    and abs(mrep.area - rep.area) < 1e-6
                    and mpoly.equals(poly)):
                mlist.extend(members)
                break
        else:
            merged.append((rep, poly, list(members)))
    return [mlist for _, _, mlist in merged]


def _build_blf_band(group: list[Piece], fabric_width_mm: float, grain_mode: str,
                    fabric_grain_deg: float, cache: NfpCache) -> _Band | None:
    """Arm-B band: NFP-BLF over just this group's copies at full fabric width.
    Copies are identical, so sorting is meaningless -> presorted=True."""
    rep = group[0]
    rotset = _layout_rotations(grain_mode, fabric_grain_deg, rep.grainline_direction_deg)
    try:
        placements, marker, _util = _blf_pack_nfp(
            list(group), fabric_width_mm, grain_mode, fabric_grain_deg,
            nfp_cache=cache, override_rotations=list(rotset), presorted=True)
    except ValueError:
        return None
    return _Band(placements, marker, rep.area)


def _band_collides(trial: list[ShapelyPolygon], placed: list[ShapelyPolygon],
                   placed_bounds: list[tuple[float, float, float, float]]) -> bool:
    for t in trial:
        tb = t.bounds
        for p, pb in zip(placed, placed_bounds):
            if tb[2] < pb[0] or pb[2] < tb[0] or tb[3] < pb[1] or pb[3] < tb[1]:
                continue
            if _has_area_overlap(t, p):
                return True
    return False


def _settle_shift(polys: list[ShapelyPolygon], placed: list[ShapelyPolygon],
                  placed_bounds: list[tuple[float, float, float, float]]) -> float:
    """Largest safe downward (-y) slide for a band: bbox fast-forward to the
    nearest possible contact, then SETTLE_STEP_MM polygon probes until first
    contact. The start position is clear (guaranteed by _stack_and_settle's
    frontier invariant), so 'last clear step' is well-defined; the floor y >= 0
    is a hard stop (spec § 4.6)."""
    floor = min(p.bounds[1] for p in polys)          # distance to y = 0
    gap = floor
    for a in polys:
        ab = a.bounds
        for pb in placed_bounds:
            if ab[2] < pb[0] or pb[2] < ab[0]:
                continue                             # no x overlap -> no constraint
            if pb[3] <= ab[1] + _EPS:
                gap = min(gap, ab[1] - pb[3])        # vertical bbox gap
            else:
                gap = 0.0                            # bboxes already interleaved
    gap = max(0.0, gap)
    cur = [shapely.affinity.translate(p, yoff=-gap) for p in polys] if gap else list(polys)
    shift = gap
    for _ in range(SETTLE_MAX_STEPS):
        if shift + SETTLE_STEP_MM > floor + _EPS:
            break
        trial = [shapely.affinity.translate(p, yoff=-SETTLE_STEP_MM) for p in cur]
        if _band_collides(trial, placed, placed_bounds):
            break
        cur, shift = trial, shift + SETTLE_STEP_MM
    return shift


def _stack_and_settle(bands: list[_Band], pieces_by_id: dict[str, Piece]) -> list[Placement]:
    """Stack bands big-pieces-first along +y, settling each band toward y = 0
    against the already-settled ones (spec § 4.6). Each band starts at the
    settled FRONTIER — max y over all settled pieces — so its start position is
    clear by construction even when an earlier band settled deeper than its own
    extent (a plain running offset would drag the start back inside band 1)."""
    ordered = sorted(bands, key=lambda b: -b.sort_area)
    out: list[Placement] = []
    placed: list[ShapelyPolygon] = []
    placed_bounds: list[tuple[float, float, float, float]] = []
    y_off = 0.0
    for band in ordered:
        polys = [_placed_polygon(pieces_by_id[p.piece_id], p.x, p.y + y_off, p.rotation_deg)
                 for p in band.placements]
        shift = _settle_shift(polys, placed, placed_bounds) if placed else 0.0
        for p, poly in zip(band.placements, polys):
            out.append(Placement(p.piece_id, p.x, round(p.y + y_off - shift, 4),
                                 p.rotation_deg))
            settled = shapely.affinity.translate(poly, yoff=-shift) if shift else poly
            placed.append(settled)
            placed_bounds.append(settled.bounds)
        y_off = max(pb[3] for pb in placed_bounds)   # frontier, never retreats
    return out


def _layout(pieces: list[Piece], fabric_width_mm: float, grain_mode: str,
            fabric_grain_deg: float, band_builders, ladder_log):
    """Shared banded pipeline. band_builders = ordered fallback ladder of
    (rung_name, builder) tried per shape group; a group with no band at all
    drops the WHOLE layout to plain Fast-BLF (spec § 4.5)."""
    if not pieces:
        raise ValueError("no pieces to lay out")
    _validate_pieces_fit(pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
                         _polygon_dims)
    cache: NfpCache = {}
    bands: list[_Band] = []
    for group in _shape_groups(pieces):
        band, rung = None, None
        for name, builder in band_builders:
            band = builder(group, fabric_width_mm, grain_mode, fabric_grain_deg, cache)
            if band is not None:
                rung = name
                break
        if band is None:
            if ladder_log is not None:
                ladder_log.append((group[0].id, "fast-blf-fallback"))
            return auto_layout_polygon(pieces, fabric_width_mm, grain_mode,
                                       fabric_grain_deg, effort=1)
        if ladder_log is not None:
            ladder_log.append((group[0].id, rung))
        bands.append(band)
    placements = _stack_and_settle(bands, {p.id: p for p in pieces})
    marker, util = _compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims)
    return placements, marker, util


def banded_blf_layout(pieces: list[Piece], fabric_width_mm: float, grain_mode: str,
                      fabric_grain_deg: float,
                      ladder_log: list[tuple[str, str]] | None = None,
                      ) -> tuple[list[Placement], float, float]:
    """Arm B: per-shape-group BLF bands, stacked + settled. Deterministic."""
    return _layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
                   [("blf", _build_blf_band)], ladder_log)
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_lattice.py -v
```
Expected: all Task-2 tests PASS. If `test_settle_slides_band_into_notch` fails on the exact marker, print the actual marker — a value in (200.0, 202.1] is the 2mm probe granularity and fine (assert allows it); anything ≥ 258 means settle didn't fire — debug `_settle_shift`.

- [ ] **Step 5: Full engine suite still green**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: baseline count + new tests, all green.

- [ ] **Step 6: Commit**

```powershell
cd WT
git add engine/core/layout/lattice.py engine/tests/unit/test_lattice.py
git commit -m "feat(engine): banded warm-start generator (shape groups, BLF bands, stack+settle)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `lattice.py` — Kuperberg-pair lattice bands (`lattice_layout`)

**Files:**
- Modify: `WT\engine\core\layout\lattice.py` (append the lattice construction; no changes to Task-2 code)
- Test: `WT\engine\tests\unit\test_lattice.py` (append lattice tests)

**Interfaces:**
- Consumes: Task 2's `_layout`, `_Band`, `_build_blf_band`, `_raw_rotated`, constants; `heuristic._get_or_compute_nfp`, `_layout_rotations`, `_has_area_overlap`.
- Produces (used by Tasks 4–5): `lattice_layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, ladder_log=None) -> tuple[list[Placement], float, float]`.

- [ ] **Step 1: Append the failing tests to `WT\engine\tests\unit\test_lattice.py`**

```python
# --- lattice_layout ---

from core.layout.lattice import lattice_layout


def test_lattice_valid_and_complete():
    pieces = _mixed_set()
    placements, marker, util = lattice_layout(pieces, FABRIC_W, "bi", 90.0)
    _validate_layout(placements, pieces, FABRIC_W, "bi", 90.0)
    assert {p.piece_id for p in placements} == {p.id for p in pieces}
    assert marker > 0 and 0 < util <= 100


def test_lattice_rotations_stay_in_bi_grain_set():
    placements, _, _ = lattice_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    for p in placements:
        assert min(p.rotation_deg % 360.0, abs(p.rotation_deg % 360.0 - 180.0),
                   abs(p.rotation_deg % 360.0 - 360.0)) < 1e-6


def test_lattice_single_mode_locks_rotation():
    placements, _, _ = lattice_layout(
        _copies(_rect, "p", 4, 300, 200, grainline=90.0), FABRIC_W, "single", 90.0)
    assert all(abs(p.rotation_deg % 360.0) < 1e-6 for p in placements)


def test_lattice_no_grainline_uses_cardinals_only():
    pieces = _copies(_rect, "p", 4, 300, 200, grainline=None)
    placements, _, _ = lattice_layout(pieces, FABRIC_W, "bi", 90.0)
    _validate_layout(placements, pieces, FABRIC_W, "bi", 90.0)
    for p in placements:
        assert any(abs(((p.rotation_deg - c + 180.0) % 360.0) - 180.0) < 1e-6
                   for c in (0.0, 90.0, 180.0, 270.0))


def test_lattice_deterministic():
    a = lattice_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    b = lattice_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    assert [(p.piece_id, p.x, p.y, p.rotation_deg) for p in a[0]] == \
           [(p.piece_id, p.x, p.y, p.rotation_deg) for p in b[0]]
    assert a[1] == b[1]


def test_lattice_too_wide_raises():
    with pytest.raises(ValueError):
        lattice_layout(_copies(_rect, "p", 2, 1200, 100, grainline=90.0),
                       FABRIC_W, "bi", 90.0)


def test_lattice_ladder_log_uses_lattice_rung():
    log = []
    lattice_layout(_mixed_set(), FABRIC_W, "bi", 90.0, ladder_log=log)
    assert len(log) == 3
    assert all(rung in ("lattice", "blf") for _, rung in log)
    assert log[0][1] == "lattice"      # the plain-rect group must lattice cleanly


def test_lattice_falls_back_to_blf_band(monkeypatch):
    import core.layout.lattice as lat
    monkeypatch.setattr(lat, "_build_lattice_band",
                        lambda group, W, gm, gd, cache: None)
    log = []
    pieces = _mixed_set()
    placements, _, _ = lattice_layout(pieces, FABRIC_W, "bi", 90.0, ladder_log=log)
    _validate_layout(placements, pieces, FABRIC_W, "bi", 90.0)
    assert all(rung == "blf" for _, rung in log)


def test_triangle_pair_beats_single_by_20pct():
    # Two 180-deg right triangles tile a rectangle (100% density); the best
    # translational single-triangle lattice is far sparser. single grain mode
    # forbids the 180 partner -> single-cell lattice as the reference.
    tris = _copies(_rtri, "t", 10, 300, 200, grainline=90.0)
    m_pair = lattice_layout(tris, FABRIC_W, "bi", 90.0)[1]
    m_single = lattice_layout(tris, FABRIC_W, "single", 90.0)[1]
    assert m_pair <= 0.8 * m_single


def test_rect_pair_no_gain_over_single():
    rects = _copies(_rect, "r", 10, 300, 200, grainline=90.0)
    m_bi = lattice_layout(rects, FABRIC_W, "bi", 90.0)[1]
    m_single = lattice_layout(rects, FABRIC_W, "single", 90.0)[1]
    assert abs(m_bi - m_single) <= 1.0


def test_lattice_bias_grainline_strip():
    # 32x330 strips with a 315-deg grainline: allowed engine rotations are
    # {135, 315} (target = (90 - 315) % 360 = 135) — diagonal lattice.
    strips = _copies(_rect, "s", 10, 32, 330, grainline=315.0)
    placements, _, _ = lattice_layout(strips, 800.0, "bi", 90.0)
    _validate_layout(placements, strips, 800.0, "bi", 90.0)
    for p in placements:
        assert any(abs(((p.rotation_deg - a + 180.0) % 360.0) - 180.0) < 1e-6
                   for a in (135.0, 315.0))


def test_lattice_single_copy_group():
    placements, marker, _ = lattice_layout(
        [_rect("p__c0", 300, 200, grainline=90.0)], FABRIC_W, "bi", 90.0)
    assert len(placements) == 1 and marker == pytest.approx(200.0, abs=1e-6)
```

- [ ] **Step 2: Run to verify the new tests fail**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_lattice.py -v
```
Expected: `ImportError: cannot import name 'lattice_layout'` (Task-2 tests still pass when run alone; the module-level import fails the whole file — that's fine).

- [ ] **Step 3: Append the lattice construction to `WT\engine\core\layout\lattice.py`**

```python
# ---------------------------------------------------------------------------
# Lattice bands (arm A) — spec § 4
# ---------------------------------------------------------------------------

@dataclass
class _Cell:
    """One lattice cell. Members are (engine rotation, t) with t the NFP-frame
    translation of the raw-rotated polygon; bbox_* describe the member union."""
    rotations: list[float]
    offsets: list[tuple[float, float]]
    x_extent: float
    y_extent: float
    bbox_min: tuple[float, float]


def _make_cell(piece: Piece, rotations: list[float],
               offsets: list[tuple[float, float]]) -> _Cell:
    bounds = [
        shapely.affinity.translate(_raw_rotated(piece, r), xoff=tx, yoff=ty).bounds
        for r, (tx, ty) in zip(rotations, offsets)
    ]
    minx = min(b[0] for b in bounds)
    miny = min(b[1] for b in bounds)
    maxx = max(b[2] for b in bounds)
    maxy = max(b[3] for b in bounds)
    return _Cell(rotations, offsets, maxx - minx, maxy - miny, (minx, miny))


def _forbidden_set(piece: Piece, cell: _Cell, cache: NfpCache):
    """F = { t : cell overlaps (cell + t) } = union over member pairs (i, j) of
    NFP(shape@rot_i, shape@rot_j) translated by (t_i - t_j)  (spec § 4.2)."""
    parts = []
    for ri, ti in zip(cell.rotations, cell.offsets):
        for rj, tj in zip(cell.rotations, cell.offsets):
            for nfp in _get_or_compute_nfp(cache, piece, ri, piece, rj):
                parts.append(shapely.affinity.translate(
                    nfp, xoff=ti[0] - tj[0], yoff=ti[1] - tj[1]))
    return unary_union(parts)


def _exit_along_x(F) -> float:
    """Rightmost crossing of F with the +x axis = smallest safe horizontal
    period w0. Any m*w0 (m >= 1) lies beyond every crossing on that line, so a
    whole row is overlap-free by construction (spec § 4.3)."""
    line = LineString([(0.0, 0.0), (F.bounds[2] + 1.0, 0.0)])
    hit = F.intersection(line)
    return 0.0 if hit.is_empty else hit.bounds[2]


def _top_crossing(F, cx: float) -> float:
    """Topmost crossing (y >= 0) of F with the vertical line x = cx; 0.0 when
    the line is clear. Points at/beyond the topmost crossing are outside F
    along that line — the conservative 'outermost exit' rule (holes in F are
    skipped, a noted spec refinement)."""
    top = F.bounds[3]
    if top <= 0.0:
        return 0.0
    hit = F.intersection(LineString([(cx, 0.0), (cx, top + 1.0)]))
    return 0.0 if hit.is_empty else max(0.0, hit.bounds[3])


def _v1_height(F, w0: float, sx: float) -> float | None:
    """Smallest safe row advance h1 for stagger sx: at/beyond the topmost
    F-crossing of every realized inter-row column x = j*sx + m*w0 (m in Z),
    for every row distance j while j*h1 is within F's y-extent. Constraints
    are one-sided (>= a column's top crossing), so growing h1 never invalidates
    an earlier j. The caps trade exhaustiveness for speed — the assembled
    band's exact overlap check is the backstop (spec § 4.5)."""
    fminx, _, fmaxx, fmaxy = F.bounds
    if (fmaxx - fminx) / w0 > 64:
        return None                           # degenerate: too many columns

    def columns(dx: float) -> list[float]:
        m_lo = math.floor((fminx - dx) / w0)
        m_hi = math.ceil((fmaxx - dx) / w0)
        return [dx + m * w0 for m in range(m_lo, m_hi + 1)]

    h1 = max((_top_crossing(F, cx) for cx in columns(sx)), default=0.0)
    if h1 < _MIN_PERIOD:
        return None
    j = 2
    while j * h1 < fmaxy + _EPS and j <= 64:
        req = max((_top_crossing(F, cx) for cx in columns(j * sx)), default=0.0)
        h1 = max(h1, req / j)
        j += 1
    return h1


def _band_plan(cell: _Cell, w0: float, sx: float, h1: float, copies: int,
               fabric_width_mm: float) -> tuple[int, int, float] | None:
    """(k, rows, band_length) for the best feasible column count, or None.
    Row j sits at x-offset (j*sx) % w0 (columns are w0-periodic), so k must fit
    at the WORST row offset. Feasibility is monotone in k (fewer rows -> offset
    set shrinks) and band length is non-increasing in k, so the largest
    feasible k wins (spec § 4.4)."""
    cells_needed = math.ceil(copies / len(cell.rotations))
    k_cap = int((fabric_width_mm - cell.x_extent + _EPS) // w0) + 1
    for k in range(min(k_cap, cells_needed), 0, -1):
        rows = math.ceil(cells_needed / k)
        max_off = max((j * sx) % w0 for j in range(rows))
        if max_off + (k - 1) * w0 + cell.x_extent <= fabric_width_mm + _EPS:
            return k, rows, (rows - 1) * h1 + cell.y_extent
    return None


def _assemble_band(group: list[Piece], cell: _Cell, w0: float, sx: float,
                   h1: float, k: int, fabric_width_mm: float,
                   ) -> tuple[list[Placement], float] | None:
    """Place the group's copies row-major (partial cell/row last) and run the
    exact backstop: pairwise area-overlap + width bounds. Returns band-local
    (placements, length) or None -> caller falls to the next ladder rung."""
    n_mem = len(cell.rotations)
    ordered = sorted(group, key=lambda p: p.id)
    placements: list[Placement] = []
    polys: list[ShapelyPolygon] = []
    for idx, piece in enumerate(ordered):
        cell_i, mem_i = divmod(idx, n_mem)
        row, col = divmod(cell_i, k)
        tx = (row * sx) % w0 + col * w0 + (cell.offsets[mem_i][0] - cell.bbox_min[0])
        ty = row * h1 + (cell.offsets[mem_i][1] - cell.bbox_min[1])
        rot = cell.rotations[mem_i]
        poly = shapely.affinity.translate(_raw_rotated(piece, rot), xoff=tx, yoff=ty)
        b = poly.bounds
        placements.append(Placement(piece.id, round(b[0], 4), round(b[1], 4), rot))
        polys.append(poly)
    for i in range(len(polys)):
        bi = polys[i].bounds
        if bi[0] < -0.5 or bi[2] > fabric_width_mm + 0.5:
            return None
        for j in range(i + 1, len(polys)):
            bj = polys[j].bounds
            if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                continue
            if _has_area_overlap(polys[i], polys[j]):
                return None
    min_y = min(p.bounds[1] for p in polys)
    max_y = max(p.bounds[3] for p in polys)
    shifted = [Placement(p.piece_id, p.x, round(p.y - min_y, 4), p.rotation_deg)
               for p in placements]
    return shifted, max_y - min_y


def _pair_offset_candidates(nfp: ShapelyPolygon) -> list[tuple[float, float]]:
    """d candidates on the RAW NFP boundary: vertices + per-edge midpoints +
    SEGMENT_MM densification, 1mm-deduped, stride-capped. Midpoints are
    load-bearing (a right triangle's perfect pair offset is an edge MIDPOINT);
    raw boundary only — simplifying can cut inside the NFP and create overlap
    far beyond the 0.5mm² tolerance (spec § 4.1)."""
    ring = list(nfp.exterior.coords)[:-1]
    mids = [((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])]
    dense = list(shapely.segmentize(nfp, SEGMENT_MM).exterior.coords)[:-1]
    cands, seen = [], set()
    for dx, dy in [*ring, *mids, *dense]:
        key = (round(dx), round(dy))               # 1mm dedup grid
        if key not in seen:
            seen.add(key)
            cands.append((dx, dy))
    stride = max(1, len(cands) // D_CANDIDATE_CAP)
    return cands[::stride]


def _build_lattice_band(group: list[Piece], fabric_width_mm: float, grain_mode: str,
                        fabric_grain_deg: float, cache: NfpCache) -> _Band | None:
    """Arm-A band: densest strip-aligned lattice of single / Kuperberg-pair
    cells, minimizing the group's exact finite-N band length (spec § 4).
    Single-cell menus come first: they are cheap, set the pruning baseline, and
    win ties (rectangle case)."""
    rep = group[0]
    rotset = _layout_rotations(grain_mode, fabric_grain_deg, rep.grainline_direction_deg)
    if len(rotset) == 1:
        menus = [[rotset[0]]]
    elif len(rotset) == 2:
        menus = [[rotset[0]], [rotset[0], rotset[1]]]
    else:  # no grainline data -> cardinals (spec § 4.1)
        menus = [[0.0], [90.0], [0.0, 180.0], [90.0, 270.0]]

    best: tuple[float, _Cell, float, float, float, int] | None = None
    for menu in menus:
        if len(menu) == 1:
            cells = [_make_cell(rep, [menu[0]], [(0.0, 0.0)])]
        else:
            cells = [
                _make_cell(rep, [menu[0], menu[1]], [(0.0, 0.0), d])
                for nfp in _get_or_compute_nfp(cache, rep, menu[0], rep, menu[1])
                for d in _pair_offset_candidates(nfp)
            ]
        cells.sort(key=lambda c: c.y_extent)
        for cell in cells:
            if best is not None and cell.y_extent >= best[0] - _EPS:
                break               # sorted ascending: no later cell can win
            if cell.x_extent > fabric_width_mm + _EPS:
                continue
            F = _forbidden_set(rep, cell, cache)
            if F.is_empty:
                continue
            w0 = _exit_along_x(F)
            if w0 < _MIN_PERIOD:
                continue
            for si in range(STAGGER_SAMPLES):
                sx = si * w0 / STAGGER_SAMPLES
                h1 = _v1_height(F, w0, sx)
                if h1 is None:
                    continue
                plan = _band_plan(cell, w0, sx, h1, len(group), fabric_width_mm)
                if plan is None:
                    continue
                k, _rows, band_len = plan
                if best is None or band_len < best[0] - _EPS:
                    best = (band_len, cell, w0, sx, h1, k)
    if best is None:
        return None
    _band_len, cell, w0, sx, h1, k = best
    assembled = _assemble_band(group, cell, w0, sx, h1, k, fabric_width_mm)
    if assembled is None:
        return None
    placements, length = assembled
    return _Band(placements, length, rep.area)


def lattice_layout(pieces: list[Piece], fabric_width_mm: float, grain_mode: str,
                   fabric_grain_deg: float,
                   ladder_log: list[tuple[str, str]] | None = None,
                   ) -> tuple[list[Placement], float, float]:
    """Arm A: per-shape-group Kuperberg-pair lattice bands with per-group BLF
    fallback, stacked + settled. Deterministic."""
    return _layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
                   [("lattice", _build_lattice_band), ("blf", _build_blf_band)],
                   ladder_log)
```

- [ ] **Step 4: Run the lattice tests**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_lattice.py -v
```
Expected: ALL tests (Task 2 + Task 3) PASS. Debug notes for the two math-heavy tests:
- `test_triangle_pair_beats_single_by_20pct`: expected values ≈ pair 400mm vs single 800mm (the pair's perfect 300×200 rectangle comes from d = the NFP hypotenuse **midpoint** (300, 200); the single-cell reference is the 300×200 grid because `w0` is pinned to 300 by the +x-axis exit). If pair > 640, check `_pair_offset_candidates` includes midpoints and `_v1_height` returns 200 for the pair cell at sx=0.
- `test_rect_pair_no_gain_over_single`: both ≈ 800mm; pair candidates d=(0,200)/(300,0) reduce to the same grid, and the single menu wins the tie (evaluated first, strict `<` keeps it).

- [ ] **Step 5: Full engine suite still green**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: green (no production module changed).

- [ ] **Step 6: Commit**

```powershell
cd WT
git add engine/core/layout/lattice.py engine/tests/unit/test_lattice.py
git commit -m "feat(engine): Kuperberg-pair lattice warm-start generator (NFP lattice vectors)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Spike runner + smoke

**Files:**
- Create: `WT\engine\tests\spike_lattice_warmstart.py` (throwaway; deleted in Task 9)
- Modify: none besides the spike file — the repo's blanket `tools/` gitignore line already ignores `tools/lattice-spike/` (an earlier draft wrongly assumed an explicit `tools/sparrow-rebuild/` line existed)

**Interfaces:**
- Consumes: `lattice_layout` / `banded_blf_layout` (Tasks 2–3); production helpers `_group_to_items`, `_instance_json`, `_placements_to_jagua`, `_reconstruct`, `_validate_layout`, `_resolve_sparrow_path`, `auto_layout_polygon`, `_compute_metrics`, `_polygon_dims`.
- Produces: `tools/lattice-spike/reports/<workload>_x<copies>/report.json` with schema `{"meta": {..., "seeds_meta": {arm: {seed_marker_mm, seed_util_pct, prelude_s, ladder_rungs?}}}, "runs": [{"arm", "seed", "marker_mm", "util_pct", "wall_s", "valid", "error?", "snapshots", "log_lines"}]}` + `report.md`; subcommands `smoke` / `run` / `evaluate` (consumed by Tasks 5–7). Exit codes: 0 all-valid, 1 some-invalid, 2 TTL.

- [ ] **Step 1: Write the spike script**

```python
"""Lattice warm-start A/B — THROWAWAY spike (delete after the §6 entry lands).

Protocol + gates: docs/superpowers/specs/2026-07-04-lattice-warmstart-design.md.
Arms share the vendored exe and differ ONLY by the -i instance's embedded
warm-start solution:
  control = Fast NFP-BLF seed (production warm start)
  lattice = core.layout.lattice.lattice_layout seed
  banded  = core.layout.lattice.banded_blf_layout seed

  ...python.exe engine\\tests\\spike_lattice_warmstart.py smoke
  ...python.exe engine\\tests\\spike_lattice_warmstart.py run --workload sample_2.dxf --copies 10 \
        --budget 600 --seeds 42,43,44 --arms control,lattice,banded [--ttl-hours 3]
  ...python.exe engine\\tests\\spike_lattice_warmstart.py evaluate --report <r1.json> \
        [--report2 <r2.json> --winner lattice]

Resume: re-running `run` keeps valid (arm, seed) rows from an existing report
and re-runs missing/invalid ones. Report JSON+MD rewritten ATOMICALLY after
every run (kill-safe). Exit codes: 0 all-valid, 1 some invalid, 2 TTL hit.
"""
from __future__ import annotations
import argparse, glob, json, math, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from dataclasses import replace
from core.dxf import parse_dxf
from core.geometry import normalize_piece
from core.layout.heuristic import auto_layout_polygon, _compute_metrics, _polygon_dims
from core.layout.lattice import banded_blf_layout, lattice_layout
from core.layout.separation import (_group_to_items, _instance_json, _placements_to_jagua,
                                    _reconstruct, _resolve_sparrow_path, _validate_layout)

FABRIC, GRAIN_MODE, GRAIN_DEG = 1651.0, "bi", 90.0
COMMERCIAL_MM = 10599.0
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
REPORTS = os.path.join(REPO, "tools", "lattice-spike", "reports")
ARMS = ("control", "lattice", "banded")


def _find_fixture(sample: str) -> str:
    p = os.path.join(REPO, "examples", "input", sample)
    if not os.path.isfile(p):
        raise SystemExit(f"fixture missing: {p} (copy it into the worktree)")
    return p


def _load(sample: str, copies: int):
    with open(_find_fixture(sample), "rb") as f:
        raw = parse_dxf(f.read())
    base = []
    for i, r in enumerate(raw):
        try:
            base.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    return [replace(b, id=f"{b.id}__c{c}") for c in range(copies) for b in base]


def _seed_layout(arm: str, pieces):
    """Build the arm's seed layout in the engine frame."""
    t0 = time.perf_counter()
    if arm == "control":
        placements, marker, util = auto_layout_polygon(
            pieces, FABRIC, GRAIN_MODE, GRAIN_DEG, effort=1)
        extra = {}
    else:
        fn = lattice_layout if arm == "lattice" else banded_blf_layout
        ladder: list[tuple[str, str]] = []
        placements, marker, util = fn(pieces, FABRIC, GRAIN_MODE, GRAIN_DEG,
                                      ladder_log=ladder)
        rungs: dict[str, int] = {}
        for _, rung in ladder:
            rungs[rung] = rungs.get(rung, 0) + 1
        extra = {"ladder_rungs": rungs}
    extra["prelude_s"] = round(time.perf_counter() - t0, 1)
    return placements, marker, util, extra


def _prepare_instances(pieces, arms, out_dir):
    """Shared jagua instance built once; one merged warm-start instance file per
    arm. G1 applies to seeds: every seed layout must pass the validator — abort
    loudly otherwise (the protocol needs all arms)."""
    items = _group_to_items(pieces, GRAIN_MODE, GRAIN_DEG)
    inst = _instance_json(items, FABRIC)
    paths, seeds_meta = {}, {}
    for arm in arms:
        try:
            placements, marker, util, extra = _seed_layout(arm, pieces)
            _validate_layout(placements, pieces, FABRIC, GRAIN_MODE, GRAIN_DEG)
            placed_items = _placements_to_jagua(items, pieces, placements, marker)
        except Exception as e:
            raise SystemExit(f"seed[{arm}] failed G1: {e}")
        sol = {"strip_width": float(marker) + 1.0,
               "layout": {"container_id": 0, "placed_items": placed_items, "density": 0.0},
               "density": 0.0, "run_time_sec": 0}
        ipath = os.path.join(out_dir, f"instance_{arm}.json")
        with open(ipath, "w", encoding="utf-8") as f:
            json.dump({**inst, "solution": sol}, f)
        paths[arm] = ipath
        seeds_meta[arm] = {"seed_marker_mm": round(marker, 1),
                           "seed_util_pct": round(util, 2), **extra}
        print(f"seed[{arm}]: marker={marker:.1f}mm util={util:.2f}% "
              f"prelude={extra['prelude_s']}s {extra.get('ladder_rungs', '')}", flush=True)
    return items, paths, seeds_meta


def _run_one(exe: str, ipath: str, budget_s: int, seed: int, workdir: str) -> dict:
    """Mirror of production _run_sparrow with a persistent workdir keeping
    output/log.txt (the real log — stderr is empty) + sols_ SVG snapshots."""
    os.makedirs(workdir, exist_ok=True)
    t0 = time.perf_counter()
    with open(os.path.join(workdir, "sparrow.stderr.log"), "wb") as logf:
        proc = subprocess.Popen([exe, "-i", ipath, "-t", str(int(budget_s)), "-s", str(int(seed))],
                                cwd=workdir, stdout=subprocess.DEVNULL, stderr=logf)
        proc.wait()
    wall = time.perf_counter() - t0
    if proc.returncode != 0:
        raise ValueError(f"sparrow exited {proc.returncode} (see {workdir})")
    outdir = os.path.join(workdir, "output")
    finals = [x for x in os.listdir(outdir) if x.startswith("final_") and x.endswith(".json")] \
        if os.path.isdir(outdir) else []
    if not finals:
        raise ValueError(f"no final_*.json in {outdir}")
    with open(os.path.join(outdir, finals[0]), encoding="utf-8") as f:
        solution = json.load(f)
    logtxt = os.path.join(outdir, "log.txt")
    log_lines = sum(1 for _ in open(logtxt, "rb")) if os.path.isfile(logtxt) else 0
    snapshots = len(glob.glob(os.path.join(outdir, "sols_*", "*.svg")))
    return {"solution": solution, "wall_s": round(wall, 1),
            "snapshots": snapshots, "log_lines": log_lines}


def _write_report(out_dir: str, meta: dict, runs: list[dict]) -> None:
    tmp = os.path.join(out_dir, "report.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "runs": runs}, f, indent=1)
    os.replace(tmp, os.path.join(out_dir, "report.json"))
    lines = [f"# lattice warm-start A/B — {meta['workload']} ×{meta['copies']} @{meta['budget_s']}s",
             "", "seed layouts (pre-sparrow):", ""]
    for arm, sm in meta.get("seeds_meta", {}).items():
        lines.append(f"- {arm}: {sm['seed_marker_mm']}mm / {sm['seed_util_pct']}% "
                     f"(prelude {sm['prelude_s']}s, rungs {sm.get('ladder_rungs', {})})")
    lines += ["", "| arm | seed | marker (mm) | util | wall (s) | valid | snaps | log lines |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in runs:
        lines.append(f"| {r['arm']} | {r['seed']} | {r.get('marker_mm', '—')} | "
                     f"{r.get('util_pct', '—')} | {r.get('wall_s', '—')} | {r['valid']} | "
                     f"{r.get('snapshots', '—')} | {r.get('log_lines', '—')} |")
    tmp2 = os.path.join(out_dir, "report.md.tmp")
    with open(tmp2, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp2, os.path.join(out_dir, "report.md"))


def cmd_run(args) -> int:
    arms = [a for a in args.arms.split(",") if a]
    for a in arms:
        if a not in ARMS:
            raise SystemExit(f"unknown arm {a!r} (choose from {ARMS})")
    seeds = [int(s) for s in args.seeds.split(",")]
    deadline = time.monotonic() + args.ttl_hours * 3600.0
    out_dir = os.path.join(REPORTS, f"{args.workload.replace('.dxf', '')}_x{args.copies}")
    os.makedirs(out_dir, exist_ok=True)

    pieces = _load(args.workload, args.copies)
    items, ipaths, seeds_meta = _prepare_instances(pieces, arms, out_dir)
    exe = _resolve_sparrow_path()

    done: dict[tuple[str, int], dict] = {}
    rpath = os.path.join(out_dir, "report.json")
    if os.path.isfile(rpath):                    # resume: keep valid rows only
        with open(rpath, encoding="utf-8") as f:
            old = json.load(f)
        done = {(r["arm"], r["seed"]): r for r in old.get("runs", []) if r.get("valid")}
        if done:
            print(f"resume: keeping {len(done)} valid rows", flush=True)

    meta = {"workload": args.workload, "copies": args.copies, "budget_s": args.budget,
            "fabric": FABRIC, "grain": [GRAIN_MODE, GRAIN_DEG], "seeds": seeds,
            "arms": arms, "exe": exe, "seeds_meta": seeds_meta,
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    runs: list[dict] = list(done.values())
    _write_report(out_dir, meta, runs)
    ttl_hit = False
    for seed in seeds:                # seed-major: arms interleave within each seed
        for arm in arms:              # so box drift hits all arms of a pair equally
            if (arm, seed) in done:
                continue
            if time.monotonic() > deadline:
                print("TTL expired — report is complete up to here", flush=True)
                ttl_hit = True
                break
            workdir = os.path.join(out_dir, "runs", f"{arm}_s{seed}")
            row = {"arm": arm, "seed": seed, "valid": False, "workdir": workdir}
            print(f"[{time.strftime('%H:%M:%S')}] {arm} seed={seed} …", flush=True)
            try:
                r = _run_one(exe, ipaths[arm], args.budget, seed, workdir)
                placements = _reconstruct(r["solution"], items, FABRIC)
                _validate_layout(placements, pieces, FABRIC, GRAIN_MODE, GRAIN_DEG)
                marker, util = _compute_metrics(placements, pieces, FABRIC, _polygon_dims)
                row.update(valid=True, marker_mm=round(marker, 1), util_pct=round(util, 2),
                           wall_s=r["wall_s"], snapshots=r["snapshots"],
                           log_lines=r["log_lines"])
                print(f"    marker={marker:.1f}mm util={util:.2f}% wall={r['wall_s']}s",
                      flush=True)
            except (ValueError, KeyError) as e:
                row["error"] = str(e)[:300]
                print(f"    INVALID/FAILED: {row['error']}", flush=True)
            runs.append(row)
            _write_report(out_dir, meta, runs)   # kill-safe: rewrite after EVERY run
        if ttl_hit:
            break
    _write_report(out_dir, meta, runs)
    if ttl_hit:
        return 2
    invalid = [(r["arm"], r["seed"]) for r in runs if not r["valid"]]
    if invalid:
        print(f"INVALID RUNS: {invalid}", flush=True)
        return 1
    print(f"done -> {rpath}", flush=True)
    return 0


def _markers(report: dict, arm: str) -> dict[int, float]:
    return {r["seed"]: r["marker_mm"] for r in report["runs"]
            if r["arm"] == arm and r["valid"]}


def _paired(report: dict, a: str, b: str):
    """(mean of a-b over shared seeds, wins for a, shared seed list)."""
    ma, mb = _markers(report, a), _markers(report, b)
    shared = sorted(set(ma) & set(mb))
    deltas = [ma[s] - mb[s] for s in shared]
    wins = sum(1 for d in deltas if d < 0)
    mean = sum(deltas) / len(deltas) if deltas else float("nan")
    return mean, wins, shared


def _gate_g2(report: dict, arm: str, n_seeds: int) -> str:
    """Spec §7 G2: GO = mean <= -25 AND wins >= 2/3 of seeds; NO-GO = mean > 0
    or wins <= 1/3; otherwise borderline -> extend seeds."""
    ms = _markers(report, arm)
    mean, wins, shared = _paired(report, arm, "control")
    n = len(shared)
    print(f"  {arm}: per-seed " + ", ".join(f"s{s}={ms[s]:.1f}" for s in shared))
    if n < n_seeds:
        print(f"  {arm}: only {n}/{n_seeds} shared valid seeds")
        return "INCOMPLETE"
    decisive = all(v < COMMERCIAL_MM for v in ms.values())
    print(f"  {arm}: paired mean {mean:+.1f}mm vs control, wins {wins}/{n}"
          + (" — DECISIVE (all seeds < 10599)" if decisive else ""))
    if mean <= -25.0 and wins >= math.ceil(2 * n / 3):
        return "GO"
    if mean > 0.0 or wins <= n // 3:
        return "NO-GO"
    return "BORDERLINE (extend all arms to seeds 45,46 and re-evaluate)"


def cmd_evaluate(args) -> int:
    with open(args.report, encoding="utf-8") as f:
        rep = json.load(f)
    n = len(rep["meta"]["seeds"])
    print(f"gates ({rep['meta']['workload']} ×{rep['meta']['copies']} "
          f"@{rep['meta']['budget_s']}s):")
    print("seed layouts (pre-sparrow):")
    for arm, sm in rep["meta"].get("seeds_meta", {}).items():
        print(f"  {arm}: {sm['seed_marker_mm']}mm ({sm['seed_util_pct']}%)")
    for arm in ("lattice", "banded"):
        if _markers(rep, arm):
            print(f"  G2[{arm}] -> {_gate_g2(rep, arm, n)}")
    if args.report2:
        with open(args.report2, encoding="utf-8") as f:
            rep2 = json.load(f)
        mean, _wins, shared = _paired(rep2, args.winner, "control")
        if not shared:
            print(f"G3[{args.winner}]: no shared valid seeds -> INCOMPLETE")
        else:
            verdict = "PASS" if mean <= 40.0 else \
                "FAIL (regression >40mm -> productize as per-workload seed pick)"
            print(f"G3[{args.winner}] ({rep2['meta']['workload']} "
                  f"×{rep2['meta']['copies']}): paired mean {mean:+.1f}mm "
                  f"over seeds {shared} -> {verdict}")
    return 0


def cmd_smoke(args) -> int:
    """15s × 1-copy sanity of all three arms (seed builds + converter round-trip
    + validator on seeds and finals)."""
    args.workload, args.copies, args.budget = "sample_2.dxf", 1, 15
    args.seeds, args.arms, args.ttl_hours = "42", "control,lattice,banded", 1.0
    rc = cmd_run(args)
    print("SMOKE PASS" if rc == 0 else f"SMOKE FAIL: rc={rc}")
    return 0 if rc == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--workload", default="sample_2.dxf")
    p_run.add_argument("--copies", type=int, default=10)
    p_run.add_argument("--budget", type=int, default=600)
    p_run.add_argument("--seeds", default="42,43,44")
    p_run.add_argument("--arms", default="control,lattice,banded")
    p_run.add_argument("--ttl-hours", type=float, default=3.0)
    p_ev = sub.add_parser("evaluate")
    p_ev.add_argument("--report", required=True)
    p_ev.add_argument("--report2")
    p_ev.add_argument("--winner", default="lattice")
    sub.add_parser("smoke")
    args = ap.parse_args()
    return {"run": cmd_run, "evaluate": cmd_evaluate, "smoke": cmd_smoke}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify spike outputs are ignored** — no .gitignore edit needed: the existing blanket `tools/` line covers `tools/lattice-spike/`. Confirm: `git check-ignore tools/lattice-spike/x` exits 0.

- [ ] **Step 3: Smoke run (3 arms × 15s × 1 copy, ~1min + preludes)**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_lattice_warmstart.py smoke
```
Expected: three `seed[...]: marker=…` lines (lattice line includes `ladder_rungs`), three `marker=… util=… wall=…` run lines, then `SMOKE PASS`, exit 0. Report under `WT\tools\lattice-spike\reports\sample_2_x1\`. Sanity-check `report.json`: `meta.seeds_meta` has all three arms; every run `valid: true`.

- [ ] **Step 4: Commit**

```powershell
cd WT
git add engine/tests/spike_lattice_warmstart.py
git commit -m "test(engine): throwaway spike runner for the lattice warm-start A/B

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Canonical matrix — 3 arms × seeds 42/43/44 @600s (~1h40m)

**Files:** none (produces `WT\tools\lattice-spike\reports\sample_2_x10\report.{json,md}` — gitignored).

**Interfaces:**
- Consumes: Task 4's `run` subcommand.
- Produces: the workload-1 report consumed by Task 6.

- [ ] **Step 1: Preflight — quiet box**

Confirm with the user that the box is quiet (no other benches/builds — sparrow's `-t` is wall-clock; concurrent load corrupts the A/B). Runs are strictly sequential by construction.

- [ ] **Step 2: Launch the matrix in the background**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_lattice_warmstart.py run --workload sample_2.dxf --copies 10 --budget 600 --seeds 42,43,44 --arms control,lattice,banded --ttl-hours 3
```
Run in the background (~95min + preludes). First lines to check immediately: the three `seed[...]` lines. **Record the seed markers** — `lattice`'s seed vs control's ~11393.2mm is the Milenkovic-premise telemetry, and the lattice `ladder_rungs` shows how many of the 13 groups actually latticed. If the lattice prelude exceeds ~90s, note it in the report conversation and (only if it exceeds ~5min) lower `STAGGER_SAMPLES` to 4 in `lattice.py` and restart — resume keeps nothing yet, so this is cheap only before runs start.

- [ ] **Step 3: On completion, verify the report**

```powershell
Get-Content WT\tools\lattice-spike\reports\sample_2_x10\report.md
```
Expected: 9 rows, all `valid: True`, exit code 0. If exit 1 (some invalid): inspect the `error` fields, fix the cause, re-run the same command — resume re-runs only the invalid pairs. If exit 2 (TTL): re-run the same command to finish the remaining pairs.

---

### Task 6: Gate evaluation + verdict  **[USER CHECKPOINT]**

**Files:** none.

**Interfaces:**
- Consumes: Task 5's report; Task 4's `evaluate`.
- Produces: the G2 verdicts (per arm) + DECISIVE flag that select Task 7 or Task 8.

- [ ] **Step 1: Evaluate**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_lattice_warmstart.py evaluate --report tools\lattice-spike\reports\sample_2_x10\report.json
```
Expected output: seed-layout telemetry + per-arm per-seed markers, paired means, wins, and one of GO / NO-GO / BORDERLINE per arm, with the DECISIVE flag when all seeds < 10599.

- [ ] **Step 2: If any arm is BORDERLINE — extend seeds first**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_lattice_warmstart.py run --workload sample_2.dxf --copies 10 --budget 600 --seeds 42,43,44,45,46 --arms control,lattice,banded --ttl-hours 4
```
(Resume skips the 9 completed pairs; this adds 6 runs ≈ 1h5m.) Then re-run Step 1; with n=5 the gate needs wins ≥ 4 (⌈2·5/3⌉) for GO.

- [ ] **Step 3: Present the verdict to the user — STOP and wait**

Present: the full per-seed table, paired means vs control for both arms, seed-layout markers (did the lattice seed beat 11393.2mm?), ladder-rung counts, DECISIVE status, and the interpretation rule from the spec (lattice ≈ banded ⇒ banding is the mechanism, ship the cheap one; lattice > banded ⇒ density matters). The user chooses the path:
- any treatment arm **GO** → Task 7 (G3 guard), then Task 9 with the GO docs.
- all arms **NO-GO** → Task 8, then Task 9 with the NO-GO docs.

---

### Task 7: G3 regression guard on sample_4 ×6  **[conditional: GO verdict]**

**Files:** none (produces `WT\tools\lattice-spike\reports\sample_4_x6\report.{json,md}`).

**Interfaces:**
- Consumes: Task 4's `run`/`evaluate`; the winning arm name from Task 6 (`lattice` or `banded`).
- Produces: G3 PASS/FAIL, which shapes the productization note in Task 9's docs.

- [ ] **Step 1: Run the guard (2 × 600s ≈ 21min; substitute the actual winner for `lattice` if it was `banded`)**

```powershell
cd WT
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_lattice_warmstart.py run --workload sample_4.dxf --copies 6 --budget 600 --seeds 42 --arms control,lattice --ttl-hours 1
```
Expected: 2 valid rows. (sample_4 is where the Fast-BLF seed measured neutral; the lattice ladder may report more `blf` rungs there — that's informative, not a failure.)

- [ ] **Step 2: Evaluate both reports together**

```powershell
D:\openmarker\engine\.venv\Scripts\python.exe engine\tests\spike_lattice_warmstart.py evaluate --report tools\lattice-spike\reports\sample_2_x10\report.json --report2 tools\lattice-spike\reports\sample_4_x6\report.json --winner lattice
```
Expected: `G3[...] -> PASS` (winner not worse than control by >40mm) or `FAIL (...)`. G3 FAIL does NOT kill the GO — it means Task 9's docs must state productization as "build both seeds, pick the better pre-sparrow" instead of unconditional default.

---

### Task 8: NO-GO cleanup  **[conditional: NO-GO verdict]**

**Files:**
- Delete: `WT\engine\core\layout\lattice.py`, `WT\engine\tests\unit\test_lattice.py`, `WT\engine\tests\spike_lattice_warmstart.py`

**Interfaces:**
- Consumes: the NO-GO decision from Task 6.
- Produces: a docs-only branch (this plan file preserves all three files' code verbatim above).

- [ ] **Step 1: Delete the spike code**

```powershell
cd WT
git rm engine/core/layout/lattice.py engine/tests/unit/test_lattice.py engine/tests/spike_lattice_warmstart.py
```

- [ ] **Step 2: Full suite green again**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: back to the baseline count, green.

- [ ] **Step 3: Commit**

```powershell
cd WT
git commit -m "chore(engine): remove lattice warm-start spike after NO-GO (code preserved in the plan doc)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Rescue the reports before any worktree removal**

```powershell
New-Item -ItemType Directory -Force D:\openmarker\tools\lattice-spike\reports
Copy-Item WT\tools\lattice-spike\reports\* D:\openmarker\tools\lattice-spike\reports\ -Recurse -Force
```
(Same on the GO path if the worktree is removed later — the reports are the protocol record's evidence.)

---

### Task 9: Docs + BACKLOG + PR

**Files:**
- Modify: `WT\docs\planning\PERFORMANCE.md` (§ 6 new entry + § 5.B row status), `WT\docs\planning\BACKLOG.md` (checklist ticks + outcome line)

**Interfaces:**
- Consumes: the verdict + all measured numbers from `report.json` files (Tasks 5–7).
- Produces: the merged protocol record; PR on `feat/lattice-warmstart`.

- [ ] **Step 1: PERFORMANCE.md § 6 entry** (append a new dated section at the end of § 6; fill every `<...>` from the reports — never leave one unfilled):

```markdown
### <YYYY-MM-DD> — Periodic-lattice warm-start A/B (lattice + banded vs Fast-BLF seed): <VERDICT>

- **What / why:** Spiked the § 5.B periodic-lattice lever: `lattice.py`
  generators (Kuperberg 180° pair cells, NFP-derived strip-aligned lattice
  vectors, per-shape-group bands + settle; plus a banded-BLF ablation) seeded
  sparrow via the production `-i` converter, vs the production Fast-BLF seed.
  Canonical protocol: sample_2×10 @600s, matched seeds <seeds>, sequential,
  validator-gated seeds AND finals.
- **Seed layouts (pre-sparrow):** control <mm>mm / lattice <mm>mm (ladder:
  <n> lattice / <n> blf rungs of 13 groups) / banded <mm>mm — vs Fast-BLF
  reference 11393.2mm.
- **Result (final markers, mm):**

| arm | s42 | s43 | s44 | paired mean vs control | wins |
| --- | --- | --- | --- | --- | --- |
| control | <mm> | <mm> | <mm> | — | — |
| lattice | <mm> | <mm> | <mm> | <+/-mm> | <n>/3 |
| banded | <mm> | <mm> | <mm> | <+/-mm> | <n>/3 |

- **Gates:** G1 <all valid?>; G2[lattice] <GO/NO-GO/BORDERLINE→extended>,
  G2[banded] <...>; DECISIVE (<10599 on all seeds): <yes/no>; G3 (sample_4×6,
  GO only): <PASS/FAIL/not run>.
- **Interpretation:** <lattice vs banded delta ⇒ density vs banding mechanism;
  seed-structure→outcome relationship observed>.
- **Decision:** <shipped lattice.py as engine module, productization follow-up
  filed / docs-only protocol record, code preserved in the plan doc>. Reports
  under `tools/lattice-spike/reports/` (gitignored, local-only).
```

- [ ] **Step 2: PERFORMANCE.md § 5.B row** — in the "Periodic-lattice warm-start generator" row, replace `**ADOPTED 2026-07-04 (§ 6) — queued after the rebuild A/B.**` with `**<GO/NO-GO> <YYYY-MM-DD> (§ 6 [lattice A/B]).**` and set the "Estimated gain" cell to the measured paired means (e.g. `MEASURED: lattice <±mm>, banded <±mm> vs warm control @600s`).

- [ ] **Step 3: BACKLOG.md** — tick the executed checklist items (leave the skipped conditional as `[ ]` with `(skipped — <verdict>)` appended) and add one outcome line under the checklist:

```markdown
- Outcome: <VERDICT> — lattice <±mm>, banded <±mm> paired vs warm control
  @600s on sample_2×10 (seeds <seeds>); seed layouts lattice <mm> / banded
  <mm> vs Fast-BLF 11393.2; DECISIVE: <yes/no>. See PERFORMANCE.md § 6.
```

On **GO** also append the productization follow-up (out of this spike's scope by spec §10):

```markdown
- [ ] Follow-up (GO): wire the winning generator into `run_separation_layout`
  (seed-source selection<, per-workload pick-better-seed if G3 FAILED>;
  composition with best-of-N) — separate spec/plan/PR.
```

- [ ] **Step 4: Commit docs**

```powershell
cd WT
git add docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git commit -m "docs(perf): lattice warm-start A/B protocol record (<VERDICT>)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Push + PR**

```powershell
cd WT
git push -u origin feat/lattice-warmstart
gh pr create --title "<VERDICT-appropriate title, e.g. 'Lattice warm-start generator: <one-line result>'>" --body "<summary of arms, per-seed table, gates, decision.

MERGE NOTE: the main tree carries an UNCOMMITTED .gitignore edit that removes the '!engine/vendor/sparrow/sparrow.exe' negation — that negation is load-bearing for the committed vendored binary. Do not let a merge/rebase drop it.

🤖 Generated with [Claude Code](https://claude.com/claude-code)>"
```

- [ ] **Step 6: Hand back for the final whole-branch review** (process-level: the executing skill dispatches it) and stop — merge is the user's call at the PR.

---

## Verdict paths (summary)

- **GO:** Tasks 1–7 + 9. `lattice.py` + tests merge (unreferenced by production); spike script deleted in Task 9 before the docs commit (`git rm engine/tests/spike_lattice_warmstart.py`, code preserved in this plan); follow-up PR for `run_separation_layout` wiring is filed in BACKLOG, not built here.
- **NO-GO:** Tasks 1–6 + 8 + 9. Docs-only merge; all spike code deleted, preserved in this plan.
- **BORDERLINE:** resolved inside Task 6 (extend to seeds 45/46) before choosing a path.
