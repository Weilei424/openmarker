# Phase 5 — Auto Layout Optimization (continuation)

> Successor design doc for PR #4. PR #4 (`auto-layout/masonw/strip-packing-grain`)
> shipped the auto-layout MVP: BLF → NFP-BLF, copies, per-set colors, live
> metrics, dotted marker-length line, manual-edit toggle, Stop button, engine
> cancellation. This document scopes the remaining UX redesign and bug
> fixes for a follow-up branch.
>
> **New worktree:** `auto-layout-optimization/masonw/<task-name>`
> **Parent:** `main` (after PR #4 lands)

---

## What shipped in PR #4

- NFP-based Bottom-Left-Fill using `pyclipper.MinkowskiSum` + Shapely
  `IFP.difference(NFP_union)`. Touching boundaries are allowed (area-based
  overlap check, eps 1e-3 mm²). Fallback to a forced new-shelf placement.
- Live `Metrics` panel: marker length + utilization bar, computed from current
  placements, clamped to 100% with "overflow" warning when pieces extend past
  fabric width.
- Multi-strategy sort (area / max-dim / height / width DESC); best result wins.
- Per-set coloring: `copies` input (1–20), 20-color palette (no black/white/yellow).
- Manual-edit toggle (off by default) disables piece dragging and the rotation
  handle.
- Stop button. `useAutoLayout` exposes `abort()` which both aborts the fetch
  AND posts `/cancel-layout` to the engine. Engine layout loop checks
  `is_cancelled()` between piece placements and raises `CancellationError`;
  endpoint returns HTTP 499 in that case. Computation runs via
  `run_in_threadpool` so `/cancel-layout` and `/ping` stay responsive.
- Coordinate-conversion fix: `engineToFrontendPlacement` iterates the actual
  polygon vertices to compute the unrotated-bbox top-left correctly for
  irregular shapes (the previous bbox-only formula was off for asymmetric
  pieces, causing false overlaps).
- Frontend SAT tolerance 0.5 mm to mask sub-mm float noise from the engine →
  Konva rotation chain.

## Open issues entering the next round

### 1. Border touching still flagged red on some inputs (Image #32)

Even after the conversion fix + 0.5 mm SAT tolerance + engine fallback. The
remaining cases are likely:

- Pieces with many vertices at large coordinates: cumulative float drift
  during rotation can exceed 0.5 mm.
- NFP edge artefacts: Shapely's polygon `difference` can produce tiny
  zero-width slivers at NFP-IFP intersections; the BLF vertex sweep may
  land on the sliver and report a position that, after rounding to 4
  decimals, sits a tiny amount inside an NFP.

Plan:

1. Add an explicit "verify placement" step in `_blf_pack_nfp`: after selecting
   a vertex, snap to integer mm grid (or 0.5 mm) and verify with Shapely that
   the resulting polygon's `intersection.area` with every placed piece is < eps.
2. Increase the engine's `_has_area_overlap` eps from `1e-3` to `0.5` mm² to
   match the frontend's visual tolerance.
3. Consider buffering NFPs by a tiny inward amount before differencing, so the
   valid region is strictly outside the NFP boundary.

### 2. "No valid position" failure on edge cases

PR #4 added a fallback. We still raise if no rotation fits the fabric width;
this is correct (the piece genuinely can't be placed) but the error path should
list which copy/rotation failed for easier diagnosis. Minor.

## New requirements for the optimization round

### 2.1 Top "piece library" panel

Always-visible horizontal strip across the top of the screen, showing every
imported piece **once** with its name (mirror of the ET-Mark UI in the
reference screenshot). Independent of placements and of `copies`. Acts as
the source-of-truth visual index.

Sketch:

```
+------------------------------------------------------------+
| [piece_a] [piece_b] [piece_c] ... [piece_z]                | ← top panel
+----+-------------------------------------------------------+
| L  |                                                       |
| E  |                                                       |
| F  |                  canvas                               |
| T  |                                                       |
|    |                                                       |
+----+-------------------------------------------------------+
| status bar                                                 |
+------------------------------------------------------------+
```

### 2.2 Don't render pieces on canvas until Auto Layout completes

Currently `usePlacements(pieces)` computes an initial single-row layout the
moment pieces import. New behavior:

- After import: placements is empty; canvas shows the empty fabric only.
- After successful auto-layout: placements set; canvas shows the layout.
- Reset Layout returns to the empty state (not back to the initial row).

This decouples the "library view" (top panel) from the "marker view" (canvas)
and removes the misleading >100% utilization on first import.

### 2.3 Rotate canvas 90° CCW (fabric grain points right)

Conceptual rotation only — the engine keeps its convention (X = fabric width
constraint, Y = length to minimize). The canvas applies a -90° transform so
that on screen:

- Fabric width = vertical extent (limited)
- Fabric length = horizontal extent (unlimited, extending to the right)
- Marker-length dotted line is a **vertical** line at engine `y = marker_length`
- Per-piece grain arrow points to the right
- Mouse coords are inverse-transformed for drag/selection

Approach: wrap the whole content layer in `<Group rotation={-90} y={fabricWidthMm} />`.
Engine output and placement math stay unchanged.

### 2.4 Click-to-select even with manual edit off

Currently disabling manual edit also disables `onClick` on PieceShape. New:

- `onClick` is always wired (regardless of `manualEditEnabled`).
- Dragging is gated by `manualEditEnabled`.
- Rotation handle is gated by `manualEditEnabled`.
- Clicking the same piece again, or clicking empty canvas, deselects it.
- Selection from PieceList sidebar continues to work.

## Out of scope (for this round)

- Switching the engine's internal convention to length-along-X. Pure rendering
  rotation is enough.
- Cross-set color customization. The 20-color palette stays as PR #4.
- Multi-process engine for true cancellation. The threadpool + cancel-flag
  approach in PR #4 is sufficient for our piece counts.

## File map (predicted)

| File | Change |
|---|---|
| `frontend/src/components/canvas/CanvasWorkspace.tsx` | Wrap content in rotated Group; vertical marker-length line; inverse-transform mouse positions |
| `frontend/src/components/PieceLibrary.tsx` (new) | Top panel showing all imported pieces with names |
| `frontend/src/app/App.tsx` | Mount PieceLibrary; suppress initial computed placements; selection-without-edit wiring |
| `frontend/src/hooks/usePlacements.ts` | Add an "empty initial" mode that doesn't call `computePlacements` on import |
| `frontend/src/components/canvas/PieceShape.tsx` | Decouple click/select from `editable` flag |
| `engine/core/layout/heuristic.py` | Bump `_has_area_overlap` eps; optional NFP buffer; placement verify step |

## Out-of-band: license posture remains Apache 2.0

The new work uses no third-party code. Algorithms continue to come from
Burke 2006 (BLF / NFP) — academic and uncopyrightable. `pyclipper` (MIT) and
Shapely (BSD) remain the only external geometry libs, already attributed.

---

## What actually shipped (post-mortem)

The original plan above held for the first half of PR #5. Subsequent
user-test rounds added scope and dropped scope. Final state:

### Delivered as planned

- Top panel (renamed `PreviewPanel`, was `PieceLibrary`) — outline-only SVG
  thumbnails so the shape is unambiguous (the first attempt filled the
  polygon, which looked like a separate "blue background shape" behind the
  outline).
- `usePlacements` starts empty; Reset Layout clears.
- Canvas rotated 90° CCW via `<Group rotation={-90} y={fabricWidthMm}>`. Engine
  math unchanged. New helper `computeFitViewportFromWorldBbox` for the
  Fit button and auto-fit on import / new layout.
- Click-to-select decoupled from edit. Re-click + empty-stage click both
  deselect. PieceList ↔ canvas selection sync by base id.
- Engine overlap eps raised from `1e-3` → `0.5` mm² (test `test_polygon_no_overlaps`
  updated to match).

### Added during the round

- **Bi-direction never worse than single.** Greedy NFP-BLF can produce a worse
  bi-mode layout than single-mode even though bi's rotation set is a strict
  superset of single's (a locally-good `target+180°` rotation can leave a worse
  global gap). `_modes_to_try("bi") → ["bi", "single"]` runs both and keeps
  the shorter marker. Same wrapper applied to bbox mode.
- **Topbar shows current import filename:** "OpenMarker — Working on
  sample_1.dxf".
- **Fabric width defaults to 1500 mm** and resets on every import (was
  auto-sizing to the initial single-row layout, which had no meaning after the
  "hide pieces until auto-layout" change).
- **PreviewPanel `fill="none"`** (was a translucent blue fill that, on irregular
  pieces, looked like a separate shape behind the outline).

### Removed during the round (originally planned to keep)

- **Frontend collision detection (entirely).** `useCollisions.ts`, `collisions.ts`,
  `collisions.test.ts`, `geometry.ts`, `geometry.test.ts` deleted. SAT was still
  flagging engine-placed pieces as colliding on edge cases (NFP slivers,
  conversion drift on pieces with many vertices at large coords). The engine
  owns placement validity; duplicating overlap detection on the frontend just
  produced false positives that contradicted the truth.
- **Manual editing (entirely).** Drag handlers, rotation handle, R-key
  rotation, "Enable manual edit on canvas" checkbox, `manualEditEnabled` state,
  `updatePlacement` from `usePlacements`, the `editable` prop on `PieceShape`,
  and the `isColliding` prop. Selection (click-to-highlight) is kept because it
  is not editing. ~270 lines deleted; ~9 lines added.

### Deferred / not done

- Placement-verify step inside `_blf_pack_nfp` (snap to grid + re-check
  Shapely intersection). Wasn't needed once collision detection was removed
  from the frontend — touching-flagged-red is gone because nothing flags
  touching anymore.
- NFP inward-buffer trick before differencing. Same reason.
- Multi-process engine. Not required for our piece counts.

### File map (final)

| File | Status | Notes |
|---|---|---|
| `frontend/src/components/PreviewPanel.tsx` | new (renamed from `PieceLibrary.tsx` via `git mv`) | Outline only |
| `frontend/src/utils/setColors.ts` | (existing, no change this round) | 20-color palette |
| `frontend/src/utils/placement.ts` | + `computeFitViewportFromWorldBbox` | For rotated canvas fit |
| `frontend/src/hooks/usePlacements.ts` | rewritten | Starts empty; no `updatePlacement` |
| `frontend/src/hooks/useCollisions.ts` | DELETED | |
| `frontend/src/utils/collisions.ts` | DELETED | |
| `frontend/src/utils/collisions.test.ts` | DELETED | |
| `frontend/src/utils/geometry.ts` | DELETED | Only consumer was `collisions.ts` |
| `frontend/src/utils/geometry.test.ts` | DELETED | |
| `frontend/src/components/canvas/PieceShape.tsx` | rewritten | No drag, no `isColliding`, no `editable` |
| `frontend/src/components/canvas/CanvasWorkspace.tsx` | rewritten | No drag/R-key/rotation-handle/useCollisions; layers wrapped in rotated Group |
| `frontend/src/app/App.tsx` | modified | No manual-edit UI; fabric default reset; topbar filename |
| `engine/core/layout/heuristic.py` | modified | overlap eps; `_modes_to_try` + `_shorter` for bi-fallback |
| `engine/tests/unit/test_heuristic.py` | modified | overlap assertion eps loosened to 0.5 mm² |
| `docs/planning/BACKLOG.md` | modified | Phase 4 marked as later-removed; Phase 5 optimization marked complete |
