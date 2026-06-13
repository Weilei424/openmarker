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


from core.layout.separation import _group_to_items, _instance_json


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


from core.layout.separation import _reconstruct
from core.layout.heuristic import _placed_polygon, _has_area_overlap


def test_reconstruct_round_trip_grain_and_no_overlap():
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0)]
    items = _group_to_items(pieces, "bi", 90.0)
    w = items[0].emitted.bounds[2]   # along-grain extent -> jagua X (length)
    h = items[0].emitted.bounds[3]   # cross-grain extent -> jagua Y (width)
    # Simulated sparrow solution: two copies side-by-side, second flipped 180.
    sol = {"solution": {"strip_width": 2 * w, "layout": {"placed_items": [
        {"item_id": 0, "transformation": {"rotation": 0.0,   "translation": [0.0, 0.0]}},
        {"item_id": 0, "transformation": {"rotation": 180.0, "translation": [2 * w, h]}},
    ]}}}
    fabric = h
    placements = _reconstruct(sol, items, fabric_width_mm=fabric)

    assert {pl.piece_id for pl in placements} == {"piece_0__c0", "piece_0__c1"}
    for pl in placements:                                  # grain: engine set {0,180}
        assert round(pl.rotation_deg) % 180 == 0
    pmap = {p.id: p for p in pieces}
    polys = [_placed_polygon(pmap[pl.piece_id], pl.x, pl.y, pl.rotation_deg) for pl in placements]
    assert not _has_area_overlap(polys[0], polys[1])        # round-trip is overlap-free
    for poly in polys:                                      # cross-grain landed on X, within width
        assert poly.bounds[0] >= -0.5 and poly.bounds[2] <= fabric + 0.5
        assert poly.bounds[1] >= -0.5
    # NOTE: a global axis-map SIGN error (-90 vs +90) is a whole-layout reflection, which is
    # reflection-invariant for symmetric/identical pieces (same bbox; rotation_deg is analytic)
    # and so cannot surface here. It is caught by _validate_layout's within-fabric-width check on
    # real length-dominant markers (integration test + bench), where a reflection drops the marker
    # length onto the width axis and is rejected.


from core.layout.separation import _validate_layout
from core.layout.heuristic import Placement


def _clean_placements():
    # two 60x40 copies, grainline 90, bi-grain: side by side, no overlap, rotation 0
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0)]
    placements = [Placement("piece_0__c0", 10.0, 10.0, 0.0),
                  Placement("piece_0__c1", 10.0, 60.0, 0.0)]
    return pieces, placements


def test_validate_passes_clean():
    pieces, placements = _clean_placements()
    _validate_layout(placements, pieces, fabric_width_mm=200.0, grain_mode="bi", fabric_grain_deg=90.0)


def test_validate_rejects_off_grain():
    pieces, placements = _clean_placements()
    placements[1] = Placement("piece_0__c1", 10.0, 60.0, 90.0)  # 90 not in {0,180}
    with pytest.raises(ValueError, match="off-grain"):
        _validate_layout(placements, pieces, 200.0, "bi", 90.0)


def test_validate_rejects_overlap():
    pieces, placements = _clean_placements()
    placements[1] = Placement("piece_0__c1", 10.0, 10.0, 0.0)  # identical position
    with pytest.raises(ValueError, match="overlap"):
        _validate_layout(placements, pieces, 200.0, "bi", 90.0)


def test_validate_rejects_over_width():
    pieces, placements = _clean_placements()
    placements[1] = Placement("piece_0__c1", 10.0, 5000.0, 0.0)  # far outside fabric width
    with pytest.raises(ValueError, match="outside fabric"):
        _validate_layout(placements, pieces, 40.0, "bi", 90.0)


def test_validate_rejects_missing():
    pieces, placements = _clean_placements()
    with pytest.raises(ValueError, match="placed 1 of 2"):
        _validate_layout(placements[:1], pieces, 200.0, "bi", 90.0)


def test_validate_rejects_unknown_piece_id():
    # A placed id not present in pieces -> clean ValueError (not an uncaught KeyError).
    pieces, placements = _clean_placements()
    placements[1] = Placement("ghost__c0", 10.0, 60.0, 0.0)
    with pytest.raises(ValueError, match="unknown piece_id"):
        _validate_layout(placements, pieces, 200.0, "bi", 90.0)


from core.layout import separation as sep


