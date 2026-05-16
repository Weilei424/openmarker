# Implementation Plan

## Overview

OpenMarker is a Windows-first, offline-first desktop fabric layout tool for non-technical factory users. It is delivered in 8 phases (0–7), from repo setup through packaged Windows installer. The engine is a local Python/FastAPI process; the UI is React + Konva inside a Tauri shell. All communication is local HTTP.

---

## Phases

### Phase 0 — Planning and repository setup ✅

**Goal:** Establish architecture, agent rules, and repo skeleton before any code is written.

**Deliverables:** CLAUDE.md, CODEX.md, ROADMAP.md, SKILLS.md, repo structure, README.md

**Success criteria:** Any future Claude instance can read the docs and understand constraints and delivery plan.

---

### Phase 1 — Desktop shell and local engine wiring ✅

**Goal:** Tauri window opens; React UI loads; Python engine starts and responds to a ping.

**Key files:** `desktop/src-tauri/`, `frontend/src/app/App.tsx`, `engine/api/main.py`

**Success criteria:** `GET /ping` round-trip works from UI button; Tauri dev mode launches without errors.

---

### Phase 2 — DXF import and normalization ✅

**Goal:** Upload an ET CAD DXF file and receive normalized piece data.

**Key files:** `engine/core/dxf/parser.py`, `engine/core/geometry/normalize.py`, `engine/core/models/piece.py`, `frontend/src/hooks/useImportDxf.ts`

**Success criteria:** All sample DXF fixtures parse without crashes; pieces have valid polygons; unit + integration tests pass.

---

### Phase 3 — Visual workspace ✅ (in progress)

**Goal:** Imported pieces appear on a Konva canvas with zoom, pan, selection, and fabric bounds.

**Key files:** `frontend/src/components/canvas/`, `frontend/src/hooks/useViewport.ts`, `frontend/src/utils/placement.ts`

**Success criteria:** User can import a DXF and see all pieces laid out; zoom and pan work; clicking a piece highlights it; fabric width renders as a boundary.

---

### Phase 4 — Manual editing

**Goal:** User can drag and rotate pieces on the canvas; placement state is tracked; collision zones are highlighted.

**Planned additions:**
- Konva `draggable` on `PieceShape`; commit drag end to placement state
- Rotation via `R` key or on-canvas handle; snap to 15° increments (optional)
- Engine endpoint `POST /check-collisions` → returns overlapping pair ids
- Placement state model: `Record<pieceId, { x, y, rotationDeg }>`
- Collision highlight: red fill overlay on overlapping pieces
- Tests: drag transform math, rotation clamp, collision detection

**Success criteria:** Non-technical user can rearrange pieces without confusion; collision zones are visually obvious.

---

### Pre-Phase 5 Fixes

**Goal:** Fix three parser/normalizer bugs discovered during Phase 4 testing, and add grainline parsing infrastructure required by Phase 5.

**Key files:** `engine/core/dxf/parser.py`, `engine/core/geometry/normalize.py`, `engine/core/models/piece.py`, `frontend/src/types/engine.ts`

**Deliverables:**
- Quantity expansion: DXF `Quantity: N` → N pieces per block, named `{name} (1)` … `{name} (N)` when N > 1
- Y-axis flip: pieces render in correct orientation (DXF Y-up → canvas Y-down)
- Grainline parsing: `LINE` layer-7 in each DXF block → `Piece.grainline_direction_deg`

**Success criteria:** Importing `examples/input/2_pieces_x_2_with_grainline.dxf` produces 4 pieces with correct orientation and `grainline_direction_deg` set on each. All parser and normalizer tests pass.

---

### Phase 5 — Simple auto layout

**Prerequisite:** Pre-Phase 5 fixes complete (grainline data in `Piece` model).

**Goal:** One-click heuristic placement that fills fabric width and reports utilization. Respects grainline constraints from DXF data.

**Planned additions:**
- Engine: `engine/core/layout/grain.py` and `heuristic.py`
- Engine endpoint `POST /auto-layout` → accepts pieces + fabric settings, returns placements + metrics
- Strip-packing heuristic: bbox mode (fast) and polygon mode (default, uses Shapely)
- Grain constraint: per-piece `target_rotation = (fabric_grain_deg - piece.grainline_direction_deg) % 360`; pieces without grainline data are unconstrained
- UI: `GrainPanel` (grain direction, grain mode, fast mode toggle); Auto Layout button; utilization in status bar
- Tests: grain logic, strip-packing, grain enforcement end-to-end

**Success criteria:** Auto layout places all pieces respecting grain constraints; utilization % is correct; fast vs default mode both produce valid outputs.

---

### Phase 6 — Export

**Goal:** User can save the current layout to a file.

**Planned additions:**
- Engine endpoint `POST /export` → accepts placements + format, returns file bytes
- Formats: DXF (preferred for downstream CAM use) and/or PNG preview
- UI: "Export" button opens save dialog via Tauri `save` dialog API
- Tests: exported DXF round-trips back through parser without data loss

**Success criteria:** Exported file opens correctly in ET CAD or a standard DXF viewer.

---

### Phase 7 — Packaging and usability polish

**Goal:** One-click Windows installer that works without any manual setup.

**Planned additions:**
- Bundle engine as PyInstaller `.exe` sidecar (`desktop/src-tauri/binaries/`)
- Wire sidecar launch in Tauri `lib.rs` (spawn on app start, kill on exit)
- Run `python scripts/gen-icons.py` before first `cargo tauri build`
- `cargo tauri build` produces an `.msi` or `.exe` installer
- QA checklist run on a clean Windows machine

**Success criteria:** A non-technical user receives the installer, runs it, and reaches the main workspace without any terminal interaction.
