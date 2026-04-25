# Phase 4 — Manual Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users can drag and rotate pieces on the Konva canvas; placement state is tracked per piece; overlapping pieces are highlighted in red; snap-to-grid is applied on drag-end.

**Architecture:** A `usePlacements` hook (called from `App.tsx`) owns `{ x, y, rotationDeg }` per piece. `CanvasWorkspace` receives placements as props and renders draggable `PieceShape` Groups. Collision detection runs in-browser as a pure SAT utility called from a `useCollisions` hook. No new engine endpoints.

**Tech Stack:** React 18, TypeScript 5, react-konva 18, Konva 9, Vitest 1, @testing-library/react

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/types/canvas.ts` | Modify | Add `rotationDeg: number` to `Placement` |
| `frontend/src/utils/placement.ts` | Modify | Add `snapToGrid`; `computePlacements` returns `rotationDeg: 0` |
| `frontend/src/utils/placement.test.ts` | Modify | Update tests for new `rotationDeg` field; add `snapToGrid` cases |
| `frontend/src/utils/geometry.ts` | Create | Pure SAT geometry: `translatePolygon`, `rotatePolygon`, `polygonsIntersect` |
| `frontend/src/utils/geometry.test.ts` | Create | TDD tests for all geometry functions |
| `frontend/src/utils/collisions.ts` | Create | Pure `computeCollidingIds(placements, pieces)` using geometry utilities |
| `frontend/src/utils/collisions.test.ts` | Create | TDD tests for collision pair detection |
| `frontend/src/hooks/usePlacements.ts` | Create | React state: init/update/reset placements |
| `frontend/src/hooks/usePlacements.test.ts` | Create | Hook tests using `renderHook` |
| `frontend/src/hooks/useCollisions.ts` | Create | `useMemo` wrapper around `computeCollidingIds` |
| `frontend/src/components/canvas/PieceShape.tsx` | Modify | Konva Group: drag + snap + rotation + collision fill |
| `frontend/src/components/canvas/CanvasWorkspace.tsx` | Modify | Receive placements props; R key listener; rotation handle; pass `isColliding` |
| `frontend/src/app/App.tsx` | Modify | Call `usePlacements`; pass `placements`/`updatePlacement` to canvas |
| `frontend/vite.config.ts` | Modify | Add vitest `environment: 'jsdom'` for hook tests |

---

## Task 0: Worktree setup

- [ ] **Step 1: Create the worktree**

```bash
git worktree add .worktrees/manual-editing/masonw/drag-rotate manual-editing/masonw/drag-rotate 2>/dev/null \
  || git worktree add .worktrees/manual-editing/masonw/drag-rotate -b manual-editing/masonw/drag-rotate
```

- [ ] **Step 2: All subsequent steps run from the worktree**

```bash
cd .worktrees/manual-editing/masonw/drag-rotate
```

Verify: `git branch --show-current` → `manual-editing/masonw/drag-rotate`

---

## Task 1: Placement type + snapToGrid utility

**Files:**
- Modify: `frontend/src/types/canvas.ts`
- Modify: `frontend/src/utils/placement.ts`
- Modify: `frontend/src/utils/placement.test.ts`

- [ ] **Step 1: Add `rotationDeg` to the Placement type**

Replace the entire contents of `frontend/src/types/canvas.ts`:

```typescript
// Canvas/viewport types for the visual workspace (Phase 3+).

export interface Placement {
  pieceId: string;
  x: number;           // mm — top-left of unrotated bbox from workspace origin
  y: number;           // mm — top-left of unrotated bbox from workspace origin
  rotationDeg: number; // degrees clockwise, normalised to [0, 360)
}

export interface ViewportTransform {
  scale: number; // pixels per mm
  x: number;     // Stage pixel offset X
  y: number;     // Stage pixel offset Y
}
```

- [ ] **Step 2: Update `computePlacements` to include `rotationDeg`, add `snapToGrid`**

Replace the entire contents of `frontend/src/utils/placement.ts`:

```typescript
import type { Piece } from "../types/engine";
import type { Placement, ViewportTransform } from "../types/canvas";

const GAP_MM = 10;

export function snapToGrid(value: number, grid = 10): number {
  return Math.round(value / grid) * grid;
}

/**
 * Arrange pieces left-to-right in a horizontal strip with a gap between each.
 * All pieces start at y=GAP_MM. Returns rotationDeg: 0 for all pieces.
 */
export function computePlacements(pieces: Piece[]): Placement[] {
  const placements: Placement[] = [];
  let cursorX = GAP_MM;

  for (const piece of pieces) {
    placements.push({ pieceId: piece.id, x: cursorX, y: GAP_MM, rotationDeg: 0 });
    cursorX += piece.bbox.width + GAP_MM;
  }

  return placements;
}

/**
 * Compute a scale + offset so all placed pieces fit within the stage with
 * 10% padding on each side.
 */
