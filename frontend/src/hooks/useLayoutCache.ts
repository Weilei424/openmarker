import { useState, useCallback, useEffect, useRef } from "react";
import type { CachedLayout, CachedLayoutSummary } from "../types/engine";

const ENGINE_URL = "http://127.0.0.1:8765";

export function useLayoutCache() {
  const [entries, setEntries] = useState<CachedLayoutSummary[]>([]);
  const [activeId, setActiveIdRaw] = useState<string | null>(null);
  const [activeEntry, setActiveEntry] = useState<CachedLayout | null>(null);

  const entriesRef = useRef<CachedLayoutSummary[]>([]);
  useEffect(() => { entriesRef.current = entries; }, [entries]);

  const refresh = useCallback(async (): Promise<CachedLayoutSummary[]> => {
    try {
      const res = await fetch(`${ENGINE_URL}/layouts`);
      if (!res.ok) return entriesRef.current;
      const list = (await res.json()) as CachedLayoutSummary[];
      setEntries(list);
      return list;
    } catch {
      return entriesRef.current;
    }
  }, []);

  const setActiveId = useCallback((id: string | null) => {
    setActiveIdRaw((prev) => {
      if (prev !== id) setActiveEntry(null);
      return id;
    });
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
    setActiveIdRaw((current) => {
      if (current !== id) return current;             // user picked a different tab; leave it
      const next = fresh[0]?.id ?? null;
      if (next === null) setActiveEntry(null);
      return next;
    });
  }, [refresh]);

  const clearAll = useCallback(async (): Promise<void> => {
    try {
      await fetch(`${ENGINE_URL}/layouts`, { method: "DELETE" });
    } catch {
      // Swallow — best-effort.
    }
    setEntries([]);
    setActiveIdRaw(null);
    setActiveEntry(null);
  }, []);

  // Restore the tab strip across webview reloads (or HMR during dev) —
  // the engine still holds the in-memory cache from this session, so a
  // single GET /layouts on mount brings the UI back into sync. `refresh`
  // is stable-identity so this fires exactly once.
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only
  }, []);

  return { entries, activeId, activeEntry, setActiveId, closeTab, refresh, clearAll };
}
