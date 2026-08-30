"use client";
import { useEffect, useState } from "react";
import {
  api,
  billing,
  founderBilling,
  integrations,
  type BillingStatus,
  type Claim,
  type DashboardSummary,
  type Evidence,
  type EvidenceQualitySummary,
  type ExtractedEvidence,
  type FounderSummary,
  type Incident,
  type Integrations,
  type PaymentClaim,
  type Postmortem,
  type PreviousDraft,
  type SimilarIncident,
  type UpiPricing,
  webhooks,
  type WirePricing,
} from "./api";
import { auth, type AuthUser } from "./auth";
import { cn } from "@/lib/utils";
import { GroundingExample, Hero, HowItWorks, SiteFooter, WhatThisIsnt } from "./landing";
import { usePolling } from "./use-polling";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { LogoMark } from "./logo-mark";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  emailOnlySchema,
  evidenceSchema,
  firstError,
  incidentSchema,
  integrationsSchema,
  loginSchema,
  paymentReferenceSchema,
  registerSchema,
} from "./validation";

// Used as an override on shadcn's <Card>, not a standalone className --
// Card's own defaults (flex flex-col + gap-(--card-spacing), ring-1
// ring-foreground/10, text-card-foreground, py-(--card-spacing)) are all
// shadcn's own theme tokens/layout, tuned for shadcn's default palette,
// not this app's own ink/paper/line/muted design system. Every one of
// those is explicitly neutralized here so wrapping the existing plain
// block sections in a real <Card> doesn't change their layout or colors
// at all -- block+gap-0 cancels the flex/gap, ring-0 removes the added
// ring border, text-ink matches this app's own body text color.
const card =
  "block gap-0 animate-in fade-in slide-in-from-bottom-1 rounded-lg border border-line bg-white p-4 py-4 text-ink shadow-sm ring-0 duration-500 mb-4";
const fieldLabel = "block text-xs font-medium text-muted mb-1";
const fieldInput =
  "w-full rounded-md border border-line px-3 py-2 mb-3 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";
// Kept as plain <button>+className rather than swapping to shadcn's
// <Button> (Base UI) primitive across these 13 call sites -- several
// submit inside React 19's <form action={fn}> pattern, and that
// interaction isn't one this session could verify by rendering in a real
// browser. Polished with the same hover-lift already proven on the
// landing page's CTA instead: real, safe animation without changing the
// underlying element.
const primaryButton =
  "rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper transition-[transform,background-color,box-shadow] duration-200 hover:-translate-y-0.5 hover:bg-ink/90 hover:shadow-md disabled:pointer-events-none disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none";
const secondaryButton =
  "rounded-md border border-line px-4 py-2 text-sm font-medium text-ink transition-[transform,background-color] duration-200 hover:-translate-y-0.5 hover:bg-paper disabled:pointer-events-none disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50";

const CURRENCY_SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", GBP: "£", EUR: "€" };
function currencySymbol(currency: string): string {
  return CURRENCY_SYMBOLS[currency] ?? `${currency} `;
}

// Auth gate: defaults to the logged-out landing/sign-in view, since that's
// what Next.js actually renders server-side for a "use client" component's
// initial state -- a curl request, a crawler, or a social-link preview
// never runs the useEffect below, so if the default were a bare loading
// state (or null) they'd see an empty page instead of the branded landing
// content. Real signed-in users still only see it for one render before
// the GET /v1/auth/me check below swaps them to the real workspace --
// nothing incident-related renders or fetches until that positively
// confirms a signed-in user.
export default function Workspace() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [showAccount, setShowAccount] = useState(false);

  useEffect(() => {
    auth
      .me()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  if (!user) return <AuthGate onSignedIn={setUser} />;

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-2.5 text-2xl font-semibold tracking-tight">
          <LogoMark size={26} />
          PostMortem AI
        </h1>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          {user.is_founder && (
            <span className="shrink-0 rounded-full bg-ink px-2.5 py-0.5 text-xs font-medium text-paper">Founder</span>
          )}
          <button
            className="min-w-0 truncate text-sm text-muted underline underline-offset-2"
            type="button"
            onClick={() => setShowAccount((v) => !v)}
          >
            {user.email}
          </button>
          <button className={cn(secondaryButton, "shrink-0")} type="button" onClick={() => void auth.logout().then(() => setUser(null))}>
            Log out
          </button>
        </div>
      </div>
      {showAccount && (
        <AccountSettings
          user={user}
          onUpdated={(updated) => {
            setUser(updated);
            setShowAccount(false);
          }}
          onDeleted={() => setUser(null)}
        />
      )}
      {user.is_founder && <FounderDashboard />}
      {/* Unlike before, an unsubscribed account still sees the real
          workspace underneath -- the free-tier account's one incident
          (once created) needs to stay reachable for adding evidence and
          drafting, not just its creation. SubscribeGate is now an upsell
          shown alongside it, not an exclusive alternative to it; the
          actual free-tier boundary (one incident, no publishing) is
          enforced server-side regardless of what renders here. */}
      {!user.has_active_subscription && <SubscribeGate hasFreeIncidentAvailable={user.has_free_incident_available} />}
      <IncidentWorkspace isFounder={user.is_founder} />
      <SiteFooter />
    </main>
  );
}

const POLL_INTERVAL_MS = 20_000;

// The polling above was already keeping data live every 20s, but with no
// visible sign of it -- a user watching the screen had no way to tell
// whether it was current or stale. Recomputed at render time (no separate
// ticking timer needed): the poll cycle and any user action already
// re-render this component often enough to keep the text reasonably fresh.
function timeAgo(timestampMs: number): string {
  const seconds = Math.max(0, Math.round((Date.now() - timestampMs) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  return `${minutes}m ago`;
}

function FounderDashboard() {
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
      <div
        className={cn(
          "mb-4 flex items-center justify-between rounded-md px-3 py-2 text-sm",
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
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-md bg-paper px-3 py-2">
            <div className="text-lg font-semibold text-ink">{value}</div>
            <div className="text-xs text-muted">{label}</div>
          </div>
        ))}
      </div>
      <ConversionFunnelPanel funnel={summary.conversion_funnel} />
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
      <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">Recent signups</h3>
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
      <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">Recent AI runs</h3>
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
      <PaymentClaimsReview />
    </Card>
  );
}

