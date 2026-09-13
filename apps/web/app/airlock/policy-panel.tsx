"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { airlock, type AirlockPolicy, type AirlockRule, type AirlockUsage } from "../api";
import { usePolling } from "../use-polling";

// The policy editor and the usage table for the Airlock section of the
// dashboard. The policy is the account's: it is read by every scan under
// any of the account's keys, and it is only ever written from here (a
// signed-in session), never with a key. The usage table is the ledger by
// day and by key, with a CSV of the raw lines for a spreadsheet.

const fieldLabel = "block text-xs font-medium text-muted mb-1";
const fieldInput =
  "w-full rounded-md border border-line px-3 py-2 mb-3 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";

const USAGE_POLL_MS = 20_000;

const FAMILY_LABEL: Record<string, string> = {
  instruction_override: "Instruction override",
  role_hijack: "Role hijack",
  delimiter_break: "Delimiter break",
  exfiltration: "Exfiltration",
  tool_abuse: "Tool abuse",
  authority_spoof: "Authority spoof",
  memory_poison: "Memory poison",
  encoding: "Encoding",
};

function family(name: string): string {
  return FAMILY_LABEL[name] ?? name;
}

// ---------------------------------------------------------------------------
// Policy
// ---------------------------------------------------------------------------

export function PolicyEditor() {
  const [policy, setPolicy] = useState<AirlockPolicy | null>(null);
  const [rules, setRules] = useState<AirlockRule[]>([]);
  const [block, setBlock] = useState("0.75");
  const [flag, setFlag] = useState("0.40");
  const [muted, setMuted] = useState<Set<string>>(new Set());
  const [allowlist, setAllowlist] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  const load = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([airlock.policy(), airlock.rules()]);
      setPolicy(p);
      setRules(r.rules);
      setBlock(p.block_threshold.toFixed(2));
      setFlag(p.flag_threshold.toFixed(2));
      setMuted(new Set(p.muted_rules));
      setAllowlist(p.egress_allowlist.join("\n"));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your policy.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const next = await airlock.setPolicy({
        block_threshold: Number(block),
        flag_threshold: Number(flag),
        muted_rules: [...muted],
        egress_allowlist: allowlist
          .split(/[\n,]/)
          .map((host) => host.trim())
          .filter(Boolean),
      });
      setPolicy(next);
      setMuted(new Set(next.muted_rules));
      setAllowlist(next.egress_allowlist.join("\n"));
      setSaved("Saved. Applies to the next call on any of your keys.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the policy.");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm("Reset to the engine defaults (block at 0.75, flag at 0.40, nothing muted, no allowlist)?")) return;
    setBusy(true);
    setError("");
    try {
      await airlock.resetPolicy();
      await load();
      setSaved("Back to the defaults.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset the policy.");
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string) {
    setMuted((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const summary = policy
    ? policy.default
      ? "Engine defaults"
      : `Block ≥ ${policy.block_threshold.toFixed(2)} · flag ≥ ${policy.flag_threshold.toFixed(2)} · ${policy.muted_rules.length} muted · ${policy.egress_allowlist.length} allowlisted`
    : "…";

  return (
    <div className="mb-4">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">Policy</h3>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="text-xs text-accent underline-offset-2 hover:underline"
          aria-expanded={open}
          aria-controls="airlock-policy-form"
        >
          {open ? "Hide" : "Edit"}
        </button>
      </div>
      <p className="mb-2 text-xs text-muted">
        <span className="font-mono text-ink">{summary}</span> — the thresholds every verdict on this account is judged
        against, the rules that are not consulted, and hosts an egress call may always reach. Set from here only;
        a key cannot change it.
      </p>
      {error && (
        <p role="status" className="mb-2 text-sm text-red-600">
          {error}
        </p>
      )}
      {open && policy && (
        <form id="airlock-policy-form" onSubmit={save} className="rounded-md border border-line bg-paper p-3">
          <div className="grid gap-x-3 sm:grid-cols-2">
            <div>
              <label htmlFor="airlock-block" className={fieldLabel}>
                Block at or above
              </label>
              <input
                id="airlock-block"
                className={fieldInput}
                type="number"
                min="0.01"
                max="1"
                step="0.01"
                value={block}
                onChange={(event) => setBlock(event.target.value)}
                required
              />
            </div>
            <div>
              <label htmlFor="airlock-flag" className={fieldLabel}>
                Flag at or above
              </label>
              <input
                id="airlock-flag"
                className={fieldInput}
                type="number"
                min="0.01"
                max="1"
                step="0.01"
                value={flag}
                onChange={(event) => setFlag(event.target.value)}
                required
              />
            </div>
          </div>
          <p className="-mt-1 mb-3 text-[11px] text-muted">
            Scores are 0–1. Lower the block line to be stricter; the flag line must not exceed it.
          </p>

          <label htmlFor="airlock-allowlist" className={fieldLabel}>
            Egress allowlist — one host per line (a leading dot allows every subdomain)
          </label>
          <textarea
            id="airlock-allowlist"
            className={cn(fieldInput, "min-h-20 font-mono")}
            value={allowlist}
            onChange={(event) => setAllowlist(event.target.value)}
            placeholder={"api.openai.com\n.internal.example.com"}
            spellCheck={false}
          />
          <p className="-mt-1 mb-3 text-[11px] text-muted">
            Merged with any <code className="font-mono">allowlist</code> sent on the call. Empty means destinations
            are not checked, and the response says so.
          </p>

          <fieldset className="mb-3">
            <legend className={fieldLabel}>Muted rules — skipped for this account ({muted.size} of {rules.length})</legend>
            <div className="max-h-56 overflow-y-auto rounded-md border border-line bg-white">
              {rules.map((rule) => (
                <label
                  key={rule.id}
                  className="flex cursor-pointer items-start gap-2 border-b border-line px-2 py-1.5 text-xs last:border-b-0"
                >
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={muted.has(rule.id)}
                    onChange={() => toggle(rule.id)}
                    aria-label={`Mute ${rule.id}`}
                  />
                  <span className="min-w-0">
                    <span className="font-mono text-ink">{rule.id}</span>
                    <span className="ml-1 text-muted">
                      {family(rule.family)} · {rule.weight.toFixed(2)}
                    </span>
                    <span className="block text-muted">{rule.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" size="sm" disabled={busy}>
              {busy ? "Saving…" : "Save policy"}
            </Button>
            {!policy.default && (
              <Button type="button" size="sm" variant="outline" disabled={busy} onClick={reset}>
                Reset to defaults
              </Button>
            )}
            {saved && (
              <span role="status" className="text-xs text-emerald-700">
                {saved}
              </span>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Usage
// ---------------------------------------------------------------------------

export function UsagePanel() {
  const [usage, setUsage] = useState<AirlockUsage | null>(null);
  const [days, setDays] = useState(30);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setUsage(await airlock.usage(days));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load usage.");
    }
  }, [days]);

  useEffect(() => {
    void refresh();
  }, [refresh]);
  usePolling(() => void refresh(), USAGE_POLL_MS);

  async function download() {
    setExporting(true);
    setError("");
    try {
      const { filename, text } = await airlock.usageCsv(Math.max(days, 90));
      const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not export usage.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="mb-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Usage · live</h3>
        <div className="flex items-center gap-2 text-xs">
          <label htmlFor="airlock-usage-days" className="text-muted">
            Last
          </label>
          <select
            id="airlock-usage-days"
            className="rounded-md border border-line bg-white px-2 py-1 text-xs"
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
          >
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={365}>365 days</option>
          </select>
          <Button type="button" size="sm" variant="outline" onClick={download} disabled={exporting}>
            {exporting ? "Preparing…" : "Download CSV"}
          </Button>
        </div>
      </div>
      {error && (
        <p role="status" className="mb-2 text-sm text-red-600">
          {error}
        </p>
      )}
      {usage && usage.rows.length === 0 && (
        <p className="text-xs text-muted">No metered calls in the last {usage.days} days.</p>
      )}
      {usage && usage.rows.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full text-left text-xs">
            <thead className="bg-paper text-muted">
              <tr>
                <th className="px-3 py-1.5 font-medium">Day (UTC)</th>
                <th className="px-3 py-1.5 font-medium">Key</th>
                <th className="px-3 py-1.5 text-right font-medium">Scans</th>
                <th className="px-3 py-1.5 text-right font-medium">Deep</th>
                <th className="px-3 py-1.5 text-right font-medium">Egress</th>
                <th className="px-3 py-1.5 text-right font-medium">Credits</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {usage.rows.map((row) => (
                <tr key={`${row.day}-${row.key_prefix ?? "dashboard"}`}>
                  <td className="px-3 py-1.5 font-mono whitespace-nowrap text-muted">{row.day}</td>
                  <td className="px-3 py-1.5 font-mono text-muted">{row.key_prefix ? `${row.key_prefix}…` : "dashboard"}</td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">{row.scans.toLocaleString("en-US")}</td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">{row.deep_scans.toLocaleString("en-US")}</td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">{row.egress.toLocaleString("en-US")}</td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums text-ink">
                    {row.credits.toLocaleString("en-US")}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-paper text-muted">
              <tr>
                <td className="px-3 py-1.5" colSpan={5}>
                  Total, {usage.days} days
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums text-ink">
                  {usage.total_credits.toLocaleString("en-US")}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
