# Architecture Notes

## Stack

| Layer | Tech | Version |
|-------|------|---------|
| Desktop shell | Tauri | 2.x |
| Frontend | React + TypeScript + Konva | React 18, TS 5, Konva 9 |
| Frontend build | Vite + Vitest | Vite 5, Vitest 1 |
| Engine | Python + FastAPI | Python 3.11, FastAPI 0.115 |
| DXF parsing | ezdxf | 1.3.4 |
| Geometry | Shapely + Pyclipper | Shapely 2.0.6, Pyclipper 1.4.0 |

## Key Decisions

**Local HTTP between UI and engine** — The frontend calls the engine at `127.0.0.1:8765` via fetch. No Tauri IPC commands are used. This keeps the engine fully testable without Tauri and avoids Rust↔Python FFI complexity.

**INSERT-based DXF parsing** — ET CAD exports use DXF INSERT entities (one INSERT = one piece, block name = piece id). The parser uses this as the primary strategy and falls back to flat layer-scan for other DXF sources.

**No Pydantic in engine** — Engine uses Python `dataclasses` and `dataclasses.asdict()` for serialization. Pydantic is not installed to keep the dependency footprint small.

**ezdxf reads via temp file** — `ezdxf.readfile(tmp_path)` is used instead of `ezdxf.read(BytesIO(...))` because ET CAD files are often CP1252-encoded and ezdxf must detect encoding from `$DWGCODEPAGE` in the file header.

**PyInstaller sidecar (Phase 7)** — The engine will be bundled as a Tauri sidecar executable to achieve one-click installation. The Tauri shell spawns it on startup and kills it on exit.

## Component Responsibilities

| Component | Owns |
|-----------|------|
| `engine/core/dxf/` | DXF bytes → RawPiece list |
| `engine/core/geometry/` | Polygon normalization, validity repair |
| `engine/core/models/` | Piece, BoundingBox dataclasses (cross-layer contract) |
| `engine/api/` | HTTP routing, CORS, request/response serialization |
| `frontend/hooks/` | Engine calls, async state, viewport state |
| `frontend/components/canvas/` | Konva rendering + click-to-select. Read-only; engine owns placements (see Phase 5 optimization-round changes below) |
| `frontend/utils/placement.ts` | Pure placement math (no side effects) |
| `desktop/src-tauri/` | Window creation, sidecar lifecycle (Phase 7) |

## Phase 4 Decisions

> Note: Phase 4 shipped a manual-editing mode (drag, rotation handle, R-key, SAT-based collision detection). These were **removed** in the Phase 5 optimization round in favour of an engine-driven, read-only workflow. The notes below describe the original Phase-4 design for historical reference; the "Phase 5 Decisions" section below explains why they were removed and what replaced them.

**~~Placement state lives in `usePlacements`~~** — A React hook in `App.tsx` owns the `Placement[]` array (pieceId, x, y, rotationDeg). ~~It initialises from `computePlacements(pieces)` on each import and exposes `updatePlacement(id, delta)` for drag/rotate edits.~~ (Phase 5: starts empty; `setAllPlacements` is the only writer; `updatePlacement` removed.) Rotations are stored as float degrees; the engine can accept arbitrary angles.

**~~Collision detection: SAT + out-of-bounds in `useCollisions`~~** — Removed entirely in Phase 5. (See "Phase 5 Decisions" below.)

**Manual panning replaces Stage `draggable`** — Konva's built-in Stage dragging conflicts with child-node dragging: both register a drag target on `mousedown`, causing the canvas to pan after every piece drag. Stage `draggable` is removed; panning is implemented manually via `onMouseDown/Move/Up` on the Stage, activating only when `e.target === stage` (empty canvas click). A `window.mouseup` listener clears pan state if the mouse exits the Stage. (Still applies after Phase 5: panning is the only Stage-level interaction.)

**~~Smooth rotation via direct Konva mutation~~** — Removed with the rotation handle in Phase 5.

**CJK encoding detection in parser** — After the initial `ezdxf.readfile()`, block/layer names are inspected for chars in U+0080–U+00FF (Latin supplement). This range is the signature of GBK or Big5 bytes misread as CP1252. If detected, the file is re-read with `encoding='gbk'` then `'big5'` as fallback, enabling correct display of Simplified and Traditional Chinese piece names.

