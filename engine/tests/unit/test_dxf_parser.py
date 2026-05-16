# Unit tests for engine/core/dxf/parser.py

import io
import sys
import os
import pytest
import ezdxf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from helpers import make_dxf_bytes, make_insert_dxf_bytes
import dataclasses

from core.dxf.parser import parse_dxf, _chain_open_segments, _parse_quantity
from core.geometry.normalize import normalize_piece


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


# --- INSERT-based (ET CAD) path ---

def test_insert_based_single_piece():
    dxf = make_insert_dxf_bytes({"FRONT-BODICE": RECTANGLE})
    pieces = parse_dxf(dxf)
    assert len(pieces) == 1
    assert pieces[0].layer == "FRONT-BODICE"


def test_insert_based_multiple_pieces():
    dxf = make_insert_dxf_bytes({
        "FRONT": RECTANGLE,
        "BACK": [(0, 0), (120, 0), (120, 100), (0, 100)],
        "SLEEVE": TRIANGLE,
    })
    pieces = parse_dxf(dxf)
    assert len(pieces) == 3
    assert {p.layer for p in pieces} == {"FRONT", "BACK", "SLEEVE"}


def test_insert_based_repeated_block():
    """Two INSERTs referencing the same block should produce two pieces."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    blk = doc.blocks.new("SLEEVE")
    blk.add_lwpolyline(RECTANGLE, close=True, dxfattribs={"layer": "1"})
    msp.add_blockref("SLEEVE", insert=(0, 0))
    msp.add_blockref("SLEEVE", insert=(200, 0))  # second instance
    stream = io.StringIO()
    doc.write(stream)
    dxf = stream.getvalue().encode("utf-8")

    pieces = parse_dxf(dxf)
    assert len(pieces) == 2
    assert pieces[0].layer == "SLEEVE"
    assert pieces[1].layer == "SLEEVE_1"


# --- Open-segment chaining ---

def test_chain_open_segments_rectangle():
    """Four open segments forming a rectangle should chain into one closed loop."""
    segs = [
        [(0, 0), (10, 0)],
        [(10, 0), (10, 8)],
        [(10, 8), (0, 8)],
        [(0, 8), (0, 0)],
    ]
    result = _chain_open_segments(segs)
    assert len(result) == 1
    assert len(result[0]) >= 4


def test_flat_file_open_segments():
    """Flat modelspace with open segments that chain into a closed outline."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.add("PIECE")
    # Rectangle split into four open segments on the same layer
    msp.add_lwpolyline([(0, 0), (10, 0)], close=False, dxfattribs={"layer": "PIECE"})
    msp.add_lwpolyline([(10, 0), (10, 8)], close=False, dxfattribs={"layer": "PIECE"})
    msp.add_lwpolyline([(10, 8), (0, 8)], close=False, dxfattribs={"layer": "PIECE"})
    msp.add_lwpolyline([(0, 8), (0, 0)], close=False, dxfattribs={"layer": "PIECE"})
    stream = io.StringIO()
    doc.write(stream)
    dxf = stream.getvalue().encode("utf-8")

    pieces = parse_dxf(dxf)
    assert len(pieces) == 1
    assert pieces[0].layer == "PIECE"


# --- Quantity expansion ---

def _make_dxf_with_quantity(block_name: str, quantity: int, points=None) -> bytes:
    """Helper: create a minimal DXF with one block INSERT, given quantity TEXT."""
    if points is None:
        points = [(0, 0), (100, 0), (100, 100), (0, 100)]
    doc = ezdxf.new("R2010")
    blk = doc.blocks.new(block_name)
    blk.add_lwpolyline(points, close=True, dxfattribs={"layer": "1"})
    blk.add_text(f"Quantity: {quantity}", dxfattribs={"layer": "1", "insert": (0, 0), "height": 0})
    msp = doc.modelspace()
    msp.add_blockref(block_name, (0, 0))
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def test_quantity_1_produces_one_piece_no_suffix():
    data = _make_dxf_with_quantity("FRONT", 1)
    pieces = parse_dxf(data)
    assert len(pieces) == 1
    assert pieces[0].layer == "FRONT"


def test_quantity_2_produces_two_pieces_with_suffix():
    data = _make_dxf_with_quantity("FRONT", 2)
    pieces = parse_dxf(data)
    assert len(pieces) == 2
    assert pieces[0].layer == "FRONT (1)"
    assert pieces[1].layer == "FRONT (2)"


