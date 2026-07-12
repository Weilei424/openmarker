# Sequential Best-of-N Ultra Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Productize the PR #23-validated seq3 policy: Ultra best-of-N runs its members SEQUENTIALLY (one 3-thread sparrow at a time), Stop returns the best completed member, and multi-hour runs get real progress in the GUI.

**Architecture:** `run_separation_layout` swaps its `ThreadPoolExecutor` for a sequential keep-best loop that reports through a new module-level progress snapshot (`core/layout/progress.py`); the API reads that snapshot for stop-outcome response fields and serves it at `GET /layout-progress`; the frontend makes Stop quality-aware (Ultra keeps the fetch open to receive the partial), polls progress, and surfaces honest copy. No algorithm change — no benches; TDD feature work.

**Tech Stack:** Python 3.11 (engine venv) + FastAPI, React/TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-07-12-seq-best-of-n-design.md` (approved 2026-07-12, incl. the truthful-cache-key amendment).

## Global Constraints

- Sequential REPLACES parallel in `run_separation_layout`; signature unchanged; `budget_s` is **per-member**; member seeds `seed..seed+n_seeds−1` (API passes seed=42); ONE shared warm start (gate unchanged: `budget_s >= WARM_START_MIN_BUDGET_S`); each member gets the full `budget_s`.
- Stop semantics: cancel mid-run with ≥1 completed member → **return the best completed member**; zero completed → `CancellationError` (→499). Member `ValueError` → skip and continue; all invalid → `ValueError` (→400). `n_seeds=1` behaves exactly as today. **This deliberately inverts the old "cancel discards results" contract** — the spec's Stop-transport decision; the old test `test_best_of_n_cancel_takes_precedence` is REPLACED, not preserved.
- Progress: `core/layout/progress.py` module-level snapshot, atomic single-assignment swap; the run writes a **final snapshot on every exit path** (`active: False`, counts preserved, `stopped_early` set) and never wipes it; `clear_progress()` is test-isolation only. Single-flight assumption (one layout at a time) documented.
- API: ultra success responses gain `stopped_early: bool`, `members_completed: int`, `members_requested: int`. **Truthful cache key on stop:** a `stopped_early` entry is stored with `ultra_seeds = members_completed`; full completions cache unchanged. New `GET /layout-progress` (snapshot + computed `total_elapsed_s`/`member_elapsed_s`; `{"active": false, ...}` when idle). Validation unchanged (`ultra_budget_s` 180–2500, `ultra_seeds` 1–4). 499/400 paths unchanged.
- Frontend: `abort()` quality-aware — Ultra posts `/cancel-layout` and keeps the fetch open (a 499 maps to the aborted outcome); other tiers abort as today. `useLayoutProgress` polls every **2000ms** only while an Ultra run is loading. Statusbar copy: `Separation run {member} of {n} — {elapsed} elapsed — best so far {marker} mm` (best omitted until a member completes); stop message `Stopped — kept best of {k} completed run(s). `; QualityPanel seeds label → **"Runs (keep best of N)"** + total-time hint `Total ≈ {m}m {s}s ({N} × {budget}s)`.
- Hard constraints unchanged everywhere: grain both ways, no mirror, no tilt, edges touchable, `_validate_layout` gates every member.
- **Round record: BACKLOG section ONLY — do NOT create or append to PERFORMANCE.md** (per user, 2026-07-12).
- Engine baseline: exactly **259 passed** before this round; suite grows and must stay green. Frontend: all existing vitest tests stay green.
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Context for implementers

- `WT` = the worktree root the user created: `D:\openmarker\.worktrees\openmarker-seq-best-of-n`, branch `feat/seq-best-of-n`; main tree stays on `main` at `D:\openmarker`.
- Engine venv ONLY in the main tree: `D:\openmarker\engine\.venv\Scripts\python.exe`; pytest as `python -m pytest` with CWD `WT\engine`.
- Frontend: `cd WT\frontend`, `npm install` once (node_modules is not in git), then `npm run test` (vitest) and `npm run build` (tsc + vite).
- Fixtures are NOT in git — Task 1 copies all of `D:\openmarker\examples\input\`.
- Key existing code (verified 2026-07-12): `engine/core/layout/separation.py:350-393` (`run_separation_layout`, parallel), `:280-289` (`_solve_one`), `:17` (executor import to remove; `import time` is ABSENT — add it); `engine/api/main.py:110-330` (handler; cache store at `:294-317`, 499 at `:278-282`); `engine/tests/unit/test_separation.py:200-266` (section to rewrite); `frontend/src/hooks/useAutoLayout.ts` (abort at `:85-88`); `frontend/src/app/App.tsx` (`handleAutoLayout` `:164-182`, loading hint `:345-352`); `frontend/src/components/sidebar/QualityPanel.tsx`. Existing test files to EXTEND (keep their conventions): `frontend/src/hooks/useAutoLayout.test.ts`, `frontend/src/components/sidebar/QualityPanel.test.tsx`, `engine/tests/integration/test_separation_sidecar.py`.

---

### Task 1: Worktree preflight + docs on branch

**Files:**
- Create (copy in, gitignored): all of `WT\examples\input\`
- Create (committed): `WT\docs\superpowers\specs\2026-07-12-seq-best-of-n-design.md`, `WT\docs\superpowers\plans\2026-07-12-seq-best-of-n.md` (copied from the main tree)
- Modify: `WT\docs\planning\BACKLOG.md` (append the productization section — the worktree forked from committed main and does NOT have main's uncommitted working-copy edit)

**Interfaces:**
- Consumes: nothing.
- Produces: verified worktree; spec/plan/BACKLOG committed on `feat/seq-best-of-n`.

- [ ] **Step 1: Verify worktree + branch**

```powershell
cd D:\openmarker\.worktrees\openmarker-seq-best-of-n
git rev-parse --abbrev-ref HEAD
git status --short
```
Expected: `feat/seq-best-of-n`, clean. If missing, STOP and ask the user to create it.

- [ ] **Step 2: Copy fixtures + install frontend deps**

```powershell
New-Item -ItemType Directory -Force WT\examples\input
Copy-Item D:\openmarker\examples\input\* WT\examples\input\ -Force
cd WT\frontend
npm install
```

- [ ] **Step 3: Baseline suites**

```powershell
cd WT\engine
D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v
cd WT\frontend
npm run test
```
Expected: engine **259 passed**; frontend all passing (note the count for later comparison). Any failure = pre-existing breakage — STOP and report.

- [ ] **Step 4: Copy spec + plan into the worktree**

```powershell
Copy-Item D:\openmarker\docs\superpowers\specs\2026-07-12-seq-best-of-n-design.md WT\docs\superpowers\specs\
Copy-Item D:\openmarker\docs\superpowers\plans\2026-07-12-seq-best-of-n.md WT\docs\superpowers\plans\
```

- [ ] **Step 5: Append to `WT\docs\planning\BACKLOG.md`** — first, in the race+fork section, extend the GO follow-up line (which ends `— separate spec/plan/PR.`) with ` (IN PROGRESS — see the productization section below.)`; then append at the end of the file:

```markdown
### Sequential best-of-N productization (GO follow-up from PR #23)

