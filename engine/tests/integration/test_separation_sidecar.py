"""Real-sparrow integration. Skips gracefully if the binary is unavailable."""
import threading
import time

import pytest

from core.models.piece import Piece, BoundingBox
from core.layout import separation as sep
from core.layout.cancellation import CancellationError, request_cancellation, reset_cancellation


def _has_binary() -> bool:
    try:
        sep._resolve_sparrow_path()
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _has_binary(), reason="sparrow binary not available")

FABRIC_WIDTH = 300.0


def _rect(piece_id, w, h, grainline=90.0):
    return Piece(id=piece_id, name=piece_id, polygon=[(0, 0), (w, 0), (w, h), (0, h)],
                 area=w * h, bbox=BoundingBox(0, 0, w, h, w, h), is_valid=True,
                 grainline_direction_deg=grainline)


def _sidecar_pieces():
    """The 3-piece instance shared by the real-sparrow end-to-end tests below."""
    return [_rect("p__c0", 80, 40), _rect("p__c1", 80, 40), _rect("q__c0", 60, 30)]


def test_run_sparrow_tiny_instance_produces_output():
    reset_cancellation()
    items = sep._group_to_items([_rect("p__c0", 80, 40), _rect("p__c1", 80, 40),
                                 _rect("q__c0", 60, 30)], "bi", 90.0)
    inst = sep._instance_json(items, strip_height=300.0)
    out = sep._run_sparrow(inst, budget_s=5, seed=42)
    assert out["solution"]["layout"]["placed_items"]


def test_cancellation_kills_sparrow():
    reset_cancellation()
    items = sep._group_to_items([_rect("p__c0", 80, 40)] + [_rect(f"p__c{i}", 80, 40) for i in range(1, 30)],
                                "bi", 90.0)
    inst = sep._instance_json(items, strip_height=300.0)
    result = {}

    def _run():
        try:
            sep._run_sparrow(inst, budget_s=600, seed=42)
        except CancellationError:
            result["cancelled"] = True
        except Exception as e:  # noqa: BLE001
            result["error"] = repr(e)

    th = threading.Thread(target=_run)
    th.start()
    time.sleep(1.0)
    request_cancellation()
    sep.kill_current_sparrow()
    th.join(timeout=15)
    reset_cancellation()
    assert result.get("cancelled") is True


def test_run_separation_layout_end_to_end():
    reset_cancellation()
    pieces = _sidecar_pieces()
    placements, marker_length, utilization = sep.run_separation_layout(
        pieces, fabric_width_mm=FABRIC_WIDTH, grain_mode="bi", fabric_grain_deg=90.0,
        budget_s=5, seed=42)
    assert len(placements) == len(pieces)
    assert marker_length > 0 and 0 < utilization <= 100
    assert all(round(pl.rotation_deg) % 180 == 0 for pl in placements)


def test_sequential_best_of_two_end_to_end():
    """Two members MUST run back-to-back (sequential wall ~= 2x budget, not ~= budget)
    and leave a full-completion final snapshot."""
    import time as _t
    import core.layout.progress as prog
    reset_cancellation()
    pieces = _sidecar_pieces()   # reuse/extract the same pieces the existing e2e test builds
    prog.clear_progress()
    t0 = _t.perf_counter()
    placements, marker, util = sep.run_separation_layout(
        pieces, FABRIC_WIDTH, "bi", 90.0, budget_s=8, seed=42, n_seeds=2, warm_start=False)
    wall = _t.perf_counter() - t0
    assert wall >= 14.0, f"members overlapped? wall={wall:.1f}s for 2 x 8s"
    assert marker > 0 and len(placements) == len(pieces)
    snap = prog.get_progress()
    assert snap["members_completed"] == 2 and snap["stopped_early"] is False
