import { useState, useEffect, useCallback } from "react";
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

  const updatePlacement = useCallback(
    (id: string, delta: Partial<Omit<Placement, "pieceId">>) => {
      setPlacements((prev) =>
        prev.map((p) => (p.pieceId === id ? { ...p, ...delta } : p))
      );
    },
    []
  );

  const setAllPlacements = useCallback((newPlacements: Placement[]) => {
    setPlacements(newPlacements);
  }, []);

  function resetPlacements() {
    setPlacements(computePlacements(pieces));
  }

  return { placements, updatePlacement, resetPlacements, setAllPlacements };
}
