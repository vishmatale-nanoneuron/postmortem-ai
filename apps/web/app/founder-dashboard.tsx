"use client";

import { useEffect, useRef, useState } from "react";
import { api, founderActivity, founderBilling, type FounderActivityLogEntry, type EconomicsWindow, type FounderSummary, type PaymentClaim, type PaymentClaimEvent } from "./api";
import { cn } from "@/lib/utils";
import { usePolling } from "./use-polling";
import { FounderErrorsPanel } from "./founder-errors";
import { FounderRuleFeedbackPanel } from "./founder-rule-feedback";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ActivityLogRow, DashboardSkeleton, POLL_INTERVAL_MS, card, currencySymbol, fieldInput, fieldLabel, formatDuration, timeAgo } from "./dashboard-shared";

export default function FounderDashboard() {
  const [summary, setSummary] = useState<FounderSummary | null>(null);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  function refresh() {
    api
      .founderSummary()
      .then((result) => {
        setSummary(result);
        setLastUpdated(Date.now());
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load founder summary."));
  }

  async function manualRefresh() {
    setRefreshing(true);
    try {
      await api.founderSummary().then((result) => {
        setSummary(result);
        setLastUpdated(Date.now());
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load founder summary.");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(refresh, []);
  usePolling(refresh, POLL_INTERVAL_MS);

  if (error) return <p className="mb-4 text-sm text-red-600">{error}</p>;
  if (!summary) return <DashboardSkeleton />;

  const stats: [string, number | string][] = [
    ["Users", summary.total_users],
    ["Incidents", summary.total_incidents],
    ["Open incidents", summary.open_incidents],
    ["Resolved incidents", summary.resolved_incidents],
    ["Avg time to resolve", summary.avg_resolution_ms != null ? formatDuration(summary.avg_resolution_ms) : "--"],
    ["Drafted postmortems", summary.drafted_postmortems],
    ["Published postmortems", summary.published_postmortems],
    ["AI runs (ok / failed)", `${summary.ai_runs_succeeded} / ${summary.ai_runs_failed}`],
    ["Avg draft latency", summary.ai_runs_avg_latency_ms != null ? `${summary.ai_runs_avg_latency_ms} ms` : "--"],
    ["Pending payment claims", summary.pending_payment_claims],
  ];

  // All-time totals stay reassuringly high for months even while
  // something is actively broken right now -- this is "is it broken
  // today," shown separately so a real ongoing incident can't hide inside
  // a lifetime average.
  const health24hLabel =
    summary.ai_runs_24h_total === 0
      ? "No AI calls in the last 24h"
      : `${summary.ai_runs_24h_succeeded}/${summary.ai_runs_24h_total} succeeded in the last 24h`;
  const health24hOk = summary.ai_runs_24h_failed === 0;

  const nav: [string, string][] = [
    ["AI health", "#founder-ai-health"],
    ["Errors", "#founder-errors"],
    ["Stats", "#founder-stats"],
    ["Margin", "#founder-margin"],
    ["Funnel", "#founder-funnel"],
    ["Airlock", "#founder-airlock"],
    ["Signups", "#founder-signups"],
    ["AI runs", "#founder-ai-runs"],
    ["Payment claims", "#founder-claims"],
    ["Agent activity", "#founder-agent-activity"],
  ];

  return (
    <Card className={card}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold">Founder dashboard</h2>
        <div className="flex items-center gap-2 text-xs text-muted">
          {lastUpdated && <span title={new Date(lastUpdated).toLocaleTimeString()}>Updated {timeAgo(lastUpdated)}</span>}
          <button
            type="button"
            onClick={() => void manualRefresh()}
            disabled={refreshing}
            className="rounded-md border border-line px-2 py-1 text-xs text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Refresh now"
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>
      {/* A long single-scroll page previously had no way to jump between
          sections -- a sticky quick-nav so "check payment claims" or
          "check AI health" doesn't mean scrolling past everything else
          every single visit. Sticky within the card's own scroll context
          (top-0 relative to the viewport once this section reaches it),
          not a page-wide fixed bar, so it never covers the app's own
          header above it. */}
      <nav
        aria-label="Founder dashboard sections"
        className="sticky top-0 z-10 -mx-4 mb-4 flex flex-wrap gap-1.5 border-b border-line bg-white/95 px-4 py-2 backdrop-blur-sm sm:-mx-5 sm:px-5"
      >
        {nav.map(([label, href]) => (
          <a
            key={href}
            href={href}
            className="rounded-md px-2 py-1 text-xs text-muted transition hover:bg-paper hover:text-ink"
          >
            {label}
          </a>
        ))}
      </nav>
      <div
        id="founder-ai-health"
        className={cn(
          "scroll-mt-16 mb-4 flex items-center justify-between rounded-md px-3 py-2 text-sm",
          summary.ai_runs_24h_total === 0
            ? "bg-paper text-muted"
            : health24hOk
              ? "bg-accent/10 text-accent"
              : "bg-red-50 text-red-700",
        )}
      >
        <span className="font-medium">{health24hLabel}</span>
        {summary.ai_runs_24h_avg_latency_ms != null && (
          <span>avg {summary.ai_runs_24h_avg_latency_ms} ms</span>
        )}
      </div>
      <div id="founder-stats" className="mb-4 grid scroll-mt-16 grid-cols-2 gap-3 sm:grid-cols-4">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-md bg-paper px-3 py-2">
            <div className="text-lg font-semibold text-ink">{value}</div>
            <div className="text-xs text-muted">{label}</div>
          </div>
        ))}
      </div>
      <div id="founder-margin" className="scroll-mt-16">
        <UnitEconomicsPanel economics={summary.unit_economics} />
      </div>
      <div id="founder-funnel" className="scroll-mt-16">
        <ConversionFunnelPanel funnel={summary.conversion_funnel} />
      </div>
      <div id="founder-airlock" className="scroll-mt-16">
        <AirlockBusinessPanel airlock={summary.airlock} waitlist={summary.airlock_waitlist} />
        <FounderRuleFeedbackPanel />
      </div>
      {summary.ai_runs_by_feature.length > 0 && (
        <>
          <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">AI features (by prompt version)</h3>
          <ul className="mb-4 space-y-1 text-sm">
            {summary.ai_runs_by_feature.map((feature) => (
              <li key={feature.prompt_version} className="flex justify-between rounded-md bg-paper px-3 py-1.5">
                <span className="font-mono text-xs">{feature.prompt_version}</span>
                <span>
                  {feature.succeeded}/{feature.total} ok
                  {feature.failed > 0 && <span className="text-red-600"> -- {feature.failed} failed</span>}
                  {feature.avg_latency_ms != null && <span className="text-muted"> -- avg {feature.avg_latency_ms} ms</span>}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      <h3 id="founder-signups" className="mb-1.5 scroll-mt-16 text-xs font-medium tracking-wide text-muted uppercase">
        Recent signups
      </h3>
      <ul className="mb-4 space-y-1 text-sm">
        {summary.recent_users.length === 0 ? (
          <li className="text-muted">None yet.</li>
        ) : (
          summary.recent_users.map((u) => (
            <li key={u.id} className="flex justify-between rounded-md bg-paper px-3 py-1.5">
              <span>{u.email}</span>
              <span className="text-muted">{new Date(u.created_at).toLocaleString()}</span>
            </li>
          ))
        )}
      </ul>
      <h3 id="founder-ai-runs" className="mb-1.5 scroll-mt-16 text-xs font-medium tracking-wide text-muted uppercase">
        Recent AI runs
      </h3>
      <ul className="space-y-1 text-sm">
        {summary.recent_ai_runs.length === 0 ? (
          <li className="text-muted">None yet.</li>
        ) : (
          summary.recent_ai_runs.map((run) => (
            <li key={run.id} className="flex justify-between rounded-md bg-paper px-3 py-1.5">
              <span>
                {run.provider}/{run.model} -- {run.status}
                {run.error_type ? ` (${run.error_type})` : ""}
              </span>
              <span className="text-muted">{run.latency_ms} ms</span>
            </li>
          ))
        )}
      </ul>
      <div id="founder-errors" className="scroll-mt-16">
        <FounderErrorsPanel last24h={summary.errors?.last_24h ?? 0} last7d={summary.errors?.last_7d ?? 0} />
      </div>
      <div id="founder-claims" className="scroll-mt-16">
        <PaymentClaimsReview />
      </div>
      <div id="founder-airlock-grant" className="scroll-mt-16">
        <AirlockGrantForm />
      </div>
      <div id="founder-agent-activity" className="scroll-mt-16">
        <AgentActivityPanel />
      </div>
    </Card>
  );
}

// Founder-only: credit Airlock scans to an account for anything that is not
// a payment (a refund credited as scans, a pilot for a prospect, goodwill
// after an outage). Paid credits come from approving a claim above; this
// is deliberately a separate form with a mandatory note, and every grant
// is a ledger line the customer can read in their own statement.
function AirlockGrantForm() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function grant(form: FormData) {
    const email = String(form.get("email") ?? "").trim();
    const credits = Number(form.get("credits") ?? 0);
    const reason = String(form.get("reason") ?? "grant") as "grant" | "refund" | "adjustment";
    const note = String(form.get("note") ?? "").trim();
    if (!email || !Number.isInteger(credits) || credits < 1 || !note) {
      return setError("Email, a whole number of credits, and a note are all required.");
    }
    if (!window.confirm(`Grant ${credits.toLocaleString("en-IN")} Airlock credits to ${email}?\n\nReason: ${reason}\nNote: ${note}`)) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await founderBilling.grantAirlockCredits(email, credits, reason, note);
      setMessage(`Granted. ${result.email} now has ${result.balance.toLocaleString("en-IN")} credits.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not grant credits.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 border-t border-line pt-4">
      <h3 className="mb-1 text-sm font-semibold">Grant Airlock credits</h3>
      <p className="mb-2 text-xs text-muted">
        For refunds, pilots and goodwill -- not for payments, which are approved above. Lands as a ledger line with
        your note on it.
      </p>
      <form action={grant} className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr]">
        <div>
          <label className={fieldLabel} htmlFor="airlock-grant-email">
            Account email
          </label>
          <input id="airlock-grant-email" className={`${fieldInput} mb-0`} name="email" type="email" required />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="airlock-grant-credits">
            Credits
          </label>
          <input id="airlock-grant-credits" className={`${fieldInput} mb-0`} name="credits" type="number" min={1} step={1} required />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="airlock-grant-reason">
            Reason
          </label>
          <select id="airlock-grant-reason" className={`${fieldInput} mb-0`} name="reason" defaultValue="grant">
            <option value="grant">grant</option>
            <option value="refund">refund</option>
            <option value="adjustment">adjustment</option>
          </select>
        </div>
        <div className="sm:col-span-3">
          <label className={fieldLabel} htmlFor="airlock-grant-note">
            Note (shown on the customer&apos;s statement)
          </label>
          <input id="airlock-grant-note" className={`${fieldInput} mb-0`} name="note" maxLength={200} required />
        </div>
        <div className="sm:col-span-3">
          <Button variant="ink" size="app" disabled={busy} type="submit">
            {busy ? "Granting..." : "Grant credits"}
          </Button>
        </div>
      </form>
      {message && <p className="mt-2 text-sm text-accent">{message}</p>}
      {error && (
        <p role="status" className="mt-2 text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

// The cross-account counterpart to the client-scoped ActivityLogPanel
// further down this file -- that one only ever shows the caller's own
// history; this is the actual accountability surface for an autonomous
// agent acting across every account, not just one. Same source of truth
// (account_activity_log via cqrs/activity.py's query handler), reached
// here through GET /v1/founder/activity-log instead of
// GET /v1/postmortems/activity-log.
// Shared between AgentActivityPanel (founder, cross-account) and
// ActivityLogPanel (a client's own history, further down this file) --
// previously each hand-rolled its own near-identical badge and list-item
// markup, which had already started drifting (different wrapper classes,
// different badge title wording) with no test or lint catching it. One
// shared shape now; a future styling/accessibility fix only needs to
// happen once.

function AgentActivityPanel() {
  const [entries, setEntries] = useState<FounderActivityLogEntry[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [clientEmail, setClientEmail] = useState("");
  const [debouncedClientEmail, setDebouncedClientEmail] = useState("");
  const [source, setSource] = useState<"" | "web" | "mcp_agent">("");
  const [error, setError] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  // Guards against out-of-order responses: only the most recently *fired*
  // request's result is ever applied to state. Debouncing below cuts down
  // how often a request fires per keystroke, but doesn't by itself
  // guarantee responses land in the order they were sent -- this ref does.
  const requestIdRef = useRef(0);

  // Without this, every keystroke into the free-text email filter fired
  // its own request -- both wasteful and, combined with the ordering risk
  // above, the actual mechanism that could show results for a filter the
  // founder no longer has typed.
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedClientEmail(clientEmail.trim()), 300);
    return () => clearTimeout(handle);
  }, [clientEmail]);

  function load(reset: boolean): Promise<void> {
    const requestId = ++requestIdRef.current;
    return founderActivity
      .list({
        clientEmail: debouncedClientEmail || undefined,
        source: source || undefined,
        cursor: reset ? undefined : (nextCursor ?? undefined),
        limit: 20,
      })
      .then((page) => {
        if (requestId !== requestIdRef.current) return; // superseded by a newer request
        setEntries((prev) => (reset ? page.entries : [...prev, ...page.entries]));
        setNextCursor(page.next_cursor);
        setError("");
      })
      .catch((err) => {
        if (requestId !== requestIdRef.current) return;
        setError(err instanceof Error ? err.message : "Could not load agent activity.");
      });
  }

  // Re-run whenever a filter changes, always as a fresh (non-appending)
  // load -- changing a filter mid-pagination should start over, not
  // append mismatched pages onto the existing list.
  useEffect(() => {
    void load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedClientEmail, source]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      await load(false);
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div>
      <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">
        Agent activity (every account)
      </h3>
      <p className="mb-2 text-xs text-muted">
        Who -- or which AI agent -- did what, across every account, not just your own. The same audit
        trail each client sees for their own history, filterable here by account and by whether it came
        from the browser or from an MCP tool call.
      </p>
      <div className="mb-2 flex flex-wrap gap-2">
        <input
          className={cn(fieldInput, "mb-0 max-w-64")}
          placeholder="Filter by account email"
          value={clientEmail}
          onChange={(e) => setClientEmail(e.target.value)}
        />
        <select
          className={cn(fieldInput, "mb-0 w-auto")}
          value={source}
          onChange={(e) => setSource(e.target.value as "" | "web" | "mcp_agent")}
        >
          <option value="">All sources</option>
          <option value="web">Web only</option>
          <option value="mcp_agent">AI agent only</option>
        </select>
      </div>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
      {entries.length === 0 && !error ? (
        <p className="text-sm text-muted">No matching activity yet.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {entries.map((entry, i) => (
            <ActivityLogRow
              key={i}
              action={entry.action}
              detail={entry.detail}
              source={entry.source}
              createdAt={entry.created_at}
              clientEmail={entry.client_email}
            />
          ))}
        </ul>
      )}
      {nextCursor && (
        <button
          type="button"
          className="mt-2 text-xs text-ink underline underline-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={loadingMore}
          onClick={() => void loadMore()}
        >
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}

// The one question every other number on this page dances around: is the
// model spend covered by what came in? Spend is shown as a ceiling ("at
// most"), never an estimate -- see EconomicsWindow in api.ts -- and revenue
// stays in INR next to spend in USD rather than being blended through a
// made-up exchange rate. Runs that reported no token count are called out
// because sum() drops them silently and a spend figure that quietly skips
// calls is exactly the reassuring-but-wrong number this dashboard avoids.
function UnitEconomicsPanel({ economics }: { economics: FounderSummary["unit_economics"] }) {
  const monthLabel = new Date(economics.month_start).toLocaleString(undefined, { month: "long", year: "numeric", timeZone: "UTC" });
  const windows: [string, EconomicsWindow][] = [
    [`This month (${monthLabel}, UTC)`, economics.month],
    ["All time", economics.all_time],
  ];
  const usd = (n: number) => `$${n.toFixed(2)}`;
  const inr = (n: number) => `\u20B9${n.toLocaleString("en-IN")}`;
  return (
    <div className="mb-4">
      <h3 className="mb-2 text-sm font-semibold text-ink">Margin</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {windows.map(([label, w]) => (
          <div key={label} className="rounded-md bg-paper px-3 py-2">
            <div className="text-xs text-muted">{label}</div>
            <div className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <div>
                <span className="text-lg font-semibold text-ink">{usd(w.ai_cost_usd_max)}</span>
                <span className="ml-1 text-xs text-muted">AI spend, at most</span>
              </div>
              <div>
                <span className="text-lg font-semibold text-ink">{inr(w.revenue_inr)}</span>
                <span className="ml-1 text-xs text-muted">revenue</span>
              </div>
            </div>
            <div className="mt-1 text-xs text-muted">
              {w.ai_runs} AI {w.ai_runs === 1 ? "call" : "calls"}, {w.ai_tokens.toLocaleString("en-IN")} tokens
              {w.ai_runs_without_token_data > 0 && (
                <span className="text-red-700">
                  {" "}
                  -- {w.ai_runs_without_token_data} recorded no token count and {w.ai_runs_without_token_data === 1 ? "is" : "are"} not
                  in the spend figure
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">
        Spend is a ceiling: every token priced at ${economics.ai_price_usd_per_million_tokens.toFixed(2)} per million ({economics.ai_price_basis}); the
        long evidence prompt is most of the tokens and bills lower, so the real figure is under this. Revenue is approved UPI and
        wire claims by approval date -- the only payment rails.
      </p>
    </div>
  );
}

// Answers "where do accounts actually drop off," which raw activity counts
// (incidents, drafts) don't -- a signup who never touches the free incident,
// one who tries it and never pays, and one who paid once and lapsed are
// three different problems needing three different fixes, not one blended
// "conversion rate."
// Is the main product earning? Sold vs used vs outstanding, in credits,
// plus real approved revenue per currency. Granted credits (pilots,
// refunds) are shown but never counted as revenue.
function AirlockBusinessPanel({
  airlock,
  waitlist,
}: {
  airlock: FounderSummary["airlock"];
  waitlist: FounderSummary["airlock_waitlist"];
}) {
  const n = (value: number) => value.toLocaleString("en-US");
  return (
    <div className="mb-4">
      <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">Airlock</h3>
      <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {(
          [
            [n(airlock.credits_sold_total), "Credits sold"],
            [n(airlock.credits_used_total), "Credits used, all time"],
            [n(airlock.credits_used_last_7d), "Credits used, 7 days"],
            [n(airlock.credits_outstanding), "Prepaid, unspent"],
            [n(airlock.accounts_with_balance), "Accounts with credits"],
            [n(airlock.active_keys), "Active API keys"],
            [n(airlock.credits_granted_total), "Granted (not revenue)"],
            [`${n(waitlist.total)} / ${n(waitlist.last_7d)}`, "Self-hosted list, total / 7d"],
          ] as [string, string][]
        ).map(([value, label]) => (
          <div key={label} className="rounded-md bg-paper px-3 py-2">
            <div className="text-lg font-semibold text-ink">{value}</div>
            <div className="text-xs text-muted">{label}</div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">
        {airlock.revenue_by_currency.length === 0
          ? "No approved Airlock pack yet."
          : "Approved packs: " +
            airlock.revenue_by_currency
              .map((r) => `${currencySymbol(r.currency)}${r.amount.toLocaleString("en-US")} (${r.claims} ${r.claims === 1 ? "claim" : "claims"})`)
              .join(" · ")}
      </p>
    </div>
  );
}

function ConversionFunnelPanel({ funnel }: { funnel: FounderSummary["conversion_funnel"] }) {
  const pct = (n: number) => (funnel.signups === 0 ? "--" : `${Math.round((n / funnel.signups) * 100)}%`);
  const stages: [string, number, string][] = [
    ["Signed up", funnel.signups, "100%"],
    ["Tried the free incident", funnel.tried_free_incident, pct(funnel.tried_free_incident)],
    ["Ever paid", funnel.ever_paid, pct(funnel.ever_paid)],
    ["Currently paying", funnel.currently_paying, pct(funnel.currently_paying)],
  ];
  return (
    <div className="mb-4">
      <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">Conversion funnel</h3>
      {funnel.signups === 0 ? (
        <p className="rounded-md bg-paper px-3 py-2 text-sm text-muted">
          No real signups yet (founder account excluded) -- nothing to convert until there&apos;s real traffic.
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {stages.map(([label, value, percent], i) => (
            <div
              key={label}
              className="animate-in fade-in slide-in-from-bottom-1 rounded-md bg-paper px-3 py-2 fill-mode-backwards duration-300"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <div className="text-lg font-semibold text-ink">
                {value} <span className="text-xs font-normal text-muted">({percent})</span>
              </div>
              <div className="text-xs text-muted">{label}</div>
            </div>
          ))}
        </div>
      )}
      {funnel.ever_paid > 0 && (
        <p className="mt-2 text-xs text-muted">
          Of {funnel.ever_paid} who ever paid, {funnel.approved_manual_claims} came through a founder-approved UPI or
          wire claim -- the only payment rails.
        </p>
      )}
    </div>
  );
}

function PaymentClaimsReview() {
  const [claims, setClaims] = useState<PaymentClaim[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loaded, setLoaded] = useState(false);
  // Which claim's full history is currently expanded, and what it holds
  // once fetched -- lazy per-claim, not preloaded for every claim on every
  // poll, since the ledger is only actually needed when a founder wants to
  // check one specific claim's history before deciding something.
  const [openHistoryId, setOpenHistoryId] = useState<string | null>(null);
  const [historyById, setHistoryById] = useState<Record<string, PaymentClaimEvent[]>>({});
  const [historyLoading, setHistoryLoading] = useState(false);

  async function toggleHistory(claimId: string) {
    if (openHistoryId === claimId) {
      setOpenHistoryId(null);
      return;
    }
    setOpenHistoryId(claimId);
    if (historyById[claimId]) return;
    setHistoryLoading(true);
    try {
      const events = await founderBilling.claimEvents(claimId);
      setHistoryById((prev) => ({ ...prev, [claimId]: events }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load claim history.");
    } finally {
      setHistoryLoading(false);
    }
  }

  async function refresh() {
    setClaims(await founderBilling.paymentClaims());
    setLastUpdated(Date.now());
    setLoaded(true);
  }

  async function manualRefresh() {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);
  usePolling(() => void refresh(), POLL_INTERVAL_MS);

  async function annotate(claimId: string, reference: string) {
    // A note only ever appends to payment_claim_events -- it never touches
    // status or grants/revokes access. For recording something that
    // happened outside the normal approve/reject flow (e.g. correcting a
    // past decision) so the audit trail stays complete.
    const detail = window.prompt(`Add a note to reference "${reference}" (visible in this claim's audit log only):`);
    if (!detail || !detail.trim()) return;
    setBusyId(claimId);
    setError("");
    try {
      await founderBilling.annotateClaim(claimId, detail.trim());
      setHistoryById((prev) => {
        if (!(claimId in prev)) return prev;
        const rest = { ...prev };
        delete rest[claimId];
        return rest;
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add note.");
    } finally {
      setBusyId(null);
    }
  }

  async function act(
    claimId: string,
    action: "approve" | "reject",
    reference: string,
    bankVerified: boolean,
    billingPeriod: string,
    product: string = "postmortem",
    scanCredits: number | null = null,
  ) {
    // Approving is what actually grants access -- a single accidental
    // click here previously had no safety net at all (this is exactly how
    // a claim with no real payment behind it got approved once already).
    // Approval always requires this explicit click, bank-verified or not
    // -- automation (bank_alerts.py) only ever marks a claim verified, it
    // never approves anything itself, per explicit instruction.
    if (action === "approve") {
      // State the duration explicitly. An annual claim grants 365 days, and
      // approving one believing it to be the usual 30 is an expensive,
      // silent mistake -- the two claims looked identical here before.
      // An Airlock claim grants scan credits, not time; say which.
      const grant =
        product === "airlock"
          ? `${(scanCredits ?? 0).toLocaleString("en-IN")} Airlock scan credits`
          : billingPeriod === "annual"
            ? "a FULL YEAR (365 days) of paid access"
            : "30 days of paid access";
      const confirmed = bankVerified
        ? window.confirm(
            `Approve reference "${reference}"?\n\nThis grants ${grant}.\n\nA real forwarded bank alert already matched this exact reference and amount.`,
          )
        : window.confirm(
            `Approve reference "${reference}"?\n\nThis grants ${grant}.\n\nNo bank alert has matched this yet -- only click OK if you have personally checked your bank/UPI statement and confirmed this exact amount and reference actually arrived.`,
          );
      if (!confirmed) return;
    }
    setBusyId(claimId);
    setError("");
    try {
      if (action === "approve") await founderBilling.approveClaim(claimId);
      else await founderBilling.rejectClaim(claimId);
      setHistoryById((prev) => {
        if (!(claimId in prev)) return prev;
        const rest = { ...prev };
        delete rest[claimId];
        return rest;
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update claim.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <div className="mt-4 mb-1.5 flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium tracking-wide text-muted uppercase">Payment claims</h3>
        <div className="flex items-center gap-2 text-xs text-muted">
          {lastUpdated && <span title={new Date(lastUpdated).toLocaleTimeString()}>Updated {timeAgo(lastUpdated)}</span>}
          <button
            type="button"
            onClick={() => void manualRefresh()}
            disabled={refreshing}
            className="rounded-md border border-line px-2 py-0.5 text-xs text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Refresh now"
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>
      {!loaded ? (
        <ul className="space-y-1.5" aria-hidden="true">
          {Array.from({ length: 2 }).map((_, i) => (
            <li key={i}>
              <Skeleton className="h-10 w-full rounded-md bg-paper" />
            </li>
          ))}
        </ul>
      ) : (
      <ul className="space-y-1.5 text-sm">
        {claims.length === 0 ? (
          <li className="text-muted">None yet.</li>
        ) : (
          claims.map((claim) => (
            <li key={claim.id} className="rounded-md bg-paper px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="min-w-0 flex-1">
                <span className="font-medium">{claim.email}</span> --{" "}
                {currencySymbol(claim.currency)}
                {claim.amount} via {claim.method === "wire" ? "SWIFT wire" : "UPI"}, ref{" "}
                <span className="font-mono text-xs">{claim.reference}</span>
                <span className="text-muted"> ({claim.status})</span>
                {claim.product === "airlock" && (
                  <span
                    className="ml-1.5 rounded-full bg-accent/10 px-1.5 py-0.5 text-xs font-medium text-accent"
                    title="Approving this grants Airlock scan credits, not a subscription"
                  >
                    AIRLOCK · {(claim.scan_credits ?? 0).toLocaleString("en-IN")} scans
                  </span>
                )}
                {claim.product !== "airlock" && claim.billing_period === "annual" && (
                  // Visible before the click, not only in the confirm dialog:
                  // a year-long grant should never be something you discover
                  // after approving.
                  <span
                    className="ml-1.5 rounded-full bg-ink px-1.5 py-0.5 text-xs font-medium text-paper"
                    title="Approving this grants 365 days of access, not 30"
                  >
                    ANNUAL · 365 days
                  </span>
                )}
                {claim.bank_verified && (
                  <span className="ml-1.5 rounded-full bg-accent/10 px-1.5 py-0.5 text-xs font-medium text-accent">
                    ✓ Bank verified
                  </span>
                )}
              </span>
              {claim.status === "pending" && (
                <span className="flex shrink-0 gap-1.5">
                  <button
                    className="rounded-md bg-ink px-2 py-1 text-xs font-medium text-paper disabled:opacity-50"
                    disabled={busyId === claim.id}
                    onClick={() =>
                      void act(
                        claim.id,
                        "approve",
                        claim.reference,
                        claim.bank_verified,
                        claim.billing_period,
                        claim.product ?? "postmortem",
                        claim.scan_credits ?? null,
                      )
                    }
                    type="button"
                  >
                    Approve
                  </button>
                  <button
                    className="rounded-md border border-line px-2 py-1 text-xs text-muted disabled:opacity-50"
                    disabled={busyId === claim.id}
                    onClick={() => void act(claim.id, "reject", claim.reference, claim.bank_verified, claim.billing_period)}
                    type="button"
                  >
                    Reject
                  </button>
                </span>
              )}
              <button
                className="shrink-0 rounded-md border border-line px-2 py-1 text-xs text-muted disabled:opacity-50"
                disabled={busyId === claim.id}
                onClick={() => void annotate(claim.id, claim.reference)}
                type="button"
              >
                Note
              </button>
              <button
                className="shrink-0 rounded-md border border-line px-2 py-1 text-xs text-muted disabled:opacity-50"
                onClick={() => void toggleHistory(claim.id)}
                type="button"
                aria-expanded={openHistoryId === claim.id}
              >
                {openHistoryId === claim.id ? "Hide history" : "History"}
              </button>
            </div>
            {/* The append-only ledger's actual payoff (created,
                bank-verified, approved/rejected, annotated) -- previously
                fetchable from the backend but never rendered anywhere,
                even though the founder could add a note to a history they
                could never see. Lazy-fetched per claim on first expand. */}
            {openHistoryId === claim.id && (
              <ul className="mt-2 space-y-1 border-t border-line pt-2 text-xs">
                {historyLoading && !historyById[claim.id] ? (
                  <li className="text-muted">Loading history…</li>
                ) : (historyById[claim.id]?.length ?? 0) === 0 ? (
                  <li className="text-muted">No history recorded.</li>
                ) : (
                  historyById[claim.id]!.map((event, i) => (
                    <li key={i} className="flex flex-wrap justify-between gap-2 rounded bg-white px-2 py-1">
                      <span>
                        <span className="font-medium">{event.event_type}</span> -- {event.actor}
                        {event.detail && <span className="text-muted"> -- {event.detail}</span>}
                      </span>
                      <span className="text-muted">{new Date(event.created_at).toLocaleString()}</span>
                    </li>
                  ))
                )}
              </ul>
            )}
            </li>
          ))
        )}
      </ul>
      )}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </>
  );
}

