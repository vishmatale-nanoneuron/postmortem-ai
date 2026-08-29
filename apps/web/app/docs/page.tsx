import type { Metadata } from "next";
import Link from "next/link";

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

export default function DocsPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8">
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

      <section className={card}>
        <h2 className={h2}>The core loop</h2>
        <p className={p}>
          Record incident evidence (alerts, logs, deploys, metrics, human notes, customer reports), generate an
          AI-drafted postmortem, publish it once a named human approves. Every account is a single user&apos;s own
          incidents -- no shared organizations yet.
        </p>
      </section>

      <section className={card}>
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
          .
        </p>
      </section>

      <section className={card}>
        <h2 className={h2}>RAG -- similar past incidents</h2>
        <p className={p}>
          When drafting, the system retrieves your own previously published postmortems that are semantically
          similar to the current incident (via embeddings, cosine similarity) and shows them to the model as
          reference context. This context is clearly labeled and is never citable -- the grounding check above only
          ever validates citations against the current incident&apos;s own numbered evidence, so a retrieved past
          incident can never become the source for a claim.
        </p>
      </section>

      <section className={card}>
        <h2 className={h2}>MCP -- backend, database, and frontend</h2>
        <p className={p}>
          The backend exposes an MCP server (<span className={code}>/mcp</span>) with tools for both founders
          (platform summary, payment-claim review, a defense-in-depth read-only SQL tool) and clients (incidents,
          evidence, drafting, publishing, similar-incident search) -- the same business logic and the same
          authorization rules as the REST API, not a second implementation. The frontend federates to it at{" "}
          <span className={code}>/api/mcp</span>, under the caller&apos;s own session.
        </p>
      </section>

      <section className={card}>
        <h2 className={h2}>Reliability</h2>
        <p className={p}>
          A real circuit breaker (closed/open/half-open) wraps the drafting model -- after repeated failures,
          further calls fail fast instead of repeatedly hitting an unhealthy provider, and an alert can fire to a
          configured webhook. Every draft attempt is logged in a queryable table (provider, latency, success or
          failure), not just described.
        </p>
      </section>

      <section className={card}>
        <h2 className={h2}>Anti-abuse</h2>
        <p className={p}>
          Login attempts are rate-limited per account and per IP. Creating incidents and drafting postmortems (the
          AI-cost-incurring action) are separately rate-limited per account. Registration and login can require a
          CAPTCHA (Cloudflare Turnstile) when configured.
        </p>
      </section>

      <section className={card}>
        <h2 className={h2}>Payments</h2>
        <p className={p}>
          An active subscription is required for the product&apos;s actual work (creating incidents, drafting,
          publishing) -- viewing your own history stays available regardless. Payment today is manual and
          human-verified: pay via UPI (India) or an international SWIFT wire, submit the transaction reference, and
          the founder approves it. Card payments (Stripe) are built and tested but not yet live.
        </p>
      </section>

      <section className={card}>
        <h2 className={h2}>What this isn&apos;t</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
          <li>Doesn&apos;t auto-publish anything -- publishing is always a deliberate human action.</li>
          <li>Doesn&apos;t estimate cost, revenue, or customer-impact figures the evidence didn&apos;t state.</li>
          <li>Doesn&apos;t integrate with PagerDuty, Datadog, or other monitoring tools yet.</li>
          <li>Doesn&apos;t support teams or organizations yet.</li>
        </ul>
      </section>

      <p className="mt-6 text-xs text-muted">
        <Link className="underline underline-offset-2" href="/">
          Back to PostMortem AI
        </Link>
      </p>
    </main>
  );
}
