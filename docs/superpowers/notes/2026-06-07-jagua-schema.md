# jagua-rs / sparrow JSON schema notes (Phase 0, Task 1)

Source: `jagua-rs 0.7.2` (`...\probs\spp\io\ext_repr.rs`), `sparrow` (`src/util/io.rs`),
and an observed run on `data/input/swim.json`. This is the contract the Phase 1
converter (Task 3) and parser (Task 4) depend on.

## GRAIN GATE: **GO** ✅

- Items carry a first-class **`allowed_orientations: [f32]`** (degrees). The swim
  benchmark itself uses `[0.0, 180.0]`.
- There is **no flip/mirror field** anywhere in `ExtItem` → mirroring is never
  applied. Handedness is preserved.
- **Proven on output:** with input `allowed_orientations: [0, 180]`, every placed
  item in `output/final_swim.json` has `transformation.rotation ∈ {0.0, -180.0}` —
  no 90/270, no reflection. sparrow honors the discrete orientation set.

## Input schema (`ExtSPInstance`)

```json
{
  "name": "string",
  "strip_height": 1631.0,          // FIXED strip dimension (f32). SEE AXIS MAPPING.
  "items": [
    {
      "id": 0,                      // int; sparrow output references this as item_id
      "demand": 10,                 // u64 = number of copies of this item
      "allowed_orientations": [0.0, 180.0],   // [f32] degrees; our grain set
      "shape": {
        "type": "simple_polygon",
        "data": [[x, y], [x, y], ...]          // exterior ring; no closing dup needed
      }
    }
  ]
}
```

## Output schema (`output/final_<name>.json`)

Wrapper = `{ name, items, solution: ExtSPSolution }`:

```json
"solution": {
  "strip_width": 5959.0,           // the MINIMIZED dimension (= our marker length). SEE AXIS MAPPING.
  "layout": {
    "container_id": 1169831941,
    "placed_items": [
      { "item_id": 9, "transformation": { "rotation": -180.0, "translation": [322.33, 26.94] } },
      ...
    ]
  },
  "density": 0.81,
  "run_time_sec": 10
}
```

- `placed_items[]` has one entry **per copy** (demand expanded). `item_id` ties back
  to the input item's `id`.
- `transformation.rotation` is **signed degrees** (e.g. `-180`). Normalize with
  `rot % 360` (so `-180 → 180`) to compare against our grain set.
- `transformation.translation = [x, y]` positions the item's own coordinate origin
  (the untransformed shape's origin), NOT a bbox corner — the parser rotates the
  shape by `rotation` then applies this translation, then derives our placement
  convention (min corner of the rotated bbox) from the resulting polygon.

## AXIS MAPPING (the key converter subtlety)

jagua-rs SPP **fixes `strip_height` (Y) and minimizes `strip_width` (X)** (confirmed
in `optimizer/explore.rs` + `compress.rs`: they shrink `strip_width`). Our engine
does the **opposite**: it fixes fabric width (X) and minimizes marker length (Y).

So the converter must rotate the whole problem 90° to align axes:
- our **fabric usable width** (`1651 - 2*EDGE_GAP = 1631`) → jagua **`strip_height`**
- our **marker length** (minimized) → jagua **`strip_width`** (the result)
- each piece's polygon is rotated 90° into jagua's frame; its grain-valid angles
  (`_layout_rotations` → `[target, target+180]`) shift by that same 90° in the
  `allowed_orientations` we emit.
- the parser rotates the returned `(rotation, translation)` back by -90° into our
  engine frame before building `Placement`s.

**Backstop:** `validate_layout` (Task 5) re-checks grain ∈ allowed, no-overlap, and
within-width in OUR frame after the round-trip — so an axis/orientation mapping bug
surfaces as a validation failure, not a silently-bad marker.

## CLI

```
sparrow.exe -i <input.json> -t <global_seconds> [-e <explore_s>] [-c <compress_s>] [-s <seed>] [-x]
```

- Writes `output/final_<name>.json` (+ `.svg` + `sols_<name>/` snapshots) **relative
  to the current working directory**. Run it from a scratch dir; read
  `<cwd>/output/final_<name>.json`.
- `-s <seed>` makes runs reproducible (needed for caching).
- `-i` also accepts a prior solution JSON for warm-starting (not needed for the eval).

## Confirmed environment

- sparrow built at `tools/sparrow/target/release/sparrow.exe` (Rust 1.89).
- Smoke run on `swim.json -t 10` succeeded; final strip_width ≈ 5959.
