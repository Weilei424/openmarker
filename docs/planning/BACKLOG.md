# Backlog

## Status Legend
- [ ] Not started
- [x] Complete
- [~] In progress

---

### Phase 0 — Planning and repository setup
- [x] Finalize architecture
- [x] Set agent rules (CLAUDE.md, CODEX.md, SKILLS.md)
- [x] Create repository skeleton
- [x] Write ROADMAP.md
- [x] Write starter README.md

### Phase 1 — Desktop shell and local engine wiring
- [x] Bootstrap Tauri app shell
- [x] Open React UI inside desktop shell
- [x] Start Python FastAPI engine locally
- [x] Wire UI → engine ping (GET /ping)
- [x] Document local dev instructions

### Phase 2 — DXF import and normalization
- [x] POST /import-dxf endpoint
- [x] INSERT-based ET CAD DXF parser
- [x] Flat layer-scan fallback parser
- [x] Open segment chaining (_chain_open_segments)
- [x] Geometry normalization (translate to origin, make_valid)
- [x] Piece and BoundingBox dataclasses
- [x] Sample DXF fixtures (examples/input/)
- [x] Unit tests: parser + normalize
- [x] Integration test: API upload round-trip

### Phase 3 — Visual workspace
- [x] Konva Stage rendering piece polygons
- [x] Zoom and pan (useViewport)
- [x] Fit-to-content on import
- [x] Piece selection (click to select)
- [x] Fabric bounds overlay
- [x] Status bar (piece count, fabric width)
- [x] PieceList sidebar panel
- [x] FabricPanel (fabric width input)
- [ ] Viewport regression tests

### Phase 4 — Manual editing ✓
- [x] Drag pieces on canvas
- [x] Rotate pieces (R key + handle)
- [x] Snap behavior (10 mm grid drag-end; 1° rotation drag-end)
- [x] Collision highlight feedback (piece-to-piece SAT + out-of-bounds)
- [x] Placement state model (usePlacements hook: pieceId → x, y, rotationDeg)
- [x] Regression tests for drag/rotate transformations
- [x] Auto fit-to-content on import
- [x] Auto fabric width on import (computed from initial row layout)
- [x] Dynamic rotation handle distance (always outside piece bbox)
- [x] Smooth rotation via direct Konva mutation (no React re-renders during drag)
- [x] CJK encoding detection in DXF parser (GBK / Big5 fallback)

### Pre-Phase 5 Fixes ✓
- [x] Parse `Quantity: N` from TEXT entities in each DXF block; emit N copies of the piece
- [x] Name duplicated pieces `{name} (1)`, `{name} (2)` … when quantity > 1
- [x] Y-axis flip in `normalize_piece()` (DXF Y-up → canvas Y-down)
- [x] Parse `LINE` on layer 7 in each DXF block as grainline; store start/end in `RawPiece`
- [x] Apply Y-flip + origin translate to grainline coords in `normalize_piece()`
- [x] Add `grainline_direction_deg: float | None` to `Piece` model and engine.ts type
- [x] Update/add tests: quantity expansion, Y-flip orientation, grainline parsing, 2×2 fixture
- [x] Cap max zoom to 500% (MAX_SCALE = 5) to prevent stroke-artifact confusion

### Phase 5 — Simple auto layout
- [ ] User inputs fabric width
- [ ] Run placement heuristic (strip packing or guillotine)
- [ ] Compute marker length
- [ ] Compute utilization percentage
- [ ] Show manual vs auto utilization comparison

### Phase 6 — Export
- [ ] Export layout as DXF or PNG
- [ ] Export UI flow
- [ ] File output tests

### Phase 7 — Packaging and usability polish
- [ ] Bundle engine as PyInstaller sidecar
- [ ] Build Windows installer (cargo tauri build)
- [ ] Generate app icons (scripts/gen-icons.py)
- [ ] Remove any remaining setup friction
- [ ] QA checklist for non-technical users
