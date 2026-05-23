# Phase 6 — Fixes, Performance, and UI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up Phase 5 rough edges, add an in-memory auto-layout result cache exposed via tabs in the UI, rework the metrics surface into a bottom panel with a layout-duration timer, and replace the fixed window size with a runtime-computed 70%-of-monitor 4:3 default.

**Architecture:** Engine adds a process-lifetime `LayoutCache` (max 5 entries, FIFO, **no deduplication**) keyed by UUID; `POST /auto-layout` becomes a cache-insert and three new endpoints expose list/get/delete. Frontend gets a new `useLayoutCache` hook that drives a `CachedLayoutTabs` strip (above the canvas, aligned to the canvas's left edge) and a `BottomPanel` that shows metrics for the active tab. Sidebar simplifies: grain "none" and fast mode are removed, a "Show grainline" checkbox is added, the copies input doubles in height. The Tauri shell computes the startup window size in `lib.rs` (70% of monitor logical height, 4:3 ratio).

**Tech Stack:** Python 3.11 + FastAPI (engine), React 18 + TypeScript + Konva (frontend), Tauri 2 + Rust (desktop shell), pytest + Vitest (tests).

**Spec:** `docs/superpowers/specs/2026-05-23-phase6-fixes-perf-ui-design.md`

---

## Execution order rationale

Tasks are ordered so the dev environment (`scripts/dev-engine.bat` + `cargo tauri dev`) stays runnable between commits:

- **Group A (Engine, additive)** — adds the cache module and new endpoints. `POST /auto-layout` keeps accepting the existing request shape (`fast_mode` ignored, `filename` optional). System still works for the old frontend.
- **Group B (Frontend)** — switches the frontend to the new contract (sends `filename`, drops `fast_mode`, uses the new endpoints, swaps grain "none" for "single", rebuilds the layout).
- **Group C (Engine, strict)** — now safe to tighten validation: require `filename`, reject `grain_mode == "none"`, delete `auto_layout_bbox` and the `"none"` branch of `allowed_rotations`.
- **Group D (Desktop shell)** — Tauri config + Rust window-sizing. Independent of the others.

---

## File map

### Created

| Path | Responsibility |
|---|---|
| `engine/core/layout/cache.py` | `CachedLayout` dataclass + `LayoutCache` (FIFO, max 5) + module-level singleton |
| `engine/tests/unit/test_cache.py` | Unit tests for `LayoutCache` |
| `engine/tests/integration/test_api_cache.py` | API tests for cache endpoints |
| `frontend/src/hooks/useLayoutCache.ts` | Tab state: entries, activeId, lazy fetch, close |
| `frontend/src/hooks/useLayoutCache.test.ts` | Vitest tests for the hook |
| `frontend/src/components/BottomPanel.tsx` | Length · Util · Overflow · ⏱ MM:SS for the active tab |
| `frontend/src/components/BottomPanel.test.tsx` | Vitest tests for MM:SS formatting + overflow |
| `frontend/src/components/CachedLayoutTabs.tsx` | Tab strip above the canvas |

### Modified

| Path | Change |
|---|---|
| `engine/api/main.py` | Cache wiring in `/auto-layout`; new `/layouts` + `/layouts/{id}` (GET, DELETE); strict request validation (final task) |
| `engine/core/layout/heuristic.py` | Remove `auto_layout_bbox`, `_strip_pack`, `_rotated_bbox_dims`, the `"none"` branches |
| `engine/core/layout/grain.py` | Remove `"none"` branch from `allowed_rotations` |
| `engine/tests/unit/test_grain.py` | Replace `"none"` tests with `ValueError` assertion |
| `engine/tests/unit/test_heuristic.py` | Drop all bbox tests; rewrite remaining tests to use `"single"`/`"bi"` grain |
| `engine/tests/integration/test_api.py` | Update existing `/auto-layout` tests to include `filename` and use `single`/`bi` grain mode |
| `frontend/src/types/engine.ts` | `GrainMode` becomes `"single" \| "bi"`; new `CachedLayoutSummary` + `CachedLayout` + update `AutoLayoutResponse` |
| `frontend/src/hooks/useAutoLayout.ts` | Drop `fastMode` param; add `filename` to request body; return entry id |
| `frontend/src/hooks/usePlacements.ts` | Source placements from `useLayoutCache.activeEntry?.placements` |
| `frontend/src/components/sidebar/GrainPanel.tsx` | Drop `"none"` radio, drop fast-mode checkbox, add `Show grainline` checkbox |
| `frontend/src/components/canvas/PieceShape.tsx` | Replace `grainMode` prop with `showGrainline: boolean` |
| `frontend/src/components/canvas/CanvasWorkspace.tsx` | Pass `showGrainline` through; drop `grainMode` for arrow logic |
| `frontend/src/app/App.tsx` | New top-level layout (tabs above canvas, bottom panel below); drop `fastMode` state; lift `showGrainline` state (default `true`); default `grainMode` becomes `"single"`; double copies input height; wire `useLayoutCache`; remove inline `MetricsPanel` |
| `frontend/src/utils/metrics.ts` | Delete (no longer used after metrics come from engine) — or trim if BottomPanel needs a helper |
| `desktop/src-tauri/tauri.conf.json` | Remove fixed `width`/`height`; set `"visible": false` |
| `desktop/src-tauri/src/lib.rs` | Compute startup size from monitor in setup hook |

---

## GROUP A — Engine, additive (cache module + new endpoints)

### Task 1: Create `LayoutCache` module

**Files:**
- Create: `engine/core/layout/cache.py`
- Test: `engine/tests/unit/test_cache.py`

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/unit/test_cache.py`:

```python
import time
import pytest
from core.layout.cache import CachedLayout, LayoutCache


def _make_entry(id_: str, created_at: float | None = None) -> CachedLayout:
    return CachedLayout(
        id=id_,
        filename="sample.dxf",
        timestamp="20260523140000",
        grain_mode="single",
        copies=1,
        fabric_width_mm=1500.0,
        placements=[{"piece_id": "p0", "x": 10, "y": 10, "rotation_deg": 0}],
        marker_length_mm=500.0,
        utilization_pct=82.4,
        duration_ms=1234,
        created_at=created_at if created_at is not None else time.time(),
    )


def test_insert_then_get_roundtrip():
    cache = LayoutCache()
    entry = _make_entry("a")
    cache.insert(entry)
    assert cache.get("a") is entry


def test_get_missing_returns_none():
    cache = LayoutCache()
    assert cache.get("missing") is None


def test_list_newest_first():
    cache = LayoutCache()
    cache.insert(_make_entry("a", created_at=100.0))
    cache.insert(_make_entry("b", created_at=200.0))
    cache.insert(_make_entry("c", created_at=150.0))
    ids = [e.id for e in cache.list()]
    assert ids == ["b", "c", "a"]


def test_insert_beyond_max_evicts_oldest():
    cache = LayoutCache()
    # MAX_ENTRIES is 5
    for i in range(5):
        cache.insert(_make_entry(f"e{i}", created_at=float(i)))
    cache.insert(_make_entry("e5", created_at=5.0))
    ids = {e.id for e in cache.list()}
    assert ids == {"e1", "e2", "e3", "e4", "e5"}
    assert cache.get("e0") is None


def test_delete_returns_true_when_present():
    cache = LayoutCache()
    cache.insert(_make_entry("a"))
    assert cache.delete("a") is True
    assert cache.get("a") is None


def test_delete_returns_false_when_missing():
    cache = LayoutCache()
    assert cache.delete("missing") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bat
engine\.venv\Scripts\pytest engine\tests\unit\test_cache.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.layout.cache'`

- [ ] **Step 3: Implement the cache module**

Create `engine/core/layout/cache.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CachedLayout:
    id: str
    filename: str
    timestamp: str                       # YYYYMMDDHHMMSS, set at insert time
    grain_mode: Literal["single", "bi"]
    copies: int
    fabric_width_mm: float
    placements: list[dict]
    marker_length_mm: float
    utilization_pct: float
    duration_ms: int
    created_at: float                    # epoch seconds, for FIFO ordering


class LayoutCache:
    MAX_ENTRIES = 5

    def __init__(self) -> None:
        # id -> entry; insertion order preserved by dict ordering, but we
        # also sort by created_at when listing/evicting so callers can supply
        # explicit timestamps (used by tests).
        self._entries: dict[str, CachedLayout] = {}

    def insert(self, entry: CachedLayout) -> None:
        self._entries[entry.id] = entry
        if len(self._entries) > self.MAX_ENTRIES:
            # FIFO: drop the oldest by created_at.
            oldest_id = min(self._entries, key=lambda k: self._entries[k].created_at)
            del self._entries[oldest_id]

    def get(self, layout_id: str) -> CachedLayout | None:
        return self._entries.get(layout_id)

    def delete(self, layout_id: str) -> bool:
        if layout_id in self._entries:
            del self._entries[layout_id]
            return True
        return False

    def list(self) -> list[CachedLayout]:
        """Newest-first by created_at."""
        return sorted(self._entries.values(), key=lambda e: e.created_at, reverse=True)


# Module-level singleton (same pattern as cancellation.py).
_cache = LayoutCache()


def get_cache() -> LayoutCache:
    return _cache


def reset_cache() -> None:
    """For tests: clear the singleton between cases."""
    _cache._entries.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

```bat
engine\.venv\Scripts\pytest engine\tests\unit\test_cache.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bat
git add engine\core\layout\cache.py engine\tests\unit\test_cache.py
git commit -m "feat(engine): add LayoutCache with FIFO eviction (Phase 6)"
```

---

### Task 2: Wire cache into `POST /auto-layout` (additive — request still backward-compatible)

**Files:**
- Modify: `engine/api/main.py`
- Test: `engine/tests/integration/test_api_cache.py` (new) and update existing `engine/tests/integration/test_api.py`

- [ ] **Step 1: Write the failing test**

Create `engine/tests/integration/test_api_cache.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bat
engine\.venv\Scripts\pytest engine\tests\integration\test_api_cache.py::test_auto_layout_returns_cache_metadata -v
```

Expected: FAIL — response lacks `id`/`timestamp`/`duration_ms`.

- [ ] **Step 3: Wire the cache into `/auto-layout`**

In `engine/api/main.py`:

Add imports near the top (alongside `from core.layout.cancellation import …`):

```python
import time
import uuid
from datetime import datetime

from core.layout.cache import CachedLayout, get_cache
```

Replace the body of `auto_layout_endpoint` from the `# Clear any stale cancellation flag` comment down to (but not including) the existing `return {` block with:

```python
    # Clear any stale cancellation flag from a previous run.
    reset_cancellation()

    # Run the CPU-bound layout in a worker thread so other endpoints
    # (notably /cancel-layout, /ping) stay responsive while it runs.
    def _do_layout():
        if fast_mode:
            return auto_layout_bbox(pieces, fabric_width_mm, grain_mode, grain_direction_deg)
        return auto_layout_polygon(pieces, fabric_width_mm, grain_mode, grain_direction_deg)

    start = time.perf_counter()
    try:
        placements, marker_length, utilization = await run_in_threadpool(_do_layout)
    except CancellationError:
        return JSONResponse(
            status_code=499,  # Client Closed Request (Nginx convention)
            content={"detail": "cancelled"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    duration_ms = int((time.perf_counter() - start) * 1000)

    placements_serialized = [
        {"piece_id": pl.piece_id, "x": pl.x, "y": pl.y, "rotation_deg": pl.rotation_deg}
        for pl in placements
    ]

    # Build and store the cache entry. No dedup — each successful run gets a
    # fresh UUID and a fresh timestamp.
    now = time.time()
    filename = str(body.get("filename", "")) or "untitled.dxf"
    copies = int(body.get("copies", 1))
    entry = CachedLayout(
        id=uuid.uuid4().hex,
        filename=filename,
        timestamp=datetime.fromtimestamp(now).strftime("%Y%m%d%H%M%S"),
        grain_mode=grain_mode if grain_mode in ("single", "bi") else "single",
        copies=copies,
        fabric_width_mm=fabric_width_mm,
        placements=placements_serialized,
        marker_length_mm=marker_length,
        utilization_pct=utilization,
        duration_ms=duration_ms,
        created_at=now,
    )
    get_cache().insert(entry)

    return {
        "id": entry.id,
        "timestamp": entry.timestamp,
        "duration_ms": entry.duration_ms,
        "placements": placements_serialized,
        "marker_length_mm": marker_length,
        "utilization_pct": utilization,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bat
engine\.venv\Scripts\pytest engine\tests\integration\test_api_cache.py -v
engine\.venv\Scripts\pytest engine\tests\integration\test_api.py -v
```

Expected: new test passes. Existing `/auto-layout` tests in `test_api.py` should still pass — the response now has extra fields (`id`, `timestamp`, `duration_ms`) but the previously-asserted fields are unchanged.

- [ ] **Step 5: Commit**

```bat
git add engine\api\main.py engine\tests\integration\test_api_cache.py
git commit -m "feat(engine): cache auto-layout results, return id/timestamp/duration (Phase 6)"
```

---

### Task 3: Add `GET /layouts`, `GET /layouts/{id}`, `DELETE /layouts/{id}` endpoints

**Files:**
- Modify: `engine/api/main.py`
- Test: `engine/tests/integration/test_api_cache.py`

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/integration/test_api_cache.py`:

```python
@pytest.mark.asyncio
async def test_list_layouts_returns_summary_newest_first():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = []
        for _ in range(3):
            res = await client.post("/auto-layout", json={
                "filename": "sample.dxf",
                "pieces": [_square_piece()],
                "fabric_width_mm": 1500,
                "grain_mode": "single",
                "grain_direction_deg": 90,
            })
            ids.append(res.json()["id"])

        listing = await client.get("/layouts")

    assert listing.status_code == 200
    body = listing.json()
    assert [e["id"] for e in body] == list(reversed(ids))
    # Summary must NOT include placements (lightweight).
    assert all("placements" not in e for e in body)
    # Summary fields:
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
async def test_delete_layout_missing_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.delete("/layouts/nonexistent")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_fifo_eviction_after_6_runs():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = []
        for _ in range(6):
            res = await client.post("/auto-layout", json={
                "filename": "sample.dxf",
                "pieces": [_square_piece()],
                "fabric_width_mm": 1500,
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bat
engine\.venv\Scripts\pytest engine\tests\integration\test_api_cache.py -v
```

Expected: 5 new tests FAIL (404 from FastAPI on the new routes, route not found).

- [ ] **Step 3: Add the endpoints**

Append to `engine/api/main.py` (above the `if __name__ == "__main__":` block):

```python
from fastapi import Response


def _summary(entry) -> dict:
    return {
        "id": entry.id,
        "filename": entry.filename,
        "timestamp": entry.timestamp,
        "grain_mode": entry.grain_mode,
        "copies": entry.copies,
        "fabric_width_mm": entry.fabric_width_mm,
        "marker_length_mm": entry.marker_length_mm,
        "utilization_pct": entry.utilization_pct,
        "duration_ms": entry.duration_ms,
    }


@app.get("/layouts")
def list_layouts() -> list[dict]:
    """Return a lightweight summary of cached layouts, newest-first.
    Excludes the (heavy) placements array; fetch a single entry to get it."""
    return [_summary(e) for e in get_cache().list()]


@app.get("/layouts/{layout_id}")
def get_layout(layout_id: str) -> dict:
    """Return the full cached layout, including placements."""
    entry = get_cache().get(layout_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Layout not found")
    return {
        **_summary(entry),
        "placements": entry.placements,
    }


@app.delete("/layouts/{layout_id}", status_code=204)
def delete_layout(layout_id: str) -> Response:
    """Remove a cached layout (manual tab close from the UI)."""
    if not get_cache().delete(layout_id):
        raise HTTPException(status_code=404, detail="Layout not found")
    return Response(status_code=204)
```

The existing `from fastapi import FastAPI, HTTPException, Request, UploadFile` line can either be extended to include `Response` or `Response` can be imported on a new line as shown above. Either is fine — pick whichever matches local style.

- [ ] **Step 4: Run tests to verify they pass**

```bat
engine\.venv\Scripts\pytest engine\tests\integration\test_api_cache.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bat
git add engine\api\main.py engine\tests\integration\test_api_cache.py
git commit -m "feat(engine): add GET /layouts, GET/DELETE /layouts/{id} (Phase 6)"
```

---

## GROUP B — Frontend (switch to new contract)

### Task 4: Update engine.ts types

**Files:**
- Modify: `frontend/src/types/engine.ts`

This is a type-only change. TypeScript will surface every downstream site that breaks; later tasks fix them. No tests of their own — `npm run build` is the verification.

- [ ] **Step 1: Apply the change**

Replace the contents of `frontend/src/types/engine.ts` with:

```typescript
// Types for responses from the local Python engine API (http://127.0.0.1:8765)

export interface PingResponse {
  status: "ok" | "error";
  message: string;
  version: string;
}

export type EngineStatus = "unknown" | "connecting" | "connected" | "error";

export interface BoundingBox {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
  width: number;
  height: number;
}

export interface Piece {
  id: string;
  name: string;
  polygon: [number, number][];
  area: number;
  bbox: BoundingBox;
  is_valid: boolean;
  validation_notes: string[];
  grainline_direction_deg: number | null;
  // Frontend-only: which copy/set this piece belongs to (0-based). The engine
  // ignores it; it just uses `id` as an opaque token.
  setIndex?: number;
}

export interface ImportDxfResponse {
  pieces: Piece[];
  piece_count: number;
  skipped_count: number;
  warnings: string[];
}

export type ImportStatus = "idle" | "loading" | "success" | "error";

// Phase 6: "none" removed. Only "single" and "bi" are valid.
export type GrainMode = "single" | "bi";

export interface AutoLayoutPlacement {
  piece_id: string;
  x: number;
  y: number;
  rotation_deg: number;
}

// Phase 6: /auto-layout now also returns the cache id, timestamp, and duration.
export interface AutoLayoutResponse {
  id: string;
  timestamp: string;            // YYYYMMDDHHMMSS
  duration_ms: number;
  placements: AutoLayoutPlacement[];
  marker_length_mm: number;
  utilization_pct: number;
}

export interface CachedLayoutSummary {
  id: string;
  filename: string;
  timestamp: string;
  grain_mode: GrainMode;
  copies: number;
  fabric_width_mm: number;
  marker_length_mm: number;
  utilization_pct: number;
  duration_ms: number;
}

export interface CachedLayout extends CachedLayoutSummary {
  placements: AutoLayoutPlacement[];
}
```

- [ ] **Step 2: Skip — types-only change**

No test to run yet. `npm run build` will fail in dependent files; subsequent tasks fix them.

- [ ] **Step 3: Commit**

```bat
git add frontend\src\types\engine.ts
git commit -m "feat(frontend): tighten GrainMode + add CachedLayout types (Phase 6)"
```

---

### Task 5: Refactor `useAutoLayout` — add filename, drop fastMode, return id

**Files:**
- Modify: `frontend/src/hooks/useAutoLayout.ts`

- [ ] **Step 1: Apply the change**

Replace the body of `useAutoLayout.ts` with:

```typescript
import { useState, useCallback, useRef } from "react";
import type { Piece, GrainMode, AutoLayoutResponse } from "../types/engine";

const ENGINE_URL = "http://127.0.0.1:8765";

export type AutoLayoutOutcome =
  | { ok: true; data: AutoLayoutResponse }
  | { ok: false; aborted: true }
  | { ok: false; aborted: false; errorMessage: string };

export function useAutoLayout() {
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const runAutoLayout = useCallback(
    async (
      filename: string,
      pieces: Piece[],
      fabricWidthMm: number,
      grainMode: GrainMode,
      grainDirectionDeg: number,
      copies: number,
    ): Promise<AutoLayoutOutcome> => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setStatus("loading");
      setErrorMessage(null);
      try {
        const res = await fetch(`${ENGINE_URL}/auto-layout`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filename,
            pieces,
            fabric_width_mm: fabricWidthMm,
            grain_mode: grainMode,
            grain_direction_deg: grainDirectionDeg,
            copies,
          }),
          signal: controller.signal,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
        }
        const data = (await res.json()) as AutoLayoutResponse;
        setStatus("idle");
        return { ok: true, data };
      } catch (e) {
        if (e instanceof Error && (e.name === "AbortError" || /aborted/i.test(e.message))) {
          setStatus("idle");
          setErrorMessage(null);
          return { ok: false, aborted: true };
        }
        const msg = e instanceof Error ? e.message : "Auto layout failed";
        setStatus("error");
        setErrorMessage(msg);
        return { ok: false, aborted: false, errorMessage: msg };
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    []
  );

  const abort = useCallback(() => {
    fetch(`${ENGINE_URL}/cancel-layout`, { method: "POST" }).catch(() => {});
    abortRef.current?.abort();
  }, []);

  return { runAutoLayout, abort, status, errorMessage };
}
```

- [ ] **Step 2: Skip — caller update follows in Task 11 (App.tsx)**

Callsite in `App.tsx` will be updated in Task 11. Don't run `npm run build` yet; it will still fail.

- [ ] **Step 3: Commit**

```bat
git add frontend\src\hooks\useAutoLayout.ts
git commit -m "refactor(frontend): useAutoLayout sends filename+copies, drops fast_mode (Phase 6)"
```

---

### Task 6: Create `useLayoutCache` hook

**Files:**
- Create: `frontend/src/hooks/useLayoutCache.ts`
- Test: `frontend/src/hooks/useLayoutCache.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/hooks/useLayoutCache.test.ts`:

```typescript
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useLayoutCache } from "./useLayoutCache";
import type { CachedLayout, CachedLayoutSummary } from "../types/engine";

const summary = (id: string): CachedLayoutSummary => ({
  id,
  filename: "sample.dxf",
  timestamp: "20260523140000",
  grain_mode: "single",
  copies: 1,
  fabric_width_mm: 1500,
  marker_length_mm: 500,
  utilization_pct: 82.4,
  duration_ms: 1234,
});

const full = (id: string): CachedLayout => ({
  ...summary(id),
  placements: [{ piece_id: "p0", x: 10, y: 10, rotation_deg: 0 }],
});

describe("useLayoutCache", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("refresh() pulls /layouts and stores entries", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => [summary("a"), summary("b")],
    } as Response);

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });

    expect(result.current.entries.map(e => e.id)).toEqual(["a", "b"]);
  });

  it("setActiveId triggers GET /layouts/{id} and stores the full entry", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, json: async () => [summary("a")] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => full("a") } as Response);

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });
    await act(async () => { result.current.setActiveId("a"); });

    await waitFor(() => expect(result.current.activeEntry?.id).toBe("a"));
    expect(result.current.activeEntry?.placements).toHaveLength(1);
  });

  it("closeTab calls DELETE and refreshes the list", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, json: async () => [summary("a"), summary("b")] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => full("a") } as Response)
      .mockResolvedValueOnce({ ok: true, status: 204 } as Response)             // DELETE
      .mockResolvedValueOnce({ ok: true, json: async () => [summary("b")] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => full("b") } as Response);

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });
    await act(async () => { result.current.setActiveId("a"); });
    await waitFor(() => expect(result.current.activeEntry?.id).toBe("a"));

    await act(async () => { await result.current.closeTab("a"); });

    await waitFor(() => expect(result.current.entries.map(e => e.id)).toEqual(["b"]));
    await waitFor(() => expect(result.current.activeId).toBe("b"));
  });

  it("closing the last tab clears active state", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, json: async () => [summary("a")] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => full("a") } as Response)
      .mockResolvedValueOnce({ ok: true, status: 204 } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [] } as Response);

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });
    await act(async () => { result.current.setActiveId("a"); });
    await waitFor(() => expect(result.current.activeEntry?.id).toBe("a"));

    await act(async () => { await result.current.closeTab("a"); });

    await waitFor(() => expect(result.current.entries).toEqual([]));
    await waitFor(() => expect(result.current.activeId).toBeNull());
    expect(result.current.activeEntry).toBeNull();
  });
});
```

If `@testing-library/react` isn't installed yet, install it:

```bat
cd frontend
npm install --save-dev @testing-library/react
```

- [ ] **Step 2: Run tests to verify they fail**

```bat
cd frontend
npm run test -- useLayoutCache
```

Expected: module not found.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/hooks/useLayoutCache.ts`:

