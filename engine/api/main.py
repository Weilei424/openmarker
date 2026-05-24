# OpenMarker engine API
# Local HTTP server that bridges the Tauri frontend to the Python geometry logic.
# Runs on 127.0.0.1:8765 — not exposed to the network.

import dataclasses
import io
import time
import uuid
from datetime import datetime

import ezdxf
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.dxf import parse_dxf
from core.geometry import normalize_piece
from core.layout.cache import CachedLayout, get_cache
from core.layout.cancellation import (
    CancellationError,
    request_cancellation,
    reset_cancellation,
)
from core.layout.heuristic import auto_layout_polygon
from core.models.piece import BoundingBox, Piece as PieceModel

app = FastAPI(title="OpenMarker Engine", version="0.1.0")

# Allow requests from the Tauri webview (file:// or localhost origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.get("/ping")
def ping() -> dict:
    """Health check — confirms the engine process is running."""
    return {"status": "ok", "message": "OpenMarker engine running", "version": "0.1.0"}


@app.post("/import-dxf")
async def import_dxf(file: UploadFile) -> dict:
    """
    Accept a DXF file upload and return normalized pattern pieces.

    Response shape:
    {
        "pieces": [...],
        "piece_count": int,
        "skipped_count": int,
        "warnings": [...]
    }
    """
    filename = file.filename or ""
    if not filename.lower().endswith(".dxf"):
        raise HTTPException(status_code=400, detail="Only .dxf files are supported")

    content = await file.read()

    try:
        raw_pieces = parse_dxf(content)
    except ezdxf.DXFStructureError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid or corrupted DXF file: {exc}")

    pieces = []
    skipped = 0
    warnings: list[str] = []

    for i, raw in enumerate(raw_pieces):
        try:
            piece = normalize_piece(raw, piece_id=f"piece_{i}")
            pieces.append(dataclasses.asdict(piece))
        except ValueError as exc:
            skipped += 1
            warnings.append(f"Skipped layer '{raw.layer}': {exc}")

    return {
        "pieces": pieces,
        "piece_count": len(pieces),
        "skipped_count": skipped,
        "warnings": warnings,
    }


@app.post("/auto-layout")
async def auto_layout_endpoint(request: Request) -> dict:
    """
    Run heuristic auto-layout on provided pieces.

    Request JSON:
    {
        "pieces": [...],            // Piece objects from /import-dxf
        "fabric_width_mm": 1500,
        "grain_mode": "single",     // "single" | "bi"
        "grain_direction_deg": 0,
        "filename": "...",          // required
        "copies": 1                 // optional, defaults to 1
    }

    Response JSON:
    {
        "id": "...",                // Phase 6: cache entry id (UUID hex)
        "timestamp": "...",         // Phase 6: YYYYMMDDHHMMSS
        "duration_ms": 1234,        // Phase 6: layout duration
        "placements": [{"piece_id": "...", "x": 0, "y": 0, "rotation_deg": 0}],
        "marker_length_mm": 1234.5,
        "utilization_pct": 82.4
    }
    """
    body = await request.json()

    filename = body.get("filename")
    if not isinstance(filename, str) or not filename:
        raise HTTPException(status_code=422, detail="`filename` is required")

    grain_mode = str(body.get("grain_mode", "single"))
    if grain_mode not in ("single", "bi"):
        raise HTTPException(status_code=422, detail=f"`grain_mode` must be 'single' or 'bi', got {grain_mode!r}")

    fabric_width_mm = float(body.get("fabric_width_mm", 1500))
    grain_direction_deg = float(body.get("grain_direction_deg", 0.0))

    pieces_data = body.get("pieces", [])
    if not pieces_data:
        raise HTTPException(status_code=400, detail="No pieces provided")

    pieces: list[PieceModel] = []
    for d in pieces_data:
        bbox_d = d["bbox"]
        pieces.append(PieceModel(
            id=d["id"],
            name=d["name"],
            polygon=[(float(p[0]), float(p[1])) for p in d["polygon"]],
            area=float(d["area"]),
            bbox=BoundingBox(
                min_x=float(bbox_d["min_x"]),
                min_y=float(bbox_d["min_y"]),
                max_x=float(bbox_d["max_x"]),
                max_y=float(bbox_d["max_y"]),
                width=float(bbox_d["width"]),
                height=float(bbox_d["height"]),
            ),
            is_valid=bool(d["is_valid"]),
            validation_notes=list(d.get("validation_notes", [])),
            grainline_direction_deg=d.get("grainline_direction_deg"),
        ))

    # Dedup: if a cached entry exists for these exact settings, return it
    # instead of re-running the heuristic.
    existing = get_cache().find_by_settings(
        filename=filename,
        grain_mode=grain_mode,
        copies=int(body.get("copies", 1)),
        fabric_width_mm=fabric_width_mm,
    )
    if existing is not None:
        return {
            "id": existing.id,
            "timestamp": existing.timestamp,
            "duration_ms": existing.duration_ms,
            "placements": existing.placements,
            "marker_length_mm": existing.marker_length_mm,
            "utilization_pct": existing.utilization_pct,
        }

    # Clear any stale cancellation flag from a previous run.
    reset_cancellation()

    # Run the CPU-bound layout in a worker thread so other endpoints
    # (notably /cancel-layout, /ping) stay responsive while it runs.
    def _do_layout():
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

    wall_now = time.time()
    copies = int(body.get("copies", 1))
    entry = CachedLayout(
        id=uuid.uuid4().hex,
        filename=filename,
        timestamp=datetime.fromtimestamp(wall_now).strftime("%Y%m%d%H%M%S"),
        grain_mode=grain_mode,
        copies=copies,
        fabric_width_mm=fabric_width_mm,
        placements=placements_serialized,
        marker_length_mm=marker_length,
        utilization_pct=utilization,
        duration_ms=duration_ms,
        # Monotonic — used only for FIFO ordering, never displayed.
        # Wall-clock display lives in `timestamp`.
        created_at=time.monotonic(),
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


@app.post("/cancel-layout")
def cancel_layout() -> dict:
    """Signal the in-progress auto-layout (if any) to abort at the next
    piece-placement checkpoint. Returns immediately."""
    request_cancellation()
    return {"ok": True}


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


@app.delete("/layouts", status_code=204)
def clear_layouts() -> Response:
    """Clear ALL cached layouts. Used by the frontend on DXF import to
    discard tabs from the previous import."""
    get_cache().clear()
    return Response(status_code=204)


@app.delete("/layouts/{layout_id}", status_code=204)
def delete_layout(layout_id: str) -> Response:
    """Remove a cached layout (manual tab close from the UI)."""
    if not get_cache().delete(layout_id):
        raise HTTPException(status_code=404, detail="Layout not found")
    return Response(status_code=204)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=False)
