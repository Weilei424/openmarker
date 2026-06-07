# Separation Engine — Phase 0 + 1 (sparrow evaluation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether the Rust SOTA nester `sparrow` produces a valid, grain-respecting marker that beats GA's 11412 mm by ≥3% on our workloads — a go/no-go gate before building the Phase 2 GUI integration.

**Architecture:** Build `sparrow` (external Rust binary). Add a Python harness in the engine that converts our `Piece` list → `jagua-rs` JSON (grain-aligned pre-rotation + `{0°,180°}` orientations, no flip), shells out to `sparrow`, parses the solution back into our `Placement` convention, and validates (grain / overlap / width) before measuring marker length with the engine's own `_compute_metrics`. Translation+discrete-rotation only, so grain is preserved by construction.

**Tech Stack:** Python 3.11 (engine), Shapely (geometry), `sparrow` + `jagua-rs` (Rust, MIT/MPL-2.0), `subprocess`.

**Worktree:** all work happens in `D:\openmarker\.worktrees\separation-engine` on branch `feat/separation-engine`. Commits within the worktree are authorized for this feature; do NOT push.

**Spec:** `docs/superpowers/specs/2026-06-07-separation-engine-design.md` (on `main`).

**Gate (binding):** `sample_2.dxf × 10` (fabric 1651 mm, bi-grain @90°) → valid marker **≤ 11070 mm** within ≤ 600 s. Miss → stop, document, do NOT build Phase 2.

**Engine helpers reused** (all in `engine/core/layout/heuristic.py` unless noted):
`EDGE_GAP` (=10.0), `Placement(piece_id, x, y, rotation_deg)`, `_placed_polygon(piece, x, y, rot)`, `_polygon_dims(piece, rot)`, `_compute_metrics(placements, pieces, fabric_w, dim_fn)`, `_has_area_overlap(a, b, eps=0.5)`, `_layout_rotations(grain_mode, fabric_grain_deg, piece_grainline_deg)`; `FABRIC_GRAIN_DEG` (=90.0) in `engine/core/layout/grain.py`. Workload loading mirrors `engine/tests/bench_ga.py::_load_workload`.

---

## File Structure

- `engine/eval/__init__.py` — new package for the (throwaway-ish) evaluation harness, kept out of `core/` so it never ships.
- `engine/eval/sparrow_io.py` — pure functions: `pieces_to_jagua(pieces, fabric_width_mm) -> dict` and `jagua_solution_to_placements(solution, pieces, prerotations) -> list[Placement]`. No subprocess, no I/O → unit-testable.
- `engine/eval/sparrow_runner.py` — `run_sparrow(instance_json_path, budget_s, seed) -> dict` (subprocess wrapper) + `evaluate(pieces, fabric_width_mm, budget_s) -> EvalResult` (glue: convert → run → parse → validate → metrics).
- `engine/eval/validate.py` — `validate_layout(placements, pieces, fabric_width_mm) -> list[str]` (grain ∈ allowed, no overlap, within width).
- `engine/tests/test_sparrow_io.py` — unit tests for conversion + round-trip parsing.
- `engine/tests/test_sparrow_validate.py` — unit tests for the validator.
- `engine/tests/bench_sparrow.py` — manual measurement harness (not pytest), prints the quality-vs-time table and the gate verdict.
- `docs/superpowers/notes/2026-06-07-jagua-schema.md` — Phase 0 schema findings (the contract Phase 1 code depends on).
- `tools/` (gitignored) — local clone + release build of `sparrow`.

---

## Task 0: Worktree environment setup

**Files:** none committed (environment only); add `tools/` to `.gitignore`.

- [ ] **Step 1: Create the engine venv in the worktree**

