"""Separation nesting engine — the "Ultra" quality tier.

Converts pieces to grain-aligned jagua-rs JSON, shells out to the bundled
`sparrow` binary (overlap-and-separate strip nester), then reconstructs and
validates the result into engine Placements. See
docs/superpowers/specs/2026-06-07-separation-engine-phase2-design.md and
docs/superpowers/notes/2026-06-07-jagua-schema.md (axis map).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

import shapely.affinity
from shapely.geometry import Polygon as ShapelyPolygon

from core.models.piece import Piece
from core.layout.cancellation import CancellationError, is_cancelled
from core.layout.clustering import group_pieces_by_base_id
from core.layout.heuristic import (
    Placement,
    auto_layout_polygon,
    _compute_metrics,
    _has_area_overlap,
    _layout_rotations,
    _placed_polygon,
    _polygon_dims,
)
from core.layout.progress import set_progress

_VENDORED = os.path.join(os.path.dirname(__file__), "..", "..", "vendor", "sparrow", "sparrow.exe")


def _resolve_sparrow_path() -> str:
    """Locate the bundled sparrow binary. Search order:
    1. OPENMARKER_SPARROW_PATH env override
    2. vendored engine/vendor/sparrow/sparrow.exe (committed, offline)
    3. PyInstaller bundle dir (sys._MEIPASS — future packaging)
    4. dev build tools/sparrow/target/release/sparrow.exe (walk up to repo root)
    """
    candidates: list[str] = []
    env = os.environ.get("OPENMARKER_SPARROW_PATH")
    if env:
        candidates.append(env)
    candidates.append(os.path.abspath(_VENDORED))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "vendor", "sparrow", "sparrow.exe"))
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidates.append(os.path.join(here, "tools", "sparrow", "target", "release", "sparrow.exe"))
        here = os.path.dirname(here)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "sparrow binary not found. Set OPENMARKER_SPARROW_PATH, or vendor it at "
        "engine/vendor/sparrow/sparrow.exe (see the Phase 2 spec §10)."
    )


@dataclass
class _SepItem:
    index: int
    piece_ids: list[str]         # expanded "__cN" ids, in placement-assignment order
    base_angle: float            # engine pre-rotation reference (engine_set[0])
    emitted: ShapelyPolygon      # grain-aligned + 90deg axis-mapped, origin-normalized
    allowed_offsets: list[float] # jagua allowed_orientations = engine_set - base_angle


def _emit_shape(piece: Piece, base_angle: float) -> ShapelyPolygon:
    """Grain-align (base) + 90deg axis swap; origin-normalize bbox-min -> (0,0)."""
    poly = shapely.affinity.rotate(
        ShapelyPolygon(piece.polygon), base_angle + 90.0, origin=(0, 0), use_radians=False)
    minx, miny = poly.bounds[0], poly.bounds[1]
    return shapely.affinity.translate(poly, xoff=-minx, yoff=-miny)


def _group_to_items(pieces: list[Piece], grain_mode: str, fabric_grain_deg: float) -> list[_SepItem]:
    """Collapse expanded pieces to base groups and build one jagua item per group.

    allowed_offsets follows the grain table (single -> [0]; bi -> [0,180];
    no-grainline -> [0,90,180,270]) by re-expressing _layout_rotations relative
    to base_angle. base_angle (= engine_set[0]) is folded into the final rotation
    on reconstruction, so net engine rotation lands exactly in the engine set.
    """
    groups = group_pieces_by_base_id(pieces)
    items: list[_SepItem] = []
    for index, members in enumerate(groups.values()):
        rep = members[0]
        engine_set = _layout_rotations(grain_mode, fabric_grain_deg, rep.grainline_direction_deg)
        base = engine_set[0]
        items.append(_SepItem(
            index=index,
            piece_ids=[p.id for p in members],
            base_angle=base,
            emitted=_emit_shape(rep, base),
            allowed_offsets=[round((a - base) % 360.0, 6) for a in engine_set],
        ))
    return items


def _instance_json(items: list[_SepItem], strip_height: float, name: str = "openmarker") -> dict:
    return {
        "name": name,
        "strip_height": float(strip_height),
        "items": [
            {
                "id": it.index,
                "demand": len(it.piece_ids),
                "allowed_orientations": [float(o) for o in it.allowed_offsets],
                "shape": {
                    "type": "simple_polygon",
                    "data": [[float(x), float(y)] for x, y in it.emitted.exterior.coords[:-1]],
                },
            }
            for it in items
        ],
    }


def _reconstruct(solution: dict, items: list[_SepItem], fabric_width_mm: float) -> list[Placement]:
    """Invert the axis map and build engine Placements.

    For each placed copy: rebuild its jagua-frame polygon (rotate emitted by r,
    translate by t), rotate the WHOLE layout by -90deg (axis-swap inverse), then
    shift bbox-min -> (0, 0). rotation_deg = (base + r) lands exactly
    in the engine grain set; (x, y) = rotated-bbox-min so the existing
    _placed_polygon reproduces the polygon for metrics/validation/render.
    """
    by_index = {it.index: it for it in items}
    counters: dict[int, int] = {it.index: 0 for it in items}
    raw: list[tuple[str, float, ShapelyPolygon]] = []  # (piece_id, rotation_deg, engine_poly)
    for pi in solution["solution"]["layout"]["placed_items"]:
        it = by_index[pi["item_id"]]
        r = float(pi["transformation"]["rotation"]) % 360.0
        t = pi["transformation"]["translation"]
        jpoly = shapely.affinity.translate(
            shapely.affinity.rotate(it.emitted, r, origin=(0, 0), use_radians=False),
            xoff=float(t[0]), yoff=float(t[1]))
        # -90 inverts the +90 axis-swap from _emit_shape (jagua X=length -> engine Y;
        # jagua Y=fabric width -> engine X). base stays folded into rotation_deg below.
        epoly = shapely.affinity.rotate(jpoly, -90.0, origin=(0, 0), use_radians=False)
        j = counters[it.index]
        counters[it.index] += 1
        raw.append((it.piece_ids[j], round((it.base_angle + r) % 360.0, 6), epoly))

    if not raw:
        return []
    dx = -min(p.bounds[0] for _, _, p in raw)
    dy = -min(p.bounds[1] for _, _, p in raw)
    placements: list[Placement] = []
    for piece_id, rotation_deg, epoly in raw:
        shifted = shapely.affinity.translate(epoly, xoff=dx, yoff=dy)
        placements.append(Placement(piece_id, round(shifted.bounds[0], 4),
                                    round(shifted.bounds[1], 4), rotation_deg))
    return placements


def _validate_layout(placements: list[Placement], pieces: list[Piece], fabric_width_mm: float,
                     grain_mode: str, fabric_grain_deg: float, tol_deg: float = 0.6) -> None:
    """Re-assert the hard constraints in OUR frame. Raises ValueError listing the
    first violations: off-grain rotation, area-overlap (>0.5 mm^2), out-of-fabric,
    or incomplete coverage. The axis/orientation backstop the spec mandates."""
    issues: list[str] = []
    piece_map = {p.id: p for p in pieces}
    if len(placements) != len(pieces):
        issues.append(f"placed {len(placements)} of {len(pieces)} pieces")

    placed: list[tuple[Placement, ShapelyPolygon]] = []
    for pl in placements:
        piece = piece_map.get(pl.piece_id)
        if piece is None:                       # unknown id -> clean ValueError, not KeyError
            issues.append(f"{pl.piece_id}: unknown piece_id")
            continue
        allowed = _layout_rotations(grain_mode, fabric_grain_deg, piece.grainline_direction_deg)
        # circular distance: min angular gap to an allowed rotation, wrapping at 360
        if not any(abs(((pl.rotation_deg - a + 180.0) % 360.0) - 180.0) <= tol_deg for a in allowed):
            issues.append(f"{pl.piece_id}: off-grain rotation {pl.rotation_deg} (allowed {allowed})")
        poly = _placed_polygon(piece, pl.x, pl.y, pl.rotation_deg)
        b = poly.bounds
        if b[0] < -0.5 or b[2] > fabric_width_mm + 0.5 or b[1] < -0.5:
            issues.append(f"{pl.piece_id}: outside fabric bounds {tuple(round(v, 1) for v in b)}")
        placed.append((pl, poly))

    n = len(placed)
    for i in range(n):
        bi = placed[i][1].bounds
        for j in range(i + 1, n):
            bj = placed[j][1].bounds
            if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                continue
            if _has_area_overlap(placed[i][1], placed[j][1]):
                issues.append(f"overlap: {placed[i][0].piece_id} & {placed[j][0].piece_id}")
                break
        if len(issues) > 8:
            break

    if issues:
        raise ValueError("separation layout invalid: " + "; ".join(issues[:6]))


# --- subprocess + cancellation plumbing ---
_sparrow_lock = threading.Lock()
_current_sparrows: "set[subprocess.Popen]" = set()


def _register_sparrow(proc) -> None:
    with _sparrow_lock:
        _current_sparrows.add(proc)


def _unregister_sparrow(proc) -> None:
    with _sparrow_lock:
        _current_sparrows.discard(proc)


def kill_current_sparrow() -> None:
    """Terminate ALL in-flight sparrow children (called by /cancel-layout).
    No-op if none. Kills every concurrent best-of-N attempt."""
    with _sparrow_lock:
        procs = list(_current_sparrows)
    for proc in procs:
        try:
            proc.terminate()
        except Exception:
            pass


def _run_sparrow(instance: dict, budget_s: float, seed: int) -> dict:
    """Write the instance, run sparrow in a scratch dir, return the parsed output.

    Raises CancellationError if /cancel-layout killed the child; ValueError on a
    genuine sparrow failure or missing output (with the stderr tail for diagnosis).
    """
    exe = _resolve_sparrow_path()
    with tempfile.TemporaryDirectory() as td:
        ipath = os.path.join(td, "inst.json")
        with open(ipath, "w", encoding="utf-8") as f:
            json.dump(instance, f)
        # stderr -> a scratch file (not PIPE): a long run can log verbosely; a file
        # avoids both pipe-buffer deadlock and unbounded in-memory capture.
        log_path = os.path.join(td, "sparrow.stderr.log")
        with open(log_path, "wb") as logf:
            proc = subprocess.Popen(
                [exe, "-i", ipath, "-t", str(int(budget_s)), "-s", str(int(seed))],
                cwd=td, stdout=subprocess.DEVNULL, stderr=logf)
            _register_sparrow(proc)
            try:
                # Close the tiny race where cancel lands between Popen and registration.
                if is_cancelled():
                    proc.terminate()
                proc.wait()
            finally:
                _unregister_sparrow(proc)
        if is_cancelled():
            raise CancellationError("sparrow run cancelled")
        if proc.returncode != 0:
            tail = ""
            try:
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    tail = f.read()[-500:].strip()
            except OSError:
                pass
            raise ValueError(f"sparrow exited with code {proc.returncode}: {tail}")
        outdir = os.path.join(td, "output")
        finals = ([x for x in os.listdir(outdir) if x.startswith("final_") and x.endswith(".json")]
                  if os.path.isdir(outdir) else [])
        if not finals:
            raise ValueError("sparrow produced no output")
        with open(os.path.join(outdir, finals[0]), encoding="utf-8") as f:
            return json.load(f)


def _solve_one(items: list[_SepItem], instance: dict, pieces: list[Piece],
               fabric_width_mm: float, grain_mode: str, fabric_grain_deg: float,
               budget_s: float, seed: int) -> tuple[list[Placement], float, float]:
    """One sparrow attempt: run -> reconstruct -> validate -> metrics. Raises
    CancellationError on kill, ValueError on invalid/empty output."""
    solution = _run_sparrow(instance, budget_s, seed)
    placements = _reconstruct(solution, items, fabric_width_mm)
    _validate_layout(placements, pieces, fabric_width_mm, grain_mode, fabric_grain_deg)
    marker_length, utilization = _compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims)
    return placements, marker_length, utilization


def _placements_to_jagua(items: list[_SepItem], pieces: list[Piece],
                         placements: list[Placement], marker_len: float) -> list[dict]:
    """Inverse of `_reconstruct`: engine Placements -> jagua `placed_items` (warm start).

    Each engine placed polygon is rotated +90deg into jagua's axis frame and shifted
    by `marker_len` in x so the layout occupies x in [0, marker_len] (jagua minimizes
    x). Per copy: rotation offset r = (rotation_deg - base_angle) % 360; translation
    from the untransformed `emitted` shape's vertex correspondence. Raises ValueError
    if the mapping is not a pure translation (axis-map regression guard)."""
    piece_map = {p.id: p for p in pieces}
    item_by_pid = {pid: it for it in items for pid in it.piece_ids}
    placed: list[dict] = []
    for pl in placements:
        it = item_by_pid[pl.piece_id]
        piece = piece_map[pl.piece_id]
        r = round((pl.rotation_deg - it.base_angle) % 360.0, 6)
        epoly = _placed_polygon(piece, pl.x, pl.y, pl.rotation_deg)
        jpoly = shapely.affinity.translate(
            shapely.affinity.rotate(epoly, 90.0, origin=(0, 0), use_radians=False),
            xoff=marker_len, yoff=0.0)
        ref = shapely.affinity.rotate(it.emitted, r, origin=(0, 0), use_radians=False)
        jc, rc = list(jpoly.exterior.coords), list(ref.exterior.coords)
        tx, ty = jc[0][0] - rc[0][0], jc[0][1] - rc[0][1]
        worst = max(abs(jx - (rx + tx)) + abs(jy - (ry + ty))
                    for (jx, jy), (rx, ry) in zip(jc, rc))
        if worst > 1e-2:
            raise ValueError(f"warm-start vertex correspondence broke for {pl.piece_id}: {worst}")
        placed.append({"item_id": it.index,
                       "transformation": {"rotation": float(r), "translation": [float(tx), float(ty)]}})
    return placed


def _build_warm_start(items: list[_SepItem], pieces: list[Piece], fabric_width_mm: float,
                      grain_mode: str, fabric_grain_deg: float) -> dict | None:
    """Seed sparrow from a Fast-tier NFP-BLF layout (passed via `-i` as an ExtSPSolution).

    Returns the solution dict, or None on any failure (caller falls back to a cold
    start). sparrow can only IMPROVE a valid seed and discards a poor one, so this is
    pure upside: on the canonical homogeneous workload it injects the repeating
    garment-row structure sparrow cannot discover on its own (-74mm matched-seed,
    first sub-commercial markers); on workloads where the Fast layout has no useful
    structure it measures neutral. See PERFORMANCE.md §6 [2026-06-12 round 2]."""
    try:
        placements, marker, _util = auto_layout_polygon(
            pieces, fabric_width_mm, grain_mode, fabric_grain_deg, effort=1)
        placed_items = _placements_to_jagua(items, pieces, placements, marker)
    except CancellationError:
        raise                       # Stop during the prelude cancels the whole run
    except Exception:
        return None                 # best-effort: never let warm start break Ultra
    return {
        "strip_width": float(marker) + 1.0,   # +1mm slack so the seed strip is feasible
        "layout": {"container_id": 0, "placed_items": placed_items, "density": 0.0},
        "density": 0.0,
        "run_time_sec": 0,
    }


def run_separation_layout(pieces: list[Piece], fabric_width_mm: float, grain_mode: str,
                          fabric_grain_deg: float, budget_s: float, seed: int = 42,
                          n_seeds: int = 1, warm_start: bool = True) -> tuple[list[Placement], float, float]:
    """Run the separation (sparrow) engine. With n_seeds>1, run that many members
    (seeds seed..seed+n_seeds-1) SEQUENTIALLY — one 3-thread sparrow process at a
    time, each with the full `budget_s` (the configuration validated in PR #23) —
    and keep the shortest VALID marker. Mirrors auto_layout_polygon's return.

    Cancellation (Stop): the in-flight member is killed; if at least one member
    already COMPLETED, its best result is RETURNED — the caller reads
    core.layout.progress for `stopped_early`/`members_completed`. With no
    completed member, raises CancellationError (->499). ValueError on empty
    input or when every member is invalid (->400).

    Progress: a snapshot is written at every member start and a FINAL snapshot
    (`active: False`, counts preserved, `stopped_early` set) on every exit path;
    the run never clears it — the next run overwrites. Single-flight by design
    (the app has one global cancel flag and runs one layout at a time).

    With warm_start=True (default) sparrow is seeded from a Fast-tier NFP-BLF
    layout (built ONCE, shared by all members); a Fast-layout failure degrades
    gracefully to a cold start. See PERFORMANCE.md §6 [2026-06-12 round 2] +
    [2026-07-10]."""
    if not pieces:
        raise ValueError("no pieces to lay out")
    items = _group_to_items(pieces, grain_mode, fabric_grain_deg)
    instance = _instance_json(items, fabric_width_mm)
    if warm_start:
        ws = _build_warm_start(items, pieces, fabric_width_mm, grain_mode, fabric_grain_deg)
        if ws is not None:
            instance = {**instance, "solution": ws}   # sparrow reads this as ExtSPOutput -> warm start
    seeds = [seed + k for k in range(max(1, n_seeds))]

    best: tuple[list[Placement], float, float] | None = None
    errors: list[str] = []
    cancelled = False
    completed = 0
    last_member = 0
    run_started = time.time()
    for k, s in enumerate(seeds, start=1):
        last_member = k
        set_progress(active=True, member=k, n_members=len(seeds),
                     members_completed=completed,
                     best_marker_mm=best[1] if best is not None else None,
                     budget_s=float(budget_s), run_started_ts=run_started,
                     member_started_ts=time.time(), stopped_early=False)
        try:
            result = _solve_one(items, instance, pieces, fabric_width_mm,
                                grain_mode, fabric_grain_deg, budget_s, s)
        except CancellationError:
            cancelled = True
            break
        except ValueError as e:
            errors.append(str(e))
            continue
        completed += 1
        if best is None or result[1] < best[1]:
            best = result
    # Final snapshot on EVERY exit path — the API reads the outcome from it
    # right after this call returns/raises.
    set_progress(active=False, member=last_member, n_members=len(seeds),
                 members_completed=completed,
                 best_marker_mm=best[1] if best is not None else None,
                 budget_s=float(budget_s), run_started_ts=run_started,
                 member_started_ts=time.time(),
                 stopped_early=cancelled and best is not None)
    if cancelled and best is None:
        raise CancellationError("separation run cancelled")
    if best is None:
        raise ValueError("all separation attempts invalid: " + "; ".join(errors[:3]))
    return best
