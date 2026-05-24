import { useMemo } from "react";
import type { Piece, AutoLayoutPlacement } from "../types/engine";
import type { Placement } from "../types/canvas";
import { engineToFrontendPlacement } from "../utils/enginePlacement";

/**
 * Derive frontend Placement[] from the active cached layout's engine-coord placements.
 *
 * Manual editing was removed in the optimization round; this hook is now a pure
 * memoized projection. Returns [] when there is no active entry.
 */
export function usePlacements(
  pieces: Piece[],
  enginePlacements: AutoLayoutPlacement[] | null,
) {
  const placements = useMemo<Placement[]>(() => {
    if (!enginePlacements || pieces.length === 0) return [];
    const pieceMap = new Map(pieces.map((p) => [p.id, p]));
    return enginePlacements
      .map((pl) => {
        const piece = pieceMap.get(pl.piece_id);
        if (!piece) return null;
        return engineToFrontendPlacement(piece, pl.x, pl.y, pl.rotation_deg);
      })
      .filter((p): p is Placement => p !== null);
  }, [pieces, enginePlacements]);

  return { placements };
}
