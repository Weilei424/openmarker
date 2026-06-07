# Expose the GA Optimizer to the GUI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a non-technical user pick a Fast/Better/Best layout quality in the app and get the stronger GA result (with a time budget, a working Stop that falls back to the warm-start, and an elapsed timer), while an omitted quality reproduces today's behavior bit-for-bit.

**Architecture:** Add an optional `quality` enum to `POST /auto-layout`; the engine maps `better`/`best` to the already-merged GA knobs (`ga_generations`/`ga_max_time_s`/`ga_seed` + `effort=4`) in `_do_layout`, while `fast` (default) passes no GA knobs. A GA cancellation is caught in `auto_layout_polygon` and returned as the pre-computed warm-start (`StoppedWithWarmStart`). `quality` joins the cache dedup key; stopped runs are cached as `fast`. The frontend adds a `QualityPanel` radio group, threads `quality` through `useAutoLayout`, and shows an elapsed timer.

**Tech Stack:** Python 3.11 / FastAPI / pytest + httpx (engine); React + TypeScript + vitest + @testing-library/react (frontend).

**Design spec:** `docs/superpowers/specs/2026-06-06-expose-optimizer-gui-design.md`.

> **Update (2026-06-06, post-manual-test):** the Stop→warm-start fallback (Task 1
> `StoppedWithWarmStart`, Task 2 `_ga_phase_or_warm_start`, and the `stopped`
> wiring in Tasks 4 / 6 / 9) was **removed before merge** — it can't surface in
> the GUI (the client aborts the request on Stop). Stop just cancels. Everything
> else in this plan shipped.

---

## Environment setup (worktree has no venv / node_modules — both are git-ignored)

All work happens in the worktree: `D:\openmarker\.worktrees\expose-optimizer`.

- **Engine interpreter:** reuse the MAIN repo venv — there is no venv in the worktree.
  `D:\openmarker\engine\.venv\Scripts\python.exe`
- **Run engine tests** from the worktree engine dir
  (`D:\openmarker\.worktrees\expose-optimizer\engine`):
  `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_cache.py -v`
  (pytest discovers `pytest.ini` there and puts the worktree `engine/` on `sys.path`; the main venv only supplies packages.)
- **Frontend:** one-time `npm install` in `D:\openmarker\.worktrees\expose-optimizer\frontend`
  (needs network once; afterwards offline). Run a single test file with
  `npx vitest run src/components/sidebar/QualityPanel.test.tsx`.
- **Bench fixtures:** the canonical DXF is git-ignored, so copy it into the worktree before Task 5:
  `Copy-Item D:\openmarker\examples\input\*.dxf D:\openmarker\.worktrees\expose-optimizer\examples\input\`
- **Commits:** authorized in this worktree. Run git from the worktree
  (`git -C D:\openmarker\.worktrees\expose-optimizer ...` or with that dir as CWD).
  End every commit message with the trailer:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

Commands below assume CWD = the worktree engine or frontend dir as noted.

---

## File structure

**Engine**
- `engine/core/layout/cancellation.py` — add `StoppedWithWarmStart` exception (carries the warm-start payload).
- `engine/core/layout/heuristic.py` — add `_ga_phase_or_warm_start` wrapper; route both GA call-sites through it.
- `engine/core/layout/cache.py` — add `quality` field to `CachedLayout` + `quality` to `find_by_settings`.
- `engine/api/main.py` — tier→knob constants; parse/validate `quality`; map it in `_do_layout`; handle `StoppedWithWarmStart`; thread `quality` into dedup + cache insert; add `stopped` to the response.
- `engine/tests/unit/test_cache.py`, `engine/tests/unit/test_heuristic.py`, `engine/tests/integration/test_api_cache.py` — new tests.
- `engine/tests/bench_optimizer_tiers.py` (new) — budget validation.

**Frontend**
- `frontend/src/types/engine.ts` — `LayoutQuality` type; `stopped?` on `AutoLayoutResponse`.
- `frontend/src/components/sidebar/QualityPanel.tsx` (new) + `QualityPanel.test.tsx` (new).
- `frontend/src/hooks/useAutoLayout.ts` (+ new `useAutoLayout.test.ts`) — `quality` arg + body field.
- `frontend/src/app/App.tsx` — `quality` state, QualityPanel section, elapsed timer, stopped status.

**Docs**
- `docs/planning/PERFORMANCE.md`, `docs/planning/BACKLOG.md`.

---

## Task 1: `StoppedWithWarmStart` exception

**Files:**
- Modify: `engine/core/layout/cancellation.py`
- Test: `engine/tests/unit/test_cache.py` is unrelated; add the test to a new `engine/tests/unit/test_cancellation.py`

- [ ] **Step 1: Write the failing test**

Create `engine/tests/unit/test_cancellation.py`:

```python
from core.layout.cancellation import StoppedWithWarmStart


def test_stopped_with_warm_start_carries_result():
    payload = (["placement"], 123.4, 56.7)
    exc = StoppedWithWarmStart(payload)
    assert exc.result == payload
    assert isinstance(exc, Exception)
```

- [ ] **Step 2: Run it to verify it fails**

From `D:\openmarker\.worktrees\expose-optimizer\engine`:
`D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_cancellation.py -v`
Expected: FAIL with `ImportError: cannot import name 'StoppedWithWarmStart'`.

- [ ] **Step 3: Implement**

Append to `engine/core/layout/cancellation.py` (after `CancellationError`):

```python
class StoppedWithWarmStart(Exception):
    """Raised by auto_layout_polygon when a GA meta-heuristic run is cancelled
    AFTER the warm-start has been computed. Carries the warm-start result so the
    API layer can return it (HTTP 200) instead of discarding the whole run.

    `result` is the (placements, marker_length_mm, utilization_pct) tuple.
    """

    def __init__(self, result) -> None:
        super().__init__("Optimizer cancelled; returning warm-start result.")
        self.result = result
