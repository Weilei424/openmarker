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
    created_at: float


class LayoutCache:
    MAX_ENTRIES = 5

    def __init__(self) -> None:
        self._entries: dict[str, CachedLayout] = {}

    def insert(self, entry: CachedLayout) -> None:
        self._entries[entry.id] = entry
        if len(self._entries) > self.MAX_ENTRIES:
            oldest_id = min(self._entries, key=lambda k: self._entries[k].created_at)
            del self._entries[oldest_id]

    def get(self, layout_id: str) -> CachedLayout | None:
        return self._entries.get(layout_id)

    def delete(self, layout_id: str) -> bool:
        if layout_id in self._entries:
            del self._entries[layout_id]
            return True
        return False

    def list(self) -> list[CachedLayout]:
        return sorted(self._entries.values(), key=lambda e: e.created_at, reverse=True)


_cache = LayoutCache()


def get_cache() -> LayoutCache:
    return _cache


def reset_cache() -> None:
    """For tests: clear the singleton between cases."""
    _cache._entries.clear()
