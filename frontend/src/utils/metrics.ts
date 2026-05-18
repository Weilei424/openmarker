import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";

const EDGE_GAP_MM = 10;

export interface MarkerMetrics {
  length: number;        // mm — bottom edge of rendered pieces + edge gap; 0 if no placements
  utilization: number;   // percent of marker area covered by piece area (clamped to 100)
  overflowsFabric: boolean; // true when any rendered piece extends past fabric width or above y=0
}

/**
 * Marker length = maximum Y bottom edge across all placed pieces.
 * The fabric has fixed WIDTH on the X axis and unlimited LENGTH on Y (what we minimize).
 *
 * If any piece extends outside the fabric in X (e.g., the initial post-import row layout
 * when fabric width is smaller than the pieces' total bbox), the utilization formula
 * "total piece area / (length × fabric_width)" exceeds 100% because pieces use fabric
 * area that doesn't exist. We clamp utilization to 100% and report the overflow flag
 * so the UI can warn the user.
 */
export function computeMarkerMetrics(
  placements: Placement[],
  pieces: Piece[],
  fabricWidthMm: number,
): MarkerMetrics {
  if (placements.length === 0 || fabricWidthMm <= 0) {
    return { length: 0, utilization: 0, overflowsFabric: false };
  }

  const pieceMap = new Map(pieces.map((p) => [p.id, p]));
  let maxBottom = 0;
  let overflowsFabric = false;

  for (const pl of placements) {
    const piece = pieceMap.get(pl.pieceId);
    if (!piece) continue;
    const cx = piece.bbox.width / 2;
    const cy = piece.bbox.height / 2;
    const rad = (pl.rotationDeg * Math.PI) / 180;
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);

    for (const [px, py] of piece.polygon) {
      const renderedX = (px - cx) * cos - (py - cy) * sin + pl.x + cx;
      const renderedY = (px - cx) * sin + (py - cy) * cos + pl.y + cy;
      if (renderedY > maxBottom) maxBottom = renderedY;
      if (renderedX < -0.01 || renderedX > fabricWidthMm + 0.01 || renderedY < -0.01) {
        overflowsFabric = true;
      }
    }
  }

  const length = maxBottom + EDGE_GAP_MM;
  const totalArea = pieces.reduce((sum, p) => sum + p.area, 0);
  const rawUtil = (totalArea / (length * fabricWidthMm)) * 100;
  const utilization = Math.min(100, rawUtil);

  return { length, utilization, overflowsFabric };
}
