# Pre-Phase 5 Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix quantity expansion, Y-axis orientation, and grainline parsing in the engine parser and normalizer so Phase 5 auto-layout has correct piece data to work with.

**Architecture:** Three bugs in `parser.py` and `normalize.py`; one data model extension. All changes are engine-side except one TypeScript type update. The 2×2 fixture (`examples/input/2_pieces_x_2_with_grainline.dxf`) is the acceptance test for all three fixes together.

**Tech Stack:** Python 3.11, ezdxf, Shapely, pytest · TypeScript (interface only)

**Worktree branch:** `pre-phase5-fixes/masonw/quantity-yflip-grainline`
**Worktree dir:** `.worktrees/pre-phase5-fixes/masonw/quantity-yflip-grainline`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `engine/core/models/piece.py` | Modify | Add `grainline_direction_deg` to `Piece`; add `grainline` to `RawPiece` |
| `engine/core/dxf/parser.py` | Modify | Add `_parse_quantity()`, `_extract_grainline()`; expand pieces by quantity |
| `engine/core/geometry/normalize.py` | Modify | Y-flip input coords; apply Y-flip+translate to grainline; compute angle |
| `engine/tests/unit/test_dxf_parser.py` | Modify | Add quantity + grainline tests; update any coordinate assertions |
| `engine/tests/unit/test_normalize.py` | Modify | Update Y-flip assertions; add grainline angle tests |
| `frontend/src/types/engine.ts` | Modify | Add `grainline_direction_deg: number \| null` to `Piece` |

---

## Task 1: Extend data models

**Files:**
- Modify: `engine/core/models/piece.py`
- Modify: `engine/core/dxf/parser.py` (RawPiece only)

No tests needed — pure data structure changes. These must land first so later tasks can reference the new fields.

- [ ] **Step 1: Add `grainline` to `RawPiece` in `parser.py`**

```python
# engine/core/dxf/parser.py  — replace the RawPiece dataclass

@dataclass
class RawPiece:
    """Intermediate representation of a piece outline before normalization."""
    layer: str
    points: list[tuple[float, float]]
    is_closed: bool
    grainline: tuple[tuple[float, float], tuple[float, float]] | None = None
    # grainline = ((start_x, start_y), (end_x, end_y)) in raw DXF coordinates
```

- [ ] **Step 2: Add `grainline_direction_deg` to `Piece` in `piece.py`**

```python
# engine/core/models/piece.py  — add field to Piece dataclass

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
    # None = no grainline LINE found on layer "7" in the DXF block for this piece
```

- [ ] **Step 3: Run existing tests to confirm they still pass (no logic changed yet)**

```
engine\.venv\Scripts\pytest tests\unit\ -v
```

Expected: all pass (data model additions are backward-compatible due to default values).

- [ ] **Step 4: Commit**

```
git add engine/core/models/piece.py engine/core/dxf/parser.py
git commit -m "feat: add grainline fields to RawPiece and Piece models"
```

---

## Task 2: Y-axis flip in normalize_piece()

**Files:**
- Modify: `engine/core/geometry/normalize.py`
- Modify: `engine/tests/unit/test_normalize.py`

DXF Y increases upward; canvas Y increases downward. Without flipping, all pieces render mirrored vertically.

- [ ] **Step 1: Read the existing normalize test file to identify what will break**

```
engine\.venv\Scripts\pytest tests\unit\test_normalize.py -v
```

Note which tests check specific polygon vertex coordinates — those will fail after the fix.

- [ ] **Step 2: Write a new failing test for correct Y-flip orientation**

Add to `engine/tests/unit/test_normalize.py`:

```python
def test_y_flip_triangle_orientation():
    """A triangle with positive DXF Y-coords should have Y-coords flipped after normalization."""
    # Triangle in DXF space (Y-up): tip at top
    raw = RawPiece(
        layer="test",
        points=[(0.0, 0.0), (50.0, 100.0), (100.0, 0.0)],
        is_closed=True,
    )
    piece = normalize_piece(raw, "p0")
    # After Y-flip: (0,0)→(0,0), (50,100)→(50,-100), (100,0)→(100,0)
    # min_y = -100 → translate yoff=+100
    # Expected coords: (0,100), (50,0), (100,100) — tip now at bottom (y=0)
    ys = [pt[1] for pt in piece.polygon]
    # The minimum y in the normalized polygon should be 0
    assert min(ys) == pytest.approx(0.0, abs=1e-3)
    # The tip (originally at y=100 in DXF) should now be at the minimum y
    # i.e., the DXF "high" point becomes the canvas "low" point
    tip_x = 50.0
    tip_point = next(pt for pt in piece.polygon if abs(pt[0] - tip_x) < 0.01)
    assert tip_point[1] == pytest.approx(0.0, abs=1e-3)
```

