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
