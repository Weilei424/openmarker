import type { Piece } from "../types/engine";
import type { Placement, ViewportTransform } from "../types/canvas";

const GAP_MM = 10;

export function snapToGrid(value: number, grid = 10): number {
  // Round half away from zero so that negative midpoints (e.g. -15 → -20)
  // are symmetric with positive ones (e.g. 15 → 20).
  return Math.sign(value) * Math.round(Math.abs(value) / grid) * grid;
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
 * Compute a viewport transform that fits a rectangular region of WORLD-space
 * (after the canvas's 90° CCW rotation) into the stage with 10% padding.
 *
 * Use this when the canvas content is rendered inside the rotation Group:
 * pass the world-space bbox directly. For unrotated canvases, use
 * `computeFitViewport` instead.
 */
export function computeFitViewportFromWorldBbox(
  worldMinX: number,
  worldMinY: number,
  worldMaxX: number,
  worldMaxY: number,
  stageW: number,
  stageH: number,
): ViewportTransform {
  const totalW = worldMaxX - worldMinX;
  const totalH = worldMaxY - worldMinY;
  if (totalW <= 0 || totalH <= 0 || stageW <= 0 || stageH <= 0) {
    return { scale: 1, x: 0, y: 0 };
  }
  const scale = Math.min((stageW * 0.85) / totalW, (stageH * 0.85) / totalH);
  const contentPxW = totalW * scale;
  const contentPxH = totalH * scale;
  return {
    scale,
    x: (stageW - contentPxW) / 2 - worldMinX * scale,
    y: (stageH - contentPxH) / 2 - worldMinY * scale,
  };
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