```

- [ ] **Step 4: Run it to verify it passes**

`D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_cancellation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/core/layout/cancellation.py engine/tests/unit/test_cancellation.py
git commit -m "feat(engine): add StoppedWithWarmStart exception

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: GA cancellation falls back to the warm-start

`auto_layout_polygon` calls `_run_ga_phase` from two identical sites (serial ~L1041, parallel ~L1119). Route both through one wrapper so a `CancellationError` becomes a `StoppedWithWarmStart` carrying the warm-start. One wrapper = DRY + one test covers both sites.

**Files:**
- Modify: `engine/core/layout/heuristic.py`
- Test: `engine/tests/unit/test_heuristic.py`

- [ ] **Step 1: Write the failing test**

Append to `engine/tests/unit/test_heuristic.py` (uses the existing `_two_simple_pieces` helper in that file):

```python
def test_ga_cancel_falls_back_to_warm_start(monkeypatch):
    """When the GA phase raises CancellationError, auto_layout_polygon re-raises
    StoppedWithWarmStart carrying the warm-start the GA phase was handed."""
    from core.layout import heuristic
    from core.layout.cancellation import CancellationError, StoppedWithWarmStart

    pieces = _two_simple_pieces()
    seen = {}

    def fake_phase(warm_start_best, *args, **kwargs):
        seen["wsb"] = warm_start_best
        raise CancellationError("simulated GA cancel")

    monkeypatch.setattr(heuristic, "_run_ga_phase", fake_phase)

    with pytest.raises(StoppedWithWarmStart) as excinfo:
        heuristic.auto_layout_polygon(
            pieces, fabric_width_mm=500, grain_mode="single",
            fabric_grain_deg=0.0, ga_generations=1, effort=1,
        )
    assert excinfo.value.result == seen["wsb"]
```

- [ ] **Step 2: Run it to verify it fails**

`D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_heuristic.py -v -k ga_cancel_falls_back`
Expected: FAIL — `CancellationError` propagates (no `StoppedWithWarmStart` yet).

- [ ] **Step 3: Add the wrapper helper**

In `engine/core/layout/heuristic.py`, immediately AFTER the `_run_ga_phase` function definition (after its `return best_placements, best_marker, best_util` ~L1373), add:

```python
def _ga_phase_or_warm_start(
    warm_start_best, warm_starts, blf_input, fabric_width_mm, grain_mode,
    fabric_grain_deg, ga_generations, ga_max_time_s, ga_seed, effort,
    disable_nfp_cache, clusters, ga_config,
):
    """Run the GA phase; if it is cancelled, fall back to the already-computed
    warm-start (GA never clusters, so `warm_start_best` is directly returnable).
    The fallback is signalled to the API layer via StoppedWithWarmStart."""
    try:
        result = _run_ga_phase(
            warm_start_best, warm_starts, blf_input, fabric_width_mm, grain_mode,
            fabric_grain_deg, ga_generations, ga_max_time_s, ga_seed, effort,
            disable_nfp_cache, clusters, ga_config,
        )
    except CancellationError:
        raise StoppedWithWarmStart(warm_start_best)
    return result
```

(The body uses `result = _run_ga_phase(...)` / `return result` — never the literal
`return _run_ga_phase(`, so the replace in Step 5 cannot touch it.)

- [ ] **Step 4: Import the exception**

In `engine/core/layout/heuristic.py`, change the cancellation import (currently `from core.layout.cancellation import CancellationError, is_cancelled`) to:

```python
from core.layout.cancellation import CancellationError, StoppedWithWarmStart, is_cancelled
```

- [ ] **Step 5: Route both GA call-sites through the wrapper**

Both call-sites read exactly `return _run_ga_phase(` (serial + parallel). Replace ALL occurrences of the literal `return _run_ga_phase(` with `return _ga_phase_or_warm_start(` (2 occurrences). The argument lists are identical and unchanged.

(If editing programmatically, use replace-all on the string `return _run_ga_phase(`.
Verify afterward that `_run_ga_phase` is still referenced exactly once outside its
own definition — inside `_ga_phase_or_warm_start`.)

- [ ] **Step 6: Run the new test + the existing GA/heuristic suite**

```
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_heuristic.py -v -k "ga or cancel"
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_heuristic.py tests\unit\test_ga.py -q
```
Expected: the new test PASSES and nothing in `test_heuristic.py` / `test_ga.py` regresses.

- [ ] **Step 7: Commit**

```bash
git add engine/core/layout/heuristic.py engine/tests/unit/test_heuristic.py
git commit -m "feat(engine): GA cancel falls back to warm-start (StoppedWithWarmStart)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `quality` in the cache dedup key

**Files:**
- Modify: `engine/core/layout/cache.py`
- Test: `engine/tests/unit/test_cache.py`

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/unit/test_cache.py` (reuses the existing `_make_entry` helper):

