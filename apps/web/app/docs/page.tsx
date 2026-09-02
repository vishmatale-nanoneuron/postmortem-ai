import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { SiteFooter, SiteHeader } from "../landing";

export const metadata: Metadata = {
  title: "Docs",
  description:
    "How PostMortem AI actually works: grounded drafting, RAG over past incidents, MCP tools, payments, and the security measures in place.",
  robots: { index: true, follow: true },
  alternates: { canonical: "/docs" },
};

const card = "rounded-lg border border-line bg-white p-5 shadow-sm mb-4";
const h2 = "mb-2 text-lg font-semibold text-ink";
const p = "text-sm text-muted leading-relaxed mb-2";
const code = "rounded bg-paper px-1.5 py-0.5 font-mono text-xs";

// Each doc section gets a fixed-angle 3D tilt on hover/focus (see
// .tilt-card in globals.css) and a staggered entrance -- section() below
// keeps that boilerplate (wrapper + delay + tilt classes) in one place
// instead of repeating it eight times by hand.
function section(index: number, children: React.ReactNode) {
  return (
    <div
      style={{ animationDelay: `${index * 70}ms` }}
      className="tilt-card-wrap mb-4 animate-in fade-in slide-in-from-bottom-2 fill-mode-backwards duration-700"
    >
      <section tabIndex={0} className={cn(card, "tilt-card mb-0")}>
        {children}
      </section>
    </div>
  );
}

