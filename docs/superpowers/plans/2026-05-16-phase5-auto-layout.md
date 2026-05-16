# Phase 5 — Auto Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click Auto Layout button that runs a strip-packing heuristic on the engine, enforces grainline constraints per piece, and displays marker length + utilization in the status bar.

**Architecture:** New engine module `core/layout/` contains pure functions for grain constraint computation (`grain.py`) and strip-packing in bbox mode and polygon mode (`heuristic.py`). A new `POST /auto-layout` endpoint wires these together. The frontend adds `GrainPanel`, `useAutoLayout`, and two buttons (Auto Layout / Reset). All placement state goes through the existing `usePlacements` hook via a new `setAllPlacements` export.

**Tech Stack:** Python 3.11 · FastAPI · Shapely · pytest · React 18 · TypeScript · Vitest

**Prerequisite:** Pre-Phase 5 fixes plan complete. `Piece` model must have `grainline_direction_deg: float | None`.

**Worktree branch:** `auto-layout/masonw/strip-packing-grain`
**Worktree dir:** `.worktrees/auto-layout/masonw/strip-packing-grain`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `engine/core/layout/__init__.py` | Create | Package marker |
| `engine/core/layout/grain.py` | Create | `allowed_rotations()` — maps grain mode + angles → candidate list |
| `engine/core/layout/heuristic.py` | Create | `auto_layout_bbox()`, `auto_layout_polygon()`, `Placement` dataclass |
| `engine/api/main.py` | Modify | Add `POST /auto-layout` endpoint |
| `engine/tests/unit/test_grain.py` | Create | Grain constraint unit tests |
| `engine/tests/unit/test_heuristic.py` | Create | Strip-packing unit tests |
| `frontend/src/types/engine.ts` | Modify | Add `GrainMode`, `AutoLayoutPlacement`, `AutoLayoutResponse` |
| `frontend/src/hooks/usePlacements.ts` | Modify | Expose `setAllPlacements` in return |
| `frontend/src/hooks/useAutoLayout.ts` | Create | Fetch wrapper for `POST /auto-layout` |
| `frontend/src/components/sidebar/GrainPanel.tsx` | Create | Grain direction + mode + fast mode controls |
| `frontend/src/app/App.tsx` | Modify | Grain state, GrainPanel, Auto Layout button, metrics display |

---

## Task 1: `grain.py` — allowed rotations per piece

**Files:**
- Create: `engine/core/layout/__init__.py`
- Create: `engine/core/layout/grain.py`
- Create: `engine/tests/unit/test_grain.py`

- [ ] **Step 1: Create the layout package (empty for now — expanded in Task 2)**

```python
# engine/core/layout/__init__.py
# populated after heuristic.py is created in Task 2
```

- [ ] **Step 2: Write failing tests for `allowed_rotations`**

Create `engine/tests/unit/test_grain.py`:

```python
import pytest
from core.layout.grain import allowed_rotations


def test_mode_none_returns_all_360():
    result = allowed_rotations("none", fabric_grain_deg=0.0, piece_grainline_deg=90.0)
    assert result == list(range(360))


def test_mode_none_ignores_grainline():
    """grain_mode='none' ignores piece grainline regardless of value."""
    result = allowed_rotations("none", fabric_grain_deg=45.0, piece_grainline_deg=None)
    assert result == list(range(360))


def test_piece_without_grainline_always_free():
    """Any grain mode with piece_grainline_deg=None returns all 360 rotations."""
    for mode in ("single", "bi"):
        result = allowed_rotations(mode, fabric_grain_deg=0.0, piece_grainline_deg=None)
        assert result == list(range(360)), f"mode={mode} with None grainline should be free"


def test_single_aligns_grainline_with_fabric():
    """
    fabric_grain=0°, piece_grain=90° →
    target = (0 - 90) % 360 = 270°.
    Rotating piece 270° CW turns its 90° grainline to 0° (fabric grain).
    """
    result = allowed_rotations("single", fabric_grain_deg=0.0, piece_grainline_deg=90.0)
    assert result == [270.0]


def test_single_no_rotation_needed():
    """piece_grain == fabric_grain → target = 0°."""
    result = allowed_rotations("single", fabric_grain_deg=0.0, piece_grainline_deg=0.0)
    assert result == [0.0]


def test_bi_returns_target_and_180():
    """fabric=0°, piece_grain=90° → target=270° → bi returns [270°, 90°]."""
    result = allowed_rotations("bi", fabric_grain_deg=0.0, piece_grainline_deg=90.0)
    assert set(result) == {270.0, 90.0}


def test_bi_wraparound():
    """fabric=0°, piece_grain=270° → target=90° → bi returns [90°, 270°]."""
    result = allowed_rotations("bi", fabric_grain_deg=0.0, piece_grainline_deg=270.0)
    assert set(result) == {90.0, 270.0}


def test_single_45_degree_fabric():
    """fabric=45°, piece_grain=90° → target=(45-90)%360=315°."""
    result = allowed_rotations("single", fabric_grain_deg=45.0, piece_grainline_deg=90.0)
    assert result == [315.0]


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown grain_mode"):
        allowed_rotations("diagonal", fabric_grain_deg=0.0, piece_grainline_deg=0.0)
```

