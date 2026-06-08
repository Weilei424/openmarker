# Separation engine — Phase 2: productionize sparrow as the "Ultra" tier

> Design spec. Status: **draft for review.** Owner: engine.
> Parent: `docs/superpowers/specs/2026-06-07-separation-engine-design.md` (§7 is Phase 2).
> Schema/axis-map: `docs/superpowers/notes/2026-06-07-jagua-schema.md`.
> Eval/GO: `docs/planning/PERFORMANCE.md` §6 [2026-06-07] + §5.B.

## 1. Context & decision

Phase 0/1 (PR #15) proved the overlap-and-separate paradigm beats our GA on garment
markers: on `sample_2.dxf ×10`, the Rust SOTA strip-nester `sparrow` (MIT, on MPL-2.0
`jagua-rs`) produced a **valid, grain-respecting** marker of **10916.5 mm / 85.08%** vs
GA's 11412.5 / 81.39% (**−4.35%**, clears the ≥3% gate, approaches the commercial 86.1%).
The eval harness `engine/tests/bench_sparrow.py` is the seed for this build.

Phase 2 productionizes that harness end-to-end: **a user imports a DXF, picks "Ultra",
and gets a valid grain-respecting marker rendered and (Phase 7) exportable — fully
offline.** sparrow runs as a bundled sidecar binary the engine shells out to.

## 2. Scope

In:
- New engine module `core/layout/separation.py`: pieces → grain-aligned `jagua-rs` JSON →
  subprocess to a vendored `sparrow.exe` → parse → reconstruct to engine `Placement`s →
  validate → metrics. Same return contract as `auto_layout_polygon`.
- `POST /auto-layout` gains `quality="ultra"`; `/cancel-layout` kills the sparrow child.
- Frontend: `QualityPanel` gains an **Ultra** radio (reuses timer / progress / render).
- Vendoring a prebuilt `sparrow.exe` + an engine-side path resolver (offline Windows).

Out (unchanged): DXF import, the Konva canvas, export (Phase 7), NFP-BLF / GA / SA (Ultra
is an *additional* engine), continuous rotation, and the not-yet-built PyInstaller/Tauri
packaging system (we add a documented hook, not the Phase-8 machinery).

## 3. Settled decisions (brainstorm 2026-06-07)

| Decision | Choice | Rationale |
|---|---|---|
| GUI surface | **4th quality tier** (Fast/Better/Best/**Ultra**) | One "how hard to pack" axis is the simplest mental model for factory users; reuses the existing `quality` field, cache key, timer, progress. The engine swap stays invisible. |
| Binary | **Commit prebuilt `sparrow.exe`** + engine resolver ladder | Always present & offline; runnable/testable now; trivial for a future PyInstaller bundle. Cost: a few-MB binary in git, refreshed on upgrade. |
| Invalid output | **Hard-fail** — surface an error, render nothing | Grain is a hard manufacturing constraint. A validation failure signals a real bug we must see, never silently render. |
| Ultra budget | `QUALITY_BUDGETS_S["ultra"] = 600.0` | Max headroom; "tightest" tier. Cancellable. Default confirmed against the Phase-2 time-curve measurement. |
| Stop | **Cancel → no marker** (same as Better/Best) | Consistent + simple; validator stays strict. "Best-so-far from sparrow snapshots" is filed as a follow-up (§13). |

## 4. Architecture

```
GUI (QualityPanel: + "Ultra")
  └─HTTP─► POST /auto-layout (quality="ultra")
             ├─ build PieceModels                       (existing)
             ├─ core/layout/separation.run_separation_layout:
             │    group by base id → jagua-rs JSON (grain-aligned + 90° axis-map)
             │    subprocess: sparrow.exe -i in.json -t <budget> -s <seed>   (in run_in_threadpool)
             │    parse output/final_<name>.json → reconstruct → VALIDATE → _compute_metrics
             ├─ cache (quality key already includes "ultra")
             └─ placements ─► Konva render ─► export (Phase 7)
```

`run_separation_layout` returns `(placements, marker_length_mm, utilization_pct)` — the
exact tuple `auto_layout_polygon` returns — so the API only needs a new branch in
`_do_layout` and the frontend renders it unchanged.

## 5. Module surface — `engine/core/layout/separation.py`

```python
def run_separation_layout(
    pieces: list[Piece], fabric_width_mm: float, grain_mode: str,
    fabric_grain_deg: float, budget_s: float, seed: int = 42,
) -> tuple[list[Placement], float, float]:
    """Mirror of auto_layout_polygon's return. Raises CancellationError if the
    sparrow child was killed (→ API 499); ValueError on invalid/empty output (→ API 400)."""
```

Private helpers (each independently testable):
- `_group_to_items(pieces, grain_mode, fabric_grain_deg)` → `(items_json, groups)` —
  collapse expanded pieces to base groups via `_base_id`; build one jagua item per group
  (demand = copy count, grain-aligned + axis-mapped polygon, per-item `allowed_orientations`).
- `_resolve_sparrow_path()` → path or `FileNotFoundError` with a clear message.
- `_run_sparrow(instance, budget_s, seed)` → output JSON dict (subprocess + cancel registration).
- `_reconstruct(solution, groups, fabric_width_mm)` → `list[Placement]` (inverse transform).
- `_validate_layout(placements, pieces, fabric_width_mm, grain_mode, fabric_grain_deg)` →
  raises `ValueError` listing the first few violations.

Reuses from `heuristic.py`: `Placement`, `EDGE_GAP`, `_base_id`, `_layout_rotations`,
`_placed_polygon`, `_has_area_overlap`, `_compute_metrics`, `_polygon_dims`.

## 6. Grain handling — per-item `allowed_orientations` (domain-critical) ⚠️

The Phase-1 bench hardcoded `allowed_orientations:[0,180]` because the canonical workload is
bi-grain-with-grainlines. **Production must derive it per item** or it violates the hard
grain constraint. Derived from `_layout_rotations(grain_mode, fabric_grain_deg, grainline)`:

| Piece | engine allowed set | jagua `allowed_orientations` |
|---|---|---|
| grainline + `single` (one-way / napped) | `{target}` | `[0]` — **no 180° flip** |
| grainline + `bi` (two-way) | `{target, target+180}` | `[0, 180]` |
| no grainline | `{0, 90, 180, 270}` | `[0, 90, 180, 270]` |

(`target = (fabric_grain_deg − grainline_deg) % 360`.) Emitting `[0,180]` for `single` would
flip napped pieces against the nap → physically invalid marker. `jagua-rs` has **no flip
field**, so handedness is always preserved; the orientation set is the only grain lever.

## 7. The axis-map round-trip (deterministic — round-trip-tested)

**Emit, per base item** (`base = engine_set[0]`):
1. Rotate `piece.polygon` by `(base + 90)°` about origin, then origin-normalize (bbox-min → (0,0)).
2. `allowed_orientations = [(a − base) % 360 for a in engine_set]` (→ table §6).
3. `strip_height = fabric_width_mm − 2·EDGE_GAP`; `demand =` copy count.

**Parse, per placed copy** (`r = rotation % 360`, `t = translation`):
1. jagua-frame polygon = emitted shape rotated by `r`, translated by `t`.
2. Rotate the **whole** layout by `−90°` about origin (inverse axis swap), then translate so
   the layout bbox-min → `(EDGE_GAP, EDGE_GAP)`.
3. `rotation_deg = (base + r) % 360`; `(x, y) =` rotated-bbox-min of that copy's engine-frame
   polygon. Assign copies to the group's `__cN` ids in placement order.

**Why it's exact:** net rotation through emit→sparrow→inverse is `(−90 + r + base + 90) =
base + r`, and `r ∈` the offset set `{0}`/`{0,180}`/`{0,90,180,270}`, so `base + r` lands
**exactly** in `engine_set`. With `rotation_deg = base+r` and `(x,y) =` the engine-frame
bbox-min, the existing `_placed_polygon(piece, x, y, rotation_deg)` reproduces the polygon
exactly, so it plugs straight into `_compute_metrics` and the renderer. The global `−90`
maps jagua's fixed `strip_height` (Y) → engine width (X ∈ `[EDGE_GAP, W−EDGE_GAP]`) and
jagua's minimized `strip_width` (X) → engine length (Y).

## 8. Validation backstop — `_validate_layout` (our frame)

Reconstruct each placement to its polygon via `_placed_polygon` and reject (→ `ValueError`)
on any of:
- **Grain:** `rotation_deg` not within tolerance of `engine_set` for that piece (snap
  near-integers first; off beyond tol = fail).
- **Overlap:** any pair with `_has_area_overlap` (eps 0.5 mm², bbox-prefiltered).
- **Width / bounds:** any piece with X outside `[0, fabric_width_mm]` or Y `< 0`.
- **Coverage:** placed count ≠ expected (one per expanded piece id).

This is the backstop the spec mandates: an axis/orientation bug surfaces as a validation
failure (→ surfaced error), never a silently-bad marker.

## 9. Subprocess + cancellation

- `_run_sparrow` writes the instance to a scratch `TemporaryDirectory`, runs
  `sparrow.exe -i inst.json -t <int budget> -s <seed>` with `cwd` = scratch (sparrow writes
  `output/final_<name>.json` relative to cwd), and reads it back. Fixed `-s seed` (default
  42, = `GA_GUI_SEED`) → reproducible & cacheable.
- **Cancellation** mirrors the executor plumbing: a lock-guarded module global
  `_current_sparrow: Popen | None` set around the run, plus `kill_current_sparrow()` that
  `terminate()`s it. `/cancel-layout` calls **both** `kill_current_executor()` and
  `kill_current_sparrow()`. A killed run (non-zero exit / missing output) → `CancellationError`
  → existing API 499. Runs inside the existing `run_in_threadpool` worker so `/cancel-layout`
  and `/ping` stay responsive.

## 10. Binary vendoring & resolution (offline Windows)

- Commit `engine/vendor/sparrow/sparrow.exe` + `engine/vendor/sparrow/PROVENANCE.md`
  recording the upstream commit hash, `cargo build --release` command, Rust version, and the
  MIT license text + a `jagua-rs` MPL-2.0 notice (we ship an unmodified binary, so the notice
  suffices). Refresh on upgrade.
- `_resolve_sparrow_path()` search ladder: `OPENMARKER_SPARROW_PATH` env override → vendored
  `engine/vendor/sparrow/sparrow.exe` (package-relative) → PyInstaller bundle dir
  (`sys._MEIPASS`, future) → dev `tools/sparrow/target/release/sparrow.exe`. Missing on all →
  `FileNotFoundError` with install guidance.
- Works in dev now; the documented Phase-8 hook is a PyInstaller `--add-binary` of the
  vendored path. No Phase-8 packaging work is in scope here.

## 11. API & cache changes (`engine/api/main.py`)

- `VALID_QUALITIES = ("fast", "better", "best", "ultra")`.
- `QUALITY_BUDGETS_S["ultra"] = 600.0`.
- `_do_layout`: `if quality == "ultra": return run_separation_layout(pieces, fabric_width_mm,
  grain_mode, FABRIC_GRAIN_DEG, budget_s=QUALITY_BUDGETS_S["ultra"], seed=GA_GUI_SEED)`.
- Hard-fail: `run_separation_layout`'s `ValueError` → existing `except ValueError` → HTTP 400
  → existing frontend error banner. `CancellationError` → existing 499.
- Cache: `quality` is already in the dedup key and `CachedLayout`; `"ultra"` flows through
  unchanged. Fixed seed → identical requests dedup to the cached marker.

## 12. Frontend changes

- `types/engine.ts`: `LayoutQuality = "fast" | "better" | "best" | "ultra"`.
- `QualityPanel.tsx`: append `{ value: "ultra", label: "Ultra", hint: "tightest" }`
  (and soften Best's hint, e.g. "very tight"). Reuses the elapsed timer, indeterminate
  progress bar, and placement render with no other change.
- Effort radio is already disabled for better/best; extend the disable to ultra (sparrow
  ignores `effort`).

## 13. Budget & time-curve

Default `600 s`. Before locking it, the bench measures the quality-vs-time curve at
`60 / 180 / 300 / 420 / 600 s` on `sample_2 ×10`, `sample_3 ×6`, `sample_4 ×6` and confirms
600 s clears the ≥3% gate everywhere (it already does at 180 s on sample_2). If a knee well
under 600 s is found, the default may be lowered — a one-line change.

**Stop behavior:** cancel → no marker (consistent with Better/Best). Follow-up (not Phase 2):
sparrow writes `sols_<name>/` intermediate snapshots; "render best-so-far on Stop" could read
the latest snapshot and re-validate it (rejecting mid-explore/overlapping ones). Filed for
later given the 600 s budget makes a zero-result Stop costly.

## 14. Testing (TDD order)

Unit (engine, no binary needed):
- `_group_to_items`: base grouping + demand; grain-aligned axis-mapped polygon; per-item
  `allowed_orientations` for **all three** §6 cases (single / bi / no-grainline).
- Axis-map round-trip: emit → simulate sparrow `(rotation, translation)` → parse; assert
  `rotation_deg ∈ engine_set`, the reconstructed polygon matches, within width — over several
  rotations and a multi-piece, multi-copy instance.
- `_validate_layout`: catches injected off-grain, overlapping, and over-width placements;
  passes a clean one.
- `_resolve_sparrow_path`: env override wins; missing → clear `FileNotFoundError` (tmp/fake binary).

Integration (skip gracefully if the binary is absent, like the bench):
- Real sparrow on a tiny 2–3-piece instance → valid, plausible marker.
- Cancellation: start a run, `kill_current_sparrow()`, assert `CancellationError`.

Bench (throwaway, not in the unit suite): Ultra-vs-GA on sample_2/3/4 + the §13 time-curve;
records numbers + the confirmed budget in PERFORMANCE.md §6.

## 15. Acceptance criteria

From the GUI, a user imports a DXF, selects **Ultra**, and gets a **valid** marker
(grain-respecting, overlap-free, within width) **≥3% shorter than GA** on the canonical
workloads — fully **offline**, **cancellable**, and **cached**; an invalid/empty sparrow
result surfaces a clear error and renders nothing. Engine unit + integration tests pass; the
bench + PERFORMANCE.md §6 entry record the win and the locked budget.

## 16. Risks & open questions

| Risk | Mitigation |
|---|---|
| Axis/orientation round-trip bug | Round-trip unit tests + `_validate_layout` backstop (rejects → surfaced error). |
| `jagua-rs` numeric tolerance vs our 0.5 mm² | Validate every placement; offending overlaps → reject (hard-fail). |
| Committed binary bloats git / goes stale | `PROVENANCE.md` pins the build; refresh deliberately on upgrade. |
| 600 s feels slow in the GUI | Cancellable; time-curve may lower the default; Best already runs 420 s. |
| Worktree lacks venv + DXF fixtures (gitignored) | Set up venv + copy fixtures before the bench/integration runs (project convention). |

## 17. References

- Parent design: `docs/superpowers/specs/2026-06-07-separation-engine-design.md` (§7).
- Schema + axis-map: `docs/superpowers/notes/2026-06-07-jagua-schema.md`.
- Eval/GO: `docs/planning/PERFORMANCE.md` §6 [2026-06-07], §5.B.
- Seed harness: `engine/tests/bench_sparrow.py`.
- `sparrow` (MIT) github.com/JeroenGar/sparrow; `jagua-rs` (MPL-2.0) github.com/JeroenGar/jagua-rs.
