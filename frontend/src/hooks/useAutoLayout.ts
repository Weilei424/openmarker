import { useState, useCallback, useRef } from "react";
import type { Piece, GrainMode, AutoLayoutResponse, LayoutQuality } from "../types/engine";

const ENGINE_URL = "http://127.0.0.1:8765";

export type AutoLayoutOutcome =
  | { ok: true; data: AutoLayoutResponse }
  | { ok: false; aborted: true }
  | { ok: false; aborted: false; errorMessage: string };

export function useAutoLayout() {
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const runAutoLayout = useCallback(
    async (
      filename: string,
      pieces: Piece[],
      fabricWidthMm: number,
      grainMode: GrainMode,
      grainDirectionDeg: number,
      copies: number,
      disableNfpCache: boolean = false,
      effort: number = 1,
      maxCacheEntries: number = 5,
      includeEffortInKey: boolean = false, // TEMP(phase6-bench)
      quality: LayoutQuality = "fast",
    ): Promise<AutoLayoutOutcome> => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setStatus("loading");
      setErrorMessage(null);
      try {
        const res = await fetch(`${ENGINE_URL}/auto-layout`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filename,
            pieces,
            fabric_width_mm: fabricWidthMm,
            grain_mode: grainMode,
            grain_direction_deg: grainDirectionDeg,
            copies,
            disable_nfp_cache: disableNfpCache,
            effort,
            max_cache_entries: maxCacheEntries,
            include_effort_in_key: includeEffortInKey, // TEMP(phase6-bench)
            quality,
          }),
          signal: controller.signal,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
        }
        const data = (await res.json()) as AutoLayoutResponse;
        setStatus("idle");
        return { ok: true, data };
      } catch (e) {
        if (e instanceof Error && (e.name === "AbortError" || /aborted/i.test(e.message))) {
          setStatus("idle");
          setErrorMessage(null);
          return { ok: false, aborted: true };
        }
        const msg = e instanceof Error ? e.message : "Auto layout failed";
        setStatus("error");
        setErrorMessage(msg);
        return { ok: false, aborted: false, errorMessage: msg };
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    []
  );

  const abort = useCallback(() => {
    fetch(`${ENGINE_URL}/cancel-layout`, { method: "POST" }).catch(() => {});
    abortRef.current?.abort();
  }, []);

  return { runAutoLayout, abort, status, errorMessage };
}