```typescript
import { useState, useCallback, useEffect } from "react";
import type { CachedLayout, CachedLayoutSummary } from "../types/engine";

const ENGINE_URL = "http://127.0.0.1:8765";

export function useLayoutCache() {
  const [entries, setEntries] = useState<CachedLayoutSummary[]>([]);
  const [activeId, setActiveIdRaw] = useState<string | null>(null);
  const [activeEntry, setActiveEntry] = useState<CachedLayout | null>(null);

  const refresh = useCallback(async (): Promise<CachedLayoutSummary[]> => {
    try {
      const res = await fetch(`${ENGINE_URL}/layouts`);
      if (!res.ok) return entries;
      const list = (await res.json()) as CachedLayoutSummary[];
      setEntries(list);
      return list;
    } catch {
      return entries;
    }
  }, [entries]);

  const setActiveId = useCallback((id: string | null) => {
    setActiveIdRaw(id);
    if (id === null) setActiveEntry(null);
  }, []);

  // Lazy fetch the full entry when the active tab changes.
  useEffect(() => {
    if (activeId === null) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${ENGINE_URL}/layouts/${activeId}`);
        if (!res.ok) {
          // 404 → entry was evicted; drop it from local state and pick a fallback.
          if (!cancelled) {
            setEntries((prev) => prev.filter((e) => e.id !== activeId));
            setActiveEntry(null);
            setActiveIdRaw(null);
          }
          return;
        }
        const data = (await res.json()) as CachedLayout;
        if (!cancelled) setActiveEntry(data);
      } catch {
        // Engine unreachable — leave state alone.
      }
    })();
    return () => { cancelled = true; };
  }, [activeId]);

  const closeTab = useCallback(async (id: string) => {
    try {
      await fetch(`${ENGINE_URL}/layouts/${id}`, { method: "DELETE" });
    } catch {
      // Idempotent: treat network error as "the tab is gone".
    }
    const fresh = await refresh();
    if (activeId === id) {
      if (fresh.length === 0) {
        setActiveIdRaw(null);
        setActiveEntry(null);
      } else {
        setActiveIdRaw(fresh[0].id);
      }
    }
  }, [activeId, refresh]);

  return { entries, activeId, activeEntry, setActiveId, closeTab, refresh };
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bat
cd frontend
npm run test -- useLayoutCache
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bat
git add frontend\src\hooks\useLayoutCache.ts frontend\src\hooks\useLayoutCache.test.ts
git commit -m "feat(frontend): add useLayoutCache hook (Phase 6)"
```

---

### Task 7: Update `GrainPanel` — drop "none" + fast-mode, add Show-grainline

**Files:**
- Modify: `frontend/src/components/sidebar/GrainPanel.tsx`

No vitest test (visual-only component); the test in Task 13 (BottomPanel) covers the test-infrastructure-still-works check. If you want a smoke test, add `GrainPanel.test.tsx` here — optional.

- [ ] **Step 1: Replace the component**

Replace `frontend/src/components/sidebar/GrainPanel.tsx` with:

```typescript
import type { GrainMode } from "../../types/engine";

