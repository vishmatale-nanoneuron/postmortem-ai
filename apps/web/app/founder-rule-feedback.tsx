"use client";

import { useEffect, useState } from "react";
import { founderBilling, type RuleFeedbackStat } from "./api";

// Which Airlock rules customers keep reporting as false positives, across
// accounts, over the window. Counts only -- the API never carries a note,
// a hash or content here -- and it is read, not acted on: a rule's weight
// or pattern changes in rules.py, benchmarked before it ships. Renders as
// absent until the API answers for it (the web deploys before the API).
export function FounderRuleFeedbackPanel() {
  const [stats, setStats] = useState<RuleFeedbackStat[] | null>(null);
  const [days, setDays] = useState(90);

  useEffect(() => {
    let cancelled = false;
    founderBilling
      .ruleFeedback(days)
      .then((rows) => {
        if (!cancelled) setStats(rows);
      })
      .catch(() => {
        if (!cancelled) setStats(null);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  if (stats === null) return null;

  return (
    <div className="mb-4">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-medium tracking-wide text-muted uppercase">Airlock rules customers dispute</h3>
        <label className="flex items-center gap-2 text-xs text-muted">
          Last
          <select
            className="rounded-md border border-line bg-white px-2 py-1 text-xs"
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
          >
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={365}>365 days</option>
          </select>
        </label>
      </div>
      {stats.length === 0 ? (
        <p className="rounded-md bg-paper px-3 py-2 text-sm text-muted">
          No false-positive reports in the last {days} days. When a rule shows up here from more than one account,
          re-run the benchmark with it reweighted before touching it.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full text-left text-xs">
            <thead className="bg-paper text-muted">
              <tr>
                <th className="px-3 py-1.5 font-medium">Rule</th>
                <th className="px-3 py-1.5 font-medium">Family</th>
                <th className="px-3 py-1.5 text-right font-medium">Reports</th>
                <th className="px-3 py-1.5 text-right font-medium">Accounts</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {stats.map((stat) => (
                <tr key={stat.rule_id}>
                  <td className="px-3 py-1.5 font-mono text-ink">
                    <a className="underline-offset-2 hover:underline" href={`/airlock/rules/${stat.rule_id.toLowerCase()}`}>
                      {stat.rule_id}
                    </a>
                  </td>
                  <td className="px-3 py-1.5 text-muted">{stat.family.replace(/_/g, " ")}</td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">{stat.false_positive_reports}</td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">{stat.accounts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