- [ ] **Step 3: Run tests to confirm they fail**

```
engine\.venv\Scripts\pytest tests\unit\test_grain.py -v
```

Expected: all FAIL (module does not exist yet).

- [ ] **Step 4: Implement `grain.py`**

Create `engine/core/layout/grain.py`:

```python
from __future__ import annotations


def allowed_rotations(
    grain_mode: str,
    fabric_grain_deg: float,
    piece_grainline_deg: float | None,
) -> list[float]:
    """
    Return the rotation angles (degrees, CW) the heuristic may try for one piece.

    grain_mode:
      'none'   — free rotation, all 360 candidates in 1° steps
      'single' — piece grainline must align with fabric grain (one candidate)
      'bi'     — piece grainline may align or be 180° opposite (two candidates)

    If piece_grainline_deg is None (no grainline data in DXF), any mode returns
    all 360 candidates — no constraint without data.
    """
    if grain_mode == "none" or piece_grainline_deg is None:
        return list(range(360))

    target = (fabric_grain_deg - piece_grainline_deg) % 360

    if grain_mode == "single":
        return [target]
    elif grain_mode == "bi":
        return [target, (target + 180) % 360]
    else:
        raise ValueError(f"Unknown grain_mode: {grain_mode!r}")
```

- [ ] **Step 5: Run tests to confirm they all pass**

```
engine\.venv\Scripts\pytest tests\unit\test_grain.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```
git add engine/core/layout/__init__.py engine/core/layout/grain.py engine/tests/unit/test_grain.py
git commit -m "feat: add grain.py — allowed_rotations() enforces grain mode per piece"
```

---

## Task 2: `heuristic.py` — bbox strip-packing

**Files:**
- Create: `engine/core/layout/heuristic.py`
- Create: `engine/tests/unit/test_heuristic.py`

- [ ] **Step 1: Write failing tests for bbox mode**

Create `engine/tests/unit/test_heuristic.py`:

```python
import pytest
from core.models.piece import Piece, BoundingBox
from core.layout.heuristic import auto_layout_bbox, auto_layout_polygon, Placement


def _make_square(piece_id: str, size: float, grainline_deg: float | None = None) -> Piece:
    """Helper: square piece of given side length."""
    return Piece(
        id=piece_id,
        name=piece_id,
        polygon=[(0, 0), (size, 0), (size, size), (0, size)],
        area=size * size,
        bbox=BoundingBox(0, 0, size, size, size, size),
        is_valid=True,
        grainline_direction_deg=grainline_deg,
    )


def _make_rect(piece_id: str, w: float, h: float, grainline_deg: float | None = None) -> Piece:
    return Piece(
        id=piece_id,
        name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        grainline_direction_deg=grainline_deg,
    )


# --- bbox mode tests ---

