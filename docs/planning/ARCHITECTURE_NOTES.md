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
| `frontend/components/canvas/` | Konva rendering, selection, drag (Phase 4+) |
| `frontend/utils/placement.ts` | Pure placement math (no side effects) |
| `desktop/src-tauri/` | Window creation, sidecar lifecycle (Phase 7) |

## Phase 4 Decisions

**Placement state lives in `usePlacements`** — A React hook in `App.tsx` owns the `Placement[]` array (pieceId, x, y, rotationDeg). It initialises from `computePlacements(pieces)` on each import and exposes `updatePlacement(id, delta)` for drag/rotate edits. Rotations are stored as float degrees; the engine can accept arbitrary angles.

**Collision detection: SAT + out-of-bounds in `useCollisions`** — `computeCollidingIds` checks all piece pairs with the Separating Axis Theorem and also flags any piece whose rotated-polygon AABB extends outside the fabric bounds (x < 0, x > fabricWidthMm, or y < 0). Results drive red highlight in `PieceShape`.

**Manual panning replaces Stage `draggable`** — Konva's built-in Stage dragging conflicts with child-node dragging: both register a drag target on `mousedown`, causing the canvas to pan after every piece drag. Stage `draggable` is removed; panning is implemented manually via `onMouseDown/Move/Up` on the Stage, activating only when `e.target === stage` (empty canvas click). A `window.mouseup` listener clears pan state if the mouse exits the Stage.

**Smooth rotation via direct Konva mutation** — During rotation-handle drag, `onDragMove` directly calls `layer.findOne('#piece-X').rotation(deg)` and updates the dashed line's points, bypassing React state. This avoids triggering React re-renders and collision-detection overhead on every mousemove, and prevents react-konva from resetting the Circle's `x/y` props mid-drag (which would snap the handle back to the arc each frame). The final angle is committed to React state on `dragEnd` with a 1° snap.

**CJK encoding detection in parser** — After the initial `ezdxf.readfile()`, block/layer names are inspected for chars in U+0080–U+00FF (Latin supplement). This range is the signature of GBK or Big5 bytes misread as CP1252. If detected, the file is re-read with `encoding='gbk'` then `'big5'` as fallback, enabling correct display of Simplified and Traditional Chinese piece names.

## Design Constraints

- **Offline-first:** No network calls outside `127.0.0.1`. No CDN assets, no telemetry.
- **Windows-first:** Paths, scripts, and packaging target Windows. Shell scripts are `.bat`.
- **Zero user setup:** End users must not touch a terminal. All dependencies are bundled.
- **Phase boundaries:** Features for Phase N+1 are not implemented during Phase N.
