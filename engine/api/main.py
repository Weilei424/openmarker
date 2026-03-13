# OpenMarker engine API
# Local HTTP server that bridges the Tauri frontend to the Python geometry logic.
# Runs on 127.0.0.1:8765 — not exposed to the network.

import dataclasses
import io

import ezdxf
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from core.dxf import parse_dxf
from core.geometry import normalize_piece

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


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=False)
