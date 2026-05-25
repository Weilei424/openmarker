import time
import pytest
from core.layout.cache import CachedLayout, LayoutCache


def _make_entry(id_: str, created_at: float | None = None) -> CachedLayout:
    return CachedLayout(
        id=id_,
        filename="sample.dxf",
        timestamp="20260523140000",
        grain_mode="single",
        copies=1,
        fabric_width_mm=1500.0,
        placements=[{"piece_id": "p0", "x": 10, "y": 10, "rotation_deg": 0}],
        marker_length_mm=500.0,
        utilization_pct=82.4,
        duration_ms=1234,
        created_at=created_at if created_at is not None else time.time(),
    )


def test_insert_then_get_roundtrip():
    cache = LayoutCache()
    entry = _make_entry("a")
    cache.insert(entry)
    assert cache.get("a") is entry


def test_get_missing_returns_none():
    cache = LayoutCache()
    assert cache.get("missing") is None


def test_list_newest_first():
    cache = LayoutCache()
    cache.insert(_make_entry("a", created_at=100.0))
    cache.insert(_make_entry("b", created_at=200.0))
    cache.insert(_make_entry("c", created_at=150.0))
    ids = [e.id for e in cache.list()]
    assert ids == ["b", "c", "a"]


def test_insert_beyond_max_evicts_oldest():
    cache = LayoutCache()
    for i in range(5):
        cache.insert(_make_entry(f"e{i}", created_at=float(i)))
    cache.insert(_make_entry("e5", created_at=5.0))
    ids = {e.id for e in cache.list()}
    assert ids == {"e1", "e2", "e3", "e4", "e5"}
    assert cache.get("e0") is None


def test_delete_returns_true_when_present():
    cache = LayoutCache()
    cache.insert(_make_entry("a"))
    assert cache.delete("a") is True
    assert cache.get("a") is None


def test_delete_returns_false_when_missing():
    cache = LayoutCache()
    assert cache.delete("missing") is False


def test_find_by_settings_returns_match():
    cache = LayoutCache()
    cache.insert(_make_entry("a"))  # default settings: sample.dxf, single, 1, 1500
    hit = cache.find_by_settings(
        filename="sample.dxf", grain_mode="single", copies=1, fabric_width_mm=1500.0
    )
    assert hit is not None
    assert hit.id == "a"


def test_find_by_settings_no_match_returns_none():
    cache = LayoutCache()
    cache.insert(_make_entry("a"))
    assert cache.find_by_settings(
        filename="other.dxf", grain_mode="single", copies=1, fabric_width_mm=1500.0
    ) is None
    assert cache.find_by_settings(
        filename="sample.dxf", grain_mode="bi", copies=1, fabric_width_mm=1500.0
    ) is None
    assert cache.find_by_settings(
        filename="sample.dxf", grain_mode="single", copies=2, fabric_width_mm=1500.0
    ) is None
    assert cache.find_by_settings(
        filename="sample.dxf", grain_mode="single", copies=1, fabric_width_mm=1600.0
    ) is None


def test_set_max_entries_trims_when_shrunk():
    cache = LayoutCache()
    cache.set_max_entries(20)
    for i in range(10):
        cache.insert(_make_entry(f"e{i}", created_at=float(i)))
    assert len(cache.list()) == 10
    cache.set_max_entries(3)
    remaining = {e.id for e in cache.list()}
    assert len(remaining) == 3
    # Oldest evicted.
    assert "e0" not in remaining
    assert "e7" in remaining and "e8" in remaining and "e9" in remaining


def test_set_max_entries_invalid_raises():
    cache = LayoutCache()
    with pytest.raises(ValueError):
        cache.set_max_entries(0)
    with pytest.raises(ValueError):
        cache.set_max_entries(-1)


def test_find_by_settings_newest_match_wins():
    """If multiple entries somehow share settings (legacy), return the newest."""
    import time as _t
    cache = LayoutCache()
    cache.insert(_make_entry("old", created_at=_t.time() - 10))
    cache.insert(_make_entry("new", created_at=_t.time()))
    hit = cache.find_by_settings(
        filename="sample.dxf", grain_mode="single", copies=1, fabric_width_mm=1500.0
    )
    assert hit is not None
    assert hit.id == "new"