def test_bbox_single_piece_placed():
    pieces = [_make_square("p0", 100)]
    placements, length, utilization = auto_layout_bbox(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 1
    assert placements[0].piece_id == "p0"
    assert placements[0].x >= 0
    assert placements[0].y >= 0


def test_bbox_three_equal_squares_single_shelf():
    """3 × 100mm squares should fit on one shelf in a 500mm fabric."""
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    placements, length, utilization = auto_layout_bbox(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 3
    ys = {pl.y for pl in placements}
    assert len(ys) == 1, "All pieces should be on the same shelf"


def test_bbox_pieces_overflow_to_new_shelf():
    """4 × 200mm squares in 500mm fabric: first 2 fit on shelf 1, next 2 on shelf 2."""
    pieces = [_make_square(f"p{i}", 200) for i in range(4)]
    placements, length, utilization = auto_layout_bbox(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 4
    ys = sorted({pl.y for pl in placements})
    assert len(ys) == 2, "Should span exactly 2 shelves"


def test_bbox_no_piece_exceeds_fabric_width():
    pieces = [_make_square(f"p{i}", 100) for i in range(5)]
    placements, length, _ = auto_layout_bbox(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    for pl in placements:
        piece = next(p for p in pieces if p.id == pl.piece_id)
        assert pl.x + piece.bbox.width <= 500 + 0.01


def test_bbox_piece_wider_than_fabric_raises():
    pieces = [_make_square("huge", 600)]
    with pytest.raises(ValueError, match="cannot fit"):
        auto_layout_bbox(pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0)


def test_bbox_single_grain_enforced():
    """piece_grain=270°, fabric=0°, single mode → all placements at rotation 270°."""
    pieces = [_make_rect(f"p{i}", 80, 120, grainline_deg=270.0) for i in range(3)]
    placements, _, _ = auto_layout_bbox(
        pieces, fabric_width_mm=800, grain_mode="single", fabric_grain_deg=0.0
    )
    for pl in placements:
        assert pl.rotation_deg == pytest.approx(270.0, abs=0.01)


def test_bbox_utilization_positive():
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    _, _, utilization = auto_layout_bbox(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert 0 < utilization <= 100
```

- [ ] **Step 2: Run to confirm all fail**

```
engine\.venv\Scripts\pytest tests\unit\test_heuristic.py -v
```

Expected: all FAIL (heuristic.py does not exist).

- [ ] **Step 3: Create `heuristic.py`**

Create `engine/core/layout/heuristic.py`:

```python
from __future__ import annotations

import math
from dataclasses import dataclass

import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon

from core.layout.grain import allowed_rotations
from core.models.piece import Piece

GAP = 10.0  # mm gap between pieces and from fabric edge


@dataclass
class Placement:
    piece_id: str
    x: float
    y: float
    rotation_deg: float


# ---------------------------------------------------------------------------
# Shared geometry helpers
# ---------------------------------------------------------------------------

def _rotated_bbox_dims(piece: Piece, rotation_deg: float) -> tuple[float, float]:
    """Return (width, height) of the axis-aligned bbox of the piece rotated CW by rotation_deg."""
    angle_rad = math.radians(rotation_deg)
    cos_a = abs(math.cos(angle_rad))
    sin_a = abs(math.sin(angle_rad))
    w = piece.bbox.width * cos_a + piece.bbox.height * sin_a
    h = piece.bbox.width * sin_a + piece.bbox.height * cos_a
    return w, h


def _placed_polygon(piece: Piece, x: float, y: float, rotation_deg: float) -> ShapelyPolygon:
    """Return the piece polygon rotated CW by rotation_deg and translated to (x, y)."""
    poly = ShapelyPolygon(piece.polygon)
    # Shapely rotate is CCW-positive; negate for CW convention
    rotated = shapely.affinity.rotate(poly, -rotation_deg, origin=(0, 0), use_radians=False)
    minx, miny = rotated.bounds[0], rotated.bounds[1]
    return shapely.affinity.translate(rotated, xoff=-minx + x, yoff=-miny + y)


def _polygon_dims(piece: Piece, rotation_deg: float) -> tuple[float, float]:
    """Return (width, height) from actual rotated polygon bounds."""
    poly = ShapelyPolygon(piece.polygon)
    rotated = shapely.affinity.rotate(poly, -rotation_deg, origin=(0, 0), use_radians=False)
    minx, miny, maxx, maxy = rotated.bounds
    return maxx - minx, maxy - miny


def _compute_metrics(
    placements: list[Placement],
    pieces: list[Piece],
    fabric_width_mm: float,
    dim_fn,
) -> tuple[float, float]:
    """Return (marker_length_mm, utilization_pct)."""
    if not placements:
        return 0.0, 0.0
    piece_map = {p.id: p for p in pieces}
    marker_length = max(
        pl.x + dim_fn(piece_map[pl.piece_id], pl.rotation_deg)[0]
        for pl in placements
    ) + GAP
    total_area = sum(p.area for p in pieces)
    utilization = round(total_area / (marker_length * fabric_width_mm) * 100, 2)
    return round(marker_length, 2), utilization


# ---------------------------------------------------------------------------
# Validation (shared)
# ---------------------------------------------------------------------------

def _validate_pieces_fit(pieces: list[Piece], fabric_width_mm: float, grain_mode: str, fabric_grain_deg: float, dim_fn) -> None:
    for piece in pieces:
        rotations = allowed_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg)
        min_w = min(dim_fn(piece, r)[0] for r in rotations)
        if min_w + 2 * GAP > fabric_width_mm:
            raise ValueError(
                f"Piece '{piece.name}' minimum width {min_w:.1f} mm cannot fit within "
                f"usable fabric width {fabric_width_mm - 2 * GAP:.1f} mm at any allowed rotation."
            )


# ---------------------------------------------------------------------------
# Strip-packing core (shared structure; dim_fn and fits_fn differ by mode)
# ---------------------------------------------------------------------------

def _strip_pack(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
    dim_fn,
    fits_fn,
) -> tuple[list[Placement], float, float]:
    sorted_pieces = sorted(pieces, key=lambda p: p.area, reverse=True)
    _validate_pieces_fit(sorted_pieces, fabric_width_mm, grain_mode, fabric_grain_deg, dim_fn)

    placements: list[Placement] = []
    shelf_y = GAP
    shelf_h = 0.0
    x_cursor = GAP

    def _best_rotation(piece: Piece, x: float, y: float) -> tuple[float, float, float] | None:
        """(rot, w, h) minimising h that fits at (x, y); None if nothing fits."""
        best: tuple[float, float, float] | None = None
        for rot in allowed_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg):
            w, h = dim_fn(piece, rot)
            if fits_fn(piece, x, y, rot, w, placements) and x + w + GAP <= fabric_width_mm:
                if best is None or h < best[2]:
                    best = (rot, w, h)
        return best

    def _best_rotation_new_shelf(piece: Piece) -> tuple[float, float, float]:
        """(rot, w, h) minimising h on a fresh shelf at x=GAP."""
        best: tuple[float, float, float] | None = None
        for rot in allowed_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg):
            w, h = dim_fn(piece, rot)
            if w + 2 * GAP <= fabric_width_mm:
                if best is None or h < best[2]:
                    best = (rot, w, h)
        return best  # type: ignore — validated above

    for piece in sorted_pieces:
        result = _best_rotation(piece, x_cursor, shelf_y)
        if result is None:
            shelf_y += shelf_h + GAP
            shelf_h = 0.0
            x_cursor = GAP
            result = _best_rotation_new_shelf(piece)

        rot, w, h = result
        placements.append(Placement(piece.id, round(x_cursor, 4), round(shelf_y, 4), rot))
        x_cursor += w + GAP
        shelf_h = max(shelf_h, h)

    marker_length, utilization = _compute_metrics(placements, pieces, fabric_width_mm, dim_fn)
    return placements, marker_length, utilization


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def auto_layout_bbox(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
) -> tuple[list[Placement], float, float]:
    """
    Strip-packing using axis-aligned bounding boxes.
    Fast; no polygon-level collision detection.
    Returns (placements, marker_length_mm, utilization_pct).
    Raises ValueError if any piece cannot fit at any allowed rotation.
    """
    def fits_bbox(piece, x, y, rot, w, placed):
        # Bbox non-overlap is guaranteed by the left-to-right cursor; no extra check needed.
        return True

    return _strip_pack(
        pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
        dim_fn=_rotated_bbox_dims,
        fits_fn=fits_bbox,
    )


def auto_layout_polygon(
    pieces: list[Piece],
    fabric_width_mm: float,
    grain_mode: str,
    fabric_grain_deg: float,
) -> tuple[list[Placement], float, float]:
    """
    Strip-packing using actual piece polygons for collision detection (Shapely).
    More accurate than bbox mode for irregular pieces; slower for free rotation.
    Returns (placements, marker_length_mm, utilization_pct).
    Raises ValueError if any piece cannot fit at any allowed rotation.
    """
    placed_polys: list[ShapelyPolygon] = []

    def fits_polygon(piece, x, y, rot, w, placed):
        candidate = _placed_polygon(piece, x, y, rot)
        if candidate.bounds[2] + GAP > fabric_width_mm:
            return False
        return not any(candidate.intersects(pp) for pp in placed_polys)

    def _strip_pack_polygon():
        sorted_pieces = sorted(pieces, key=lambda p: p.area, reverse=True)
        _validate_pieces_fit(sorted_pieces, fabric_width_mm, grain_mode, fabric_grain_deg, _polygon_dims)

        placements: list[Placement] = []
        shelf_y = GAP
        shelf_h = 0.0
        x_cursor = GAP

        def _best_rotation(piece, x, y):
            best = None
            for rot in allowed_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg):
                w, h = _polygon_dims(piece, rot)
                if fits_polygon(piece, x, y, rot, w, placements) and x + w + GAP <= fabric_width_mm:
                    if best is None or h < best[2]:
                        best = (rot, w, h)
            return best

        def _best_rotation_new_shelf(piece):
            best = None
            for rot in allowed_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg):
                w, h = _polygon_dims(piece, rot)
                if w + 2 * GAP <= fabric_width_mm:
                    if best is None or h < best[2]:
                        best = (rot, w, h)
            return best

        for piece in sorted_pieces:
            result = _best_rotation(piece, x_cursor, shelf_y)
            if result is None:
                shelf_y += shelf_h + GAP
                shelf_h = 0.0
                x_cursor = GAP
                result = _best_rotation_new_shelf(piece)

            rot, w, h = result
            placements.append(Placement(piece.id, round(x_cursor, 4), round(shelf_y, 4), rot))
            placed_polys.append(_placed_polygon(piece, x_cursor, shelf_y, rot))
            x_cursor += w + GAP
            shelf_h = max(shelf_h, h)

        return placements

    placements = _strip_pack_polygon()
    marker_length, utilization = _compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims)
    return placements, marker_length, utilization
