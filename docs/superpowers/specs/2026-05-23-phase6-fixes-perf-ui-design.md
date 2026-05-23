# Phase 6 — Fixes, performance, and UI improvements (design)

**Date:** 2026-05-23
**Status:** Design approved; ready for implementation plan.
**Phase goal:** Clean up Phase 5 rough edges, simplify the settings surface, add an in-memory auto-layout result cache that the Phase 7 export flow will consume, and rework the metrics UI.

---

## Scope

The 9 user requirements (verbatim, with the design decision for each):

1. **Dynamic window size** — default to 70% of monitor logical height, 4:3 aspect ratio (`width = height × 4/3`). Computed at startup in Rust; replaces the fixed 1280×800 default.
2. **Copies input height** — double the height of the Settings → Copies number input.
3. **Remove grain mode "none"** — drop from UI, engine, types. Default = `single`.
4. **Remove fast mode (bbox)** — drop the toggle, the request field, and `auto_layout_bbox` + its tests.
5. **Show/hide grainline toggle** — checkbox on `GrainPanel`, default = on, gates per-piece arrow rendering only (no fabric grain indicator exists on the canvas).
6. **Auto-layout result cache** — in-memory engine cache, max 5 entries, FIFO eviction. **No deduplication**: every successful `/auto-layout` insertion creates a new entry with a fresh UUID and a fresh `YYYYMMDDHHMMSS` timestamp.
7. **Cache feeds future export** — entries store everything Phase 7 will need (placements + fabric width + metrics + duration). Schema is export-ready.
8. **Metrics moved to bottom panel + timer** — remove `MetricsCard` from sidebar; new `BottomPanel` shows length, utilization, overflow warning, and a `MM:SS` duration timer. Duration is measured engine-side around the BLF call.
9. **Per-tab cached metrics + tab strip** — new `CachedLayoutTabs` strip between the preview panel and the canvas (left edge aligned with the canvas, not the sidebar). Each tab shows a short label, has a × close button (manual close), and is highlighted when active. Active tab drives both the canvas placements and the bottom-panel metrics.

---

## Top-level UI layout

```
┌──────────────────────────────────────────────────┐
│ topbar  "OpenMarker — Working on sample_1.dxf"   │
├──────────────────────────────────────────────────┤
│ preview-panel  (piece thumbnails, unchanged)     │
├──────────────┬───────────────────────────────────┤
│              │ cached-layout-tabs  [t1×|t2×|…]   │  ← left edge = canvas left edge
│  sidebar     ├───────────────────────────────────┤
│  (Fabric,    │                                   │
│   Grain,     │       canvas (Konva stage)        │
│   Copies,    │                                   │
│   Run btn)   │                                   │
├──────────────┴───────────────────────────────────┤
│ bottom-panel  Length · Util · Overflow · ⏱ MM:SS │
├──────────────────────────────────────────────────┤
│ statusbar (unchanged)                            │
└──────────────────────────────────────────────────┘
```

