# Phase 5 — Simple Auto Layout: Design Spec

**Date:** 2026-05-16
**Status:** Approved

---

## Overview

Phase 5 adds a one-click auto-layout feature that places all imported pieces onto the fabric using a strip-packing heuristic. The engine handles all placement logic; the frontend shows the result and reports marker length and utilization. Grainline constraints are enforced per user-configured grain mode.

---

## Scope

### In scope
- `POST /auto-layout` engine endpoint
- Strip-packing heuristic (bounding-box mode and polygon mode)
- Grain constraint enforcement (none / single direction / bi-directional)
- Fabric grain direction setting (0°, 45°, 90°, 135°)
- Global grain mode selector in UI
- Fast mode toggle (bbox vs polygon collision)
- Auto Layout button wired to endpoint
- Marker length + utilization display in status bar
- Unit tests for grain logic and heuristic

### Out of scope (future phases)
- Per-piece grain mode override in the UI
- Grain deviation tolerance (auto-layout places at exact allowed angles; tolerance is a manual-editing concern)
- Multi-size / quantity-per-piece support
- Fabric defect zones
- Mirrored / paired pieces
- NFP-based (No-Fit Polygon) exact placement

**Prerequisite:** Pre-Phase 5 fixes must be complete before Phase 5 starts. Those fixes add `grainline_direction_deg: float | None` to the `Piece` model (parsed from layer-7 `LINE` entities in DXF blocks). Phase 5 reads this field from each piece to compute allowed rotations.

---

## Grain constraint model

### Fabric settings (global)

| Setting | Values | Default |
|---|---|---|
| Grain direction | 0°, 45°, 90°, 135° | 0° |
| Grain mode | `none`, `single`, `bi` | `none` |
| Fast mode | boolean | `false` (polygon mode) |

### Allowed rotations per piece

Grain mode applies globally to all pieces. Per-piece allowed rotations are computed from the piece's own `grainline_direction_deg` (from DXF) and the fabric grain direction (user-set).

```
target_rotation = (fabric_grain_direction_deg - piece.grainline_direction_deg) % 360
```

| Grain mode | Piece has grainline? | Allowed rotations |
|---|---|---|
| `none` | either | 0° … 359° in 1° steps |
| `single` | yes | `[target_rotation]` |
| `single` | no (null) | 0° … 359° in 1° steps (no constraint without grainline data) |
| `bi` | yes | `[target_rotation, (target_rotation + 180) % 360]` |
| `bi` | no (null) | 0° … 359° in 1° steps |

`target_rotation` is the rotation needed to align the piece's grainline with the fabric's warp direction. For example: fabric grain = 0° (horizontal), piece grainline = 90° (vertical) → `target_rotation = (0 - 90) % 360 = 270°` — the piece must be rotated 270° so its vertical grainline becomes horizontal.

Grain mode `none` → free rotation search. Grain mode `single` / `bi` → strict enforcement for pieces that have grainline data; pieces without grainline data are treated as unconstrained.

---

## Engine

### New module: `engine/core/layout/`

```
engine/core/layout/
  __init__.py
  grain.py        — maps (grain_mode, grain_direction_deg) → list[float] of allowed rotations
  heuristic.py    — strip-packing in bbox mode and polygon mode
```

### `grain.py`

```python
def allowed_rotations(
    grain_mode: str,
    fabric_grain_deg: float,
    piece_grainline_deg: float | None,
) -> list[float]:
    """
    Return rotation angles (degrees) the heuristic may try for one piece.

    If grain_mode is 'none', or the piece has no grainline data, returns all
    360 degree candidates (1° steps). Otherwise derives the target rotation
    from the angle between the piece's grainline and the fabric grain direction.
    """
```

- `none` (any piece) → `list(range(360))`
- `piece_grainline_deg is None` (any mode) → `list(range(360))`
- `single` with grainline → `[int((fabric_grain_deg - piece_grainline_deg) % 360)]`
- `bi` with grainline → `[target, (target + 180) % 360]` where `target = int((fabric_grain_deg - piece_grainline_deg) % 360)`

### `heuristic.py`

**Algorithm (shared structure for both modes):**

1. Sort pieces by bounding-box area descending.
2. Maintain shelf list: each shelf has `y_offset`, `shelf_height`, `x_cursor`.
3. For each piece:
   a. Get allowed rotations from `grain.py`.
   b. For each rotation, compute the rotated shape (bbox or polygon).
   c. Find the rotation that fits in the current shelf with least height waste. If none fit, open a new shelf.
   d. Record placement `(x_cursor, shelf.y_offset, rotation_deg)`.
   e. Advance `x_cursor` by the rotated shape's width.
4. `marker_length_mm` = rightmost x extent across all placements.
5. `utilization_pct` = `sum(piece.area for all pieces) / (marker_length_mm × fabric_width_mm) × 100`.

**Fast mode (`fast_mode=True`):**
- Rotated shape = axis-aligned bounding box of the rotated polygon (pure math, no Shapely).
- Collision check = bounding box overlap.

**Default mode (`fast_mode=False`):**
- Rotated shape = Shapely `rotate(polygon, angle)`.
- Collision check = Shapely `intersects()` against all already-placed polygons.
- Piece width contribution = `rotated_polygon.bounds` width.

**Failure condition:** If `fabric_width_mm` is narrower than the minimum bounding dimension of any piece across all its allowed rotations, return HTTP 400 with a descriptive error listing the offending piece(s).

### New endpoint: `POST /auto-layout`

