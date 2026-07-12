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