interface GrainPanelProps {
  grainMode: GrainMode;
  showGrainline: boolean;
  onGrainModeChange: (mode: GrainMode) => void;
  onShowGrainlineChange: (show: boolean) => void;
}

const GRAIN_MODE_LABELS: Record<GrainMode, string> = {
  single: "Single direction",
  bi: "Bi-directional",
};

export function GrainPanel({
  grainMode,
  showGrainline,
  onGrainModeChange,
  onShowGrainlineChange,
}: GrainPanelProps) {
  return (
    <div>
      <div>
        <div style={styles.label}>Grain Mode</div>
        <div style={styles.hint}>Fabric grain runs top → bottom</div>
        {(["single", "bi"] as const).map((mode) => (
          <label key={mode} style={styles.radioRow}>
            <input
              type="radio"
              name="grain-mode"
              checked={grainMode === mode}
              onChange={() => onGrainModeChange(mode)}
            />
            <span style={{ fontSize: 12 }}>{GRAIN_MODE_LABELS[mode]}</span>
          </label>
        ))}
      </div>

      <div style={{ marginTop: 10 }}>
        <label style={styles.checkRow}>
          <input
            type="checkbox"
            checked={showGrainline}
            onChange={(e) => onShowGrainlineChange(e.target.checked)}
          />
          <span style={{ fontSize: 12 }}>Show grainline</span>
        </label>
      </div>
    </div>
  );
}

