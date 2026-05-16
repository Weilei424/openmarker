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
    grainline_direction_deg: null,
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
