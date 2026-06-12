# Separation controls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Relabel the quality strategies to algorithm names and give the Separation tier a user budget (360–1500s) + best-of-N-seeds (1–4, parallel).

**Architecture:** Engine `run_separation_layout` gains `n_seeds` (concurrent best-of-N via a per-seed `_solve_one` helper) + a multi-process kill registry; the API gains validated `ultra_budget_s`/`ultra_seeds` fields that join the cache key; the frontend relabels `QualityPanel` and adds conditional budget/seeds controls.

**Tech Stack:** Python (concurrent.futures, subprocess) · FastAPI · React/TS/Vitest.

**Spec:** `docs/superpowers/specs/2026-06-09-separation-controls-design.md`. Branch: `feat/separation-phase2` (extends PR #16).

---

## File Structure

| File | Change |
|---|---|
| `engine/core/layout/separation.py` | multi-proc kill registry; `_solve_one`; `run_separation_layout(n_seeds)` best-of-N |
| `engine/tests/unit/test_separation.py` | multi-kill test; best-of-N selection + all-invalid tests; update kill test |
| `engine/core/layout/cache.py` | `CachedLayout` + `find_by_settings` gain `ultra_budget_s`/`ultra_seeds` |
| `engine/api/main.py` | parse/validate `ultra_budget_s`/`ultra_seeds`; route; cache key |
| `engine/tests/integration/test_api.py` | validation + routing + cache-distinguish tests |
| `engine/tests/unit/test_cache.py` | dedup distinguishes budget/seeds |
| `frontend/src/components/sidebar/QualityPanel.tsx` | algo labels + conditional budget/seeds controls |
| `frontend/src/components/sidebar/QualityPanel.test.tsx` | label + conditional-control tests |
| `frontend/src/app/App.tsx` | `ultraBudgetS`/`ultraSeeds` state + wiring |
| `frontend/src/hooks/useAutoLayout.ts` | pass `ultra_budget_s`/`ultra_seeds` in POST body |

---

## Task A: Engine — multi-process kill registry

**Files:** `engine/core/layout/separation.py`, `engine/tests/unit/test_separation.py`.

- [ ] **Step 1: Update the failing test** — REPLACE the existing `test_kill_current_sparrow_terminates_registered_proc` in `test_separation.py` with these two (the registry API changes from `_set_current_sparrow` to `_register_sparrow`/`_unregister_sparrow`):
```python
def test_kill_current_sparrow_terminates_one():
    class _Dummy:
        def __init__(self): self.killed = False
        def terminate(self): self.killed = True
    d = _Dummy()
    sep._register_sparrow(d)
    sep.kill_current_sparrow()
    assert d.killed is True
    sep._unregister_sparrow(d)
    sep.kill_current_sparrow()  # no-op when empty


def test_kill_current_sparrow_terminates_all_concurrent():
    class _Dummy:
        def __init__(self): self.killed = False
        def terminate(self): self.killed = True
    a, b = _Dummy(), _Dummy()
    sep._register_sparrow(a); sep._register_sparrow(b)
    sep.kill_current_sparrow()
    assert a.killed and b.killed
    sep._unregister_sparrow(a); sep._unregister_sparrow(b)
```

- [ ] **Step 2: Run, confirm FAIL**
Run: `engine/.venv/Scripts/pytest engine/tests/unit/test_separation.py -v -k kill`
Expected: FAIL — `AttributeError: ... '_register_sparrow'`.

- [ ] **Step 3: Refactor the registry** in `separation.py`. REPLACE the `_sparrow_lock`/`_current_sparrow`/`_set_current_sparrow`/`kill_current_sparrow` block with:
```python
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
```
Then in `_run_sparrow`, change the registration calls: `_set_current_sparrow(proc)` → `_register_sparrow(proc)`, and the `finally: _set_current_sparrow(None)` → `finally: _unregister_sparrow(proc)`.

- [ ] **Step 4: Run, confirm PASS**
Run: `engine/.venv/Scripts/pytest engine/tests/unit/test_separation.py -v` then `engine/.venv/Scripts/pytest engine/tests/unit -q` (expect prior count − 1 + 2 = +1 net; all pass).
Also run integration to confirm the real cancel still works: `engine/.venv/Scripts/pytest engine/tests/integration/test_separation_sidecar.py -v` (3 pass).

- [ ] **Step 5: Commit**
```
git add engine/core/layout/separation.py engine/tests/unit/test_separation.py
git commit -m "refactor(separation): multi-process kill registry (set of Popens)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task B: Engine — best-of-N-seeds in run_separation_layout

**Files:** `engine/core/layout/separation.py`, `engine/tests/unit/test_separation.py`.

- [ ] **Step 1: Write the failing tests** — APPEND to `test_separation.py`:
```python
from concurrent.futures import ThreadPoolExecutor  # noqa: F401  (ensures import is available)
from core.layout.heuristic import Placement as _Pl


def test_best_of_n_returns_shortest_valid(monkeypatch):
    calls = []
    def fake_solve(items, instance, pieces, fw, gm, fg, budget_s, seed):
        calls.append(seed)
        marker = {42: 1000.0, 43: 800.0, 44: 1200.0}[seed]
        return ([_Pl("p__c0", 0.0, 0.0, 0.0)], marker, 50.0)
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    pieces = [_rect("p__c0", 60, 40, 90.0)]
    placements, marker, util = sep.run_separation_layout(
        pieces, 200.0, "bi", 90.0, budget_s=5, seed=42, n_seeds=3)
    assert sorted(calls) == [42, 43, 44]
    assert marker == 800.0   # shortest valid wins


def test_best_of_n_all_invalid_raises(monkeypatch):
    def fake_solve(*a, **k):
        raise ValueError("separation layout invalid: off-grain")
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    with pytest.raises(ValueError, match="all separation attempts invalid"):
        sep.run_separation_layout([_rect("p__c0", 60, 40, 90.0)], 200.0, "bi", 90.0,
                                  budget_s=5, seed=42, n_seeds=2)
```

- [ ] **Step 2: Run, confirm FAIL**
Run: `engine/.venv/Scripts/pytest engine/tests/unit/test_separation.py -v -k best_of_n`
Expected: FAIL — `run_separation_layout()` has no `n_seeds`, and/or `_solve_one` missing.

- [ ] **Step 3: Refactor `run_separation_layout`** in `separation.py`. Add the import at the top (with the other stdlib imports): `from concurrent.futures import ThreadPoolExecutor, as_completed`. Then REPLACE the existing `run_separation_layout` with:
```python
def _solve_one(items, instance, pieces, fabric_width_mm, grain_mode, fabric_grain_deg,
               budget_s, seed):
    """One sparrow attempt: run -> reconstruct -> validate -> metrics. Raises
    CancellationError on kill, ValueError on invalid/empty output."""
    solution = _run_sparrow(instance, budget_s, seed)
    placements = _reconstruct(solution, items, fabric_width_mm)
    _validate_layout(placements, pieces, fabric_width_mm, grain_mode, fabric_grain_deg)
    marker_length, utilization = _compute_metrics(placements, pieces, fabric_width_mm, _polygon_dims)
    return placements, marker_length, utilization


def run_separation_layout(pieces: list[Piece], fabric_width_mm: float, grain_mode: str,
                          fabric_grain_deg: float, budget_s: float, seed: int = 42,
                          n_seeds: int = 1) -> tuple[list[Placement], float, float]:
    """Run the separation (sparrow) engine. With n_seeds>1, run that many attempts
    (seeds seed..seed+n_seeds-1) IN PARALLEL and keep the shortest VALID marker.
    Mirrors auto_layout_polygon's return. Raises CancellationError on kill (->499);
    ValueError on empty input or when every attempt is invalid (->400)."""
    if not pieces:
        raise ValueError("no pieces to lay out")
    items = _group_to_items(pieces, grain_mode, fabric_grain_deg)
    instance = _instance_json(items, fabric_width_mm - 2 * EDGE_GAP)
    seeds = [seed + k for k in range(max(1, n_seeds))]

    if len(seeds) == 1:
        return _solve_one(items, instance, pieces, fabric_width_mm, grain_mode,
                          fabric_grain_deg, budget_s, seeds[0])

    results: list[tuple] = []
    errors: list[str] = []
    cancelled = False
    with ThreadPoolExecutor(max_workers=len(seeds)) as ex:
        futures = [ex.submit(_solve_one, items, instance, pieces, fabric_width_mm,
                             grain_mode, fabric_grain_deg, budget_s, s) for s in seeds]
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except CancellationError:
                cancelled = True
            except ValueError as e:
                errors.append(str(e))
    if cancelled:
        raise CancellationError("separation run cancelled")
    if not results:
        raise ValueError("all separation attempts invalid: " + "; ".join(errors[:3]))
    return min(results, key=lambda r: r[1])  # shortest marker_length
```

- [ ] **Step 4: Run, confirm PASS**
Run: `engine/.venv/Scripts/pytest engine/tests/unit/test_separation.py -v` (best-of-N + the prior assembly test still pass — the n_seeds=1 path still routes through `_run_sparrow` via `_solve_one`).
Then `engine/.venv/Scripts/pytest engine/tests/unit engine/tests/integration -q` (all pass incl. 3 integration).

- [ ] **Step 5: Commit**
```
git add engine/core/layout/separation.py engine/tests/unit/test_separation.py
git commit -m "feat(separation): best-of-N-seeds (parallel, keep shortest valid marker)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task C: API + cache — ultra_budget_s / ultra_seeds

**Files:** `engine/core/layout/cache.py`, `engine/api/main.py`, `engine/tests/integration/test_api.py`, `engine/tests/unit/test_cache.py`.

- [ ] **Step 1: Write the failing tests.**
APPEND to `engine/tests/unit/test_cache.py` (mirror the file's existing CachedLayout construction + `reset_cache`/`get_cache` usage; inspect the top of the file first):
```python
def test_dedup_distinguishes_ultra_budget_and_seeds():
    from core.layout.cache import LayoutCache, CachedLayout
    c = LayoutCache()
    def mk(bid, budget, seeds):
        return CachedLayout(id=bid, filename="f.dxf", timestamp="t", grain_mode="bi",
                            copies=1, fabric_width_mm=1651.0, placements=[], marker_length_mm=1.0,
                            utilization_pct=1.0, duration_ms=1, created_at=0.0, quality="ultra",
                            ultra_budget_s=budget, ultra_seeds=seeds)
    c.insert(mk("a", 600.0, 1)); c.insert(mk("b", 600.0, 3)); c.insert(mk("d", 900.0, 1))
    assert c.find_by_settings("f.dxf", "bi", 1, 1651.0, "ultra", ultra_budget_s=600.0, ultra_seeds=1).id == "a"
    assert c.find_by_settings("f.dxf", "bi", 1, 1651.0, "ultra", ultra_budget_s=600.0, ultra_seeds=3).id == "b"
    assert c.find_by_settings("f.dxf", "bi", 1, 1651.0, "ultra", ultra_budget_s=900.0, ultra_seeds=1).id == "d"
    assert c.find_by_settings("f.dxf", "bi", 1, 1651.0, "ultra", ultra_budget_s=1200.0, ultra_seeds=1) is None
```
APPEND to `engine/tests/integration/test_api.py` (mirror the inline `AsyncClient` + `_one_piece_body` pattern; add a `quality`/budget/seeds-parameterized body helper or extend `_one_piece_body`):
```python
async def test_ultra_budget_out_of_range_422(client):  # adapt to inline AsyncClient pattern
    for bad in (359, 1501):
        body = _one_piece_body(quality="ultra"); body["ultra_budget_s"] = bad
        resp = await _post(body)  # use the file's existing POST helper/pattern
        assert resp.status_code == 422

async def test_ultra_seeds_out_of_range_422():
    for bad in (0, 5):
        body = _one_piece_body(quality="ultra"); body["ultra_seeds"] = bad
        resp = await _post(body)
        assert resp.status_code == 422

async def test_ultra_passes_budget_and_seeds(monkeypatch):
    import api.main as main
    captured = {}
    def _stub(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, budget_s, seed=42, n_seeds=1):
        captured["budget_s"] = budget_s; captured["n_seeds"] = n_seeds
        from core.layout.heuristic import Placement
        return [Placement(pieces[0].id, 10.0, 10.0, 0.0)], 99.0, 50.0
    monkeypatch.setattr(main, "run_separation_layout", _stub)
    body = _one_piece_body(quality="ultra"); body["ultra_budget_s"] = 900; body["ultra_seeds"] = 3
    resp = await _post(body)
    assert resp.status_code == 200
    assert captured == {"budget_s": 900.0, "n_seeds": 3}
```
(Adapt `_post`/`client` to whatever the file already uses — inspect it first; do NOT invent a fixture that doesn't exist.)

- [ ] **Step 2: Run, confirm FAIL**
Run: `engine/.venv/Scripts/pytest engine/tests/unit/test_cache.py engine/tests/integration/test_api.py -v -k "ultra or budget or seeds"`
Expected: FAIL (CachedLayout has no `ultra_budget_s`; 422 not raised; stub args missing).

- [ ] **Step 3a: Extend the cache** (`engine/core/layout/cache.py`).
Add two fields to `CachedLayout` after `quality` (defaults keep existing constructions valid):
```python
    quality: str = "fast"
    # Separation ("ultra") run parameters — part of the dedup key so different
    # budget/seeds produce distinct entries. Defaults match non-ultra requests.
    ultra_budget_s: float = 600.0
    ultra_seeds: int = 1
```
In `find_by_settings`, add params + matching. Change the signature to:
```python
    def find_by_settings(
        self,
        filename: str,
        grain_mode: str,
        copies: int,
        fabric_width_mm: float,
        quality: str = "fast",
        effort: int | None = None,
        ultra_budget_s: float = 600.0,
        ultra_seeds: int = 1,
    ) -> CachedLayout | None:
```
And in the match loop, add to the `if not (... e.quality == quality):` conjunction:
```python
                    and e.quality == quality
                    and e.ultra_budget_s == ultra_budget_s
                    and e.ultra_seeds == ultra_seeds):
```

- [ ] **Step 3b: Wire the API** (`engine/api/main.py`).
After the existing `quality` parse/validate block, add:
```python
    ultra_budget_s = body.get("ultra_budget_s", QUALITY_BUDGETS_S["ultra"])
    try:
        ultra_budget_s = float(ultra_budget_s)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="`ultra_budget_s` must be a number")
    if ultra_budget_s < 360 or ultra_budget_s > 1500:
        raise HTTPException(status_code=422, detail=f"`ultra_budget_s` must be 360..1500, got {ultra_budget_s}")
    try:
        ultra_seeds = int(body.get("ultra_seeds", 1))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="`ultra_seeds` must be an integer")
    if ultra_seeds < 1 or ultra_seeds > 4:
        raise HTTPException(status_code=422, detail=f"`ultra_seeds` must be 1..4, got {ultra_seeds}")
```
Update the dedup lookup `get_cache().find_by_settings(...)` call to pass `ultra_budget_s=ultra_budget_s, ultra_seeds=ultra_seeds`.
Update the ultra branch in `_do_layout`:
```python
        if quality == "ultra":
            return run_separation_layout(
                pieces, fabric_width_mm, grain_mode, FABRIC_GRAIN_DEG,
                budget_s=ultra_budget_s, seed=GA_GUI_SEED, n_seeds=ultra_seeds,
            )
```
Add `ultra_budget_s=ultra_budget_s, ultra_seeds=ultra_seeds` to the `CachedLayout(...)` construction.

- [ ] **Step 4: Run, confirm PASS**
Run: `engine/.venv/Scripts/pytest engine/tests/unit/test_cache.py engine/tests/integration/test_api.py -v` then `engine/.venv/Scripts/pytest engine/tests/unit engine/tests/integration -q` (all pass).

- [ ] **Step 5: Commit**
```
git add engine/core/layout/cache.py engine/api/main.py engine/tests/integration/test_api.py engine/tests/unit/test_cache.py
git commit -m "feat(api): ultra_budget_s (360-1500) + ultra_seeds (1-4) + cache key

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task D: Frontend — relabel + conditional budget/seeds controls

**Files:** `frontend/src/components/sidebar/QualityPanel.tsx` (+ test), `frontend/src/app/App.tsx`, `frontend/src/hooks/useAutoLayout.ts`.

- [ ] **Step 1: Write the failing tests** — APPEND inside the `describe` in `QualityPanel.test.tsx`. The panel will take new props `ultraBudgetS`, `onUltraBudgetChange`, `ultraSeeds`, `onUltraSeedsChange`:
```tsx
  const sepProps = { ultraBudgetS: 600, onUltraBudgetChange: () => {}, ultraSeeds: 1, onUltraSeedsChange: () => {} };

  it("shows algorithm names", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} {...sepProps} />);
    expect(screen.getByLabelText(/NFP-BLF/i)).toBeTruthy();
    expect(screen.getByLabelText(/Genetic Algorithm.*quick/i)).toBeTruthy();
    expect(screen.getByLabelText(/Genetic Algorithm.*thorough/i)).toBeTruthy();
    expect(screen.getByLabelText(/Separation/i)).toBeTruthy();
  });

  it("hides Separation controls unless Separation is selected", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} {...sepProps} />);
    expect(screen.queryByLabelText(/time budget/i)).toBeNull();
  });

  it("shows budget + seeds controls when Separation selected", () => {
    render(<QualityPanel quality="ultra" onChange={() => {}} {...sepProps} />);
    expect(screen.getByLabelText(/time budget/i)).toBeTruthy();
    expect(screen.getByLabelText(/seeds/i)).toBeTruthy();
  });
