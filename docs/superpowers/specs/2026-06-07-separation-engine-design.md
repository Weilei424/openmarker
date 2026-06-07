# Separation Engine — evaluation & integration (overlap-and-separate / `sparrow`)

> Design spec. Status: **draft for review.** Owner: engine.
> Related: `docs/planning/PERFORMANCE.md` § 5.B + § 6 [2026-06-07].

## 1. Context & problem

OpenMarker's nesting is a constructive **NFP-BLF** packer wrapped by **GA/SA**
meta-heuristics that optimize *piece ordering* + *grain choice*. On the canonical
workload (`sample_2.dxf × 10`, fabric 1651 mm, bi-grain @90°) GA reaches
**11412 mm / 81.39%**, beating the historical bar (11699 mm) by ~2.5%. The
commercial reference is **10599 mm / 86.1%** — ~7% better still.

GA has **stalled**: the ordering axis is near-maxed, and the 2026-06-07
investigation proved every "refine the BLF output" lever is a dead end —
**compaction (greedy and LP) both recovered ≈0** on every workload/baseline
(PERFORMANCE.md § 6), because BLF already sits at a tight local optimum and
local refinement can't change *which piece goes where*.

The literature points to one paradigm with real headroom: **overlap-and-separate
local search** (Umetani–Yagiura 2009 → `sparrow` 2025, the academic SOTA for 2D
irregular **strip** packing — our exact problem). Instead of placing pieces
one-by-one, it drops all pieces into a too-short strip (overlaps allowed) and
runs an overlap-minimizing local search with Guided Local Search to resolve them,
shrinking the strip toward feasibility. This explores *fundamentally different
arrangements* rather than polishing BLF.

`sparrow` is **MIT-licensed** (Apache-compatible), built in **Rust** on the
**MPL-2.0** `jagua-rs` collision engine.

## 2. Goals & success metric

- **Primary:** determine whether overlap-and-separate beats GA on *our* garment
  workloads, then — if it does — ship it as a GUI-accessible layout option.
