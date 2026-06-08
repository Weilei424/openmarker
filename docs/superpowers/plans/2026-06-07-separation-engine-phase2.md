# Separation Engine — Phase 2 (Ultra tier) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a GUI "Ultra" quality tier that runs the bundled Rust nester `sparrow` as an offline subprocess, producing a valid grain-respecting marker that beats GA by ≥3%.

**Architecture:** New engine module `core/layout/separation.py` converts pieces → grain-aligned + 90°-axis-mapped `jagua-rs` JSON, shells out to a vendored `sparrow.exe`, then reconstructs + validates the result into engine `Placement`s (same return tuple as `auto_layout_polygon`). `POST /auto-layout` routes `quality="ultra"` to it; `/cancel-layout` kills the child; `QualityPanel` gains an Ultra radio. The binary is committed under `engine/vendor/sparrow/` and located by a resolver ladder.

**Tech Stack:** Python 3.11 · Shapely · subprocess · FastAPI · React/TypeScript/Vitest · Rust (one-time `cargo build` to produce the vendored binary).

**Spec:** `docs/superpowers/specs/2026-06-07-separation-engine-phase2-design.md`. Schema/axis-map: `docs/superpowers/notes/2026-06-07-jagua-schema.md`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `engine/core/layout/separation.py` | Convert → run sparrow → reconstruct → validate; cancellation registry | Create |
| `engine/tests/unit/test_separation.py` | Unit tests (grouping, emit, reconstruct, validate, resolver) | Create |
| `engine/tests/integration/test_separation_sidecar.py` | Real-binary integration + cancellation (skips if absent) | Create |
| `engine/vendor/sparrow/sparrow.exe` | Committed offline sidecar binary | Create (built) |
| `engine/vendor/sparrow/PROVENANCE.md` | Build provenance + licenses | Create |
| `.gitignore` | Negate `*.exe` for the vendored binary | Modify |
| `engine/api/main.py` | Route `quality="ultra"`; `/cancel-layout` kill | Modify |
| `engine/tests/integration/test_api.py` | Ultra routing + validation-failure 400 | Modify |
| `frontend/src/types/engine.ts` | `LayoutQuality += "ultra"` | Modify |
| `frontend/src/components/sidebar/QualityPanel.tsx` | Ultra radio | Modify |
| `frontend/src/components/sidebar/QualityPanel.test.tsx` | Ultra tests | Modify |
| `frontend/src/app/App.tsx` | Effort-disable comment only (logic already covers ultra) | Modify |
| `engine/tests/bench_separation.py` | Production-module bench + time-curve | Create |
| `docs/planning/PERFORMANCE.md` | §6 result entry | Modify |
| `docs/planning/BACKLOG.md` | Phase-2 checklist | Modify |

---

## Task 1: Worktree environment + fixtures

**Files:** none committed (env only). Fixtures are gitignored.

- [ ] **Step 1: Copy DXF fixtures into the worktree** (gitignored; absent in a fresh worktree)

Run (PowerShell, from worktree root `D:\openmarker\.worktrees\separation-phase2`):
```powershell
New-Item -ItemType Directory -Force examples\input | Out-Null
Copy-Item D:\openmarker\examples\input\*.dxf -Destination examples\input\
Get-ChildItem examples\input\sample_2.dxf
```
Expected: `sample_2.dxf` listed.

- [ ] **Step 2: Create the engine venv and install deps**

Run (from `engine/`):
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
```
Expected: install completes (shapely, pyclipper, ezdxf, fastapi, uvicorn, pytest, …).

- [ ] **Step 3: Verify a clean baseline**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit -q`
Expected: all unit tests PASS (this branch == green `main`). If any fail, STOP and report.

- [ ] **Step 4: No commit** — environment only.

---

## Task 2: `_resolve_sparrow_path` (binary resolver)

**Files:**
- Create: `engine/core/layout/separation.py`
- Test: `engine/tests/unit/test_separation.py`

- [ ] **Step 1: Write the failing test**

Create `engine/tests/unit/test_separation.py`:
```python
import os
import pytest
from core.models.piece import Piece, BoundingBox
from core.layout.separation import _resolve_sparrow_path


def _rect(piece_id: str, w: float, h: float, grainline: float | None = None) -> Piece:
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        grainline_direction_deg=grainline,
    )


# --- _resolve_sparrow_path ---

def test_resolve_prefers_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "sparrow.exe"
    fake.write_bytes(b"\x00")
    monkeypatch.setenv("OPENMARKER_SPARROW_PATH", str(fake))
    assert _resolve_sparrow_path() == str(fake)


def test_resolve_missing_raises(monkeypatch):
    monkeypatch.delenv("OPENMARKER_SPARROW_PATH", raising=False)
    monkeypatch.setattr(os.path, "isfile", lambda p: False)
    with pytest.raises(FileNotFoundError):
        _resolve_sparrow_path()
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit\test_separation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.layout.separation'`.

- [ ] **Step 3: Write minimal implementation**

