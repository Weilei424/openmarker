# DXF parser for ET CAD exports.
# Extracts closed polyline outlines grouped by layer name.

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import ezdxf

# Layers that are CAD infrastructure, not pattern pieces
_IGNORED_LAYERS = {"0", "DEFPOINTS"}

# Tolerance (mm) for treating a non-closed polyline as closed
_CLOSE_TOLERANCE = 0.1


@dataclass
class RawPiece:
    """Intermediate representation of a piece outline before normalization."""
    layer: str
    points: list[tuple[float, float]]
    is_closed: bool


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _polygon_area(points: list[tuple[float, float]]) -> float:
    """Shoelace formula — returns absolute area."""
    n = len(points)
    if n < 3:
        return 0.0
    area = sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    )
    return abs(area) / 2.0


def _extract_lwpolyline(entity) -> tuple[list[tuple[float, float]], bool]:
    """Return (points, is_closed) for an LWPOLYLINE entity."""
    points = [(x, y) for x, y, *_ in entity.get_points("xy")]
    closed = bool(entity.closed)
    return points, closed


def _extract_polyline(entity) -> tuple[list[tuple[float, float]], bool]:
    """Return (points, is_closed) for a legacy POLYLINE entity."""
    points = []
    for vertex in entity.vertices:
        loc = vertex.dxf.location
        points.append((float(loc.x), float(loc.y)))
    closed = bool(entity.is_closed)
    return points, closed


def parse_dxf(file_bytes: bytes) -> list[RawPiece]:
    """
    Parse a DXF file (as raw bytes) and return one RawPiece per layer.

    Strategy per layer:
    - Collect all closed polylines (or near-closed ones within _CLOSE_TOLERANCE).
    - Keep only the largest by area — this discards grain lines and notch marks
      that ET CAD places on the same layer as the piece outline.

    Raises ezdxf.DXFStructureError if the bytes are not a valid DXF file.
    """
    doc = ezdxf.read(io.StringIO(file_bytes.decode("utf-8", errors="replace")))
    msp = doc.modelspace()

    # layer_name -> list of (points, is_closed)
    candidates: dict[str, list[list[tuple[float, float]]]] = {}

    for entity in msp:
        layer = entity.dxf.layer
        if layer in _IGNORED_LAYERS:
            continue

        points: list[tuple[float, float]] = []
        closed = False

        if entity.dxftype() == "LWPOLYLINE":
            points, closed = _extract_lwpolyline(entity)
        elif entity.dxftype() == "POLYLINE":
            points, closed = _extract_polyline(entity)
        else:
            continue

        if len(points) < 3:
            continue

        # Treat as closed if first and last point are within tolerance
        if not closed and _distance(points[0], points[-1]) <= _CLOSE_TOLERANCE:
            closed = True

        if not closed:
            continue

        candidates.setdefault(layer, []).append(points)

    result: list[RawPiece] = []
    for layer, polylines in candidates.items():
        # Pick the largest closed polyline per layer
        best = max(polylines, key=_polygon_area)
        result.append(RawPiece(layer=layer, points=best, is_closed=True))

    return result
