import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useLayoutCache } from "./useLayoutCache";
import type { CachedLayout, CachedLayoutSummary } from "../types/engine";

const summary = (id: string): CachedLayoutSummary => ({
  id,
  filename: "sample.dxf",
  timestamp: "20260523140000",
  grain_mode: "single",
  copies: 1,
  fabric_width_mm: 1500,
  marker_length_mm: 500,
  utilization_pct: 82.4,
  duration_ms: 1234,
});

const full = (id: string): CachedLayout => ({
  ...summary(id),
  placements: [{ piece_id: "p0", x: 10, y: 10, rotation_deg: 0 }],
});

describe("useLayoutCache", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("refresh() pulls /layouts and stores entries", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => [summary("a"), summary("b")],
    } as Response);

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });

    expect(result.current.entries.map(e => e.id)).toEqual(["a", "b"]);
  });

  it("setActiveId triggers GET /layouts/{id} and stores the full entry", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, json: async () => [summary("a")] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => full("a") } as Response);

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });
    await act(async () => { result.current.setActiveId("a"); });

    await waitFor(() => expect(result.current.activeEntry?.id).toBe("a"));
    expect(result.current.activeEntry?.placements).toHaveLength(1);
  });

  it("closeTab calls DELETE and refreshes the list", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, json: async () => [summary("a"), summary("b")] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => full("a") } as Response)
      .mockResolvedValueOnce({ ok: true, status: 204 } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [summary("b")] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => full("b") } as Response);

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });
    await act(async () => { result.current.setActiveId("a"); });
    await waitFor(() => expect(result.current.activeEntry?.id).toBe("a"));

    await act(async () => { await result.current.closeTab("a"); });

    await waitFor(() => expect(result.current.entries.map(e => e.id)).toEqual(["b"]));
    await waitFor(() => expect(result.current.activeId).toBe("b"));
  });

  it("closing the last tab clears active state", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, json: async () => [summary("a")] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => full("a") } as Response)
      .mockResolvedValueOnce({ ok: true, status: 204 } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [] } as Response);

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });
    await act(async () => { result.current.setActiveId("a"); });
    await waitFor(() => expect(result.current.activeEntry?.id).toBe("a"));

    await act(async () => { await result.current.closeTab("a"); });

    await waitFor(() => expect(result.current.entries).toEqual([]));
    await waitFor(() => expect(result.current.activeId).toBeNull());
    expect(result.current.activeEntry).toBeNull();
  });
});
