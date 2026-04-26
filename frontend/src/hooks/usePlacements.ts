import { useState, useEffect } from "react";
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";
import { computePlacements } from "../utils/placement";

export function usePlacements(pieces: Piece[]) {
  const [placements, setPlacements] = useState<Placement[]>(() =>
    computePlacements(pieces)
  );

  // Re-initialise whenever a new set of pieces arrives.
  useEffect(() => {
    setPlacements(computePlacements(pieces));
  }, [pieces]);

  function updatePlacement(
    id: string,
    delta: Partial<Omit<Placement, "pieceId">>
  ) {
    setPlacements((prev) =>
      prev.map((p) => (p.pieceId === id ? { ...p, ...delta } : p))
    );
  }

  function resetPlacements() {
    setPlacements(computePlacements(pieces));
  }

  return { placements, updatePlacement, resetPlacements };
}
