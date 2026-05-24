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

### Phase 4 — Manual editing ✓ (later REMOVED in Phase 5 optimization round)
> All of the items below shipped during Phase 4 but were removed in the Phase 5
> optimization round in favour of an engine-driven, read-only workflow. See
> "Phase 5 (optimization round)" below for the removal commits.
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
- [x] User inputs fabric width
- [x] Run placement heuristic (NFP-based Bottom-Left-Fill via pyclipper + Shapely)
- [x] Compute marker length (max Y bottom edge of placed pieces + edge gap)
- [x] Compute utilization percentage (clamped to 100% with overflow warning)
- [x] Multi-strategy sort (area / max-dim / height / width DESC); best wins
- [x] Grain mode (none / single / bi) with fabric grain fixed at 90°
- [x] Fast mode (bbox shelf-pack) vs accurate mode (polygon NFP-BLF)
- [x] Copies (1–20) with per-set color palette (no black/white/yellow)
- [x] Manual-edit toggle (off by default); R-key + drag + rotation handle gated
- [x] Stop button — engine cancellation flag + /cancel-layout endpoint + run_in_threadpool
- [x] Live metrics panel + dotted marker-length line on canvas
- [x] Fabric/piece grain arrows when grain mode != none

### Phase 5 (optimization round) — UX redesign & remaining bugs ✓
See `docs/superpowers/plans/2026-05-18-phase5-auto-layout-optimization.md`.
- [x] Top preview panel — always-visible horizontal strip of imported pieces with names (outline-only thumbnails, no fill)
- [x] Don't render pieces on canvas until auto-layout completes (no initial single-row preview)
- [x] Rotate canvas 90° CCW (fabric extends right; grain arrow points right; marker-length line vertical)
- [x] Selection by click works without enabling editing; re-click / empty-stage click deselects
- [x] Engine overlap eps raised from 1e-3 → 0.5 mm² to match frontend SAT tolerance
- [x] **Removed** frontend collision detection (`useCollisions`, `collisions.ts`, `geometry.ts` + tests) — engine is now authoritative for placement validity
- [x] **Removed** manual editing entirely (drag, rotate handle, R-key, "Enable manual edit on canvas" checkbox, `updatePlacement`) — too risky to maintain alongside engine-driven layout
- [x] Fabric width default = 1500 mm, resets on each import (no auto-fit to pieces)
- [x] Bi-direction never worse than single-direction — engine runs both modes when bi is selected and keeps the shorter result
- [x] Topbar shows current import filename ("OpenMarker — Working on sample_1.dxf")

### Phase 6 — Fixes, performance, and UI improvements

User-visible scope (raw requirements captured from planning conversation):

1. **UI — dynamic window size.** Default window starts at 70% of the monitor *height* with a 4:3 aspect ratio (width = height × 4 / 3), regardless of monitor resolution. Replace the current fixed 1280×800 default in `desktop/src-tauri/tauri.conf.json`.
2. **UI — copies input height.** Double the height of the Settings → Copies number input. Currently too short to read comfortably.
3. **Feature — remove grain mode "none" (free).** Drop the "none" option from `GrainPanel` and from engine `grain.allowed_rotations()`. Only `single` and `bi` remain. Default = `single`.
4. **Feature — remove fast mode (bbox).** Drop the "Fast mode" toggle and `auto_layout_bbox` code path. Only the polygon NFP-BLF path (`auto_layout_polygon`) remains.
5. **Feature — show/hide grainline toggle.** Add a checkbox (likely in `GrainPanel` or new view-options area) that toggles rendering of the yellow grainline arrows on pieces. Default = visible.
6. **Feature — auto-layout result cache.** In-memory cache (engine side) keyed by `filename + timestamp (YYYYMMDDHHMMSS)` + settings `{grain_mode (single|bi), copies}`. Max 5 entries (FIFO eviction). Identical request returns the cached result instead of re-running the heuristic.
7. **Feature — cache feeds future export.** Cached entries store the full layout result (placements + metrics) so that the Phase 7 export flow can pick any cached tab to export, not just the current one.
8. **UI — metrics moved to bottom panel + timer.** Remove the live metrics block from the left sidebar. Add a new bottom panel showing: marker length, utilization %, overflow warning, and a layout-duration timer in `MM:SS` format (measured from auto-layout request → response).
9. **Feature — per-tab cached metrics.** Each cached-result tab keeps its own metrics (marker length, utilization, duration). Switching tabs swaps both the canvas placements and the bottom-panel metrics.

Task checklist (filled in once the planning skill produces the detailed plan):