export default function DocsPage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 duration-700">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Docs</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">How PostMortem AI works</h1>
        <p className="mt-2 text-sm text-muted">
          Written for humans and AI agents alike -- every claim here matches{" "}
          <a className="underline underline-offset-2" href="/llms.txt">
            /llms.txt
          </a>{" "}
          and the actual running code, not a roadmap.
        </p>
      </div>

      {section(
        0,
        <>
          <h2 className={h2}>The core loop</h2>
          <p className={p}>
            Record incident evidence (alerts, logs, deploys, metrics, human notes, customer reports), generate an
            AI-drafted postmortem, publish it once a named human approves. Every account is a single user&apos;s own
            incidents -- no shared organizations yet.
          </p>
        </>,
      )}

      {section(
        1,
        <>
          <h2 className={h2}>Grounded drafting -- the actual guarantee</h2>
          <p className={p}>
            The drafting model is given numbered evidence entries and told to cite the entry number behind every
            claim. Independently of what the model says about its own citations, code re-verifies every citation
            against the real evidence list before anything is stored. A claim with no valid citation is replaced
            with a fixed <span className={code}>&quot;Not established by the recorded evidence.&quot;</span> marker,
            or dropped. This verification step can only remove or replace the model&apos;s text -- it never adds
            anything.
          </p>
          <p className={p}>
            Publishing always records a named human approver; the database itself refuses to mark a postmortem
            published without one.
          </p>
          <p className={p}>
            Longer writeup with the exact verification steps:{" "}
            <Link className="underline underline-offset-2" href="/blog/grounding-mechanism">
              How postmortem drafting is grounded, mechanically
            </Link>
            . Real, unedited output on a public incident:{" "}
            <Link className="underline underline-offset-2" href="/blog/github-outage-demo">
              what our tool drafted from GitHub&apos;s August 2026 outage
            </Link>
            .
          </p>
        </>,
      )}

      {section(
        2,
        <>
          <h2 className={h2}>RAG -- similar past incidents</h2>
          <p className={p}>
            When drafting, the system retrieves your own previously published postmortems that are semantically
            similar to the current incident (via embeddings, cosine similarity) and shows them to the model as
            reference context. This context is clearly labeled and is never citable -- the grounding check above
            only ever validates citations against the current incident&apos;s own numbered evidence, so a retrieved
            past incident can never become the source for a claim.
          </p>
        </>,
      )}

      {section(
        3,
        <>
          <h2 className={h2}>MCP -- backend, database, and frontend</h2>
          <p className={p}>
            The backend exposes an MCP server (<span className={code}>/mcp</span>) with tools for both founders
            (platform summary, payment-claim review, a defense-in-depth read-only SQL tool) and clients (incidents,
            evidence, drafting, publishing, similar-incident search) -- the same business logic and the same
            authorization rules as the REST API, not a second implementation. The frontend federates to it at{" "}
            <span className={code}>/api/mcp</span>, under the caller&apos;s own session.
          </p>
        </>,
      )}

      {section(
        3.5,
        <>
          <h2 className={h2}>Automatic evidence via webhook</h2>
          <p className={p}>
            Every account has its own real, rotatable webhook URL -- posting JSON to it from any monitoring tool,
            alert, script, or CI job creates a new incident or appends evidence to an existing open one, the same
            write path and paywall as the authenticated app itself. The generic shape works with whatever your
            stack already sends, not just a pre-approved integration list.
          </p>
          <p className={p}>
            PagerDuty has a dedicated adapter (account settings has the exact URL) that parses PagerDuty&apos;s own
            v3 webhook payload directly -- point a PagerDuty webhook subscription at it and triggered/acknowledged/
            resolved events create, and later resolve, the matching incident automatically. Datadog&apos;s webhook
            payload is entirely user-templated on Datadog&apos;s side (it has no fixed schema to adapt to), so its
            integration is a documented JSON template for Datadog&apos;s own payload field, pointed at the generic
            webhook above -- also in account settings.
          </p>
        </>,
      )}

      {section(
        4,
        <>
          <h2 className={h2}>Reliability</h2>
          <p className={p}>
            A real circuit breaker (closed/open/half-open) wraps the drafting model -- after repeated failures,
            further calls fail fast instead of repeatedly hitting an unhealthy provider, and an alert can fire to a
            configured webhook. Every draft attempt is logged in a queryable table (provider, latency, success or
            failure), not just described.
          </p>
        </>,
      )}

      {section(
        5,
        <>
          <h2 className={h2}>Anti-abuse</h2>
          <p className={p}>
            Login attempts are rate-limited per account and per IP. Creating incidents and drafting postmortems (the
            AI-cost-incurring action) are separately rate-limited per account. Registration and login can require a
            CAPTCHA (Cloudflare Turnstile) when configured.
          </p>
        </>,
      )}

      {section(
        6,
        <>
          <h2 className={h2}>Payments</h2>
          <p className={p}>
            Every account gets one incident fully free -- record evidence, run AI extraction, and draft a real
            grounded postmortem with no card required, so you can see the actual output before deciding anything.
            Publishing it, or creating a second incident, requires an active subscription. For clients anywhere in
            the world, an international SWIFT wire (USD/GBP/EUR) or UPI (India) works today -- submit the
            transaction reference and the founder reviews and approves it personally, usually quickly. Self-serve
            card checkout via Stripe is built but not switched on for real payments yet; when it is, it&apos;ll
            appear as an option automatically, without anything else here needing to change. Not happy after
            subscribing? Email the founder within 14 days of your first charge and it&apos;s refunded -- the same
            personal review as approving a payment, on any rail.
          </p>
        </>,
      )}

      {section(
        6.5,
        <>
          <h2 className={h2}>What kind of tool this is</h2>
          <p className={p}>
            PostMortem AI is a focused drafting tool, not a general incident-management platform. It doesn&apos;t
            page anyone, run on-call schedules, or host a public status-page suite for you -- there&apos;s a single,
            shareable status page per incident, not a standing product for that. What it does is narrower and
            checkable: turn recorded evidence into a draft where every claim traces back to something real, verified
            by code before it&apos;s stored, not left to the model&apos;s word.
          </p>
        </>,
      )}

      {section(
        7,
        <>
          <h2 className={h2}>What this isn&apos;t</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
            <li>Doesn&apos;t auto-publish anything -- publishing is always a deliberate human action.</li>
            <li>Doesn&apos;t estimate cost, revenue, or customer-impact figures the evidence didn&apos;t state.</li>
            <li>
              Has real, documented setup paths for PagerDuty and Datadog (above) but not for other monitoring
              vendors -- any other tool can still be pointed at the generic webhook, un-adapted.
            </li>
            <li>Doesn&apos;t support teams or organizations yet -- each account is a single person&apos;s own incidents.</li>
          </ul>
        </>,
      )}

      <p className="mt-6 text-xs text-muted">
        <Link className="underline underline-offset-2" href="/">
          Back to PostMortem AI
        </Link>
      </p>
      </main>
      <SiteFooter />
    </>
  );
}