```

- [ ] **Step 4: Run bbox tests to confirm they pass**

```
engine\.venv\Scripts\pytest tests\unit\test_heuristic.py -k "bbox" -v
```

Expected: all bbox tests PASS.

- [ ] **Step 5: Add polygon-mode tests**

Append to `engine/tests/unit/test_heuristic.py`:

```python
# --- polygon mode tests ---

def test_polygon_single_piece_placed():
    pieces = [_make_square("p0", 100)]
    placements, length, utilization = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 1
    assert length > 0
    assert utilization > 0


def test_polygon_three_squares_all_placed():
    pieces = [_make_square(f"p{i}", 100) for i in range(3)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=500, grain_mode="none", fabric_grain_deg=0.0
    )
    assert len(placements) == 3


def test_polygon_no_overlaps():
    """Placed polygons must not intersect each other."""
    pieces = [_make_rect(f"p{i}", 80 + i * 10, 120) for i in range(5)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=600, grain_mode="none", fabric_grain_deg=0.0
    )
    from shapely.geometry import Polygon as SP
    import shapely.affinity

    placed = []
    for pl in placements:
        piece = next(p for p in pieces if p.id == pl.piece_id)
        poly = SP(piece.polygon)
        rotated = shapely.affinity.rotate(poly, -pl.rotation_deg, origin=(0, 0))
        minx, miny = rotated.bounds[0], rotated.bounds[1]
        placed.append(shapely.affinity.translate(rotated, xoff=-minx + pl.x, yoff=-miny + pl.y))

    for i, a in enumerate(placed):
        for j, b in enumerate(placed):
            if i < j:
                assert not a.intersects(b), f"Pieces {i} and {j} overlap"