Create `engine/core/layout/separation.py`:
```python
"""Separation nesting engine — the "Ultra" quality tier.

Converts pieces to grain-aligned jagua-rs JSON, shells out to the bundled
`sparrow` binary (overlap-and-separate strip nester), then reconstructs and
validates the result into engine Placements. See
docs/superpowers/specs/2026-06-07-separation-engine-phase2-design.md and
docs/superpowers/notes/2026-06-07-jagua-schema.md (axis map).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass

import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon

from core.models.piece import Piece
from core.layout.cancellation import CancellationError, is_cancelled
from core.layout.clustering import group_pieces_by_base_id
from core.layout.heuristic import (
    EDGE_GAP,
    Placement,
    _compute_metrics,
    _has_area_overlap,
    _layout_rotations,
    _placed_polygon,
    _polygon_dims,
)

_VENDORED = os.path.join(os.path.dirname(__file__), "..", "..", "vendor", "sparrow", "sparrow.exe")


def _resolve_sparrow_path() -> str:
    """Locate the bundled sparrow binary. Search order:
    1. OPENMARKER_SPARROW_PATH env override
    2. vendored engine/vendor/sparrow/sparrow.exe (committed, offline)
    3. PyInstaller bundle dir (sys._MEIPASS — future packaging)
    4. dev build tools/sparrow/target/release/sparrow.exe (walk up to repo root)
    """
    candidates: list[str] = []
    env = os.environ.get("OPENMARKER_SPARROW_PATH")
    if env:
        candidates.append(env)
    candidates.append(os.path.abspath(_VENDORED))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "vendor", "sparrow", "sparrow.exe"))
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidates.append(os.path.join(here, "tools", "sparrow", "target", "release", "sparrow.exe"))
        here = os.path.dirname(here)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "sparrow binary not found. Set OPENMARKER_SPARROW_PATH, or vendor it at "
        "engine/vendor/sparrow/sparrow.exe (see the Phase 2 spec §10)."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit\test_separation.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/separation.py engine/tests/unit/test_separation.py
git commit -m "feat(separation): sparrow binary resolver ladder

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `_group_to_items` + emit transform + instance JSON

**Files:**
- Modify: `engine/core/layout/separation.py`
- Test: `engine/tests/unit/test_separation.py`

- [ ] **Step 1: Write the failing tests** (append to `test_separation.py`)

```python
from core.layout.separation import _group_to_items, _instance_json, EDGE_GAP


# --- _group_to_items: grouping + demand ---

def test_group_demand_and_piece_ids():
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0),
              _rect("piece_1__c0", 50, 30, 90.0)]
    items = _group_to_items(pieces, "bi", 90.0)
    assert [it.index for it in items] == [0, 1]
    assert items[0].piece_ids == ["piece_0__c0", "piece_0__c1"]
    assert items[1].piece_ids == ["piece_1__c0"]


# --- allowed_orientations per grain (the §6 table) ---

def test_allowed_single_grain_no_flip():
    items = _group_to_items([_rect("p__c0", 60, 40, 90.0)], "single", 90.0)
    assert items[0].allowed_offsets == [0.0]


def test_allowed_bi_grain_flip():
    items = _group_to_items([_rect("p__c0", 60, 40, 90.0)], "bi", 90.0)
    assert items[0].allowed_offsets == [0.0, 180.0]


def test_allowed_no_grainline_cardinals():
    items = _group_to_items([_rect("p__c0", 60, 40, None)], "single", 90.0)
    assert items[0].allowed_offsets == [0.0, 90.0, 180.0, 270.0]


# --- emit transform: grain-aligned + 90deg axis map, origin-normalized ---

def test_emit_axis_map_bounds():
    # 100x50 rect, grainline 90 == fabric grain 90 -> target 0, emit rotation 90deg.
    # 90deg rotation swaps extents: x 100->50 (along-grain->length), y 50->100 (cross-grain->width).
    items = _group_to_items([_rect("p__c0", 100, 50, 90.0)], "single", 90.0)
    minx, miny, maxx, maxy = items[0].emitted.bounds
    assert (round(minx), round(miny)) == (0, 0)          # origin-normalized
    assert (round(maxx), round(maxy)) == (50, 100)        # along-grain->X, cross-grain->Y


# --- _instance_json shape ---

def test_instance_json_shape():
    items = _group_to_items([_rect("p__c0", 100, 50, 90.0), _rect("p__c1", 100, 50, 90.0)], "bi", 90.0)
    inst = _instance_json(items, strip_height=1631.0)
    assert inst["strip_height"] == 1631.0
    assert inst["items"][0]["id"] == 0
    assert inst["items"][0]["demand"] == 2
    assert inst["items"][0]["allowed_orientations"] == [0.0, 180.0]
    assert inst["items"][0]["shape"]["type"] == "simple_polygon"
    assert len(inst["items"][0]["shape"]["data"]) == 4  # no closing dup
```

- [ ] **Step 2: Run to verify it fails**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit\test_separation.py -v -k "group or allowed or emit or instance"`
Expected: FAIL — `ImportError: cannot import name '_group_to_items'`.

- [ ] **Step 3: Write minimal implementation** (append to `separation.py`, after the resolver)

