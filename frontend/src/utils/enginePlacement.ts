import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";

/**
 * Convert an engine placement (where x/y is the top-left of the actually-rotated
 * polygon's bounding box, rotation applied around the piece's origin) into the
 * frontend's Placement convention (x/y is the top-left of the UNROTATED bbox;
 * rotation applied around its center (x + w/2, y + h/2) by Konva).
 *
 * For irregular polygons, the rotated polygon's bbox is not centered on the
 * unrotated bbox center, so we must iterate the actual polygon vertices to find
 * the true bbox extents under the rendered rotation.
 *
 * Derivation (see PR notes): Konva renders vertex (px, py) at
 *   rendered_x = (px - cx)·cosθ - (py - cy)·sinθ + fx + cx
 *   rendered_y = (px - cx)·sinθ + (py - cy)·cosθ + fy + cy
 * For min(rendered_x) = ex and min(rendered_y) = ey:
 *   fx = ex - cx - min((px - cx)·cosθ - (py - cy)·sinθ)
 *   fy = ey - cy - min((px - cx)·sinθ + (py - cy)·cosθ)
 */
export function engineToFrontendPlacement(
  piece: Piece,
  ex: number,
  ey: number,
  rotationDeg: number,
): Placement {
  const cx = piece.bbox.width / 2;
  const cy = piece.bbox.height / 2;
  const rad = (rotationDeg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);

  let minA = Infinity;
  let minB = Infinity;
  for (const [px, py] of piece.polygon) {
    const A = (px - cx) * cos - (py - cy) * sin;
    const B = (px - cx) * sin + (py - cy) * cos;
    if (A < minA) minA = A;
    if (B < minB) minB = B;
  }

  return {
    pieceId: piece.id,
    x: ex - cx - minA,
    y: ey - cy - minB,
    rotationDeg,
  };
}