Round conventions (per user, 2026-07-12): this is a FEATURE round, not an experiment round — **no PERFORMANCE.md entry**; this BACKLOG section is the round record. Spec: `docs/superpowers/specs/2026-07-12-seq-best-of-n-design.md`; plan: `docs/superpowers/plans/2026-07-12-seq-best-of-n.md`.

- [ ] P1: Worktree preflight + spec/plan/BACKLOG committed on branch
- [ ] P2: Engine progress module (core/layout/progress.py)
- [ ] P3: Engine sequential orchestration + stop-best-so-far (run_separation_layout)
- [ ] P4: API — response flags, truthful-key partial caching, GET /layout-progress
- [ ] P5: Frontend — quality-aware Stop + response types
- [ ] P6: Frontend — progress polling + statusbar + QualityPanel copy
- [ ] P7: Real-sparrow sequential integration + full suites green
- [ ] P8: Docs (CLAUDE.md + BACKLOG ticks/outcome — NO PERFORMANCE.md), PR, final review
```

- [ ] **Step 6: Commit**

```powershell
cd WT
git add docs/superpowers/specs/2026-07-12-seq-best-of-n-design.md docs/superpowers/plans/2026-07-12-seq-best-of-n.md docs/planning/BACKLOG.md
git commit -m "docs: spec + plan + BACKLOG checklist for the sequential best-of-N round

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Engine progress module

**Files:**
- Create: `WT\engine\core\layout\progress.py`
- Test: `WT\engine\tests\unit\test_progress.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `set_progress(**fields) -> None` (replaces the snapshot), `get_progress() -> dict` (current snapshot, never mutated in place), `clear_progress() -> None` (reset to `{"active": False}`; test isolation only). Tasks 3/4 import these.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for core.layout.progress — the single-flight layout progress snapshot."""
import core.layout.progress as prog


def setup_function(_fn):
    prog.clear_progress()


def test_idle_default():
    assert prog.get_progress() == {"active": False}


def test_set_get_roundtrip():
    prog.set_progress(active=True, member=2, n_members=3, members_completed=1,
                      best_marker_mm=10552.0, budget_s=2500.0,
                      run_started_ts=1000.0, member_started_ts=2000.0,
                      stopped_early=False)
    snap = prog.get_progress()
    assert snap["active"] is True and snap["member"] == 2
    assert snap["members_completed"] == 1 and snap["best_marker_mm"] == 10552.0


def test_set_replaces_whole_snapshot():
    prog.set_progress(active=True, member=1, n_members=3)
    prog.set_progress(active=False, stopped_early=True)
    snap = prog.get_progress()
    assert snap == {"active": False, "stopped_early": True}   # no 'member' leftover


def test_get_returns_snapshot_not_live_reference():
    prog.set_progress(active=True, member=1)
    snap = prog.get_progress()
    snap["member"] = 99
    assert prog.get_progress()["member"] == 1


def test_clear_resets_to_idle():
    prog.set_progress(active=True, member=1)
    prog.clear_progress()
    assert prog.get_progress() == {"active": False}
```

- [ ] **Step 2: Run to verify failure**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_progress.py -v` (CWD `WT\engine`)
Expected: FAIL — `ModuleNotFoundError: No module named 'core.layout.progress'`.

- [ ] **Step 3: Implement the module**

```python
"""Module-level progress snapshot for the (single-flight) layout run.

The desktop app runs one layout at a time — it already has ONE global
cancellation flag and one engine process — and this module mirrors that
assumption: one module-level snapshot, replaced by a single assignment so
readers never observe a half-written dict. `get_progress` returns a copy so
callers cannot mutate the live snapshot.
"""
from __future__ import annotations

_IDLE: dict = {"active": False}
_snapshot: dict = dict(_IDLE)


def set_progress(**fields) -> None:
    """Replace the whole snapshot (atomic single assignment)."""
    global _snapshot
    _snapshot = dict(fields)


def get_progress() -> dict:
    """Return a copy of the current snapshot."""
    return dict(_snapshot)


def clear_progress() -> None:
    """Reset to idle. For test isolation only — the run path never clears;
    it leaves a final snapshot that the next run overwrites."""
    global _snapshot
    _snapshot = dict(_IDLE)