def test_polygon_grain_single_enforced():
    pieces = [_make_rect(f"p{i}", 80, 150, grainline_deg=270.0) for i in range(3)]
    placements, _, _ = auto_layout_polygon(
        pieces, fabric_width_mm=900, grain_mode="single", fabric_grain_deg=0.0
    )
    for pl in placements:
        assert pl.rotation_deg == pytest.approx(270.0, abs=0.01)
```

- [ ] **Step 6: Run all heuristic tests**

```
engine\.venv\Scripts\pytest tests\unit\test_heuristic.py -v
```

Expected: all PASS.

- [ ] **Step 7: Run the full test suite**

```
engine\.venv\Scripts\pytest tests\ -v
```

Expected: all pass.

- [ ] **Step 8: Update `__init__.py` to export heuristic symbols**

```python
# engine/core/layout/__init__.py
from core.layout.grain import allowed_rotations
from core.layout.heuristic import auto_layout_bbox, auto_layout_polygon, Placement

__all__ = ["allowed_rotations", "auto_layout_bbox", "auto_layout_polygon", "Placement"]
```

- [ ] **Step 9: Commit**

```
git add engine/core/layout/__init__.py engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git commit -m "feat: strip-packing heuristic in bbox and polygon modes with grain constraint enforcement"
```

---

## Task 3: `POST /auto-layout` endpoint

**Files:**
- Modify: `engine/api/main.py`

- [ ] **Step 1: Add the endpoint to `main.py`**

Add these imports at the top of `main.py` (after existing imports):

```python
from fastapi import Request
from core.layout.heuristic import auto_layout_bbox, auto_layout_polygon
from core.models.piece import BoundingBox, Piece as PieceModel
```

Add the endpoint after the `/import-dxf` route:

```python
@app.post("/auto-layout")
async def auto_layout_endpoint(request: Request) -> dict:
    """
    Run heuristic auto-layout on provided pieces.

    Request JSON:
    {
        "pieces": [...],           // Piece objects from /import-dxf
        "fabric_width_mm": 1500,
        "grain_mode": "none",      // "none" | "single" | "bi"
        "grain_direction_deg": 0,  // 0 | 45 | 90 | 135
        "fast_mode": false         // true = bbox mode; false = polygon mode
    }

    Response JSON:
    {
        "placements": [{"piece_id": "...", "x": 0, "y": 0, "rotation_deg": 0}],
        "marker_length_mm": 1234.5,
        "utilization_pct": 82.4
    }
    """
    body = await request.json()

    fabric_width_mm = float(body.get("fabric_width_mm", 1500))
    grain_mode = str(body.get("grain_mode", "none"))
    grain_direction_deg = float(body.get("grain_direction_deg", 0.0))
    fast_mode = bool(body.get("fast_mode", False))

    pieces_data = body.get("pieces", [])
    if not pieces_data:
        raise HTTPException(status_code=400, detail="No pieces provided")

    pieces: list[PieceModel] = []
    for d in pieces_data:
        bbox_d = d["bbox"]
        pieces.append(PieceModel(
            id=d["id"],
            name=d["name"],
            polygon=[(float(p[0]), float(p[1])) for p in d["polygon"]],
            area=float(d["area"]),
            bbox=BoundingBox(
                min_x=float(bbox_d["min_x"]),
                min_y=float(bbox_d["min_y"]),
                max_x=float(bbox_d["max_x"]),
                max_y=float(bbox_d["max_y"]),
                width=float(bbox_d["width"]),
                height=float(bbox_d["height"]),
            ),
            is_valid=bool(d["is_valid"]),
            validation_notes=list(d.get("validation_notes", [])),
            grainline_direction_deg=d.get("grainline_direction_deg"),
        ))

    try:
        if fast_mode:
            placements, marker_length, utilization = auto_layout_bbox(
                pieces, fabric_width_mm, grain_mode, grain_direction_deg
            )
        else:
            placements, marker_length, utilization = auto_layout_polygon(
                pieces, fabric_width_mm, grain_mode, grain_direction_deg
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "placements": [
            {"piece_id": pl.piece_id, "x": pl.x, "y": pl.y, "rotation_deg": pl.rotation_deg}
            for pl in placements
        ],
        "marker_length_mm": marker_length,
        "utilization_pct": utilization,
    }
