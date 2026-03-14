import { describe, it, expect } from "vitest";
import { computePlacements, computeFitViewport } from "./placement";
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

describe("computePlacements", () => {
  it("places single piece at (GAP_MM, GAP_MM)", () => {
    const piece = makePiece("A", 100, 200);
    const result = computePlacements([piece]);
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ pieceId: "A", x: 10, y: 10 });
  });

  it("places second piece after first width + gap", () => {
    const p1 = makePiece("A", 100, 200);
    const p2 = makePiece("B", 50, 80);
    const result = computePlacements([p1, p2]);
    expect(result[0]).toEqual({ pieceId: "A", x: 10, y: 10 });
    // Second piece: x = GAP(10) + width(100) + GAP(10) = 120
    expect(result[1]).toEqual({ pieceId: "B", x: 120, y: 10 });
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
    const placements = [{ pieceId: "A", x: 10, y: 10 }];
    const stageW = 800;
    const stageH = 600;

    const vp = computeFitViewport(placements, [piece], stageW, stageH);

    // Total content: x from 10 to 110 (100 wide), y from 10 to 210 (200 tall)
    // scaleX = 800*0.8/100 = 6.4, scaleY = 600*0.8/200 = 2.4 → scale = 2.4
    expect(vp.scale).toBeCloseTo(2.4);

    // Content px: 100*2.4=240 wide, 200*2.4=480 tall
    // offsetX = (800-240)/2 - 10*2.4 = 280 - 24 = 256
    // offsetY = (600-480)/2 - 10*2.4 = 60 - 24 = 36
    expect(vp.x).toBeCloseTo(256);
    expect(vp.y).toBeCloseTo(36);
  });

  it("picks the smaller of scaleX/scaleY", () => {
    // Very wide piece — height scale will be the limiting factor
    const piece = makePiece("A", 1000, 10);
    const placements = [{ pieceId: "A", x: 0, y: 0 }];
    const vp = computeFitViewport(placements, [piece], 800, 600);
    // scaleX = 800*0.8/1000 = 0.64, scaleY = 600*0.8/10 = 48 → scale = 0.64
    expect(vp.scale).toBeCloseTo(0.64);
  });
});