```

- [ ] **Step 4: Run to verify pass**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_progress.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```powershell
cd WT
git add engine/core/layout/progress.py engine/tests/unit/test_progress.py
git commit -m "feat(engine): module-level layout progress snapshot

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Engine sequential orchestration + stop-best-so-far

**Files:**
- Modify: `WT\engine\core\layout\separation.py` (imports + `run_separation_layout` body, currently `:350-393`)
- Test: `WT\engine\tests\unit\test_separation.py` (rewrite the `# --- run_separation_layout ---` section, currently `:200-266`)

**Interfaces:**
- Consumes: `progress.set_progress` (Task 2); existing `_solve_one`, `_group_to_items`, `_instance_json`, `_build_warm_start`, `CancellationError`.
- Produces: `run_separation_layout(...)` with the NEW cancel contract (returns best completed member on mid-run cancel; final progress snapshot carries `stopped_early`/`members_completed`). Signature unchanged. Task 4 relies on the final-snapshot contract; Task 7's integration test relies on sequential wall time.

- [ ] **Step 1: Rewrite the test section** — replace everything from `# --- run_separation_layout ---` (line 200) through `test_best_of_n_cancel_takes_precedence` (line 266) with:

```python
# --- run_separation_layout ---

import core.layout.separation as sep_mod
import core.layout.progress as prog
from core.layout.cancellation import CancellationError
from core.layout.heuristic import Placement as _Pl


@pytest.fixture(autouse=True)
def _fresh_progress():
    prog.clear_progress()
    yield
    prog.clear_progress()


def test_run_separation_layout_assembles(monkeypatch):
    pieces = [_rect("piece_0__c0", 60, 40, 90.0), _rect("piece_0__c1", 60, 40, 90.0)]
    items = sep_mod._group_to_items(pieces, "bi", 90.0)
    w = items[0].emitted.bounds[2]
    h = items[0].emitted.bounds[3]
    fabric = h
    canned = {"solution": {"strip_width": 2 * w, "layout": {"placed_items": [
        {"item_id": 0, "transformation": {"rotation": 0.0,   "translation": [0.0, 0.0]}},
        {"item_id": 0, "transformation": {"rotation": 180.0, "translation": [2 * w, h]}},
    ]}}}
    monkeypatch.setattr(sep_mod, "_run_sparrow", lambda instance, budget_s, seed: canned)
    placements, marker, util = sep_mod.run_separation_layout(
        pieces, fabric_width_mm=fabric, grain_mode="bi", fabric_grain_deg=90.0,
        budget_s=5, seed=42, warm_start=False)
    assert {p.piece_id for p in placements} == {"piece_0__c0", "piece_0__c1"}
    assert marker > 0 and 0 < util <= 100
    assert all(round(p.rotation_deg) % 180 == 0 for p in placements)


def test_run_separation_layout_empty_raises():
    with pytest.raises(ValueError, match="no pieces"):
        sep_mod.run_separation_layout([], 200.0, "bi", 90.0, budget_s=5)


def test_best_of_n_sequential_order_and_shortest_valid(monkeypatch):
    calls = []
    def fake_solve(items, instance, pieces, fw, gm, fg, budget_s, seed):
        calls.append(seed)
        marker = {42: 1000.0, 43: 800.0, 44: 1200.0}[seed]
        return ([_Pl("p__c0", 0.0, 0.0, 0.0)], marker, 50.0)
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    pieces = [_rect("p__c0", 60, 40, 90.0)]
    placements, marker, util = sep.run_separation_layout(
        pieces, 200.0, "bi", 90.0, budget_s=5, seed=42, n_seeds=3, warm_start=False)
    assert calls == [42, 43, 44]     # strictly sequential, in seed order
    assert marker == 800.0           # shortest valid wins
    snap = prog.get_progress()
    assert snap["active"] is False and snap["members_completed"] == 3
    assert snap["stopped_early"] is False and snap["best_marker_mm"] == 800.0


def test_best_of_n_all_invalid_raises(monkeypatch):
    def fake_solve(*a, **k):
        raise ValueError("separation layout invalid: off-grain")
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    with pytest.raises(ValueError, match="all separation attempts invalid"):
        sep.run_separation_layout([_rect("p__c0", 60, 40, 90.0)], 200.0, "bi", 90.0,
                                  budget_s=5, seed=42, n_seeds=2, warm_start=False)


def test_invalid_member_skipped_run_continues(monkeypatch):
    def fake_solve(items, instance, pieces, fw, gm, fg, budget_s, seed):
        if seed == 42:
            raise ValueError("separation layout invalid: overlap")
        return ([_Pl("p__c0", 0.0, 0.0, 0.0)], 800.0, 50.0)
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    placements, marker, util = sep.run_separation_layout(
        [_rect("p__c0", 60, 40, 90.0)], 200.0, "bi", 90.0,
        budget_s=5, seed=42, n_seeds=2, warm_start=False)
    assert marker == 800.0
    assert prog.get_progress()["members_completed"] == 1


def test_cancel_mid_run_returns_best_so_far(monkeypatch):
    # NEW CONTRACT (spec 2026-07-12 §2 Stop transport, inverting the pre-PR#23
    # behavior): Stop keeps the best COMPLETED member instead of discarding it.
    def fake_solve(items, instance, pieces, fw, gm, fg, budget_s, seed):
        if seed == 42:
            return ([_Pl("p__c0", 0.0, 0.0, 0.0)], 900.0, 50.0)
        raise CancellationError("cancelled")
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    placements, marker, util = sep.run_separation_layout(
        [_rect("p__c0", 60, 40, 90.0)], 200.0, "bi", 90.0,
        budget_s=5, seed=42, n_seeds=3, warm_start=False)
    assert marker == 900.0
    snap = prog.get_progress()
    assert snap["stopped_early"] is True
    assert snap["members_completed"] == 1 and snap["active"] is False


def test_cancel_before_any_completion_raises(monkeypatch):
    def fake_solve(*a, **k):
        raise CancellationError("cancelled")
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    with pytest.raises(CancellationError):
        sep.run_separation_layout([_rect("p__c0", 60, 40, 90.0)], 200.0, "bi", 90.0,
                                  budget_s=5, seed=42, n_seeds=2, warm_start=False)
    snap = prog.get_progress()
    assert snap["stopped_early"] is False and snap["members_completed"] == 0


def test_warm_start_built_once_for_n_members(monkeypatch):
    ws_calls = []
    monkeypatch.setattr(sep, "_build_warm_start",
                        lambda *a, **k: ws_calls.append(1) or None)
    monkeypatch.setattr(sep, "_solve_one",
                        lambda *a, **k: ([_Pl("p__c0", 0.0, 0.0, 0.0)], 800.0, 50.0))
    sep.run_separation_layout([_rect("p__c0", 60, 40, 90.0)], 200.0, "bi", 90.0,
                              budget_s=500, seed=42, n_seeds=3, warm_start=True)
    assert len(ws_calls) == 1


def test_progress_reports_member_during_run(monkeypatch):
    seen = []
    def fake_solve(items, instance, pieces, fw, gm, fg, budget_s, seed):
        snap = prog.get_progress()
        seen.append((snap["member"], snap["active"]))
        return ([_Pl("p__c0", 0.0, 0.0, 0.0)], 800.0 + seed, 50.0)
    monkeypatch.setattr(sep, "_solve_one", fake_solve)
    sep.run_separation_layout([_rect("p__c0", 60, 40, 90.0)], 200.0, "bi", 90.0,
                              budget_s=5, seed=42, n_seeds=2, warm_start=False)
    assert seen == [(1, True), (2, True)]
```

