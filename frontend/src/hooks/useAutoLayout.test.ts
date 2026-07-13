import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAutoLayout } from "./useAutoLayout";
import type { Piece } from "../types/engine";

const PIECE: Piece = {
  id: "p0",
  name: "p0",
  polygon: [[0, 0], [100, 0], [100, 80], [0, 80]],
  area: 8000,
  bbox: { min_x: 0, min_y: 0, max_x: 100, max_y: 80, width: 100, height: 80 },
  is_valid: true,
  validation_notes: [],
  grainline_direction_deg: null,
};

const okResponse = () =>
  ({
    ok: true,
    json: async () => ({
      id: "x", timestamp: "t", duration_ms: 1,
      placements: [], marker_length_mm: 1, utilization_pct: 1,
    }),
  } as Response);

function lastBody(): Record<string, unknown> {
  const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
  return JSON.parse(calls[calls.length - 1][1].body as string);
}

describe("useAutoLayout", () => {
  beforeEach(() => { vi.spyOn(globalThis, "fetch"); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("includes the given quality in the request body", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(okResponse());
    const { result } = renderHook(() => useAutoLayout());
    await act(async () => {
      await result.current.runAutoLayout(
        "f.dxf", [], 1500, "single", 90, 1, false, 1, 5, false, "best",
      );
    });
    expect(lastBody().quality).toBe("best");
  });

  it("defaults quality to fast when the arg is omitted", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(okResponse());
    const { result } = renderHook(() => useAutoLayout());
    await act(async () => {
      await result.current.runAutoLayout("f.dxf", [], 1500, "single", 90, 1);
    });
    expect(lastBody().quality).toBe("fast");
  });

  it("ultra Stop posts /cancel-layout but does NOT abort the request", async () => {
    let resolveLayout: (r: Response) => void;
    const layoutPromise = new Promise<Response>((r) => { resolveLayout = r; });
    const seenSignals: (AbortSignal | undefined)[] = [];
    const fetchMock = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).includes("/cancel-layout")) {
        return Promise.resolve(new Response("{}", { status: 200 }));
      }
      seenSignals.push(init?.signal ?? undefined);
      return layoutPromise;
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useAutoLayout());
    const run = result.current.runAutoLayout(
      "f.dxf", [PIECE], 1500, "bi", 90, 1, false, 1, 5, false, "ultra", 600, 3,
    );
    await act(async () => { result.current.abort(); });
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/cancel-layout"))).toBe(true);
    expect(seenSignals[0]?.aborted).toBe(false);   // request still open

    resolveLayout!(new Response(JSON.stringify({
      id: "x", timestamp: "t", duration_ms: 1, placements: [],
      marker_length_mm: 10552, utilization_pct: 88,
      stopped_early: true, members_completed: 2, members_requested: 3,
    }), { status: 200 }));
    const outcome = await run;
    expect(outcome.ok && outcome.data.stopped_early).toBe(true);
  });

  it("non-ultra Stop aborts the request as before", async () => {
    const fetchMock = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).includes("/cancel-layout")) {
        return Promise.resolve(new Response("{}", { status: 200 }));
      }
      return new Promise<Response>((_r, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")));
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAutoLayout());
    const run = result.current.runAutoLayout(
      "f.dxf", [PIECE], 1500, "bi", 90, 1, false, 1, 5, false, "fast", 600, 1,
    );
    await act(async () => { result.current.abort(); });
    const outcome = await run;
    expect(outcome).toEqual({ ok: false, aborted: true });
  });

  it("a 499 response maps to the aborted outcome (ultra stop with nothing completed)", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ detail: "cancelled" }), { status: 499 })));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAutoLayout());
    const outcome = await result.current.runAutoLayout(
      "f.dxf", [PIECE], 1500, "bi", 90, 1, false, 1, 5, false, "ultra", 600, 3,
    );
    expect(outcome).toEqual({ ok: false, aborted: true });
  });
});
