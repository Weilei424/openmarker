from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CachedLayout:
    id: str
    filename: str
    timestamp: str
    grain_mode: Literal["single", "bi"]
    copies: int
    fabric_width_mm: float
    placements: list[dict]
    marker_length_mm: float
    utilization_pct: float
    duration_ms: int
    # Monotonic ordering key (time.monotonic() at insertion time, not a
    # wall-clock instant). Used by LayoutCache for FIFO eviction and
    # newest-first listing so the order stays stable even if the system
    # clock jumps backward. For a wall-clock instant, read `timestamp`.
    # On platforms with coarse monotonic resolution (e.g. Windows ~16 ms),
    # rapid inserts can tie; LayoutCache adds an internal tiebreaker
    # (_sort_key) so ordering remains deterministic.
    created_at: float
    # Internal tiebreaker assigned by LayoutCache.insert when the entry is
    # accepted. Strictly increasing per-cache; not part of the public API
    # and not serialized to clients.
    _sort_key: int = field(default=0, repr=False, compare=False)


class LayoutCache:
    def __init__(self) -> None:
        # Per-instance FIFO eviction threshold (default matches the previous
        # class-level MAX_ENTRIES). Mutate via `set_max_entries` so shrinking
        # also trims the current contents.
        self.max_entries: int = 5
        self._entries: dict[str, CachedLayout] = {}
        # Strictly-increasing counter that breaks ties when two entries
        # share a `created_at` (Windows monotonic resolution is ~16 ms,
        # so rapid back-to-back inserts otherwise tie).
        self._next_sort_key: int = 0

    def _order_key(self, entry: CachedLayout) -> tuple[float, int]:
        return (entry.created_at, entry._sort_key)

    def set_max_entries(self, n: int) -> None:
        """Set the FIFO eviction threshold. If n is smaller than current size,
        evict oldest entries down to n immediately."""
        if n < 1:
            raise ValueError(f"max_entries must be >= 1, got {n}")
        self.max_entries = n
        while len(self._entries) > self.max_entries:
            oldest_id = min(self._entries, key=lambda k: self._order_key(self._entries[k]))
            del self._entries[oldest_id]

    def insert(self, entry: CachedLayout) -> None:
        entry._sort_key = self._next_sort_key
        self._next_sort_key += 1
        self._entries[entry.id] = entry
        if len(self._entries) > self.max_entries:
            oldest_id = min(self._entries, key=lambda k: self._order_key(self._entries[k]))
            del self._entries[oldest_id]

    def get(self, layout_id: str) -> CachedLayout | None:
        return self._entries.get(layout_id)

    def delete(self, layout_id: str) -> bool:
        if layout_id in self._entries:
            del self._entries[layout_id]
            return True
        return False

    def clear(self) -> None:
        """Drop all entries. Idempotent."""
        self._entries.clear()

    def list(self) -> list[CachedLayout]:
        return sorted(self._entries.values(), key=self._order_key, reverse=True)

    def find_by_settings(
        self,
        filename: str,
        grain_mode: str,
        copies: int,
        fabric_width_mm: float,
        effort: int | None = None,  # TEMP(phase6-bench): include in key when not None
    ) -> CachedLayout | None:
        """Return the newest entry matching ALL of (filename, grain_mode, copies,
        fabric_width_mm), or None. Used to dedup re-runs with identical settings."""
        matches = []
        for e in self._entries.values():
            if not (e.filename == filename
                    and e.grain_mode == grain_mode
                    and e.copies == copies
                    and e.fabric_width_mm == fabric_width_mm):
                continue
            # TEMP(phase6-bench): if effort is part of the key, require it to match.
            # Entries inserted without the bench flag won't have _bench_effort set,
            # so they're treated as effort=None and never collide with a tagged lookup.
            if effort is not None:
                stored = getattr(e, "_bench_effort", None)
                if stored != effort:
                    continue
            matches.append(e)
        if not matches:
            return None
        return max(matches, key=self._order_key)


_cache = LayoutCache()


def get_cache() -> LayoutCache:
    return _cache


def reset_cache() -> None:
    """For tests: clear the singleton between cases and restore the default
    max_entries so per-test set_max_entries calls don't leak across cases."""
    _cache.clear()
    _cache.max_entries = 5