Changes vs current:
- **NEW** `CachedLayoutTabs` strip, scoped to the canvas column (above canvas, sharing the canvas's left edge).
- **NEW** `BottomPanel` between the canvas row and the statusbar.
- **REMOVED** inline `MetricsCard` from `App.tsx` (currently around line 200).
- Sidebar shrinks to: Fabric width, Grain (single/bi radios + Show-grainline checkbox), Copies (taller input), Run button.

---

## Engine

### New module — `engine/core/layout/cache.py`

```python
@dataclass
class CachedLayout:
    id: str                              # UUID4 hex (URL path param)
    filename: str                        # echoed by frontend from /import-dxf response
    timestamp: str                       # YYYYMMDDHHMMSS, set when this entry is created
    grain_mode: Literal["single", "bi"]
    copies: int
    fabric_width_mm: float
    placements: list[dict]               # engine-convention coords (top-left of rotated bbox)
    marker_length_mm: float
    utilization_pct: float
    duration_ms: int                     # measured around the BLF call (time.perf_counter)
    created_at: float                    # epoch seconds, for FIFO ordering

class LayoutCache:
    MAX_ENTRIES = 5
    def insert(self, entry: CachedLayout) -> None  # FIFO-evict if size would exceed MAX
    def get(self, layout_id: str) -> CachedLayout | None
    def delete(self, layout_id: str) -> bool       # True if found and removed
    def list(self) -> list[CachedLayout]           # newest-first by created_at
```

- **Process-lifetime only.** No disk persistence. Module-level singleton (same pattern as `cancellation.py`).
- **No deduplication.** Each successful `/auto-layout` produces a fresh entry. Identical re-runs create duplicate tabs by design.
- **FIFO eviction.** When `insert` would push the size past 5, drop the oldest by `created_at`.

### API surface

| Method | Path | Change |
|---|---|---|
| POST | `/auto-layout` | **Modified.** Request adds `filename: str`. Request removes `fast_mode`. `grain_mode` enum tightens to `"single" \| "bi"` (422 on `"none"`). Engine times the BLF call with `time.perf_counter()`, builds a `CachedLayout`, inserts it, and returns the full entry (placements + metrics + `id` + `timestamp` + `duration_ms`). |
| GET | `/layouts` | **New.** Returns lightweight list (no `placements`): `[{id, filename, timestamp, grain_mode, copies, fabric_width_mm, marker_length_mm, utilization_pct, duration_ms}]`, newest-first. |
| GET | `/layouts/{id}` | **New.** Returns the full `CachedLayout` (including `placements`). 404 if missing. |
| DELETE | `/layouts/{id}` | **New.** Manual tab close. 204 on success, 404 if missing. |
| POST | `/import-dxf` | Unchanged. |
| POST | `/cancel-layout` | Unchanged. |
| GET | `/ping` | Unchanged. |

### Removed engine code

- `auto_layout_bbox` in `engine/core/layout/heuristic.py` and its tests.
- `"none"` branch in `engine/core/layout/grain.py::allowed_rotations()`.
- `fast_mode` field from the `/auto-layout` request model.

---

## Frontend

### New files

- **`frontend/src/components/CachedLayoutTabs.tsx`** — tab strip rendered above the canvas, scoped to the canvas column. Each tab: short label (e.g. `single · ×2 · 14:32:07`) and inline × close button. Active tab visually highlighted. New tabs come from clicking Run in the sidebar; there is no `+` button on the strip.
- **`frontend/src/components/BottomPanel.tsx`** — single row showing `Length: <n> mm · Util: <n>% · ⏱ MM:SS`, plus overflow warning when applicable. Reads from the active cached entry.
- **`frontend/src/hooks/useLayoutCache.ts`** — owns cache state. After each successful `/auto-layout`: calls `GET /layouts` and `setActiveId(newId)`. Activation triggers a lazy `GET /layouts/{id}` for the full placement payload. Exposes `entries`, `activeId`, `activeEntry`, `setActiveId`, `closeTab`.

### Modified files

- **`frontend/src/app/App.tsx`** — adopt top-level layout above; remove inline `MetricsCard`; wire `useLayoutCache`; lift `showGrainline` boolean (default `true`) and pass to `PieceShape`. Drop `fastMode` state.
- **`frontend/src/components/sidebar/GrainPanel.tsx`** — drop the `"none"` radio and the fast-mode checkbox. Add `Show grainline` checkbox. `GRAIN_MODE_LABELS` becomes `{ single, bi }`.
- **`frontend/src/components/canvas/PieceShape.tsx`** — accept `showGrainline: boolean`; render arrow when `showGrainline && piece.grainline_direction_deg !== null`. Drop the `grainMode !== "none"` check.
- **`frontend/src/components/canvas/CanvasWorkspace.tsx`** — accept/pass through `showGrainline`.
- **`frontend/src/hooks/useAutoLayout.ts`** — drop `fast_mode`; add `filename` to the request; return the new entry's `id` so `useLayoutCache` can activate it.
- **`frontend/src/hooks/usePlacements.ts`** — driven by `useLayoutCache.activeEntry?.placements` instead of being set directly from `/auto-layout` responses.
- **`frontend/src/types/engine.ts`** — `GrainMode` becomes `"single" | "bi"`; add `CachedLayoutSummary` and `CachedLayout` interfaces; drop `fast_mode` from the request type.
- **Copies input** (currently inline in `App.tsx` ~line 186–194) — double the input's height via CSS (e.g. `height: 32px → 64px`; adjust font-size for readability).

### Removed frontend code

- `MetricsCard` component + props in `App.tsx` (lines ~290+, ~314+).
- `fastMode` state in `App.tsx` and the matching prop on `GrainPanel`.
- `"none"` from `GrainMode`, `GRAIN_MODE_LABELS`, and the radio loop in `GrainPanel`.

---

## Desktop shell — dynamic window size

### `desktop/src-tauri/tauri.conf.json`

- Remove fixed `width: 1280, height: 800`.
- Keep `min_width: 900, min_height: 600`.
- Set `visible: false` initially (avoid flash at the wrong size).

### `desktop/src-tauri/src/lib.rs` (or `main.rs`)

In the Tauri setup hook, on the main window:

1. `let monitor = window.current_monitor()?` — monitor under the cursor at startup.
2. Read `monitor.size()` (physical pixels) and `monitor.scale_factor()` to derive logical size.
3. Compute `height = monitor_logical_height * 0.7`, `width = height * 4.0 / 3.0`.
4. If `width > monitor_logical_width * 0.95`, clamp `width = monitor_logical_width * 0.95` and recompute `height = width * 3.0 / 4.0`.
5. `window.set_size(LogicalSize { width, height })`.
6. `window.center()`.
7. `window.show()`.

Fallback: if `current_monitor()` returns `None`, set `1280×800` and `center()`, log a warning.

`min_width` / `min_height` from the config remain enforced by Tauri after `set_size`.

Expected sizes:
| Monitor | Scale | Logical | Window |
|---|---|---|---|
| 1920×1080 | 1.0 | 1920×1080 | 1008×756 |
| 2560×1440 | 1.0 | 2560×1440 | 1344×1008 |
| 5120×2880 | 1.0 | 5120×2880 | 2688×2016 |
| 5120×2880 | 2.0 | 2560×1440 | 1344×1008 |

---

## Data flow

```
[User clicks Run]
   ↓
useAutoLayout posts /auto-layout
   { filename, pieces, fabric_width_mm, grain_mode, copies }
   ↓
engine: time the BLF call → build CachedLayout (new UUID, fresh timestamp)
        → cache.insert() (FIFO-evict if > 5)
        → return full entry
   ↓
useAutoLayout returns entry.id
   ↓
useLayoutCache:
   - GET /layouts             (refresh summary list for tab strip)
   - setActiveId(entry.id)
   ↓
activeId change → GET /layouts/{id} (lazy fetch placements)
   ↓
usePlacements ← activeEntry.placements
BottomPanel  ← activeEntry.{marker_length_mm, utilization_pct, duration_ms}
CachedLayoutTabs ← entries (newest-first), active highlighted
canvas re-renders
```

**Tab click** — `setActiveId(otherId)` → `GET /layouts/{id}` → swap placements + metrics. No engine work.

**Tab close (× button)** — `DELETE /layouts/{id}` → refresh `GET /layouts`. If the closed tab was active: select the newest remaining; if no entries remain, clear placements.

**Show-grainline toggle** — pure frontend state; no engine round-trip; no cache invalidation.

**`MM:SS` formatting** — `Math.floor(ms/60000)` and `Math.floor((ms%60000)/1000)`, zero-padded. MM unbounded for the unlikely ≥60-minute case.

---

## Error handling

- `POST /auto-layout` with `grain_mode="none"` → 422. Frontend never sends this; engine validates defensively.
- `POST /auto-layout` without `filename` → 422. Frontend always includes it.
- `GET /layouts/{id}` for an evicted/missing id → 404. Frontend removes the tab from local state and activates the newest remaining (or clears the canvas).
- `DELETE /layouts/{id}` for missing id → 404; frontend treats as idempotent success.
- Cache insert over `MAX_ENTRIES` → silent FIFO eviction. The next `GET /layouts` simply omits the evicted entry.
- Engine crash mid-layout → cancellation flag path unchanged; no entry inserted. No partial entries.
- Tauri window-sizing failure (`current_monitor()` None or `set_size` errors) → fall back to `1280×800`, log warning, app still opens.
- `POST /import-dxf` response unchanged; filename already present.

No new global error state. The cache is a soft resource — losing it on process restart starts the user with an empty tab strip.

---

## Testing

### Engine

**New — `engine/tests/unit/test_cache.py`**
- `insert` then `get` round-trip.
- `insert` past `MAX_ENTRIES` evicts oldest by `created_at`.
- `list` returns newest-first.
- `delete` returns True for found id, False for missing id.
- `get` returns None for missing id.

**New — `engine/tests/integration/test_api_cache.py`**
- `POST /auto-layout` response includes `id`, `timestamp`, `duration_ms`.
- `GET /layouts` returns summary list newest-first.
- `GET /layouts/{id}` returns full entry; 404 for missing id.
- `DELETE /layouts/{id}` returns 204; subsequent GET returns 404.
- 6 consecutive `/auto-layout` calls → only 5 entries remain; oldest is gone.
- `POST /auto-layout` with `grain_mode="none"` → 422.
- `POST /auto-layout` without `filename` → 422.

**Modified — `engine/tests/unit/test_grain.py`**
- Remove `"none"` test case; assert `allowed_rotations("none")` raises `ValueError`.

**Modified — `engine/tests/unit/test_heuristic.py`**
- Remove all `auto_layout_bbox` tests. Existing `auto_layout_polygon` tests unchanged.

### Frontend (Vitest)

**New — `frontend/src/hooks/useLayoutCache.test.ts`**
- Mock fetch; `GET /layouts` is called after activation.
- `setActiveId` triggers `GET /layouts/{id}` and updates state.
- `closeTab` calls `DELETE` then refreshes the list.
- Closing the active tab selects the newest remaining.
- Closing the last tab clears active state.

**New or modify — `frontend/src/components/sidebar/GrainPanel.test.tsx`**
- Renders only `single` and `bi` radios.
- No fast-mode checkbox.
- `Show grainline` checkbox calls its handler.

**New — `frontend/src/components/BottomPanel.test.tsx`**
- Formats `duration_ms` 3500 → `"00:03"`, 125000 → `"02:05"`.
- Shows overflow warning when prop set.

**Audit — `frontend/src/utils/metrics.ts`**
- If still used after metrics move to engine-returned values, trim to what `BottomPanel` needs. May be deletable.

### Desktop

- Manual: run `cargo tauri dev` on at least two monitor sizes; confirm window starts at ~70% of monitor logical height in 4:3.

### Out of scope

- Visual regression of the new tab strip (no infrastructure for it).
- Cross-process cache persistence (intentionally unsupported).

---

## Open items deferred to Phase 7

- Export endpoint design (`POST /export` accepting a cache id).
- "Export" button placement (per-tab vs in bottom panel).
- File format(s): DXF and/or PNG.

---

## Decision log

- **Cache deduplication:** none. Every Run = new tab. User accepted this trade-off (allows comparing two identical-settings runs that may differ due to heuristic non-determinism).
- **Cache timestamp source:** generated by the engine at insert time (post-layout).
- **Cache API:** split — `GET /layouts` (summary) + `GET /layouts/{id}` (full).
- **Timer:** engine-side `time.perf_counter()` around the BLF call. Excludes network/serialization.
- **Tab close:** manual × per tab plus FIFO when size exceeds 5.
- **Grainline toggle:** affects per-piece arrows only; no fabric grain indicator exists on the canvas.
- **Window sizing:** 70% of monitor logical height, 4:3, computed at startup in Rust.