```

- [ ] **Step 2: Start the engine and manually test the endpoint**

```bat
scripts\dev-engine.bat
```

In a second terminal:
```bash
curl -X POST http://127.0.0.1:8765/auto-layout \
  -H "Content-Type: application/json" \
  -d "{\"pieces\":[{\"id\":\"p0\",\"name\":\"FRONT\",\"polygon\":[[0,0],[100,0],[100,200],[0,200]],\"area\":20000,\"bbox\":{\"min_x\":0,\"min_y\":0,\"max_x\":100,\"max_y\":200,\"width\":100,\"height\":200},\"is_valid\":true,\"validation_notes\":[],\"grainline_direction_deg\":null}],\"fabric_width_mm\":500,\"grain_mode\":\"none\",\"grain_direction_deg\":0,\"fast_mode\":true}"
```

Expected: JSON response with 1 placement, positive `marker_length_mm`, positive `utilization_pct`.

- [ ] **Step 3: Run the full engine test suite**

```
engine\.venv\Scripts\pytest tests\ -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```
git add engine/api/main.py
git commit -m "feat: add POST /auto-layout endpoint (bbox + polygon modes, grain constraints)"
```

---

## Task 4: Frontend type additions

**Files:**
- Modify: `frontend/src/types/engine.ts`

- [ ] **Step 1: Add auto-layout types to `engine.ts`**

```typescript
// frontend/src/types/engine.ts — append after existing types

export type GrainMode = "none" | "single" | "bi";

export interface AutoLayoutPlacement {
  piece_id: string;
  x: number;
  y: number;
  rotation_deg: number;
}

export interface AutoLayoutResponse {
  placements: AutoLayoutPlacement[];
  marker_length_mm: number;
  utilization_pct: number;
}
```

- [ ] **Step 2: Check TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/types/engine.ts
git commit -m "feat: add GrainMode, AutoLayoutPlacement, AutoLayoutResponse to engine types"
```

---

## Task 5: Expose `setAllPlacements` from `usePlacements`

**Files:**
- Modify: `frontend/src/hooks/usePlacements.ts`

The auto-layout result replaces all placements at once. `usePlacements` needs to expose this.

- [ ] **Step 1: Add `setAllPlacements` to the hook return**

```typescript
// frontend/src/hooks/usePlacements.ts — full file

import { useState, useEffect, useCallback } from "react";
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";
import { computePlacements } from "../utils/placement";

export function usePlacements(pieces: Piece[]) {
  const [placements, setPlacements] = useState<Placement[]>(() =>
    computePlacements(pieces)
  );

  useEffect(() => {
    setPlacements(computePlacements(pieces));
  }, [pieces]);

  const updatePlacement = useCallback(
    (id: string, delta: Partial<Omit<Placement, "pieceId">>) => {
      setPlacements((prev) =>
        prev.map((p) => (p.pieceId === id ? { ...p, ...delta } : p))
      );
    },
    []
  );

  const setAllPlacements = useCallback((newPlacements: Placement[]) => {
    setPlacements(newPlacements);
  }, []);

  function resetPlacements() {
    setPlacements(computePlacements(pieces));
  }

  return { placements, updatePlacement, resetPlacements, setAllPlacements };
}
```

- [ ] **Step 2: Run frontend tests**

```bash
cd frontend && npm run test
```

Expected: all pass.

- [ ] **Step 3: Commit**

```
git add frontend/src/hooks/usePlacements.ts
git commit -m "feat: expose setAllPlacements from usePlacements for auto-layout result injection"
```

---

## Task 6: `useAutoLayout` hook

**Files:**
- Create: `frontend/src/hooks/useAutoLayout.ts`

- [ ] **Step 1: Create the hook**

```typescript
// frontend/src/hooks/useAutoLayout.ts

import { useState, useCallback } from "react";
import type { Piece, GrainMode, AutoLayoutResponse } from "../types/engine";

