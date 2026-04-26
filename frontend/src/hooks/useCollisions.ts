import { useMemo } from "react";
import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";
import { computeCollidingIds } from "../utils/collisions";

export function useCollisions(placements: Placement[], pieces: Piece[]): Set<string> {
  return useMemo(() => computeCollidingIds(placements, pieces), [placements, pieces]);
}