- [ ] **Step 3: Run to confirm it fails**

```
engine\.venv\Scripts\pytest tests\unit\test_normalize.py::test_y_flip_triangle_orientation -v
```

Expected: FAIL — tip is currently at y=100 (not flipped).

- [ ] **Step 4: Implement the Y-flip in `normalize.py`**

```python
# engine/core/geometry/normalize.py — full updated file

from __future__ import annotations

import math

import shapely.affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.validation import make_valid

from core.dxf.parser import RawPiece
from core.models.piece import BoundingBox, Piece


def normalize_piece(raw: RawPiece, piece_id: str) -> Piece:
    """
    Build a normalized Piece from a RawPiece.

    Steps:
    1. Flip Y (DXF Y-up → canvas Y-down).
    2. Build a Shapely Polygon.
    3. Repair invalid geometry via make_valid; take the largest sub-polygon if needed.
    4. Reject degenerate results (non-Polygon after repair).
    5. Translate to origin (min_x=0, min_y=0).
    6. Apply same Y-flip + translate to grainline; compute direction angle.
    7. Return populated Piece.

    Raises ValueError if the geometry is degenerate after repair.
    """
    if len(raw.points) < 3:
        raise ValueError(f"Piece '{raw.layer}' has fewer than 3 points")

    notes: list[str] = []

    # Flip Y: DXF uses Y-up; canvas uses Y-down.
    points = [(x, -y) for x, y in raw.points]
    polygon = Polygon(points)

    if not polygon.is_valid:
        repaired = make_valid(polygon)
        notes.append("self-intersection repaired with make_valid")

        if isinstance(repaired, Polygon):
            polygon = repaired
        elif isinstance(repaired, (MultiPolygon, GeometryCollection)):
            polys = [g for g in repaired.geoms if isinstance(g, Polygon) and not g.is_empty]
            if not polys:
                raise ValueError(
                    f"Piece '{raw.layer}' became degenerate after repair: {repaired.geom_type}"
                )
            polygon = max(polys, key=lambda g: g.area)
            notes.append(f"{repaired.geom_type} result: largest sub-polygon kept")
        else:
            raise ValueError(
                f"Piece '{raw.layer}' became degenerate after repair: {repaired.geom_type}"
            )

    if not isinstance(polygon, Polygon) or polygon.is_empty:
        raise ValueError(f"Piece '{raw.layer}' produced an empty or non-polygon geometry")

    # Translate so that min_x=0, min_y=0
    minx, miny, maxx, maxy = polygon.bounds
    polygon = shapely.affinity.translate(polygon, xoff=-minx, yoff=-miny)

    # Re-read bounds after translation (should be 0,0,width,height)
    _, _, width, height = polygon.bounds

    # Exterior ring without the closing duplicate point
    coords = list(polygon.exterior.coords)[:-1]

    bbox = BoundingBox(
        min_x=0.0,
        min_y=0.0,
        max_x=round(width, 6),
        max_y=round(height, 6),
        width=round(width, 6),
        height=round(height, 6),
    )

    # Grainline: apply same Y-flip and origin translate as the polygon.
    grainline_deg: float | None = None
    if raw.grainline is not None:
        (sx, sy), (ex, ey) = raw.grainline
        # Y-flip then translate by the same offset used for the polygon
        sx_n = sx - minx
        sy_n = (-sy) - miny
        ex_n = ex - minx
        ey_n = (-ey) - miny
        dx = ex_n - sx_n
        dy = ey_n - sy_n
        grainline_deg = round(math.degrees(math.atan2(dy, dx)) % 360, 6)

    return Piece(
        id=piece_id,
        name=raw.layer,
        polygon=[(round(x, 6), round(y, 6)) for x, y in coords],
        area=round(polygon.area, 6),
        bbox=bbox,
        is_valid=polygon.is_valid,
        validation_notes=notes,
        grainline_direction_deg=grainline_deg,
    )
```

- [ ] **Step 5: Run the new test to confirm it passes**

