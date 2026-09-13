"use client";

import * as React from "react";
import { airlockStats, type AirlockStats } from "../api";
import { usePolling } from "../use-polling";

// The decision counters on /airlock, kept live. The server renders the
// first values (so the numbers are in the HTML for crawlers and for a
// reader with JavaScript off), and this refreshes them from the public
// /v1/airlock/stats endpoint every REFRESH_MS while the tab is visible.
// A counter that says "945 decisions" all afternoon while the engine runs
// is a screenshot; this is the thing itself.
const REFRESH_MS = 60_000;

function n(value: number): string {
  return value.toLocaleString("en-US");
}

export function LiveCounters({ initial }: { initial: AirlockStats }) {
  const [stats, setStats] = React.useState<AirlockStats>(initial);
  const [ticked, setTicked] = React.useState(false);

  const refresh = React.useCallback(async () => {
    try {
      const next = await airlockStats();
      setStats(next);
      setTicked(true);
      window.setTimeout(() => setTicked(false), 1200);
    } catch {
      // The server-rendered numbers stay; a failed refresh is not news.
    }
  }, []);

  usePolling(() => void refresh(), REFRESH_MS);

  if (stats.total <= 0) return null;

  return (
    <p className="mb-2 flex flex-wrap items-center gap-x-1.5 font-mono text-xs text-ink" aria-live="polite">
      <span
        aria-hidden
        className={
          "inline-block size-1.5 rounded-full bg-emerald-600 transition-opacity duration-700 " +
          (ticked ? "opacity-100" : "opacity-40")
        }
        title="Refreshes every minute from /v1/airlock/stats"
      />
      <span>
        {n(stats.total)} decisions recorded · {n(stats.blocked)} blocked · {n(stats.flagged)} flagged ·{" "}
        {n(stats.last_7d)} in the last 7 days
      </span>
    </p>
  );
}
