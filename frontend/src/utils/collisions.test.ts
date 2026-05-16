import { describe, it, expect } from "vitest";
import { computeCollidingIds } from "./collisions";
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";

function makePiece(id: string, w: number, h: number): Piece {
  return {
    id,
    name: id,
    polygon: [[0,0],[w,0],[w,h],[0,h]] as [number,number][],
    area: w * h,
    bbox: { min_x: 0, min_y: 0, max_x: w, max_y: h, width: w, height: h },
    is_valid: true,
    validation_notes: [],
    grainline_direction_deg: null,
  };
}

function makePlacement(pieceId: string, x: number, y: number, rotationDeg = 0): Placement {
  return { pieceId, x, y, rotationDeg };
}

describe("computeCollidingIds", () => {
  const FABRIC_WIDTH_MM = 1500;

  it("returns empty set when no pieces", () => {
    expect(computeCollidingIds([], [], FABRIC_WIDTH_MM)).toEqual(new Set());
  });

  it("returns empty set for a single piece", () => {
    const pieces = [makePiece("A", 100, 100)];
    const placements = [makePlacement("A", 0, 0)];
    expect(computeCollidingIds(placements, pieces, FABRIC_WIDTH_MM)).toEqual(new Set());
  });

  it("returns empty set for non-overlapping pieces", () => {
    const pieces = [makePiece("A", 100, 100), makePiece("B", 100, 100)];
    const placements = [makePlacement("A", 0, 0), makePlacement("B", 200, 0)];
    expect(computeCollidingIds(placements, pieces, FABRIC_WIDTH_MM)).toEqual(new Set());
  });

  it("returns both IDs when pieces overlap", () => {
    const pieces = [makePiece("A", 100, 100), makePiece("B", 100, 100)];
    // B placed at x=50 overlaps A by 50mm
    const placements = [makePlacement("A", 0, 0), makePlacement("B", 50, 0)];
    const result = computeCollidingIds(placements, pieces, FABRIC_WIDTH_MM);
    expect(result).toEqual(new Set(["A", "B"]));
  });

  it("only returns the colliding pair, not uninvolved pieces", () => {
    const pieces = [makePiece("A", 100, 100), makePiece("B", 100, 100), makePiece("C", 100, 100)];
    const placements = [
      makePlacement("A", 0, 0),
      makePlacement("B", 50, 0),   // overlaps A
      makePlacement("C", 500, 0),  // far away
    ];
    const result = computeCollidingIds(placements, pieces, FABRIC_WIDTH_MM);
    expect(result.has("A")).toBe(true);
    expect(result.has("B")).toBe(true);
    expect(result.has("C")).toBe(false);
  });
});
