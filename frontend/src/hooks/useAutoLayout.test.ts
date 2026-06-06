import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAutoLayout } from "./useAutoLayout";

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
});