```python
def test_find_by_settings_quality_must_match():
    cache = LayoutCache()
    e = _make_entry("best1")
    e.quality = "best"
    cache.insert(e)
    # Default lookup quality is "fast" → must NOT match a "best" entry.
    assert cache.find_by_settings(
        filename="sample.dxf", grain_mode="single", copies=1, fabric_width_mm=1500.0
    ) is None
    hit = cache.find_by_settings(
        filename="sample.dxf", grain_mode="single", copies=1,
        fabric_width_mm=1500.0, quality="best",
    )
    assert hit is not None and hit.id == "best1"


def test_find_by_settings_default_quality_is_fast():
    cache = LayoutCache()
    cache.insert(_make_entry("f1"))  # quality defaults to "fast"
    hit = cache.find_by_settings(
        filename="sample.dxf", grain_mode="single", copies=1, fabric_width_mm=1500.0
    )
    assert hit is not None and hit.id == "f1"
```

- [ ] **Step 2: Run them to verify they fail**

`D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_cache.py -v -k quality`
Expected: FAIL — `CachedLayout` has no `quality`; `find_by_settings` has no `quality` kwarg.

- [ ] **Step 3: Add the `quality` field to `CachedLayout`**

In `engine/core/layout/cache.py`, in the `CachedLayout` dataclass, insert `quality` between `created_at` and `_sort_key`:

```python
    created_at: float
    # Layout quality tier this entry was produced at ("fast" | "better" | "best").
    # Part of the dedup key so a Best run never returns a cached Fast result.
    # Defaults to "fast" so legacy/auxiliary constructions dedup as the warm-start.
    quality: str = "fast"
    # Internal tiebreaker assigned by LayoutCache.insert when the entry is
    # accepted. Strictly increasing per-cache; not part of the public API
    # and not serialized to clients.
    _sort_key: int = field(default=0, repr=False, compare=False)
```

(Remove the now-duplicated original `_sort_key` line + its comment if the edit
leaves two; there must be exactly one `_sort_key` field.)

- [ ] **Step 4: Add `quality` to `find_by_settings`**

Change the signature and the match condition:

```python
    def find_by_settings(
        self,
        filename: str,
        grain_mode: str,
        copies: int,
        fabric_width_mm: float,
        quality: str = "fast",
        effort: int | None = None,  # TEMP(phase6-bench): include in key when not None
    ) -> CachedLayout | None:
        """Return the newest entry matching ALL of (filename, grain_mode, copies,
        fabric_width_mm, quality), or None. Used to dedup re-runs with identical
        settings."""
        matches = []
        for e in self._entries.values():
            if not (e.filename == filename
                    and e.grain_mode == grain_mode
                    and e.copies == copies
                    and e.fabric_width_mm == fabric_width_mm
                    and e.quality == quality):
                continue
```

(Leave the rest of the method — the `effort` block and `return max(...)` — unchanged.)

- [ ] **Step 5: Run the cache suite**

`D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_cache.py -v`
Expected: the two new tests PASS and all existing cache tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/core/layout/cache.py engine/tests/unit/test_cache.py
git commit -m "feat(engine): add quality to the layout cache dedup key

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `/auto-layout` quality wiring + stopped fallback

**Files:**
- Modify: `engine/api/main.py`
- Test: `engine/tests/integration/test_api_cache.py`

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/integration/test_api_cache.py` (reuses its `_square_piece` + `_reset_cache` autouse fixture):

```python
from types import SimpleNamespace


def _fake_layout_factory(captured: dict):
    """Returns a stub for api.main.auto_layout_polygon that records kwargs and
    returns a trivial valid result (one placement)."""
    def _fake(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        pl = SimpleNamespace(piece_id="p0", x=0.0, y=0.0, rotation_deg=0.0)
        return ([pl], 100.0, 50.0)
    return _fake


@pytest.mark.asyncio
async def test_quality_best_maps_to_ga_knobs(monkeypatch):
    import api.main as main_mod
    captured = {}
    monkeypatch.setattr(main_mod, "auto_layout_polygon", _fake_layout_factory(captured))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/auto-layout", json={
            "filename": "q.dxf", "pieces": [_square_piece()],
            "fabric_width_mm": 1500, "grain_mode": "single", "quality": "best",
        })
    assert res.status_code == 200
    kw = captured["kwargs"]
    assert kw["ga_generations"] == 12
    assert kw["ga_max_time_s"] == 420.0
    assert kw["ga_seed"] == 42
    assert kw["effort"] == 4
    assert "sa_iterations" not in kw  # GA path only


@pytest.mark.asyncio
async def test_quality_better_maps_to_180s(monkeypatch):
    import api.main as main_mod
    captured = {}
    monkeypatch.setattr(main_mod, "auto_layout_polygon", _fake_layout_factory(captured))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/auto-layout", json={
            "filename": "q.dxf", "pieces": [_square_piece()],
            "fabric_width_mm": 1500, "grain_mode": "single", "quality": "better",
        })
    assert res.status_code == 200
    assert captured["kwargs"]["ga_max_time_s"] == 180.0
    assert captured["kwargs"]["ga_generations"] == 12


@pytest.mark.asyncio
async def test_quality_fast_passes_no_ga_knobs(monkeypatch):
    import api.main as main_mod
    captured = {}
    monkeypatch.setattr(main_mod, "auto_layout_polygon", _fake_layout_factory(captured))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/auto-layout", json={
            "filename": "q.dxf", "pieces": [_square_piece()],
            "fabric_width_mm": 1500, "grain_mode": "single",  # quality omitted
        })
    assert res.status_code == 200
    kw = captured["kwargs"]
    assert "ga_generations" not in kw
    assert "ga_max_time_s" not in kw
    assert kw["effort"] == 1  # the user's effort radio default, unchanged
    assert res.json()["stopped"] is False