```python
@dataclass
class _SepItem:
    index: int
    piece_ids: list[str]         # expanded "__cN" ids, in placement-assignment order
    base_angle: float            # engine pre-rotation reference (engine_set[0])
    emitted: ShapelyPolygon      # grain-aligned + 90deg axis-mapped, origin-normalized
    allowed_offsets: list[float] # jagua allowed_orientations = engine_set - base_angle


def _emit_shape(piece: Piece, base_angle: float) -> ShapelyPolygon:
    """Grain-align (base) + 90deg axis swap; origin-normalize bbox-min -> (0,0)."""
    poly = shapely.affinity.rotate(
        ShapelyPolygon(piece.polygon), base_angle + 90.0, origin=(0, 0), use_radians=False)
    minx, miny = poly.bounds[0], poly.bounds[1]
    return shapely.affinity.translate(poly, xoff=-minx, yoff=-miny)


def _group_to_items(pieces: list[Piece], grain_mode: str, fabric_grain_deg: float) -> list[_SepItem]:
    """Collapse expanded pieces to base groups and build one jagua item per group.

    allowed_offsets follows the grain table (single -> [0]; bi -> [0,180];
    no-grainline -> [0,90,180,270]) by re-expressing _layout_rotations relative
    to base_angle. base_angle (= engine_set[0]) is folded into the final rotation
    on reconstruction, so net engine rotation lands exactly in the engine set.
    """
    groups = group_pieces_by_base_id(pieces)
    items: list[_SepItem] = []
    for index, members in enumerate(groups.values()):
        rep = members[0]
        engine_set = _layout_rotations(grain_mode, fabric_grain_deg, rep.grainline_direction_deg)
        base = engine_set[0]
        items.append(_SepItem(
            index=index,
            piece_ids=[p.id for p in members],
            base_angle=base,
            emitted=_emit_shape(rep, base),
            allowed_offsets=[round((a - base) % 360.0, 6) for a in engine_set],
        ))
    return items


def _instance_json(items: list[_SepItem], strip_height: float, name: str = "openmarker") -> dict:
    return {
        "name": name,
        "strip_height": float(strip_height),
        "items": [
            {
                "id": it.index,
                "demand": len(it.piece_ids),
                "allowed_orientations": [float(o) for o in it.allowed_offsets],
                "shape": {
                    "type": "simple_polygon",
                    "data": [[float(x), float(y)] for x, y in it.emitted.exterior.coords[:-1]],
                },
            }
            for it in items
        ],
    }
```

- [ ] **Step 4: Run to verify it passes**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit\test_separation.py -v`
Expected: PASS (all Task 2 + Task 3 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/separation.py engine/tests/unit/test_separation.py
git commit -m "feat(separation): pieces -> grain-aligned jagua-rs instance JSON

Per-item allowed_orientations from grain_mode + grainline (single=[0] no flip,
bi=[0,180], no-grainline=[0,90,180,270]); 90deg axis map on the emitted shape.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `_reconstruct` (inverse axis-map → Placements)

**Files:**
- Modify: `engine/core/layout/separation.py`
- Test: `engine/tests/unit/test_separation.py`

- [ ] **Step 1: Write the failing test** (append to `test_separation.py`)

```python
from core.layout.separation import _reconstruct
from core.layout.heuristic import _placed_polygon, _has_area_overlap


def test_reconstruct_round_trip_grain_and_no_overlap():
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0)]
    items = _group_to_items(pieces, "bi", 90.0)
    w = items[0].emitted.bounds[2]   # along-grain extent -> jagua X (length)
    h = items[0].emitted.bounds[3]   # cross-grain extent -> jagua Y (width)
    # Simulated sparrow solution: two copies side-by-side, second flipped 180.
    sol = {"solution": {"strip_width": 2 * w, "layout": {"placed_items": [
        {"item_id": 0, "transformation": {"rotation": 0.0,   "translation": [0.0, 0.0]}},
        {"item_id": 0, "transformation": {"rotation": 180.0, "translation": [2 * w, h]}},
    ]}}}
    fabric = h + 2 * EDGE_GAP
    placements = _reconstruct(sol, items, fabric_width_mm=fabric)

    assert {pl.piece_id for pl in placements} == {"piece_0__c0", "piece_0__c1"}
    for pl in placements:                                  # grain: engine set {0,180}
        assert round(pl.rotation_deg) % 180 == 0
    pmap = {p.id: p for p in pieces}
    polys = [_placed_polygon(pmap[pl.piece_id], pl.x, pl.y, pl.rotation_deg) for pl in placements]
    assert not _has_area_overlap(polys[0], polys[1])        # round-trip is overlap-free
    for poly in polys:                                      # cross-grain landed on X, within width
        assert poly.bounds[0] >= -0.5 and poly.bounds[2] <= fabric + 0.5
        assert poly.bounds[1] >= -0.5
```

- [ ] **Step 2: Run to verify it fails**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit\test_separation.py -v -k reconstruct`
Expected: FAIL — `ImportError: cannot import name '_reconstruct'`.

- [ ] **Step 3: Write minimal implementation** (append to `separation.py`)

```python
def _reconstruct(solution: dict, items: list[_SepItem], fabric_width_mm: float) -> list[Placement]:
    """Invert the axis map and build engine Placements.

    For each placed copy: rebuild its jagua-frame polygon (rotate emitted by r,
    translate by t), rotate the WHOLE layout by -90deg (axis-swap inverse), then
    shift bbox-min -> (EDGE_GAP, EDGE_GAP). rotation_deg = (base + r) lands exactly
    in the engine grain set; (x, y) = rotated-bbox-min so the existing
    _placed_polygon reproduces the polygon for metrics/validation/render.
    """
    by_index = {it.index: it for it in items}
    counters: dict[int, int] = {it.index: 0 for it in items}
    raw: list[tuple[str, float, ShapelyPolygon]] = []  # (piece_id, rotation_deg, engine_poly)
    for pi in solution["solution"]["layout"]["placed_items"]:
        it = by_index[pi["item_id"]]
        r = float(pi["transformation"]["rotation"]) % 360.0
        t = pi["transformation"]["translation"]
        jpoly = shapely.affinity.translate(
            shapely.affinity.rotate(it.emitted, r, origin=(0, 0), use_radians=False),
            xoff=float(t[0]), yoff=float(t[1]))
        epoly = shapely.affinity.rotate(jpoly, -90.0, origin=(0, 0), use_radians=False)
        j = counters[it.index]
        counters[it.index] += 1
        raw.append((it.piece_ids[j], round((it.base_angle + r) % 360.0, 6), epoly))

    if not raw:
        return []
    dx = EDGE_GAP - min(p.bounds[0] for _, _, p in raw)
    dy = EDGE_GAP - min(p.bounds[1] for _, _, p in raw)
    placements: list[Placement] = []
    for piece_id, rotation_deg, epoly in raw:
        shifted = shapely.affinity.translate(epoly, xoff=dx, yoff=dy)
        placements.append(Placement(piece_id, round(shifted.bounds[0], 4),
                                    round(shifted.bounds[1], 4), rotation_deg))
    return placements
```