```
engine\.venv\Scripts\pytest tests\unit\test_normalize.py::test_y_flip_triangle_orientation -v
```

Expected: PASS.

- [ ] **Step 6: Run all normalize tests and fix any that fail due to Y-flip**

```
engine\.venv\Scripts\pytest tests\unit\test_normalize.py -v
```

Any test that checked specific vertex coordinates will now fail. For each failing test, recalculate expected coordinates by:
1. Multiply all input Y values by -1
2. Translate so min_x=0, min_y=0
3. Update the assertion with the corrected values

Tests checking only `bbox.width`, `bbox.height`, and `area` should still pass (these are rotation-invariant).

- [ ] **Step 7: Run all unit tests to catch any further regressions**

```
engine\.venv\Scripts\pytest tests\ -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```
git add engine/core/geometry/normalize.py engine/tests/unit/test_normalize.py
git commit -m "fix: flip Y-axis in normalize_piece so pieces render correctly (DXF Y-up → canvas Y-down)"
```

---

## Task 3: Quantity parsing and piece expansion

**Files:**
- Modify: `engine/core/dxf/parser.py`
- Modify: `engine/tests/unit/test_dxf_parser.py`

Each DXF block may contain a `TEXT` entity whose value starts with `Quantity:`. When N > 1, the block must produce N pieces named `{block} (1)` … `{block} (N)`.

- [ ] **Step 1: Write failing tests for quantity expansion**

Add to `engine/tests/unit/test_dxf_parser.py`:

```python
import io
import ezdxf
import pytest
from core.dxf.parser import parse_dxf, _parse_quantity


def _make_dxf_with_quantity(block_name: str, quantity: int, points=None) -> bytes:
    """Helper: create a minimal DXF with one block INSERT, given quantity TEXT."""
    if points is None:
        points = [(0, 0), (100, 0), (100, 100), (0, 100)]
    doc = ezdxf.new("R2010")
    blk = doc.blocks.new(block_name)
    blk.add_lwpolyline(points, close=True, dxfattribs={"layer": "1"})
    blk.add_text(f"Quantity: {quantity}", dxfattribs={"layer": "1", "insert": (0, 0), "height": 0})
    msp = doc.modelspace()
    msp.add_blockref(block_name, (0, 0))
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def test_quantity_1_produces_one_piece_no_suffix():
    data = _make_dxf_with_quantity("FRONT", 1)
    pieces = parse_dxf(data)
    assert len(pieces) == 1
    assert pieces[0].layer == "FRONT"


def test_quantity_2_produces_two_pieces_with_suffix():
    data = _make_dxf_with_quantity("FRONT", 2)
    pieces = parse_dxf(data)
    assert len(pieces) == 2
    assert pieces[0].layer == "FRONT (1)"
    assert pieces[1].layer == "FRONT (2)"


def test_quantity_missing_defaults_to_one():
    doc = ezdxf.new("R2010")
    blk = doc.blocks.new("BACK")
    blk.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True, dxfattribs={"layer": "1"})
    msp = doc.modelspace()
    msp.add_blockref("BACK", (0, 0))
    stream = io.StringIO()
    doc.write(stream)
    data = stream.getvalue().encode("utf-8")
    pieces = parse_dxf(data)
    assert len(pieces) == 1
    assert pieces[0].layer == "BACK"
```

- [ ] **Step 2: Run to confirm all three fail**

```
engine\.venv\Scripts\pytest tests\unit\test_dxf_parser.py::test_quantity_1_produces_one_piece_no_suffix tests\unit\test_dxf_parser.py::test_quantity_2_produces_two_pieces_with_suffix tests\unit\test_dxf_parser.py::test_quantity_missing_defaults_to_one -v
```

Expected: FAIL (quantity logic not implemented).

- [ ] **Step 3: Implement `_parse_quantity()` in `parser.py`**

Add this function after the `_collect_closed_polylines` function:

```python
def _parse_quantity(block) -> int:
    """Scan TEXT entities in a block for 'Quantity: N'; return N (default 1)."""
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

- [ ] **Step 4: Update `_parse_insert_based()` to expand by quantity**

Replace the piece-naming and append section in `_parse_insert_based()`:

