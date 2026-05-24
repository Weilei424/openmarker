import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { usePlacements } from "./usePlacements";
import type { Piece, AutoLayoutPlacement } from "../types/engine";

function makePiece(id: string): Piece {
  return {
    id,
    name: id,
    polygon: [[0, 0], [100, 0], [100, 80], [0, 80]],
    area: 8000,
    bbox: { min_x: 0, min_y: 0, max_x: 100, max_y: 80, width: 100, height: 80 },
    is_valid: true,
    validation_notes: [],
    grainline_direction_deg: null,
  };
}

describe("usePlacements (derived)", () => {
  it("returns [] when enginePlacements is null", () => {
    const { result } = renderHook(() =>
      usePlacements([makePiece("p0")], null)
    );
    expect(result.current.placements).toEqual([]);
  });

  it("returns [] when pieces are empty", () => {
    const ep: AutoLayoutPlacement[] = [{ piece_id: "p0", x: 10, y: 20, rotation_deg: 0 }];
    const { result } = renderHook(() => usePlacements([], ep));
    expect(result.current.placements).toEqual([]);
  });

  it("maps each engine placement to a frontend placement, dropping pieces with no matching id", () => {
    const pieces = [makePiece("p0"), makePiece("p1")];
    const ep: AutoLayoutPlacement[] = [
      { piece_id: "p0", x: 0, y: 0, rotation_deg: 0 },
      { piece_id: "missing", x: 0, y: 0, rotation_deg: 0 },
      { piece_id: "p1", x: 50, y: 50, rotation_deg: 90 },
    ];
    const { result } = renderHook(() => usePlacements(pieces, ep));
    expect(result.current.placements).toHaveLength(2);
    expect(result.current.placements.map((p) => p.pieceId)).toEqual(["p0", "p1"]);
  });

  it("memoizes — same inputs yield the same array reference", () => {
    const pieces = [makePiece("p0")];
    const ep: AutoLayoutPlacement[] = [{ piece_id: "p0", x: 0, y: 0, rotation_deg: 0 }];
    const { result, rerender } = renderHook(
      ({ pieces, ep }) => usePlacements(pieces, ep),
      { initialProps: { pieces, ep } }
    );
    const first = result.current.placements;
    rerender({ pieces, ep });
    expect(result.current.placements).toBe(first);
  });
});