Note: this file already imports `sep` and defines `_rect` above line 200 — keep those; the replaced section re-declares only what it needs (`sep_mod`, `prog`, `CancellationError`, `_Pl`, the fixture).

- [ ] **Step 2: Run to verify the new tests fail**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_separation.py -v -k "best_of_n or cancel or warm_start_built or progress_reports or invalid_member"`
Expected: FAIL — sequential-order/cancel/progress tests fail against the parallel implementation (e.g. `calls == [42, 43, 44]` order not guaranteed, `CancellationError` raised where a result is expected, `KeyError` on progress fields).

- [ ] **Step 3: Modify imports in `separation.py`**

Delete line 17 (`from concurrent.futures import ThreadPoolExecutor, as_completed`) and add to the import block:

```python
import time
```
(alphabetically after `import tempfile`), and after the other `core.layout` imports:

```python
from core.layout.progress import set_progress
```

- [ ] **Step 4: Replace `run_separation_layout` (currently `:350-393`) with:**

```python
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
```

- [ ] **Step 5: Run the full separation test file, then the whole unit tree**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit\test_separation.py tests\unit\test_progress.py -v`
Expected: all pass (the warm-start section `:269+` is untouched and must stay green).
Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\unit -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
cd WT
git add engine/core/layout/separation.py engine/tests/unit/test_separation.py
git commit -m "feat(engine): sequential best-of-N Ultra with stop-best-so-far (PR #23 seq3 policy)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: API — response flags, truthful-key partial caching, GET /layout-progress

**Files:**
- Modify: `WT\engine\api\main.py` (imports; ultra branch after `run_in_threadpool` `:277-326`; new route)
- Test: `WT\engine\tests\integration\test_api.py` (append tests)

**Interfaces:**
- Consumes: `progress.get_progress` (Task 2); Task 3's final-snapshot contract.
- Produces: ultra `/auto-layout` responses with `stopped_early`/`members_completed`/`members_requested`; `GET /layout-progress`. Task 5's frontend types mirror these names exactly.