```python
def _parse_insert_based(doc, msp) -> list[RawPiece]:
    result: list[RawPiece] = []
    name_counts: dict[str, int] = {}

    for entity in msp:
        if entity.dxftype() != "INSERT":
            continue

        block_name = entity.dxf.name
        if block_name.startswith("*"):
            continue

        try:
            block = doc.blocks[block_name]
        except KeyError:
            continue

        closed_polys = _collect_closed_polylines(block)
        if not closed_polys:
            continue

        count = name_counts.get(block_name, 0)
        name_counts[block_name] = count + 1
        base_name = block_name if count == 0 else f"{block_name}_{count}"

        quantity = _parse_quantity(block)
        best = max(closed_polys, key=_polygon_area)

        for i in range(quantity):
            piece_name = f"{base_name} ({i + 1})" if quantity > 1 else base_name
            result.append(RawPiece(layer=piece_name, points=best, is_closed=True))

    return result
```

- [ ] **Step 5: Run the three quantity tests to confirm they pass**

```
engine\.venv\Scripts\pytest tests\unit\test_dxf_parser.py::test_quantity_1_produces_one_piece_no_suffix tests\unit\test_dxf_parser.py::test_quantity_2_produces_two_pieces_with_suffix tests\unit\test_dxf_parser.py::test_quantity_missing_defaults_to_one -v
```

Expected: all PASS.

- [ ] **Step 6: Run all tests**

```
engine\.venv\Scripts\pytest tests\ -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```
git add engine/core/dxf/parser.py engine/tests/unit/test_dxf_parser.py
git commit -m "feat: expand pieces by DXF Quantity field; name duplicates '{name} (N)'"
```

---

## Task 4: Grainline extraction from DXF blocks

**Files:**
- Modify: `engine/core/dxf/parser.py`
- Modify: `engine/core/geometry/normalize.py` (grainline angle section only — already stubbed in Task 2)
- Modify: `engine/tests/unit/test_dxf_parser.py`
- Modify: `engine/tests/unit/test_normalize.py`

`LINE` entities on layer `"7"` inside a piece BLOCK are grainlines. The start→end vector defines the grain direction.

- [ ] **Step 1: Write failing parser test for grainline detection**

Add to `engine/tests/unit/test_dxf_parser.py`:

```python
def _make_dxf_with_grainline(
    block_name: str,
    piece_points: list,
    grain_start: tuple,
    grain_end: tuple,
) -> bytes:
    """Helper: DXF block with a piece polygon and a layer-7 LINE grainline."""
    doc = ezdxf.new("R2010")
    blk = doc.blocks.new(block_name)
    blk.add_lwpolyline(piece_points, close=True, dxfattribs={"layer": "1"})
    blk.add_line(grain_start, grain_end, dxfattribs={"layer": "7"})
    msp = doc.modelspace()
    msp.add_blockref(block_name, (0, 0))
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def test_grainline_extracted_from_layer_7():
    data = _make_dxf_with_grainline(
        "PIECE",
        [(0, 0), (100, 0), (100, 200), (0, 200)],
        grain_start=(50, 0),
        grain_end=(50, 100),
    )
    pieces = parse_dxf(data)
    assert len(pieces) == 1
    assert pieces[0].grainline is not None
    start, end = pieces[0].grainline
    assert start == pytest.approx((50.0, 0.0), abs=0.01)
    assert end == pytest.approx((50.0, 100.0), abs=0.01)


def test_grainline_absent_when_no_layer7_line():
    doc = ezdxf.new("R2010")
    blk = doc.blocks.new("NOLINE")
    blk.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True, dxfattribs={"layer": "1"})
    msp = doc.modelspace()
    msp.add_blockref("NOLINE", (0, 0))
    stream = io.StringIO()
    doc.write(stream)
    pieces = parse_dxf(stream.getvalue().encode("utf-8"))
    assert pieces[0].grainline is None
```

- [ ] **Step 2: Run to confirm both fail**

```
engine\.venv\Scripts\pytest tests\unit\test_dxf_parser.py::test_grainline_extracted_from_layer_7 tests\unit\test_dxf_parser.py::test_grainline_absent_when_no_layer7_line -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `_extract_grainline()` in `parser.py`**

Add after `_parse_quantity()`:

```python
def _extract_grainline(
    block,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Return (start, end) of the first LINE on layer '7' in the block, or None."""
    for entity in block:
        if entity.dxftype() == "LINE" and entity.dxf.layer == "7":
            start = (float(entity.dxf.start.x), float(entity.dxf.start.y))
            end = (float(entity.dxf.end.x), float(entity.dxf.end.y))
            return (start, end)
    return None
```

- [ ] **Step 4: Wire `_extract_grainline` into `_parse_insert_based()`**

