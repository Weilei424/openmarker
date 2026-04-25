# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role

Claude Code acts as the **primary implementer** for this project.

Claude owns feature implementation, refactoring, test creation, and internal documentation updates.

## Project context

This project is a **Windows-first offline desktop fabric layout tool** for non-technical factory users.

Core constraints:

- one-click installation matters a lot
- users should not install Python, Node, Docker, or anything manually
- the app must work without internet
- DXF import from ET CAD is the main input path
- the architecture should remain simple and maintainable

## Working Rules

- Keep `/BACKLOG.md` updated: add each phase's task checklist after its plan is written, check off tasks during execution, and mark all tasks complete when the phase is done.

---

## Dev commands

### Engine (Python · FastAPI · port 8765)

```bat
# One-time setup (Windows)
scripts\setup-engine.bat

# Start engine for development
scripts\dev-engine.bat
# or directly:
cd engine && .\.venv\Scripts\python api/main.py

# Run all tests
engine\.venv\Scripts\pytest tests\ -v

# Run a single test file
engine\.venv\Scripts\pytest tests\unit\test_dxf_parser.py -v

# Run a single test by name
engine\.venv\Scripts\pytest tests\unit\test_dxf_parser.py -v -k "test_name"
```

### Frontend (React · Vite · port 1420)

```bash
cd frontend
npm install
npm run dev        # standalone Vite server
npm run build      # tsc + vite build
npm run test       # vitest
```

### Desktop shell (Tauri · Rust)

```bash
cd desktop/src-tauri
cargo tauri dev    # opens Tauri window; starts Vite dev server automatically
cargo tauri build  # production binary (run after cargo tauri dev works)
```

Full dev session: start `scripts\dev-engine.bat` first, then `cargo tauri dev` in a second terminal.

---

## Architecture

Three layers communicate over local HTTP only — the engine is never exposed to a network.

```
Tauri window
  └─ React/Konva UI  ──HTTP──►  FastAPI engine (127.0.0.1:8765)
```

### Engine (`engine/`)

- `api/main.py` — FastAPI app, CORS middleware, two routes:
  - `GET /ping` → `{"status": "ok", "version": "0.1.0"}`
  - `POST /import-dxf` → multipart upload, returns parsed pieces
- `core/dxf/parser.py` — `parse_dxf(bytes)` → `list[RawPiece]`. Uses INSERT-based strategy for ET CAD files (one INSERT = one piece, block name = piece id); falls back to flat modelspace layer scan. Both paths support chained open segments via `_chain_open_segments()`.
- `core/geometry/normalize.py` — `normalize_piece()` translates polygon to origin, repairs invalid geometry with Shapely's `make_valid()`.
- `core/models/piece.py` — `Piece` and `BoundingBox` dataclasses; these are the contract between all layers.
- No Pydantic; use `dataclasses.asdict()` for serialization.

### Frontend (`frontend/src/`)

- `app/App.tsx` — top-level layout: topbar | sidebar + canvas | statusbar.
- `hooks/useImportDxf.ts` — file upload to engine; returns `ImportOutcome` directly (don't read React state after awaiting — it's stale).
- `hooks/useViewport.ts` — zoom/pan/fit-to-content state.
- `components/canvas/CanvasWorkspace.tsx` — Konva `Stage` rendering pieces and fabric bounds.
- `components/canvas/PieceShape.tsx` — renders each piece as a closed Konva `Line` polygon.
- `utils/placement.ts` — pure functions computing initial piece positions and viewport transforms (no side effects).
- `types/engine.ts` — TypeScript interfaces mirroring engine JSON shapes.

### Desktop shell (`desktop/src-tauri/`)

Thin Tauri 2.x wrapper. `tauri.conf.json` sets window size (1280×800, min 900×600) and points to the Vite dev server. No direct Rust↔engine calls; all communication goes through the browser HTTP client.

---

## Key data model (engine → frontend)

```typescript
interface Piece {
  id: string                    // "piece_0", "piece_1", …
  name: string                  // DXF layer name
  polygon: [number, number][]   // exterior ring, origin-translated, no closing duplicate
  area: number                  // mm²
  bbox: { min_x; min_y; max_x; max_y; width; height }
  is_valid: boolean
  validation_notes: string[]    // non-empty when Shapely repair was applied
}
```

To detect repaired geometry, key off `validation_notes.length > 0` — not `!is_valid`, because `make_valid()` always produces a valid result.

---

## ezdxf gotchas

- Write DXF to bytes: `stream = io.StringIO(); doc.write(stream); return stream.getvalue().encode("utf-8")`
- Read DXF from bytes: write to a temp file and use `ezdxf.readfile(tmp_path)` — ET CAD files are often CP1252; decoding with `errors='replace'` silently corrupts entity data.
- `add_lwpolyline()`: use `close=True` kwarg (not deprecated `dxfattribs={"closed": True}`).
- Layer `"0"` always exists; calling `doc.layers.add("0")` raises `DXFTableEntryError`.

---

## Architecture to follow

- **Desktop shell:** Tauri
- **Frontend:** React + TypeScript + Konva
- **Engine:** Python
- **Geometry:** Shapely + Pyclipper
- **DXF parsing:** ezdxf

Claude should implement within these boundaries unless the roadmap is explicitly revised.

## Implementation principles

### 1. Build for the actual users

The users are Windows factory workers who are not technical. Prefer:

- simple flows and obvious buttons
- stable local behavior
- low setup friction

### 2. Deliver in phases

1. app shell  2. DXF import  3. visualization  4. manual editing  5. simple auto layout  6. export  7. packaging polish

### 3. Keep modules clean

- `frontend/` — presentation and interaction only
- `desktop/` — app shell and packaging only
- `engine/` — DXF, geometry, nesting, export, metrics

### 4. Favor explicit data models

Use clear dataclasses/interfaces for: pattern pieces, normalized polygons, placements, fabric settings, export payloads.

### 5. Make testability easy

Isolate: DXF parsing, geometry normalization, collision checks, placement rules, utilization calculations.

## Coding expectations

- Write readable code; add brief comments only where logic is non-obvious.
- Keep functions focused; isolate hot-path logic from UI glue code.
- Document assumptions when DXF formats are uncertain.

## Preferred workflow per task

1. Identify touched modules.
2. Implement smallest working version.
3. Add or update tests.
4. Update docs if behavior or architecture changed.

## When making tradeoffs

Prefer: correctness over cleverness · maintainability over micro-optimization · local simplicity over distributed complexity · stable UX over feature count.

## Do not do these by default

- No cloud dependencies.
- No always-on internet assumptions.
- No Linux-only tooling in user workflows.
- No terminal usage for end users.
- No advanced AI features before core editing works.

## Definition of done

A feature is done when it works in the intended layer, fits the roadmap phase, has reasonable tests, and does not conflict with offline Windows usage or make packaging meaningfully harder.
