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
from core.layout.progress import get_progress
from core.layout.separation import run_separation_layout
from core.layout.grain import FABRIC_GRAIN_DEG
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


# Optimizer quality tiers -> GA knobs (see
# docs/superpowers/specs/2026-06-06-expose-optimizer-gui-design.md).
# "fast" runs no meta-heuristic (today's warm-start). "better"/"best" run the
# island-model GA with a wall-clock budget. "ultra" runs the separation engine
# (bundled sparrow sidecar) at a 600s budget. Budgets validated by
# engine/tests/bench_optimizer_tiers.py + bench_separation.py.
VALID_QUALITIES = ("fast", "better", "best", "ultra")
GA_GENERATIONS_CAP = 12        # generation cap; binds on small jobs, time binds on big
GA_GUI_SEED = 42               # fixed -> deterministic per (input, quality)
OPTIMIZED_EFFORT = 4           # "all but one core": more islands, machine stays usable
QUALITY_BUDGETS_S = {"better": 180.0, "best": 420.0, "ultra": 600.0}
# Ultra warm-start (Fast-tier seed via sparrow -i) wins only with enough compression
# budget: tie at 180s, -0.37% at 360s, -1.11% at 600s. Below this floor the Fast-layout
# prelude costs wall time for no marker gain, so keep the sub-360s "fast" runs cold.
# See PERFORMANCE.md §6 [2026-06-12 round 2].
WARM_START_MIN_BUDGET_S = 360.0