Inside the loop in `_parse_insert_based()`, after `best = max(closed_polys, ...)`, add:

```python
        grainline = _extract_grainline(block)

        for i in range(quantity):
            piece_name = f"{base_name} ({i + 1})" if quantity > 1 else base_name
            result.append(RawPiece(layer=piece_name, points=best, is_closed=True, grainline=grainline))
```

- [ ] **Step 5: Run grainline parser tests to confirm they pass**

```
engine\.venv\Scripts\pytest tests\unit\test_dxf_parser.py::test_grainline_extracted_from_layer_7 tests\unit\test_dxf_parser.py::test_grainline_absent_when_no_layer7_line -v
```

Expected: PASS.

- [ ] **Step 6: Write failing normalize tests for grainline angle computation**

Add to `engine/tests/unit/test_normalize.py`:

```python
import math
from core.dxf.parser import RawPiece
from core.geometry.normalize import normalize_piece


def test_grainline_horizontal_gives_0_degrees():
    """A horizontal grainline (pointing right in DXF) → 0° in canvas space."""
    raw = RawPiece(
        layer="test",
        points=[(0.0, 0.0), (100.0, 0.0), (100.0, 200.0), (0.0, 200.0)],
        is_closed=True,
        grainline=((10.0, -50.0), (90.0, -50.0)),  # horizontal, both y same
    )
    piece = normalize_piece(raw, "p0")
    assert piece.grainline_direction_deg is not None
    assert piece.grainline_direction_deg == pytest.approx(0.0, abs=0.01)


def test_grainline_vertical_in_dxf_gives_270_degrees():
    """
    A vertical DXF grainline pointing upward (start_y < end_y in DXF Y-up space)
    becomes 270° in canvas Y-down space (pointing upward on screen).
    """
    raw = RawPiece(
        layer="test",
        points=[(0.0, -200.0), (100.0, -200.0), (100.0, 200.0), (0.0, 200.0)],
        is_closed=True,
        # Grainline in DXF: start lower, end higher (pointing UP in DXF Y-up)
        grainline=((50.0, -100.0), (50.0, 100.0)),
    )
    piece = normalize_piece(raw, "p0")
    assert piece.grainline_direction_deg is not None
    # After Y-flip: start_y=100, end_y=-100 → dy = -200 → atan2(-200,0) = -90° → 270°
    assert piece.grainline_direction_deg == pytest.approx(270.0, abs=0.01)


def test_grainline_absent_gives_none():
    raw = RawPiece(
        layer="test",
        points=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        is_closed=True,
        grainline=None,
    )
    piece = normalize_piece(raw, "p0")
    assert piece.grainline_direction_deg is None
```

- [ ] **Step 7: Run to confirm they fail**

```
engine\.venv\Scripts\pytest tests\unit\test_normalize.py::test_grainline_horizontal_gives_0_degrees tests\unit\test_normalize.py::test_grainline_vertical_in_dxf_gives_270_degrees tests\unit\test_normalize.py::test_grainline_absent_gives_none -v
```

Expected: FAIL (normalize.py's grainline section is already implemented in Task 2's code — these should actually pass if Task 2 was completed correctly). If they fail, check the grainline angle block in `normalize.py` matches the implementation in Task 2 Step 4.

- [ ] **Step 8: Run all tests**

```
engine\.venv\Scripts\pytest tests\ -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```
git add engine/core/dxf/parser.py engine/tests/unit/test_dxf_parser.py engine/tests/unit/test_normalize.py
git commit -m "feat: parse grainline from DXF layer-7 LINE; compute direction angle in normalize_piece"
```

---

## Task 5: Acceptance test with 2×2 fixture

**Files:**
- Modify: `engine/tests/unit/test_dxf_parser.py` (or a new integration test file)

Verify the full pipeline on `examples/input/2_pieces_x_2_with_grainline.dxf`.

- [ ] **Step 1: Write the acceptance test**

Add to `engine/tests/unit/test_dxf_parser.py`:

```python
import os
import dataclasses
from core.geometry.normalize import normalize_piece


def test_2_pieces_x_2_fixture_produces_4_pieces():
    fixture = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "examples", "input",
        "2_pieces_x_2_with_grainline.dxf"
    )
    with open(fixture, "rb") as f:
        data = f.read()
    raw_pieces = parse_dxf(data)
    assert len(raw_pieces) == 4, f"Expected 4 pieces, got {len(raw_pieces)}: {[p.layer for p in raw_pieces]}"