const ENGINE_URL = "http://127.0.0.1:8765";

export function useAutoLayout() {
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const runAutoLayout = useCallback(
    async (
      pieces: Piece[],
      fabricWidthMm: number,
      grainMode: GrainMode,
      grainDirectionDeg: number,
      fastMode: boolean
    ): Promise<AutoLayoutResponse | null> => {
      setStatus("loading");
      setErrorMessage(null);
      try {
        const res = await fetch(`${ENGINE_URL}/auto-layout`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            pieces,
            fabric_width_mm: fabricWidthMm,
            grain_mode: grainMode,
            grain_direction_deg: grainDirectionDeg,
            fast_mode: fastMode,
          }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
        }
        const data = (await res.json()) as AutoLayoutResponse;
        setStatus("idle");
        return data;
      } catch (e) {
        setStatus("error");
        setErrorMessage(e instanceof Error ? e.message : "Auto layout failed");
        return null;
      }
    },
    []
  );

  return { runAutoLayout, status, errorMessage };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/hooks/useAutoLayout.ts
git commit -m "feat: add useAutoLayout hook wrapping POST /auto-layout"
```

---

## Task 7: `GrainPanel` sidebar component

**Files:**
- Create: `frontend/src/components/sidebar/GrainPanel.tsx`

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/sidebar/GrainPanel.tsx

import type { GrainMode } from "../../types/engine";

interface GrainPanelProps {
  grainDirectionDeg: number;
  grainMode: GrainMode;
  fastMode: boolean;
  onGrainDirectionChange: (deg: number) => void;
  onGrainModeChange: (mode: GrainMode) => void;
  onFastModeChange: (enabled: boolean) => void;
}

const GRAIN_DIRECTIONS = [0, 45, 90, 135] as const;
const GRAIN_MODE_LABELS: Record<GrainMode, string> = {
  none: "None (free)",
  single: "Single direction",
  bi: "Bi-directional",
};

export function GrainPanel({
  grainDirectionDeg,
  grainMode,
  fastMode,
  onGrainDirectionChange,
  onGrainModeChange,
  onFastModeChange,
}: GrainPanelProps) {
  return (
    <div>
      <div>
        <div style={styles.label}>Grain Direction</div>
        <div style={styles.directionRow}>
          {GRAIN_DIRECTIONS.map((deg) => (
            <button
              key={deg}
              onClick={() => onGrainDirectionChange(deg)}
              style={{
                ...styles.dirBtn,
                background:
                  grainDirectionDeg === deg
                    ? "var(--color-primary, #3b82f6)"
                    : "var(--color-surface)",
                color: grainDirectionDeg === deg ? "#fff" : "var(--color-text)",
              }}
            >
              {deg}°
            </button>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        <div style={styles.label}>Grain Mode</div>
        {(["none", "single", "bi"] as const).map((mode) => (
          <label key={mode} style={styles.radioRow}>
            <input
              type="radio"
              name="grain-mode"
              checked={grainMode === mode}
              onChange={() => onGrainModeChange(mode)}
            />
            <span style={{ fontSize: 12 }}>{GRAIN_MODE_LABELS[mode]}</span>
          </label>
        ))}
      </div>

      <div style={{ marginTop: 10 }}>
        <label style={styles.checkRow}>
          <input
            type="checkbox"
            checked={fastMode}
            onChange={(e) => onFastModeChange(e.target.checked)}
          />
          <span style={{ fontSize: 12 }}>Fast mode (bbox)</span>
        </label>
      </div>
    </div>
  );
}

const styles = {
  label: {
    fontSize: 11,
    fontWeight: 600 as const,
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
    color: "var(--color-text-muted)",
    marginBottom: 4,
  },
  directionRow: {
    display: "flex",
    gap: 4,
  },
  dirBtn: {
    border: "1px solid var(--color-border)",
    padding: "2px 7px",
    fontSize: 11,
    cursor: "pointer",
    borderRadius: 3,
  },
  radioRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginTop: 4,
    cursor: "pointer",
  },
  checkRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    cursor: "pointer",
  },
} as const;
```

- [ ] **Step 2: Check TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/sidebar/GrainPanel.tsx
git commit -m "feat: add GrainPanel sidebar component (grain direction, mode, fast mode)"
```

---

## Task 8: Wire Auto Layout into `App.tsx`

**Files:**
- Modify: `frontend/src/app/App.tsx`

- [ ] **Step 1: Add imports**

At the top of `App.tsx`, add:

```typescript
import { useAutoLayout } from "../hooks/useAutoLayout";
import { GrainPanel } from "../components/sidebar/GrainPanel";
import type { GrainMode, AutoLayoutPlacement } from "../types/engine";
import type { Placement } from "../types/canvas";
```

- [ ] **Step 2: Add grain + auto-layout state and hooks inside `App()`**

After the existing `usePlacements` line:

```typescript
const { placements, updatePlacement, resetPlacements, setAllPlacements } = usePlacements(pieces);