- [ ] **Step 1: Write the failing tests** (append to `test_api.py`; follow the file's existing stub pattern at `:111-119` — stubs monkeypatch `main.run_separation_layout`):

```python
# --- sequential best-of-N: response flags + truthful-key partial caching + progress ---

import core.layout.progress as prog


def _ultra_body(seeds=3, budget=600):
    return {**_VALID_BODY, "quality": "ultra", "ultra_seeds": seeds, "ultra_budget_s": budget}


def test_ultra_response_carries_member_fields(monkeypatch, client):
    def _stub(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, budget_s,
              seed=42, n_seeds=1, warm_start=True):
        prog.set_progress(active=False, members_completed=n_seeds, stopped_early=False)
        return ([], 1000.0, 50.0)
    monkeypatch.setattr(main, "run_separation_layout", _stub)
    res = client.post("/auto-layout", json=_ultra_body(seeds=3))
    assert res.status_code == 200
    data = res.json()
    assert data["stopped_early"] is False
    assert data["members_completed"] == 3 and data["members_requested"] == 3


def test_ultra_stopped_early_cached_under_truthful_key(monkeypatch, client):
    calls = []
    def _stub(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, budget_s,
              seed=42, n_seeds=1, warm_start=True):
        calls.append(n_seeds)
        prog.set_progress(active=False, members_completed=1, stopped_early=True)
        return ([], 1000.0, 50.0)
    monkeypatch.setattr(main, "run_separation_layout", _stub)
    res = client.post("/auto-layout", json=_ultra_body(seeds=3))
    assert res.status_code == 200
    assert res.json()["stopped_early"] is True
    assert res.json()["members_completed"] == 1

    # Repeat of the ORIGINAL-N request: the N=3 key is unoccupied -> re-runs.
    prog.clear_progress()
    def _stub2(pieces, fabric_width_mm, grain_mode, fabric_grain_deg, budget_s,
               seed=42, n_seeds=1, warm_start=True):
        calls.append(n_seeds)
        prog.set_progress(active=False, members_completed=n_seeds, stopped_early=False)
        return ([], 990.0, 51.0)
    monkeypatch.setattr(main, "run_separation_layout", _stub2)
    res2 = client.post("/auto-layout", json=_ultra_body(seeds=3))
    assert res2.status_code == 200 and len(calls) == 2

    # A request for N = members_completed (1) HITS the truthful-key entry.
    res3 = client.post("/auto-layout", json=_ultra_body(seeds=1))
    assert res3.status_code == 200 and len(calls) == 2   # cache hit, no third run
    assert res3.json()["marker_length_mm"] == 1000.0


def test_ultra_cancel_with_nothing_completed_stays_499(monkeypatch, client):
    from core.layout.cancellation import CancellationError
    def _stub(*a, **k):
        prog.set_progress(active=False, members_completed=0, stopped_early=False)
        raise CancellationError("cancelled")
    monkeypatch.setattr(main, "run_separation_layout", _stub)
    res = client.post("/auto-layout", json=_ultra_body(seeds=2))
    assert res.status_code == 499


def test_layout_progress_idle_and_midrun(client):
    prog.clear_progress()
    res = client.get("/layout-progress")
    assert res.status_code == 200 and res.json() == {"active": False}

    prog.set_progress(active=True, member=2, n_members=3, members_completed=1,
                      best_marker_mm=10552.0, budget_s=2500.0,
                      run_started_ts=prog_time() - 100.0,
                      member_started_ts=prog_time() - 40.0, stopped_early=False)
    res = client.get("/layout-progress")
    snap = res.json()
    assert snap["active"] is True and snap["member"] == 2
    assert 99.0 <= snap["total_elapsed_s"] <= 105.0
    assert 39.0 <= snap["member_elapsed_s"] <= 45.0
    prog.clear_progress()


def prog_time():
    import time as _t
    return _t.time()
```

Adapt `_VALID_BODY`/`client` to the file's existing fixture names (they exist — the file already posts `/auto-layout` with ultra stubs at `:111+`; reuse its body/client helpers verbatim). If the existing tests build the body inline, define `_ultra_body` on the same inline pattern.

- [ ] **Step 2: Run to verify failure**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\integration\test_api.py -v -k "member_fields or truthful_key or layout_progress or stays_499"`
Expected: FAIL/mixed — `stopped_early` missing from response; `/layout-progress` 404 (the 499 test may already pass — it guards the preserved path).

- [ ] **Step 3: Implement the API changes**

Imports: add `from core.layout.progress import get_progress` next to the other `core.layout` imports.

In the handler, after `duration_ms = int(...)` (`:285`) insert:

```python
    # Ultra: the run's final progress snapshot carries the stop outcome
    # (sequential best-of-N, spec 2026-07-12). Defaults cover stubbed tests.
    stopped_early = False
    members_completed = ultra_seeds
    if quality == "ultra":
        snap = get_progress()
        stopped_early = bool(snap.get("stopped_early", False))
        members_completed = int(snap.get("members_completed", ultra_seeds))
```

Change the `CachedLayout` construction's `ultra_seeds=ultra_seeds,` line (`:310`) to:

```python
        # Truthful key: a stop after k of N members IS the best-of-k artifact
        # (same seeds 42..42+k-1 a real best-of-k run uses) — cache it as such
        # so the requested-N key stays free for a full re-run.
        ultra_seeds=members_completed if (quality == "ultra" and stopped_early) else ultra_seeds,
```

Extend the returned dict (`:319-326`): after `"utilization_pct": utilization,` add:

```python
        **({"stopped_early": stopped_early,
            "members_completed": members_completed,
            "members_requested": ultra_seeds} if quality == "ultra" else {}),
```

Add the new route after `/cancel-layout`:

```python
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
```

Also update the handler docstring's Response JSON block to document the three ultra-only fields.

- [ ] **Step 4: Run to verify pass, then the integration tree**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\integration\test_api.py -v`
Expected: all pass (existing ultra tests at `:111-241` keep passing — their stubs don't set progress, so the response defaults apply).

- [ ] **Step 5: Commit**

```powershell
cd WT
git add engine/api/main.py engine/tests/integration/test_api.py
git commit -m "feat(api): ultra stop-outcome fields, truthful-key partial caching, GET /layout-progress

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Frontend — quality-aware Stop + response types

**Files:**
- Modify: `WT\frontend\src\types\engine.ts` (`AutoLayoutResponse`), `WT\frontend\src\hooks\useAutoLayout.ts`
- Test: `WT\frontend\src\hooks\useAutoLayout.test.ts` (extend, keeping its existing mock conventions)

**Interfaces:**
- Consumes: Task 4's response field names (`stopped_early`, `members_completed`, `members_requested`).
- Produces: `abort()` that keeps the fetch open for ultra; `AutoLayoutResponse` with the three optional fields. Task 6's App wiring reads `outcome.data.stopped_early` / `outcome.data.members_completed`.

- [ ] **Step 1: Extend `types/engine.ts`** — inside `AutoLayoutResponse` after `utilization_pct: number;`:

```typescript
  // Ultra only (sequential best-of-N): present on ultra responses.
  stopped_early?: boolean;      // Stop kept the best completed run
  members_completed?: number;
  members_requested?: number;
```

- [ ] **Step 2: Write the failing tests** (extend `useAutoLayout.test.ts`; reuse its existing fetch-mock helpers — read the file first and follow its patterns):

```typescript
it("ultra Stop posts /cancel-layout but does NOT abort the request", async () => {
  let resolveLayout: (r: Response) => void;
  const layoutPromise = new Promise<Response>((r) => { resolveLayout = r; });
  const seenSignals: (AbortSignal | undefined)[] = [];
  const fetchMock = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).includes("/cancel-layout")) {
      return Promise.resolve(new Response("{}", { status: 200 }));
    }
    seenSignals.push(init?.signal ?? undefined);
    return layoutPromise;
  });
  vi.stubGlobal("fetch", fetchMock);

  const { result } = renderHook(() => useAutoLayout());
  const run = result.current.runAutoLayout(
    "f.dxf", [PIECE], 1500, "bi", 90, 1, false, 1, 5, false, "ultra", 600, 3,
  );
  await act(async () => { result.current.abort(); });
  expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/cancel-layout"))).toBe(true);
  expect(seenSignals[0]?.aborted).toBe(false);   // request still open

  resolveLayout!(new Response(JSON.stringify({
    id: "x", timestamp: "t", duration_ms: 1, placements: [],
    marker_length_mm: 10552, utilization_pct: 88,
    stopped_early: true, members_completed: 2, members_requested: 3,
  }), { status: 200 }));
  const outcome = await run;
  expect(outcome.ok && outcome.data.stopped_early).toBe(true);
});