def test_kill_current_sparrow_terminates_one():
    class _Dummy:
        def __init__(self): self.killed = False
        def terminate(self): self.killed = True
    d = _Dummy()
    sep._register_sparrow(d)
    sep.kill_current_sparrow()
    assert d.killed is True
    sep._unregister_sparrow(d)
    sep.kill_current_sparrow()  # no-op when empty


def test_kill_current_sparrow_terminates_all_concurrent():
    class _Dummy:
        def __init__(self): self.killed = False
        def terminate(self): self.killed = True
    a, b = _Dummy(), _Dummy()
    sep._register_sparrow(a); sep._register_sparrow(b)
    sep.kill_current_sparrow()
    assert a.killed and b.killed
    sep._unregister_sparrow(a); sep._unregister_sparrow(b)


# --- run_separation_layout ---

import core.layout.separation as sep_mod


def test_run_separation_layout_assembles(monkeypatch):
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0)]
    items = sep_mod._group_to_items(pieces, "bi", 90.0)
    w = items[0].emitted.bounds[2]
    h = items[0].emitted.bounds[3]
    fabric = h
    canned = {"solution": {"strip_width": 2 * w, "layout": {"placed_items": [
        {"item_id": 0, "transformation": {"rotation": 0.0,   "translation": [0.0, 0.0]}},
        {"item_id": 0, "transformation": {"rotation": 180.0, "translation": [2 * w, h]}},
    ]}}}
    monkeypatch.setattr(sep_mod, "_run_sparrow", lambda instance, budget_s, seed: canned)
    placements, marker, util = sep_mod.run_separation_layout(
        pieces, fabric_width_mm=fabric, grain_mode="bi", fabric_grain_deg=90.0,
        budget_s=5, seed=42, warm_start=False)
    assert {p.piece_id for p in placements} == {"piece_0__c0", "piece_0__c1"}
    assert marker > 0 and 0 < util <= 100
    assert all(round(p.rotation_deg) % 180 == 0 for p in placements)


def test_run_separation_layout_empty_raises():
    with pytest.raises(ValueError, match="no pieces"):
        sep_mod.run_separation_layout([], 200.0, "bi", 90.0, budget_s=5)


from core.layout.heuristic import Placement as _Pl


def test_best_of_n_returns_shortest_valid(monkeypatch):
    calls = []
    def fake_solve(items, instance, pieces, fw, gm, fg, budget_s, seed):
        calls.append(seed)
        marker = {42: 1000.0, 43: 800.0, 44: 1200.0}[seed]
        return ([_Pl("p__c0", 0.0, 0.0, 0.0)], marker, 50.0)
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    pieces = [_rect("p__c0", 60, 40, 90.0)]
    placements, marker, util = sep.run_separation_layout(
        pieces, 200.0, "bi", 90.0, budget_s=5, seed=42, n_seeds=3, warm_start=False)
    assert sorted(calls) == [42, 43, 44]
    assert marker == 800.0   # shortest valid wins


def test_best_of_n_all_invalid_raises(monkeypatch):
    def fake_solve(*a, **k):
        raise ValueError("separation layout invalid: off-grain")
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    with pytest.raises(ValueError, match="all separation attempts invalid"):
        sep.run_separation_layout([_rect("p__c0", 60, 40, 90.0)], 200.0, "bi", 90.0,
                                  budget_s=5, seed=42, n_seeds=2, warm_start=False)


def test_best_of_n_cancel_takes_precedence(monkeypatch):
    # Even when one seed returns a valid result, a cancelled attempt makes the whole
    # run raise CancellationError (Stop must never return a partial best-of-N result).
    from core.layout.cancellation import CancellationError
    def fake_solve(items, instance, pieces, fw, gm, fg, budget_s, seed):
        if seed == 42:
            return ([_Pl("p__c0", 0.0, 0.0, 0.0)], 900.0, 50.0)
        raise CancellationError("cancelled")
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    with pytest.raises(CancellationError):
        sep.run_separation_layout([_rect("p__c0", 60, 40, 90.0)], 200.0, "bi", 90.0,
                                  budget_s=5, seed=42, n_seeds=2, warm_start=False)


# --- warm start (#7b): Fast-tier NFP-BLF layout fed to sparrow via -i ---

from core.layout.heuristic import auto_layout_polygon