```

- [ ] **Step 2: Run, confirm FAIL** — `cd frontend && npm run test -- QualityPanel` (new tests fail; labels/controls missing).

- [ ] **Step 3: Implement `QualityPanel.tsx`.** Read the current file, then:
  - Update `OPTIONS` to the algorithm names:
```typescript
const OPTIONS: { value: LayoutQuality; label: string; hint: string }[] = [
  { value: "fast", label: "NFP-BLF", hint: "constructive" },
  { value: "better", label: "Genetic Algorithm — quick", hint: "180s" },
  { value: "best", label: "Genetic Algorithm — thorough", hint: "420s" },
  { value: "ultra", label: "Separation (sparrow)", hint: "best-of-N" },
];
```
  - Extend `QualityPanelProps` with `ultraBudgetS: number; onUltraBudgetChange: (n: number) => void; ultraSeeds: number; onUltraSeedsChange: (n: number) => void;`.
  - After the radios map, add a conditional block (clamp budget to [360,1500] on change; seeds radio 1–4):
```tsx
      {quality === "ultra" && (
        <div style={styles.sepControls}>
          <label style={styles.fieldRow}>
            <span style={{ fontSize: 13 }}>Time budget (s)</span>
            <input
              type="number" min={360} max={1500} step={30}
              aria-label="time budget seconds"
              value={ultraBudgetS}
              onChange={(e) => {
                const v = Math.round(Number(e.target.value));
                if (!Number.isNaN(v)) onUltraBudgetChange(Math.min(1500, Math.max(360, v)));
              }}
              style={{ width: 70 }}
            />
          </label>
          <div style={{ fontSize: 13, marginTop: 6 }} aria-label="seeds">Seeds (best of N)</div>
          {[1, 2, 3, 4].map((n) => (
            <label key={n} style={styles.radioRow}>
              <input type="radio" name="ultra-seeds" checked={ultraSeeds === n}
                     onChange={() => onUltraSeedsChange(n)} />
              <span style={{ fontSize: 13 }}>{n}</span>
            </label>
          ))}
        </div>
      )}