const [grainDirectionDeg, setGrainDirectionDeg] = useState<number>(0);
const [grainMode, setGrainMode] = useState<GrainMode>("none");
const [fastMode, setFastMode] = useState<boolean>(false);

const { runAutoLayout, status: autoStatus, errorMessage: autoError } = useAutoLayout();
```

- [ ] **Step 3: Add the auto-layout handler**

After `onFileChange`, add:

```typescript
const handleAutoLayout = useCallback(async () => {
  if (pieces.length === 0) return;
  const result = await runAutoLayout(pieces, fabricWidthMm, grainMode, grainDirectionDeg, fastMode);
  if (result) {
    const mapped: Placement[] = result.placements.map((pl: AutoLayoutPlacement) => ({
      pieceId: pl.piece_id,
      x: pl.x,
      y: pl.y,
      rotationDeg: pl.rotation_deg,
    }));
    setAllPlacements(mapped);
    setStatusMessage(
      `Auto layout: ${result.placements.length} piece${result.placements.length !== 1 ? "s" : ""} · ` +
      `Marker: ${Math.round(result.marker_length_mm)} mm · ` +
      `Utilization: ${result.utilization_pct}%`
    );
  } else {
    setStatusMessage(`Auto layout failed: ${autoError ?? "unknown error"}`);
  }
}, [pieces, fabricWidthMm, grainMode, grainDirectionDeg, fastMode, runAutoLayout, setAllPlacements, autoError]);
```

- [ ] **Step 4: Add `GrainPanel` section and Auto Layout button to the sidebar JSX**

In the sidebar, add a new `<Section title="Grain">` between the Fabric and Layout sections:

```tsx
<Section title="Grain">
  <GrainPanel
    grainDirectionDeg={grainDirectionDeg}
    grainMode={grainMode}
    fastMode={fastMode}
    onGrainDirectionChange={setGrainDirectionDeg}
    onGrainModeChange={setGrainMode}
    onFastModeChange={setFastMode}
  />
</Section>
```

In the Layout section, after the Import DXF button, add:

```tsx
<button
  onClick={handleAutoLayout}
  disabled={pieces.length === 0 || autoStatus === "loading"}
  style={{ opacity: pieces.length === 0 ? 0.4 : 1 }}
>
  {autoStatus === "loading" ? "Running..." : "Auto Layout"}
</button>

<button
  onClick={resetPlacements}
  disabled={pieces.length === 0}
  style={{ fontSize: 11, opacity: pieces.length === 0 ? 0.4 : 1 }}
>
  Reset Layout
</button>
```

- [ ] **Step 5: Run TypeScript build to confirm no errors**

```bash
cd frontend && npm run build 2>&1 | head -30
```

Expected: builds cleanly.

- [ ] **Step 6: Start the full dev stack and test the golden path**

Terminal 1:
```bat
scripts\dev-engine.bat
```

Terminal 2:
```bash
cd desktop && cargo tauri dev
```

Test:
1. Import `examples/input/2_pieces_x_2_with_grainline.dxf` → confirm 4 pieces appear
2. Leave Grain Mode = None, click Auto Layout → all 4 pieces placed, status bar shows length + utilization
3. Set Grain Mode = Single direction, Grain Direction = 0° → click Auto Layout → all pieces at ~270° rotation (grainline aligned)
4. Enable Fast mode, click Auto Layout → runs faster, still places all pieces
5. Click Reset Layout → pieces return to initial row layout

- [ ] **Step 7: Run frontend tests**

```bash
cd frontend && npm run test
```

Expected: all pass.

- [ ] **Step 8: Commit**

```
git add frontend/src/app/App.tsx
git commit -m "feat: wire Auto Layout button, GrainPanel, and setAllPlacements into App"
```

---

## Final check

- [ ] **Run the complete engine test suite**

```
engine\.venv\Scripts\pytest tests\ -v
```

Expected: all pass.

- [ ] **Run the complete frontend test suite**

```bash
cd frontend && npm run test
```

Expected: all pass.

- [ ] **Self-review spec coverage checklist**
  - [x] `POST /auto-layout` endpoint → Task 3
  - [x] Strip-packing heuristic bbox mode → Task 2
  - [x] Strip-packing heuristic polygon mode → Task 2
  - [x] `grain.py` → Task 1
  - [x] Grain direction setting (0°/45°/90°/135°) → Task 7
  - [x] Grain mode selector (none/single/bi) → Task 7
  - [x] Fast mode toggle → Task 7
  - [x] Auto Layout button → Task 8
  - [x] Marker length + utilization in status bar → Task 8
  - [x] Reset Layout button → Task 8
  - [x] HTTP 400 when piece wider than fabric → Task 2 + Task 3