@app.post("/auto-layout")
async def auto_layout_endpoint(request: Request) -> dict:
    """
    Run heuristic auto-layout on provided pieces.

    Request JSON:
    {
        "pieces": [...],            // Piece objects from /import-dxf
        "fabric_width_mm": 1500,
        "grain_mode": "single",     // "single" | "bi"
        "grain_direction_deg": 0,   // IGNORED — grain is locked at 90° (FABRIC_GRAIN_DEG)
        "filename": "...",          // required
        "copies": 1,                // optional, defaults to 1
        "disable_nfp_cache": false, // optional, A/B benchmark toggle
        "effort": 1,                // optional, 1=serial..5=all cores; ignored for better/best (forced to 4) and ultra
        "max_cache_entries": 5,     // optional, 5..20; sets FIFO cap before dedup check
        "quality": "fast",          // optional: "fast" | "better" | "best" | "ultra"; better/best run GA, ultra runs sparrow
    }

    Response JSON:
    {
        "id": "...",                // Phase 6: cache entry id (UUID hex)
        "timestamp": "...",         // Phase 6: YYYYMMDDHHMMSS
        "duration_ms": 1234,        // Phase 6: layout duration
        "placements": [{"piece_id": "...", "x": 0, "y": 0, "rotation_deg": 0}],
        "marker_length_mm": 1234.5,
        "utilization_pct": 82.4,
        // quality="ultra" only (sequential best-of-N, spec 2026-07-12):
        "stopped_early": false,     // True if Stop cut the run short (best-so-far kept)
        "members_completed": 3,     // seeds actually run before returning
        "members_requested": 3      // ultra_seeds as requested
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
    disable_nfp_cache = bool(body.get("disable_nfp_cache", False))
    effort = int(body.get("effort", 1))
    if effort < 1 or effort > 5:
        raise HTTPException(status_code=422, detail=f"`effort` must be between 1 and 5, got {effort}")

    quality = str(body.get("quality", "fast"))
    if quality not in VALID_QUALITIES:
        raise HTTPException(
            status_code=422,
            detail=f"`quality` must be one of {VALID_QUALITIES}, got {quality!r}",
        )

    ultra_budget_s = body.get("ultra_budget_s", QUALITY_BUDGETS_S["ultra"])
    try:
        ultra_budget_s = float(ultra_budget_s)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="`ultra_budget_s` must be a number")
    if ultra_budget_s < 180 or ultra_budget_s > 2500:
        raise HTTPException(
            status_code=422,
            detail=f"`ultra_budget_s` must be 180..2500, got {ultra_budget_s}",
        )
    try:
        ultra_seeds = int(body.get("ultra_seeds", 1))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="`ultra_seeds` must be an integer")
    if ultra_seeds < 1 or ultra_seeds > 4:
        raise HTTPException(
            status_code=422,
            detail=f"`ultra_seeds` must be 1..4, got {ultra_seeds}",
        )

    # TEMP(phase6-bench): when True, dedup key also includes the effort level,
    # so the same settings run at different effort levels produce distinct entries.
    include_effort_in_key = bool(body.get("include_effort_in_key", False))

    max_cache_entries = body.get("max_cache_entries")
    if max_cache_entries is not None:
        try:
            max_cache_entries = int(max_cache_entries)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="`max_cache_entries` must be an integer")
        if max_cache_entries < 5 or max_cache_entries > 20:
            raise HTTPException(
                status_code=422,
                detail=f"`max_cache_entries` must be 5..20, got {max_cache_entries}",
            )
        get_cache().set_max_entries(max_cache_entries)

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
        quality=quality,
        effort=effort if include_effort_in_key else None,  # TEMP(phase6-bench)
        ultra_budget_s=ultra_budget_s,
        ultra_seeds=ultra_seeds,
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
        if quality == "fast":
            return auto_layout_polygon(
                pieces, fabric_width_mm, grain_mode, FABRIC_GRAIN_DEG,
                disable_nfp_cache=disable_nfp_cache,
                effort=effort,
            )
        if quality == "ultra":
            return run_separation_layout(
                pieces, fabric_width_mm, grain_mode, FABRIC_GRAIN_DEG,
                budget_s=ultra_budget_s, seed=GA_GUI_SEED, n_seeds=ultra_seeds,
                warm_start=ultra_budget_s >= WARM_START_MIN_BUDGET_S,
            )
        # better / best: island-model GA with a wall-clock budget. effort is
        # forced to OPTIMIZED_EFFORT (all-but-one core) for more GA islands.
        return auto_layout_polygon(
            pieces, fabric_width_mm, grain_mode, FABRIC_GRAIN_DEG,
            disable_nfp_cache=disable_nfp_cache,
            effort=OPTIMIZED_EFFORT,
            ga_generations=GA_GENERATIONS_CAP,
            ga_max_time_s=QUALITY_BUDGETS_S[quality],
            ga_seed=GA_GUI_SEED,
        )

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

    # Ultra: the run's final progress snapshot carries the stop outcome
    # (sequential best-of-N, spec 2026-07-12). Defaults cover stubbed tests.
    stopped_early = False
    members_completed = ultra_seeds
    if quality == "ultra":
        snap = get_progress()
        stopped_early = bool(snap.get("stopped_early", False))
        members_completed = int(snap.get("members_completed", ultra_seeds))

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
        quality=quality,
        ultra_budget_s=ultra_budget_s,
        # Truthful key: a stop after k of N members IS the best-of-k artifact
        # (same seeds 42..42+k-1 a real best-of-k run uses) — cache it as such
        # so the requested-N key stays free for a full re-run.
        ultra_seeds=members_completed if (quality == "ultra" and stopped_early) else ultra_seeds,
    )
    # TEMP(phase6-bench): tag the entry with the effort level used to compute it,
    # so future lookups with include_effort_in_key=True can find it.
    # CachedLayout is a (non-frozen) @dataclass so a dynamic attribute is allowed.
    if include_effort_in_key:
        entry._bench_effort = effort
    get_cache().insert(entry)

    return {
        "id": entry.id,
        "timestamp": entry.timestamp,
        "duration_ms": entry.duration_ms,
        "placements": placements_serialized,
        "marker_length_mm": marker_length,
        "utilization_pct": utilization,
        **({"stopped_early": stopped_early,
            "members_completed": members_completed,
            "members_requested": ultra_seeds} if quality == "ultra" else {}),
    }


@app.post("/cancel-layout")
def cancel_layout() -> dict:
    """Signal the in-progress auto-layout (if any) to abort at the next
    piece-placement checkpoint AND terminate any parallel workers immediately."""
    request_cancellation()
    # Parallel-mode kill: terminates ProcessPoolExecutor children so workers
    # don't run to completion when the user clicks Stop. Local import keeps
    # the top-level imports tidy; called only on the one-shot cancel path.
    from core.layout.heuristic import kill_current_executor
    kill_current_executor()
    from core.layout.separation import kill_current_sparrow
    kill_current_sparrow()
    return {"ok": True}


@app.get("/layout-progress")
def layout_progress() -> dict:
    """Current layout-run progress snapshot (single-flight; see core.layout.progress).
    Adds server-computed elapsed fields while a run is active."""
    snap = get_progress()
    if snap.get("active"):
        now = time.time()
        snap["total_elapsed_s"] = round(now - snap["run_started_ts"], 1)
        snap["member_elapsed_s"] = round(now - snap["member_started_ts"], 1)
    return snap


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