// Answers "where do accounts actually drop off," which raw activity counts
// (incidents, drafts) don't -- a signup who never touches the free incident,
// one who tries it and never pays, and one who paid once and lapsed are
// three different problems needing three different fixes, not one blended
// "conversion rate."
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
          Of {funnel.ever_paid} who ever paid: {funnel.ever_paid_via_stripe} via Stripe checkout,{" "}
          {funnel.approved_manual_claims} via a founder-approved manual UPI/wire claim.
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
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add note.");
    } finally {
      setBusyId(null);
    }
  }

  async function act(claimId: string, action: "approve" | "reject", reference: string, bankVerified: boolean) {
    // Approving is what actually grants access -- a single accidental
    // click here previously had no safety net at all (this is exactly how
    // a claim with no real payment behind it got approved once already).
    // Approval always requires this explicit click, bank-verified or not
    // -- automation (bank_alerts.py) only ever marks a claim verified, it
    // never approves anything itself, per explicit instruction.
    if (action === "approve") {
      const confirmed = bankVerified
        ? window.confirm(
            `Approve reference "${reference}"?\n\nA real forwarded bank alert already matched this exact reference and amount. This grants the client real paid access.`,
          )
        : window.confirm(
            `Approve reference "${reference}"?\n\nNo bank alert has matched this yet -- only click OK if you have personally checked your bank/UPI statement and confirmed this exact amount and reference actually arrived. This grants the client real paid access.`,
          );
      if (!confirmed) return;
    }
    setBusyId(claimId);
    setError("");
    try {
      if (action === "approve") await founderBilling.approveClaim(claimId);
      else await founderBilling.rejectClaim(claimId);
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
            <li key={claim.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-paper px-3 py-2">
              <span className="min-w-0 flex-1">
                <span className="font-medium">{claim.email}</span> --{" "}
                {currencySymbol(claim.currency)}
                {claim.amount} via {claim.method === "wire" ? "SWIFT wire" : "UPI"}, ref{" "}
                <span className="font-mono text-xs">{claim.reference}</span>
                <span className="text-muted"> ({claim.status})</span>
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
                    onClick={() => void act(claim.id, "approve", claim.reference, claim.bank_verified)}
                    type="button"
                  >
                    Approve
                  </button>
                  <button
                    className="rounded-md border border-line px-2 py-1 text-xs text-muted disabled:opacity-50"
                    disabled={busyId === claim.id}
                    onClick={() => void act(claim.id, "reject", claim.reference, claim.bank_verified)}
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
            </li>
          ))
        )}
      </ul>
      )}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </>
  );
}