@pytest.mark.asyncio
async def test_quality_invalid_returns_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/auto-layout", json={
            "filename": "q.dxf", "pieces": [_square_piece()],
            "fabric_width_mm": 1500, "grain_mode": "single", "quality": "ultra",
        })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_quality_in_dedup_key_distinguishes_best_and_fast(monkeypatch):
    import api.main as main_mod
    monkeypatch.setattr(main_mod, "auto_layout_polygon", _fake_layout_factory({}))
    body = {"filename": "d.dxf", "pieces": [_square_piece()],
            "fabric_width_mm": 1500, "grain_mode": "single"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        f = await client.post("/auto-layout", json={**body, "quality": "fast"})
        b = await client.post("/auto-layout", json={**body, "quality": "best"})
        listing = await client.get("/layouts")
    assert f.json()["id"] != b.json()["id"]
    assert len(listing.json()) == 2


@pytest.mark.asyncio
async def test_quality_stopped_returns_warm_start_cached_as_fast(monkeypatch):
    import api.main as main_mod
    from core.layout.cancellation import StoppedWithWarmStart
    warm = ([SimpleNamespace(piece_id="p0", x=1.0, y=2.0, rotation_deg=0.0)], 999.0, 60.0)

    def fake(*args, **kwargs):
        if kwargs.get("ga_generations"):       # the best/better path
            raise StoppedWithWarmStart(warm)
        return warm                             # the fast path

    monkeypatch.setattr(main_mod, "auto_layout_polygon", fake)
    body = {"filename": "s.dxf", "pieces": [_square_piece()],
            "fabric_width_mm": 1500, "grain_mode": "single"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        best = await client.post("/auto-layout", json={**body, "quality": "best"})
        fast = await client.post("/auto-layout", json={**body, "quality": "fast"})
    assert best.status_code == 200
    assert best.json()["stopped"] is True
    assert best.json()["marker_length_mm"] == 999.0
    # The stopped Best run was cached as Fast → a later Fast run dedups to it.
    assert fast.json()["stopped"] is False
    assert fast.json()["id"] == best.json()["id"]
```

- [ ] **Step 2: Run them to verify they fail**

`D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\integration\test_api_cache.py -v -k quality`
Expected: FAIL — `quality` is ignored; no `stopped` key; no tier mapping.

- [ ] **Step 3: Add the cancellation import**

In `engine/api/main.py`, change:

```python
from core.layout.cancellation import (
    CancellationError,
    request_cancellation,
    reset_cancellation,
)
```

to:

```python
from core.layout.cancellation import (
    CancellationError,
    StoppedWithWarmStart,
    request_cancellation,
    reset_cancellation,
)
```

- [ ] **Step 4: Add the tier→knob constants**

In `engine/api/main.py`, immediately before the `@app.post("/auto-layout")` decorator, add:

```python
# Optimizer quality tiers -> GA knobs (see
# docs/superpowers/specs/2026-06-06-expose-optimizer-gui-design.md).
# "fast" runs no meta-heuristic (today's warm-start). "better"/"best" run the
# island-model GA with a wall-clock budget. Budgets validated by
# engine/tests/bench_optimizer_tiers.py on the canonical workload.
VALID_QUALITIES = ("fast", "better", "best")
GA_GENERATIONS_CAP = 12        # generation cap; binds on small jobs, time binds on big
GA_GUI_SEED = 42               # fixed -> deterministic per (input, quality)
OPTIMIZED_EFFORT = 4           # "all but one core": more islands, machine stays usable
QUALITY_BUDGETS_S = {"better": 180.0, "best": 420.0}
```

- [ ] **Step 5: Parse + validate `quality`**

In `auto_layout_endpoint`, after the `effort` validation block (after the lines that raise on bad `effort`), add:

```python
    quality = str(body.get("quality", "fast"))
    if quality not in VALID_QUALITIES:
        raise HTTPException(
            status_code=422,
            detail=f"`quality` must be one of {VALID_QUALITIES}, got {quality!r}",
        )
```

- [ ] **Step 6: Thread `quality` into the dedup lookup + early return**

Change the `find_by_settings(...)` call to pass `quality=quality`:

```python
    existing = get_cache().find_by_settings(
        filename=filename,
        grain_mode=grain_mode,
        copies=int(body.get("copies", 1)),
        fabric_width_mm=fabric_width_mm,
        quality=quality,
        effort=effort if include_effort_in_key else None,  # TEMP(phase6-bench)
    )
```

And add `"stopped": False` to the dedup early-return dict:

```python
    if existing is not None:
        return {
            "id": existing.id,
            "timestamp": existing.timestamp,
            "duration_ms": existing.duration_ms,
            "placements": existing.placements,
            "marker_length_mm": existing.marker_length_mm,
            "utilization_pct": existing.utilization_pct,
            "stopped": False,
        }
```

- [ ] **Step 7: Map `quality` in `_do_layout`**

Replace the `_do_layout` function body:

```python
    def _do_layout():
        if quality == "fast":
            return auto_layout_polygon(
                pieces, fabric_width_mm, grain_mode, FABRIC_GRAIN_DEG,
                disable_nfp_cache=disable_nfp_cache,
                effort=effort,
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
```

- [ ] **Step 8: Handle the stopped fallback around the run**

Replace the `start = time.perf_counter()` / try-except / `duration_ms = ...` block with:

```python
    start = time.perf_counter()
    stopped = False
    try:
        placements, marker_length, utilization = await run_in_threadpool(_do_layout)
    except StoppedWithWarmStart as fallback:
        # GA cancelled after the warm-start was computed: return the warm-start
        # (== the Fast result) instead of discarding the run.
        placements, marker_length, utilization = fallback.result
        stopped = True
    except CancellationError:
        # Cancelled before any result existed (e.g. during the warm-start phase).
        return JSONResponse(
            status_code=499,  # Client Closed Request (Nginx convention)
            content={"detail": "cancelled"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    duration_ms = int((time.perf_counter() - start) * 1000)

    # A stopped optimized run yielded the warm-start, which IS the Fast result —
    # cache and label it as Fast so it dedups correctly and never shadows a real
    # Best run.
    effective_quality = "fast" if stopped else quality
```

- [ ] **Step 9: Persist `quality` + return `stopped`**

Add `quality=effective_quality,` to the `CachedLayout(...)` constructor call (anywhere in its kwargs, e.g. right after `duration_ms=duration_ms,`):

```python
        duration_ms=duration_ms,
        quality=effective_quality,
```

And add `"stopped": stopped` to the final success response dict:

```python
    return {
        "id": entry.id,
        "timestamp": entry.timestamp,
        "duration_ms": entry.duration_ms,
        "placements": placements_serialized,
        "marker_length_mm": marker_length,
        "utilization_pct": utilization,
        "stopped": stopped,
    }
```

- [ ] **Step 10: Update the endpoint docstring**

In the `auto_layout_endpoint` docstring, add `"quality": "fast"` to the documented request JSON (with a comment `// optional: "fast" | "better" | "best"; better/best run GA`) and `"stopped": false` to the documented response JSON (`// true if a better/best run was cancelled and fell back to the warm-start`).

- [ ] **Step 11: Run the API + full engine suite**

```
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\integration\test_api_cache.py -v
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit tests\integration -q
```
Expected: all new `quality`/`stopped` tests PASS; the whole engine suite stays green (the existing `/auto-layout` tests still pass because omitting `quality` defaults to `fast`).

- [ ] **Step 12: Commit**

```bash
git add engine/api/main.py engine/tests/integration/test_api_cache.py
git commit -m "feat(engine): map quality tier to GA knobs in /auto-layout

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Budget-validation bench (locks 180 / 420)

Validates that Best beats the bar (11699mm) and Better beats it too, on the canonical workload. Long-running (~10-15 min) and fixture-dependent — run it in the background. May run concurrently with Tasks 6-9.

**Files:**
- Create: `engine/tests/bench_optimizer_tiers.py`

- [ ] **Step 1: Copy the fixture into the worktree**

`Copy-Item D:\openmarker\examples\input\*.dxf D:\openmarker\.worktrees\expose-optimizer\examples\input\`
(If `sample_2.dxf` is missing from the main repo too, the bench self-SKIPs; record that and keep the spec's 180/420 estimates, noting validation is pending.)

- [ ] **Step 2: Write the bench script**

Create `engine/tests/bench_optimizer_tiers.py`:

```python
"""Budget-validation bench for the GUI optimizer tiers (Better / Best).

Not part of pytest. Run from the worktree engine dir with the main venv:
    D:\\openmarker\\engine\\.venv\\Scripts\\python.exe tests\\bench_optimizer_tiers.py

Confirms api.main.QUALITY_BUDGETS_S on the canonical workload: Best must beat the
bar (11699mm); Better must beat it within its shorter budget. Writes a JSON report
to engine/tests/_reports/ after each tier so a kill still leaves partial results.
Soft TTL via BENCH_TTL_S env (default 1500s).
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.layout.grain import FABRIC_GRAIN_DEG
from core.layout.heuristic import auto_layout_polygon
from bench_ga import _load_workload, FABRIC, BAR
from api.main import (
    QUALITY_BUDGETS_S, GA_GENERATIONS_CAP, GA_GUI_SEED, OPTIMIZED_EFFORT,
)

REPORT_DIR = os.path.join(HERE, "_reports")
SOFT_TTL_S = float(os.environ.get("BENCH_TTL_S", "1500"))


def _write_report(rows, note=""):
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "optimizer_tiers.json")
    with open(path, "w") as f:
        json.dump({"bar": BAR, "rows": rows, "note": note}, f, indent=2)
    print(f"report -> {path}", flush=True)


def main() -> int:
    pieces = _load_workload()  # SKIPs (exit 0) if the fixture is absent
    print(f"workload: {len(pieces)} pieces; budgets={QUALITY_BUDGETS_S}", flush=True)
    start = time.monotonic()
    rows = []

    base = auto_layout_polygon(pieces, FABRIC, "bi", FABRIC_GRAIN_DEG,
                               effort=OPTIMIZED_EFFORT)
    rows.append({"tier": "fast", "marker": round(base[1], 1), "util": round(base[2], 2)})
    print(f"fast (warm-start): L={base[1]:.1f} U={base[2]:.2f}%", flush=True)
    _write_report(rows, "warm-start only so far")

    for tier in ("better", "best"):
        if time.monotonic() - start > SOFT_TTL_S:
            _write_report(rows, f"TTL hit before {tier}")
            print(f"TTL hit; stopping before {tier}", flush=True)
            return 0
        budget = QUALITY_BUDGETS_S[tier]
        t0 = time.monotonic()
        pl, marker, util = auto_layout_polygon(
            pieces, FABRIC, "bi", FABRIC_GRAIN_DEG, effort=OPTIMIZED_EFFORT,
            ga_generations=GA_GENERATIONS_CAP, ga_max_time_s=budget, ga_seed=GA_GUI_SEED,
        )
        wall = time.monotonic() - t0
        rows.append({"tier": tier, "budget_s": budget, "marker": round(marker, 1),
                     "util": round(util, 2), "wall_s": round(wall, 1), "placed": len(pl)})
        print(f"{tier} budget={budget}s: L={marker:.1f} U={util:.2f}% "
              f"wall={wall:.0f}s placed={len(pl)}", flush=True)
        _write_report(rows)

    best_row = next(r for r in rows if r["tier"] == "best")
    better_row = next(r for r in rows if r["tier"] == "better")
    failures = []
    if best_row["marker"] > BAR:
        failures.append(f"BEST {best_row['marker']:.1f} did not beat bar {BAR}")
    if better_row["marker"] >= BAR:
        failures.append(f"BETTER {better_row['marker']:.1f} did not beat bar {BAR}")
    _write_report(rows, ("FAIL: " + "; ".join(failures)) if failures else "PASS")
    print("GATES:", ("FAIL: " + "; ".join(failures)) if failures else "PASS", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the bench (background)**

From `D:\openmarker\.worktrees\expose-optimizer\engine`:
`D:\openmarker\engine\.venv\Scripts\python.exe tests\bench_optimizer_tiers.py`
Expected: prints `fast`, `better`, `best` markers and `GATES: PASS`. Read
`engine/tests/_reports/optimizer_tiers.json` for the numbers.

- [ ] **Step 4: Lock or adjust the constants**

- If `GATES: PASS`, the 180/420 defaults are confirmed — keep them.
- If BETTER did not beat the bar within 180s, bump `QUALITY_BUDGETS_S["better"]`
  in `engine/api/main.py` (e.g. to 240.0) and re-run; record the chosen value.
- If even BEST missed at 420s (unexpected), bump `best` to 480-540s and re-run.
- Record the measured `fast`/`better`/`best` markers + walls — Task 10 writes them
  into PERFORMANCE.md.

- [ ] **Step 5: Commit**

```bash
git add engine/tests/bench_optimizer_tiers.py engine/api/main.py
git commit -m "test(engine): budget-validation bench for optimizer tiers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

(`examples/` and `engine/tests/_reports/` are git-ignored — they won't be staged.)

---

## Task 6: Frontend types

**Files:**
- Modify: `frontend/src/types/engine.ts`

- [ ] **Step 1: Add the `LayoutQuality` type**

After the `GrainMode` type (`export type GrainMode = "single" | "bi";`), add:

```typescript
// Layout quality tier sent to POST /auto-layout. "fast" = today's warm-start;
// "better"/"best" run the GA optimizer with a short/long time budget.
export type LayoutQuality = "fast" | "better" | "best";
```

- [ ] **Step 2: Add `stopped` to `AutoLayoutResponse`**

In the `AutoLayoutResponse` interface, add:

```typescript
  utilization_pct: number;
  // True when a better/best run was cancelled and fell back to the warm-start.
  stopped?: boolean;
```

- [ ] **Step 3: Type-check**

From `D:\openmarker\.worktrees\expose-optimizer\frontend`: `npx tsc --noEmit`
Expected: no new errors (the fields are additive).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/engine.ts
git commit -m "feat(frontend): LayoutQuality type + stopped on AutoLayoutResponse

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `QualityPanel` component

**Files:**
- Create: `frontend/src/components/sidebar/QualityPanel.tsx`
- Test: `frontend/src/components/sidebar/QualityPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/sidebar/QualityPanel.test.tsx` (mirrors `GrainPanel.test.tsx`):

```tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { QualityPanel } from "./QualityPanel";

describe("QualityPanel", () => {
  afterEach(() => cleanup());

  it("renders Fast, Better and Best radios", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} />);
    expect(screen.getByLabelText(/Fast/i)).toBeTruthy();
    expect(screen.getByLabelText(/Better/i)).toBeTruthy();
    expect(screen.getByLabelText(/Best/i)).toBeTruthy();
  });

  it("checks the active quality only", () => {
    render(<QualityPanel quality="best" onChange={() => {}} />);
    expect((screen.getByLabelText(/Best/i) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText(/Fast/i) as HTMLInputElement).checked).toBe(false);
  });

  it("calls onChange with the clicked value", () => {
    const onChange = vi.fn();
    render(<QualityPanel quality="fast" onChange={onChange} />);
    fireEvent.click(screen.getByLabelText(/Better/i));
    expect(onChange).toHaveBeenCalledWith("better");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

From the frontend dir: `npx vitest run src/components/sidebar/QualityPanel.test.tsx`
Expected: FAIL — module `./QualityPanel` not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/sidebar/QualityPanel.tsx`:

```tsx
import type { LayoutQuality } from "../../types/engine";

interface QualityPanelProps {
  quality: LayoutQuality;
  onChange: (q: LayoutQuality) => void;
}

const OPTIONS: { value: LayoutQuality; label: string; hint: string }[] = [
  { value: "fast", label: "Fast", hint: "instant" },
  { value: "better", label: "Better", hint: "~3 min, tighter" },
  { value: "best", label: "Best", hint: "~7 min, tightest" },
];

export function QualityPanel({ quality, onChange }: QualityPanelProps) {
  return (
    <div>
      <p style={styles.hint}>
        Higher quality packs tighter but takes minutes. Click Stop to keep the
        best result so far.
      </p>
      {OPTIONS.map((opt) => (
        <label key={opt.value} style={styles.radioRow}>
          <input
            type="radio"
            name="layout-quality"
            checked={quality === opt.value}
            onChange={() => onChange(opt.value)}
          />
          <span style={{ fontSize: 12 }}>{opt.label}</span>
          <span style={styles.optHint}>{opt.hint}</span>
        </label>
      ))}
    </div>
  );
}

const styles = {
  hint: {
    fontSize: 11,
    color: "var(--color-text-muted)",
    fontStyle: "italic" as const,
    marginTop: 0,
    marginBottom: 6,
  },
  radioRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginTop: 4,
    cursor: "pointer",
  },
  optHint: {
    fontSize: 11,
    color: "var(--color-text-muted)",
  },
} as const;
```

- [ ] **Step 4: Run it to verify it passes**

`npx vitest run src/components/sidebar/QualityPanel.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sidebar/QualityPanel.tsx frontend/src/components/sidebar/QualityPanel.test.tsx
git commit -m "feat(frontend): QualityPanel Fast/Better/Best selector

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `useAutoLayout` sends `quality`

**Files:**
- Modify: `frontend/src/hooks/useAutoLayout.ts`
- Test: `frontend/src/hooks/useAutoLayout.test.ts` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/useAutoLayout.test.ts` (mirrors `useLayoutCache.test.ts`'s fetch-spy pattern):

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAutoLayout } from "./useAutoLayout";

const okResponse = () =>
  ({
    ok: true,
    json: async () => ({
      id: "x", timestamp: "t", duration_ms: 1,
      placements: [], marker_length_mm: 1, utilization_pct: 1,
    }),
  } as Response);

function lastBody(): Record<string, unknown> {
  const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
  return JSON.parse(calls[calls.length - 1][1].body as string);
}

describe("useAutoLayout", () => {
  beforeEach(() => { vi.spyOn(globalThis, "fetch"); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("includes the given quality in the request body", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(okResponse());
    const { result } = renderHook(() => useAutoLayout());
    await act(async () => {
      await result.current.runAutoLayout(
        "f.dxf", [], 1500, "single", 90, 1, false, 1, 5, false, "best",
      );
    });
    expect(lastBody().quality).toBe("best");
  });

  it("defaults quality to fast when the arg is omitted", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(okResponse());
    const { result } = renderHook(() => useAutoLayout());
    await act(async () => {
      await result.current.runAutoLayout("f.dxf", [], 1500, "single", 90, 1);
    });
    expect(lastBody().quality).toBe("fast");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

`npx vitest run src/hooks/useAutoLayout.test.ts`
Expected: FAIL — `quality` is `undefined` in the body (param doesn't exist yet).

- [ ] **Step 3: Add the `quality` param + body field**

In `frontend/src/hooks/useAutoLayout.ts`:

Update the import to include `LayoutQuality`:

```ts
import type { Piece, GrainMode, AutoLayoutResponse, LayoutQuality } from "../types/engine";
```

Add `quality` as the last parameter of `runAutoLayout`:

```ts
      includeEffortInKey: boolean = false, // TEMP(phase6-bench)
      quality: LayoutQuality = "fast",
    ): Promise<AutoLayoutOutcome> => {
```

Add `quality` to the POST body (after `include_effort_in_key`):

```ts
            include_effort_in_key: includeEffortInKey, // TEMP(phase6-bench)
            quality,
```

- [ ] **Step 4: Run it to verify it passes**

`npx vitest run src/hooks/useAutoLayout.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useAutoLayout.ts frontend/src/hooks/useAutoLayout.test.ts
git commit -m "feat(frontend): useAutoLayout sends quality

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Wire `App.tsx` — quality state, panel, timer, stopped status

App.tsx is presentation glue with no existing unit test; verification is `tsc --noEmit` + the component/hook tests + a manual smoke. Keep edits minimal.

**Files:**
- Modify: `frontend/src/app/App.tsx`

- [ ] **Step 1: Import `QualityPanel`, `formatDuration`, and the type**

Add the imports (next to the other sidebar imports / the BottomPanel import):

```tsx
import { BottomPanel, formatDuration } from "../components/BottomPanel";
import { QualityPanel } from "../components/sidebar/QualityPanel";
```

(Replace the existing `import { BottomPanel } from "../components/BottomPanel";` line.)

And extend the engine-types import to include `LayoutQuality`:

```tsx
import type { EngineStatus, PingResponse, GrainMode, Piece, LayoutQuality } from "../types/engine";
```

- [ ] **Step 2: Add `quality` + elapsed-timer state**

After the existing `const [effort, setEffort] = useState<number>(1);` line, add:

```tsx
  const [quality, setQuality] = useState<LayoutQuality>("fast");
  const [elapsedMs, setElapsedMs] = useState<number>(0);
```

- [ ] **Step 3: Tick the elapsed timer while a layout runs**

After the existing `useEffect` that syncs the window title (the block ending with `}, [currentFileName]);`), add:

```tsx
  // Live elapsed timer while an auto-layout runs (mainly for the multi-minute
  // Better/Best tiers). Resets to 0 when not loading.
  useEffect(() => {
    if (autoStatus !== "loading") {
      setElapsedMs(0);
      return;
    }
    const startedAt = Date.now();
    setElapsedMs(0);
    const id = setInterval(() => setElapsedMs(Date.now() - startedAt), 1000);
    return () => clearInterval(id);
  }, [autoStatus]);
```

- [ ] **Step 4: Pass `quality` to `runAutoLayout` and handle `stopped`**

In `handleAutoLayout`, change the `runAutoLayout(...)` call to append `quality`:

```tsx
    const outcome = await runAutoLayout(
      currentFileName, expandedPieces, fabricWidthMm, grainMode, FABRIC_GRAIN_DEG, copies, disableNfpCache, effort, maxCacheEntries, includeEffortInKey, quality,
    );
```

Replace the `if (outcome.ok) { ... }` success branch body with one that handles `stopped`:

```tsx
    if (outcome.ok) {
      await refreshCache();
      setActiveId(outcome.data.id);
      if (outcome.data.stopped) {
        setStatusMessage("Stopped — showing best result so far.");
      } else {
        setStatusMessage(
          `Auto layout: ${outcome.data.placements.length} piece${outcome.data.placements.length !== 1 ? "s" : ""} · ` +
          `Marker: ${Math.round(outcome.data.marker_length_mm)} mm · ` +
          `Utilization: ${outcome.data.utilization_pct}%`
        );
      }
    } else if (outcome.aborted) {
```

Add `quality` to the `handleAutoLayout` `useCallback` dependency array (append `quality` to the existing deps list).

- [ ] **Step 5: Render the QualityPanel section + the elapsed timer**

Insert a new `<Section>` immediately BEFORE the existing `<Section title="Layout">`:

```tsx
          <Section title="Layout quality">
            <QualityPanel quality={quality} onChange={setQuality} />
          </Section>
```

Inside the `<Section title="Layout">`, immediately after the `autoStatus === "loading"` Stop-button block, add the elapsed indicator:

```tsx
            {autoStatus === "loading" && (
              <p style={styles.advancedHint}>
                {`Optimizing (${quality})… ${formatDuration(elapsedMs)} elapsed`}
                {quality !== "fast" ? " · this can take several minutes" : ""}
              </p>
            )}
```

- [ ] **Step 6: Type-check + run the full frontend suite**

From the frontend dir:
```
npx tsc --noEmit
npx vitest run
```
Expected: no type errors; all tests (existing + QualityPanel + useAutoLayout) PASS.

- [ ] **Step 7: Manual smoke (optional but recommended)**

Start the engine (`scripts\dev-engine.bat` from the MAIN repo, or
`D:\openmarker\engine\.venv\Scripts\python.exe api/main.py` from the worktree
engine dir) and `npm run dev` in the worktree frontend. Import a DXF, choose
**Better**, click Auto Layout, confirm the elapsed timer ticks and Stop returns a
usable layout with "Stopped — showing best result so far."

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/App.tsx
git commit -m "feat(frontend): wire quality selector + elapsed timer into App

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Docs

**Files:**
- Modify: `docs/planning/PERFORMANCE.md`, `docs/planning/BACKLOG.md`

- [ ] **Step 1: Check off the BACKLOG items**

In `docs/planning/BACKLOG.md`, change the line
`- [ ] Expose SA/GA to the GUI ...` to `- [x]`, and check off every box in the
"Expose the GA optimizer to the GUI" checklist that this plan added (see the
checklist block near that line).

- [ ] **Step 2: Add a PERFORMANCE.md § 6 entry**

Append a dated entry to `docs/planning/PERFORMANCE.md` § 6, filling the markers
from the Task 5 `_reports/optimizer_tiers.json`:

```markdown
### 2026-06-06 — GA optimizer exposed to the GUI (Fast / Better / Best)

- **What:** `POST /auto-layout` gained an optional `quality` field
  (`fast` | `better` | `best`, default `fast` = today's warm-start, bit-identical).
  `_do_layout` maps `better`/`best` to `auto_layout_polygon(ga_generations=12,
  ga_max_time_s=<budget>, ga_seed=42, effort=4)`. Budgets:
  `better=<BETTER_S>s`, `best=<BEST_S>s` (`api.main.QUALITY_BUDGETS_S`).
- **Stop:** a GA cancellation now returns the pre-computed warm-start
  (`StoppedWithWarmStart`) as HTTP 200 + `stopped=true`, cached as `fast`.
- **Cache:** `quality` joined the dedup key.
- **Frontend:** `QualityPanel` radio group + elapsed timer; SA stays engine-only.
- **Validation** (`bench_optimizer_tiers.py`, canonical workload):
  fast=<FAST_MARKER>mm, better=<BETTER_MARKER>mm (<BETTER_WALL>s),
  best=<BEST_MARKER>mm (<BEST_WALL>s) — both beat the bar (11699mm).
- **Code:** `engine/api/main.py` (tier map + stopped handling),
  `engine/core/layout/heuristic.py` (`_ga_phase_or_warm_start`),
  `engine/core/layout/cancellation.py` (`StoppedWithWarmStart`),
  `engine/core/layout/cache.py` (quality key),
  `frontend/src/components/sidebar/QualityPanel.tsx`.
  Spec: `docs/superpowers/specs/2026-06-06-expose-optimizer-gui-design.md`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git commit -m "docs: record GUI optimizer exposure + validated budgets

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Full engine suite green:
  `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit tests\integration -q`
- [ ] Full frontend suite green + types: `npx tsc --noEmit && npx vitest run`
- [ ] Omitted-`quality` regression: confirm `test_quality_fast_passes_no_ga_knobs`
  and the existing `/auto-layout` tests pass — the default path is unchanged.
- [ ] `bench_optimizer_tiers.py` printed `GATES: PASS` (or budgets were adjusted + re-validated).
- [ ] Manual smoke: Better/Best run shows the timer, Stop yields the warm-start.
- [ ] Then use superpowers:finishing-a-development-branch to open the PR.
```

