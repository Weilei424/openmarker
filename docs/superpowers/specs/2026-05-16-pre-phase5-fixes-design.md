# Pre-Phase 5 Fixes: Design Spec

**Date:** 2026-05-16
**Status:** Approved

---

## Overview

Three bugs must be fixed before Phase 5 auto-layout work begins. All are in the parser and normalizer. A fourth task (grainline parsing) is not a bug but is foundational infrastructure that Phase 5 requires.

---

## Fix 1 — Quantity expansion

### Problem

The `Quantity: N` value in each block's TEXT entities is ignored. A DXF with two blocks each having `Quantity: 2` produces 2 pieces; it should produce 4.

### Root cause

`_parse_insert_based()` in `engine/core/dxf/parser.py` iterates INSERT entities in modelspace (there is one INSERT per unique block, not one per quantity). It never reads the `Quantity:` TEXT inside the block.

### Fix

In `_parse_insert_based()` and `_parse_flat()`, after collecting closed polylines for a block, scan the block's TEXT entities for a line matching `Quantity: {N}`. Parse N (default 1 if absent or unparseable). Emit N copies of the `RawPiece`, each with a unique name.

### Naming convention

| Quantity | Names emitted |
|---|---|
| 1 | `{block_name}` (unchanged) |
| > 1 | `{block_name} (1)`, `{block_name} (2)`, … `{block_name} (N)` |

### Implementation detail

Extract quantity from TEXT entities using a simple string prefix check:

```python
def _parse_quantity(block) -> int:
    for entity in block:
        if entity.dxftype() == "TEXT":
            text = entity.dxf.text.strip()
            if text.startswith("Quantity:"):
                try:
                    return max(1, int(text.split(":", 1)[1].strip()))
                except ValueError:
                    pass
    return 1
```

Call after collecting closed polylines. Emit quantity copies of the piece into result.

---

## Fix 2 — Y-axis coordinate flip

### Problem

Pieces appear vertically mirrored compared to how they look in the source CAD software.

### Root cause

DXF uses a right-handed coordinate system where Y increases **upward**. The canvas (Konva) uses a screen coordinate system where Y increases **downward**. `normalize_piece()` in `engine/core/geometry/normalize.py` translates to origin but never inverts Y.

### Fix

In `normalize_piece()`, after receiving `raw.points`, multiply every Y coordinate by -1 before building the Shapely polygon. The rest of the normalization (validity repair, translate to origin) then operates on correctly-oriented data.

```python
# Before building Shapely polygon:
points = [(x, -y) for x, y in raw.points]
polygon = Polygon(points)
```

This fix affects all DXF files. Existing fixtures and tests must be updated to reflect the corrected orientation.

**Impact on grainline**: Grainline coordinates must also have Y flipped (see Fix 4 below). Apply `(x, -y)` to both start and end points of the grainline line before computing the direction angle.

---

## Fix 3 — Grainline parsing

### Background

Not a bug, but required before Phase 5. Phase 5's auto-layout needs per-piece grainline direction to compute allowed rotations. The format is now confirmed from the DXF file.

### DXF grainline format

Inside each pattern piece BLOCK, a `LINE` entity on **layer 7** is the grainline:

```
0
LINE
8
7          ← layer 7
10
<start_x>
20
<start_y>
11
<end_x>
21
<end_y>
```

Rules:
- Only `LINE` on layer `7` inside a BLOCK is a grainline candidate.
- At most one grainline line per block is expected; if multiple exist, use the first.
- `LINE` entities in the ENTITIES section (outside any BLOCK) are not grainlines.
- No arrowhead entities exist in the DXF; the arrow is rendered by the CAD viewer, not stored.

### Changes to `RawPiece`

Add an optional grainline field:

```python
@dataclass
class RawPiece:
    layer: str
    points: list[tuple[float, float]]
    is_closed: bool
    grainline: tuple[tuple[float, float], tuple[float, float]] | None = None
    # grainline = ((start_x, start_y), (end_x, end_y)) in raw DXF coordinates
```