## Phase 5 Decisions

**NFP-based Bottom-Left-Fill** — `_blf_pack_nfp` in `engine/core/layout/heuristic.py`. For each piece + rotation, build the IFP (rectangle of valid reference-point positions inside fabric width) and the union of NFPs against every placed piece (via `pyclipper.MinkowskiSum`). The Shapely `difference` of IFP and NFP-union is the valid-placement region; pick the lowest-then-leftmost boundary vertex. Touching boundaries allowed (engine `_has_area_overlap` eps = 0.5 mm² to match frontend SAT tolerance — see below).

**Bi-direction superset fallback** — Bi's rotation set `[target, target+180°]` is a strict superset of single's `[target]`, so bi should never be globally worse. Greedy BLF can produce a worse bi layout (a locally-good `target+180°` rotation leaves a worse gap for subsequent pieces). `_modes_to_try("bi") → ["bi", "single"]` runs both and keeps the shorter marker. Same logic applies to `auto_layout_bbox`.

**Cancellation via cooperative flag + threadpool** — `core/layout/cancellation.py` exposes a module-level boolean. The auto-layout endpoint runs the synchronous NFP/BLF work via FastAPI's `run_in_threadpool`, so concurrent `/cancel-layout` requests are handled in the event loop. The layout loop checks `is_cancelled()` between piece placements and raises `CancellationError`; the endpoint returns HTTP 499. The frontend `useAutoLayout.abort()` aborts the in-flight fetch AND posts `/cancel-layout`.

**Frontend collision detection removed (entirely)** — `useCollisions`, `collisions.ts`, `geometry.ts`, `polygonsIntersect` (SAT), and the related tests are deleted. The frontend trusts the engine for placement validity. Previously the duplicate SAT check kept disagreeing with the engine on edge cases (NFP slivers, conversion drift on pieces with many vertices at large coords), flagging engine-placed pieces as colliding when they were touching. Removing the entire layer eliminated the false positives.

**Manual editing removed (entirely)** — Drag handlers, rotation handle, R-key handler, "Enable manual edit on canvas" checkbox, `manualEditEnabled` state, `updatePlacement`, `editable` and `isColliding` props are all gone. Selection (click-to-highlight) is kept because it isn't editing. Workflow is now: import → set fabric / grain / copies → Auto Layout → view-only result.

**Canvas rotated 90° CCW** — Pure visual transform: content layers wrapped in `<Group rotation={-90} y={fabricWidthMm}>`. Fabric extends to the right; grain points right; the marker-length dotted line is vertical. Engine math and placement convention are unchanged (X = fabric width constraint, Y = length to minimize). New helper `computeFitViewportFromWorldBbox` for the rotated fit math.

**`PreviewPanel` (top strip)** — One outline-only SVG thumbnail per imported piece, with the piece name. Independent of `copies` and of canvas placements. SVG (not Konva) because these are tiny static thumbnails. Selection by base id, so clicking a thumbnail highlights all canvas copies of that piece.

**Coordinate conversion correct for irregular polygons** — `utils/engineToFrontendPlacement.ts` iterates the actual polygon vertices to compute the Konva-frame `(x, y)` from the engine's "top-left of rotated polygon bbox". The earlier `W_rot/2`-based formula assumed symmetry around the unrotated bbox center, which only holds for rectangles.

**Per-set coloring** — `utils/setColors.ts` defines a 20-color palette excluding black, white, yellow (per spec) plus orange (`#ff9800` reserved for selection) and bright red (reserved for previous collision highlight). Each copy gets `colorForSet(setIndex)`.

**Live metrics with overflow guard** — `utils/metrics.ts` computes marker length and utilization from current placements. Iterates rendered polygon vertices for accuracy. Detects overflow (any vertex past fabric width or above y=0) and the UI shows "—" with a warning instead of a >100% value.

## Design Constraints

- **Offline-first:** No network calls outside `127.0.0.1`. No CDN assets, no telemetry.
- **Windows-first:** Paths, scripts, and packaging target Windows. Shell scripts are `.bat`.
- **Zero user setup:** End users must not touch a terminal. All dependencies are bundled.
- **Phase boundaries:** Features for Phase N+1 are not implemented during Phase N.
