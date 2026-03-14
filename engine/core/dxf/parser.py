# DXF parser for ET CAD exports.
# Extracts closed polyline outlines from pattern piece blocks.
#
# ET CAD structure:
#   - Modelspace contains INSERT entities (block references), one per piece.
#   - Each block holds TEXT, POINT, POLYLINE, LINE, etc.
#   - The piece outline is the largest closed POLYLINE in the block.
#   - Block name is used as the piece identifier.
#
# Fallback strategy for flat files (no INSERTs):
#   - Scan modelspace directly for LWPOLYLINE / POLYLINE, grouped by layer.

from __future__ import annotations

import io
import math
import os
import tempfile
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


def _chain_open_segments(
    segments: list[list[tuple[float, float]]],
) -> list[list[tuple[float, float]]]:
    """
    Given a list of open polyline point lists, chain connected segments into
    closed loops.

    ET CAD files split each piece outline across multiple POLYLINE segments
    that connect end-to-end.  This function groups them by chaining consecutive
    segments whose endpoints are within _CLOSE_TOLERANCE of each other, then
    returns any chains that close back to their own start.
    """
    if not segments:
        return []

    remaining = [list(s) for s in segments]
    closed: list[list[tuple[float, float]]] = []

    while remaining:
        chain = remaining.pop(0)
        # Try to extend chain by appending connecting segments
        changed = True
        while changed:
            changed = False
            for i, seg in enumerate(remaining):
                if _distance(chain[-1], seg[0]) <= _CLOSE_TOLERANCE:
                    chain.extend(seg[1:])  # skip duplicate junction point
                    remaining.pop(i)
                    changed = True
                    break
                elif _distance(chain[-1], seg[-1]) <= _CLOSE_TOLERANCE:
                    chain.extend(reversed(seg[:-1]))
                    remaining.pop(i)
                    changed = True
                    break

        # Accept chain if it closes back to its own start
        if len(chain) >= 3 and _distance(chain[0], chain[-1]) <= _CLOSE_TOLERANCE:
            closed.append(chain)

    return closed


def _collect_closed_polylines(
    entities,
) -> list[list[tuple[float, float]]]:
    """
    Scan an iterable of DXF entities and return all closed polyline point lists.

    Accepts both LWPOLYLINE and legacy POLYLINE.  Handles two layouts:

    1. Single closed polyline  — detected via the entity's closed flag or
       near-zero endpoint distance.
    2. Chained open segments   — ET CAD splits each piece outline into multiple
       POLYLINE segments that connect end-to-end.  These are stitched together
       by _chain_open_segments() after collection.
    """
    closed_polys: list[list[tuple[float, float]]] = []
    open_segments: list[list[tuple[float, float]]] = []

    for entity in entities:
        dxftype = entity.dxftype()

        if dxftype == "LWPOLYLINE":
            points, closed = _extract_lwpolyline(entity)
        elif dxftype == "POLYLINE":
            points, closed = _extract_polyline(entity)
        else:
            continue

        if len(points) < 2:
            continue

        if not closed and _distance(points[0], points[-1]) <= _CLOSE_TOLERANCE:
            closed = True

        if closed:
            if len(points) >= 3:
                closed_polys.append(points)
        else:
            open_segments.append(points)

    # Try to assemble open segments into closed outlines
    closed_polys.extend(_chain_open_segments(open_segments))

    return closed_polys


def _parse_insert_based(doc, msp) -> list[RawPiece]:
    """
    Extract pieces from an INSERT-based file (ET CAD style).

    Each INSERT in modelspace references a block that represents one piece.
    We read the block definition directly (no transform needed — normalize_piece
    will translate to origin anyway).
    """
    result: list[RawPiece] = []
    seen_blocks: set[str] = set()

    for entity in msp:
        if entity.dxftype() != "INSERT":
            continue

        block_name = entity.dxf.name
        # Skip internal AutoCAD blocks and duplicates
        if block_name.startswith("*") or block_name in seen_blocks:
            continue
        seen_blocks.add(block_name)

        try:
            block = doc.blocks[block_name]
        except KeyError:
            continue

        closed_polys = _collect_closed_polylines(block)

        if not closed_polys:
            continue

        # The piece outline is the largest closed polyline in the block
        best = max(closed_polys, key=_polygon_area)
        result.append(RawPiece(layer=block_name, points=best, is_closed=True))

    return result


def _parse_flat(msp) -> list[RawPiece]:
    """
    Fallback: extract pieces from a flat modelspace (no INSERTs).

    Groups polylines by layer; picks the largest per layer.
    """
    candidates: dict[str, list[list[tuple[float, float]]]] = {}

    for entity in msp:
        layer = entity.dxf.layer
        if layer in _IGNORED_LAYERS:
            continue

        dxftype = entity.dxftype()
        if dxftype == "LWPOLYLINE":
            points, closed = _extract_lwpolyline(entity)
        elif dxftype == "POLYLINE":
            points, closed = _extract_polyline(entity)
        else:
            continue

        if len(points) < 3:
            continue

        if not closed and _distance(points[0], points[-1]) <= _CLOSE_TOLERANCE:
            closed = True

        if closed:
            candidates.setdefault(layer, []).append(points)

    result: list[RawPiece] = []
    for layer, polylines in candidates.items():
        best = max(polylines, key=_polygon_area)
        result.append(RawPiece(layer=layer, points=best, is_closed=True))

    return result


def parse_dxf(file_bytes: bytes) -> list[RawPiece]:
    """
    Parse a DXF file (as raw bytes) and return one RawPiece per pattern piece.

    Tries INSERT-based extraction first (ET CAD format). Falls back to flat
    modelspace scanning if no INSERTs are found.

    Raises ezdxf.DXFStructureError if the bytes are not a valid DXF file.
    """
    # Write to a temp file so ezdxf.readfile() can detect the encoding
    # from the $DWGCODEPAGE header (ET CAD files are often CP1252, not UTF-8).
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".dxf")
    try:
        os.write(tmp_fd, file_bytes)
        os.close(tmp_fd)
        try:
            doc = ezdxf.readfile(tmp_path)
        except OSError as exc:
            # ezdxf raises OSError for binary/corrupt content that isn't DXF;
            # re-raise as DXFStructureError so callers get a consistent exception.
            raise ezdxf.DXFStructureError(str(exc)) from exc
    finally:
        os.unlink(tmp_path)
    msp = doc.modelspace()

    # Detect whether this file uses block references (ET CAD style)
    has_inserts = any(e.dxftype() == "INSERT" for e in msp)

    if has_inserts:
        return _parse_insert_based(doc, msp)
    else:
        return _parse_flat(msp)
