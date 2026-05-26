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

- `api/main.py` — FastAPI app, CORS middleware. Routes:
  - `GET /ping` → `{"status": "ok", "version": "0.1.0"}`
  - `POST /import-dxf` → multipart upload, returns parsed pieces
  - `POST /auto-layout` → run NFP-BLF; pieces + fabric + grain + fast_mode in, placements + marker_length + utilization out. Runs in a worker thread via `run_in_threadpool` so other endpoints stay responsive.
  - `POST /cancel-layout` → sets a cancellation flag the layout loop checks between piece placements; returns immediately.
- `core/dxf/parser.py` — `parse_dxf(bytes)` → `list[RawPiece]`. Uses INSERT-based strategy for ET CAD files (one INSERT = one piece, block name = piece id); falls back to flat modelspace layer scan. Both paths support chained open segments via `_chain_open_segments()`.
- `core/geometry/normalize.py` — `normalize_piece()` translates polygon to origin, repairs invalid geometry with Shapely's `make_valid()`.
- `core/layout/grain.py` — `allowed_rotations()` for none / single / bi grain modes.
- `core/layout/heuristic.py` — `auto_layout_polygon` (NFP-BLF via pyclipper + Shapely) and `auto_layout_bbox` (shelf-pack, "fast mode"). `_blf_pack_nfp` is the core: IFP rectangle of valid reference points minus union of NFPs (Burke 2006). Touching boundaries allowed (`_has_area_overlap` eps = 0.5 mm²). When `grain_mode == "bi"` runs both `bi` and `single` and keeps the shorter result (greedy BLF can otherwise produce a worse bi layout). 4 sort strategies tried; best wins. Fallback: forced new-shelf placement below all placed pieces. Serial path (effort=1) prunes strategies whose partial marker length already meets/exceeds the best complete result so far — sound because BLF's partial marker length is monotone non-decreasing in the number of placed pieces. Parallel path (effort>1) also prunes: workers share a `multiprocessing.Value('d', float('inf'))` that the main process updates (running min) as each strategy completes via `as_completed`, and workers read per-placement to abort their own runs when partial >= shared cutoff. `disable_pruning: bool = False` on `auto_layout_polygon` turns it off in both paths for A/B benchmarking (mirrors `disable_nfp_cache`). Identical-piece pre-clustering (`core/layout/clustering.py`) is implemented but **off by default** (`disable_clustering: bool = True`): bbox approximation regresses on garment workloads by forcing rigid rectangular super-pieces that can't interleave with other pieces. Enable with `disable_clustering=False` for benchmarking; will be replaced by true-union polygon clusters (filed in BACKLOG) which can tile inter-copy bays.
- `core/layout/clustering.py` — `pre_cluster_pieces` (groups by base id; for each group, packs into a super-piece via greedy grid aspect-ratio search; rotation-aware feasibility check honors grain_mode + fabric_grain_deg so the cluster fits at BLF's chosen rotation) and `expand_cluster_placement` (converts a super-piece placement back to per-copy placements). `Cluster` dataclass holds the super-piece + copy offsets + original pieces. Cluster polygon is the bounding box of the packed grid — inter-copy bays are unused, which is why this is off by default for now (true-union polygon clusters would reclaim that area).
- `core/layout/cancellation.py` — module-level flag + `CancellationError`. `is_cancelled()` checked between piece placements.
- `core/models/piece.py` — `Piece` and `BoundingBox` dataclasses; these are the contract between all layers.
- No Pydantic; use `dataclasses.asdict()` for serialization.

### Frontend (`frontend/src/`)

Top-level: `topbar | preview-panel | (sidebar + canvas) | statusbar`. The canvas is **read-only** — no drag, no rotate, no per-piece editing. Engine output is the source of truth for placements; the frontend renders it and offers selection (click-to-highlight) only.

- `app/App.tsx` — wires all panels; manages fabric width (defaults to 1500 mm and resets on every import), grain mode, copies input, and selection state. Topbar shows "OpenMarker — Working on {filename}" once a DXF imports.
- `components/PreviewPanel.tsx` — top horizontal strip of imported pieces (outline-only SVG thumbnails, base id, name). Clicking a thumbnail selects all copies of that piece on the canvas.
- `components/canvas/CanvasWorkspace.tsx` — Konva `Stage`. Content wrapped in `<Group rotation={-90} y={fabricWidthMm}>` so the fabric visually extends right with grain pointing right. Engine math stays in original engine coords.
- `components/canvas/PieceShape.tsx` — closed Konva `Line` polygon + optional grain arrow; click selects/deselects. No drag, no rotation handle, no collision highlight.
- `components/sidebar/{Fabric,Grain}Panel.tsx` — sidebar controls.
- `hooks/useImportDxf.ts` — file upload to engine; returns `ImportOutcome` directly (don't read React state after awaiting — it's stale).
- `hooks/useAutoLayout.ts` — `POST /auto-layout` wrapper; `abort()` cancels in-flight fetch AND posts `/cancel-layout`.
- `hooks/usePlacements.ts` — placement state. Starts empty; populated by `setAllPlacements` (only auto-layout uses this). `resetPlacements` clears.
- `hooks/useViewport.ts` — zoom/pan/fit-to-content state.
- `utils/engineToFrontendPlacement.ts` — converts engine "top-left of rotated bbox" to frontend "top-left of unrotated bbox + rotation around center" by iterating polygon vertices (exact for any polygon shape).
- `utils/metrics.ts` — live marker length + utilization; clamped to 100 % with overflow warning when pieces exceed fabric width.
- `utils/setColors.ts` — 20-color palette for per-copy coloring (no black / white / yellow; avoids the orange + red used for selection / hover state).
- `utils/placement.ts` — `computeFitViewportFromWorldBbox` for the rotated canvas fit math.
- `types/engine.ts` — TypeScript interfaces mirroring engine JSON shapes.

Note on what's NOT here: there is intentionally no `useCollisions`, no `collisions.ts`, no SAT/`polygonsIntersect`, and no manual-editing surface. Frontend collision detection was removed in the Phase 5 optimization round because it kept disagreeing with the engine on touching/edge-case placements; the engine owns placement validity now.

### Desktop shell (`desktop/src-tauri/`)

Thin Tauri 2.x wrapper. `tauri.conf.json` sets window size (1280×800, min 900×600) and points to the Vite dev server. No direct Rust↔engine calls; all communication goes through the browser HTTP client.

---

## Key data model (engine → frontend)

```typescript
interface Piece {
  id: string                       // "piece_0", "piece_1", … (engine). Frontend
                                   // suffixes "__c{n}" per copy when copies > 1.
  name: string                     // DXF layer name
  polygon: [number, number][]      // exterior ring, origin-translated, no closing duplicate
  area: number                     // mm²
  bbox: { min_x; min_y; max_x; max_y; width; height }
  is_valid: boolean
  validation_notes: string[]       // non-empty when Shapely repair was applied
  grainline_direction_deg: number | null  // piece-space angle in degrees
  setIndex?: number                // frontend-only: which copy this piece is (for coloring)
}

interface Placement {
  pieceId: string
  x: number                        // mm — top-left of UNROTATED bbox in engine space
  y: number                        // (canvas applies the 90° CCW visual rotation)
  rotationDeg: number              // CW around the piece's bbox center
}
```

To detect repaired geometry, key off `validation_notes.length > 0` — not `!is_valid`, because `make_valid()` always produces a valid result.

`POST /auto-layout` returns `placements` with engine-convention coords (top-left of the *rotated* polygon bbox). The frontend converts to the `Placement` shape above via `utils/engineToFrontendPlacement.ts`.

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

1. app shell  2. DXF import  3. visualization  4. ~~manual editing~~ (shipped, then removed in Phase 5 optimization in favour of engine-driven read-only layout)  5. auto layout  6. export  7. packaging polish

### 3. Keep modules clean

- `frontend/` — presentation and interaction only
- `desktop/` — app shell and packaging only
- `engine/` — DXF, geometry, nesting, export, metrics

### 4. Favor explicit data models

Use clear dataclasses/interfaces for: pattern pieces, normalized polygons, placements, fabric settings, export payloads.

### 5. Make testability easy

Isolate: DXF parsing, geometry normalization, NFP / placement rules, utilization calculations. (Collision detection lives only in the engine — the frontend trusts engine output and does not double-check overlaps.)

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