it("non-ultra Stop aborts the request as before", async () => {
  const fetchMock = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).includes("/cancel-layout")) {
      return Promise.resolve(new Response("{}", { status: 200 }));
    }
    return new Promise<Response>((_r, reject) => {
      init?.signal?.addEventListener("abort", () =>
        reject(new DOMException("aborted", "AbortError")));
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  const { result } = renderHook(() => useAutoLayout());
  const run = result.current.runAutoLayout(
    "f.dxf", [PIECE], 1500, "bi", 90, 1, false, 1, 5, false, "fast", 600, 1,
  );
  await act(async () => { result.current.abort(); });
  const outcome = await run;
  expect(outcome).toEqual({ ok: false, aborted: true });
});

it("a 499 response maps to the aborted outcome (ultra stop with nothing completed)", async () => {
  const fetchMock = vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify({ detail: "cancelled" }), { status: 499 })));
  vi.stubGlobal("fetch", fetchMock);
  const { result } = renderHook(() => useAutoLayout());
  const outcome = await result.current.runAutoLayout(
    "f.dxf", [PIECE], 1500, "bi", 90, 1, false, 1, 5, false, "ultra", 600, 3,
  );
  expect(outcome).toEqual({ ok: false, aborted: true });
});
```

(`PIECE` = whatever minimal piece fixture the file already uses; reuse it.)

- [ ] **Step 3: Run to verify failure**

Run: `cd WT\frontend; npm run test -- useAutoLayout`
Expected: FAIL — ultra Stop currently aborts the signal; 499 lands in the error branch.

- [ ] **Step 4: Implement in `useAutoLayout.ts`**

Add a ref + capture the quality, branch the abort, and map 499:

```typescript
  const abortRef = useRef<AbortController | null>(null);
  const inFlightQualityRef = useRef<LayoutQuality | null>(null);
```

In `runAutoLayout`, right after `abortRef.current = controller;`:

```typescript
      inFlightQualityRef.current = quality;
```

In the `!res.ok` branch, BEFORE the generic throw:

```typescript
        if (res.status === 499) {
          // Engine confirmed the cancel with nothing completed (ultra keeps
          // the request open on Stop; other tiers normally abort client-side).
          setStatus("idle");
          setErrorMessage(null);
          return { ok: false, aborted: true };
        }
```

Replace `abort`:

```typescript
  const abort = useCallback(() => {
    fetch(`${ENGINE_URL}/cancel-layout`, { method: "POST" }).catch(() => {});
    if (inFlightQualityRef.current !== "ultra") {
      abortRef.current?.abort();
    }
    // Ultra: keep the request open — the engine returns the best completed
    // member (stopped_early) or 499 when nothing completed yet.
  }, []);
```

- [ ] **Step 5: Run to verify pass + full frontend suite**

Run: `cd WT\frontend; npm run test`
Expected: all pass (existing useAutoLayout tests included).

- [ ] **Step 6: Commit**

```powershell
cd WT
git add frontend/src/types/engine.ts frontend/src/hooks/useAutoLayout.ts frontend/src/hooks/useAutoLayout.test.ts
git commit -m "feat(frontend): quality-aware Stop — ultra keeps the request open for best-so-far

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Frontend — progress polling + statusbar + QualityPanel copy

**Files:**
- Create: `WT\frontend\src\hooks\useLayoutProgress.ts`
- Modify: `WT\frontend\src\app\App.tsx` (progress line `:345-352`, stop message in `handleAutoLayout` `:169-181`), `WT\frontend\src\components\sidebar\QualityPanel.tsx`
- Test: Create `WT\frontend\src\hooks\useLayoutProgress.test.ts`; extend `WT\frontend\src\components\sidebar\QualityPanel.test.tsx`

**Interfaces:**
- Consumes: `GET /layout-progress` (Task 4 shape); `outcome.data.stopped_early`/`members_completed` (Task 5).
- Produces: `useLayoutProgress(active: boolean): LayoutProgress | null`; QualityPanel copy per Global Constraints.

- [ ] **Step 1: Write the failing hook test** (`useLayoutProgress.test.ts`):

