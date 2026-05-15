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
