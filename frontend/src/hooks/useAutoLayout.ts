import { useState, useCallback } from "react";
import type { Piece, GrainMode, AutoLayoutResponse } from "../types/engine";

const ENGINE_URL = "http://127.0.0.1:8765";

export function useAutoLayout() {
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const runAutoLayout = useCallback(
    async (
      pieces: Piece[],
      fabricWidthMm: number,
      grainMode: GrainMode,
      grainDirectionDeg: number,
      fastMode: boolean
    ): Promise<AutoLayoutResponse | null> => {
      setStatus("loading");
      setErrorMessage(null);
      try {
        const res = await fetch(`${ENGINE_URL}/auto-layout`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            pieces,
            fabric_width_mm: fabricWidthMm,
            grain_mode: grainMode,
            grain_direction_deg: grainDirectionDeg,
            fast_mode: fastMode,
          }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
        }
        const data = (await res.json()) as AutoLayoutResponse;
        setStatus("idle");
        return data;
      } catch (e) {
        setStatus("error");
        setErrorMessage(e instanceof Error ? e.message : "Auto layout failed");
        return null;
      }
    },
    []
  );

  return { runAutoLayout, status, errorMessage };
}