def test_placements_to_jagua_round_trips_through_reconstruct():
    # The warm-start converter is the exact inverse of _reconstruct: a real Fast layout
    # encoded to jagua placed_items, then reconstructed, must reproduce a geometrically
    # FAITHFUL engine layout (validator passes; marker length preserved within slack).
    # copies of a base id are identical (real pieces come from replace(b, id=...)); the
    # converter relies on that — one `emitted` per base id covers all its copies.
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0),
              _rect("piece_1__c0", 80, 30, 90.0)]
    fabric = 200.0
    placements, marker, _ = auto_layout_polygon(pieces, fabric, "bi", 90.0, effort=1)
    items = _group_to_items(pieces, "bi", 90.0)
    placed_items = sep._placements_to_jagua(items, pieces, placements, marker)
    assert len(placed_items) == len(pieces)

    sol = {"solution": {"strip_width": marker + 1.0, "layout": {"placed_items": placed_items}}}
    rebuilt = _reconstruct(sol, items, fabric_width_mm=fabric)
    _validate_layout(rebuilt, pieces, fabric, "bi", 90.0)          # faithful: grain/overlap/width
    pmap = {p.id: p for p in pieces}
    rebuilt_marker = max(_placed_polygon(pmap[pl.piece_id], pl.x, pl.y, pl.rotation_deg).bounds[3]
                         for pl in rebuilt)
    assert abs(rebuilt_marker - marker) < 1.0                       # marker length preserved


def test_build_warm_start_returns_solution_dict():
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0)]
    items = _group_to_items(pieces, "bi", 90.0)
    ws = sep._build_warm_start(items, pieces, 200.0, "bi", 90.0)
    assert ws is not None
    assert ws["strip_width"] > 0
    assert len(ws["layout"]["placed_items"]) == 2
    assert "rotation" in ws["layout"]["placed_items"][0]["transformation"]


def test_build_warm_start_none_on_blf_failure(monkeypatch):
    # A Fast-layout failure must degrade to None (caller falls back to a cold start),
    # never propagate — warm start is pure upside and must never break Ultra.
    def boom(*a, **k):
        raise RuntimeError("blf exploded")
    monkeypatch.setattr(sep, "auto_layout_polygon", boom)
    pieces = [_rect("piece_0__c0", 60, 40, 90.0)]
    items = _group_to_items(pieces, "bi", 90.0)
    assert sep._build_warm_start(items, pieces, 200.0, "bi", 90.0) is None


def test_build_warm_start_propagates_cancellation(monkeypatch):
    # Stop during the Fast prelude must cancel the whole run, not silently fall back.
    from core.layout.cancellation import CancellationError
    def cancel(*a, **k):
        raise CancellationError("stop")
    monkeypatch.setattr(sep, "auto_layout_polygon", cancel)
    pieces = [_rect("piece_0__c0", 60, 40, 90.0)]
    items = _group_to_items(pieces, "bi", 90.0)
    with pytest.raises(CancellationError):
        sep._build_warm_start(items, pieces, 200.0, "bi", 90.0)


def _capture_instance(monkeypatch, pieces, **kwargs):
    captured = {}
    items = _group_to_items(pieces, "bi", 90.0)
    w, h = items[0].emitted.bounds[2], items[0].emitted.bounds[3]
    # one valid placed_item per copy, laid side-by-side along jagua-x (no overlap)
    placed, k = [], 0
    for it in items:
        for _ in it.piece_ids:
            placed.append({"item_id": it.index,
                           "transformation": {"rotation": 0.0, "translation": [k * w, 0.0]}})
            k += 1
    canned = {"solution": {"strip_width": k * w, "layout": {"placed_items": placed}}}

    def fake_run(instance, budget_s, seed):
        captured["instance"] = instance
        return canned
    monkeypatch.setattr(sep, "_run_sparrow", fake_run)
    sep.run_separation_layout(pieces, h, "bi", 90.0, budget_s=5, seed=42, **kwargs)
    return captured["instance"]


def test_run_separation_layout_warm_start_injects_solution(monkeypatch):
    # warm_start=True must attach a "solution" key (ExtSPOutput) to the instance sparrow sees.
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0)]
    instance = _capture_instance(monkeypatch, pieces, warm_start=True)
    assert "solution" in instance
    assert len(instance["solution"]["layout"]["placed_items"]) == len(pieces)


def test_run_separation_layout_no_warm_start_omits_solution(monkeypatch):
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0)]
    instance = _capture_instance(monkeypatch, pieces, warm_start=False)
    assert "solution" not in instance


def test_run_separation_layout_warm_start_failure_falls_back(monkeypatch):
    # If the Fast layout fails, warm_start=True still runs sparrow cold (no "solution").
    monkeypatch.setattr(sep, "auto_layout_polygon", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0)]
    instance = _capture_instance(monkeypatch, pieces, warm_start=True)
    assert "solution" not in instance