- [x] Engine: `LayoutCache` module (FIFO, max 5, no dedup)
- [x] Engine: wire cache into `POST /auto-layout` (returns id/timestamp/duration)
- [x] Engine: `GET /layouts`, `GET /layouts/{id}`, `DELETE /layouts/{id}`
- [x] Engine: drop `'none'` grain mode
- [x] Engine: drop `auto_layout_bbox` (fast mode)
- [x] Engine: require `filename`, reject `grain_mode='none'` (422)
- [x] Frontend: tighten `GrainMode` type, add `CachedLayout` types
- [x] Frontend: `useLayoutCache` hook
- [x] Frontend: `useAutoLayout` sends filename + copies; drops fast_mode
- [x] Frontend: `usePlacements` derives from active cached entry
- [x] Frontend: `GrainPanel` drops none + fast, adds Show grainline
- [x] Frontend: `PieceShape` uses `showGrainline` prop
- [x] Frontend: `CanvasWorkspace` passes `showGrainline`
- [x] Frontend: `BottomPanel` with `MM:SS` timer
- [x] Frontend: `CachedLayoutTabs` strip above canvas
- [x] Frontend: App.tsx new layout; double-height copies input
- [x] Frontend: delete unused `utils/metrics.ts`
- [x] Desktop: drop fixed window size, start hidden
- [x] Desktop: compute 70%-height 4:3 size in `lib.rs`

### Phase 7 — Export
- [ ] Export layout as DXF or PNG (sourced from any cached layout tab)
- [ ] Export UI flow
- [ ] File output tests

### Phase 8 — Packaging and usability polish
- [ ] Bundle engine as PyInstaller sidecar
- [ ] Build Windows installer (cargo tauri build)
- [ ] Generate app icons (scripts/gen-icons.py)
- [ ] Remove any remaining setup friction
- [ ] QA checklist for non-technical users

---

## Future / Unscheduled

Items not yet assigned to a phase. Rough notes captured to avoid losing context.

### Layout performance — advanced controls

- [ ] **NFP cache toggle (developer / advanced).** Sidebar (under a "Developer" subsection, NOT main Settings) checkbox to bypass the per-call NFP cache. Engine: `/auto-layout` accepts an optional `disable_nfp_cache: bool`; when true, `_blf_pack_nfp` is invoked with a fresh `{}` per strategy. Intended for A/B comparison and bug isolation, not regular use. Quietly remove once confidence is high (target: Phase 7 acceptance testing window).

- [ ] **Parallel strategy execution + effort slider.** Run the 4-strategy `_best_of_strategies` (and the 2-mode `_modes_to_try` runs in bi grain) across multiple worker processes via `concurrent.futures.ProcessPoolExecutor`. Expose user-facing effort selector (5 levels):
  - `Eco / Off` → 1 worker (serial; current behaviour, maximum NFP-cache benefit)
  - `Low` → 2 workers
  - `Balanced` → `cpu_count // 2`
  - `High` → `cpu_count - 1` (leaves one core for UI/OS)
  - `Max` → `cpu_count` (may stutter the UI)

  Implementation notes:
  - Put the selector under **Settings → Preferences** (menu bar), not the sidebar Settings block — it's a workflow preference, not a layout input.
  - Show the resolved core count next to the slider (e.g. *"Uses ~3 of 8 CPU cores"*) so non-technical users can calibrate.
  - Skip pool spawn for tiny inputs (`pieces × strategies < ~20`); Windows process spawn is ~200–500 ms.
  - Per-request pool (created in `auto_layout_polygon`, torn down after) so memory returns to baseline between Runs.
  - Trade-off vs the NFP cache: each worker rebuilds its own cache, losing cross-strategy reuse. Net win is still positive for medium/large inputs but the combined speedup of cache+parallel is sub-multiplicative. Worth documenting in the slider's tooltip.

### Other deferred items (captured by the Phase 6 final reviewer)

- [ ] `GrainPanel.test.tsx` — was in the spec but never added; trivial vitest case for the new `Show grainline` checkbox + the `single/bi` radio set.
- [ ] `BottomPanel` overflow branch — currently unreachable from the NFP-BLF output (utilization is mathematically bounded by 100%). Either remove the branch or wire it to an engine-emitted warning when a piece's bbox edge exceeds usable fabric width.
- [ ] `useLayoutCache` on-mount `refresh()` — tabs currently start empty after a webview reload even if the engine still holds entries. One-shot mount effect would restore them.
- [ ] Cache `created_at` uses wall-clock `time.time()`; FIFO order could reverse under system-clock change. `time.monotonic()` would be more correct.
