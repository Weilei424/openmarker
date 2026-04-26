import type { Piece } from "../types/engine";
import type { Placement } from "../types/canvas";
import { polygonsIntersect, translatePolygon, rotatePolygon } from "./geometry";

type Point = [number, number];

function transformedPolygon(piece: Piece, pl: Placement): Point[] {
  const cx = piece.bbox.width / 2;
  const cy = piece.bbox.height / 2;
  let poly = piece.polygon as Point[];
  if (pl.rotationDeg !== 0) {
    poly = rotatePolygon(poly, pl.rotationDeg, cx, cy);
  }
  return translatePolygon(poly, pl.x, pl.y);
}

export function computeCollidingIds(placements: Placement[], pieces: Piece[]): Set<string> {
  const collidingIds = new Set<string>();
  const pieceMap = new Map(pieces.map((p) => [p.id, p]));

  const transformed = placements
    .map((pl) => {
      const piece = pieceMap.get(pl.pieceId);
      return piece ? { pieceId: pl.pieceId, poly: transformedPolygon(piece, pl) } : null;
    })
    .filter((x): x is { pieceId: string; poly: Point[] } => x !== null);

  for (let i = 0; i < transformed.length; i++) {
    for (let j = i + 1; j < transformed.length; j++) {
      if (polygonsIntersect(transformed[i].poly, transformed[j].poly)) {
        collidingIds.add(transformed[i].pieceId);
        collidingIds.add(transformed[j].pieceId);
      }
    }
  }

  return collidingIds;
}