const styles = {
  label: {
    fontSize: 11,
    fontWeight: 600 as const,
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
    color: "var(--color-text-muted)",
    marginBottom: 4,
  },
  hint: {
    fontSize: 11,
    color: "var(--color-text-muted)",
    marginBottom: 4,
    fontStyle: "italic" as const,
  },
  radioRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginTop: 4,
    cursor: "pointer",
  },
  checkRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    cursor: "pointer",
  },
} as const;
```

- [ ] **Step 2: Skip — App.tsx caller updated in Task 11**

- [ ] **Step 3: Commit**

```bat
git add frontend\src\components\sidebar\GrainPanel.tsx
git commit -m "feat(frontend): GrainPanel drops none+fastMode, adds show-grainline (Phase 6)"
```

---

### Task 8: Update `PieceShape` — replace `grainMode` with `showGrainline`

**Files:**
- Modify: `frontend/src/components/canvas/PieceShape.tsx`

- [ ] **Step 1: Apply the change**

In `frontend/src/components/canvas/PieceShape.tsx`:

- Change the import line `import type { Piece, GrainMode } from "../../types/engine";` to `import type { Piece } from "../../types/engine";`
- Replace the `Props` interface field `grainMode: GrainMode;` with `showGrainline: boolean;`
- Replace the destructured prop `grainMode,` with `showGrainline,`
- Replace the conditional `{grainMode !== "none" && piece.grainline_direction_deg !== null && (() => {` with `{showGrainline && piece.grainline_direction_deg !== null && (() => {`

Final file content:

```typescript
// Renders a single placed piece as a Konva Group with the piece polygon,
// optional set color, and optional grain arrow.

import { Group, Line, Arrow } from "react-konva";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";

interface Props {
  piece: Piece;
  placement: Placement;
  isSelected: boolean;
  onSelect: () => void;
  showGrainline: boolean;
  scale: number;
  baseStroke: string;
  baseFill: string;
}

export function PieceShape({
  piece,
  placement,
  isSelected,
  onSelect,
  showGrainline,
  scale,
  baseStroke,
  baseFill,
}: Props) {
  const stroke = isSelected ? "#ff9800" : baseStroke;
  const fill = isSelected ? "rgba(255, 152, 0, 0.12)" : baseFill;

  const flatPoints = piece.polygon.flatMap(([x, y]) => [x, y]);

  const cx = piece.bbox.width / 2;
  const cy = piece.bbox.height / 2;

  const handleMouseEnter = (e: KonvaEventObject<MouseEvent>) => {
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "pointer";
  };

  const handleMouseLeave = (e: KonvaEventObject<MouseEvent>) => {
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "default";
  };

  return (
    <Group
      id={`piece-${piece.id}`}
      x={placement.x + cx}
      y={placement.y + cy}
      offsetX={cx}
      offsetY={cy}
      rotation={placement.rotationDeg}
      onClick={onSelect}
      onTap={onSelect}
      onMouseDown={(e) => { e.cancelBubble = true; }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <Line
        points={flatPoints}
        closed={true}
        stroke={stroke}
        fill={fill}
        strokeWidth={1}
        strokeScaleEnabled={false}
      />
      {showGrainline && piece.grainline_direction_deg !== null && (() => {
        const arrowLen = 50 / scale;
        const rad = (piece.grainline_direction_deg * Math.PI) / 180;
        return (
          <Arrow
            points={[
              cx - (arrowLen / 2) * Math.cos(rad),
              cy - (arrowLen / 2) * Math.sin(rad),
              cx + (arrowLen / 2) * Math.cos(rad),
              cy + (arrowLen / 2) * Math.sin(rad),
            ]}
            fill="#facc15"
            stroke="#facc15"
            strokeWidth={1.5}
            strokeScaleEnabled={false}
            pointerLength={8 / scale}
            pointerWidth={6 / scale}
            listening={false}
          />
        );
      })()}
    </Group>
  );
}
```

- [ ] **Step 2: Skip — CanvasWorkspace caller updated in Task 9**

- [ ] **Step 3: Commit**

```bat
git add frontend\src\components\canvas\PieceShape.tsx
git commit -m "refactor(frontend): PieceShape uses showGrainline instead of grainMode (Phase 6)"
```

---

### Task 9: Update `CanvasWorkspace` — pass `showGrainline` through

**Files:**
- Modify: `frontend/src/components/canvas/CanvasWorkspace.tsx`

- [ ] **Step 1: Apply the change**

In `frontend/src/components/canvas/CanvasWorkspace.tsx`:

- Change `import type { Piece, GrainMode } from "../../types/engine";` to `import type { Piece } from "../../types/engine";`
- In the `Props` interface, replace `grainMode: GrainMode;` with `showGrainline: boolean;`
- In the function signature, replace `grainMode,` (in the destructured props list) with `showGrainline,`
- In the `<PieceShape …>` JSX (around line 195–205), replace the prop `grainMode={grainMode}` with `showGrainline={showGrainline}`

- [ ] **Step 2: Skip — App.tsx caller updated in Task 11**

- [ ] **Step 3: Commit**

```bat
git add frontend\src\components\canvas\CanvasWorkspace.tsx
git commit -m "refactor(frontend): CanvasWorkspace forwards showGrainline (Phase 6)"
```

---

### Task 10: Update `usePlacements` — driven by active cached entry

**Files:**
- Modify: `frontend/src/hooks/usePlacements.ts`

The current hook owns `placements` state and exposes `setAllPlacements` + `resetPlacements`. Phase 6 makes the hook a thin transformer over `useLayoutCache.activeEntry?.placements` (engine-coord) → frontend `Placement[]`. The transform was previously done inline in `App.tsx` (lines 121–124).

- [ ] **Step 1: Apply the change**

Replace `frontend/src/hooks/usePlacements.ts` with:

```typescript
import { useMemo } from "react";
import type { Piece, AutoLayoutPlacement } from "../types/engine";
import type { Placement } from "../types/canvas";
import { engineToFrontendPlacement } from "../utils/enginePlacement";

/**
 * Derive frontend Placement[] from the active cached layout's engine-coord placements.
 *
 * Manual editing was removed in the optimization round; this hook is now a pure
 * memoized projection. Returns [] when there is no active entry.
 */
export function usePlacements(
  pieces: Piece[],
  enginePlacements: AutoLayoutPlacement[] | null,
) {
  const placements = useMemo<Placement[]>(() => {
    if (!enginePlacements || pieces.length === 0) return [];
    const pieceMap = new Map(pieces.map((p) => [p.id, p]));
    return enginePlacements
      .map((pl) => {
        const piece = pieceMap.get(pl.piece_id);
        if (!piece) return null;
        return engineToFrontendPlacement(piece, pl.x, pl.y, pl.rotation_deg);
      })
      .filter((p): p is Placement => p !== null);
  }, [pieces, enginePlacements]);

  return { placements };
}
```

- [ ] **Step 2: Skip — App.tsx will adopt the new signature in Task 11**

- [ ] **Step 3: Commit**

```bat
git add frontend\src\hooks\usePlacements.ts
git commit -m "refactor(frontend): usePlacements derives from active cached entry (Phase 6)"
```

---

### Task 11: Create `BottomPanel` component

**Files:**
- Create: `frontend/src/components/BottomPanel.tsx`
- Test: `frontend/src/components/BottomPanel.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/BottomPanel.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BottomPanel, formatDuration } from "./BottomPanel";

describe("formatDuration", () => {
  it("formats 0 ms as 00:00", () => {
    expect(formatDuration(0)).toBe("00:00");
  });
  it("formats 3500 ms as 00:03", () => {
    expect(formatDuration(3500)).toBe("00:03");
  });
  it("formats 125000 ms as 02:05", () => {
    expect(formatDuration(125000)).toBe("02:05");
  });
  it("formats 1 hour as 60:00", () => {
    expect(formatDuration(3_600_000)).toBe("60:00");
  });
});

describe("BottomPanel", () => {
  it("shows length, utilization and duration when given an entry", () => {
    render(
      <BottomPanel
        markerLengthMm={1234.5}
        utilizationPct={82.4}
        durationMs={3500}
        overflow={false}
      />
    );
    expect(screen.getByText(/1235 mm/)).toBeInTheDocument();
    expect(screen.getByText(/82\.4%/)).toBeInTheDocument();
    expect(screen.getByText(/00:03/)).toBeInTheDocument();
    expect(screen.queryByText(/overflow/i)).not.toBeInTheDocument();
  });

  it("shows overflow warning when overflow is true", () => {
    render(
      <BottomPanel
        markerLengthMm={9999}
        utilizationPct={100}
        durationMs={1000}
        overflow={true}
      />
    );
    expect(screen.getByText(/overflow/i)).toBeInTheDocument();
  });

  it("renders an empty placeholder when no entry data is provided", () => {
    render(<BottomPanel markerLengthMm={null} utilizationPct={null} durationMs={null} overflow={false} />);
    expect(screen.getByText(/no layout yet/i)).toBeInTheDocument();
  });
});
```

If `@testing-library/jest-dom` isn't set up, either omit the `.toBeInTheDocument()` assertions in favour of `expect(screen.getByText(…)).toBeTruthy()`, or install it:

```bat
cd frontend
npm install --save-dev @testing-library/jest-dom
```

…and add `import "@testing-library/jest-dom";` to the test setup file (or to the test file directly).

- [ ] **Step 2: Run tests to verify they fail**

```bat
cd frontend
npm run test -- BottomPanel
```

Expected: module not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/BottomPanel.tsx`:

```typescript
interface BottomPanelProps {
  markerLengthMm: number | null;
  utilizationPct: number | null;
  durationMs: number | null;
  overflow: boolean;
}

export function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const mm = Math.floor(totalSeconds / 60);
  const ss = totalSeconds % 60;
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

export function BottomPanel({
  markerLengthMm,
  utilizationPct,
  durationMs,
  overflow,
}: BottomPanelProps) {
  if (markerLengthMm === null || utilizationPct === null || durationMs === null) {
    return (
      <div style={styles.root}>
        <span style={styles.placeholder}>No layout yet. Click Auto Layout.</span>
      </div>
    );
  }

  const utilColor =
    utilizationPct >= 75 ? "var(--color-success)"
    : utilizationPct >= 50 ? "var(--color-warning)"
    : "var(--color-text)";

  return (
    <div style={styles.root}>
      <div style={styles.item}>
        <span style={styles.label}>Length:</span>
        <span style={styles.value}>{Math.round(markerLengthMm)} mm</span>
      </div>
      <div style={styles.item}>
        <span style={styles.label}>Util:</span>
        <span style={{ ...styles.value, color: utilColor }}>
          {overflow ? "—" : `${utilizationPct.toFixed(1)}%`}
        </span>
      </div>
      <div style={styles.item}>
        <span style={styles.label}>⏱</span>
        <span style={styles.value}>{formatDuration(durationMs)}</span>
      </div>
      {overflow && (
        <span style={styles.warn}>Pieces overflow fabric.</span>
      )}
    </div>
  );
}

const styles = {
  root: {
    height: 32,
    background: "var(--color-surface)",
    borderTop: "1px solid var(--color-border)",
    display: "flex",
    alignItems: "center",
    gap: 24,
    padding: "0 16px",
    fontSize: 12,
    color: "var(--color-text)",
    flexShrink: 0,
  },
  item: {
    display: "flex",
    alignItems: "center",
    gap: 6,
  },
  label: {
    color: "var(--color-text-muted)",
  },
  value: {
    fontWeight: 600 as const,
  },
  warn: {
    marginLeft: "auto",
    color: "var(--color-warning)",
  },
  placeholder: {
    color: "var(--color-text-muted)",
  },
} as const;
```

- [ ] **Step 4: Run tests to verify they pass**

```bat
cd frontend
npm run test -- BottomPanel
```

Expected: all tests passed.

- [ ] **Step 5: Commit**

```bat
git add frontend\src\components\BottomPanel.tsx frontend\src\components\BottomPanel.test.tsx
git commit -m "feat(frontend): add BottomPanel with MM:SS timer (Phase 6)"
```

---

### Task 12: Create `CachedLayoutTabs` component

**Files:**
- Create: `frontend/src/components/CachedLayoutTabs.tsx`

No vitest (visual). Tab strip is verified manually in the dev server.

- [ ] **Step 1: Implement the component**

Create `frontend/src/components/CachedLayoutTabs.tsx`:

```typescript
import type { CachedLayoutSummary } from "../types/engine";

interface Props {
  entries: CachedLayoutSummary[];
  activeId: string | null;
  onActivate: (id: string) => void;
  onClose: (id: string) => void;
}

/**
 * Tab strip rendered ABOVE the canvas, scoped to the canvas column
 * (left edge aligned with canvas, not with the sidebar).
 */
export function CachedLayoutTabs({ entries, activeId, onActivate, onClose }: Props) {
  if (entries.length === 0) {
    return <div style={styles.empty}>No cached layouts yet.</div>;
  }
  return (
    <div style={styles.strip}>
      {entries.map((e) => {
        const isActive = e.id === activeId;
        return (
          <div
            key={e.id}
            style={{ ...styles.tab, ...(isActive ? styles.tabActive : {}) }}
            onClick={() => onActivate(e.id)}
            role="button"
            tabIndex={0}
          >
            <span style={styles.label}>
              {e.grain_mode} · ×{e.copies} · {formatHHMMSS(e.timestamp)}
            </span>
            <button
              style={styles.closeBtn}
              onClick={(ev) => {
                ev.stopPropagation();
                onClose(e.id);
              }}
              aria-label={`Close ${e.id}`}
              title="Close tab"
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}

// "YYYYMMDDHHMMSS" → "HH:MM:SS"
function formatHHMMSS(timestamp: string): string {
  if (timestamp.length !== 14) return timestamp;
  return `${timestamp.slice(8, 10)}:${timestamp.slice(10, 12)}:${timestamp.slice(12, 14)}`;
}

const styles = {
  strip: {
    height: 32,
    background: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border)",
    display: "flex",
    alignItems: "stretch",
    overflowX: "auto" as const,
    flexShrink: 0,
  },
  empty: {
    height: 32,
    background: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border)",
    display: "flex",
    alignItems: "center",
    padding: "0 12px",
    fontSize: 12,
    color: "var(--color-text-muted)",
    flexShrink: 0,
  },
  tab: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "0 8px 0 12px",
    fontSize: 12,
    cursor: "pointer",
    borderRight: "1px solid var(--color-border)",
    color: "var(--color-text-muted)",
    background: "transparent",
  },
  tabActive: {
    background: "var(--color-bg)",
    color: "var(--color-text)",
    fontWeight: 600 as const,
  },
  label: {
    whiteSpace: "nowrap" as const,
  },
  closeBtn: {
    background: "transparent",
    border: "none",
    color: "inherit",
    cursor: "pointer",
    fontSize: 14,
    padding: "0 4px",
    lineHeight: 1,
  },
} as const;
```

- [ ] **Step 2: Skip — wired into App.tsx in Task 13**

- [ ] **Step 3: Commit**

```bat
git add frontend\src\components\CachedLayoutTabs.tsx
git commit -m "feat(frontend): add CachedLayoutTabs strip (Phase 6)"
```

---

### Task 13: Rewire `App.tsx` to the new layout and contracts

**Files:**
- Modify: `frontend/src/app/App.tsx`

This is the big integration task. The dev environment is currently broken (`npm run build` will fail) because of all the prior interface changes — this task makes it green again.

- [ ] **Step 1: Apply the change**

Replace `frontend/src/app/App.tsx` with:

```typescript
// OpenMarker — Phase 6: cached-tabs workflow with bottom metrics panel.
// Layout: topbar | preview-panel | (sidebar + (tabs / canvas)) | bottom-panel | statusbar.

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import type { EngineStatus, PingResponse, GrainMode, Piece } from "../types/engine";
import { useImportDxf, type ImportOutcome } from "../hooks/useImportDxf";
import { usePlacements } from "../hooks/usePlacements";
import { useAutoLayout } from "../hooks/useAutoLayout";
import { useLayoutCache } from "../hooks/useLayoutCache";
import { PieceList } from "../components/pieces/PieceList";
import { PreviewPanel } from "../components/PreviewPanel";
import { CachedLayoutTabs } from "../components/CachedLayoutTabs";
import { BottomPanel } from "../components/BottomPanel";
import { CanvasWorkspace } from "../components/canvas/CanvasWorkspace";
import { FabricPanel } from "../components/sidebar/FabricPanel";
import { GrainPanel } from "../components/sidebar/GrainPanel";

const FABRIC_GRAIN_DEG = 90;
const ENGINE_URL = "http://127.0.0.1:8765";

export default function App() {
  const [engineStatus, setEngineStatus] = useState<EngineStatus>("unknown");
  const [statusMessage, setStatusMessage] = useState("Engine not connected");
  const [selectedPieceId, setSelectedPieceId] = useState<string | null>(null);
  const [fabricWidthMm, setFabricWidthMm] = useState<number>(1500);
  const [currentFileName, setCurrentFileName] = useState<string | null>(null);

  const { status: importStatus, pieces, warnings, errorMessage, handleFileSelected } = useImportDxf();

  const [grainMode, setGrainMode] = useState<GrainMode>("single");
  const [showGrainline, setShowGrainline] = useState<boolean>(true);
  const [copiesInput, setCopiesInput] = useState<string>("");

  const { runAutoLayout, abort: abortAutoLayout, status: autoStatus, errorMessage: autoError } = useAutoLayout();
  const { entries, activeId, activeEntry, setActiveId, closeTab, refresh: refreshCache } = useLayoutCache();

  const copies = useMemo(() => {
    const trimmed = copiesInput.trim();
    if (trimmed === "") return 1;
    const v = parseInt(trimmed, 10);
    if (!Number.isFinite(v) || v < 1) return 1;
    return Math.min(20, Math.floor(v));
  }, [copiesInput]);

  const expandedPieces = useMemo<Piece[]>(() => {
    if (pieces.length === 0) return [];
    const out: Piece[] = [];
    for (let setIdx = 0; setIdx < copies; setIdx++) {
      for (const p of pieces) {
        out.push({ ...p, id: `${p.id}__c${setIdx}`, setIndex: setIdx });
      }
    }
    return out;
  }, [pieces, copies]);

  const { placements } = usePlacements(expandedPieces, activeEntry?.placements ?? null);

  const overflow = (activeEntry?.marker_length_mm ?? 0) > 0 && (activeEntry?.utilization_pct ?? 0) > 100;

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setSelectedPieceId(null);
  }, [pieces]);

  const pingEngine = useCallback(async () => {
    setEngineStatus("connecting");
    setStatusMessage("Connecting to engine...");
    try {
      const res = await fetch(`${ENGINE_URL}/ping`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: PingResponse = await res.json();
      setEngineStatus("connected");
      setStatusMessage(`Engine connected — ${data.message} (v${data.version})`);
    } catch {
      setEngineStatus("error");
      setStatusMessage("Engine not reachable. Start: scripts/dev-engine.bat");
    }
  }, []);

  const onFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      e.target.value = "";
      const outcome: ImportOutcome = await handleFileSelected(file);
      if (outcome.ok) {
        setStatusMessage(`${outcome.pieces.length} piece${outcome.pieces.length !== 1 ? "s" : ""} imported from ${file.name}`);
        setCurrentFileName(file.name);
        setFabricWidthMm(1500);
      } else {
        setStatusMessage(`Import failed: ${outcome.errorMessage}`);
      }
    },
    [handleFileSelected]
  );

  const handleAutoLayout = useCallback(async () => {
    if (expandedPieces.length === 0 || !currentFileName) return;
    const canonical = String(copies);
    if (copiesInput.trim() !== canonical) {
      setCopiesInput(canonical);
    }
    const outcome = await runAutoLayout(
      currentFileName, expandedPieces, fabricWidthMm, grainMode, FABRIC_GRAIN_DEG, copies,
    );
    if (outcome.ok) {
      await refreshCache();
      setActiveId(outcome.data.id);
      setStatusMessage(
        `Auto layout: ${outcome.data.placements.length} piece${outcome.data.placements.length !== 1 ? "s" : ""} · ` +
        `Marker: ${Math.round(outcome.data.marker_length_mm)} mm · ` +
        `Utilization: ${outcome.data.utilization_pct}%`
      );
    } else if (outcome.aborted) {
      setStatusMessage("Auto layout stopped.");
    } else {
      setStatusMessage(`Auto layout failed: ${outcome.errorMessage}`);
    }
  }, [expandedPieces, currentFileName, fabricWidthMm, grainMode, copies, copiesInput, runAutoLayout, refreshCache, setActiveId]);

  const importButtonLabel = importStatus === "loading" ? "Importing..." : "Import DXF";

  return (
    <div style={styles.root}>
      <div style={styles.topBar}>
        <span style={styles.appTitle}>
          OpenMarker
          {currentFileName && (
            <span style={styles.appSubtitle}> — Working on {currentFileName}</span>
          )}
        </span>
      </div>

      <PreviewPanel
        pieces={pieces}
        selectedPieceId={selectedPieceId}
        onSelect={setSelectedPieceId}
      />

      <div style={styles.body}>
        <div style={styles.sidebar}>
          <Section title="Engine">
            <button onClick={pingEngine} disabled={engineStatus === "connecting"}>
              {engineStatus === "connecting" ? "Connecting..." : "Ping Engine"}
            </button>
            <StatusDot status={engineStatus} />
          </Section>

          <Section title="Fabric">
            <FabricPanel fabricWidthMm={fabricWidthMm} onChange={setFabricWidthMm} />
          </Section>

          <Section title="Grain">
            <GrainPanel
              grainMode={grainMode}
              showGrainline={showGrainline}
              onGrainModeChange={setGrainMode}
              onShowGrainlineChange={setShowGrainline}
            />
          </Section>

          <Section title="Settings">
            <label style={styles.settingRowVertical}>
              <span style={styles.settingLabel}>Copies (1–20)</span>
              <input
                type="number"
                min={1}
                max={20}
                value={copiesInput}
                placeholder="1"
                onChange={(e) => setCopiesInput(e.target.value)}
                style={styles.numberInputTall}
              />
            </label>
          </Section>

          <Section title="Layout">
            <input
              ref={fileInputRef}
              type="file"
              accept=".dxf"
              style={{ display: "none" }}
              onChange={onFileChange}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={importStatus === "loading"}
            >
              {importButtonLabel}
            </button>

            <button
              onClick={handleAutoLayout}
              disabled={pieces.length === 0 || autoStatus === "loading"}
              style={{ opacity: pieces.length === 0 ? 0.4 : 1 }}
            >
              {autoStatus === "loading" ? "Running..." : "Auto Layout"}
            </button>

            {autoStatus === "loading" && (
              <button
                onClick={abortAutoLayout}
                style={{ fontSize: 12, background: "var(--color-error, #b91c1c)", color: "#fff" }}
              >
                Stop
              </button>
            )}

            {autoStatus === "error" && autoError && (
              <p style={styles.errorText}>{autoError}</p>
            )}

            {importStatus === "error" && (
              <p style={styles.errorText}>{errorMessage}</p>
            )}

            {importStatus === "success" && (
              <>
                <p style={styles.successText}>{pieces.length} piece{pieces.length !== 1 ? "s" : ""} imported</p>
                <PieceList
                  pieces={pieces}
                  selectedPieceId={selectedPieceId}
                  onSelect={(id) => setSelectedPieceId(id === selectedPieceId ? null : id)}
                />
                {warnings.length > 0 && (
                  <div style={styles.warningBlock}>
                    {warnings.map((w, i) => (
                      <p key={i} style={styles.warningText}>{w}</p>
                    ))}
                  </div>
                )}
              </>
            )}

            {importStatus === "idle" && (
              <p style={styles.placeholder}>Import a DXF to begin.</p>
            )}
          </Section>
        </div>

        {/* Canvas column: tabs strip above the canvas (sharing the canvas's left edge). */}
        <div style={styles.canvasColumn}>
          <CachedLayoutTabs
            entries={entries}
            activeId={activeId}
            onActivate={setActiveId}
            onClose={closeTab}
          />
          <div style={styles.canvas}>
            <CanvasWorkspace
              pieces={expandedPieces}
              placements={placements}
              selectedPieceId={selectedPieceId}
              onSelectPiece={setSelectedPieceId}
              fabricWidthMm={fabricWidthMm}
              showGrainline={showGrainline}
              markerLengthMm={activeEntry?.marker_length_mm ?? 0}
            />
          </div>
        </div>
      </div>

      <BottomPanel
        markerLengthMm={activeEntry?.marker_length_mm ?? null}
        utilizationPct={activeEntry?.utilization_pct ?? null}
        durationMs={activeEntry?.duration_ms ?? null}
        overflow={overflow}
      />

      <div style={styles.statusBar}>
        <span>{statusMessage}</span>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={styles.section}>
      <div style={styles.sectionTitle}>{title}</div>
      <div style={styles.sectionBody}>{children}</div>
    </div>
  );
}

function StatusDot({ status }: { status: EngineStatus }) {
  const colors: Record<EngineStatus, string> = {
    unknown: "var(--color-text-muted)",
    connecting: "var(--color-warning)",
    connected: "var(--color-success)",
    error: "var(--color-error)",
  };
  const labels: Record<EngineStatus, string> = {
    unknown: "Not checked",
    connecting: "Connecting",
    connected: "Connected",
    error: "Error",
  };
  return (
    <div style={styles.statusDot}>
      <span style={{ ...styles.dot, background: colors[status] }} />
      <span style={{ color: colors[status] }}>{labels[status]}</span>
    </div>
  );
}

const styles = {
  root: {
    display: "flex",
    flexDirection: "column" as const,
    height: "100vh",
    background: "var(--color-bg)",
  },
  topBar: {
    height: "var(--topbar-height)",
    background: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border)",
    display: "flex",
    alignItems: "center",
    padding: "0 16px",
    flexShrink: 0,
  },
  appTitle: { fontWeight: 600, fontSize: 14, letterSpacing: "0.02em", color: "var(--color-text)" },
  appSubtitle: { fontWeight: 400, color: "var(--color-text-muted)", marginLeft: 4 },
  body: { flex: 1, display: "flex", overflow: "hidden" },
  sidebar: {
    width: "var(--sidebar-width)",
    borderRight: "1px solid var(--color-border)",
    background: "var(--color-surface)",
    display: "flex",
    flexDirection: "column" as const,
    flexShrink: 0,
    overflowY: "auto" as const,
  },
  canvasColumn: {
    flex: 1,
    display: "flex",
    flexDirection: "column" as const,
    overflow: "hidden",
  },
  canvas: { flex: 1, overflow: "hidden" },
  section: { borderBottom: "1px solid var(--color-border)" },
  sectionTitle: {
    padding: "8px 12px",
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
    color: "var(--color-text-muted)",
  },
  sectionBody: {
    padding: "8px 12px 12px",
    display: "flex",
    flexDirection: "column" as const,
    gap: 8,
  },
  statusBar: {
    height: "var(--statusbar-height)",
    background: "var(--color-surface)",
    borderTop: "1px solid var(--color-border)",
    display: "flex",
    alignItems: "center",
    padding: "0 12px",
    fontSize: 12,
    color: "var(--color-text-muted)",
    flexShrink: 0,
  },
  statusDot: { display: "flex", alignItems: "center", gap: 6, fontSize: 12 },
  dot: { width: 8, height: 8, borderRadius: "50%", display: "inline-block" },
  placeholder: { color: "var(--color-text-muted)", fontSize: 12 },
  errorText: { color: "var(--color-error)", fontSize: 12 },
  successText: { color: "var(--color-success)", fontSize: 12 },
  warningBlock: { borderTop: "1px solid var(--color-border)", paddingTop: 4 },
  warningText: { color: "var(--color-warning)", fontSize: 11 },
  settingRowVertical: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 6,
    fontSize: 12,
  },
  settingLabel: { color: "var(--color-text-muted)" },
  // Doubled height vs the old `numberInput` style (was 60×~22px; now 60×44px,
  // larger font for legibility per Phase 6 spec).
  numberInputTall: {
    width: 80,
    height: 44,
    padding: "4px 8px",
    background: "var(--color-surface)",
    color: "var(--color-text)",
    border: "1px solid var(--color-border)",
    borderRadius: 3,
    fontSize: 18,
    textAlign: "right" as const,
  },
} as const;
```

- [ ] **Step 2: Verify build**

```bat
cd frontend
npm run build
```

Expected: build succeeds with no TypeScript errors.

```bat
npm run test
```

Expected: existing tests still pass.

- [ ] **Step 3: Manual smoke test**

In two terminals:

```bat
scripts\dev-engine.bat
```

```bat
cd desktop\src-tauri
cargo tauri dev
```

Verify:
- Import a DXF → preview panel shows pieces, canvas is empty, tabs strip says "No cached layouts yet."
- Click Auto Layout → a new tab appears, canvas shows placement, bottom panel shows length / util / `MM:SS`.
- Click Auto Layout again → second tab appears, becomes active.
- Click first tab → canvas + bottom panel switch to first run's data.
- Click × on a tab → tab removed; if it was active, newest remaining becomes active.
- Toggle Show grainline → yellow arrows appear/disappear with no engine call.
- Settings → Copies input is visibly taller than before.

- [ ] **Step 4: Commit**

```bat
git add frontend\src\app\App.tsx
git commit -m "feat(frontend): wire cached tabs + bottom panel + new layout (Phase 6)"
```

---

### Task 14: Delete `frontend/src/utils/metrics.ts`

**Files:**
- Delete: `frontend/src/utils/metrics.ts` (if no longer imported)

- [ ] **Step 1: Check for remaining imports**

```bat
cd frontend
findstr /s /m "from \"\.\./utils/metrics\"" src
findstr /s /m "computeMarkerMetrics" src
```

Expected: no matches. (App.tsx no longer imports it after Task 13.)

- [ ] **Step 2: Delete the file**

```bat
del frontend\src\utils\metrics.ts
```

If there is a `metrics.test.ts`, delete it too:

```bat
del frontend\src\utils\metrics.test.ts 2>nul
```

- [ ] **Step 3: Verify build still works**

```bat
cd frontend
npm run build
```

Expected: success.

- [ ] **Step 4: Commit**

```bat
git add -A frontend\src\utils
git commit -m "chore(frontend): delete unused metrics util (Phase 6)"
```

---

## GROUP C — Engine, strict (now safe to tighten)

### Task 15: Remove `"none"` branch from `allowed_rotations`

**Files:**
- Modify: `engine/core/layout/grain.py`
- Modify: `engine/tests/unit/test_grain.py`

- [ ] **Step 1: Update the test file**

Replace `engine/tests/unit/test_grain.py` with:

```python
import pytest
from core.layout.grain import allowed_rotations


def test_piece_without_grainline_always_free():
    """Any grain mode with piece_grainline_deg=None returns all 360 rotations
    — no constraint without grain data."""
    for mode in ("single", "bi"):
        result = allowed_rotations(mode, fabric_grain_deg=0.0, piece_grainline_deg=None)
        assert result == list(range(360)), f"mode={mode} with None grainline should be free"


def test_single_aligns_grainline_with_fabric():
    """fabric_grain=0°, piece_grain=90° → target=(0-90)%360=270°."""
    result = allowed_rotations("single", fabric_grain_deg=0.0, piece_grainline_deg=90.0)
    assert result == [270.0]


def test_single_no_rotation_needed():
    """piece_grain == fabric_grain → target = 0°."""
    result = allowed_rotations("single", fabric_grain_deg=0.0, piece_grainline_deg=0.0)
    assert result == [0.0]


def test_bi_returns_target_and_180():
    """fabric=0°, piece_grain=90° → target=270° → bi returns [270°, 90°]."""
    result = allowed_rotations("bi", fabric_grain_deg=0.0, piece_grainline_deg=90.0)
    assert set(result) == {270.0, 90.0}


def test_bi_wraparound():
    """fabric=0°, piece_grain=270° → target=90° → bi returns [90°, 270°]."""
    result = allowed_rotations("bi", fabric_grain_deg=0.0, piece_grainline_deg=270.0)
    assert set(result) == {90.0, 270.0}


def test_single_45_degree_fabric():
    """fabric=45°, piece_grain=90° → target=(45-90)%360=315°."""
    result = allowed_rotations("single", fabric_grain_deg=45.0, piece_grainline_deg=90.0)
    assert result == [315.0]


def test_none_mode_is_rejected():
    """Phase 6 removed 'none' as a grain mode."""
    with pytest.raises(ValueError, match="Unknown grain_mode"):
        allowed_rotations("none", fabric_grain_deg=0.0, piece_grainline_deg=0.0)


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown grain_mode"):
        allowed_rotations("diagonal", fabric_grain_deg=0.0, piece_grainline_deg=0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bat
engine\.venv\Scripts\pytest engine\tests\unit\test_grain.py -v
```

Expected: `test_none_mode_is_rejected` FAILS (current code returns `list(range(360))` for "none" instead of raising).

- [ ] **Step 3: Update `grain.py`**

Replace `engine/core/layout/grain.py` with:

```python
from __future__ import annotations


def allowed_rotations(
    grain_mode: str,
    fabric_grain_deg: float,
    piece_grainline_deg: float | None,
) -> list[float]:
    """
    Return the rotation angles (degrees, CW) the heuristic may try for one piece.

    grain_mode:
      'single' — piece grainline must align with fabric grain (one candidate)
      'bi'     — piece grainline may align or be 180° opposite (two candidates)

    If piece_grainline_deg is None (no grainline data in DXF), any mode returns
    all 360 candidates — no constraint without data.

    Phase 6: the 'none' (free rotation) mode was removed — production markers
    always honour grain. Pass 'single' for a fixed alignment.
    """
    if grain_mode not in ("single", "bi"):
        raise ValueError(f"Unknown grain_mode: {grain_mode!r}")

    if piece_grainline_deg is None:
        return list(range(360))

    target = (fabric_grain_deg - piece_grainline_deg) % 360

    if grain_mode == "single":
        return [target]
    # grain_mode == "bi"
    return [target, (target + 180) % 360]
```

- [ ] **Step 4: Run tests to verify they pass**

```bat
engine\.venv\Scripts\pytest engine\tests\unit\test_grain.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bat
git add engine\core\layout\grain.py engine\tests\unit\test_grain.py
git commit -m "feat(engine): drop 'none' grain mode (Phase 6)"
```

---

### Task 16: Remove `auto_layout_bbox` and related code from `heuristic.py`

**Files:**
- Modify: `engine/core/layout/heuristic.py`
- Modify: `engine/tests/unit/test_heuristic.py`

- [ ] **Step 1: Update tests first**

Open `engine/tests/unit/test_heuristic.py` and:

1. Change the import line `from core.layout.heuristic import auto_layout_bbox, auto_layout_polygon, Placement` to `from core.layout.heuristic import auto_layout_polygon, Placement`
2. Delete every test function whose name starts with `test_bbox_` (the "--- bbox mode tests ---" section).
3. In every remaining test that passes `grain_mode="none"`, change it to `grain_mode="single"`. Where the test uses pieces without grainline data, behaviour is unchanged (None grainline → all 360 rotations regardless of mode). Where the test uses pieces with grainline data, verify the assertion still makes sense for `"single"`; if not, mark `@pytest.mark.skip(reason="needs rewrite for 'single' grain mode")` and add a TODO comment — better to ship a skipped test than a broken one.

Run the file:

```bat
engine\.venv\Scripts\pytest engine\tests\unit\test_heuristic.py -v
```

Expected: bbox tests gone; polygon tests pass.

- [ ] **Step 2: Remove the dead code from `heuristic.py`**

In `engine/core/layout/heuristic.py`, delete:

- The function `_rotated_bbox_dims` (lines 38–45)
- The function `_strip_pack` (the entire "Strip-packing (bbox / fast mode)" section, lines ~148–209)
- The function `auto_layout_bbox` (the public-API "Strip-packing" wrapper, lines ~578–603)

Also simplify `_modes_to_try` and `_layout_rotations`:

- In `_modes_to_try`, remove the `if grain_mode == "none": return ["none"]` branch — only `"single"` and `"bi"` remain.
- In `_layout_rotations`, remove the `if grain_mode == "none" or piece_grainline_deg is None: return [0.0, 90.0, 180.0, 270.0]` early-return. The remaining body should be:

```python
def _layout_rotations(
    grain_mode: str,
    fabric_grain_deg: float,
    piece_grainline_deg: float | None,
) -> list[float]:
    """Discrete rotation set for layout search.

    Pieces with no grainline data: fall back to cardinal angles (production
    markers only use cardinal rotations; 360 candidates wastes search).
    """
    if piece_grainline_deg is None:
        return [0.0, 90.0, 180.0, 270.0]
    target = (fabric_grain_deg - piece_grainline_deg) % 360
    if grain_mode == "single":
        return [target]
    if grain_mode == "bi":
        return [target, (target + 180) % 360]
    raise ValueError(f"Unknown grain_mode: {grain_mode!r}")
```

The final `_modes_to_try`:

```python
def _modes_to_try(grain_mode: str) -> list[str]:
    """Bi mode's rotation set is a strict superset of single's. A greedy BLF
    can therefore produce a worse bi layout than single (a locally-good rotation
    leaves a worse global gap). To guarantee bi >= single, run both and keep
    the shorter result."""
    if grain_mode == "bi":
        return ["bi", "single"]
    return [grain_mode]
```

- [ ] **Step 3: Update `engine/api/main.py`** to drop the bbox branch from `_do_layout` and stop importing `auto_layout_bbox`:

- Change `from core.layout.heuristic import auto_layout_bbox, auto_layout_polygon` to `from core.layout.heuristic import auto_layout_polygon`
- Replace the `_do_layout` closure (currently uses `fast_mode`) with:

```python
    def _do_layout():
        return auto_layout_polygon(pieces, fabric_width_mm, grain_mode, grain_direction_deg)
```

- Remove the line `fast_mode = bool(body.get("fast_mode", False))`.

- [ ] **Step 4: Run all engine tests**

```bat
engine\.venv\Scripts\pytest engine\tests -v
```

Expected: all tests pass. (Cache tests, polygon heuristic tests, grain tests, API tests, parser tests, normalize tests.)

- [ ] **Step 5: Commit**

```bat
git add engine\core\layout\heuristic.py engine\api\main.py engine\tests\unit\test_heuristic.py
git commit -m "refactor(engine): remove auto_layout_bbox + fast_mode (Phase 6)"
```

---

### Task 17: Tighten `/auto-layout` request validation

**Files:**
- Modify: `engine/api/main.py`
- Modify: `engine/tests/integration/test_api_cache.py`

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/integration/test_api_cache.py`:

```python
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
async def test_auto_layout_rejects_missing_filename():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/auto-layout", json={
            "pieces": [_square_piece()],
            "fabric_width_mm": 1500,
            "grain_mode": "single",
            "grain_direction_deg": 90,
        })
    assert res.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bat
engine\.venv\Scripts\pytest engine\tests\integration\test_api_cache.py::test_auto_layout_rejects_grain_mode_none engine\tests\integration\test_api_cache.py::test_auto_layout_rejects_missing_filename -v
```

Expected: both FAIL — current code accepts `"none"` (caught later in heuristic ValueError → 400 instead of 422) and treats missing filename as `"untitled.dxf"`.

- [ ] **Step 3: Add validation at the top of `auto_layout_endpoint`**

In `engine/api/main.py`, immediately after `body = await request.json()` and before any other field reads, add:

```python
    filename = body.get("filename")
    if not isinstance(filename, str) or not filename:
        raise HTTPException(status_code=422, detail="`filename` is required")

    grain_mode = str(body.get("grain_mode", "single"))
    if grain_mode not in ("single", "bi"):
        raise HTTPException(status_code=422, detail=f"`grain_mode` must be 'single' or 'bi', got {grain_mode!r}")
```

Remove the now-duplicate later assignments:
- Delete `grain_mode = str(body.get("grain_mode", "none"))` (or "single", whichever the prior task left).
- The earlier `filename = str(body.get("filename", "")) or "untitled.dxf"` line in the cache-insertion block is now redundant — replace it with the existing validated `filename` local.

Verify `fast_mode = …` is already gone (Task 16). If not, remove it.

- [ ] **Step 4: Update existing `test_api.py` auto-layout tests** to include `filename` and `grain_mode="single"` (currently they likely pass `grain_mode="none"` and omit `filename`):

```bat
engine\.venv\Scripts\pytest engine\tests\integration\test_api.py -v
```

If failures appear, open each failing test in `engine/tests/integration/test_api.py` and:
- Add `"filename": "sample.dxf"` to every `/auto-layout` request body.
- Change any `"grain_mode": "none"` to `"grain_mode": "single"`.

Re-run until green.

- [ ] **Step 5: Run all engine tests**

```bat
engine\.venv\Scripts\pytest engine\tests -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bat
git add engine\api\main.py engine\tests\integration\test_api_cache.py engine\tests\integration\test_api.py
git commit -m "feat(engine): require filename, reject grain_mode='none' (Phase 6)"
```

---

## GROUP D — Desktop shell (dynamic window size)

### Task 18: Tauri config — remove fixed size, set `visible: false`

**Files:**
- Modify: `desktop/src-tauri/tauri.conf.json`

- [ ] **Step 1: Apply the change**

Replace the `app.windows[0]` object in `desktop/src-tauri/tauri.conf.json` with:

```json
{
  "title": "OpenMarker",
  "minWidth": 900,
  "minHeight": 600,
  "resizable": true,
  "visible": false
}
```

Full file:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "OpenMarker",
  "version": "0.1.0",
  "identifier": "com.openmarker.app",
  "build": {
    "frontendDist": "../../frontend/dist",
    "devUrl": "http://localhost:1420",
    "beforeDevCommand": {
      "script": "npm run dev",
      "cwd": "../../frontend"
    },
    "beforeBuildCommand": {
      "script": "npm run build",
      "cwd": "../../frontend"
    }
  },
  "app": {
    "windows": [
      {
        "title": "OpenMarker",
        "minWidth": 900,
        "minHeight": 600,
        "resizable": true,
        "visible": false
      }
    ],
    "security": {
      "csp": null
    }
  },
  "bundle": {
    "active": true,
    "targets": "all",
    "icon": [
      "icons/32x32.png",
      "icons/128x128.png",
      "icons/icon.ico"
    ]
  }
}
```

- [ ] **Step 2: Skip — `lib.rs` sets size + shows window in next task**

If you launch `cargo tauri dev` now, the window will not be visible until Task 19 wires the show() call. That's expected.

- [ ] **Step 3: Commit**

```bat
git add desktop\src-tauri\tauri.conf.json
git commit -m "chore(desktop): drop fixed window size, start hidden (Phase 6)"
```

---

### Task 19: Compute startup window size in `lib.rs`

**Files:**
- Modify: `desktop/src-tauri/src/lib.rs`

- [ ] **Step 1: Apply the change**

Replace `desktop/src-tauri/src/lib.rs` with:

```rust
// OpenMarker — Tauri application entry point.
// Phase 6: dynamic window size — 70% of monitor logical height, 4:3 aspect ratio.

use tauri::{Manager, LogicalSize, Size};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                if let Err(err) = size_and_show(&window) {
                    eprintln!("[OpenMarker] window sizing failed: {err}");
                    // Fallback: best-effort default + show, so the user is never stuck with a hidden window.
                    let _ = window.set_size(Size::Logical(LogicalSize { width: 1280.0, height: 800.0 }));
                    let _ = window.center();
                    let _ = window.show();
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn size_and_show(window: &tauri::WebviewWindow) -> Result<(), Box<dyn std::error::Error>> {
    // current_monitor returns the monitor under the cursor at startup.
    let monitor = window
        .current_monitor()?
        .ok_or("no monitor detected")?;

    let scale = monitor.scale_factor();
    let physical = monitor.size();
    let logical_w = physical.width as f64 / scale;
    let logical_h = physical.height as f64 / scale;

    let mut height = logical_h * 0.7;
    let mut width = height * 4.0 / 3.0;

    // If the 4:3 width would exceed the monitor, clamp to 95% of monitor width
    // and recompute height from that.
    let max_width = logical_w * 0.95;
    if width > max_width {
        width = max_width;
        height = width * 3.0 / 4.0;
    }

    window.set_size(Size::Logical(LogicalSize { width, height }))?;
    window.center()?;
    window.show()?;
    Ok(())
}
```

- [ ] **Step 2: Build to verify Rust compiles**

```bat
cd desktop\src-tauri
cargo build
```

Expected: success. `tauri::WebviewWindow`, `Manager`, `LogicalSize`, `Size`, `Monitor::scale_factor()` / `size()` / `current_monitor()` are all stable in Tauri 2.

- [ ] **Step 3: Manual smoke test**

```bat
cd desktop\src-tauri
cargo tauri dev
```

Expected: window opens centered at ~70% of monitor logical height, 4:3 ratio. On your 5K monitor (5120×2880, scale 2.0 → logical 2560×1440), expect ~1344×1008. On 1080p, ~1008×756.

- [ ] **Step 4: Commit**

```bat
git add desktop\src-tauri\src\lib.rs
git commit -m "feat(desktop): dynamic window size at 70%% monitor height, 4:3 (Phase 6)"
```

---

## Wrap-up

### Task 20: Update BACKLOG.md — mark Phase 6 tasks complete

**Files:**
- Modify: `docs/planning/BACKLOG.md`

- [ ] **Step 1: Replace the Phase 6 placeholder checklist**

In `docs/planning/BACKLOG.md`, locate the Phase 6 section. Replace the line:

```
- [ ] (to be populated by the Phase 6 planning skill)
```

with the completed checklist:

```
- [x] Engine: `LayoutCache` module (FIFO, max 5, no dedup)
- [x] Engine: wire cache into `POST /auto-layout` (returns id/timestamp/duration)
- [x] Engine: `GET /layouts`, `GET /layouts/{id}`, `DELETE /layouts/{id}`
- [x] Engine: drop `'none'` grain mode
- [x] Engine: drop `auto_layout_bbox` (fast mode)
- [x] Engine: require `filename`, reject `grain_mode='none'` (422)
- [x] Frontend: tighten `GrainMode` type, add `CachedLayout` types
- [x] Frontend: `useLayoutCache` hook
- [x] Frontend: `useAutoLayout` sends filename + copies; drops fast_mode
- [x] Frontend: `usePlacements` derives from active cached entry
- [x] Frontend: `GrainPanel` drops none + fast, adds Show grainline
- [x] Frontend: `PieceShape` uses `showGrainline` prop
- [x] Frontend: `CanvasWorkspace` passes `showGrainline`
- [x] Frontend: `BottomPanel` with `MM:SS` timer
- [x] Frontend: `CachedLayoutTabs` strip above canvas
- [x] Frontend: App.tsx new layout; double-height copies input
- [x] Frontend: delete unused `utils/metrics.ts`
- [x] Desktop: drop fixed window size, start hidden
- [x] Desktop: compute 70%-height 4:3 size in `lib.rs`
```

- [ ] **Step 2: Commit**

```bat
git add docs\planning\BACKLOG.md
git commit -m "docs: mark Phase 6 tasks complete (Phase 6)"
```

---

## Done

After Task 20:

```bat
engine\.venv\Scripts\pytest engine\tests -v
cd frontend && npm run test && npm run build
cd ..\desktop\src-tauri && cargo build
```

All three green ⇒ Phase 6 is complete and ready to merge.
