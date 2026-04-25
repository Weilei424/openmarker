# Phase 4 — Manual Editing Design

**Date:** 2026-04-25
**Phase:** 4 of 7
**Status:** Approved

---

## Goal

Users can drag and rotate pieces on the Konva canvas. Placement state is tracked per piece. Overlapping pieces are highlighted in red in real time. No engine endpoints are needed.

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Rotation interaction | R key (90°) + rotation handle (free angle) | Keyboard is fast for 0°/90°; handle is discoverable for non-technical users |
| Collision detection | Frontend SAT (no engine endpoint) | Real-time feedback during drag; no HTTP latency |
| Snap | 10 mm grid, applied on drag-end | Matches existing GAP_MM constant; silent/behavioural only |
| Placement state location | `usePlacements` hook, called from App.tsx | App.tsx stays clean; Phase 5 auto-layout and Phase 6 export can read/write the same state |

---

## Data Model

### `types/canvas.ts`

Add `rotationDeg` to `Placement`:

```typescript
export interface Placement {
  pieceId: string;
  x: number;        // mm from workspace origin
  y: number;        // mm from workspace origin
  rotationDeg: number; // degrees, clockwise, normalised to [0, 360)
}
```

---

## New Files

### `hooks/usePlacements.ts`

Owns mutable placement state for all pieces.

```
usePlacements(pieces: Piece[]) → {
  placements: Placement[],
  updatePlacement(id: string, delta: Partial<Omit<Placement, 'pieceId'>>): void,
  resetPlacements(): void,
}
```

- Initialises from `computePlacements(pieces)` (adds `rotationDeg: 0`) whenever `pieces` reference changes.
- `updatePlacement` merges the delta into the matching placement by `pieceId`.
- `resetPlacements` re-runs `computePlacements(pieces)` and replaces state.

### `hooks/useCollisions.ts`

Returns the set of piece IDs that are currently overlapping at least one other piece.

```
useCollisions(placements: Placement[], pieces: Piece[]) → Set<string>
```

- Implemented as `useMemo` — recomputes synchronously whenever placements change.
- For each pair (i, j): transform both polygons (translate + rotate via `rotatePolygon` / `translatePolygon`), then run `polygonsIntersect`.
- Piece counts in this tool are small (typically < 100), so O(n²) is acceptable.

### `utils/geometry.ts`

Pure TypeScript geometry utilities. No external dependencies.

| Function | Signature | Purpose |
|----------|-----------|---------|
| `translatePolygon` | `(poly, dx, dy) → Point[]` | Translate all vertices |
| `rotatePolygon` | `(poly, deg, cx, cy) → Point[]` | Rotate vertices around a centre point |
| `getAxes` | `(poly) → Vector[]` | Edge-perpendicular normals for SAT |
| `projectOntoAxis` | `(poly, axis) → {min, max}` | Scalar projection for SAT |
| `polygonsIntersect` | `(polyA, polyB) → boolean` | SAT separating axis test |

Concave polygons are not fully handled by SAT — acceptable for Phase 4 since most garment pieces are convex or near-convex. A note in the source will document this limitation.

---

## Modified Files

### `utils/placement.ts`

- `computePlacements` returns `rotationDeg: 0` on each placement.
- Add `snapToGrid(value: number, grid = 10): number` → `Math.round(value / grid) * grid`.

### `components/canvas/PieceShape.tsx`

Refactored from a bare `<Line>` to a Konva `<Group>`.

**Structure:**
```
Group (draggable, positioned at placement.x, placement.y, rotated around bbox centre)
  └─ Line (polygon at local origin)
  └─ Circle (rotation handle — rendered only when isSelected)
  └─ Line (dashed handle connector — rendered only when isSelected)
```

**Drag behaviour:**
- `onDragEnd`: read `group.x(), group.y()` → `snapToGrid` both → call `onDragEnd(id, {x, y})`. React re-renders the group at the snapped position via `x/y` props; no manual position reset needed.
- Cursor: `grab` on hover, `grabbing` during drag.
- Clicking a piece selects it; dragging does not change selection.

**Rotation handle behaviour:**
- Handle circle positioned 24 px above bbox centre (in local coordinates).
- Handle is `draggable`.
- `onDragMove`: compute `angle = Math.atan2(handle.y − centre.y, handle.x − centre.x)` converted to degrees → call `onRotate(id, angle)`.
- `onDragEnd`: snap to nearest 5° → call `onRotate(id, snappedAngle)` → reset handle position.

**Rotation application:**
- Konva `Group.rotation(rotationDeg)` with `offsetX/offsetY` set to bbox centre so rotation is around the piece centre.

**Collision state:**
- `isColliding: boolean` prop.
- When `true`: `fill = "rgba(229, 57, 53, 0.25)"`, `stroke = "#e53935"`.
- Collision colour takes precedence over selection orange.

**Props:**
```typescript
interface Props {
  piece: Piece;
  placement: Placement;       // now includes rotationDeg
  isSelected: boolean;
  isColliding: boolean;       // new
  onSelect: () => void;
  onDragEnd: (id: string, pos: { x: number; y: number }) => void;  // new
  onRotate: (id: string, deg: number) => void;                     // new
}
```

### `components/canvas/CanvasWorkspace.tsx`

- Props extended: receives `placements: Placement[]` and `updatePlacement` from App.
- Removes local `useMemo(() => computePlacements(...))` — placements now come from props.
- Calls `useCollisions(placements, pieces)` to get `collidingIds`.
- Adds `window` `keydown` listener (registered/removed via `useEffect`):
  - Key `r` or `R` with `selectedPieceId !== null` → `updatePlacement(selectedPieceId, { rotationDeg: (current + 90) % 360 })`.
- Passes `isColliding={collidingIds.has(piece.id)}`, `onDragEnd`, `onRotate` to each `PieceShape`.

### `app/App.tsx`

- Calls `usePlacements(pieces)` → destructures `placements`, `updatePlacement`, `resetPlacements`.
- Passes `placements` and `updatePlacement` to `CanvasWorkspace`.
- Removes `const placements = useMemo(...)` (now in the hook).

---

## Tests

| File | Cases |
|------|-------|
| `utils/geometry.test.ts` | Overlapping squares → true; touching edges → false; separated → false; one polygon inside another → true; rotated pieces overlapping → true |
| `hooks/usePlacements.test.ts` | Initialises from pieces with rotationDeg 0; updatePlacement merges x/y/rotationDeg; resetPlacements re-initialises on pieces change |
| `utils/placement.test.ts` | snapToGrid: 14→10, 15→20, 0→0, negative values |

---

## Out of Scope for Phase 4

- Visual grid lines on canvas (snap is silent)
- Undo / redo
- Piece-to-piece snapping (snap to edges)
- Fabric boundary clamping (pieces can be dragged outside fabric bounds)
- Collision detection for concave polygons (SAT limitation — noted in source)
