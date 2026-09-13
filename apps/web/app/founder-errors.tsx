"use client";

import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { founderBilling, type ErrorGroup } from "./api";
import { usePolling } from "./use-polling";

// Every unhandled 500 the API answered, one line per fault, most recent
// first -- the error tracker this product has instead of a vendor. Polls
// at the dashboard cadence so a fault that starts while the page is open
// shows up without a reload. The request id on each line is what the
// customer saw and what the log line carries.
const POLL_MS = 20_000;

function when(ms: number): string {
  return new Date(ms).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function FounderErrorsPanel({ last24h, last7d }: { last24h: number; last7d: number }) {
  const [groups, setGroups] = useState<ErrorGroup[] | null>(null);
  const [days, setDays] = useState(7);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setGroups(await founderBilling.errors(days));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load errors.");
    }
  }, [days]);

  useEffect(() => {
    void refresh();
  }, [refresh]);
  usePolling(() => void refresh(), POLL_MS);

  const healthy = last24h === 0;

  return (
    <div className="mb-6">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Application errors</h3>
        <label className="flex items-center gap-2 text-xs text-muted">
          Last
          <select
            className="rounded-md border border-line bg-white px-2 py-1 text-xs"
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
          >
            <option value={1}>1 day</option>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
        </label>
      </div>
      <p className={cn("mb-2 text-xs", healthy ? "text-emerald-700" : "text-red-700")}>
        <span className="font-mono">{last24h}</span> unhandled 500{last24h === 1 ? "" : "s"} in the last 24 hours ·{" "}
        <span className="font-mono">{last7d}</span> in 7 days. A fault not seen for a day emails you once; repeats do
        not.
      </p>
      {error && (
        <p role="status" className="mb-2 text-sm text-red-600">
          {error}
        </p>
      )}
      {groups && groups.length === 0 && <p className="text-xs text-muted">Nothing in the last {days} day{days === 1 ? "" : "s"}.</p>}
      {groups && groups.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full text-left text-xs">
            <thead className="bg-paper text-muted">
              <tr>
                <th className="px-3 py-1.5 font-medium">Fault</th>
                <th className="px-3 py-1.5 font-medium">Route</th>
                <th className="px-3 py-1.5 text-right font-medium">Count</th>
                <th className="px-3 py-1.5 font-medium">Last seen</th>
                <th className="px-3 py-1.5 font-medium">Last request id</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {groups.map((group) => (
                <tr key={group.fingerprint}>
                  <td className="px-3 py-1.5">
                    <span className="font-mono text-red-700">{group.error_type}</span>
                    {group.sample_message && <span className="block max-w-md truncate text-muted">{group.sample_message}</span>}
                  </td>
                  <td className="px-3 py-1.5 font-mono whitespace-nowrap">
                    {group.method} {group.path}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">{group.count.toLocaleString("en-US")}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap text-muted">{when(group.last_seen)}</td>
                  <td className="px-3 py-1.5 font-mono text-muted">
                    {group.last_request_id}
                    {group.notified && <span className="ml-1 text-emerald-700">· emailed</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
