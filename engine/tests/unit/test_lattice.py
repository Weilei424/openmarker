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


def test_stack_frontier_never_retreats_past_earlier_bands():
    # Band 2 settles deeper (120mm) than its own extent (60mm). The stacking
    # frontier must stay at band 1's edge (y=200), not retreat to 140 — a
    # third band starting below the frontier would begin INSIDE band 1's
    # right column and settle would silently accept the overlap.
    pieces = [_notch_l("piece_0__c0", grainline=90.0),
              _rect("piece_1__c0", 60, 60, grainline=90.0),
              _rect("piece_2__c0", 150, 20, grainline=90.0)]
    placements, marker, _ = banded_blf_layout(pieces, 300.0, "single", 90.0)
    _validate_layout(placements, pieces, 300.0, "single", 90.0)
    # rect 150x20 rests on the notch-L column top (y 200..220)
    assert marker == pytest.approx(220.0, abs=2.1)


# --- lattice_layout ---

from core.layout.lattice import lattice_layout


def test_lattice_valid_and_complete():
    pieces = _mixed_set()
    placements, marker, util = lattice_layout(pieces, FABRIC_W, "bi", 90.0)
    _validate_layout(placements, pieces, FABRIC_W, "bi", 90.0)
    assert {p.piece_id for p in placements} == {p.id for p in pieces}
    assert marker > 0 and 0 < util <= 100


def test_lattice_rotations_stay_in_bi_grain_set():
    placements, _, _ = lattice_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    for p in placements:
        assert min(p.rotation_deg % 360.0, abs(p.rotation_deg % 360.0 - 180.0),
                   abs(p.rotation_deg % 360.0 - 360.0)) < 1e-6


def test_lattice_single_mode_locks_rotation():
    placements, _, _ = lattice_layout(
        _copies(_rect, "p", 4, 300, 200, grainline=90.0), FABRIC_W, "single", 90.0)
    assert all(abs(p.rotation_deg % 360.0) < 1e-6 for p in placements)


def test_lattice_no_grainline_uses_cardinals_only():
    pieces = _copies(_rect, "p", 4, 300, 200, grainline=None)
    placements, _, _ = lattice_layout(pieces, FABRIC_W, "bi", 90.0)
    _validate_layout(placements, pieces, FABRIC_W, "bi", 90.0)
    for p in placements:
        assert any(abs(((p.rotation_deg - c + 180.0) % 360.0) - 180.0) < 1e-6
                   for c in (0.0, 90.0, 180.0, 270.0))


def test_lattice_deterministic():
    a = lattice_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    b = lattice_layout(_mixed_set(), FABRIC_W, "bi", 90.0)
    assert [(p.piece_id, p.x, p.y, p.rotation_deg) for p in a[0]] == \
           [(p.piece_id, p.x, p.y, p.rotation_deg) for p in b[0]]
    assert a[1] == b[1]


def test_lattice_too_wide_raises():
    with pytest.raises(ValueError):
        lattice_layout(_copies(_rect, "p", 2, 1200, 100, grainline=90.0),
                       FABRIC_W, "bi", 90.0)


def test_lattice_ladder_log_uses_lattice_rung():
    log = []
    lattice_layout(_mixed_set(), FABRIC_W, "bi", 90.0, ladder_log=log)
    assert len(log) == 3
    assert all(rung in ("lattice", "blf") for _, rung in log)
    assert log[0][1] == "lattice"      # the plain-rect group must lattice cleanly


def test_lattice_falls_back_to_blf_band(monkeypatch):
    import core.layout.lattice as lat
    monkeypatch.setattr(lat, "_build_lattice_band",
                        lambda group, W, gm, gd, cache: None)
    log = []
    pieces = _mixed_set()
    placements, _, _ = lattice_layout(pieces, FABRIC_W, "bi", 90.0, ladder_log=log)
    _validate_layout(placements, pieces, FABRIC_W, "bi", 90.0)
    assert all(rung == "blf" for _, rung in log)


def test_triangle_pair_beats_single_by_20pct():
    # Two 180-deg right triangles tile a rectangle (100% density); the best
    # translational single-triangle lattice is far sparser. single grain mode
    # forbids the 180 partner -> single-cell lattice as the reference.
    tris = _copies(_rtri, "t", 10, 300, 200, grainline=90.0)
    m_pair = lattice_layout(tris, FABRIC_W, "bi", 90.0)[1]
    m_single = lattice_layout(tris, FABRIC_W, "single", 90.0)[1]
    assert m_pair <= 0.8 * m_single


def test_rect_pair_no_gain_over_single():
    rects = _copies(_rect, "r", 10, 300, 200, grainline=90.0)
    m_bi = lattice_layout(rects, FABRIC_W, "bi", 90.0)[1]
    m_single = lattice_layout(rects, FABRIC_W, "single", 90.0)[1]
    assert abs(m_bi - m_single) <= 1.0


def test_lattice_bias_grainline_strip():
    # 32x330 strips with a 315-deg grainline: allowed engine rotations are
    # {135, 315} (target = (90 - 315) % 360 = 135) — diagonal lattice.
    strips = _copies(_rect, "s", 10, 32, 330, grainline=315.0)
    placements, _, _ = lattice_layout(strips, 800.0, "bi", 90.0)
    _validate_layout(placements, strips, 800.0, "bi", 90.0)
    for p in placements:
        assert any(abs(((p.rotation_deg - a + 180.0) % 360.0) - 180.0) < 1e-6
                   for a in (135.0, 315.0))


def test_lattice_single_copy_group():
    placements, marker, _ = lattice_layout(
        [_rect("p__c0", 300, 200, grainline=90.0)], FABRIC_W, "bi", 90.0)
    assert len(placements) == 1 and marker == pytest.approx(200.0, abs=1e-6)