def test_2_pieces_x_2_fixture_naming():
    fixture = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "examples", "input",
        "2_pieces_x_2_with_grainline.dxf"
    )
    with open(fixture, "rb") as f:
        data = f.read()
    raw_pieces = parse_dxf(data)
    names = {p.layer for p in raw_pieces}
    assert "123.2.S (1)" in names
    assert "123.2.S (2)" in names
    assert "123.1.S (1)" in names
    assert "123.1.S (2)" in names


def test_2_pieces_x_2_fixture_grainlines_present():
    fixture = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "examples", "input",
        "2_pieces_x_2_with_grainline.dxf"
    )
    with open(fixture, "rb") as f:
        data = f.read()
    raw_pieces = parse_dxf(data)
    # All pieces should have grainline data (both DXF blocks have a layer-7 LINE)
    for p in raw_pieces:
        assert p.grainline is not None, f"Piece '{p.layer}' missing grainline"


def test_2_pieces_x_2_fixture_normalized_grainline_degrees():
    fixture = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "examples", "input",
        "2_pieces_x_2_with_grainline.dxf"
    )
    with open(fixture, "rb") as f:
        data = f.read()
    raw_pieces = parse_dxf(data)
    pieces = [normalize_piece(r, f"p{i}") for i, r in enumerate(raw_pieces)]
    # 123.2.S: vertical grainline (DXF layer-7 LINE is vertical) → 270° after Y-flip
    # 123.1.S: horizontal grainline → 0°
    for piece in pieces:
        assert piece.grainline_direction_deg is not None
    s_pieces = [p for p in pieces if "123.2.S" in p.name]
    l_pieces = [p for p in pieces if "123.1.S" in p.name]
    for p in s_pieces:
        assert p.grainline_direction_deg == pytest.approx(270.0, abs=1.0), \
            f"123.2.S expected ~270°, got {p.grainline_direction_deg}"
    for p in l_pieces:
        assert p.grainline_direction_deg == pytest.approx(0.0, abs=1.0), \
            f"123.1.S expected ~0°, got {p.grainline_direction_deg}"
```

- [ ] **Step 2: Run to confirm they pass**

```
engine\.venv\Scripts\pytest tests\unit\test_dxf_parser.py -k "fixture" -v
```

Expected: all PASS. If grainline degree assertions fail, the angles from the fixture may differ — check the computed value and update the tolerance if within 5°.

- [ ] **Step 3: Run the full test suite**

```
engine\.venv\Scripts\pytest tests\ -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```
git add engine/tests/unit/test_dxf_parser.py
git commit -m "test: add acceptance tests for 2×2 DXF fixture (quantity, naming, grainline)"
```

---

## Task 6: Frontend type update

**Files:**
- Modify: `frontend/src/types/engine.ts`

No frontend logic changes — only the TypeScript interface needs the new field so the compiler doesn't reject it.

- [ ] **Step 1: Add `grainline_direction_deg` to the `Piece` interface**

```typescript
// frontend/src/types/engine.ts — update Piece interface

export interface Piece {
  id: string;
  name: string;
  polygon: [number, number][];
  area: number;
  bbox: BoundingBox;
  is_valid: boolean;
  validation_notes: string[];
  grainline_direction_deg: number | null;
}
```

- [ ] **Step 2: Check TypeScript compiles**

```bash
cd frontend && npm run build
```

Expected: builds without errors. (The new field is nullable; existing code that doesn't read it will compile fine.)

- [ ] **Step 3: Run frontend tests**

```bash
cd frontend && npm run test
```

Expected: all pass.

- [ ] **Step 4: Commit**

```
git add frontend/src/types/engine.ts
git commit -m "feat: add grainline_direction_deg to frontend Piece type"
```

---

## Final check

- [ ] **Run the complete test suite one more time**

```
engine\.venv\Scripts\pytest tests\ -v
cd frontend && npm run test
```

Expected: all pass in both suites.

- [ ] **Manual smoke test** — start the engine and import `examples/input/2_pieces_x_2_with_grainline.dxf` in the app. Confirm:
  - 4 pieces are listed in the sidebar (not 2)
  - Pieces are named `123.2.S (1)`, `123.2.S (2)`, `123.1.S (1)`, `123.1.S (2)`
  - Piece shapes match the reference CAD orientation (not mirrored)
