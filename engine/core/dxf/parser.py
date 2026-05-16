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
    grainline: tuple[tuple[float, float], tuple[float, float]] | None = None
    # grainline = ((start_x, start_y), (end_x, end_y)) in raw DXF coordinates


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
        # Try to extend chain from either end
        changed = True
        while changed:
            changed = False
            for i, seg in enumerate(remaining):
                if _distance(chain[-1], seg[0]) <= _CLOSE_TOLERANCE:
                    chain.extend(seg[1:])
                    remaining.pop(i)
                    changed = True
                    break
                elif _distance(chain[-1], seg[-1]) <= _CLOSE_TOLERANCE:
                    chain.extend(reversed(seg[:-1]))
                    remaining.pop(i)
                    changed = True
                    break
                elif _distance(chain[0], seg[-1]) <= _CLOSE_TOLERANCE:
                    chain[:0] = seg[:-1]
                    remaining.pop(i)
                    changed = True
                    break
                elif _distance(chain[0], seg[0]) <= _CLOSE_TOLERANCE:
                    chain[:0] = list(reversed(seg))[:-1]
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

    Open segments are grouped by DXF layer before chaining.  ET CAD blocks
    contain outlines for multiple sizes on different layers; mixing them
    produces crossed polygons.
    """
    closed_polys: list[list[tuple[float, float]]] = []
    # layer -> list of open segment point lists
    open_by_layer: dict[str, list[list[tuple[float, float]]]] = {}

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
            layer = entity.dxf.layer
            open_by_layer.setdefault(layer, []).append(points)

    # Chain open segments per layer so outlines from different sizes don't mix
    for segments in open_by_layer.values():
        closed_polys.extend(_chain_open_segments(segments))

    return closed_polys


def _parse_quantity(block) -> int:
    """Scan TEXT entities in a block for 'Quantity: N'; return N (default 1)."""
    for entity in block:
        if entity.dxftype() == "TEXT":
            text = entity.dxf.text.strip()
            if text.startswith("Quantity:"):
                try:
                    return max(1, int(text.split(":", 1)[1].strip()))
                except ValueError:
                    pass
    return 1


def _extract_grainline(
    block,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Return (start, end) of the first LINE on layer '7' in the block, or None."""
    for entity in block:
        if entity.dxftype() == "LINE" and entity.dxf.layer == "7":
            start = (float(entity.dxf.start.x), float(entity.dxf.start.y))
            end = (float(entity.dxf.end.x), float(entity.dxf.end.y))
            return (start, end)
    return None


def _parse_insert_based(doc, msp) -> list[RawPiece]:
    """
    Extract pieces from an INSERT-based file (ET CAD style).

    Each INSERT in modelspace is one piece instance.  If the same block is
    referenced multiple times (e.g. two sleeves from one template), each
    INSERT produces a separate RawPiece; duplicate names get a numeric suffix.

    When a block contains a 'Quantity: N' TEXT entity, that INSERT expands to
    N pieces named '{name} (1)' … '{name} (N)'.  Quantity 1 produces one piece
    with no suffix.
    """
    result: list[RawPiece] = []
    name_counts: dict[str, int] = {}

    for entity in msp:
        if entity.dxftype() != "INSERT":
            continue

        block_name = entity.dxf.name
        if block_name.startswith("*"):
            continue

        try:
            block = doc.blocks[block_name]
        except KeyError:
            continue

        closed_polys = _collect_closed_polylines(block)
        if not closed_polys:
            continue

        count = name_counts.get(block_name, 0)
        name_counts[block_name] = count + 1
        base_name = block_name if count == 0 else f"{block_name}_{count}"

        quantity = _parse_quantity(block)
        best = max(closed_polys, key=_polygon_area)
        grainline = _extract_grainline(block)

        for i in range(quantity):
            piece_name = f"{base_name} ({i + 1})" if quantity > 1 else base_name
            result.append(RawPiece(layer=piece_name, points=best, is_closed=True, grainline=grainline))

    return result


def _parse_flat(msp) -> list[RawPiece]:
    """
    Fallback: extract pieces from a flat modelspace (no INSERTs).

    Groups polylines by layer; picks the largest closed outline per layer.
    Supports both natively-closed polylines and chained open segments.
    """
    # Collect entities per non-ignored layer so _collect_closed_polylines
    # can handle open-segment chaining within each layer independently.
    by_layer: dict[str, list] = {}
    for entity in msp:
        layer = entity.dxf.layer
        if layer not in _IGNORED_LAYERS:
            by_layer.setdefault(layer, []).append(entity)

    result: list[RawPiece] = []
    for layer, entities in by_layer.items():
        closed_polys = _collect_closed_polylines(entities)
        if not closed_polys:
            continue
        best = max(closed_polys, key=_polygon_area)
        result.append(RawPiece(layer=layer, points=best, is_closed=True))

    return result


def _read_dxf(tmp_path: str):
    """
    Read a DXF file, retrying with CJK encodings when auto-detection yields
    garbled text.

    ezdxf uses the $DWGCODEPAGE header to pick an encoding.  Many Chinese CAD
    files declare ANSI_1252 (CP1252) while storing GBK or Big5 bytes, so
    layer/block names come out as Latin-supplement characters (U+0080–U+00FF).
    When that signature is detected, the file is re-read with 'gbk' then 'big5'.
    """
    try:
        doc = ezdxf.readfile(tmp_path)
    except OSError as exc:
        raise ezdxf.DXFStructureError(str(exc)) from exc

    # Check if any block/layer name contains Latin-supplement chars — the
    # tell-tale sign of CJK bytes misinterpreted as CP1252.
    names: list[str] = [b.name for b in doc.blocks if not b.name.startswith("*")]
    names += [e.dxf.layer for e in doc.modelspace() if hasattr(e.dxf, "layer")]
    has_garbled = any(any(0x80 <= ord(c) <= 0xFF for c in n) for n in names)

    if has_garbled:
        for enc in ("gbk", "big5"):
            try:
                return ezdxf.readfile(tmp_path, encoding=enc)
            except Exception:
                continue

    return doc


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
        doc = _read_dxf(tmp_path)
    finally:
        os.unlink(tmp_path)
    msp = doc.modelspace()

    # Detect whether this file uses block references (ET CAD style)
    has_inserts = any(e.dxftype() == "INSERT" for e in msp)

    if has_inserts:
        return _parse_insert_based(doc, msp)
    else:
        return _parse_flat(msp)
