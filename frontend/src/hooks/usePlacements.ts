import { useState, useEffect, useCallback } from "react";
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";

/**
 * Placement state for the marker canvas.
 *
 * Starts EMPTY and stays empty until something (typically the Auto Layout
 * result) calls setAllPlacements. The pre-Phase-5-optimization behaviour of
 * pre-laying out pieces in a single row on import was removed — it produced
 * misleading >100% utilisation and a confusing "is this auto-layout or just a
 * preview?" state.
 *
 * `pieces` is observed only to clear placements when the imported set
 * changes (so stale placements for unloaded piece ids don't linger).
 */
export function usePlacements(pieces: Piece[]) {
  const [placements, setPlacements] = useState<Placement[]>([]);

  useEffect(() => {
    setPlacements([]);
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
    setPlacements([]);
  }

  return { placements, updatePlacement, resetPlacements, setAllPlacements };
}