### Changes to parser

In `_parse_insert_based()`, after collecting closed polylines for a block, also scan for a `LINE` entity on layer `7`:

```python
def _extract_grainline(block) -> tuple[tuple[float, float], tuple[float, float]] | None:
    for entity in block:
        if entity.dxftype() == "LINE" and entity.dxf.layer == "7":
            start = (float(entity.dxf.start.x), float(entity.dxf.start.y))
            end   = (float(entity.dxf.end.x),   float(entity.dxf.end.y))
            return (start, end)
    return None
```

Assign the result to `RawPiece.grainline`.

### Changes to `Piece` model

Add `grainline_direction_deg` to `engine/core/models/piece.py`:

```python
@dataclass
class Piece:
    id: str
    name: str
    polygon: list[tuple[float, float]]
    area: float
    bbox: BoundingBox
    is_valid: bool
    validation_notes: list[str] = field(default_factory=list)
    grainline_direction_deg: float | None = None
    # None = no grainline entity found in the DXF block for this piece
```

### Changes to `normalize_piece()`

After Y-flipping `raw.points` (Fix 2), also Y-flip `raw.grainline` if present. Then:

1. Translate grainline coordinates by the same offset used to translate the polygon to origin.
2. Compute direction angle: `atan2(end_y_norm - start_y_norm, end_x_norm - start_x_norm)` in degrees.
3. Store as `grainline_direction_deg` (range: -180 to 180 or 0 to 360 — use `% 360` for consistency).

If `raw.grainline is None`, set `Piece.grainline_direction_deg = None`.

### Frontend type update

Add to `frontend/src/types/engine.ts`:

```typescript
export interface Piece {
  // ... existing fields ...
  grainline_direction_deg: number | null;
}
```

---

## Files changed

| File | Change |
|---|---|
| `engine/core/dxf/parser.py` | Add `_parse_quantity()`, `_extract_grainline()`; update `_parse_insert_based()` and `_parse_flat()` |
| `engine/core/models/piece.py` | Add `grainline_direction_deg: float | None` to `Piece` |
| `engine/core/geometry/normalize.py` | Y-flip all input Y coords; apply Y-flip + translate to grainline; compute `grainline_direction_deg` |
| `frontend/src/types/engine.ts` | Add `grainline_direction_deg: number | null` to `Piece` interface |
| `engine/tests/unit/test_dxf_parser.py` | Update existing tests for Y-flip; add quantity expansion tests; add grainline detection tests |
| `engine/tests/unit/test_normalize.py` | Update Y-flip behavior; add grainline coordinate transform test |

---

## Tests

| Test | What it checks |
|---|---|
| `test_quantity_2_produces_2_pieces` | Block with `Quantity: 2` emits 2 RawPieces named `{name} (1)`, `{name} (2)` |
| `test_quantity_1_produces_1_piece` | Block with `Quantity: 1` (or absent) emits 1 RawPiece with no suffix |
| `test_quantity_missing_defaults_to_1` | No Quantity TEXT → 1 piece, no suffix |
| `test_y_flip_triangle` | Triangle with positive Y DXF coords normalizes with Y inverted |
| `test_grainline_extracted` | Block with LINE on layer 7 → `RawPiece.grainline` is set correctly |
| `test_grainline_absent` | Block with no layer-7 LINE → `RawPiece.grainline is None` |
| `test_grainline_direction_deg_vertical` | Vertical grainline → `grainline_direction_deg` ≈ 90 (or 270 after Y-flip) |
| `test_grainline_direction_deg_horizontal` | Horizontal grainline → `grainline_direction_deg` ≈ 0 |
| `test_2_pieces_x_2_fixture` | Import `examples/input/2_pieces_x_2_with_grainline.dxf` → 4 pieces total; both have `grainline_direction_deg` set |
