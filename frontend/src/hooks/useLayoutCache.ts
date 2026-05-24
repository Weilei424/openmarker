import { useState, useCallback, useEffect } from "react";
import type { CachedLayout, CachedLayoutSummary } from "../types/engine";

const ENGINE_URL = "http://127.0.0.1:8765";

export function useLayoutCache() {
  const [entries, setEntries] = useState<CachedLayoutSummary[]>([]);
  const [activeId, setActiveIdRaw] = useState<string | null>(null);
  const [activeEntry, setActiveEntry] = useState<CachedLayout | null>(null);

  const refresh = useCallback(async (): Promise<CachedLayoutSummary[]> => {
    try {
      const res = await fetch(`${ENGINE_URL}/layouts`);
      if (!res.ok) return entries;
      const list = (await res.json()) as CachedLayoutSummary[];
      setEntries(list);
      return list;
    } catch {
      return entries;
    }
  }, [entries]);

  const setActiveId = useCallback((id: string | null) => {
    setActiveIdRaw(id);
    if (id === null) setActiveEntry(null);
  }, []);

  useEffect(() => {
    if (activeId === null) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${ENGINE_URL}/layouts/${activeId}`);
        if (!res.ok) {
          if (!cancelled) {
            setEntries((prev) => prev.filter((e) => e.id !== activeId));
            setActiveEntry(null);
            setActiveIdRaw(null);
          }
          return;
        }
        const data = (await res.json()) as CachedLayout;
        if (!cancelled) setActiveEntry(data);
      } catch {}
    })();
    return () => { cancelled = true; };
  }, [activeId]);

  const closeTab = useCallback(async (id: string) => {
    try {
      await fetch(`${ENGINE_URL}/layouts/${id}`, { method: "DELETE" });
    } catch {}
    const fresh = await refresh();
    if (activeId === id) {
      if (fresh.length === 0) {
        setActiveIdRaw(null);
        setActiveEntry(null);
      } else {
        setActiveIdRaw(fresh[0].id);
      }
    }
  }, [activeId, refresh]);

  return { entries, activeId, activeEntry, setActiveId, closeTab, refresh };
}
