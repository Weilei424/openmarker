import pytest
from shapely.geometry import Polygon as ShapelyPolygon

from core.layout.lattice import _shape_groups, banded_blf_layout
from core.layout.separation import _validate_layout
from core.models.piece import BoundingBox, Piece

FABRIC_W = 1000.0


def _piece(pid, points, grainline=None):
    poly = ShapelyPolygon(points)
    minx, miny, maxx, maxy = poly.bounds
    return Piece(id=pid, name=pid, polygon=list(points), area=poly.area,
                 bbox=BoundingBox(minx, miny, maxx, maxy, maxx - minx, maxy - miny),
                 is_valid=True, grainline_direction_deg=grainline)


def _rect(pid, w, h, grainline=None):
    return _piece(pid, [(0, 0), (w, 0), (w, h), (0, h)], grainline)


def _rtri(pid, w, h, grainline=None):
    return _piece(pid, [(0, 0), (w, 0), (0, h)], grainline)


def _lshape(pid, grainline=None):
    # bottom bar y 0..80 full width 0..200 + left column x 0..80 up to y 200
    return _piece(pid, [(0, 0), (200, 0), (200, 80), (80, 80), (80, 200), (0, 200)],
                  grainline)


def _notch_l(pid, grainline=None):
    # bottom bar y 0..80 full width 0..200 + RIGHT column x 120..200 up to y 200;
    # free notch = x 0..120, y 80..200
    return _piece(pid, [(0, 0), (200, 0), (200, 200), (120, 200), (120, 80), (0, 80)],
                  grainline)


def _copies(factory, base, n, *args, **kw):
    return [factory(f"{base}__c{i}", *args, **kw) for i in range(n)]


def _mixed_set(n=6):
    return (_copies(_rect, "piece_0", n, 300, 200, grainline=90.0)
            + _copies(_lshape, "piece_1", n, grainline=90.0)
            + _copies(_rtri, "piece_2", n, 250, 180, grainline=90.0))


# --- _shape_groups ---

def test_shape_groups_merges_exact_duplicates_any_ring_start():
    pts_a = [(0, 0), (300, 0), (300, 200), (0, 200)]
    pts_b = [(300, 0), (300, 200), (0, 200), (0, 0)]   # same ring, rotated start
    pieces = (_copies(_piece, "piece_0", 2, pts_a, grainline=90.0)
              + _copies(_piece, "piece_1", 2, pts_b, grainline=90.0)
              + _copies(_rect, "piece_2", 2, 100, 50, grainline=90.0))
    groups = _shape_groups(pieces)
    assert sorted(len(g) for g in groups) == [2, 4]


def test_shape_groups_respects_grainline():
    pieces = (_copies(_rect, "piece_0", 2, 300, 200, grainline=90.0)
              + _copies(_rect, "piece_1", 2, 300, 200, grainline=180.0))
    assert [len(g) for g in _shape_groups(pieces)] == [2, 2]


# --- banded_blf_layout contract ---

def test_banded_valid_and_complete():
    pieces = _mixed_set()
    placements, marker, util = banded_blf_layout(pieces, FABRIC_W, "bi", 90.0)
    _validate_layout(placements, pieces, FABRIC_W, "bi", 90.0)   # raises on violation
    assert {p.piece_id for p in placements} == {p.id for p in pieces}
    assert marker > 0 and 0 < util <= 100


def test_banded_rotations_stay_in_bi_grain_set():
    placements, _, _ = banded_blf_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    for p in placements:
        assert min(p.rotation_deg % 360.0, abs(p.rotation_deg % 360.0 - 180.0),
                   abs(p.rotation_deg % 360.0 - 360.0)) < 1e-6


def test_banded_single_mode_locks_rotation():
    placements, _, _ = banded_blf_layout(
        _copies(_rect, "p", 4, 300, 200, grainline=90.0), FABRIC_W, "single", 90.0)
    assert all(abs(p.rotation_deg % 360.0) < 1e-6 for p in placements)


def test_banded_deterministic():
    a = banded_blf_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    b = banded_blf_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    assert [(p.piece_id, p.x, p.y, p.rotation_deg) for p in a[0]] == \
           [(p.piece_id, p.x, p.y, p.rotation_deg) for p in b[0]]
    assert a[1] == b[1]


def test_banded_too_wide_raises():
    with pytest.raises(ValueError):
        banded_blf_layout(_copies(_rect, "p", 2, 1200, 100, grainline=90.0),
                          FABRIC_W, "bi", 90.0)


def test_banded_empty_raises():
    with pytest.raises(ValueError):
        banded_blf_layout([], FABRIC_W, "bi", 90.0)


def test_banded_ladder_log():
    log = []
    banded_blf_layout(_mixed_set(), FABRIC_W, "bi", 90.0, ladder_log=log)
    assert len(log) == 3 and all(rung == "blf" for _, rung in log)


def test_banded_single_copy_group():
    placements, marker, _ = banded_blf_layout(
        [_rect("p__c0", 300, 200, grainline=90.0)], FABRIC_W, "bi", 90.0)
    assert len(placements) == 1 and marker == pytest.approx(200.0, abs=1e-6)


def test_settle_slides_band_into_notch():
    # Band 1 (bigger area) = notch-L; band 2 = 60x60 rect placed above it, which
    # settles down through the free notch until it rests on the y<=80 bottom bar.
    pieces = [_notch_l("piece_0__c0", grainline=90.0),
              _rect("piece_1__c0", 60, 60, grainline=90.0)]
    placements, marker, _ = banded_blf_layout(pieces, 300.0, "single", 90.0)
    _validate_layout(placements, pieces, 300.0, "single", 90.0)
    # without settle the marker would be 260 (200 + 60); with settle the rect
    # rests at y ~= 80..140 -> marker stays 200 (2mm probe granularity slack)
    assert marker == pytest.approx(200.0, abs=2.1)