**Request body (JSON):**
```json
{
  "pieces": [ /* Piece objects as returned by /import-dxf */ ],
  "fabric_width_mm": 1500,
  "grain_mode": "none",
  "grain_direction_deg": 0,
  "fast_mode": false
}
```

**Response (JSON):**
```json
{
  "placements": [
    { "piece_id": "piece_0", "x": 10.0, "y": 10.0, "rotation_deg": 0.0 }
  ],
  "marker_length_mm": 3240.0,
  "utilization_pct": 84.2
}
```

---

## Frontend

### New component: `GrainPanel`

File: `frontend/src/components/sidebar/GrainPanel.tsx`

Renders inside the sidebar between the Fabric section and the Layout section. Contains:

- **Grain direction**: button group `[0°] [45°] [90°] [135°]`, default 0°.
- **Grain mode**: radio group `○ None  ○ Single direction  ○ Bi-directional`, default None.
- **Fast mode**: checkbox `☐ Fast mode (bbox)`, default unchecked.

Props: `grainDir`, `grainMode`, `fastMode`, and their respective `onChange` handlers. All state lives in `App.tsx`.

### New hook: `useAutoLayout`

File: `frontend/src/hooks/useAutoLayout.ts`

```typescript
interface AutoLayoutResult {
  placements: { piece_id: string; x: number; y: number; rotation_deg: number }[];
  marker_length_mm: number;
  utilization_pct: number;
}

function useAutoLayout(): {
  runAutoLayout: (
    pieces: Piece[],
    fabricWidthMm: number,
    grainMode: GrainMode,
    grainDirectionDeg: number,
    fastMode: boolean
  ) => Promise<AutoLayoutResult | null>;
  status: 'idle' | 'loading' | 'error';
  errorMessage: string | null;
}
```

On success, the caller (`App.tsx`) maps the response `placements` to the `Placement[]` type used by `usePlacements` and calls `setPlacements()`.

### `App.tsx` changes

- Add state: `grainMode`, `grainDirectionDeg`, `fastMode`.
- Add `GrainPanel` to the sidebar between Fabric and Layout sections.
- Add `Auto Layout` button in the Layout section (below Import DXF).
- On Auto Layout click: call `runAutoLayout(...)`, then on success call `setPlacements(mapped)` and update status bar.
- Status bar after auto layout: `{N} pieces · Marker: {length} mm · Utilization: {pct}%`

### Type additions: `engine.ts`

```typescript
export type GrainMode = 'none' | 'single' | 'bi';

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

---

## Data flow

```
User sets: fabric width, grain direction, grain mode, fast mode
User clicks "Auto Layout"
  → useAutoLayout.runAutoLayout(pieces, fabricWidthMm, grainMode, grainDirectionDeg, fastMode)
  → POST /auto-layout (JSON body)
  → engine: grain.allowed_rotations() → heuristic.auto_layout()
  → response: { placements, marker_length_mm, utilization_pct }
  → App.tsx: setPlacements(mapped placements)
  → status bar updated with metrics
```

---

## Error handling

| Case | Behavior |
|---|---|
| Piece wider than fabric at all allowed rotations | HTTP 400, lists offending piece(s) |
| No pieces imported | Auto Layout button disabled |
| Engine unreachable | `useAutoLayout` returns `null`, status bar shows error |
| `fast_mode=false` with many pieces + free rotation | Expected slowness; no timeout in Phase 5 |

---

## Tests

### Engine

| Test | What it checks |
|---|---|
| `test_grain_none` | `allowed_rotations('none', 0, 90)` returns 360 values, 0–359 |
| `test_grain_no_grainline_data` | `allowed_rotations('single', 0, None)` returns 360 values (unconstrained) |
| `test_grain_single_align` | fabric=0°, piece_grain=90° → `allowed_rotations('single', 0, 90)` returns `[270]` |
| `test_grain_bi_align` | fabric=0°, piece_grain=90° → `allowed_rotations('bi', 0, 90)` returns `[270, 90]` |
| `test_grain_bi_wraparound` | fabric=0°, piece_grain=270° → `allowed_rotations('bi', 0, 270)` returns `[90, 270]` |
| `test_bbox_pack_trivial` | 3 equal squares, fabric = 3× square width → single shelf, 100% utilization |
| `test_bbox_pack_new_shelf` | pieces too wide to share a shelf → two shelves, all pieces placed |
| `test_polygon_pack_trivial` | same as bbox trivial, using polygon mode |
| `test_single_grain_enforced` | pieces with `grainline_direction_deg=90`, fabric=0° → all placements have `rotation_deg=270` |
| `test_piece_wider_than_fabric` | returns HTTP 400 for an impossible piece |

### Frontend

- `useAutoLayout` returns mapped placements on a mocked successful response.
- `GrainPanel` renders correct button/radio states and calls `onChange` handlers.

---

## Files changed / created

| File | Action |
|---|---|
| `engine/core/layout/__init__.py` | Create |
| `engine/core/layout/grain.py` | Create |
| `engine/core/layout/heuristic.py` | Create |
| `engine/api/main.py` | Edit — add `POST /auto-layout` |
| `engine/tests/unit/test_grain.py` | Create |
| `engine/tests/unit/test_heuristic.py` | Create |
| `frontend/src/types/engine.ts` | Edit — add `GrainMode`, `AutoLayoutPlacement`, `AutoLayoutResponse` |
| `frontend/src/hooks/useAutoLayout.ts` | Create |
| `frontend/src/components/sidebar/GrainPanel.tsx` | Create |
| `frontend/src/app/App.tsx` | Edit — grain state, GrainPanel, Auto Layout button, metrics |
