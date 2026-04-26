import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePlacements } from "./usePlacements";
import type { Piece } from "../types/engine";

function makePiece(id: string, w: number, h: number): Piece {
  return {
    id,
    name: id,
    polygon: [[0,0],[w,0],[w,h],[0,h]] as [number,number][],
    area: w * h,
    bbox: { min_x: 0, min_y: 0, max_x: w, max_y: h, width: w, height: h },
    is_valid: true,
    validation_notes: [],
  };
}

describe("usePlacements", () => {
  it("initialises placements from pieces with rotationDeg 0", () => {
    const pieces = [makePiece("A", 100, 200)];
    const { result } = renderHook(() => usePlacements(pieces));
    expect(result.current.placements).toHaveLength(1);
    expect(result.current.placements[0].rotationDeg).toBe(0);
    expect(result.current.placements[0].pieceId).toBe("A");
  });

  it("updatePlacement merges x and y", () => {
    const pieces = [makePiece("A", 100, 200)];
    const { result } = renderHook(() => usePlacements(pieces));
    act(() => {
      result.current.updatePlacement("A", { x: 300, y: 50 });
    });
    expect(result.current.placements[0].x).toBe(300);
    expect(result.current.placements[0].y).toBe(50);
    expect(result.current.placements[0].rotationDeg).toBe(0); // unchanged
  });

  it("updatePlacement merges rotationDeg", () => {
    const pieces = [makePiece("A", 100, 200)];
    const { result } = renderHook(() => usePlacements(pieces));
    act(() => {
      result.current.updatePlacement("A", { rotationDeg: 90 });
    });
    expect(result.current.placements[0].rotationDeg).toBe(90);
    expect(result.current.placements[0].x).toBe(10); // unchanged (GAP_MM)
  });

  it("updatePlacement ignores unknown pieceId", () => {
    const pieces = [makePiece("A", 100, 200)];
    const { result } = renderHook(() => usePlacements(pieces));
    const before = result.current.placements[0].x;
    act(() => {
      result.current.updatePlacement("Z", { x: 999 });
    });
    expect(result.current.placements[0].x).toBe(before);
  });

  it("re-initialises when pieces reference changes", () => {
    const piecesV1 = [makePiece("A", 100, 200)];
    const { result, rerender } = renderHook(({ pieces }) => usePlacements(pieces), {
      initialProps: { pieces: piecesV1 },
    });
    act(() => {
      result.current.updatePlacement("A", { x: 999 });
    });
    expect(result.current.placements[0].x).toBe(999);

    // New pieces reference triggers re-init
    const piecesV2 = [makePiece("A", 100, 200)];
    rerender({ pieces: piecesV2 });
    expect(result.current.placements[0].x).toBe(10); // back to GAP_MM
  });
});
