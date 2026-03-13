# Unit tests for engine/core/dxf/parser.py

import sys
import os
import pytest
import ezdxf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from helpers import make_dxf_bytes
from core.dxf.parser import parse_dxf


RECTANGLE = [(0, 0), (100, 0), (100, 80), (0, 80)]
TRIANGLE = [(0, 0), (50, 0), (25, 40)]


def test_parse_single_piece():
    dxf = make_dxf_bytes({"FRONT_BODICE": RECTANGLE})
    pieces = parse_dxf(dxf)
    assert len(pieces) == 1
    assert pieces[0].layer == "FRONT_BODICE"
    assert len(pieces[0].points) == 4
    assert pieces[0].is_closed is True


def test_parse_multiple_pieces():
    dxf = make_dxf_bytes({
        "FRONT": RECTANGLE,
        "BACK": TRIANGLE,
        "SLEEVE": [(0, 0), (60, 0), (60, 120), (0, 120)],
    })
    pieces = parse_dxf(dxf)
    assert len(pieces) == 3
    names = {p.layer for p in pieces}
    assert names == {"FRONT", "BACK", "SLEEVE"}


def test_ignores_layer_zero():
    dxf = make_dxf_bytes({"0": RECTANGLE, "FRONT": TRIANGLE})
    pieces = parse_dxf(dxf)
    assert len(pieces) == 1
    assert pieces[0].layer == "FRONT"


def test_open_polyline_auto_closed():
    """A polyline whose first and last points are within 0.1 mm should be accepted."""
    import io
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.add("PIECE")
    # Last point is 0.05 mm away from first point — not flagged closed by ezdxf
    pts = [(0, 0), (100, 0), (100, 80), (0.05, 0.0)]
    msp.add_lwpolyline(pts, close=False, dxfattribs={"layer": "PIECE"})
    stream = io.StringIO()
    doc.write(stream)
    dxf_bytes = stream.getvalue().encode("utf-8")

    pieces = parse_dxf(dxf_bytes)
    assert len(pieces) == 1
    assert pieces[0].layer == "PIECE"
    assert pieces[0].is_closed is True


def test_invalid_dxf_bytes():
    with pytest.raises(ezdxf.DXFStructureError):
        parse_dxf(b"this is not a dxf file")
