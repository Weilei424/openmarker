import sys
import os
import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.main import app
from core.layout.cache import reset_cache


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_cache()
    yield
    reset_cache()


def _square_piece(piece_id: str = "p0", size: float = 100.0) -> dict:
    return {
        "id": piece_id,
        "name": piece_id,
        "polygon": [[0, 0], [size, 0], [size, size], [0, size]],
        "area": size * size,
        "bbox": {
            "min_x": 0, "min_y": 0, "max_x": size, "max_y": size,
            "width": size, "height": size,
        },
        "is_valid": True,
        "validation_notes": [],
        "grainline_direction_deg": None,
    }


@pytest.mark.asyncio
async def test_auto_layout_returns_cache_metadata():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/auto-layout", json={
            "filename": "sample.dxf",
            "pieces": [_square_piece()],
            "fabric_width_mm": 1500,
            "grain_mode": "single",
            "grain_direction_deg": 90,
        })
    assert res.status_code == 200
    body = res.json()
    assert "id" in body
    assert "timestamp" in body
    assert "duration_ms" in body
    assert body["marker_length_mm"] > 0
    assert isinstance(body["id"], str) and len(body["id"]) > 0
