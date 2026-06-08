"""Phase 1 measurement: run sparrow (Rust SOTA nester) on our workload and
compare the achieved marker length to GA's 11412.5.

Lean end-to-end eval (NOT the full TDD module suite) — the deliverable is the
go/no-go number. Schema + axis mapping: docs/superpowers/notes/2026-06-07-jagua-schema.md.

Axis map: jagua-rs fixes `strip_height` (Y) and minimizes `strip_width` (X); we
fix fabric width and minimize length. So each piece is rotated to grain-aligned
(`_layout_rotations` target) + 90deg so its cross-grain WIDTH lands on jagua's Y
(<= fabric width) and grain runs along the minimized X. allowed_orientations
[0,180] gives the bi-grain flip. (Sign of the +90 is irrelevant: {t+90,t-90}.)

    ...python.exe engine\\tests\\bench_sparrow.py [--sample S --copies N --budget SECS]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

import shapely.affinity
from shapely.geometry import Polygon as SPoly

from core.layout.grain import FABRIC_GRAIN_DEG
from core.layout.heuristic import EDGE_GAP, _has_area_overlap, _layout_rotations

FABRIC = 1651.0
GA_REF = 11412.5
GATE = 11070.0  # >=3% under GA
SPARROW = os.path.abspath(os.path.join(HERE, "..", "..", "tools", "sparrow", "target", "release", "sparrow.exe"))


def _find(sample: str) -> str | None:
    here = os.path.abspath(HERE)
    for _ in range(8):
        c = os.path.join(here, "examples", "input", sample)
        if os.path.isfile(c):
            return c
        here = os.path.dirname(here)
    return None


def _load(sample: str, copies: int):
    from dataclasses import replace
    from core.dxf import parse_dxf
    from core.geometry import normalize_piece

    path = _find(sample)
    if not path:
        print(f"SKIP: {sample} not found", flush=True)
        sys.exit(0)
    with open(path, "rb") as f:
        raw = parse_dxf(f.read())
    base = []
    for i, r in enumerate(raw):
        try:
            base.append(normalize_piece(r, piece_id=f"piece_{i}"))
        except ValueError:
            pass
    expanded = [replace(b, id=f"{b.id}__c{c}") for c in range(copies) for b in base]
    return expanded, base


def _emit_shape(piece):
    """Grain-align (target) + 90deg axis-swap, origin-normalize. Returns (shapely, ring)."""
    target = _layout_rotations("single", FABRIC_GRAIN_DEG, piece.grainline_direction_deg)[0]
    poly = shapely.affinity.rotate(SPoly(piece.polygon), target + 90.0, origin=(0, 0))
    minx, miny = poly.bounds[0], poly.bounds[1]
    poly = shapely.affinity.translate(poly, xoff=-minx, yoff=-miny)
    ring = [[float(x), float(y)] for x, y in poly.exterior.coords[:-1]]
    return poly, ring


def build_instance(base_pieces, copies, strip_height):
    items, emitted = [], []
    for idx, bp in enumerate(base_pieces):
        shp, ring = _emit_shape(bp)
        items.append({
            "id": idx, "demand": copies,
            "allowed_orientations": [0.0, 180.0],
            "shape": {"type": "simple_polygon", "data": ring},
        })
        emitted.append(shp)
    return {"name": "openmarker", "strip_height": float(strip_height), "items": items}, emitted


def run_sparrow(instance, budget, seed=42):
    with tempfile.TemporaryDirectory() as td:
        ipath = os.path.join(td, "inst.json")
        with open(ipath, "w", encoding="utf-8") as f:
            json.dump(instance, f)
        subprocess.run([SPARROW, "-i", ipath, "-t", str(int(budget)), "-s", str(seed)],
                       cwd=td, check=True, capture_output=True)
        outdir = os.path.join(td, "output")
        finals = [x for x in os.listdir(outdir) if x.startswith("final_") and x.endswith(".json")]
        with open(os.path.join(outdir, finals[0]), encoding="utf-8") as f:
            return json.load(f)


def reconstruct(sol, emitted):
    polys = []
    layout = sol["solution"]["layout"]
    for pi in layout["placed_items"]:
        base = emitted[pi["item_id"]]
        r = float(pi["transformation"]["rotation"])
        t = pi["transformation"]["translation"]
        p = shapely.affinity.rotate(base, r, origin=(0, 0))
        p = shapely.affinity.translate(p, xoff=float(t[0]), yoff=float(t[1]))
        polys.append((p, r % 360))
    return polys, float(sol["solution"]["strip_width"])


def validate(polys, strip_height):
    issues = []
    for _, rn in polys:
        if round(rn) % 180 != 0:
            issues.append(f"off-grain rotation {rn}")
            break
    for p, _ in polys:
        b = p.bounds
        if b[1] < -0.5 or b[3] > strip_height + 0.5:
            issues.append("piece outside strip height (axis-map?)")
            break
    n, ov = len(polys), 0
    for i in range(n):
        bi = polys[i][0].bounds
        for j in range(i + 1, n):
            bj = polys[j][0].bounds
            if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                continue
            if _has_area_overlap(polys[i][0], polys[j][0]):
                ov += 1
    if ov:
        issues.append(f"{ov} overlapping pair(s)")
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="sample_2.dxf")
    ap.add_argument("--copies", type=int, default=10)
    ap.add_argument("--budget", type=int, default=600)
    args = ap.parse_args()

    pieces, base = _load(args.sample, args.copies)
    strip_height = FABRIC - 2 * EDGE_GAP
    inst, emitted = build_instance(base, args.copies, strip_height)
    total_area = sum(p.area for p in pieces)
    print(f"workload {args.sample} x{args.copies}: {len(pieces)} pieces ({len(base)} distinct), "
          f"strip_height={strip_height:.0f}, budget={args.budget}s", flush=True)

    t0 = time.perf_counter()
    sol = run_sparrow(inst, args.budget)
    dt = time.perf_counter() - t0

    polys, strip_width = reconstruct(sol, emitted)
    issues = validate(polys, strip_height)
    xext = max(p.bounds[2] for p, _ in polys) - min(p.bounds[0] for p, _ in polys)
    marker = xext + 2 * EDGE_GAP
    util = total_area / (marker * FABRIC) * 100.0

    print(f"placed={len(polys)}  strip_width={strip_width:.1f}  marker={marker:.1f}mm  "
          f"util={util:.2f}%  time={dt:.1f}s", flush=True)
    print(f"validity: {'PASS' if not issues else 'FAIL: ' + '; '.join(issues[:3])}", flush=True)
    ok = (not issues) and marker <= GATE
    print(f"reference: GA={GA_REF}  gate(<=3%)={GATE}  ->  {'GATE PASS' if ok else 'below gate'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
