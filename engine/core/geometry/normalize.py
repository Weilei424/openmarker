# Geometry normalization: converts a RawPiece into a validated, origin-translated Piece.

from __future__ import annotations

import shapely.affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.validation import make_valid

from core.dxf.parser import RawPiece
from core.models.piece import BoundingBox, Piece


def normalize_piece(raw: RawPiece, piece_id: str) -> Piece:
    """
    Build a normalized Piece from a RawPiece.

    Steps:
    1. Build a Shapely Polygon.
    2. Repair invalid geometry via make_valid; take the largest sub-polygon if needed.
    3. Reject degenerate results (non-Polygon after repair).
    4. Translate to origin (min_x=0, min_y=0).
    5. Return populated Piece.

    Raises ValueError if the geometry is degenerate after repair.
    """
    if len(raw.points) < 3:
        raise ValueError(f"Piece '{raw.layer}' has fewer than 3 points")

    notes: list[str] = []
    polygon = Polygon(raw.points)

    if not polygon.is_valid:
        repaired = make_valid(polygon)
        notes.append("self-intersection repaired with make_valid")

        if isinstance(repaired, Polygon):
            polygon = repaired
        elif isinstance(repaired, (MultiPolygon, GeometryCollection)):
            # Extract all polygon-type geometries and keep the largest
            polys = [g for g in repaired.geoms if isinstance(g, Polygon) and not g.is_empty]
            if not polys:
                raise ValueError(
                    f"Piece '{raw.layer}' became degenerate after repair: {repaired.geom_type}"
                )
            polygon = max(polys, key=lambda g: g.area)
            notes.append(f"{repaired.geom_type} result: largest sub-polygon kept")
        else:
            raise ValueError(
                f"Piece '{raw.layer}' became degenerate after repair: {repaired.geom_type}"
            )

    if not isinstance(polygon, Polygon) or polygon.is_empty:
        raise ValueError(f"Piece '{raw.layer}' produced an empty or non-polygon geometry")

    # Translate so that min_x=0, min_y=0
    minx, miny, maxx, maxy = polygon.bounds
    polygon = shapely.affinity.translate(polygon, xoff=-minx, yoff=-miny)

    # Re-read bounds after translation (should be 0,0,width,height)
    _, _, width, height = polygon.bounds

    # Exterior ring without the closing duplicate point
    coords = list(polygon.exterior.coords)[:-1]

    bbox = BoundingBox(
        min_x=0.0,
        min_y=0.0,
        max_x=round(width, 6),
        max_y=round(height, 6),
        width=round(width, 6),
        height=round(height, 6),
    )

    return Piece(
        id=piece_id,
        name=raw.layer,
        polygon=[(round(x, 6), round(y, 6)) for x, y in coords],
        area=round(polygon.area, 6),
        bbox=bbox,
        is_valid=polygon.is_valid,
        validation_notes=notes,
    )