```typescript
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { useLayoutProgress } from "./useLayoutProgress";

const SNAP = { active: true, member: 2, n_members: 3, members_completed: 1,
               best_marker_mm: 10552, total_elapsed_s: 100.5, stopped_early: false };

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("useLayoutProgress", () => {
  it("polls every 2s while active and stops when inactive", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(SNAP), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);

    const { result, rerender } = renderHook(({ a }) => useLayoutProgress(a),
                                            { initialProps: { a: true } });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });     // initial poll
    expect(result.current?.member).toBe(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(4100); });  // 2 more polls
    expect(fetchMock.mock.calls.length).toBe(3);

    rerender({ a: false });
    expect(result.current).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(4100); });
    expect(fetchMock.mock.calls.length).toBe(3);                          // no more polls
  });

  it("keeps the last snapshot when a poll fails", async () => {
    vi.useFakeTimers();
    let fail = false;
    const fetchMock = vi.fn(() => fail
      ? Promise.reject(new Error("net"))
      : Promise.resolve(new Response(JSON.stringify(SNAP), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useLayoutProgress(true));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    fail = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(result.current?.member).toBe(2);   // stale-but-present beats null
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd WT\frontend; npm run test -- useLayoutProgress` → FAIL (module missing).

- [ ] **Step 3: Implement `useLayoutProgress.ts`**

```typescript
import { useEffect, useState } from "react";

const ENGINE_URL = "http://127.0.0.1:8765";
const POLL_MS = 2000;

export interface LayoutProgress {
  active: boolean;
  member?: number;
  n_members?: number;
  members_completed?: number;
  best_marker_mm?: number | null;
  budget_s?: number;
  total_elapsed_s?: number;
  member_elapsed_s?: number;
  stopped_early?: boolean;
}

/** Polls GET /layout-progress every 2s while `active`; null when inactive.
 *  A failed poll keeps the last snapshot (engine briefly busy ≠ no progress). */
export function useLayoutProgress(active: boolean): LayoutProgress | null {
  const [progress, setProgress] = useState<LayoutProgress | null>(null);

  useEffect(() => {
    if (!active) {
      setProgress(null);
      return;
    }
    let disposed = false;
    const poll = async () => {
      try {
        const res = await fetch(`${ENGINE_URL}/layout-progress`);
        if (!res.ok || disposed) return;
        const data = (await res.json()) as LayoutProgress;
        if (!disposed) setProgress(data);
      } catch {
        /* keep last snapshot */
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => { disposed = true; clearInterval(id); };
  }, [active]);

  return progress;
}
```

- [ ] **Step 4: Wire App.tsx**

Import + hook (after the `useAutoLayout` line `:49`):

```typescript
import { useLayoutProgress } from "../hooks/useLayoutProgress";
```
```typescript
  const layoutProgress = useLayoutProgress(autoStatus === "loading" && quality === "ultra");
```

Replace the loading hint paragraph (`:347-349`) with:

```tsx
                <p style={styles.advancedHint}>
                  {quality === "ultra" && layoutProgress?.active
                    ? `Separation run ${layoutProgress.member} of ${layoutProgress.n_members} — ` +
                      `${formatDuration((layoutProgress.total_elapsed_s ?? 0) * 1000)} elapsed` +
                      (layoutProgress.best_marker_mm != null
                        ? ` — best so far ${Math.round(layoutProgress.best_marker_mm)} mm`
                        : "")
                    : `Optimizing (${quality})… ${formatDuration(elapsedMs)} elapsed`}
                </p>
```

In `handleAutoLayout`'s success branch (`:169-176`), prefix the status message:

```typescript
      const stoppedNote = outcome.data.stopped_early
        ? `Stopped — kept best of ${outcome.data.members_completed} completed run(s). `
        : "";
      setStatusMessage(
        stoppedNote +
        `Auto layout: ${outcome.data.placements.length} piece${outcome.data.placements.length !== 1 ? "s" : ""} · ` +
        `Marker: ${Math.round(outcome.data.marker_length_mm)} mm · ` +
        `Utilization: ${outcome.data.utilization_pct}%`
      );
```

- [ ] **Step 5: QualityPanel copy + total-time hint**

In `QualityPanel.tsx`, change the seeds label line (`:62`) to:

```tsx
          <div style={{ fontSize: 13, marginTop: 6 }} aria-label="seeds">Runs (keep best of N)</div>
```

and after the seeds radio `map` block (`:63-69`), add:

```tsx
          <p style={styles.totalHint}>
            {`Total ≈ ${Math.floor((ultraSeeds * ultraBudgetS) / 60)}m ${(ultraSeeds * ultraBudgetS) % 60}s (${ultraSeeds} × ${ultraBudgetS}s)`}
          </p>
```

with the style added to the `styles` object:

```tsx
  totalHint: {
    fontSize: 12,
    color: "var(--color-text-muted)",
    fontStyle: "italic" as const,
    marginTop: 4,
    marginBottom: 0,
  },
```

Extend `QualityPanel.test.tsx` (follow its existing render helpers):

```typescript
it("shows the runs label and computed total-time hint for ultra", () => {
  render(<QualityPanel quality="ultra" onChange={() => {}}
                       ultraBudgetS={2500} ultraSeeds={3}
                       onUltraBudgetChange={() => {}} onUltraSeedsChange={() => {}} />);
  expect(screen.getByText("Runs (keep best of N)")).toBeInTheDocument();
  expect(screen.getByText("Total ≈ 125m 0s (3 × 2500s)")).toBeInTheDocument();
});
```

- [ ] **Step 6: Run frontend suite + build**

Run: `cd WT\frontend; npm run test` → all pass. Then `npm run build` → tsc clean.

- [ ] **Step 7: Commit**

