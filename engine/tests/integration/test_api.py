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