def test_quantity_missing_defaults_to_one():
    doc = ezdxf.new("R2010")
    blk = doc.blocks.new("BACK")
    blk.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True, dxfattribs={"layer": "1"})
    msp = doc.modelspace()
    msp.add_blockref("BACK", (0, 0))
    stream = io.StringIO()
    doc.write(stream)
    data = stream.getvalue().encode("utf-8")
    pieces = parse_dxf(data)
    assert len(pieces) == 1
    assert pieces[0].layer == "BACK"


# --- Grainline extraction ---

def _make_dxf_with_grainline(
    block_name: str,
    piece_points: list,
    grain_start: tuple,
    grain_end: tuple,
) -> bytes:
    """Helper: DXF block with a piece polygon and a layer-7 LINE grainline."""
    doc = ezdxf.new("R2010")
    blk = doc.blocks.new(block_name)
    blk.add_lwpolyline(piece_points, close=True, dxfattribs={"layer": "1"})
    blk.add_line(grain_start, grain_end, dxfattribs={"layer": "7"})
    msp = doc.modelspace()
    msp.add_blockref(block_name, (0, 0))
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def test_grainline_extracted_from_layer_7():
    data = _make_dxf_with_grainline(
        "PIECE",
        [(0, 0), (100, 0), (100, 200), (0, 200)],
        grain_start=(50, 0),
        grain_end=(50, 100),
    )
    pieces = parse_dxf(data)
    assert len(pieces) == 1
    assert pieces[0].grainline is not None
    start, end = pieces[0].grainline
    assert start == pytest.approx((50.0, 0.0), abs=0.01)
    assert end == pytest.approx((50.0, 100.0), abs=0.01)


def test_grainline_absent_when_no_layer7_line():
    doc = ezdxf.new("R2010")
    blk = doc.blocks.new("NOLINE")
    blk.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True, dxfattribs={"layer": "1"})
    msp = doc.modelspace()
    msp.add_blockref("NOLINE", (0, 0))
    stream = io.StringIO()
    doc.write(stream)
    pieces = parse_dxf(stream.getvalue().encode("utf-8"))
    assert pieces[0].grainline is None


# --- Acceptance tests: 2×2 fixture (2 piece types × quantity 2, with grainlines) ---

_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "..", "..", "..", "..",
    "examples", "input",
    "2_pieces_x_2_with_grainline.dxf"
)


def _load_fixture_raw():
    with open(_FIXTURE_PATH, "rb") as f:
        return parse_dxf(f.read())


def test_2_pieces_x_2_fixture_produces_4_pieces():
    """Fixture has 2 piece types each with quantity 2 → 4 raw pieces."""
    pieces = _load_fixture_raw()
    assert len(pieces) == 4


def test_2_pieces_x_2_fixture_naming():
    """Piece names match expected quantity-expanded layer names."""
    pieces = _load_fixture_raw()
    names = {p.layer for p in pieces}
    assert names == {"123.2.S (1)", "123.2.S (2)", "123.1.S (1)", "123.1.S (2)"}


def test_2_pieces_x_2_fixture_grainlines_present():
    """All 4 pieces carry a non-None grainline extracted from layer-7 LINE."""
    pieces = _load_fixture_raw()
    for p in pieces:
        assert p.grainline is not None, f"piece {p.layer!r} has no grainline"


def test_2_pieces_x_2_fixture_normalized_grainline_degrees():
    """Normalized grainline angles match the fixture geometry (5° tolerance).

    123.2.S pieces: vertical line → 270°
    123.1.S pieces: horizontal line → 0°
    """
    raw_pieces = _load_fixture_raw()
    normalized = [normalize_piece(r, f"p{i}") for i, r in enumerate(raw_pieces)]

    for p in normalized:
        if "123.2.S" in p.name:
            assert p.grainline_direction_deg == pytest.approx(270.0, abs=5), (
                f"{p.name}: expected ~270°, got {p.grainline_direction_deg}"
            )
        elif "123.1.S" in p.name:
            assert p.grainline_direction_deg == pytest.approx(0.0, abs=5), (
                f"{p.name}: expected ~0°, got {p.grainline_direction_deg}"
            )