- **Gate metric (binding):** on `sample_2.dxf × 10`, the separation engine must
  produce a **valid** marker (grain respected, no overlaps, within usable width)
  of **≤ 11070 mm (≥ 3% better than GA's 11412)** within a ≤ 600 s budget.
  Approaching the commercial 10599 mm is aspirational, not required.
- **Performance is why production = Rust, not Python.** Overlap-and-separate is
  collision-query-heavy in a tight loop; a Python reimplementation would be too
  slow. We evaluate and ship the **Rust** engine directly.

## 3. Non-goals

- Not replacing NFP-BLF / GA — separation is an *additional* engine.
- Not a from-scratch Python nesting engine (perf) and not a from-scratch Rust one
  (`sparrow` exists). If `jagua-rs` can't express grain we reconsider (§ 8).
- No continuous-rotation nesting — grain locks every piece to `{0°, 180°}`.
- No change to DXF import, the Konva canvas, or export (Phase 7).

## 4. Gating philosophy

This is a large build pointed at an *unproven-on-our-data* hypothesis (the SOTA
numbers are on non-garment academic datasets — not cross-comparable to our
81.39%). So we **measure with the real engine before integrating**, exactly as
the compaction spike saved a week. Three phases, each with a hard gate; we only
spend Phase-N effort if Phase-(N−1) cleared its gate.

## 5. Phase 0 — Feasibility: can `sparrow` express our grain constraint? (hours)

Grain is a **hard manufacturing constraint**: each piece is locked to `{0°, 180°}`
(no mirror/flip). If `sparrow`'s raw output rotates pieces off-grain or mirrors
them, the marker is *physically invalid*, not merely suboptimal. `jagua-rs`
advertises *continuous* rotation, so this is a **gate, not an assumption.**

**Planned reduction:** pre-rotate each piece so its grainline is already aligned
to the fabric warp, then ask `sparrow` for only a **global `{0°, 180°}` discrete
orientation set with flipping disabled**. This turns per-piece grain targets into
a single uniform allowed set.

**Tasks**
- Inspect the `jagua-rs` JSON schema (repo `assets/` examples, `rustdoc`) for
  per-instance orientation control and flip control. Confirm `{0,180}` + no-flip
  is expressible.
- Build `sparrow` (`cargo build --release`) using the Rust toolchain the Tauri
  shell already requires.
- Run a hand-built 2–3 piece instance with the `{0,180}` set; verify the output
  uses only `0°/180°` and never mirrors.

**Gate:** grain is expressible and verified on the toy case.
**If it fails:** STOP and reconsider — fork `jagua-rs` (MPL-2.0 permits) to add an
orientation constraint, or fall back to a Python overlap-min reimplementation
(slow, opt-in only). Document the decision; do not proceed to Phase 1 assuming it.

## 6. Phase 1 — Measure the ceiling on our workload (~1 day)

**Tasks**
- Python converter `pieces → jagua-rs JSON`: grain-aligned pre-rotation, strip
  width 1651 mm, per-item polygon (exterior ring), demand = copies, global
  `{0,180}` orientations, flip off. Cover `sample_2 ×10`, `sample_3 ×6`,
  `sample_4 ×6`.
- Run `sparrow -i instance.json -t <budget>` at several budgets (e.g. 60 / 180 /
  420 / 600 s) to capture the **quality-vs-time curve** (informs the GUI budget).
- Parse `sparrow`'s output JSON (per-item rotation + translation) → reconstruct
  placements in our engine convention → **validate** (grain `∈ {0,180}`, no
  area-overlap at 0.5 mm² via `_has_area_overlap`, within `[EDGE_GAP, W−EDGE_GAP]`)
  → compute marker length / util via `_compute_metrics`.
- Record the gate result + runtime for each workload.

**Gate:** `sample_2 ×10` marker **≤ 11070 mm (≥3% < GA)**, valid, within ≤ 600 s.
**If it fails:** separation does not beat GA on garment pieces — document in
PERFORMANCE.md and **stop** (cheaply, using the actual SOTA). Do **not** build
Phase 2.

**Deliverable:** a measurement script (throwaway, like the compaction spikes) +
a PERFORMANCE.md § 6 entry with the numbers and the go/no-go decision.

## 7. Phase 2 — Productionize end-to-end (only if Phase 1 clears the gate)

Per the product decision, the GUI has access **beginning to end** — unlike SA/GA
(which stayed engine-only). The deliverable is: *user imports a DXF, picks the
separation option, gets a valid marker rendered on the canvas, and can export it.*

### 7.1 Architecture — `sparrow` as a bundled sidecar binary

```
GUI (QualityPanel: + "Ultra")
  └─HTTP─► FastAPI /auto-layout (quality="ultra")
             ├─ parse DXF → pieces            (existing)
             ├─ core/layout/separation.py:
             │    pieces → grain-aligned → jagua-rs JSON
             │    subprocess: sparrow -i in.json -t <budget> -s <seed> -o out/
             │    parse out.json → placements (engine convention)
             │    validate (grain / overlap / width) + _compute_metrics
             ├─ cache (quality key already includes "ultra")
             └─ placements ─► Konva render ─► export (Phase 7)
```

- **New module** `engine/core/layout/separation.py`: JSON build, subprocess
  invocation (in the existing `run_in_threadpool` worker), output parse, the
  pre-rotation round-trip, and validation. Reuses `_placed_polygon`,
  `_compute_metrics`, `_has_area_overlap`.
- **API:** `POST /auto-layout` maps `quality="ultra"` → the separation path (the
  `quality` field + cache dedup key already exist from the GA-GUI PR). Budget from
  a new `QUALITY_BUDGETS_S["ultra"]` informed by the Phase-1 time curve.
- **Cancellation:** `/cancel-layout` terminates the `sparrow` child process
  (mirrors `kill_current_executor`); translate to `CancellationError`.
- **Determinism / cache:** invoke with a fixed `-s` seed so identical requests are
  reproducible and cacheable.
- **Frontend:** `QualityPanel` gains an **"Ultra"** option (alongside
  Fast/Better/Best); existing elapsed timer + progress bar + placement rendering
  are reused unchanged. End-to-end import → Ultra → render → export.
- **Packaging (offline Windows):** bundle the `sparrow.exe` (Windows x64,
  `cargo build --release`) as a Tauri sidecar / engine-relative binary; the engine
  locates and shells out to it. Ships with the app — no network. Build step adds a
  `cargo build` for the sidecar; PyInstaller bundles the engine as today.

### 7.2 Domain handling (grain)

The pre-rotation + `{0,180}` + no-flip reduction (Phase 0) is enforced at JSON
build time; the output validator re-asserts grain on every returned placement.
Any off-grain or mirrored placement is a **hard failure** (reject the result,
surface an error) — never silently rendered.

## 8. Risks & open questions

| Risk | Mitigation |
|---|---|
| `jagua-rs` can't pin orientation to `{0,180}` / disable flip | Phase 0 gate; fallback = fork `jagua-rs` (MPL-2.0) or Python reimpl |
| `sparrow` doesn't beat GA by ≥3% on garment pieces | Phase 1 gate; stop cheaply if so |
| 600 s feels slow in a GUI | Phase-1 time curve sets a sane "Ultra" budget; it's still cancellable; "Best" already runs 420 s |
| Pre-rotation ↔ engine-placement round-trip bugs | Unit tests on the transform round-trip; the output validator is the backstop |
| Sidecar packaging weight / build complexity | Rust binary is a few MB; Tauri already builds Rust |
| `jagua-rs` numeric tolerances vs our 0.5 mm² | Validate every placement; small offending overlaps → reject |

## 9. Testing

- **Phase 0/1:** validation scripts (grain / overlap / width) like the compaction
  spikes; quality-vs-time table.
- **Phase 2:** unit tests for JSON conversion, output parsing, and the
  pre-rotation round-trip; an integration test for the sidecar path (run
  `sparrow` on a tiny instance, or stub it); a bench comparing Ultra vs GA on the
  canonical workloads; cancellation test.

## 10. Acceptance criteria

- **Phase 1:** documented measurement + go/no-go recorded in PERFORMANCE.md.
- **Phase 2 (if built):** from the GUI, a user imports a DXF, selects **Ultra**,
  and gets a **valid** marker (grain-respecting, overlap-free, within width)
  **≥ 3% shorter than GA** on the canonical workloads, fully **offline**,
  **cancellable**, and **cached** — and can export it via the Phase 7 flow.

## 11. References

- Umetani, Yagiura et al. 2009 — GLS overlap-minimization for irregular strip packing (ITOR).
- `sparrow` (MIT) — github.com/JeroenGar/sparrow; paper arXiv:2509.13329 (2025).
- `jagua-rs` (MPL-2.0) — github.com/JeroenGar/jagua-rs.
- Li & Milenkovic 1995 — compaction/separation for marker making (EJOR 84(3)); the
  *separation* half is the classical root of this paradigm.
- PERFORMANCE.md § 5.B (candidate row) + § 6 [2026-06-07] (compaction-shelved finding).