- [ ] **Step 4: Run to verify it passes**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit\test_separation.py -v`
Expected: PASS (all prior + reconstruct).

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/separation.py engine/tests/unit/test_separation.py
git commit -m "feat(separation): reconstruct sparrow output to engine Placements

Inverse 90deg axis map + global shift; rotation_deg = base + r lands in the
engine grain set; (x,y) = rotated-bbox-min round-trips through _placed_polygon.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `_validate_layout` (backstop)

**Files:**
- Modify: `engine/core/layout/separation.py`
- Test: `engine/tests/unit/test_separation.py`

- [ ] **Step 1: Write the failing tests** (append to `test_separation.py`)

```python
from core.layout.separation import _validate_layout
from core.layout.heuristic import Placement


def _clean_placements():
    # two 60x40 copies, grainline 90, bi-grain: side by side, no overlap, rotation 0
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0)]
    placements = [Placement("piece_0__c0", 10.0, 10.0, 0.0),
                  Placement("piece_0__c1", 10.0, 60.0, 0.0)]
    return pieces, placements


def test_validate_passes_clean():
    pieces, placements = _clean_placements()
    _validate_layout(placements, pieces, fabric_width_mm=200.0, grain_mode="bi", fabric_grain_deg=90.0)


def test_validate_rejects_off_grain():
    pieces, placements = _clean_placements()
    placements[1] = Placement("piece_0__c1", 10.0, 60.0, 90.0)  # 90 not in {0,180}
    with pytest.raises(ValueError, match="off-grain"):
        _validate_layout(placements, pieces, 200.0, "bi", 90.0)


def test_validate_rejects_overlap():
    pieces, placements = _clean_placements()
    placements[1] = Placement("piece_0__c1", 10.0, 10.0, 0.0)  # identical position
    with pytest.raises(ValueError, match="overlap"):
        _validate_layout(placements, pieces, 200.0, "bi", 90.0)


def test_validate_rejects_over_width():
    pieces, placements = _clean_placements()
    placements[1] = Placement("piece_0__c1", 10.0, 5000.0, 0.0)  # far outside fabric width
    with pytest.raises(ValueError, match="outside fabric"):
        _validate_layout(placements, pieces, 40.0, "bi", 90.0)


def test_validate_rejects_missing():
    pieces, placements = _clean_placements()
    with pytest.raises(ValueError, match="placed 1 of 2"):
        _validate_layout(placements[:1], pieces, 200.0, "bi", 90.0)
```

- [ ] **Step 2: Run to verify it fails**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit\test_separation.py -v -k validate`
Expected: FAIL — `ImportError: cannot import name '_validate_layout'`.

- [ ] **Step 3: Write minimal implementation** (append to `separation.py`)

```python
def _validate_layout(placements: list[Placement], pieces: list[Piece], fabric_width_mm: float,
                     grain_mode: str, fabric_grain_deg: float, tol_deg: float = 0.6) -> None:
    """Re-assert the hard constraints in OUR frame. Raises ValueError listing the
    first violations: off-grain rotation, area-overlap (>0.5 mm^2), out-of-fabric,
    or incomplete coverage. The axis/orientation backstop the spec mandates."""
    issues: list[str] = []
    piece_map = {p.id: p for p in pieces}
    if len(placements) != len(pieces):
        issues.append(f"placed {len(placements)} of {len(pieces)} pieces")

    polys: list[ShapelyPolygon] = []
    for pl in placements:
        piece = piece_map[pl.piece_id]
        allowed = _layout_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg)
        if not any(abs(((pl.rotation_deg - a + 180.0) % 360.0) - 180.0) <= tol_deg for a in allowed):
            issues.append(f"{pl.piece_id}: off-grain rotation {pl.rotation_deg} (allowed {allowed})")
        poly = _placed_polygon(piece, pl.x, pl.y, pl.rotation_deg)
        b = poly.bounds
        if b[0] < -0.5 or b[2] > fabric_width_mm + 0.5 or b[1] < -0.5:
            issues.append(f"{pl.piece_id}: outside fabric bounds {tuple(round(v, 1) for v in b)}")
        polys.append(poly)

    n = len(polys)
    for i in range(n):
        bi = polys[i].bounds
        for j in range(i + 1, n):
            bj = polys[j].bounds
            if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                continue
            if _has_area_overlap(polys[i], polys[j]):
                issues.append(f"overlap: {placements[i].piece_id} & {placements[j].piece_id}")
                break
        if len(issues) > 8:
            break

    if issues:
        raise ValueError("separation layout invalid: " + "; ".join(issues[:6]))
```

