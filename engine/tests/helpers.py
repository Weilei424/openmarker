# Shared test utilities for creating synthetic DXF fixtures in memory.

import io
import ezdxf


def make_insert_dxf_bytes(pieces: dict[str, list[tuple[float, float]]]) -> bytes:
    """
    Create a DXF in ET CAD INSERT-based format.

    Each piece is stored as a block with a closed LWPOLYLINE, referenced by
    an INSERT in modelspace — matching the real ET CAD file structure.

    Args:
        pieces: mapping of block_name -> list of (x, y) points
    Returns:
        DXF file content as bytes
    """
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for block_name, points in pieces.items():
        blk = doc.blocks.new(block_name)
        blk.add_lwpolyline(points, close=True, dxfattribs={"layer": "1"})
        msp.add_blockref(block_name, insert=(0, 0))
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def make_dxf_bytes(pieces: dict[str, list[tuple[float, float]]]) -> bytes:
    """
    Create a minimal DXF in memory with one closed LWPOLYLINE per layer.

    Args:
        pieces: mapping of layer_name -> list of (x, y) points
    Returns:
        DXF file content as bytes
    """
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for layer_name, points in pieces.items():
        # Layer "0" always exists in a new DXF document; only add new ones
        if layer_name != "0" and not doc.layers.has_entry(layer_name):
            doc.layers.add(layer_name)
        msp.add_lwpolyline(points, close=True, dxfattribs={"layer": layer_name})
    # doc.write() requires a text stream
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")