export function computeFitViewport(
  placements: Placement[],
  pieces: Piece[],
  stageW: number,
  stageH: number
): ViewportTransform {
  if (placements.length === 0 || stageW <= 0 || stageH <= 0) {
    return { scale: 1, x: 0, y: 0 };
  }

  const pieceMap = new Map(pieces.map((p) => [p.id, p]));

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  for (const pl of placements) {
    const piece = pieceMap.get(pl.pieceId);
    if (!piece) continue;
    minX = Math.min(minX, pl.x);
    minY = Math.min(minY, pl.y);
    maxX = Math.max(maxX, pl.x + piece.bbox.width);
    maxY = Math.max(maxY, pl.y + piece.bbox.height);
  }

  const totalW = maxX - minX;
  const totalH = maxY - minY;

  if (totalW <= 0 || totalH <= 0) {
    return { scale: 1, x: 0, y: 0 };
  }

  const scaleX = (stageW * 0.8) / totalW;
  const scaleY = (stageH * 0.8) / totalH;
  const scale = Math.min(scaleX, scaleY);

  const contentPxW = totalW * scale;
  const contentPxH = totalH * scale;
  const offsetX = (stageW - contentPxW) / 2 - minX * scale;
  const offsetY = (stageH - contentPxH) / 2 - minY * scale;

  return { scale, x: offsetX, y: offsetY };
}
```

- [ ] **Step 3: Update placement tests for `rotationDeg` + add `snapToGrid` cases**

Replace the entire contents of `frontend/src/utils/placement.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { computePlacements, computeFitViewport, snapToGrid } from "./placement";
import type { Piece } from "../types/engine";

function makePiece(id: string, width: number, height: number): Piece {
  return {
    id,
    name: id,
    polygon: [
      [0, 0],
      [width, 0],
      [width, height],
      [0, height],
    ],
    area: width * height,
    bbox: { min_x: 0, min_y: 0, max_x: width, max_y: height, width, height },
    is_valid: true,
    validation_notes: [],
  };
}

describe("snapToGrid", () => {
  it("snaps down when below midpoint", () => {
    expect(snapToGrid(14)).toBe(10);
  });
  it("snaps up when at or above midpoint", () => {
    expect(snapToGrid(15)).toBe(20);
  });
  it("returns 0 unchanged", () => {
    expect(snapToGrid(0)).toBe(0);
  });
  it("snaps negative values", () => {
    expect(snapToGrid(-14)).toBe(-10);
    expect(snapToGrid(-15)).toBe(-20);
  });
  it("respects custom grid size", () => {
    expect(snapToGrid(7, 5)).toBe(5);
    expect(snapToGrid(8, 5)).toBe(10);
  });
});

describe("computePlacements", () => {
  it("places single piece at (GAP_MM, GAP_MM) with rotationDeg 0", () => {
    const piece = makePiece("A", 100, 200);
    const result = computePlacements([piece]);
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ pieceId: "A", x: 10, y: 10, rotationDeg: 0 });
  });

  it("places second piece after first width + gap", () => {
    const p1 = makePiece("A", 100, 200);
    const p2 = makePiece("B", 50, 80);
    const result = computePlacements([p1, p2]);
    expect(result[0]).toEqual({ pieceId: "A", x: 10, y: 10, rotationDeg: 0 });
    expect(result[1]).toEqual({ pieceId: "B", x: 120, y: 10, rotationDeg: 0 });
  });

  it("returns empty array for no pieces", () => {
    expect(computePlacements([])).toEqual([]);
  });
});

describe("computeFitViewport", () => {
  it("returns default transform for empty placements", () => {
    const vp = computeFitViewport([], [], 800, 600);
    expect(vp).toEqual({ scale: 1, x: 0, y: 0 });
  });

  it("fits a single piece to stage with centering", () => {
    const piece = makePiece("A", 100, 200);
    const placements = [{ pieceId: "A", x: 10, y: 10, rotationDeg: 0 }];
    const vp = computeFitViewport(placements, [piece], 800, 600);
    expect(vp.scale).toBeCloseTo(2.4);
    expect(vp.x).toBeCloseTo(256);
    expect(vp.y).toBeCloseTo(36);
  });

  it("picks the smaller of scaleX/scaleY", () => {
    const piece = makePiece("A", 1000, 10);
    const placements = [{ pieceId: "A", x: 0, y: 0, rotationDeg: 0 }];
    const vp = computeFitViewport(placements, [piece], 800, 600);
    expect(vp.scale).toBeCloseTo(0.64);
  });
});
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd frontend && npm run test
```

Expected: all tests pass (snapToGrid cases + updated computePlacements/computeFitViewport)

- [ ] **Step 5: Commit**

```
feat(canvas): add rotationDeg to Placement type and snapToGrid utility
```

---

## Task 2: Geometry utilities

**Files:**
- Create: `frontend/src/utils/geometry.ts`
- Create: `frontend/src/utils/geometry.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/utils/geometry.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import {
  translatePolygon,
  rotatePolygon,
  polygonsIntersect,
} from "./geometry";

type Point = [number, number];

// Unit square at origin
const square: Point[] = [[0,0],[1,0],[1,1],[0,1]];

describe("translatePolygon", () => {
  it("shifts all vertices by dx, dy", () => {
    const result = translatePolygon(square, 5, 10);
    expect(result).toEqual([[5,10],[6,10],[6,11],[5,11]]);
  });

  it("handles zero translation", () => {
    expect(translatePolygon(square, 0, 0)).toEqual(square);
  });
});

describe("rotatePolygon", () => {
  it("rotates 90° CW around origin", () => {
    // In screen coords (y-down), Konva CW rotation: (x,y) → (-y, x) at 90°
    // Formula: x' = x·cosθ - y·sinθ,  y' = x·sinθ + y·cosθ
    // For θ=90°, cos=0, sin=1: x'=-y, y'=x
    // For point (1,0): x'=0, y'=1 → (0,1) — point moves "down" which is CW in screen
    const result = rotatePolygon([[1, 0]], 90, 0, 0);
    expect(result[0][0]).toBeCloseTo(0);
    expect(result[0][1]).toBeCloseTo(1);
  });

  it("rotates 90° CW around center (0.5, 0.5)", () => {
    const result = rotatePolygon(square, 90, 0.5, 0.5);
    // (0,0) → translate → (-0.5,-0.5) → CW 90° → (0.5,-0.5) → translate back → (1, 0)
    expect(result[0][0]).toBeCloseTo(1);
    expect(result[0][1]).toBeCloseTo(0);
  });

  it("0° rotation returns same points", () => {
    const result = rotatePolygon(square, 0, 0, 0);
    result.forEach(([x, y], i) => {
      expect(x).toBeCloseTo(square[i][0]);
      expect(y).toBeCloseTo(square[i][1]);
    });
  });
});