Run (from the worktree root `D:\openmarker\.worktrees\separation-engine`):
```
scripts\setup-engine.bat
```
Expected: `engine\.venv\` created, dependencies installed. (If the script assumes a fixed path, fall back to `python -m venv engine\.venv` then `engine\.venv\Scripts\python -m pip install -r engine\requirements.txt`.)

- [ ] **Step 2: Copy the DXF fixtures into the worktree**

The fixtures are gitignored and absent in a fresh worktree.
Run:
```
robocopy D:\openmarker\examples\input .\examples\input sample_2.dxf sample_3.dxf sample_4.dxf
```
Expected: the three files exist under `.\examples\input\`. Verify: `Test-Path .\examples\input\sample_2.dxf` → True.

- [ ] **Step 3: Clone and build sparrow**

Run:
```
git clone https://github.com/JeroenGar/sparrow tools\sparrow
cd tools\sparrow
cargo build --release
```
Expected: `tools\sparrow\target\release\sparrow.exe` exists. Requires Rust ≥ 1.86 (the Tauri shell already provides cargo).

- [ ] **Step 4: Smoke-run sparrow on its bundled example**

Run (from `tools\sparrow`):
```
cargo run --release -- -i data\input\swim.json -t 10
```
Expected: exits 0; an `output\final_swim.json` (and `.svg`) is produced. Inspect that a solution JSON exists — this confirms the binary + output path conventions before we depend on them.

- [ ] **Step 5: Ignore the tools dir and commit the gitignore**

Add `tools/` to `.gitignore` (worktree copy), then:
```
git add .gitignore
git commit -m "chore: ignore tools/ (local sparrow build) for separation eval

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 1 (Phase 0 — GATE): Document the jagua-rs input/output schema

**Files:**
- Create: `docs/superpowers/notes/2026-06-07-jagua-schema.md`

This task produces the contract that Tasks 3–4 depend on. No code.

- [ ] **Step 1: Inspect the example instance and the solution output**

