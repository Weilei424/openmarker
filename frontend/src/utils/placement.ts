import type { Piece } from "../types/engine";
import type { Placement, ViewportTransform } from "../types/canvas";

const GAP_MM = 10;

export function snapToGrid(value: number, grid = 10): number {
  // Use Math.floor + 0.5 offset for symmetric (round-half-away-from-zero) behaviour,
  // so that -15 snaps to -20 rather than -10.
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
