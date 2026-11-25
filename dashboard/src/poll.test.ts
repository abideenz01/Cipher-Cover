import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { usePoll } from "./poll";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  Object.defineProperty(document, "hidden", {
    value: false,
    configurable: true,
  });
});

it("waits for a slow call to finish before the next one", async () => {
  const load = vi.fn(() => new Promise((resolve) => setTimeout(resolve, 3000)));
  renderHook(() => {
    usePoll(load, 2000);
  });
  expect(load).toHaveBeenCalledTimes(1);
  // Calls start at 0, 5 and 10 s: 3 s out, then a 2 s pause. With
  // setInterval(2000) there would be 5 by 9 s, 3 of them still out.
  await act(() => vi.advanceTimersByTimeAsync(9_000));
  expect(load).toHaveBeenCalledTimes(2);
  await act(() => vi.advanceTimersByTimeAsync(1_000));
  expect(load).toHaveBeenCalledTimes(3);
});

it("keeps polling after a failed call", async () => {
  const load = vi.fn(() => Promise.reject(new Error("down")));
  renderHook(() => {
    usePoll(load, 1000);
  });
  await act(() => vi.advanceTimersByTimeAsync(2_500));
  expect(load).toHaveBeenCalledTimes(3);
});

it("skips its turns while the tab is hidden", async () => {
  Object.defineProperty(document, "hidden", {
    value: true,
    configurable: true,
  });
  const load = vi.fn(() => Promise.resolve());
  renderHook(() => {
    usePoll(load, 1000);
  });
  await act(() => vi.advanceTimersByTimeAsync(5_000));
  expect(load).not.toHaveBeenCalled();
  Object.defineProperty(document, "hidden", {
    value: false,
    configurable: true,
  });
  await act(() => vi.advanceTimersByTimeAsync(1_000));
  expect(load).toHaveBeenCalledTimes(1);
});

it("stops when switched off or unmounted, and starts afresh on a new key", async () => {
  const load = vi.fn(() => Promise.resolve());
  const { rerender, unmount } = renderHook(
    ({ on, key }) => {
      usePoll(load, 1000, on, key);
    },
    { initialProps: { on: false, key: "a" } },
  );
  await act(() => vi.advanceTimersByTimeAsync(3_000));
  expect(load).not.toHaveBeenCalled();
  rerender({ on: true, key: "a" });
  expect(load).toHaveBeenCalledTimes(1);
  rerender({ on: true, key: "b" });
  expect(load).toHaveBeenCalledTimes(2);
  unmount();
  await act(() => vi.advanceTimersByTimeAsync(5_000));
  expect(load).toHaveBeenCalledTimes(2);
});