- [ ] **Step 4: Run to verify it passes**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit\test_separation.py -v`
Expected: PASS (all unit tests).

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/separation.py engine/tests/unit/test_separation.py
git commit -m "feat(separation): output validator (grain/overlap/width/coverage)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Build + vendor `sparrow.exe`

> ⚠️ **One-time ONLINE step** (network + Rust ≥1.86). Produces the committed offline binary. If the sandbox/network blocks the build, ask the user to run the clone+build, then continue from Step 3.

**Files:**
- Modify: `.gitignore`
- Create: `engine/vendor/sparrow/sparrow.exe`, `engine/vendor/sparrow/PROVENANCE.md`

- [ ] **Step 1: Clone + build sparrow** (from worktree root)

```powershell
git clone https://github.com/JeroenGar/sparrow tools/sparrow
cd tools/sparrow
git rev-parse HEAD    # record this hash for PROVENANCE.md
cargo build --release
cd ..\..
Get-ChildItem tools\sparrow\target\release\sparrow.exe
```
Expected: `sparrow.exe` exists. (`tools/` is gitignored.)

- [ ] **Step 2: Vendor the binary**

```powershell
New-Item -ItemType Directory -Force engine\vendor\sparrow | Out-Null
Copy-Item tools\sparrow\target\release\sparrow.exe engine\vendor\sparrow\sparrow.exe
```

- [ ] **Step 3: Add the `.gitignore` negation** so the vendored `*.exe` can be staged

In `.gitignore`, immediately after the `*.exe` / `*.dll` / `*.msi` block (the `# OS / Windows` section), add:
```gitignore
# Exception: the vendored sparrow sidecar must be committed (offline Ultra tier)
!engine/vendor/sparrow/sparrow.exe
```

- [ ] **Step 4: Write `engine/vendor/sparrow/PROVENANCE.md`**

```markdown
# Vendored sparrow binary

- **Upstream:** https://github.com/JeroenGar/sparrow (MIT)
- **Commit:** <PASTE the `git rev-parse HEAD` hash from Step 1>
- **Built with:** `cargo build --release`, Rust <PASTE `rustc --version`>
- **Target:** Windows x64
- **Built on:** 2026-06-07

## Why committed
Offline, one-click install (no Rust/network on user machines). Refresh deliberately
on upgrade: rebuild from the pinned commit, replace `sparrow.exe`, update this file.

## Licenses
- sparrow — MIT (see upstream `LICENSE`).
- jagua-rs (collision engine sparrow links) — MPL-2.0. We ship an UNMODIFIED binary,
  so the MPL-2.0 source-availability notice suffices: https://github.com/JeroenGar/jagua-rs
```

- [ ] **Step 5: Verify the binary is now resolvable + stageable**

Run (from `engine/`): `.venv\Scripts\python -c "from core.layout.separation import _resolve_sparrow_path; print(_resolve_sparrow_path())"`
Expected: prints the `engine\vendor\sparrow\sparrow.exe` path.

Run (from worktree root): `git check-ignore engine/vendor/sparrow/sparrow.exe`
Expected: **no output** (exit 1) — i.e. NOT ignored.

- [ ] **Step 6: Commit**

```bash
git add .gitignore engine/vendor/sparrow/sparrow.exe engine/vendor/sparrow/PROVENANCE.md
git commit -m "build(separation): vendor offline sparrow.exe sidecar + provenance

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `_run_sparrow` + cancellation registry

**Files:**
- Modify: `engine/core/layout/separation.py`
- Test: `engine/tests/unit/test_separation.py` (registry unit test)
- Create: `engine/tests/integration/test_separation_sidecar.py` (real-binary)

- [ ] **Step 1: Write the failing unit test** (append to `test_separation.py`)

```python
from core.layout import separation as sep


def test_kill_current_sparrow_terminates_registered_proc():
    class _Dummy:
        def __init__(self): self.killed = False
        def terminate(self): self.killed = True
    d = _Dummy()
    sep._set_current_sparrow(d)
    sep.kill_current_sparrow()
    assert d.killed is True
    sep._set_current_sparrow(None)
    sep.kill_current_sparrow()  # no-op when none registered
```

- [ ] **Step 2: Run to verify it fails**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit\test_separation.py -v -k kill`
Expected: FAIL — `AttributeError: module ... has no attribute '_set_current_sparrow'`.

- [ ] **Step 3: Write minimal implementation** (append to `separation.py`)

```python
# --- subprocess + cancellation plumbing ---
_sparrow_lock = threading.Lock()
_current_sparrow: "subprocess.Popen | None" = None


def _set_current_sparrow(proc) -> None:
    global _current_sparrow
    with _sparrow_lock:
        _current_sparrow = proc


def kill_current_sparrow() -> None:
    """Terminate the in-flight sparrow child (called by /cancel-layout). No-op if none."""
    with _sparrow_lock:
        proc = _current_sparrow
    if proc is None:
        return
    try:
        proc.terminate()
    except Exception:
        pass


def _run_sparrow(instance: dict, budget_s: float, seed: int) -> dict:
    """Write the instance, run sparrow in a scratch dir, return the parsed output.

    Raises CancellationError if /cancel-layout killed the child; ValueError on a
    genuine sparrow failure or missing output.
    """
    exe = _resolve_sparrow_path()
    with tempfile.TemporaryDirectory() as td:
        ipath = os.path.join(td, "inst.json")
        with open(ipath, "w", encoding="utf-8") as f:
            json.dump(instance, f)
        proc = subprocess.Popen(
            [exe, "-i", ipath, "-t", str(int(budget_s)), "-s", str(int(seed))],
            cwd=td, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _set_current_sparrow(proc)
        try:
            proc.wait()
        finally:
            _set_current_sparrow(None)
        if is_cancelled():
            raise CancellationError("sparrow run cancelled")
        if proc.returncode != 0:
            raise ValueError(f"sparrow exited with code {proc.returncode}")
        outdir = os.path.join(td, "output")
        finals = ([x for x in os.listdir(outdir) if x.startswith("final_") and x.endswith(".json")]
                  if os.path.isdir(outdir) else [])
        if not finals:
            raise ValueError("sparrow produced no output")
        with open(os.path.join(outdir, finals[0]), encoding="utf-8") as f:
            return json.load(f)
```

- [ ] **Step 4: Write the real-binary integration test**

