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
  // Mount fires a single GET /layouts. Tests below prepend a `mountEmpty()`
  // entry to their mock chain so the mount-refresh resolves to an empty
  // list and doesn't steal a mock intended for an explicit later call.
  const mountEmpty = () =>
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

  beforeEach(() => {
    vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("refresh() pulls /layouts and stores entries", async () => {
    mountEmpty();
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => [summary("a"), summary("b")],
    } as Response);

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });

    expect(result.current.entries.map(e => e.id)).toEqual(["a", "b"]);
  });

  it("setActiveId triggers GET /layouts/{id} and stores the full entry", async () => {
    mountEmpty();
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
    mountEmpty();
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
    mountEmpty();
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

  it("clearAll empties entries, clears activeId/activeEntry, calls DELETE /layouts", async () => {
    mountEmpty();
    (globalThis.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, json: async () => [summary("a")] } as Response)   // refresh
      .mockResolvedValueOnce({ ok: true, json: async () => full("a") } as Response)         // GET a
      .mockResolvedValueOnce({ ok: true, status: 204 } as Response);                        // DELETE /layouts

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });
    await act(async () => { result.current.setActiveId("a"); });
    await waitFor(() => expect(result.current.activeEntry?.id).toBe("a"));

    await act(async () => { await result.current.clearAll(); });

    expect(result.current.entries).toEqual([]);
    expect(result.current.activeId).toBeNull();
    expect(result.current.activeEntry).toBeNull();

    // The last fetch call must have been DELETE /layouts (no id).
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    const lastCall = calls[calls.length - 1];
    expect(lastCall[0]).toMatch(/\/layouts$/);
    expect(lastCall[1]?.method).toBe("DELETE");
  });

  it("calls /layouts on mount to restore tabs across webview reloads", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => [summary("a"), summary("b")],
    } as Response);

    const { result } = renderHook(() => useLayoutCache());

    await waitFor(() => expect(result.current.entries.map(e => e.id)).toEqual(["a", "b"]));
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0])
      .toMatch(/\/layouts$/);
  });

  it("switching active tab mid-fetch does not overwrite the new active entry", async () => {
    let resolveA: (value: Response) => void = () => {};
    const aPromise = new Promise<Response>((r) => { resolveA = r; });

    mountEmpty();
    (globalThis.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, json: async () => [summary("a"), summary("b")] } as Response) // /layouts
      .mockReturnValueOnce(aPromise)                                                                     // GET a (held)
      .mockResolvedValueOnce({ ok: true, json: async () => full("b") } as Response);                     // GET b

    const { result } = renderHook(() => useLayoutCache());
    await act(async () => { await result.current.refresh(); });
    await act(async () => { result.current.setActiveId("a"); });
    // Switch to b BEFORE a's GET resolves.
    await act(async () => { result.current.setActiveId("b"); });
    await waitFor(() => expect(result.current.activeEntry?.id).toBe("b"));

    // Now let a's GET resolve — the cancelled flag should prevent it overwriting b.
    await act(async () => {
      resolveA({ ok: true, json: async () => full("a") } as Response);
      // Allow microtasks to drain.
      await new Promise(r => setTimeout(r, 0));
    });

    expect(result.current.activeEntry?.id).toBe("b");
    expect(result.current.activeId).toBe("b");
  });
});