function AuthGate({ onSignedIn }: { onSignedIn: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<"login" | "register" | "forgot">("login");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(form: FormData) {
    setError("");
    setMessage("");
    const email = String(form.get("email"));

    if (mode === "forgot") {
      const validationError = firstError(emailOnlySchema, { email });
      if (validationError) return setError(validationError);
      setBusy(true);
      try {
        await auth.requestPasswordReset(email);
        // Always the same message whether or not the email is registered
        // -- the backend never reveals that distinction either.
        setMessage("If an account exists for that email, a reset link is on its way.");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not send the reset email.");
      } finally {
        setBusy(false);
      }
      return;
    }

    const password = String(form.get("password"));
    const schema = mode === "login" ? loginSchema : registerSchema;
    const validationError = firstError(schema, { email, password });
    if (validationError) return setError(validationError);

    setBusy(true);
    try {
      const user = mode === "login" ? await auth.login(email, password) : await auth.register(email, password);
      onSignedIn(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  }

  const heading =
    mode === "login" ? "Welcome back" : mode === "register" ? "Get started free" : "Reset your password";
  const subheading =
    mode === "login"
      ? "Log in to your account."
      : mode === "register"
        ? "Create your account — your first postmortem is free."
        : "Enter your email and we'll send you a link to choose a new password.";

  return (
    <main>
      <Hero />
      <GroundingExample />
      <HowItWorks />
      <div id="get-started" className="mx-auto mb-16 max-w-sm px-4">
        <Card className="animate-in fade-in slide-in-from-bottom-1 rounded-xl border border-line bg-white p-6 text-ink shadow-lg shadow-ink/5 duration-500">
          <h2 className="mb-1 text-lg font-semibold text-ink">{heading}</h2>
          <p className="mb-4 text-sm text-muted">{subheading}</p>
          <form action={submit}>
            <Label className={fieldLabel} htmlFor="auth-email">
              Email
            </Label>
            <Input
              id="auth-email"
              className="mb-3 rounded-md border-line text-ink focus-visible:ring-accent/30"
              name="email"
              type="email"
              required
            />
            {mode !== "forgot" && (
              <>
                <Label className={fieldLabel} htmlFor="auth-password">
                  Password
                </Label>
                <Input
                  id="auth-password"
                  className="mb-3 rounded-md border-line text-ink focus-visible:ring-accent/30"
                  name="password"
                  type="password"
                  minLength={8}
                  required
                />
              </>
            )}
            <button className={`${primaryButton} w-full`} disabled={busy} type="submit">
              {mode === "login" ? "Log in" : mode === "register" ? "Create account" : "Send reset link"}
            </button>
          </form>
          {message && (
            <Alert role="status" className="mt-3 animate-in fade-in border-accent/30 bg-accent/10 text-accent">
              <AlertDescription className="text-accent">{message}</AlertDescription>
            </Alert>
          )}
          {error && (
            <Alert role="status" variant="destructive" className="mt-3 animate-in fade-in border-red-200 bg-red-50">
              <AlertDescription className="text-red-700">{error}</AlertDescription>
            </Alert>
          )}
          {mode === "login" && (
            <p className="mt-2 text-sm text-muted">
              <button
                className="font-medium text-ink underline underline-offset-2"
                type="button"
                onClick={() => {
                  setMode("forgot");
                  setError("");
                  setMessage("");
                }}
              >
                Forgot password?
              </button>
            </p>
          )}
          <p className="mt-3 text-sm text-muted">
            {mode === "login" && (
              <>
                No account yet?{" "}
                <button
                  className="font-medium text-ink underline underline-offset-2"
                  type="button"
                  onClick={() => {
                    setMode("register");
                    setError("");
                    setMessage("");
                  }}
                >
                  Create one
                </button>
              </>
            )}
            {mode === "register" && (
              <>
                Already have an account?{" "}
                <button
                  className="font-medium text-ink underline underline-offset-2"
                  type="button"
                  onClick={() => {
                    setMode("login");
                    setError("");
                    setMessage("");
                  }}
                >
                  Log in
                </button>
              </>
            )}
            {mode === "forgot" && (
              <button
                className="font-medium text-ink underline underline-offset-2"
                type="button"
                onClick={() => {
                  setMode("login");
                  setError("");
                  setMessage("");
                }}
              >
                Back to log in
              </button>
            )}
          </p>
        </Card>
      </div>
      <WhatThisIsnt />
      <SiteFooter />
    </main>
  );
}

function SubscribeGate({ hasFreeIncidentAvailable }: { hasFreeIncidentAvailable: boolean }) {
  const [tab, setTab] = useState<"card" | "upi" | "wire">("upi");
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [cardConfigured, setCardConfigured] = useState(false);

  // Distinguishes a brand new unpaid account from one whose real, once-
  // active subscription lapsed -- otherwise a client who paid before sees
  // the exact same "Subscribe to use..." copy as someone who never has,
  // with no indication anything expired rather than never having started.
  useEffect(() => {
    billing.status().then(setStatus).catch(() => setStatus(null));
  }, []);

  // Real Stripe checkout has existed on the backend for a while, but no
  // client-facing tab ever called it -- everyone only ever saw the manual
  // UPI/wire flow. Card checkout is instant (no waiting on the founder to
  // review a claim) so it's offered first, but only once /card/pricing
  // confirms Stripe is actually configured in this environment; falls
  // back to defaulting on UPI when it isn't (unchanged prior behavior).
  useEffect(() => {
    billing
      .cardPricing()
      .then((p) => {
        setCardConfigured(p.configured);
        if (p.configured) setTab("card");
      })
      .catch(() => setCardConfigured(false));
  }, []);

  const expired = status?.subscription_status === "expired";

  return (
    <Card className={card}>
      <h2 className="mb-2 text-base font-semibold">
        {expired
          ? "Your subscription has expired"
          : hasFreeIncidentAvailable
            ? "Your first postmortem is free"
            : "Subscribe to publish and create another postmortem"}
      </h2>
      <p className="mb-3 text-sm text-muted">
        {expired && status?.current_period_end
          ? `Your access expired on ${new Date(status.current_period_end * 1000).toLocaleDateString()}. Make a new payment below to reactivate -- creating incidents, recording evidence, drafting, and publishing all require an active subscription; viewing your existing history stays available either way.`
          : hasFreeIncidentAvailable
            ? "Create one incident, record evidence, and draft a grounded postmortem with no payment -- see the real output before you decide. Publishing it (making it a permanent, citable record) and creating a second incident both require a subscription."
            : "You've used your free postmortem. Subscribe below to publish it, or to create another incident -- your existing history stays available either way."}
      </p>
      <Tabs value={tab} onValueChange={(value) => setTab(value as "card" | "upi" | "wire")} className="gap-3">
        <TabsList className="h-auto justify-start gap-1.5 rounded-none bg-transparent p-0">
          {cardConfigured && (
            <TabsTrigger
              value="card"
              className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-muted shadow-none data-active:border-ink data-active:bg-ink data-active:text-paper data-active:shadow-none"
            >
              Card (instant)
            </TabsTrigger>
          )}
          <TabsTrigger
            value="upi"
            className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-muted shadow-none data-active:border-ink data-active:bg-ink data-active:text-paper data-active:shadow-none"
          >
            UPI (India)
          </TabsTrigger>
          <TabsTrigger
            value="wire"
            className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-muted shadow-none data-active:border-ink data-active:bg-ink data-active:text-paper data-active:shadow-none"
          >
            International wire (SWIFT)
          </TabsTrigger>
        </TabsList>
        <TabsContent value="card" className="animate-in fade-in duration-300">
          <CardPayment />
        </TabsContent>
        <TabsContent value="upi" className="animate-in fade-in duration-300">
          <UpiPayment />
        </TabsContent>
        <TabsContent value="wire" className="animate-in fade-in duration-300">
          <WirePayment />
        </TabsContent>
      </Tabs>
    </Card>
  );
}

function CardPayment() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function subscribe() {
    setBusy(true);
    setError("");
    try {
      const { url } = await billing.checkout();
      window.location.href = url; // real Stripe Checkout -- leaves the app
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start checkout.");
      setBusy(false);
    }
  }

  return (
    <div className="rounded-md bg-paper px-3 py-2 text-sm">
      <p className="mb-2 text-muted">
        Pay by card via Stripe -- access activates immediately after payment, no waiting on manual review. You can
        cancel or update your card anytime from account settings.
      </p>
      <button className={primaryButton} disabled={busy} type="button" onClick={() => void subscribe()}>
        {busy ? "Redirecting…" : "Subscribe with card"}
      </button>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}

export function PendingClaim({ claim, onChanged }: { claim: Claim; onChanged: () => void | Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function saveReference(form: FormData) {
    const reference = String(form.get("reference") || "").trim();
    const validationError = firstError(paymentReferenceSchema, { reference });
    if (validationError) return setError(validationError);
    setBusy(true);
    setError("");
    try {
      await billing.updateClaim(claim.id, reference);
      setEditing(false);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update reference.");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!window.confirm(`Withdraw reference "${claim.reference}"? You can submit a new one afterward.`)) return;
    setBusy(true);
    setError("");
    try {
      await billing.cancelClaim(claim.id);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel claim.");
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <form action={saveReference} className="rounded-md bg-paper px-3 py-2">
        <label className={fieldLabel} htmlFor={`claim-reference-${claim.id}`}>
          Transaction reference
        </label>
        <input
          id={`claim-reference-${claim.id}`}
          className={fieldInput}
          name="reference"
          defaultValue={claim.reference}
          required
        />
        <div className="flex gap-2">
          <button className={primaryButton} disabled={busy} type="submit">
            Save
          </button>
          <button className={secondaryButton} disabled={busy} type="button" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </form>
    );
  }

  return (
    <div className="rounded-md bg-paper px-3 py-2 text-sm text-muted">
      <p>
        Reference <span className="font-medium text-ink">{claim.reference}</span> submitted, awaiting review.
      </p>
      <div className="mt-1.5 flex gap-3">
        <button className="text-xs underline underline-offset-2" disabled={busy} type="button" onClick={() => setEditing(true)}>
          Edit
        </button>
        <button className="text-xs text-red-600 underline underline-offset-2" disabled={busy} type="button" onClick={() => void cancel()}>
          Withdraw
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}

function UpiPayment() {
  const [upi, setUpi] = useState<UpiPricing | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  // Real UPI ID is founder-only now (see api/v1/billing.py) -- a client
  // never fetches it directly; this only shows the price, which is public
  // information, and a claim-submission form for after they've been given
  // the actual account to pay via a direct, founder-arranged channel.
  async function refresh() {
    setUpi(await billing.upiPricing());
    setClaims(await billing.myUpiClaims());
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function submitReference(form: FormData) {
    const reference = String(form.get("reference") || "").trim();
    const validationError = firstError(paymentReferenceSchema, { reference });
    if (validationError) return setError(validationError);
    setBusy(true);
    setError("");
    try {
      await billing.submitUpiClaim(reference);
      await refresh();
      setMessage("Submitted. The founder will review and activate your account shortly.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit payment reference.");
    } finally {
      setBusy(false);
    }
  }

  const latestPending = claims.find((c) => c.status === "pending");

  if (!upi?.configured) return <p className="text-sm text-muted">UPI payment is not yet configured.</p>;

  return (
    <>
      <p className="mb-3 text-sm text-muted">
        ₹{upi.amount_inr}/month via UPI.{" "}
        <a className="underline underline-offset-2" href="mailto:vish.matale@gmail.com?subject=UPI%20payment%20details">
          Email the founder
        </a>{" "}
        to receive the account to pay to, then submit your transaction reference below.
      </p>
      <p className="mb-3 text-xs text-muted">
        UPI requires an Indian bank account -- it can&apos;t accept payment from outside India. Use the
        international wire tab instead if you&apos;re paying from outside India.
      </p>
      {latestPending ? (
        <PendingClaim claim={latestPending} onChanged={refresh} />
      ) : (
        <form action={submitReference}>
          <label className={fieldLabel} htmlFor="upi-reference">
            UPI transaction reference / UTR number
          </label>
          <input id="upi-reference" className={fieldInput} name="reference" placeholder="e.g. 123456789012" required />
          <button className={primaryButton} disabled={busy} type="submit">
            {busy ? "Submitting..." : "I've paid -- submit reference"}
          </button>
        </form>
      )}
      {message && <p className="mt-3 text-sm text-accent">{message}</p>}
      {claims.some((c) => c.status === "rejected") && !latestPending && (
        <p className="mt-3 text-sm text-red-600">
          A previous reference was rejected -- double-check the amount and UPI ID, then resubmit.
        </p>
      )}
      {error && (
        <p role="status" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      )}
    </>
  );
}

function WirePayment() {
  const [wire, setWire] = useState<WirePricing | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [currency, setCurrency] = useState("USD");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  // Real account/SWIFT/correspondent-bank details are founder-only now
  // (see api/v1/billing.py) -- a client never fetches them directly; this
  // only shows prices, which are public information, and a claim-
  // submission form for after they've been given the actual account to
  // pay via a direct, founder-arranged channel.
  async function refresh() {
    setWire(await billing.wirePricing());
    setClaims(await billing.myWireClaims());
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function submitReference(form: FormData) {
    const reference = String(form.get("reference") || "").trim();
    const validationError = firstError(paymentReferenceSchema, { reference });
    if (validationError) return setError(validationError);
    setBusy(true);
    setError("");
    try {
      await billing.submitWireClaim(currency, reference);
      await refresh();
      setMessage("Submitted. The founder will review and activate your account shortly.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit payment reference.");
    } finally {
      setBusy(false);
    }
  }

  const latestPending = claims.find((c) => c.status === "pending");

  if (!wire?.configured) return <p className="text-sm text-muted">Wire payment is not yet configured.</p>;

  const active = wire.currencies.find((c) => c.currency === currency) ?? wire.currencies[0];

  return (
    <>
      <div className="mb-3 flex gap-1.5">
        {wire.currencies.map((c) => (
          <button
            key={c.currency}
            className={`rounded-md px-2.5 py-1 text-xs font-medium ${currency === c.currency ? "bg-accent/10 text-accent" : "border border-line text-muted"}`}
            onClick={() => setCurrency(c.currency)}
            type="button"
          >
            {c.currency}
          </button>
        ))}
      </div>
      <p className="mb-3 text-sm text-muted">
        {currencySymbol(active.currency)}
        {active.amount}/month via SWIFT wire in {active.currency}.{" "}
        <a className="underline underline-offset-2" href="mailto:vish.matale@gmail.com?subject=Wire%20payment%20details">
          Email the founder
        </a>{" "}
        to receive the account to wire to, then submit your transaction reference below.
      </p>
      {latestPending ? (
        <PendingClaim claim={latestPending} onChanged={refresh} />
      ) : (
        <form action={submitReference}>
          <label className={fieldLabel} htmlFor="wire-reference">
            Wire transaction reference
          </label>
          <input
            id="wire-reference"
            className={fieldInput}
            name="reference"
            placeholder="e.g. SWIFT MT103 reference"
            required
          />
          <button className={primaryButton} disabled={busy} type="submit">
            {busy ? "Submitting..." : "I've paid -- submit reference"}
          </button>
        </form>
      )}
      {message && <p className="mt-3 text-sm text-accent">{message}</p>}
      {claims.some((c) => c.status === "rejected") && !latestPending && (
        <p className="mt-3 text-sm text-red-600">
          A previous reference was rejected -- double-check the amount and account details, then resubmit.
        </p>
      )}
      {error && (
        <p role="status" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      )}
    </>
  );
}

function ManageBilling() {
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Whether a Stripe-backed billing account exists is only knowable by
  // trying the portal and reading the result -- BillingStatus doesn't
  // carry a payment-method field. Starts "unknown" so the button always
  // renders (a client who paid by card should always see it); a 404 from
  // the backend (no stripe_customer_id -- i.e. paid via UPI/wire instead)
  // flips this off so the button doesn't stay there promising something
  // that will only ever fail for that account.
  const [hasStripeAccount, setHasStripeAccount] = useState(true);

  useEffect(() => {
    billing.status().then(setStatus).catch(() => setStatus(null));
  }, []);

  async function openPortal() {
    setBusy(true);
    setError("");
    try {
      const { url } = await billing.portal();
      window.location.href = url; // real Stripe Customer Portal -- cancel, update card, view invoices
    } catch (err) {
      // /v1/billing/portal 404s specifically when there's no
      // stripe_customer_id on this account -- i.e. this client paid via
      // the manual UPI/wire flow, not Stripe, so there's genuinely no
      // portal to open (not a transient failure worth retrying).
      setHasStripeAccount(false);
      setError(err instanceof Error ? err.message : "Could not open billing portal.");
      setBusy(false);
    }
  }

  if (!status) return null;

  return (
    <Card className={card}>
      <div className="text-sm">
        <span className="font-medium">Subscription:</span> {status.subscription_status}
        {status.current_period_end && (
          <span className="text-muted">
            {" "}
            -- {status.subscription_status === "expired" ? "expired" : "renews"}{" "}
            {new Date(status.current_period_end * 1000).toLocaleDateString()}
          </span>
        )}
      </div>
      {hasStripeAccount ? (
        <>
          <button className={cn(secondaryButton, "mt-2")} disabled={busy} type="button" onClick={() => void openPortal()}>
            {busy ? "Opening…" : "Manage billing"}
          </button>
          {error && (
            <p className="mt-2 text-xs text-muted">
              Paid via UPI/wire instead?{" "}
              <a className="underline underline-offset-2" href="mailto:vish.matale@gmail.com?subject=Renewal%20question">
                Email the founder
              </a>{" "}
              directly to renew or ask a question.
            </p>
          )}
        </>
      ) : (
        <p className="mt-1 text-xs text-muted">
          {status.subscription_status === "expired" ? "Your access has expired -- " : "Paid via UPI/wire -- "}
          <a className="underline underline-offset-2" href="mailto:vish.matale@gmail.com?subject=Payment%20question">
            email the founder
          </a>
          {status.subscription_status === "expired" ? " to make a new payment and reactivate." : " to renew or ask a question."}
        </p>
      )}
    </Card>
  );
}

export function AccountSettings({ user, onUpdated, onDeleted }: { user: AuthUser; onUpdated: (u: AuthUser) => void; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function save(form: FormData) {
    const email = String(form.get("email") || "").trim();
    const password = String(form.get("password") || "").trim();
    const fields: { email?: string; password?: string } = {};
    if (email && email !== user.email) fields.email = email;
    if (password) fields.password = password;
    if (Object.keys(fields).length === 0) return setError("Change the email or enter a new password first.");

    setBusy(true);
    setError("");
    setMessage("");
    try {
      // PATCH -- only the fields actually changed are sent.
      const updated = await auth.updateAccount(fields);
      onUpdated(updated);
      setMessage("Saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update account.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteAccount() {
    if (user.is_founder) return; // button is hidden for the founder anyway; guards a stray call too
    if (
      !window.confirm(
        "Delete your account? This cannot be undone. Your incident/postmortem history stays as a record, but you will no longer be able to sign in.",
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      await auth.deleteAccount();
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete account.");
      setBusy(false);
    }
  }

  return (
    <Card className={card}>
      <h2 className="mb-1 text-base font-semibold">Account</h2>
      <p className="mb-3 text-xs text-muted">Update your login email or password.</p>
      <form action={save} className="space-y-1">
        <label className={fieldLabel} htmlFor="account-email">
          Email
        </label>
        <input
          id="account-email"
          className={fieldInput}
          name="email"
          type="email"
          defaultValue={user.email}
          disabled={user.is_founder}
        />
        <label className={fieldLabel} htmlFor="account-password">
          New password (leave blank to keep current)
        </label>
        <input
          id="account-password"
          className={fieldInput}
          name="password"
          type="password"
          placeholder="••••••••"
          minLength={8}
        />
        <button className={secondaryButton} disabled={busy} type="submit">
          Save changes
        </button>
      </form>
      {message && <p className="mt-2 text-sm text-accent">{message}</p>}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      {!user.is_founder && (
        <div className="mt-4 border-t border-line pt-3">
          <button className="text-xs text-red-600 underline underline-offset-2" disabled={busy} type="button" onClick={() => void deleteAccount()}>
            Delete my account
          </button>
        </div>
      )}
    </Card>
  );
}

function IntegrationsSettings() {
  const [state, setState] = useState<Integrations | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  function refresh() {
    integrations.get().then(setState).catch(() => setState(null));
  }

  useEffect(refresh, []);

  async function save(form: FormData) {
    const payload: Record<string, string> = {};
    for (const key of ["slack_webhook_url", "linear_api_key", "linear_team_id"] as const) {
      const value = String(form.get(key) ?? "").trim();
      if (value) payload[key] = value;
    }
    const validationError = firstError(integrationsSchema, payload);
    if (validationError) return setError(validationError);

    setBusy(true);
    setError("");
    setMessage("");
    try {
      await integrations.update(payload);
      refresh();
      setMessage("Saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save integrations.");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect(field: "slack_webhook_url" | "linear_api_key") {
    setBusy(true);
    try {
      await integrations.update({ [field]: "" });
      refresh();
    } finally {
      setBusy(false);
    }
  }

  if (!state) return null;

  return (
    <Card className={card}>
      <h2 className="mb-1 text-base font-semibold">Integrations</h2>
      <p className="mb-3 text-xs text-muted">
        Publishing a postmortem notifies Slack and creates a Linear ticket per action item, when connected.
      </p>
      <form action={save} className="space-y-1">
        <div className="flex items-center justify-between">
          <label className={fieldLabel} htmlFor="slack-webhook-url">
            Slack incoming webhook URL
          </label>
          {state.slack_connected && (
            <span className="text-xs text-accent">
              Connected --{" "}
              <button
                className="underline underline-offset-2"
                disabled={busy}
                onClick={() => void disconnect("slack_webhook_url")}
                type="button"
              >
                disconnect
              </button>
            </span>
          )}
        </div>
        <input
          id="slack-webhook-url"
          className={fieldInput}
          name="slack_webhook_url"
          placeholder={state.slack_connected ? "•••• (connected)" : "https://hooks.slack.com/services/..."}
        />

        <div className="flex items-center justify-between">
          <label className={fieldLabel} htmlFor="linear-api-key">
            Linear personal API key
          </label>
          {state.linear_connected && (
            <span className="text-xs text-accent">
              Connected --{" "}
              <button
                className="underline underline-offset-2"
                disabled={busy}
                onClick={() => void disconnect("linear_api_key")}
                type="button"
              >
                disconnect
              </button>
            </span>
          )}
        </div>
        <input
          id="linear-api-key"
          className={fieldInput}
          name="linear_api_key"
          placeholder={state.linear_connected ? "•••• (connected)" : "lin_api_..."}
        />

        <label className={fieldLabel} htmlFor="linear-team-id">
          Linear team ID
        </label>
        <input
          id="linear-team-id"
          className={fieldInput}
          name="linear_team_id"
          defaultValue={state.linear_team_id ?? ""}
          placeholder="team-id"
        />

        <button className={secondaryButton} disabled={busy} type="submit">
          Save
        </button>
      </form>
      {message && <p className="mt-2 text-sm text-accent">{message}</p>}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </Card>
  );
}

// Real webhook ingestion, not just a description of one -- POSTing this
// URL from any external tool (a monitoring alert, a script, a CI job)
// creates an incident or appends evidence to one, the same write path
// EvidenceExtractor and the manual evidence form use, just authenticated
// by this per-account token instead of a session cookie. See
// apps/api/app/api/v1/webhooks.py for the full contract (incident_id
// grouping, paywall, rate limiting).
function WebhookSettings() {
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    webhooks.token().then((t) => setToken(t.token)).catch(() => setToken(null));
  }, []);

  const url = token ? `${process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000"}/v1/webhooks/incidents/${token}` : "";

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied (permissions, non-HTTPS context) --
      // the URL is still selectable/visible in the input below, so this
      // isn't the only way to get it.
    }
  }

  async function rotate() {
    setBusy(true);
    setError("");
    try {
      const t = await webhooks.rotate();
      setToken(t.token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not rotate the webhook URL.");
    } finally {
      setBusy(false);
    }
  }

  if (!token) return null;

  return (
    <Card className={card}>
      <h2 className="mb-1 text-base font-semibold">Webhook</h2>
      <p className="mb-3 text-xs text-muted">
        POST JSON to this URL from any monitoring tool or script to create an incident or add evidence
        automatically -- no manual typing required. Body: <code className="font-mono">{"{source, summary, detail?, incident_id?}"}</code>.
        Omit <code className="font-mono">incident_id</code> to start a new incident; include the one returned by a
        previous call to group related events together.
      </p>
      <div className="flex gap-2">
        <input className={`${fieldInput} mb-0 font-mono text-xs`} value={url} readOnly />
        <button className={secondaryButton} type="button" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <AlertDialog>
        <AlertDialogTrigger
          className="mt-3 text-xs text-red-600 underline underline-offset-2"
          disabled={busy}
          render={<button type="button" />}
        >
          Rotate URL
        </AlertDialogTrigger>
        <AlertDialogContent className="border-line bg-white text-ink">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-ink">Rotate your webhook URL?</AlertDialogTitle>
            <AlertDialogDescription className="text-muted">
              Any tool still configured with the old URL will stop working immediately. This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-line text-ink hover:bg-paper">Cancel</AlertDialogCancel>
            <AlertDialogAction className="bg-red-600 text-white hover:bg-red-700" onClick={() => void rotate()}>
              Rotate URL
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </Card>
  );
}

// AI-assisted, not autonomous: proposes evidence entries from pasted text
// (a Slack thread, a log excerpt) but never saves anything on its own --
// each suggestion is reviewed, optionally edited, and added individually
// through the same POST .../evidence call the manual form below uses.
// Discarding a suggestion just removes it from local state; nothing was
// ever written for it in the first place.
function EvidenceExtractor({
  incidentId,
  onAdded,
  setMessage,
}: {
  incidentId: string;
  onAdded: () => void;
  setMessage: (message: string) => void;
}) {
  const [text, setText] = useState("");
  const [suggestions, setSuggestions] = useState<ExtractedEvidence[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function extract() {
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      const extracted = await api.extractEvidence(incidentId, text);
      setSuggestions(extracted);
      if (extracted.length === 0) setError("No factual entries found in that text -- try pasting more detail.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not extract evidence.");
    } finally {
      setBusy(false);
    }
  }

  async function addSuggestion(index: number) {
    const item = suggestions[index];
    setBusy(true);
    try {
      await api.addEvidence(incidentId, {
        occurred_at: Date.now(),
        source: item.source,
        summary: item.summary,
        detail: item.detail ?? undefined,
      });
      setSuggestions((prev) => prev.filter((_, i) => i !== index));
      onAdded();
      setMessage("Evidence recorded.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add evidence.");
    } finally {
      setBusy(false);
    }
  }

  function discardSuggestion(index: number) {
    setSuggestions((prev) => prev.filter((_, i) => i !== index));
  }

  function updateSuggestion(index: number, summary: string) {
    setSuggestions((prev) => prev.map((s, i) => (i === index ? { ...s, summary } : s)));
  }

  return (
    <div className="mb-4 rounded-md border border-line bg-paper p-3">
      <label className={fieldLabel} htmlFor="evidence-extract-text">
        Paste a Slack thread, log excerpt, or notes to extract evidence from
      </label>
      <textarea
        id="evidence-extract-text"
        className={cn(fieldInput, "min-h-24 font-mono text-xs")}
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="[14:02] deploy bot: shipped release 1.2&#10;[14:04] pagerduty: p99 latency alert fired..."
      />
      <button className={secondaryButton} disabled={busy || !text.trim()} type="button" onClick={() => void extract()}>
        {busy ? "Extracting..." : "Extract evidence with AI"}
      </button>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      {suggestions.length > 0 && (
        <ul className="mt-3 space-y-2">
          {suggestions.map((item, index) => (
            <li key={index} className="rounded-md bg-white p-2 shadow-sm">
              <span className="text-xs font-medium text-accent">[{item.source}]</span>
              <input
                className={cn(fieldInput, "mt-1 mb-1")}
                value={item.summary}
                onChange={(event) => updateSuggestion(index, event.target.value)}
              />
              {item.detail && <p className="mb-1.5 text-xs text-muted">{item.detail}</p>}
              <div className="flex gap-2">
                <button
                  className="rounded-md bg-ink px-2 py-1 text-xs font-medium text-paper disabled:opacity-50"
                  disabled={busy}
                  type="button"
                  onClick={() => void addSuggestion(index)}
                >
                  Add
                </button>
                <button
                  className="rounded-md border border-line px-2 py-1 text-xs text-muted disabled:opacity-50"
                  disabled={busy}
                  type="button"
                  onClick={() => discardSuggestion(index)}
                >
                  Discard
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Automated sources (an alert, a log line, a deploy note, a metric) carry
// different weight than a human's own recollection typed in after the
// fact -- an incident grounded only in human_note/customer_report entries
// is a real, honest signal worth surfacing, not because either source type
// is invalid (both are real evidence, both can ground a draft), but
// because a reviewer calibrating how much to trust a draft benefits from
// knowing which kind of evidence it actually rests on.
const AUTOMATED_SOURCES = new Set(["alert", "log", "deploy", "metric"]);

// Same Badge-plus-app-token-override pattern already used in landing.tsx's
// Hero (variant="outline" as the structural base, this app's own
// ink/paper/line/muted/accent colors layered on via className, not
// shadcn's own default theme tokens).
function SeverityBadge({ severity }: { severity: string }) {
  const isCritical = severity === "sev1" || severity === "sev2";
  return (
    <Badge
      variant="outline"
      className={cn(
        "shrink-0 border-line font-mono text-[10px] uppercase",
        isCritical ? "border-red-200 bg-red-50 text-red-700" : "text-muted",
      )}
    >
      {severity}
    </Badge>
  );
}

// Shown in place of a stats grid while its first fetch is in flight, so a
// dashboard loads in as "clearly still loading" rather than a blank gap
// that's indistinguishable from a slow/broken request.
function DashboardSkeleton({ tiles = 4 }: { tiles?: number }) {
  return (
    <Card className={card}>
      <Skeleton className="mb-3 h-5 w-40 bg-paper" />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: tiles }).map((_, i) => (
          <Skeleton key={i} className="h-14 rounded-md bg-paper" />
        ))}
      </div>
    </Card>
  );
}

function IncidentListSkeleton() {
  return (
    <ul className="mb-3 space-y-1.5" aria-hidden="true">
      {Array.from({ length: 3 }).map((_, i) => (
        <li key={i}>
          <Skeleton className="h-10 w-full rounded-md bg-paper" />
        </li>
      ))}
    </ul>
  );
}

function StatusBadge({ status }: { status: string }) {
  const isResolved = status === "resolved";
  return (
    <Badge
      variant="outline"
      className={cn(
        "shrink-0 border-line text-[10px]",
        isResolved ? "bg-paper text-muted" : "border-accent/30 bg-accent/10 text-accent",
      )}
    >
      {status}
    </Badge>
  );
}

function EvidenceQualitySummary({ evidence }: { evidence: Evidence[] }) {
  const automated = evidence.filter((e) => AUTOMATED_SOURCES.has(e.source)).length;
  const human = evidence.length - automated;
  const parts: string[] = [];
  if (automated > 0) parts.push(`${automated} automated source${automated === 1 ? "" : "s"}`);
  if (human > 0) parts.push(`${human} human note${human === 1 ? "" : "s"}`);
  return (
    <p className="mb-3 text-xs text-muted">
      Grounded in {parts.join(" + ")}
      {automated === 0 && " -- no automated signal backs this incident yet."}
    </p>
  );
}

// Surfaces the same similar-past-incident retrieval that already runs
// silently inside drafting (as hidden RAG context for the model) directly
// to the human -- so a real pattern ("you've had 3 incidents like this")
// is something a reviewer can actually notice, not just something that
// invisibly shapes the model's output.
function SimilarIncidentsPanel({ incidentId }: { incidentId: string }) {
  const [similar, setSimilar] = useState<SimilarIncident[] | null>(null);

  useEffect(() => {
    setSimilar(null);
    api
      .similarIncidents(incidentId)
      .then(setSimilar)
      .catch(() => setSimilar([]));
  }, [incidentId]);

  if (!similar || similar.length === 0) return null;

  return (
    <div className="mb-3 rounded-md bg-paper px-3 py-2.5 text-xs">
      <p className="mb-1.5 font-medium text-ink">Similar past incidents ({similar.length})</p>
      <ul className="space-y-1.5">
        {similar.map((item) => (
          <li key={item.incident_title + item.summary} className="text-muted">
            <span className="font-medium text-ink">{item.incident_title}</span> -- {item.root_cause}
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-muted">Reference only -- shown for context, never used as a citation source.</p>
    </div>
  );
}

// A field-by-field comparison against the draft this one replaced, rather
// than a re-draft looking like an unexplained full rewrite. Deliberately
// simple (changed vs. unchanged per structured field, not a text diff
// library) -- this app's draft shape is already four discrete sections,
// so a real diffing library would be solving a problem that doesn't exist
// here.
function DraftComparison({ postmortem, previous }: { postmortem: Postmortem; previous: PreviousDraft }) {
  const fields: [string, string, string][] = [
    ["Summary", previous.summary, postmortem.summary],
    ["Root cause", previous.root_cause, postmortem.root_cause],
    ["Detection", previous.detection, postmortem.detection],
    ["Resolution", previous.resolution, postmortem.resolution],
  ];
  const changed = fields.filter(([, before, after]) => before !== after);

  if (changed.length === 0) {
    return <p className="mt-3 text-xs text-muted">Unchanged from the previous draft.</p>;
  }

  return (
    <div className="mt-3 rounded-md bg-paper px-3 py-2.5 text-xs">
      <p className="mb-1.5 font-medium text-ink">
        Changed since the previous draft ({new Date(previous.superseded_at).toLocaleString()}):
      </p>
      <ul className="space-y-2">
        {changed.map(([label, before]) => (
          <li key={label}>
            <span className="font-medium text-ink">{label}</span>
            <div className="mt-0.5 rounded bg-red-50 px-2 py-1 text-red-700 line-through">{before}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Turns the fixed "Not established by the recorded evidence." marker from
// a per-draft error message into an account-wide, self-fetching signal --
// not a quality judgment on any single incident, but something worth
// noticing as a pattern (e.g. resolution unsupported on most incidents
// might mean evidence habits worth adjusting).
function QualitySummaryPanel() {
  const [summary, setSummary] = useState<EvidenceQualitySummary | null>(null);

  useEffect(() => {
    api.qualitySummary().then(setSummary).catch(() => setSummary(null));
  }, []);

  if (!summary || summary.total_drafts === 0) return null;

  const sectionLabels: Record<string, string> = {
    summary: "Summary",
    root_cause: "Root cause",
    detection: "Detection",
    resolution: "Resolution",
  };
  const sectionsWithGaps = Object.entries(summary.unsupported_by_section).filter(([, count]) => count > 0);

  return (
    <div className="mt-3 rounded-md bg-paper px-3 py-2.5 text-xs text-muted">
      <p>
        <span className="font-medium text-ink">{summary.drafts_with_any_unsupported_section}</span> of{" "}
        <span className="font-medium text-ink">{summary.total_drafts}</span> drafts have at least one section marked
        unsupported.
      </p>
      {sectionsWithGaps.length > 0 && (
        <p className="mt-1">
          Most often:{" "}
          {sectionsWithGaps
            .sort((a, b) => b[1] - a[1])
            .map(([section, count]) => `${sectionLabels[section] ?? section} (${count})`)
            .join(", ")}
          . Not a mistake -- usually means that section&apos;s evidence wasn&apos;t recorded.
        </p>
      )}
    </div>
  );
}

function IncidentWorkspace({ isFounder }: { isFounder: boolean }) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [postmortem, setPostmortem] = useState<Postmortem | null>(null);
  const [previousDraft, setPreviousDraft] = useState<PreviousDraft | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  // The 20s poll (usePolling below) already keeps this data live, but that
  // was entirely invisible before -- nothing told a user their screen was
  // updating itself, or gave them a way to force it right now instead of
  // waiting out the interval. lastUpdated/refreshing surface both.
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  // Distinguishes "still loading the first time" from "loaded, genuinely
  // zero incidents" -- incidents/summary both start empty/null either way,
  // so without this the loading and empty states were visually identical.
  const [loaded, setLoaded] = useState(false);

  async function refreshIncidents() {
    // Independent GETs -- run in parallel rather than serially, halving
    // the real wall-clock wait on every dashboard load and status toggle.
    const [incidentsResult, summaryResult] = await Promise.all([api.listIncidents(), api.summary()]);
    setIncidents(incidentsResult);
    setSummary(summaryResult);
    setLastUpdated(Date.now());
    setLoaded(true);
  }

  async function manualRefresh() {
    setRefreshing(true);
    try {
      await refreshIncidents();
      if (selectedId) await refreshSelected(selectedId);
    } finally {
      setRefreshing(false);
    }
  }

  async function toggleResolved(incident: Incident) {
    const nextStatus = incident.status === "resolved" ? "open" : "resolved";
    setBusy(true);
    try {
      await api.updateIncidentStatus(incident.id, nextStatus);
      await refreshIncidents();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update status.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshSelected(id: string) {
    // Independent GETs -- start both immediately rather than waiting for
    // evidence before even requesting the postmortem. getPostmortem is
    // expected to 404 (no draft yet), so each is awaited with its own
    // error handling rather than Promise.all, which would reject the
    // whole thing (and lose the evidence result) on that expected 404.
    const evidencePromise = api.listEvidence(id);
    const postmortemPromise = api.getPostmortem(id).catch(() => null);
    const previousDraftPromise = api.previousDraft(id).catch(() => null);
    setEvidence(await evidencePromise);
    setPostmortem(await postmortemPromise);
    setPreviousDraft(await previousDraftPromise);
  }

  useEffect(() => {
    void refreshIncidents();
  }, []);
  usePolling(() => void refreshIncidents(), POLL_INTERVAL_MS);

  useEffect(() => {
    if (selectedId) void refreshSelected(selectedId);
  }, [selectedId]);
  usePolling(() => {
    if (selectedId) void refreshSelected(selectedId);
  }, POLL_INTERVAL_MS);

  async function createIncident(form: FormData) {
    const payload = {
      title: String(form.get("title")),
      severity: String(form.get("severity")),
      impact: String(form.get("impact") || "") || undefined,
    };
    const validationError = firstError(incidentSchema, payload);
    if (validationError) return setMessage(validationError);

    setBusy(true);
    try {
      const created = await api.createIncident(payload);
      await refreshIncidents();
      setSelectedId(created.id);
      setMessage("Incident created.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create incident.");
    } finally {
      setBusy(false);
    }
  }

  async function addEvidence(form: FormData) {
    if (!selectedId) return;
    const payload = {
      occurred_at: Date.now(),
      source: String(form.get("source")),
      summary: String(form.get("summary")),
      detail: String(form.get("detail") || "") || undefined,
    };
    const validationError = firstError(evidenceSchema, payload);
    if (validationError) return setMessage(validationError);

    setBusy(true);
    try {
      await api.addEvidence(selectedId, payload);
      await refreshSelected(selectedId);
      setMessage("Evidence recorded.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not record evidence.");
    } finally {
      setBusy(false);
    }
  }

  async function generateDraft() {
    if (!selectedId) return;
    setBusy(true);
    setMessage("Drafting...");
    try {
      const draft = await api.draft(selectedId);
      setPostmortem(draft);
      // The snapshot of whatever this draft just replaced is only written
      // server-side inside the draft call above -- fetch it fresh
      // afterward (sequentially, not in parallel with the draft call
      // itself, since it doesn't exist until that call has committed)
      // rather than reusing whatever was loaded before this ran.
      setPreviousDraft(await api.previousDraft(selectedId).catch(() => null));
      setMessage("Draft generated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not draft postmortem.");
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!selectedId) return;
    setBusy(true);
    try {
      const published = await api.publish(selectedId);
      setPostmortem(published);
      setMessage("Postmortem published.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not publish.");
    } finally {
      setBusy(false);
    }
  }

  async function togglePublic() {
    if (!selectedId || !postmortem) return;
    setBusy(true);
    try {
      const updated = await api.updatePublicVisibility(selectedId, !postmortem.is_public);
      setPostmortem(updated);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update visibility.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="mb-6 text-sm text-muted">Evidence-grounded incident postmortem drafting.</p>

      {!isFounder && <ManageBilling />}
      <IntegrationsSettings />
      <WebhookSettings />

      {!loaded && <DashboardSkeleton />}
      {summary && (
        <Card className={card}>
          <h2 className="mb-3 text-base font-semibold">Dashboard</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(
              [
                ["Open", summary.open_incidents],
                ["Resolved", summary.resolved_incidents],
                ["Drafted", summary.drafted_postmortems],
                ["Published", summary.published_postmortems],
              ] as [string, number][]
            ).map(([label, value]) => (
              <div key={label} className="rounded-md bg-paper px-3 py-2">
                <div className="text-lg font-semibold text-ink">{value}</div>
                <div className="text-xs text-muted">{label}</div>
              </div>
            ))}
          </div>
          <QualitySummaryPanel />
        </Card>
      )}

      <Card className={card}>
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Incidents</h2>
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
        {!loaded ? (
          <IncidentListSkeleton />
        ) : incidents.length === 0 ? (
          <p className="mb-3 text-sm text-muted">No incidents yet.</p>
        ) : (
          <ul className="mb-3 space-y-1.5">
            {incidents.map((incident, i) => (
              <li
                key={incident.id}
                style={{ animationDelay: `${Math.min(i, 10) * 40}ms` }}
                className="flex animate-in fade-in slide-in-from-bottom-1 items-center gap-1.5 fill-mode-backwards duration-300"
              >
                <button
                  className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition ${
                    selectedId === incident.id ? "bg-accent/10 font-medium text-accent" : "hover:bg-paper"
                  }`}
                  onClick={() => setSelectedId(incident.id)}
                  type="button"
                >
                  <span className="min-w-0 flex-1 truncate">{incident.title}</span>
                  <SeverityBadge severity={incident.severity} />
                  <StatusBadge status={incident.status} />
                </button>
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0 border-line text-xs text-muted hover:bg-paper hover:text-ink"
                  disabled={busy}
                  onClick={() => void toggleResolved(incident)}
                  type="button"
                >
                  {incident.status === "resolved" ? "Reopen" : "Mark resolved"}
                </Button>
              </li>
            ))}
          </ul>
        )}
        <form action={createIncident}>
          <label className={fieldLabel} htmlFor="incident-title">
            Title
          </label>
          <input id="incident-title" className={fieldInput} name="title" required />
          <label className={fieldLabel} htmlFor="incident-severity">
            Severity
          </label>
          <select id="incident-severity" className={fieldInput} name="severity" defaultValue="sev2">
            <option value="sev1">sev1</option>
            <option value="sev2">sev2</option>
            <option value="sev3">sev3</option>
            <option value="sev4">sev4</option>
          </select>
          <label className={fieldLabel} htmlFor="incident-impact">
            Impact
          </label>
          <input id="incident-impact" className={fieldInput} name="impact" />
          <button className={primaryButton} disabled={busy} type="submit">
            Create incident
          </button>
        </form>
      </Card>

      {selectedId && (
        <>
          <Card className={card}>
            <h2 className="mb-3 text-base font-semibold">Evidence</h2>
            {evidence.length > 0 && <EvidenceQualitySummary evidence={evidence} />}
            {evidence.length === 0 ? (
              <p className="mb-3 text-sm text-muted">No evidence recorded yet.</p>
            ) : (
              <div className="mb-3 rounded-md border border-line">
                <Table>
                  <TableHeader>
                    <TableRow className="border-line hover:bg-transparent">
                      <TableHead className="text-ink">Source</TableHead>
                      <TableHead className="text-ink">Summary</TableHead>
                      <TableHead className="text-ink">Detail</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {evidence.map((entry, i) => (
                      <TableRow
                        key={entry.id}
                        className="animate-in fade-in slide-in-from-left-1 border-line duration-300 hover:bg-paper"
                        style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}
                      >
                        <TableCell className="font-medium text-ink">{entry.source}</TableCell>
                        <TableCell className="whitespace-normal text-ink">{entry.summary}</TableCell>
                        <TableCell className="whitespace-normal text-muted">{entry.detail ?? "--"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            <EvidenceExtractor incidentId={selectedId} onAdded={() => void refreshSelected(selectedId)} setMessage={setMessage} />
            <form action={addEvidence}>
              <label className={fieldLabel} htmlFor="evidence-source">
                Source
              </label>
              <select id="evidence-source" className={fieldInput} name="source" defaultValue="alert">
                <option value="alert">alert</option>
                <option value="log">log</option>
                <option value="deploy">deploy</option>
                <option value="metric">metric</option>
                <option value="human_note">human_note</option>
                <option value="customer_report">customer_report</option>
              </select>
              <label className={fieldLabel} htmlFor="evidence-summary">
                Summary
              </label>
              <input id="evidence-summary" className={fieldInput} name="summary" required />
              <label className={fieldLabel} htmlFor="evidence-detail">
                Detail (optional)
              </label>
              <input id="evidence-detail" className={fieldInput} name="detail" />
              <button className={primaryButton} disabled={busy} type="submit">
                Add evidence
              </button>
            </form>
          </Card>

          <Card className={card}>
            <h2 className="mb-3 text-base font-semibold">Draft</h2>
            <SimilarIncidentsPanel incidentId={selectedId} />
            <button
              className={primaryButton}
              disabled={busy || evidence.length === 0}
              onClick={() => void generateDraft()}
              type="button"
            >
              Generate draft
            </button>
            {postmortem && previousDraft && <DraftComparison postmortem={postmortem} previous={previousDraft} />}
            {postmortem && (
              <div className="mt-4 space-y-2 text-sm">
                <p>
                  <span className="font-medium">Status:</span> {postmortem.status}
                </p>
                <p>
                  <span className="font-medium">Summary:</span> {postmortem.summary}
                </p>
                <p>
                  <span className="font-medium">Root cause:</span> {postmortem.root_cause}
                </p>
                <p>
                  <span className="font-medium">Detection:</span> {postmortem.detection}
                </p>
                <p>
                  <span className="font-medium">Resolution:</span> {postmortem.resolution}
                </p>
                {postmortem.contributing_factors.length > 0 && (
                  <div>
                    <span className="font-medium">Contributing factors:</span>
                    <ul className="mt-1 list-disc space-y-1 pl-5">
                      {postmortem.contributing_factors.map((factor) => (
                        <li key={factor}>{factor}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {postmortem.actions.length > 0 && (
                  <div>
                    <span className="font-medium">Actions:</span>
                    <ul className="mt-1 list-disc space-y-1 pl-5">
                      {postmortem.actions.map((action) => (
                        <li key={action.id}>
                          {action.title} -- {action.owner} ({action.rationale})
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <p className="text-xs text-muted">
                  Cited evidence: {postmortem.cited_evidence_ids.length} / unsupported claims dropped:{" "}
                  {postmortem.unsupported_claims_dropped}
                </p>
                {postmortem.status !== "published" && (
                  <button className={`${primaryButton} mt-1`} disabled={busy} onClick={() => void publish()} type="button">
                    Publish
                  </button>
                )}
                {postmortem.approved_by && (
                  <p className="text-xs text-muted">
                    Approved by {postmortem.approved_by} at {new Date(postmortem.approved_at ?? 0).toLocaleString()}
                  </p>
                )}
                {postmortem.status === "published" && (
                  <div className="mt-1">
                    <button className={secondaryButton} disabled={busy} onClick={() => void togglePublic()} type="button">
                      {postmortem.is_public ? "Make private" : "Make public"}
                    </button>
                    {postmortem.is_public && postmortem.slug && (
                      <p className="mt-1.5 text-xs text-muted">
                        Public at{" "}
                        <a className="underline underline-offset-2" href={`/postmortems/${postmortem.slug}`} target="_blank" rel="noreferrer">
                          /postmortems/{postmortem.slug}
                        </a>
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}
          </Card>
        </>
      )}

      {message && (
        <p role="status" className="text-sm text-muted">
          {message}
        </p>
      )}
    </>
  );
}