Create `engine/tests/integration/test_separation_sidecar.py`:
```python
"""Real-sparrow integration. Skips gracefully if the binary is unavailable."""
import threading
import time

import pytest

from core.models.piece import Piece, BoundingBox
from core.layout import separation as sep
from core.layout.cancellation import CancellationError, request_cancellation, reset_cancellation


def _has_binary() -> bool:
    try:
        sep._resolve_sparrow_path()
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _has_binary(), reason="sparrow binary not available")


def _rect(piece_id, w, h, grainline=90.0):
    return Piece(id=piece_id, name=piece_id, polygon=[(0, 0), (w, 0), (w, h), (0, h)],
                 area=w * h, bbox=BoundingBox(0, 0, w, h, w, h), is_valid=True,
                 grainline_direction_deg=grainline)


def test_run_sparrow_tiny_instance_produces_output():
    reset_cancellation()
    items = sep._group_to_items([_rect("p__c0", 80, 40), _rect("p__c1", 80, 40),
                                 _rect("q__c0", 60, 30)], "bi", 90.0)
    inst = sep._instance_json(items, strip_height=300.0)
    out = sep._run_sparrow(inst, budget_s=5, seed=42)
    assert out["solution"]["layout"]["placed_items"]


def test_cancellation_kills_sparrow():
    reset_cancellation()
    items = sep._group_to_items([_rect("p__c0", 80, 40)] + [_rect(f"p__c{i}", 80, 40) for i in range(1, 30)],
                                "bi", 90.0)
    inst = sep._instance_json(items, strip_height=300.0)
    result = {}

    def _run():
        try:
            sep._run_sparrow(inst, budget_s=600, seed=42)
        except CancellationError:
            result["cancelled"] = True
        except Exception as e:  # noqa: BLE001
            result["error"] = repr(e)

    th = threading.Thread(target=_run)
    th.start()
    time.sleep(1.0)
    request_cancellation()
    sep.kill_current_sparrow()
    th.join(timeout=15)
    reset_cancellation()
    assert result.get("cancelled") is True
```

- [ ] **Step 5: Run tests to verify they pass**

Run (from `engine/`): `.venv\Scripts\pytest tests\unit\test_separation.py tests\integration\test_separation_sidecar.py -v`
Expected: unit PASS; integration PASS (binary vendored in Task 6).

- [ ] **Step 6: Commit**

```bash
git add engine/core/layout/separation.py engine/tests/unit/test_separation.py engine/tests/integration/test_separation_sidecar.py
git commit -m "feat(separation): sparrow subprocess runner + cancellation kill

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `run_separation_layout` (public entry)

**Files:**
- Modify: `engine/core/layout/separation.py`
- Test: `engine/tests/integration/test_separation_sidecar.py`

- [ ] **Step 1: Write the failing integration test** (append to `test_separation_sidecar.py`)

```python
def test_run_separation_layout_end_to_end():
    reset_cancellation()
    pieces = [_rect("p__c0", 80, 40), _rect("p__c1", 80, 40), _rect("q__c0", 60, 30)]
    placements, marker_length, utilization = sep.run_separation_layout(
        pieces, fabric_width_mm=300.0, grain_mode="bi", fabric_grain_deg=90.0,
        budget_s=5, seed=42)
    assert len(placements) == len(pieces)
    assert marker_length > 0 and 0 < utilization <= 100
    # grain respected on every placement
    assert all(round(pl.rotation_deg) % 180 == 0 for pl in placements)
```

- [ ] **Step 2: Run to verify it fails**

Run (from `engine/`): `.venv\Scripts\pytest tests\integration\test_separation_sidecar.py -v -k end_to_end`
Expected: FAIL — `AttributeError: ... has no attribute 'run_separation_layout'`.

- [ ] **Step 3: Write minimal implementation** (append to `separation.py`)

```python
def run_separation_layout(pieces: list[Piece], fabric_width_mm: float, grain_mode: str,
                          fabric_grain_deg: float, budget_s: float, seed: int = 42
                          ) -> tuple[list[Placement], float, float]:
    """Run the separation (sparrow) engine. Mirrors auto_layout_polygon's return
    (placements, marker_length_mm, utilization_pct). Raises CancellationError on
    kill (-> API 499); ValueError on invalid/empty output (-> API 400)."""
    if not pieces:
        raise ValueError("no pieces to lay out")
    items = _group_to_items(pieces, grain_mode, fabric_grain_deg)
    strip_height = fabric_width_mm - 2 * EDGE_GAP
    solution = _run_sparrow(_instance_json(items, strip_height), budget_s, seed)
    placements = _reconstruct(solution, items, fabric_width_mm)
    _validate_layout(placements, pieces, fabric_width_mm, grain_mode, fabric_grain_deg)
    marker_length, utilization = _compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims)
    return placements, marker_length, utilization
```

- [ ] **Step 4: Run to verify it passes**

Run (from `engine/`): `.venv\Scripts\pytest tests\integration\test_separation_sidecar.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/separation.py engine/tests/integration/test_separation_sidecar.py
git commit -m "feat(separation): run_separation_layout public entry (convert/run/parse/validate/metrics)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: API wiring (`quality="ultra"` + cancel kill)

**Files:**
- Modify: `engine/api/main.py`
- Modify: `engine/tests/integration/test_api.py`

- [ ] **Step 1: Write the failing tests** (append to `engine/tests/integration/test_api.py`)