```powershell
cd WT
git add frontend/src/hooks/useLayoutProgress.ts frontend/src/hooks/useLayoutProgress.test.ts frontend/src/app/App.tsx frontend/src/components/sidebar/QualityPanel.tsx frontend/src/components/sidebar/QualityPanel.test.tsx
git commit -m "feat(frontend): ultra run progress line, stop-kept-best message, runs copy + total-time hint

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Real-sparrow sequential integration + full suites

**Files:**
- Modify: `WT\engine\tests\integration\test_separation_sidecar.py` (append one test, reusing the file's existing skip guards/decorators and piece-building helpers — read the existing `test_run_separation_layout_end_to_end` first and mirror it)

**Interfaces:**
- Consumes: Task 3's sequential contract + final snapshot.
- Produces: end-to-end confidence for the round; the suites-green gate before docs.

- [ ] **Step 1: Append the test** (mirror the existing end-to-end test's fixtures/guards; the NEW assertions are the sequential wall and the final snapshot):

```python
def test_sequential_best_of_two_end_to_end():
    """Two members MUST run back-to-back (sequential wall ≈ 2×budget, not ≈ budget)
    and leave a full-completion final snapshot."""
    import time as _t
    import core.layout.progress as prog
    pieces = _sidecar_pieces()   # reuse/extract the same pieces the existing e2e test builds
    prog.clear_progress()
    t0 = _t.perf_counter()
    placements, marker, util = sep.run_separation_layout(
        pieces, FABRIC_WIDTH, "bi", 90.0, budget_s=8, seed=42, n_seeds=2, warm_start=False)
    wall = _t.perf_counter() - t0
    assert wall >= 14.0, f"members overlapped? wall={wall:.1f}s for 2 × 8s"
    assert marker > 0 and len(placements) == len(pieces)
    snap = prog.get_progress()
    assert snap["members_completed"] == 2 and snap["stopped_early"] is False
```

If the existing test builds pieces inline rather than via a helper, extract its construction into `_sidecar_pieces()` used by BOTH tests (no duplication), keeping the old test's assertions unchanged. `FABRIC_WIDTH` = whatever width the existing test uses.

- [ ] **Step 2: Run the integration file (needs the vendored sparrow.exe — present in the worktree via git)**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\integration\test_separation_sidecar.py -v`
Expected: all pass; the new test takes ~16-20s.

- [ ] **Step 3: Full suites**

Run: `D:\openmarker\engine\.venv\Scripts\python.exe -m pytest tests\ -v` (CWD `WT\engine`)
Expected: **all pass**, total > 259 (record the new count for Task 8's outcome line).
Run: `cd WT\frontend; npm run test`
Expected: all pass.

- [ ] **Step 4: Commit**

```powershell
cd WT
git add engine/tests/integration/test_separation_sidecar.py
git commit -m "test(engine): real-sparrow sequential best-of-two integration

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Docs + BACKLOG + PR

**Files:**
- Modify: `WT\CLAUDE.md` (architecture blurbs), `WT\docs\planning\BACKLOG.md` (ticks + outcome). **Do NOT touch PERFORMANCE.md.**

- [ ] **Step 1: CLAUDE.md updates** — three surgical edits:

1. In the `core/layout/separation.py` bullet, replace the sentence `` `n_seeds > 1` runs parallel attempts and keeps the shortest VALID marker; `` with:

```markdown
`n_seeds > 1` runs members SEQUENTIALLY (one 3-thread sparrow at a time, each at the full budget — the PR #23-validated seq3 policy; seeds `seed..seed+N−1`) and keeps the shortest VALID marker; Stop mid-run returns the best COMPLETED member (`stopped_early`), with progress reported via `core/layout/progress.py` (module-level single-flight snapshot; final snapshot on every exit path);
```

2. In the `POST /auto-layout` route bullet, after the `quality` description, append:

```markdown
Ultra responses add `stopped_early` / `members_completed` / `members_requested`; a stopped-early result is cached under the truthful key (`ultra_seeds = members_completed`). `GET /layout-progress` → live run snapshot (member k of N, elapsed, best-so-far) polled by the GUI every 2s.
```

3. In the frontend section, update the `useAutoLayout.ts` bullet to note the quality-aware Stop (ultra keeps the request open; 499 → aborted) and add a bullet:

```markdown
- `hooks/useLayoutProgress.ts` — polls `GET /layout-progress` every 2s while an Ultra run is loading; drives the "Separation run k of N — elapsed — best so far" sidebar line. QualityPanel's seeds control reads "Runs (keep best of N)" with a computed total-time hint.
```

- [ ] **Step 2: BACKLOG** — tick P1–P8 in the productization section, and append the outcome line (fill the test counts from Task 7):

```markdown
- Outcome: SHIPPED — Ultra best-of-N now sequential (seq3 policy, PR #23); Stop returns best completed member (truthful-key cached); GET /layout-progress + GUI run-k-of-N line; QualityPanel "Runs (keep best of N)" + total-time hint. Engine suite <N_ENGINE> passed (was 259); frontend <N_FE> passed. No PERFORMANCE.md entry (feature round — this section is the record).
```

Also tick the race+fork section's `- [ ] Follow-up (GO)` checkbox to `- [x]` (it ships with this round).

- [ ] **Step 3: Commit**

```powershell
cd WT
git add CLAUDE.md docs/planning/BACKLOG.md
git commit -m "docs: sequential best-of-N shipped — CLAUDE.md blurbs + BACKLOG round record

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Hand back to the controller** for the final whole-branch review, push, `gh pr create`, and the established merge choreography on the user's word — **including the new hazard: main's `docs/planning/BACKLOG.md` carries an uncommitted planning-section edit; drop it (`git checkout -- docs/planning/BACKLOG.md` in the main tree) before the merge-time `git pull` — the section content arrives via the squash.**

---

## Verdict paths (summary)

Feature round — no gates. Tasks run 1→8 in order; each task's suite must be green before the next. BLOCKED escalations per the subagent-driven protocol. The final whole-branch review checks: engine/frontend diffs match the spec exactly, no PERFORMANCE.md change, no `.gitignore` change, suite counts recorded in the BACKLOG outcome.