describe("polygonsIntersect", () => {
  it("returns true for overlapping squares", () => {
    const a: Point[] = [[0,0],[2,0],[2,2],[0,2]];
    const b: Point[] = [[1,1],[3,1],[3,3],[1,3]];
    expect(polygonsIntersect(a, b)).toBe(true);
  });

  it("returns false for separated squares", () => {
    const a: Point[] = [[0,0],[1,0],[1,1],[0,1]];
    const b: Point[] = [[2,0],[3,0],[3,1],[2,1]];
    expect(polygonsIntersect(a, b)).toBe(false);
  });

  it("returns false for touching-edge squares (not overlapping)", () => {
    const a: Point[] = [[0,0],[1,0],[1,1],[0,1]];
    const b: Point[] = [[1,0],[2,0],[2,1],[1,1]];
    expect(polygonsIntersect(a, b)).toBe(false);
  });

  it("returns true when one polygon is inside another", () => {
    const outer: Point[] = [[0,0],[10,0],[10,10],[0,10]];
    const inner: Point[] = [[2,2],[4,2],[4,4],[2,4]];
    expect(polygonsIntersect(outer, inner)).toBe(true);
  });

  it("returns true for rotated overlapping pieces", () => {
    // Two rectangles overlapping after one is rotated
    const a: Point[] = [[0,0],[4,0],[4,1],[0,1]];
    // b is a 4x1 rectangle rotated ~45° — its AABB overlaps a
    const b: Point[] = [[1,1],[3,-1],[4,0],[2,2]];
    expect(polygonsIntersect(a, b)).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd frontend && npm run test -- geometry
```

Expected: FAIL — "Cannot find module './geometry'"

- [ ] **Step 3: Implement geometry utilities**

Create `frontend/src/utils/geometry.ts`:

```typescript
type Point = [number, number];
type Vector = [number, number];

export function translatePolygon(poly: Point[], dx: number, dy: number): Point[] {
  return poly.map(([x, y]) => [x + dx, y + dy]);
}

/**
 * Rotate polygon vertices deg° clockwise around (cx, cy).
 * Formula: x' = tx·cosθ − ty·sinθ,  y' = tx·sinθ + ty·cosθ
 * Matches Konva's convention: positive angles are CW in screen space (y increases downward).
 */
export function rotatePolygon(poly: Point[], deg: number, cx: number, cy: number): Point[] {
  const rad = (deg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  return poly.map(([x, y]) => {
    const tx = x - cx;
    const ty = y - cy;
    return [tx * cos - ty * sin + cx, tx * sin + ty * cos + cy];
  });
}

function getAxes(poly: Point[]): Vector[] {
  const axes: Vector[] = [];
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    // Edge perpendicular (normal)
    axes.push([-(y2 - y1), x2 - x1]);
  }
  return axes;
}

function project(poly: Point[], axis: Vector): { min: number; max: number } {
  const len = Math.sqrt(axis[0] ** 2 + axis[1] ** 2);
  if (len === 0) return { min: 0, max: 0 };
  const nx = axis[0] / len;
  const ny = axis[1] / len;
  const dots = poly.map(([x, y]) => x * nx + y * ny);
  return { min: Math.min(...dots), max: Math.max(...dots) };
}

/**
 * Separating Axis Theorem intersection test.
 * Returns true if the polygons overlap (touching edges = false).
 * NOTE: SAT is exact for convex polygons. Concave polygons may produce
 * false negatives — acceptable for Phase 4 where most pieces are near-convex.
 */
export function polygonsIntersect(polyA: Point[], polyB: Point[]): boolean {
  const axes = [...getAxes(polyA), ...getAxes(polyB)];
  for (const axis of axes) {
    const a = project(polyA, axis);
    const b = project(polyB, axis);
    // Strict inequality: touching edges are not considered overlapping
    if (a.max <= b.min || b.max <= a.min) return false;
  }
  return true;
}
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd frontend && npm run test -- geometry
```

Expected: all geometry tests pass

- [ ] **Step 5: Commit**

```
feat(geometry): add SAT polygon intersection utilities
```

---

## Task 3: Collision detection utility

**Files:**
- Create: `frontend/src/utils/collisions.ts`
- Create: `frontend/src/utils/collisions.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/utils/collisions.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { computeCollidingIds } from "./collisions";
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";

function makePiece(id: string, w: number, h: number): Piece {
  return {
    id,
    name: id,
    polygon: [[0,0],[w,0],[w,h],[0,h]] as [number,number][],
    area: w * h,
    bbox: { min_x: 0, min_y: 0, max_x: w, max_y: h, width: w, height: h },
    is_valid: true,
    validation_notes: [],
  };
}

function makePlacement(pieceId: string, x: number, y: number, rotationDeg = 0): Placement {
  return { pieceId, x, y, rotationDeg };
}

describe("computeCollidingIds", () => {
  it("returns empty set when no pieces", () => {
    expect(computeCollidingIds([], [])).toEqual(new Set());
  });

  it("returns empty set for a single piece", () => {
    const pieces = [makePiece("A", 100, 100)];
    const placements = [makePlacement("A", 0, 0)];
    expect(computeCollidingIds(placements, pieces)).toEqual(new Set());
  });

  it("returns empty set for non-overlapping pieces", () => {
    const pieces = [makePiece("A", 100, 100), makePiece("B", 100, 100)];
    const placements = [makePlacement("A", 0, 0), makePlacement("B", 200, 0)];
    expect(computeCollidingIds(placements, pieces)).toEqual(new Set());
  });

  it("returns both IDs when pieces overlap", () => {
    const pieces = [makePiece("A", 100, 100), makePiece("B", 100, 100)];
    // B placed at x=50 overlaps A by 50mm
    const placements = [makePlacement("A", 0, 0), makePlacement("B", 50, 0)];
    const result = computeCollidingIds(placements, pieces);
    expect(result).toEqual(new Set(["A", "B"]));
  });

  it("only returns the colliding pair, not uninvolved pieces", () => {
    const pieces = [makePiece("A", 100, 100), makePiece("B", 100, 100), makePiece("C", 100, 100)];
    const placements = [
      makePlacement("A", 0, 0),
      makePlacement("B", 50, 0),   // overlaps A
      makePlacement("C", 500, 0),  // far away
    ];
    const result = computeCollidingIds(placements, pieces);
    expect(result.has("A")).toBe(true);
    expect(result.has("B")).toBe(true);
    expect(result.has("C")).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd frontend && npm run test -- collisions
```

Expected: FAIL — "Cannot find module './collisions'"

- [ ] **Step 3: Implement the collision utility**

Create `frontend/src/utils/collisions.ts`:

```typescript
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";
import { polygonsIntersect, translatePolygon, rotatePolygon } from "./geometry";

type Point = [number, number];

function transformedPolygon(piece: Piece, pl: Placement): Point[] {
  const cx = piece.bbox.width / 2;
  const cy = piece.bbox.height / 2;
  let poly = piece.polygon as Point[];
  if (pl.rotationDeg !== 0) {
    poly = rotatePolygon(poly, pl.rotationDeg, cx, cy);
  }
  return translatePolygon(poly, pl.x, pl.y);
}

export function computeCollidingIds(placements: Placement[], pieces: Piece[]): Set<string> {
  const collidingIds = new Set<string>();
  const pieceMap = new Map(pieces.map((p) => [p.id, p]));

  const transformed = placements
    .map((pl) => {
      const piece = pieceMap.get(pl.pieceId);
      return piece ? { pieceId: pl.pieceId, poly: transformedPolygon(piece, pl) } : null;
    })
    .filter((x): x is { pieceId: string; poly: Point[] } => x !== null);

  for (let i = 0; i < transformed.length; i++) {
    for (let j = i + 1; j < transformed.length; j++) {
      if (polygonsIntersect(transformed[i].poly, transformed[j].poly)) {
        collidingIds.add(transformed[i].pieceId);
        collidingIds.add(transformed[j].pieceId);
      }
    }
  }

  return collidingIds;
}
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd frontend && npm run test -- collisions
```

Expected: all collision tests pass

- [ ] **Step 5: Commit**

```
feat(collisions): add computeCollidingIds pure utility
```

---

## Task 4: `usePlacements` hook

**Files:**
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/hooks/usePlacements.ts`
- Create: `frontend/src/hooks/usePlacements.test.ts`

- [ ] **Step 1: Install testing dependencies for React hooks**

```bash
cd frontend && npm install --save-dev @testing-library/react jsdom
```

- [ ] **Step 2: Add vitest environment config to `vite.config.ts`**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    host: host || false,
    port: 1420,
    strictPort: true,
    hmr: host
      ? { protocol: "ws", host, port: 1421 }
      : undefined,
  },
  build: {
    target: ["es2021", "chrome100", "safari13"],
    minify: !process.env.TAURI_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_DEBUG,
  },
  envPrefix: ["VITE_", "TAURI_"],
  test: {
    environment: "jsdom",
  },
});
```

- [ ] **Step 3: Write failing hook tests**

Create `frontend/src/hooks/usePlacements.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePlacements } from "./usePlacements";
import type { Piece } from "../types/engine";

function makePiece(id: string, w: number, h: number): Piece {
  return {
    id,
    name: id,
    polygon: [[0,0],[w,0],[w,h],[0,h]] as [number,number][],
    area: w * h,
    bbox: { min_x: 0, min_y: 0, max_x: w, max_y: h, width: w, height: h },
    is_valid: true,
    validation_notes: [],
  };
}

describe("usePlacements", () => {
  it("initialises placements from pieces with rotationDeg 0", () => {
    const pieces = [makePiece("A", 100, 200)];
    const { result } = renderHook(() => usePlacements(pieces));
    expect(result.current.placements).toHaveLength(1);
    expect(result.current.placements[0].rotationDeg).toBe(0);
    expect(result.current.placements[0].pieceId).toBe("A");
  });

  it("updatePlacement merges x and y", () => {
    const pieces = [makePiece("A", 100, 200)];
    const { result } = renderHook(() => usePlacements(pieces));
    act(() => {
      result.current.updatePlacement("A", { x: 300, y: 50 });
    });
    expect(result.current.placements[0].x).toBe(300);
    expect(result.current.placements[0].y).toBe(50);
    expect(result.current.placements[0].rotationDeg).toBe(0); // unchanged
  });

  it("updatePlacement merges rotationDeg", () => {
    const pieces = [makePiece("A", 100, 200)];
    const { result } = renderHook(() => usePlacements(pieces));
    act(() => {
      result.current.updatePlacement("A", { rotationDeg: 90 });
    });
    expect(result.current.placements[0].rotationDeg).toBe(90);
    expect(result.current.placements[0].x).toBe(10); // unchanged (GAP_MM)
  });

  it("updatePlacement ignores unknown pieceId", () => {
    const pieces = [makePiece("A", 100, 200)];
    const { result } = renderHook(() => usePlacements(pieces));
    const before = result.current.placements[0].x;
    act(() => {
      result.current.updatePlacement("Z", { x: 999 });
    });
    expect(result.current.placements[0].x).toBe(before);
  });

  it("re-initialises when pieces reference changes", () => {
    const piecesV1 = [makePiece("A", 100, 200)];
    const { result, rerender } = renderHook(({ pieces }) => usePlacements(pieces), {
      initialProps: { pieces: piecesV1 },
    });
    act(() => {
      result.current.updatePlacement("A", { x: 999 });
    });
    expect(result.current.placements[0].x).toBe(999);

    // New pieces reference triggers re-init
    const piecesV2 = [makePiece("A", 100, 200)];
    rerender({ pieces: piecesV2 });
    expect(result.current.placements[0].x).toBe(10); // back to GAP_MM
  });
});
```

- [ ] **Step 4: Run tests — confirm they fail**

```bash
cd frontend && npm run test -- usePlacements
```

Expected: FAIL — "Cannot find module './usePlacements'"

- [ ] **Step 5: Implement `usePlacements`**

Create `frontend/src/hooks/usePlacements.ts`:

```typescript
import { useState, useEffect } from "react";
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";
import { computePlacements } from "../utils/placement";

export function usePlacements(pieces: Piece[]) {
  const [placements, setPlacements] = useState<Placement[]>(() =>
    computePlacements(pieces)
  );

  // Re-initialise whenever a new set of pieces arrives.
  useEffect(() => {
    setPlacements(computePlacements(pieces));
  }, [pieces]);

  function updatePlacement(
    id: string,
    delta: Partial<Omit<Placement, "pieceId">>
  ) {
    setPlacements((prev) =>
      prev.map((p) => (p.pieceId === id ? { ...p, ...delta } : p))
    );
  }

  function resetPlacements() {
    setPlacements(computePlacements(pieces));
  }

  return { placements, updatePlacement, resetPlacements };
}
```

- [ ] **Step 6: Run tests — all should pass**

```bash
cd frontend && npm run test -- usePlacements
```

Expected: all usePlacements tests pass

- [ ] **Step 7: Create `useCollisions` hook**

Create `frontend/src/hooks/useCollisions.ts`:

```typescript
import { useMemo } from "react";
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";
import { computeCollidingIds } from "../utils/collisions";

export function useCollisions(placements: Placement[], pieces: Piece[]): Set<string> {
  return useMemo(() => computeCollidingIds(placements, pieces), [placements, pieces]);
}
```

- [ ] **Step 8: Run all tests**

```bash
cd frontend && npm run test
```

Expected: all tests pass

- [ ] **Step 9: Commit**

```
feat(hooks): add usePlacements and useCollisions hooks
```

---

## Task 5: Wire `usePlacements` into App + CanvasWorkspace

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/components/canvas/CanvasWorkspace.tsx`

- [ ] **Step 1: Update `CanvasWorkspace` props to receive placements from outside**

Replace `frontend/src/components/canvas/CanvasWorkspace.tsx`:

```tsx
// Main Konva canvas component for the visual workspace.
// Renders fabric bounds, placed piece outlines, and handles zoom/pan.

import { useRef, useState, useEffect } from "react";
import { Stage, Layer, Rect, Line } from "react-konva";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";
import { useViewport } from "../../hooks/useViewport";
import { PieceShape } from "./PieceShape";
import { ViewportControls } from "./ViewportControls";

const FABRIC_HEIGHT_MM = 99_000;

interface Props {
  pieces: Piece[];
  placements: Placement[];
  updatePlacement: (id: string, delta: Partial<Omit<Placement, "pieceId">>) => void;
  selectedPieceId: string | null;
  onSelectPiece: (id: string | null) => void;
  fabricWidthMm: number;
}

export function CanvasWorkspace({
  pieces,
  placements,
  updatePlacement,
  selectedPieceId,
  onSelectPiece,
  fabricWidthMm,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [stageSize, setStageSize] = useState({ w: 800, h: 600 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setStageSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { transform, setTransform, handleWheel, fitToContent, zoomIn, zoomOut } =
    useViewport();

  useEffect(() => {
    if (pieces.length === 0) return;
    const id = setTimeout(() => {
      fitToContent(placements, pieces, stageSize.w, stageSize.h);
    }, 0);
    return () => clearTimeout(id);
  }, [pieces]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleFit = () => {
    fitToContent(placements, pieces, stageSize.w, stageSize.h);
  };

  return (
    <div ref={containerRef} style={styles.container}>
      <Stage
        width={stageSize.w}
        height={stageSize.h}
        draggable
        scaleX={transform.scale}
        scaleY={transform.scale}
        x={transform.x}
        y={transform.y}
        onWheel={handleWheel}
        onDragEnd={(e) => {
          setTransform((t) => ({ ...t, x: e.target.x(), y: e.target.y() }));
        }}
        onClick={(e) => {
          if (e.target === e.target.getStage()) onSelectPiece(null);
        }}
      >
        <Layer listening={false}>
          <Rect
            x={0}
            y={0}
            width={fabricWidthMm}
            height={FABRIC_HEIGHT_MM}
            fill="rgba(255,255,255,0.04)"
            stroke="#333"
            strokeWidth={1}
          />
          <Line
            points={[fabricWidthMm, 0, fabricWidthMm, FABRIC_HEIGHT_MM]}
            stroke="#555"
            strokeWidth={1}
          />
        </Layer>

        <Layer>
          {placements.map((pl) => {
            const piece = pieces.find((p) => p.id === pl.pieceId);
            if (!piece) return null;
            return (
              <PieceShape
                key={piece.id}
                piece={piece}
                placement={pl}
                isSelected={piece.id === selectedPieceId}
                isColliding={false}
                onSelect={() => onSelectPiece(piece.id)}
                onDragEnd={(id, pos) => updatePlacement(id, pos)}
              />
            );
          })}
        </Layer>
      </Stage>

      <ViewportControls
        scale={transform.scale}
        onFit={handleFit}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
      />
    </div>
  );
}

const styles = {
  container: {
    position: "relative" as const,
    width: "100%",
    height: "100%",
    overflow: "hidden",
    background: "#111",
  },
} as const;
```

- [ ] **Step 2: Update `App.tsx` to use `usePlacements`**

In `frontend/src/app/App.tsx`, make these targeted changes:

Add import at top:
```typescript
import { usePlacements } from "../hooks/usePlacements";
```

Inside the `App` component, replace the `CanvasWorkspace` invocation. First, add after the `useImportDxf` line:
```typescript
const { placements, updatePlacement } = usePlacements(pieces);
```

Then update the `CanvasWorkspace` JSX to pass the new props:
```tsx
<CanvasWorkspace
  pieces={pieces}
  placements={placements}
  updatePlacement={updatePlacement}
  selectedPieceId={selectedPieceId}
  onSelectPiece={setSelectedPieceId}
  fabricWidthMm={fabricWidthMm}
/>
```

- [ ] **Step 3: Update `PieceShape` signature to accept `isColliding` and `onDragEnd` (stubs)**

Replace the entire contents of `frontend/src/components/canvas/PieceShape.tsx` with this intermediate version (drag and rotation in next tasks):

```tsx
// Renders a single pattern piece as a Konva Group (closed polygon).
// Click to select; drag to reposition; rotation handle when selected.

import { Line } from "react-konva";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";

interface Props {
  piece: Piece;
  placement: Placement;
  isSelected: boolean;
  isColliding: boolean;
  onSelect: () => void;
  onDragEnd: (id: string, pos: { x: number; y: number }) => void;
}

export function PieceShape({ piece, placement, isSelected, isColliding, onSelect }: Props) {
  const stroke = isColliding ? "#e53935" : isSelected ? "#ff9800" : "#4a9eff";
  const fill = isColliding
    ? "rgba(229, 57, 53, 0.25)"
    : isSelected
    ? "rgba(255, 152, 0, 0.12)"
    : "rgba(74, 158, 255, 0.08)";

  const points = piece.polygon.flatMap(([x, y]) => [placement.x + x, placement.y + y]);

  return (
    <Line
      points={points}
      closed={true}
      stroke={stroke}
      fill={fill}
      strokeWidth={1}
      strokeScaleEnabled={false}
      onClick={onSelect}
      onTap={onSelect}
      onMouseEnter={(e) => {
        const container = e.target.getStage()?.container();
        if (container) container.style.cursor = "pointer";
      }}
      onMouseLeave={(e) => {
        const container = e.target.getStage()?.container();
        if (container) container.style.cursor = "default";
      }}
    />
  );
}
```

- [ ] **Step 4: Run all tests — should pass**

```bash
cd frontend && npm run test
```

Expected: all tests pass. The app compiles and pieces render on canvas as before.

- [ ] **Step 5: Commit**

```
refactor(canvas): thread usePlacements through App and CanvasWorkspace
```

---

## Task 6: `PieceShape` — draggable Group with snap

**Files:**
- Modify: `frontend/src/components/canvas/PieceShape.tsx`

- [ ] **Step 1: Rewrite `PieceShape` as a draggable Konva `Group`**

Replace `frontend/src/components/canvas/PieceShape.tsx`:

```tsx
// Renders a single pattern piece as a draggable Konva Group.
// Drag repositions the piece (snapped to 10 mm grid).
// Selected pieces show an orange outline; colliding pieces show red.

import { Group, Line } from "react-konva";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";
import { snapToGrid } from "../../utils/placement";

interface Props {
  piece: Piece;
  placement: Placement;
  isSelected: boolean;
  isColliding: boolean;
  onSelect: () => void;
  onDragEnd: (id: string, pos: { x: number; y: number }) => void;
}

export function PieceShape({
  piece,
  placement,
  isSelected,
  isColliding,
  onSelect,
  onDragEnd,
}: Props) {
  const stroke = isColliding ? "#e53935" : isSelected ? "#ff9800" : "#4a9eff";
  const fill = isColliding
    ? "rgba(229, 57, 53, 0.25)"
    : isSelected
    ? "rgba(255, 152, 0, 0.12)"
    : "rgba(74, 158, 255, 0.08)";

  // Polygon points in Group-local coordinates (piece is at origin)
  const flatPoints = piece.polygon.flatMap(([x, y]) => [x, y]);

  // Group is placed at the bbox center with offsetX/offsetY so rotation
  // is around the centre. placement.x/y is the top-left of the unrotated bbox.
  const cx = piece.bbox.width / 2;
  const cy = piece.bbox.height / 2;

  const handleDragEnd = (e: KonvaEventObject<DragEvent>) => {
    // Group position after drag: (placement.x + cx + drag_delta_x, placement.y + cy + drag_delta_y)
    // Recover top-left: subtract cx/cy, then snap.
    const rawX = e.target.x() - cx;
    const rawY = e.target.y() - cy;
    onDragEnd(piece.id, { x: snapToGrid(rawX), y: snapToGrid(rawY) });
  };

  const handleMouseEnter = (e: KonvaEventObject<MouseEvent>) => {
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "grab";
  };

  const handleMouseLeave = (e: KonvaEventObject<MouseEvent>) => {
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "default";
  };

  const handleDragStart = (e: KonvaEventObject<DragEvent>) => {
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "grabbing";
  };

  return (
    <Group
      x={placement.x + cx}
      y={placement.y + cy}
      offsetX={cx}
      offsetY={cy}
      rotation={placement.rotationDeg}
      draggable
      onClick={onSelect}
      onTap={onSelect}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <Line
        points={flatPoints}
        closed={true}
        stroke={stroke}
        fill={fill}
        strokeWidth={1}
        strokeScaleEnabled={false}
        listening={false}
      />
    </Group>
  );
}
```

- [ ] **Step 2: Run all tests**

```bash
cd frontend && npm run test
```

Expected: all tests pass

- [ ] **Step 3: Manual smoke test**

Start the dev server and engine:
```bash
# Terminal 1
scripts\dev-engine.bat

# Terminal 2
cd frontend && npm run dev
```

Open http://localhost:1420, import a DXF, and verify:
- Pieces render on canvas
- Dragging a piece moves it and snaps to 10 mm grid on release
- Stage pan still works when not dragging a piece

- [ ] **Step 4: Commit**

```
feat(canvas): make pieces draggable with 10mm snap-to-grid
```

---

## Task 7: Rotation — R key + on-canvas handle

**Files:**
- Modify: `frontend/src/components/canvas/CanvasWorkspace.tsx`

- [ ] **Step 1: Add R-key rotation and rotation handle to `CanvasWorkspace`**

Replace `frontend/src/components/canvas/CanvasWorkspace.tsx` with the full updated version:

```tsx
// Main Konva canvas component for the visual workspace.
// Handles zoom/pan, R-key rotation, and per-piece rotation handle.

import { useRef, useState, useEffect } from "react";
import { Stage, Layer, Rect, Line, Circle } from "react-konva";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";
import { useViewport } from "../../hooks/useViewport";
import { PieceShape } from "./PieceShape";
import { ViewportControls } from "./ViewportControls";

const FABRIC_HEIGHT_MM = 99_000;
const HANDLE_DISTANCE_MM = 20;

interface Props {
  pieces: Piece[];
  placements: Placement[];
  updatePlacement: (id: string, delta: Partial<Omit<Placement, "pieceId">>) => void;
  selectedPieceId: string | null;
  onSelectPiece: (id: string | null) => void;
  fabricWidthMm: number;
}

export function CanvasWorkspace({
  pieces,
  placements,
  updatePlacement,
  selectedPieceId,
  onSelectPiece,
  fabricWidthMm,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [stageSize, setStageSize] = useState({ w: 800, h: 600 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setStageSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { transform, setTransform, handleWheel, fitToContent, zoomIn, zoomOut } =
    useViewport();

  useEffect(() => {
    if (pieces.length === 0) return;
    const id = setTimeout(() => {
      fitToContent(placements, pieces, stageSize.w, stageSize.h);
    }, 0);
    return () => clearTimeout(id);
  }, [pieces]); // eslint-disable-line react-hooks/exhaustive-deps

  // R key: rotate selected piece by 90° CW
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.key === "r" || e.key === "R") && selectedPieceId !== null) {
        const current = placements.find((p) => p.pieceId === selectedPieceId);
        if (!current) return;
        const rotationDeg = (current.rotationDeg + 90) % 360;
        updatePlacement(selectedPieceId, { rotationDeg });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedPieceId, placements, updatePlacement]);

  const handleFit = () => {
    fitToContent(placements, pieces, stageSize.w, stageSize.h);
  };

  // Compute rotation handle position for selected piece
  const rotationHandle = (() => {
    if (!selectedPieceId) return null;
    const pl = placements.find((p) => p.pieceId === selectedPieceId);
    const piece = pieces.find((p) => p.id === selectedPieceId);
    if (!pl || !piece) return null;

    const cx = pl.x + piece.bbox.width / 2;
    const cy = pl.y + piece.bbox.height / 2;
    const rad = ((pl.rotationDeg - 90) * Math.PI) / 180;
    const hx = cx + HANDLE_DISTANCE_MM * Math.cos(rad);
    const hy = cy + HANDLE_DISTANCE_MM * Math.sin(rad);
    return { cx, cy, hx, hy };
  })();

  const handleRotateDragMove = (e: KonvaEventObject<DragEvent>) => {
    if (!selectedPieceId || !rotationHandle) return;
    const { cx, cy } = rotationHandle;
    const angle = Math.atan2(e.target.y() - cy, e.target.x() - cx) * (180 / Math.PI);
    // atan2 = 0 means "right"; rotate +90 so that "up" = 0° Konva rotation
    const rotationDeg = (angle + 90 + 360) % 360;
    updatePlacement(selectedPieceId, { rotationDeg });
  };

  const handleRotateDragEnd = (e: KonvaEventObject<DragEvent>) => {
    if (!selectedPieceId || !rotationHandle) return;
    const { cx, cy } = rotationHandle;
    const angle = Math.atan2(e.target.y() - cy, e.target.x() - cx) * (180 / Math.PI);
    const raw = (angle + 90 + 360) % 360;
    const snapped = Math.round(raw / 5) * 5 % 360;
    updatePlacement(selectedPieceId, { rotationDeg: snapped });
    // Reposition handle to match snapped rotation so it doesn't jump on next render
    const snapRad = ((snapped - 90) * Math.PI) / 180;
    e.target.x(cx + HANDLE_DISTANCE_MM * Math.cos(snapRad));
    e.target.y(cy + HANDLE_DISTANCE_MM * Math.sin(snapRad));
  };

  return (
    <div ref={containerRef} style={styles.container}>
      <Stage
        width={stageSize.w}
        height={stageSize.h}
        draggable
        scaleX={transform.scale}
        scaleY={transform.scale}
        x={transform.x}
        y={transform.y}
        onWheel={handleWheel}
        onDragEnd={(e) => {
          setTransform((t) => ({ ...t, x: e.target.x(), y: e.target.y() }));
        }}
        onClick={(e) => {
          if (e.target === e.target.getStage()) onSelectPiece(null);
        }}
      >
        {/* Layer 1: fabric background bounds */}
        <Layer listening={false}>
          <Rect
            x={0}
            y={0}
            width={fabricWidthMm}
            height={FABRIC_HEIGHT_MM}
            fill="rgba(255,255,255,0.04)"
            stroke="#333"
            strokeWidth={1}
          />
          <Line
            points={[fabricWidthMm, 0, fabricWidthMm, FABRIC_HEIGHT_MM]}
            stroke="#555"
            strokeWidth={1}
          />
        </Layer>

        {/* Layer 2: piece outlines + rotation handle */}
        <Layer>
          {placements.map((pl) => {
            const piece = pieces.find((p) => p.id === pl.pieceId);
            if (!piece) return null;
            return (
              <PieceShape
                key={piece.id}
                piece={piece}
                placement={pl}
                isSelected={piece.id === selectedPieceId}
                isColliding={false}
                onSelect={() => onSelectPiece(piece.id)}
                onDragEnd={(id, pos) => updatePlacement(id, pos)}
              />
            );
          })}

          {/* Rotation handle — only when a piece is selected */}
          {rotationHandle && (
            <>
              <Line
                points={[rotationHandle.cx, rotationHandle.cy, rotationHandle.hx, rotationHandle.hy]}
                stroke="#ff9800"
                strokeWidth={1}
                strokeScaleEnabled={false}
                dash={[4, 3]}
                listening={false}
              />
              <Circle
                x={rotationHandle.hx}
                y={rotationHandle.hy}
                radius={6}
                fill="#ff9800"
                stroke="white"
                strokeWidth={1.5}
                strokeScaleEnabled={false}
                draggable
                onDragMove={handleRotateDragMove}
                onDragEnd={handleRotateDragEnd}
                onMouseEnter={(e) => {
                  const container = e.target.getStage()?.container();
                  if (container) container.style.cursor = "crosshair";
                }}
                onMouseLeave={(e) => {
                  const container = e.target.getStage()?.container();
                  if (container) container.style.cursor = "default";
                }}
              />
            </>
          )}
        </Layer>
      </Stage>

      <ViewportControls
        scale={transform.scale}
        onFit={handleFit}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
      />
    </div>
  );
}

const styles = {
  container: {
    position: "relative" as const,
    width: "100%",
    height: "100%",
    overflow: "hidden",
    background: "#111",
  },
} as const;
```

- [ ] **Step 2: Run all tests**

```bash
cd frontend && npm run test
```

Expected: all tests pass

- [ ] **Step 3: Manual smoke test**

Start the dev server and verify:
- Select a piece, press **R** → piece rotates 90° CW. Press again → 180°, 270°, 360°=0°.
- Select a piece → orange rotation handle circle appears above it, connected by a dashed line.
- Drag the handle → piece rotates to follow. On release, snaps to nearest 5°.
- Stage pan still works when no piece is being dragged.

- [ ] **Step 4: Commit**

```
feat(canvas): add R-key rotation and on-canvas rotation handle
```

---

## Task 8: Collision highlight

**Files:**
- Modify: `frontend/src/components/canvas/CanvasWorkspace.tsx`

- [ ] **Step 1: Wire `useCollisions` into `CanvasWorkspace` and pass `isColliding` to pieces**

Add the import at the top of `CanvasWorkspace.tsx`:
```typescript
import { useCollisions } from "../../hooks/useCollisions";
```

Inside the `CanvasWorkspace` function, add after the `useViewport` call:
```typescript
const collidingIds = useCollisions(placements, pieces);
```

Update the `PieceShape` JSX to pass the real `isColliding` value (replace `isColliding={false}` with):
```tsx
isColliding={collidingIds.has(piece.id)}
```

- [ ] **Step 2: Run all tests**

```bash
cd frontend && npm run test
```

Expected: all tests pass

- [ ] **Step 3: Manual smoke test**

Start the dev server and verify:
- Import a DXF with multiple pieces.
- Drag two pieces so they overlap → both turn red.
- Drag them apart → red highlight disappears.
- Collision updates in real time (on every placement change, not just on drag-end).

- [ ] **Step 4: Commit**

```
feat(canvas): highlight colliding pieces in red using frontend SAT
```

---

## Task 9: BACKLOG update

**Files:**
- Modify: `docs/planning/BACKLOG.md`

- [ ] **Step 1: Mark Phase 4 tasks complete in BACKLOG.md**

Update the Phase 4 section in `docs/planning/BACKLOG.md`:

```markdown
### Phase 4 — Manual editing
- [x] Drag pieces on canvas
- [x] Rotate pieces (R key + handle)
- [x] Snap behavior (10 mm grid, drag-end)
- [x] Collision highlight feedback
- [x] Placement state model (usePlacements hook: pieceId → x, y, rotationDeg)
- [x] Regression tests for drag/rotate transformations
```

- [ ] **Step 2: Open pull request**

```bash
git push -u origin manual-editing/masonw/drag-rotate
gh pr create \
  --title "feat: Phase 4 — manual editing (drag, rotate, collision highlight)" \
  --body "Implements Phase 4: draggable pieces with snap-to-grid, R-key and handle rotation, and real-time SAT collision highlighting. No new engine endpoints."
```