First check the top of `test_api.py` for the existing `client` fixture / TestClient pattern and a helper that builds a piece payload; reuse them. Then add:
```python
def test_ultra_is_a_valid_quality(client, monkeypatch):
    # Stub the engine so routing is tested without the binary.
    from core.layout.heuristic import Placement
    import api.main as main
    def _stub(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, budget_s, seed=42):
        return [Placement(pieces[0].id, 10.0, 10.0, 0.0)], 123.0, 45.6
    monkeypatch.setattr(main, "run_separation_layout", _stub)
    resp = client.post("/auto-layout", json=_one_piece_body(quality="ultra"))
    assert resp.status_code == 200
    assert resp.json()["marker_length_mm"] == 123.0


def test_ultra_invalid_output_returns_400(client, monkeypatch):
    import api.main as main
    def _bad(*a, **k):
        raise ValueError("separation layout invalid: off-grain")
    monkeypatch.setattr(main, "run_separation_layout", _bad)
    resp = client.post("/auto-layout", json=_one_piece_body(quality="ultra"))
    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"]
```
Add a `_one_piece_body(quality)` helper near the top of the test module (mirror the existing auto-layout request bodies in this file — same `pieces`/`bbox` shape, `filename`, `fabric_width_mm`, `grain_mode`, and the given `quality`).

- [ ] **Step 2: Run to verify it fails**

Run (from `engine/`): `.venv\Scripts\pytest tests\integration\test_api.py -v -k ultra`
Expected: FAIL — `422` (quality "ultra" rejected) and/or `run_separation_layout` not importable in `api.main`.

- [ ] **Step 3: Implement the wiring** in `engine/api/main.py`

3a. Extend the import (near line 26):
```python
from core.layout.heuristic import auto_layout_polygon
from core.layout.separation import run_separation_layout
```
3b. Add `"ultra"` to `VALID_QUALITIES` (line ~96):
```python
VALID_QUALITIES = ("fast", "better", "best", "ultra")
```
3c. Add the budget (line ~100):
```python
QUALITY_BUDGETS_S = {"better": 180.0, "best": 420.0, "ultra": 600.0}
```
3d. Add the routing branch inside `_do_layout` (after the `fast` branch, before `better/best`):
```python
        if quality == "ultra":
            return run_separation_layout(
                pieces, fabric_width_mm, grain_mode, FABRIC_GRAIN_DEG,
                budget_s=QUALITY_BUDGETS_S["ultra"], seed=GA_GUI_SEED,
            )
```
3e. Kill the child on cancel — in `cancel_layout()` (line ~300), after `kill_current_executor()`:
```python
    from core.layout.separation import kill_current_sparrow
    kill_current_sparrow()
```

- [ ] **Step 4: Run to verify it passes**

Run (from `engine/`): `.venv\Scripts\pytest tests\integration\test_api.py -v`
Expected: PASS (new + existing API tests).

- [ ] **Step 5: Commit**

```bash
git add engine/api/main.py engine/tests/integration/test_api.py
git commit -m "feat(api): route quality=ultra to separation engine; cancel kills sparrow

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Frontend — Ultra radio

**Files:**
- Modify: `frontend/src/types/engine.ts`, `frontend/src/components/sidebar/QualityPanel.tsx`, `frontend/src/components/sidebar/QualityPanel.test.tsx`, `frontend/src/app/App.tsx`

- [ ] **Step 1: Install frontend deps** (once)

Run (from `frontend/`): `npm install`
Expected: completes.

- [ ] **Step 2: Write the failing tests** — append to `QualityPanel.test.tsx`:
```python
  it("renders the Ultra radio", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} />);
    expect(screen.getByLabelText(/Ultra/i)).toBeTruthy();
  });

  it("calls onChange with 'ultra' when Ultra clicked", () => {
    const onChange = vi.fn();
    render(<QualityPanel quality="fast" onChange={onChange} />);
    fireEvent.click(screen.getByLabelText(/Ultra/i));
    expect(onChange).toHaveBeenCalledWith("ultra");
  });
```
(Use TSX/JS syntax — the block above is JS despite the fence.)

- [ ] **Step 3: Run to verify it fails**

Run (from `frontend/`): `npm run test -- QualityPanel`
Expected: FAIL — no element labelled "Ultra".

- [ ] **Step 4: Implement**

4a. `frontend/src/types/engine.ts` (line 48):
```typescript
export type LayoutQuality = "fast" | "better" | "best" | "ultra";
```
4b. `frontend/src/components/sidebar/QualityPanel.tsx` — extend `OPTIONS`:
```typescript
const OPTIONS: { value: LayoutQuality; label: string; hint: string }[] = [
  { value: "fast", label: "Fast", hint: "quick" },
  { value: "better", label: "Better", hint: "tighter" },
  { value: "best", label: "Best", hint: "very tight" },
  { value: "ultra", label: "Ultra", hint: "tightest" },
];
```
4c. `frontend/src/app/App.tsx` — update the effort-disable comment (line ~275) to note Ultra (the predicate `quality !== "fast"` already disables effort for ultra; no logic change):
```tsx
            {/* Parallel effort applies to the Fast tier only. Better/Best force
                all-but-one core for more GA islands; Ultra runs the sparrow
                sidecar (no effort knob) — so the radio is disabled for all of them. */}
```

- [ ] **Step 5: Run to verify it passes**

Run (from `frontend/`): `npm run test -- QualityPanel`
Expected: PASS. Then `npm run build` — Expected: tsc + vite build succeed (LayoutQuality union is exhaustive).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/engine.ts frontend/src/components/sidebar/QualityPanel.tsx frontend/src/components/sidebar/QualityPanel.test.tsx frontend/src/app/App.tsx
git commit -m "feat(frontend): add Ultra quality tier to QualityPanel

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Bench, time-curve, and docs

**Files:**
- Create: `engine/tests/bench_separation.py`
- Modify: `docs/planning/PERFORMANCE.md`, `docs/planning/BACKLOG.md`

- [ ] **Step 1: Create the production-module bench** `engine/tests/bench_separation.py`

```python
"""Ultra-vs-GA bench + time-curve, via the PRODUCTION separation module.

    ...python.exe engine\\tests\\bench_separation.py [--sample S --copies N --budgets 60,180,300,420,600]
"""
from __future__ import annotations
import argparse, os, sys, time
HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from dataclasses import replace
from core.dxf import parse_dxf
from core.geometry import normalize_piece
from core.layout.separation import run_separation_layout

