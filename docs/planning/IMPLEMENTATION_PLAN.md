# Implementation Plan

## Overview

OpenMarker is a Windows-first, offline-first desktop fabric layout tool for non-technical factory users. It is delivered in 9 phases (0–8), from repo setup through packaged Windows installer. The engine is a local Python/FastAPI process; the UI is React + Konva inside a Tauri shell. All communication is local HTTP.

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

### Phase 4 — Manual editing  *(shipped, then removed in Phase 5 optimization)*

**Original goal:** User can drag and rotate pieces on the canvas; placement state is tracked; collision zones are highlighted.

**Shipped during Phase 4:**
- Konva `draggable` on `PieceShape`; commit drag end to placement state
- Rotation via `R` key + on-canvas rotation handle; 1° snap on drag end
- Frontend SAT-based collision detection in `useCollisions` (no engine endpoint — done in browser)
- Placement state model: `Placement[]` in `usePlacements` with `updatePlacement(id, delta)`
- Collision highlight: red stroke + translucent red fill on overlapping or out-of-bounds pieces

**Removed in Phase 5 optimization round (PR #5):**
After the engine became authoritative for placement (NFP-BLF), the frontend's SAT-based duplicate collision check kept disagreeing with the engine on touching / edge-case placements and producing visible false positives. Rather than tune the two layers to agree, we deleted the frontend collision layer and the entire manual-editing surface (drag, rotation handle, R-key, edit checkbox, `updatePlacement`, `isColliding` / `editable` props). The app is now read-only after Auto Layout. Click-to-select / deselect is the only canvas interaction.

See `docs/superpowers/plans/2026-05-18-phase5-auto-layout-optimization.md` ("What actually shipped" section) for the deletion list.

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

### Phase 6 — Fixes, performance, and UI improvements

**Goal:** Clean up Phase 5 rough edges, simplify the settings surface, add a results cache that the export phase will consume, and rework the metrics UI.

**Raw user requirements (source of truth for the planning skill):**

1. **Dynamic window size.** Replace the fixed 1280×800 default in `desktop/src-tauri/tauri.conf.json` with a runtime-computed size: 70% of monitor height, 4:3 aspect ratio (width = height × 4 / 3). Likely implemented in Rust (`lib.rs` / `main.rs`) using the Tauri 2.x monitor API at window creation. Keep `min_width` / `min_height` reasonable so the layout still works on smaller monitors.
2. **Copies input height.** Double the height of the Settings → Copies number input in the sidebar (currently in `frontend/src/components/sidebar/` — likely a `CopiesPanel` or part of an existing settings panel). Pure CSS change.
3. **Remove grain mode "none".** Drop the "none" option from `GrainPanel`, from the `GrainMode` TypeScript union, and from `engine/core/layout/grain.py::allowed_rotations()`. Update the engine endpoint to reject `"none"`. Default = `"single"`.
4. **Remove fast mode (bbox).** Delete the Fast-mode toggle in the sidebar, the `fast_mode` field in the `/auto-layout` request, and the `auto_layout_bbox` function (+ its tests). Only `auto_layout_polygon` remains.
5. **Show/hide grainline toggle.** Add a "Show grainline" checkbox (default = on). State lives in `App.tsx` and is passed down to `PieceShape` to gate the yellow arrow rendering. Applies to both fabric grain indicator and per-piece arrows — confirm during planning whether the toggle covers both or only the piece arrows.
6. **Auto-layout result cache.** New module `engine/core/layout/cache.py`. In-memory cache (engine-process lifetime only), keyed by `(filename, timestamp YYYYMMDDHHMMSS, grain_mode, copies)`. Max 5 entries with FIFO eviction. The cache stores the full `AutoLayoutResponse` (placements + metrics + duration). `POST /auto-layout` checks the cache before running and returns the cached entry on hit; otherwise runs the heuristic and inserts. New endpoints likely needed: `GET /layouts` (list cached entries with their keys + metrics) and `GET /layouts/{id}` (fetch a specific cached result). Confirm endpoint shape during planning.
7. **Cache feeds future export.** The cache stores everything Phase 7 needs (placements, fabric width, metrics) so export can target any cached entry by id, not just the active one. No export code is written in Phase 6 — just make sure the cache schema is export-ready.
8. **Metrics moved to bottom panel + timer.** Remove the live metrics block from the left sidebar. Create `frontend/src/components/BottomPanel.tsx` displaying: marker length (mm), utilization %, overflow warning (if applicable), and a layout-duration timer in `MM:SS` (measured engine-side from request start → response, returned in the `/auto-layout` response). Top-level layout in `App.tsx` becomes `topbar | preview-panel | tabs | (sidebar + canvas) | bottom-panel | statusbar`.
9. **Per-tab cached metrics + tab bar.** New `frontend/src/components/CachedLayoutTabs.tsx` rendered between the preview panel and the canvas. Each tab represents one cache entry (label e.g. `"sample_1.dxf · single · ×2"`). Active tab drives the canvas placements and the bottom-panel metrics. Closing/eviction UX: confirm during planning whether users can manually close tabs or only FIFO-evict.

**Clarifications already collected:**
- Window: **70% of monitor height, 4:3 aspect ratio**.
- Cache key: **filename + timestamp (YYYYMMDDHHMMSS) + settings**, in-memory only.
- Tab placement: **between preview panel (top) and canvas**.

**Key files (likely):**
- `desktop/src-tauri/tauri.conf.json`, `desktop/src-tauri/src/lib.rs` (or `main.rs`) — dynamic window size
- `frontend/src/components/sidebar/GrainPanel.tsx` (remove `none`, remove fast-mode, add grainline toggle) and copies input component (double height)
- `frontend/src/App.tsx` (new layout regions, tab/cache state, grainline toggle wiring)
- `frontend/src/components/PreviewPanel.tsx` (unchanged, but a new `CachedLayoutTabs.tsx` will sit directly below it)
- `frontend/src/components/BottomPanel.tsx` (new)
- `frontend/src/components/CachedLayoutTabs.tsx` (new)
- `frontend/src/hooks/useAutoLayout.ts` (cache-aware: surface cache hits, expose tab list)
- `engine/core/layout/cache.py` (new)
- `engine/api/main.py` (cache-aware `/auto-layout`; possibly `GET /layouts` + `GET /layouts/{id}`)
- `engine/core/layout/grain.py` (drop `none`)
- `engine/core/layout/heuristic.py` (drop `auto_layout_bbox`)
- Tests across all of the above.

**Success criteria:**
- App window opens at 70% monitor height in 4:3 ratio on a 1080p, 1440p, and 5K monitor without manual resize.
- Settings sidebar shows no "none" grain option and no fast-mode toggle; copies input is visibly taller.
- Grainline arrows can be toggled on/off without re-running the layout.
- Running auto-layout with identical filename+timestamp+settings a second time returns instantly (cache hit); 6th distinct run evicts the oldest entry.
- Each cached run appears as a tab between the preview panel and canvas; clicking a tab swaps both the canvas and the bottom-panel metrics.
- Bottom panel shows marker length, utilization, and an `MM:SS` duration for the active tab.
- No metrics block remains in the left sidebar.

---

### Phase 7 — Export

**Goal:** User can save any cached layout to a file.

**Planned additions:**
- Engine endpoint `POST /export` → accepts a cache id (or placements + format), returns file bytes
- Formats: DXF (preferred for downstream CAM use) and/or PNG preview
- UI: "Export" button on each cached tab (or on the bottom panel for the active tab) → Tauri `save` dialog API
- Tests: exported DXF round-trips back through parser without data loss

**Success criteria:** Exported file opens correctly in ET CAD or a standard DXF viewer; any cached tab (not just the most recent) can be exported.

---

### Phase 8 — Packaging and usability polish

**Goal:** One-click Windows installer that works without any manual setup.

**Planned additions:**
- Bundle engine as PyInstaller `.exe` sidecar (`desktop/src-tauri/binaries/`)
- Wire sidecar launch in Tauri `lib.rs` (spawn on app start, kill on exit)
- Run `python scripts/gen-icons.py` before first `cargo tauri build`
- `cargo tauri build` produces an `.msi` or `.exe` installer
- QA checklist run on a clean Windows machine

**Success criteria:** A non-technical user receives the installer, runs it, and reaches the main workspace without any terminal interaction.