```
  - Add `sepControls` + `fieldRow` to the `styles` object (e.g. `sepControls: { marginTop: 8, paddingTop: 6, borderTop: "1px solid var(--color-border, #ddd)" }`, `fieldRow: { display: "flex", alignItems: "center", gap: 6, marginTop: 4 }`).

- [ ] **Step 4: Wire `App.tsx` + `useAutoLayout.ts`.**
  - `App.tsx`: add `const [ultraBudgetS, setUltraBudgetS] = useState(600);` and `const [ultraSeeds, setUltraSeeds] = useState(1);`. Pass the 4 new props into `<QualityPanel .../>`. Add `ultraBudgetS, ultraSeeds` to the `runAutoLayout(...)` call args and to its `useCallback` dependency array.
  - `useAutoLayout.ts`: add params `ultraBudgetS: number = 600, ultraSeeds: number = 1` to `runAutoLayout`, and include `ultra_budget_s: ultraBudgetS, ultra_seeds: ultraSeeds` in the POST `body`.

- [ ] **Step 5: Run, confirm PASS + build** — `cd frontend && npm run test -- QualityPanel` (pass) then `npm run build` (tsc+vite clean — the new props must be threaded through without type errors).

- [ ] **Step 6: Commit**
```
git add frontend/src/components/sidebar/QualityPanel.tsx frontend/src/components/sidebar/QualityPanel.test.tsx frontend/src/app/App.tsx frontend/src/hooks/useAutoLayout.ts
git commit -m "feat(frontend): algorithm-name strategy labels + Separation budget/seeds controls

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task E: Docs + final review

