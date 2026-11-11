import { useEffect, useRef } from "react";

// Call load now, then again `pause` ms after each call settles. A call never
// starts while the last is still out, so a slow backend is asked less often
// rather than buried; a hidden tab skips its turns. A new `key` starts afresh.
export function usePoll(
  load: () => Promise<unknown>,
  pause: number,
  enabled = true,
  key = "",
): void {
  const latest = useRef(load);
  latest.current = load;

  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    async function tick() {
      if (!document.hidden) {
        await latest.current().catch(() => undefined);
      }
      if (!stopped) timer = setTimeout(() => void tick(), pause);
    }
    void tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [pause, enabled, key]);
}
