import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { useLayoutProgress } from "./useLayoutProgress";

const SNAP = { active: true, member: 2, n_members: 3, members_completed: 1,
               best_marker_mm: 10552, total_elapsed_s: 100.5, stopped_early: false };

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("useLayoutProgress", () => {
  it("polls every 2s while active and stops when inactive", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(SNAP), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);

    const { result, rerender } = renderHook(({ a }) => useLayoutProgress(a),
                                            { initialProps: { a: true } });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });     // initial poll
    expect(result.current?.member).toBe(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(4100); });  // 2 more polls
    expect(fetchMock.mock.calls.length).toBe(3);

    rerender({ a: false });
    expect(result.current).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(4100); });
    expect(fetchMock.mock.calls.length).toBe(3);                          // no more polls
  });

  it("keeps the last snapshot when a poll fails", async () => {
    vi.useFakeTimers();
    let fail = false;
    const fetchMock = vi.fn(() => fail
      ? Promise.reject(new Error("net"))
      : Promise.resolve(new Response(JSON.stringify(SNAP), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useLayoutProgress(true));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    fail = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(result.current?.member).toBe(2);   // stale-but-present beats null
  });
});
