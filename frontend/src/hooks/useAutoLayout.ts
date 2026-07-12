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
  const inFlightQualityRef = useRef<LayoutQuality | null>(null);

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
      ultraBudgetS: number = 600,
      ultraSeeds: number = 1,
    ): Promise<AutoLayoutOutcome> => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      inFlightQualityRef.current = quality;

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
            ultra_budget_s: ultraBudgetS,
            ultra_seeds: ultraSeeds,
          }),
          signal: controller.signal,
        });
        if (!res.ok) {
          if (res.status === 499) {
            // Engine confirmed the cancel with nothing completed (ultra keeps
            // the request open on Stop; other tiers normally abort client-side).
            setStatus("idle");
            setErrorMessage(null);
            return { ok: false, aborted: true };
          }
          const err = await res.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
        }
        const data = (await res.json()) as AutoLayoutResponse;
        setStatus("idle");
        return { ok: true, data };
      } catch (e) {
        // DOMException (thrown by a real aborted fetch, and by jsdom's fetch
        // mocks in tests) does NOT satisfy `instanceof Error` per the DOM
        // spec — must check it alongside Error to catch legitimate aborts.
        if (
          (e instanceof Error || e instanceof DOMException) &&
          (e.name === "AbortError" || /aborted/i.test(e.message))
        ) {
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
    if (inFlightQualityRef.current !== "ultra") {
      abortRef.current?.abort();
    }
    // Ultra: keep the request open — the engine returns the best completed
    // member (stopped_early) or 499 when nothing completed yet.
  }, []);

  return { runAutoLayout, abort, status, errorMessage };
}
