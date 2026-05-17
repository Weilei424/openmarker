import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";

const EDGE_GAP_MM = 10;

export interface MarkerMetrics {
  length: number;       // mm — rightmost extent + edge gap; 0 if no placements
  utilization: number;  // percent of marker area covered by piece area
}

/**
 * Marker length is the rightmost edge of all placed pieces (taking each piece's
 * rotated bounding box into account) plus a small edge gap. Utilization is the
 * total piece area divided by (length × fabric width).
 *
 * placement.x / .y are the top-left of the UNROTATED bbox; rotation is around
 * the bbox center. The rotated bbox has dimensions (w·|cos|+h·|sin|, w·|sin|+h·|cos|)
 * centered at (x+w/2, y+h/2).
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
  let maxRight = 0;

  for (const pl of placements) {
    const piece = pieceMap.get(pl.pieceId);
    if (!piece) continue;
    const w = piece.bbox.width;
    const h = piece.bbox.height;
    const rad = (pl.rotationDeg * Math.PI) / 180;
    const wRot = w * Math.abs(Math.cos(rad)) + h * Math.abs(Math.sin(rad));
    const right = pl.x + w / 2 + wRot / 2;
    if (right > maxRight) maxRight = right;
  }

  const length = maxRight + EDGE_GAP_MM;
  const totalArea = pieces.reduce((sum, p) => sum + p.area, 0);
  const utilization = (totalArea / (length * fabricWidthMm)) * 100;

  return { length, utilization };
}
