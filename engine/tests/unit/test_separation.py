import os
import pytest
from core.models.piece import Piece, BoundingBox
from core.layout.separation import _resolve_sparrow_path


def _rect(piece_id: str, w: float, h: float, grainline: float | None = None) -> Piece:
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        grainline_direction_deg=grainline,
    )


# --- _resolve_sparrow_path ---

def test_resolve_prefers_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "sparrow.exe"
    fake.write_bytes(b"\x00")
    monkeypatch.setenv("OPENMARKER_SPARROW_PATH", str(fake))
    assert _resolve_sparrow_path() == str(fake)


def test_resolve_missing_raises(monkeypatch):
    monkeypatch.delenv("OPENMARKER_SPARROW_PATH", raising=False)
    monkeypatch.setattr(os.path, "isfile", lambda p: False)
    with pytest.raises(FileNotFoundError):
        _resolve_sparrow_path()


from core.layout.separation import _group_to_items, _instance_json, EDGE_GAP


# --- _group_to_items: grouping + demand ---

def test_group_demand_and_piece_ids():
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0),
              _rect("piece_1__c0", 50, 30, 90.0)]
    items = _group_to_items(pieces, "bi", 90.0)
    assert [it.index for it in items] == [0, 1]
    assert items[0].piece_ids == ["piece_0__c0", "piece_0__c1"]
    assert items[1].piece_ids == ["piece_1__c0"]


# --- allowed_orientations per grain (the grain table) ---

def test_allowed_single_grain_no_flip():
    items = _group_to_items([_rect("p__c0", 60, 40, 90.0)], "single", 90.0)
    assert items[0].allowed_offsets == [0.0]


def test_allowed_bi_grain_flip():
    items = _group_to_items([_rect("p__c0", 60, 40, 90.0)], "bi", 90.0)
    assert items[0].allowed_offsets == [0.0, 180.0]


def test_allowed_no_grainline_cardinals():
    items = _group_to_items([_rect("p__c0", 60, 40, None)], "single", 90.0)
    assert items[0].allowed_offsets == [0.0, 90.0, 180.0, 270.0]


# --- emit transform: grain-aligned + 90deg axis map, origin-normalized ---

def test_emit_axis_map_bounds():
    # 100x50 rect, grainline 90 == fabric grain 90 -> target 0, emit rotation 90deg.
    # 90deg rotation swaps extents: x 100->50 (along-grain->length), y 50->100 (cross-grain->width).
    items = _group_to_items([_rect("p__c0", 100, 50, 90.0)], "single", 90.0)
    minx, miny, maxx, maxy = items[0].emitted.bounds
    assert (round(minx), round(miny)) == (0, 0)          # origin-normalized
    assert (round(maxx), round(maxy)) == (50, 100)        # along-grain->X, cross-grain->Y


# --- _instance_json shape ---

def test_instance_json_shape():
    items = _group_to_items([_rect("p__c0", 100, 50, 90.0), _rect("p__c1", 100, 50, 90.0)], "bi", 90.0)
    inst = _instance_json(items, strip_height=1631.0)
    assert inst["strip_height"] == 1631.0
    assert inst["items"][0]["id"] == 0
    assert inst["items"][0]["demand"] == 2
    assert inst["items"][0]["allowed_orientations"] == [0.0, 180.0]
    assert inst["items"][0]["shape"]["type"] == "simple_polygon"
    assert len(inst["items"][0]["shape"]["data"]) == 4  # no closing dup