Read `tools\sparrow\data\input\swim.json` (the input schema) and the `output\final_swim.json` produced in Task 0 Step 4 (the solution schema). Cross-reference the jagua-rs rustdoc (https://jeroengar.github.io/jagua-rs/jagua_rs/) for field meanings.

- [ ] **Step 2: Answer and record these questions in the notes file**

Write `docs/superpowers/notes/2026-06-07-jagua-schema.md` answering, with the exact JSON field names quoted:
  1. **Container/strip:** how is a fixed-width, variable-length strip specified? (field names, units)
  2. **Item shape:** how is each item's polygon given (vertex array? key name?), and how is its **demand/quantity** (number of copies) set?
  3. **Orientation (CRITICAL):** can each item restrict allowed rotations to a discrete set `{0, 180}`? Exact field name and value shape. If only *continuous* or a *global* set is supported, note that.
  4. **Flip:** is mirroring ever applied, and can it be disabled? Exact field/flag.
  5. **Solution output:** for each placed item, what transform is reported (rotation in degrees/radians? translation origin? does the translation place a reference point, a centroid, or the polygon's first vertex?).
  6. **Coordinate convention:** y-up or y-down? origin location?

- [ ] **Step 3: GATE decision**

If `{0,180}` discrete orientations + flip-disabled are expressible (directly, or via the planned reduction: pre-rotate each piece to grain-aligned, then global `{0,180}`, no flip) → record **GO** and proceed.

If NOT expressible → record **NO-GO** with the specific limitation, list the fallback options (fork `jagua-rs` (MPL-2.0) to add an orientation constraint; or Python overlap-min reimplementation), and **STOP the plan here** — surface to the user. Do not start Task 2+.

- [ ] **Step 4: Commit the notes**

```
git add docs/superpowers/notes/2026-06-07-jagua-schema.md
git commit -m "docs(eval): jagua-rs schema notes + grain-feasibility GO/NO-GO

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2 (Phase 0 — GATE): Toy grain-feasibility run

**Files:**
- Create: `engine/eval/__init__.py` (empty), `engine/eval/_toy_grain.py`

Confirms sparrow *actually* honors `{0,180}` + no-flip on a hand-built instance (not just that the schema claims to).

- [ ] **Step 1: Write a 3-rectangle toy instance using the Task 1 schema**

Create `engine/eval/_toy_grain.py` that writes a `jagua-rs` JSON with a 200-wide strip and three distinct rectangles (e.g. 50×120, 80×40, 30×30), each with allowed orientations `{0,180}` and flip disabled, using the exact field names from `docs/superpowers/notes/2026-06-07-jagua-schema.md`. Print the path it wrote.

- [ ] **Step 2: Run sparrow on the toy and dump the solution transforms**

Run:
```
engine\.venv\Scripts\python engine\eval\_toy_grain.py
tools\sparrow\target\release\sparrow.exe -i <toy_path> -t 5
```
Read `output\final_*.json`. Print each item's rotation.

- [ ] **Step 3: Assert grain respected**

Verify every reported rotation ∈ `{0, 180}` (modulo the schema's angle unit) and no item is mirrored. Record the observed rotations in the schema notes file.

Expected: all rotations are 0 or 180, no mirroring. If any item is at 90/270 or mirrored → the orientation constraint is NOT enforced → **NO-GO**, surface to the user, stop.

- [ ] **Step 4: Commit**

```
git add engine/eval/__init__.py engine/eval/_toy_grain.py docs/superpowers/notes/2026-06-07-jagua-schema.md
git commit -m "test(eval): toy instance confirms sparrow honors {0,180} + no-flip

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3 (Phase 1): pieces → jagua-rs JSON converter (TDD)

**Files:**
- Create: `engine/eval/sparrow_io.py`
- Test: `engine/tests/test_sparrow_io.py`

The pre-rotation reduction: for each piece, `prerot = _layout_rotations("single", FABRIC_GRAIN_DEG, piece.grainline_direction_deg)[0]` is the grain-aligned angle (the `target` in `_layout_rotations`). Pre-rotate the piece polygon by `prerot`; emit it to jagua with allowed orientations `{0,180}` for grained pieces (`{0,90,180,270}` for pieces whose `grainline_direction_deg is None`). The effective engine rotation of an item that sparrow places at local angle `r` is `(prerot + r) % 360`.

- [ ] **Step 1: Write the failing test for pre-rotation + structure**

```python
# engine/tests/test_sparrow_io.py
import math
from core.models.piece import Piece, BoundingBox
from core.layout.grain import FABRIC_GRAIN_DEG
from eval.sparrow_io import pieces_to_jagua, prerotation_for

def _square(pid, grain_deg):
    poly = [(0,0),(100,0),(100,100),(0,100)]
    return Piece(id=pid, name=pid, polygon=poly, area=10000.0,
                 bbox=BoundingBox(0,0,100,100,100,100), is_valid=True,
                 grainline_direction_deg=grain_deg)

def test_prerotation_aligns_grain_to_fabric():
    # piece grainline at 0°, fabric grain 90° → target 90°
    p = _square("piece_0", 0.0)
    assert math.isclose(prerotation_for(p) % 360, (FABRIC_GRAIN_DEG - 0.0) % 360)

def test_converter_emits_one_item_per_distinct_piece_with_demand():
    pieces = [_square("piece_0__c0", 0.0), _square("piece_0__c1", 0.0)]
    inst = pieces_to_jagua(pieces, fabric_width_mm=1651.0)
    # two copies of the same base shape → demand 2 (grouping by polygon+prerot)
    items = inst["items"] if "items" in inst else inst["Items"]  # adjust to Task 1 schema
    assert sum(it.get("demand", it.get("Demand", 1)) for it in items) == 2

def test_grained_piece_has_two_orientations():
    inst = pieces_to_jagua([_square("piece_0__c0", 0.0)], fabric_width_mm=1651.0)
    item = (inst.get("items") or inst.get("Items"))[0]
    # exact key from Task 1 schema notes; values represent {0,180}
    allowed = item["allowed_orientations"]  # ADJUST per Task 1
    assert sorted(allowed) == [0, 180]
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `engine\.venv\Scripts\pytest engine\tests\test_sparrow_io.py -v`
Expected: FAIL (`ModuleNotFoundError: eval.sparrow_io` / `prerotation_for` undefined).

- [ ] **Step 3: Implement `prerotation_for` and `pieces_to_jagua`**

```python
# engine/eval/sparrow_io.py
from __future__ import annotations
import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon
from core.models.piece import Piece
from core.layout.grain import FABRIC_GRAIN_DEG
from core.layout.heuristic import _layout_rotations, EDGE_GAP

def prerotation_for(piece: Piece) -> float:
    """Grain-aligned angle: rotating the piece by this puts its grainline on the
    fabric warp, so sparrow only needs a global {0,180} (bi) set afterwards."""
    return _layout_rotations("single", FABRIC_GRAIN_DEG, piece.grainline_direction_deg)[0]

def _prerotated_ring(piece: Piece, prerot: float) -> list[tuple[float, float]]:
    poly = ShapelyPolygon(piece.polygon)
    rot = shapely.affinity.rotate(poly, prerot, origin=(0, 0), use_radians=False)
    minx, miny = rot.bounds[0], rot.bounds[1]
    rot = shapely.affinity.translate(rot, xoff=-minx, yoff=-miny)  # origin-normalize
    return [(float(x), float(y)) for x, y in rot.exterior.coords[:-1]]

def pieces_to_jagua(pieces: list[Piece], fabric_width_mm: float) -> dict:
    """Build a jagua-rs strip-packing instance. NOTE: the outer key names below
    follow docs/superpowers/notes/2026-06-07-jagua-schema.md (Task 1) — adjust
    the literal keys/units if Task 1 found different ones."""
    # group identical (base shape, prerot) so demand = copies
    groups: dict[tuple, dict] = {}
    for p in pieces:
        prerot = prerotation_for(p)
        ring = _prerotated_ring(p, prerot)
        key = (round(prerot, 3), tuple((round(x, 3), round(y, 3)) for x, y in ring))
        g = groups.get(key)
        if g is None:
            grained = p.grainline_direction_deg is not None
            orientations = [0, 180] if grained else [0, 90, 180, 270]
            groups[key] = {
                "shape": [list(v) for v in ring],     # ADJUST key per Task 1
                "demand": 0,
                "allowed_orientations": orientations,  # ADJUST key per Task 1
                "prerot": prerot,                      # internal bookkeeping (strip before emit)
            }
            g = groups[key]
        g["demand"] += 1
    items = []
    prerot_index = []  # parallel: prerot per emitted item, for the parser
    for g in groups.values():
        prerot_index.append(g.pop("prerot"))
        items.append(g)
    return {
        "strip": {"width": fabric_width_mm - 2 * EDGE_GAP},  # ADJUST key per Task 1
        "items": items,                                       # ADJUST key per Task 1
        "_prerotations": prerot_index,                        # internal; stripped before writing JSON
    }
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `engine\.venv\Scripts\pytest engine\tests\test_sparrow_io.py -v`
Expected: PASS. (If a key name assertion fails, reconcile the test + impl with the Task 1 schema notes — the schema is the source of truth.)

- [ ] **Step 5: Commit**

```
git add engine/eval/sparrow_io.py engine/tests/test_sparrow_io.py
git commit -m "feat(eval): pieces -> jagua-rs instance converter (grain pre-rotation)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4 (Phase 1): sparrow solution → engine placements (TDD)

**Files:**
- Modify: `engine/eval/sparrow_io.py`
- Test: `engine/tests/test_sparrow_io.py`

For each placed item, sparrow reports a local rotation `r` and a translation. Effective engine rotation = `(prerot + r) % 360`. We reconstruct the final placed polygon with `_placed_polygon`-style logic and read its rotated-bbox top-left as `Placement.x/y`. The exact mapping from sparrow's translation to a top-left depends on Task 1 Step 2 question 5/6 (what point the translation places, y-up vs y-down) — implement per those notes.

- [ ] **Step 1: Write the failing round-trip test**

```python
# add to engine/tests/test_sparrow_io.py
from eval.sparrow_io import jagua_solution_to_placements
from core.layout.heuristic import _placed_polygon

def test_roundtrip_known_placement():
    # one square, grainline 0° (prerot 90°). Simulate a solution that places the
    # single item at local rotation 0 and a known translation; assert we recover a
    # Placement whose reconstructed polygon bbox matches.
    p = _square("piece_0__c0", 0.0)
    inst = pieces_to_jagua([p], 1651.0)
    prerots = inst["_prerotations"]
    # minimal fake solution in the Task 1 output shape:
    solution = {"placements": [{"item_index": 0, "rotation": 0, "x": 10.0, "y": 10.0}]}  # ADJUST per Task 1
    placements = jagua_solution_to_placements(solution, [p], prerots)
    assert len(placements) == 1
    eff = placements[0].rotation_deg
    assert eff % 360 == (prerots[0] + 0) % 360
    poly = _placed_polygon(p, placements[0].x, placements[0].y, eff)
    assert poly.bounds[0] >= 10.0 - 1.0 and poly.bounds[1] >= 10.0 - 1.0
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `engine\.venv\Scripts\pytest engine\tests\test_sparrow_io.py::test_roundtrip_known_placement -v`
Expected: FAIL (`jagua_solution_to_placements` undefined).

- [ ] **Step 3: Implement the parser**

```python
# add to engine/eval/sparrow_io.py
from core.layout.heuristic import Placement, _placed_polygon

def jagua_solution_to_placements(solution: dict, pieces: list[Piece],
                                 prerotations: list[float]) -> list[Placement]:
    """Map sparrow's per-item transforms back to engine Placements.

    Field access follows the Task 1 output schema; adjust the literal keys and the
    translation->top-left mapping (y-up vs y-down, reference point) to the notes.
    `pieces` here is one representative Piece per emitted item (same order as the
    converter's items / prerotations)."""
    placements: list[Placement] = []
    for placed in solution["placements"]:          # ADJUST key per Task 1
        idx = placed["item_index"]                 # ADJUST key per Task 1
        local_rot = float(placed["rotation"])      # ADJUST unit per Task 1 (deg vs rad)
        eff_rot = (prerotations[idx] + local_rot) % 360
        piece = pieces[idx]
        # Build the polygon at eff_rot, then translate so its rotated-bbox min
        # corner lands where sparrow placed it. _placed_polygon already aligns the
        # rotated bbox min to (x, y); convert sparrow's translation to that (x, y)
        # per the Task 1 coordinate notes:
        x, y = _sparrow_xy_to_topleft(placed, piece, eff_rot)  # ADJUST per Task 1
        placements.append(Placement(piece.id, x, y, eff_rot))
    return placements

def _sparrow_xy_to_topleft(placed: dict, piece: Piece, eff_rot: float) -> tuple[float, float]:
    """Translate sparrow's reported position to the engine's 'min corner of the
    rotated bbox' convention. Implement exactly per Task 1 Step 2 Q5/Q6.
    Default assumption (verify!): sparrow reports the placed polygon's own
    coordinate-space origin; compute the rotated polygon and offset so its bbox
    min matches the reported translation."""
    import shapely.affinity
    from shapely.geometry import Polygon as ShapelyPolygon
    poly = ShapelyPolygon(piece.polygon)
    rot = shapely.affinity.rotate(poly, eff_rot, origin=(0, 0), use_radians=False)
    minx, miny = rot.bounds[0], rot.bounds[1]
    return float(placed["x"] - minx), float(placed["y"] - miny)  # ADJUST per Task 1
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `engine\.venv\Scripts\pytest engine\tests\test_sparrow_io.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```
git add engine/eval/sparrow_io.py engine/tests/test_sparrow_io.py
git commit -m "feat(eval): parse sparrow solution into engine Placements

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5 (Phase 1): validator + metric (TDD)

**Files:**
- Create: `engine/eval/validate.py`
- Test: `engine/tests/test_sparrow_validate.py`

- [ ] **Step 1: Write the failing tests**

```python
# engine/tests/test_sparrow_validate.py
from core.models.piece import Piece, BoundingBox
from core.layout.heuristic import Placement
from eval.validate import validate_layout

def _square(pid):
    return Piece(id=pid, name=pid, polygon=[(0,0),(100,0),(100,100),(0,100)],
                 area=10000.0, bbox=BoundingBox(0,0,100,100,100,100),
                 is_valid=True, grainline_direction_deg=0.0)

def test_valid_layout_has_no_issues():
    pieces = [_square("a"), _square("b")]
    pls = [Placement("a", 10, 10, 0.0), Placement("b", 200, 10, 0.0)]
    assert validate_layout(pls, pieces, 1651.0) == []

def test_overlap_is_flagged():
    pieces = [_square("a"), _square("b")]
    pls = [Placement("a", 10, 10, 0.0), Placement("b", 50, 10, 0.0)]  # overlap
    issues = validate_layout(pls, pieces, 1651.0)
    assert any("overlap" in s for s in issues)

def test_out_of_width_is_flagged():
    pieces = [_square("a")]
    pls = [Placement("a", 1600, 10, 0.0)]  # exceeds 1651-10 usable
    issues = validate_layout(pls, pieces, 1651.0)
    assert any("width" in s for s in issues)

def test_off_grain_rotation_is_flagged():
    pieces = [_square("a")]  # grained → allowed {90, 270} after fabric@90? see note
    pls = [Placement("a", 10, 10, 45.0)]  # 45° is never grain-valid
    issues = validate_layout(pls, pieces, 1651.0)
    assert any("grain" in s for s in issues)
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `engine\.venv\Scripts\pytest engine\tests\test_sparrow_validate.py -v`
Expected: FAIL (`eval.validate` missing).

- [ ] **Step 3: Implement the validator**

```python
# engine/eval/validate.py
from __future__ import annotations
from core.models.piece import Piece
from core.layout.heuristic import (
    EDGE_GAP, Placement, _placed_polygon, _has_area_overlap,
)
from core.layout.grain import FABRIC_GRAIN_DEG
from core.layout.heuristic import _layout_rotations

def validate_layout(placements: list[Placement], pieces: list[Piece],
                    fabric_width_mm: float) -> list[str]:
    issues: list[str] = []
    pm = {p.id: p for p in pieces}
    polys = []
    for pl in placements:
        piece = pm[pl.piece_id]
        # grain: rotation must be one allowed by the piece's grain set (bi)
        allowed = {round(a % 360, 3) for a in
                   _layout_rotations("bi", FABRIC_GRAIN_DEG, piece.grainline_direction_deg)}
        if round(pl.rotation_deg % 360, 3) not in allowed:
            issues.append(f"grain: {pl.piece_id} at {pl.rotation_deg}° not in {sorted(allowed)}")
        poly = _placed_polygon(piece, pl.x, pl.y, pl.rotation_deg)
        b = poly.bounds
        if b[0] < EDGE_GAP - 1e-3 or b[2] > fabric_width_mm - EDGE_GAP + 1e-3 or b[1] < EDGE_GAP - 1e-3:
            issues.append(f"width: {pl.piece_id} outside usable strip")
        polys.append(poly)
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            bi, bj = polys[i].bounds, polys[j].bounds
            if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                continue
            if _has_area_overlap(polys[i], polys[j]):
                issues.append(f"overlap: {placements[i].piece_id} & {placements[j].piece_id}")
    return issues
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `engine\.venv\Scripts\pytest engine\tests\test_sparrow_validate.py -v`
Expected: PASS. (If `test_off_grain_rotation` mismatches the grain math, align the test's expected angle with `_layout_rotations` output for fabric@90, grainline 0 — the implementation is the source of truth.)

- [ ] **Step 5: Commit**

```
git add engine/eval/validate.py engine/tests/test_sparrow_validate.py
git commit -m "feat(eval): layout validator (grain / overlap / width)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6 (Phase 1): runner + measurement harness

**Files:**
- Create: `engine/eval/sparrow_runner.py`, `engine/tests/bench_sparrow.py`

- [ ] **Step 1: Implement the subprocess runner + glue**

```python
# engine/eval/sparrow_runner.py
from __future__ import annotations
import json, os, subprocess, tempfile, time
from dataclasses import dataclass
from core.models.piece import Piece
from core.layout.heuristic import _compute_metrics, _polygon_dims
from eval.sparrow_io import pieces_to_jagua, jagua_solution_to_placements
from eval.validate import validate_layout

SPARROW_EXE = os.environ.get("SPARROW_EXE",
    os.path.join("tools", "sparrow", "target", "release", "sparrow.exe"))

@dataclass
class EvalResult:
    marker: float
    util: float
    placed: int
    issues: list[str]
    seconds: float

def run_sparrow(instance_path: str, out_dir: str, budget_s: float, seed: int = 42) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run([SPARROW_EXE, "-i", instance_path, "-t", str(int(budget_s)), "-s", str(seed)],
                   cwd=out_dir, check=True)  # ADJUST output flag per Task 1/Task 0 Step 4
    finals = [f for f in os.listdir(os.path.join(out_dir, "output")) if f.startswith("final_") and f.endswith(".json")]
    with open(os.path.join(out_dir, "output", finals[0]), "r", encoding="utf-8") as fh:
        return json.load(fh)

def evaluate(pieces: list[Piece], fabric_width_mm: float, budget_s: float, seed: int = 42) -> EvalResult:
    inst = pieces_to_jagua(pieces, fabric_width_mm)
    prerots = inst.pop("_prerotations")
    reps = _representatives(pieces)  # one Piece per emitted item, same order as items
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as td:
        ipath = os.path.join(td, "instance.json")
        with open(ipath, "w", encoding="utf-8") as fh:
            json.dump(inst, fh)
        solution = run_sparrow(ipath, td, budget_s, seed)
    dt = time.perf_counter() - t0
    placements = jagua_solution_to_placements(solution, _expand(reps, solution), prerots)
    issues = validate_layout(placements, pieces, fabric_width_mm)
    marker, util = _compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims)
    return EvalResult(marker, util, len(placements), issues, dt)
```

Note: `_representatives` / `_expand` map jagua's per-item demand back to individual `Piece` copies for placement reconstruction; implement them alongside, grouping exactly as `pieces_to_jagua` did (same key). Keep the grouping key in one shared helper to stay DRY.

- [ ] **Step 2: Write the measurement harness**

```python
# engine/tests/bench_sparrow.py  (manual; not pytest)
import os, sys
HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, os.path.join(HERE, "..", ".."))
from dataclasses import replace
from core.dxf import parse_dxf
from core.geometry import normalize_piece
from eval.sparrow_runner import evaluate

FABRIC, GA_REF, GATE = 1651.0, 11412.5, 11070.0

def load(name, copies):
    raw = parse_dxf(open(os.path.join(HERE, "..", "..", "examples", "input", name), "rb").read())
    base = []
    for i, r in enumerate(raw):
        try: base.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError: pass
    return [replace(b, id=f"{b.id}__c{c}") for c in range(copies) for b in base]

def main():
    pieces = load("sample_2.dxf", 10)
    print(f"workload: {len(pieces)} pieces", flush=True)
    for budget in (60, 180, 420, 600):
        r = evaluate(pieces, FABRIC, budget)
        ok = "VALID" if not r.issues else f"INVALID: {r.issues[:2]}"
        gate = "GATE-PASS" if (not r.issues and r.marker <= GATE) else "below-gate"
        print(f"t={budget:>4}s  L={r.marker:8.1f}  U={r.util:5.2f}%  placed={r.placed}  {ok}  {gate}", flush=True)
    print(f"reference: GA={GA_REF}  gate(<=3%)={GATE}", flush=True)

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the harness on sample_2 ×10**

Run:
```
engine\.venv\Scripts\python engine\tests\bench_sparrow.py
```
Expected: a table of `(budget, marker, util, placed, VALID?, gate)` rows. Every row must be `VALID` (grain/overlap/width clean). Capture the output.

- [ ] **Step 4: Commit the harness**

```
git add engine/eval/sparrow_runner.py engine/tests/bench_sparrow.py
git commit -m "feat(eval): sparrow runner + measurement harness

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7 (Phase 1 — GATE): record results + go/no-go

**Files:**
- Modify (on `main`, per the docs-to-main convention): `docs/planning/PERFORMANCE.md`

- [ ] **Step 1: Extend the harness to sample_3/4 and capture the full table**

Run `bench_sparrow.py` for `sample_3.dxf ×6` and `sample_4.dxf ×6` (add them to `main()` or parametrize). Record marker + validity + runtime for each.

- [ ] **Step 2: Write the PERFORMANCE.md §6 entry (on main)**

Switch to the main checkout (`D:\openmarker`) and add a `2026-06-07` (cont.) §6 entry: What (sparrow eval), Result (the quality-vs-time table + validity), and the **GATE decision**:
  - `sample_2 ×10` valid marker **≤ 11070 mm** → **GO**: Phase 2 (GUI sidecar integration) is justified; write its plan next.
  - Otherwise → **NO-GO**: separation does not beat GA on garment pieces; stop. Note runtimes either way (the production-speed signal).
Also flip the §5.B "Overlap-and-separate + GLS" row from "candidate" to the measured outcome.

- [ ] **Step 3: Commit the findings to main**

```
git add docs/planning/PERFORMANCE.md
git commit -m "docs(perf): sparrow separation eval results + Phase-2 go/no-go

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 4: Report the verdict to the user**

Summarize the gate result and the recommended next step (write the Phase 2 plan, or stop). Do not start Phase 2 without a fresh decision.

---

## Notes for the executor

- **The gates are real.** Stop at Task 1 Step 3 or Task 2 Step 3 if grain isn't enforceable; stop at Task 7 if the ≥3% gate is missed. Surface to the user rather than pushing on.
- **`# ADJUST per Task 1` markers** are the only deliberately-deferred bits — they're filled from the schema notes Task 1 produces, because the exact `jagua-rs` field names/units are discovered, not assumed. Everything engine-side is concrete.
- **Determinism:** sparrow is seeded (`-s`); use a fixed seed (42) so reruns and the eventual cache are reproducible.
- **DRY:** the demand-grouping key in `pieces_to_jagua` and the `_representatives`/`_expand` reconstruction must use one shared helper.
