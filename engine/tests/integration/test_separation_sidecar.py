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


def _rect(piece_id, w, h, grainline=90.0):
    return Piece(id=piece_id, name=piece_id, polygon=[(0, 0), (w, 0), (w, h), (0, h)],
                 area=w * h, bbox=BoundingBox(0, 0, w, h, w, h), is_valid=True,
                 grainline_direction_deg=grainline)


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
