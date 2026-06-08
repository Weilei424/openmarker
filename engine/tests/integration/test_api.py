# Integration tests for the engine API endpoints.
# Uses httpx.AsyncClient with the ASGI app directly — no running server needed.

import sys
import os
import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.main import app
from helpers import make_dxf_bytes


@pytest.mark.asyncio
async def test_ping_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ping")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_import_dxf_valid_file():
    dxf_bytes = make_dxf_bytes({
        "FRONT": [(0, 0), (100, 0), (100, 80), (0, 80)],
        "BACK": [(0, 0), (90, 0), (90, 70), (0, 70)],
    })
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/import-dxf",
            files={"file": ("pattern.dxf", dxf_bytes, "application/octet-stream")},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["piece_count"] >= 1
    assert len(body["pieces"]) == body["piece_count"]
    piece = body["pieces"][0]
    assert "name" in piece
    assert "polygon" in piece
    assert "bbox" in piece
    assert piece["bbox"]["width"] > 0
    assert piece["bbox"]["height"] > 0


@pytest.mark.asyncio
async def test_import_dxf_wrong_extension():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/import-dxf",
            files={"file": ("pattern.txt", b"some text content", "text/plain")},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_import_dxf_corrupt_content():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/import-dxf",
            files={"file": ("pattern.dxf", b"this is garbage not dxf", "application/octet-stream")},
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Ultra quality tier — separation engine routing
# ---------------------------------------------------------------------------

def _one_piece_body(quality: str) -> dict:
    """Build a minimal /auto-layout request body with a single piece.

    Uses a unique filename per call (includes quality + uuid nonce) so the
    layout cache never short-circuits the stub engine.
    """
    import uuid
    nonce = uuid.uuid4().hex[:8]
    return {
        "filename": f"ultra_test_{quality}_{nonce}.dxf",
        "fabric_width_mm": 1500.0,
        "grain_mode": "single",
        "quality": quality,
        "copies": 1,
        "pieces": [
            {
                "id": "piece_0",
                "name": "FRONT",
                "polygon": [[0.0, 0.0], [100.0, 0.0], [100.0, 80.0], [0.0, 80.0]],
                "area": 8000.0,
                "bbox": {
                    "min_x": 0.0,
                    "min_y": 0.0,
                    "max_x": 100.0,
                    "max_y": 80.0,
                    "width": 100.0,
                    "height": 80.0,
                },
                "is_valid": True,
                "validation_notes": [],
                "grainline_direction_deg": None,
            }
        ],
    }


@pytest.mark.asyncio
async def test_ultra_is_a_valid_quality(monkeypatch):
    """quality=ultra routes to run_separation_layout; stub avoids needing the binary."""
    from core.layout.heuristic import Placement
    import api.main as main

    def _stub(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, budget_s, seed=42):
        return [Placement(pieces[0].id, 10.0, 10.0, 0.0)], 123.0, 45.6

    monkeypatch.setattr(main, "run_separation_layout", _stub)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/auto-layout", json=_one_piece_body(quality="ultra"))

    assert resp.status_code == 200
    assert resp.json()["marker_length_mm"] == 123.0


@pytest.mark.asyncio
async def test_ultra_invalid_output_returns_400(monkeypatch):
    """ValueError from run_separation_layout surfaces as HTTP 400 with 'invalid' in detail."""
    import api.main as main

    def _bad(*a, **k):
        raise ValueError("separation layout invalid: off-grain")

    monkeypatch.setattr(main, "run_separation_layout", _bad)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/auto-layout", json=_one_piece_body(quality="ultra"))

    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"]
