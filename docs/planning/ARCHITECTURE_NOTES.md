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

## Design Constraints

- **Offline-first:** No network calls outside `127.0.0.1`. No CDN assets, no telemetry.
- **Windows-first:** Paths, scripts, and packaging target Windows. Shell scripts are `.bat`.
- **Zero user setup:** End users must not touch a terminal. All dependencies are bundled.
- **Phase boundaries:** Features for Phase N+1 are not implemented during Phase N.