**Files:** `docs/planning/PERFORMANCE.md`, `docs/planning/BACKLOG.md`.

- [ ] **Step 1 (optional bench):** measure the seeds lever — `engine/.venv/Scripts/python.exe engine/tests/bench_separation.py` won't cover n_seeds; SKIP unless extending the bench. Instead, note the design rationale (best-of-N > longer single budget) already in PERFORMANCE.md §6 [2026-06-09].
- [ ] **Step 2:** Append a short PERFORMANCE.md §6 note dated 2026-06-09: the GUI now exposes algorithm names + a 360–1500s Separation budget + best-of-N-seeds (1–4, parallel, keep shortest valid); multi-process kill; budget/seeds in the cache key.
- [ ] **Step 3:** Update BACKLOG: under the Phase-2 entry, check off "GUI controls: strategy names + Separation budget + best-of-N-seeds"; note spec `docs/superpowers/specs/2026-06-09-separation-controls-design.md`.
- [ ] **Step 4: Commit**
```
git add docs/planning/PERFORMANCE.md docs/planning/BACKLOG.md
git commit -m "docs(separation): record GUI controls (algo names, budget, best-of-N)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
- [ ] **Step 5: Final review** — run the full engine suite + frontend build, then a whole-diff review of Tasks A–E vs this spec.

---

## Self-Review

**Spec coverage:** §3 labels → Task D; §4 frontend controls → Task D; §5 engine best-of-N + multi-kill → Tasks A, B; §6 API/cache → Task C; §8 testing → each task is TDD. All covered.

**Placeholder scan:** The API test helpers (`_post`, `_one_piece_body`) reference the existing `test_api.py` conventions — the implementer is told to inspect and adapt rather than invent; this is integration guidance, not a code placeholder. No TBDs.

**Type consistency:** `run_separation_layout(..., budget_s, seed=42, n_seeds=1)` and `_solve_one(items, instance, pieces, fabric_width_mm, grain_mode, fabric_grain_deg, budget_s, seed)` match between Task B's def, the Task B tests' monkeypatch, and Task C's API stub. `_register_sparrow`/`_unregister_sparrow`/`kill_current_sparrow` consistent (A). `ultra_budget_s`/`ultra_seeds` consistent across cache (C-3a), API (C-3b), and frontend body (D-4). `QualityPanel` new props consistent between test (D-1) and impl (D-3/D-4).
