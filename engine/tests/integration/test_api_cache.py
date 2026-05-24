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


@pytest.mark.asyncio
async def test_list_layouts_returns_summary_newest_first():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = []
        for i in range(3):
            res = await client.post("/auto-layout", json={
                "filename": "sample.dxf",
                "pieces": [_square_piece()],
                "fabric_width_mm": 1500 + i,           # distinct per run (dedup)
                "grain_mode": "single",
                "grain_direction_deg": 90,
            })
            ids.append(res.json()["id"])

        listing = await client.get("/layouts")

    assert listing.status_code == 200
    body = listing.json()
    assert [e["id"] for e in body] == list(reversed(ids))
    assert all("placements" not in e for e in body)
    for e in body:
        assert {"id", "filename", "timestamp", "grain_mode", "copies",
                "fabric_width_mm", "marker_length_mm", "utilization_pct",
                "duration_ms"}.issubset(e.keys())


@pytest.mark.asyncio
async def test_get_layout_returns_full_entry():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        post = await client.post("/auto-layout", json={
            "filename": "sample.dxf",
            "pieces": [_square_piece()],
            "fabric_width_mm": 1500,
            "grain_mode": "single",
            "grain_direction_deg": 90,
        })
        layout_id = post.json()["id"]

        res = await client.get(f"/layouts/{layout_id}")

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == layout_id
    assert "placements" in body
    assert len(body["placements"]) == 1
    assert body["placements"][0]["piece_id"] == "p0"


@pytest.mark.asyncio
async def test_get_layout_missing_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/layouts/nonexistent")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_layout_removes_entry():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        post = await client.post("/auto-layout", json={
            "filename": "sample.dxf",
            "pieces": [_square_piece()],
            "fabric_width_mm": 1500,
            "grain_mode": "single",
            "grain_direction_deg": 90,
        })
        layout_id = post.json()["id"]

        del_res = await client.delete(f"/layouts/{layout_id}")
        get_res = await client.get(f"/layouts/{layout_id}")

    assert del_res.status_code == 204
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_cors_allows_delete_preflight():
    """Browser preflight (OPTIONS) for DELETE must be allowed by CORS middleware.
    Regression: previously CORS only listed GET/POST, so the × tab-close button
    silently failed in real browsers (preflight rejected → DELETE never sent)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.options(
            "/layouts/some-id",
            headers={
                "Origin": "http://localhost:1420",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert res.status_code == 200, res.text
    allow_methods = res.headers.get("access-control-allow-methods", "")
    assert "DELETE" in allow_methods.upper(), f"DELETE not in: {allow_methods!r}"


@pytest.mark.asyncio
async def test_delete_layout_missing_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.delete("/layouts/nonexistent")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_fifo_eviction_after_6_runs():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = []
        for i in range(6):
            res = await client.post("/auto-layout", json={
                "filename": "sample.dxf",
                "pieces": [_square_piece()],
                "fabric_width_mm": 1500 + i,           # distinct per run
                "grain_mode": "single",
                "grain_direction_deg": 90,
            })
            ids.append(res.json()["id"])

        listing = await client.get("/layouts")
        oldest_get = await client.get(f"/layouts/{ids[0]}")

    listed_ids = {e["id"] for e in listing.json()}
    assert len(listed_ids) == 5
    assert ids[0] not in listed_ids
    assert oldest_get.status_code == 404


@pytest.mark.asyncio
async def test_auto_layout_dedup_returns_existing_entry():
    body = {
        "filename": "sample.dxf",
        "pieces": [_square_piece()],
        "fabric_width_mm": 1500,
        "grain_mode": "single",
        "grain_direction_deg": 90,
        "copies": 1,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/auto-layout", json=body)
        second = await client.post("/auto-layout", json=body)
        listing = await client.get("/layouts")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    # Same id from both runs AND only one entry in the cache.
    assert len(listing.json()) == 1


@pytest.mark.asyncio
async def test_auto_layout_different_settings_creates_new_entry():
    base = {
        "filename": "sample.dxf",
        "pieces": [_square_piece()],
        "fabric_width_mm": 1500,
        "grain_mode": "single",
        "grain_direction_deg": 90,
        "copies": 1,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post("/auto-layout", json=base)
        r2 = await client.post("/auto-layout", json={**base, "copies": 2})
        r3 = await client.post("/auto-layout", json={**base, "fabric_width_mm": 1600})
        r4 = await client.post("/auto-layout", json={**base, "grain_mode": "bi"})

    ids = {r1.json()["id"], r2.json()["id"], r3.json()["id"], r4.json()["id"]}
    assert len(ids) == 4  # all distinct


@pytest.mark.asyncio
async def test_auto_layout_rejects_grain_mode_none():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/auto-layout", json={
            "filename": "sample.dxf",
            "pieces": [_square_piece()],
            "fabric_width_mm": 1500,
            "grain_mode": "none",
            "grain_direction_deg": 90,
        })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_delete_all_layouts_clears_cache():
    body = {
        "filename": "sample.dxf",
        "pieces": [_square_piece()],
        "fabric_width_mm": 1500,
        "grain_mode": "single",
        "grain_direction_deg": 90,
        "copies": 1,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Seed the cache with 3 distinct entries.
        for i in range(3):
            await client.post("/auto-layout", json={**body, "fabric_width_mm": 1500 + i})
        before = await client.get("/layouts")
        clear = await client.delete("/layouts")
        after = await client.get("/layouts")

    assert len(before.json()) == 3
    assert clear.status_code == 204
    assert after.json() == []


@pytest.mark.asyncio
async def test_delete_all_layouts_when_empty_returns_204():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.delete("/layouts")
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_auto_layout_rejects_missing_filename():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/auto-layout", json={
            "pieces": [_square_piece()],
            "fabric_width_mm": 1500,
            "grain_mode": "single",
            "grain_direction_deg": 90,
        })
    assert res.status_code == 422
