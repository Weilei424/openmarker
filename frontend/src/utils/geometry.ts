type Point = [number, number];
type Vector = [number, number];

export function translatePolygon(poly: Point[], dx: number, dy: number): Point[] {
  return poly.map(([x, y]) => [x + dx, y + dy] as Point);
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
    return [tx * cos - ty * sin + cx, tx * sin + ty * cos + cy] as Point;
  });
}

function getAxes(poly: Point[]): Vector[] {
  const axes: Vector[] = [];
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    // Edge perpendicular (normal)
    axes.push([-(y2 - y1), x2 - x1] as Vector);
  }
  return axes;
}

function project(poly: Point[], axis: Vector): { min: number; max: number } {
  const nx = axis[0];
  const ny = axis[1];
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
    const len = Math.sqrt(axis[0] ** 2 + axis[1] ** 2);
    if (len === 0) continue;
    const nx = axis[0] / len;
    const ny = axis[1] / len;
    const normalised: Vector = [nx, ny];
    const a = project(polyA, normalised);
    const b = project(polyB, normalised);
    // Strict inequality: touching edges are not considered overlapping
    if (a.max <= b.min || b.max <= a.min) return false;
  }
  return true;
}
