import { useMemo } from "react";
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";
import { computeCollidingIds } from "../utils/collisions";

export function useCollisions(placements: Placement[], pieces: Piece[], fabricWidthMm: number): Set<string> {
  return useMemo(
    () => computeCollidingIds(placements, pieces, fabricWidthMm),
    [placements, pieces, fabricWidthMm],
  );
}
