import { useState, useEffect, useCallback } from "react";
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";

/**
 * Placement state for the marker canvas.
 *
 * Starts EMPTY and stays empty until `setAllPlacements` is called (typically
 * with the Auto Layout result). `pieces` is observed only to clear placements
 * when the imported set changes, so stale placements for unloaded piece ids
 * don't linger.
 *
 * Manual editing was removed in the optimization round, so this hook no
 * longer exposes a per-piece update method.
 */
export function usePlacements(pieces: Piece[]) {
  const [placements, setPlacements] = useState<Placement[]>([]);

  useEffect(() => {
    setPlacements([]);
  }, [pieces]);

  const setAllPlacements = useCallback((newPlacements: Placement[]) => {
    setPlacements(newPlacements);
  }, []);

  const resetPlacements = useCallback(() => {
    setPlacements([]);
  }, []);

  return { placements, setAllPlacements, resetPlacements };
}
