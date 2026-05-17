import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";

const EDGE_GAP_MM = 10;

export interface MarkerMetrics {
  length: number;       // mm — bottom edge of rendered pieces + edge gap; 0 if no placements
  utilization: number;  // percent of marker area covered by piece area
}

/**
 * Marker length = maximum Y bottom edge across all placed pieces.
 *
 * The fabric is oriented with WIDTH on the X axis (limited by fabricWidthMm)
 * and LENGTH on the Y axis (what we minimize). Pieces fill X up to fabricWidthMm,
 * then stack downward; the "length used" is the lowest piece edge.
 *
 * For correctness with irregular polygons we iterate the actual polygon vertices
 * after applying the Konva rotation (CW around the unrotated bbox center).
 */
export function computeMarkerMetrics(
  placements: Placement[],
  pieces: Piece[],
  fabricWidthMm: number,
): MarkerMetrics {
  if (placements.length === 0 || fabricWidthMm <= 0) {
    return { length: 0, utilization: 0 };
  }

  const pieceMap = new Map(pieces.map((p) => [p.id, p]));
  let maxBottom = 0;

  for (const pl of placements) {
    const piece = pieceMap.get(pl.pieceId);
    if (!piece) continue;
    const cx = piece.bbox.width / 2;
    const cy = piece.bbox.height / 2;
    const rad = (pl.rotationDeg * Math.PI) / 180;
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);

    for (const [px, py] of piece.polygon) {
      const renderedY = (px - cx) * sin + (py - cy) * cos + pl.y + cy;
      if (renderedY > maxBottom) maxBottom = renderedY;
    }
  }

  const length = maxBottom + EDGE_GAP_MM;
  const totalArea = pieces.reduce((sum, p) => sum + p.area, 0);
  const utilization = (totalArea / (length * fabricWidthMm)) * 100;

  return { length, utilization };
}
