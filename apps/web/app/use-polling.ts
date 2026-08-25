"use client";
import { useEffect, useRef } from "react";

// Real-time-ish UI updates via polling -- the pragmatic choice for this
// backend: it's Vercel serverless functions, so a websocket connection
// would need to be held open per client with no natural place for a
// long-lived process to own that state, versus a plain periodic fetch
// which fits the same request/response model every other call here
// already uses. Pauses while the tab is hidden (document.visibilityState)
// so a backgrounded tab doesn't keep polling for no one to see it.
export function usePolling(callback: () => void, intervalMs: number): void {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "visible") callbackRef.current();
    };
    const id = window.setInterval(tick, intervalMs);
    // Also refresh immediately on returning to the tab, rather than
    // waiting up to a full interval to catch up on what was missed.
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [intervalMs]);
}