FABRIC = 1651.0
GA_REF = {"sample_2.dxf": 11412.5, "sample_3.dxf": None, "sample_4.dxf": None}


def _find(sample):
    here = os.path.abspath(HERE)
    for _ in range(8):
        c = os.path.join(here, "examples", "input", sample)
        if os.path.isfile(c):
            return c
        here = os.path.dirname(here)
    return None


def _load(sample, copies):
    path = _find(sample)
    if not path:
        print(f"SKIP: {sample} not found"); sys.exit(0)
    with open(path, "rb") as f:
        raw = parse_dxf(f.read())
    base = []
    for i, r in enumerate(raw):
        try:
            base.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    return [replace(b, id=f"{b.id}__c{c}") for c in range(copies) for b in base]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="sample_2.dxf")
    ap.add_argument("--copies", type=int, default=10)
    ap.add_argument("--budgets", default="600")
    args = ap.parse_args()
    pieces = _load(args.sample, args.copies)
    ref = GA_REF.get(args.sample)
    for budget in [int(b) for b in args.budgets.split(",")]:
        t0 = time.perf_counter()
        placements, marker, util = run_separation_layout(pieces, FABRIC, "bi", 90.0, budget_s=budget, seed=42)
        dt = time.perf_counter() - t0
        gate = f"  GA={ref}  ->  {'PASS >=3%' if ref and marker <= ref * 0.97 else ''}" if ref else ""
        print(f"{args.sample} x{args.copies} @ {budget}s:  marker={marker:.1f}mm  util={util:.2f}%  "
              f"valid({len(placements)} placed)  time={dt:.1f}s{gate}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the time-curve** (long — minutes per budget)

Run (from worktree root):
```powershell
engine\.venv\Scripts\python.exe engine\tests\bench_separation.py --sample sample_2.dxf --copies 10 --budgets 60,180,300,420,600
engine\.venv\Scripts\python.exe engine\tests\bench_separation.py --sample sample_4.dxf --copies 6 --budgets 180,600
```
Expected: every line `valid`; `sample_2 ×10` marker ≤ 11070 mm (≥3% under GA 11412.5) at ≥180s. Record the numbers.

- [ ] **Step 3: Append a PERFORMANCE.md §6 entry** dated `2026-06-07` titled "Separation engine (sparrow) PRODUCTIONIZED as Ultra tier", with: the time-curve table (budget → marker/util/time), confirmation the 600 s default clears the gate, and a note that the win matches the Phase-1 eval. (Follow the existing §6 entry format.)

- [ ] **Step 4: Update BACKLOG.md** — add/check off the Phase-2 task list (module, API, frontend, vendoring, bench/docs) per the project working rule.

- [ ] **Step 5: Commit**

```bash
git add engine/tests/bench_separation.py docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git commit -m "bench+docs(separation): Ultra time-curve, PERFORMANCE.md result, BACKLOG

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Full engine suite (from `engine/`): `.venv\Scripts\pytest tests\ -q` — all pass (integration sidecar tests run since the binary is vendored).
- [ ] Frontend (from `frontend/`): `npm run test` and `npm run build` — pass.
- [ ] `git check-ignore engine/vendor/sparrow/sparrow.exe` returns nothing (binary committed).
- [ ] Manual smoke (optional): start `scripts\dev-engine.bat`, `cargo tauri dev`, import `sample_2.dxf`, pick **Ultra**, confirm a valid marker renders and Stop cancels cleanly.
- [ ] Use `superpowers:requesting-code-review` before opening the PR (push/PR need explicit user approval).

---

## Self-Review

**Spec coverage:** §4 architecture → Tasks 3-9. §5 module surface → Tasks 2-8 (every helper has a task). §6 grain table → Task 3 (three allowed_orientations tests). §7 transform → Tasks 3-4 (emit + reconstruct, round-trip test). §8 validation → Task 5. §9 subprocess/cancel → Tasks 7, 9. §10 vendoring/resolver → Tasks 2, 6. §11 API/cache → Task 9 (cache key already includes `quality`; no code change needed — covered). §12 frontend → Task 10. §13 budget/time-curve → Tasks 9, 11. §14 testing → every task is TDD; integration + bench in 7, 8, 11. §15 acceptance → Final verification.

**Placeholder scan:** PROVENANCE.md has two `<PASTE …>` markers — these are *runtime values* (the build's commit hash + rustc version) that only exist after Step 1 runs, so they are captured-during-execution, not plan placeholders. No other TODOs.

**Type consistency:** `_SepItem` fields (`index`, `piece_ids`, `base_angle`, `emitted`, `allowed_offsets`) are defined in Task 3 and used identically in Tasks 4, 7, 8. `run_separation_layout(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, budget_s, seed)` signature matches between Task 8 (def), Task 9 (API call + stub), and the integration test. `kill_current_sparrow` / `_set_current_sparrow` consistent across Tasks 7 and 9. `Placement(piece_id, x, y, rotation_deg)` matches the heuristic dataclass. `QUALITY_BUDGETS_S["ultra"]` defined and read in Task 9.
