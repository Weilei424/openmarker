# OpenMarker engine API
# Local HTTP server that bridges the Tauri frontend to the Python geometry logic.
# Runs on 127.0.0.1:8765 — not exposed to the network.

import dataclasses
import io

import ezdxf
import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from core.dxf import parse_dxf
from core.geometry import normalize_piece
from core.layout.heuristic import auto_layout_bbox, auto_layout_polygon
from core.models.piece import BoundingBox, Piece as PieceModel

app = FastAPI(title="OpenMarker Engine", version="0.1.0")

# Allow requests from the Tauri webview (file:// or localhost origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
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
        "pieces": [...],           // Piece objects from /import-dxf
        "fabric_width_mm": 1500,
        "grain_mode": "none",      // "none" | "single" | "bi"
        "grain_direction_deg": 0,  // 0 | 45 | 90 | 135
        "fast_mode": false         // true = bbox mode; false = polygon mode
    }

    Response JSON:
    {
        "placements": [{"piece_id": "...", "x": 0, "y": 0, "rotation_deg": 0}],
        "marker_length_mm": 1234.5,
        "utilization_pct": 82.4
    }
    """
    body = await request.json()

    fabric_width_mm = float(body.get("fabric_width_mm", 1500))
    grain_mode = str(body.get("grain_mode", "none"))
    grain_direction_deg = float(body.get("grain_direction_deg", 0.0))
    fast_mode = bool(body.get("fast_mode", False))

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

    try:
        if fast_mode:
            placements, marker_length, utilization = auto_layout_bbox(
                pieces, fabric_width_mm, grain_mode, grain_direction_deg
            )
        else:
            placements, marker_length, utilization = auto_layout_polygon(
                pieces, fabric_width_mm, grain_mode, grain_direction_deg
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "placements": [
            {"piece_id": pl.piece_id, "x": pl.x, "y": pl.y, "rotation_deg": pl.rotation_deg}
            for pl in placements
        ],
        "marker_length_mm": marker_length,
        "utilization_pct": utilization,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=False)
