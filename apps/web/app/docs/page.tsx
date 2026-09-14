import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { SiteFooter, SiteHeader } from "../landing";

export const metadata: Metadata = {
  title: "Docs",
  description:
    "The Airlock API reference (authentication, credits, scan and egress, deep scan, error semantics, code samples) and how PostMortem AI works: grounded drafting, RAG, MCP tools, payments, security.",
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
function section(index: number, children: React.ReactNode, id?: string) {
  return (
    <div
      id={id}
      style={{ animationDelay: `${index * 70}ms` }}
      // scroll-mt-16 only matters for a section with an id (something links
      // to it directly, e.g. the navbar's /docs#mcp) -- without it, this
      // page's own sticky SiteHeader would cover the top of the section on
      // arrival via anchor link.
      className={cn(
        "tilt-card-wrap mb-4 animate-in fade-in slide-in-from-bottom-2 fill-mode-backwards duration-700",
        id && "scroll-mt-16",
      )}
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
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">Airlock API reference, and how PostMortem AI works</h1>
        <p className="mt-2 text-sm text-muted">
          Written for humans and AI agents alike -- every claim here matches{" "}
          <a className="underline underline-offset-2" href="/llms.txt">
            /llms.txt
          </a>{" "}
          and the actual running code, not a roadmap.
        </p>
        <p className="mt-2 text-sm text-muted">
          Built for DevOps and SRE teams running their own on-call rotation, and for freelance SRE/DevOps
          consultants who need a clean, citable writeup at the end of an engagement -- one account, one client&apos;s
          incidents at a time; see &quot;The core loop&quot; below for exactly what that does and doesn&apos;t
          mean today.
        </p>
      </div>

      {section(
        0,
        <>
          <h2 className={h2}>Airlock API</h2>
          <p className={p}>
            Three decision endpoints (scan, egress, proxy fetch) plus policy, rules and usage, JSON in and JSON out, on{" "}
            <code className={code}>https://postmortem-ai-api.vercel.app</code>. The interactive reference (every
            field, every response code, an Authorize button that takes your key) is the{" "}
            <a className="underline underline-offset-2" href="https://postmortem-ai-api.vercel.app/docs" target="_blank" rel="noopener noreferrer">
              OpenAPI document
            </a>
            ; this page is the shape of it.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Authentication.</span> Send your key as{" "}
            <code className={code}>X-Airlock-Key: alk_…</code> (or <code className={code}>Authorization: Bearer alk_…</code>).
            Keys are minted in the Airlock section of your dashboard, shown once, stored as a hash, revocable at any
            time. No key and no session is <code className={code}>401</code>.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Credits.</span> One credit per call to{" "}
            <code className={code}>POST /v1/airlock/scan</code> or <code className={code}>POST /v1/airlock/egress</code>;
            five for a scan with <code className={code}>&quot;deep&quot;: true</code>, four of which are refunded when the
            rules alone already block -- the model is not asked what it cannot change. Taken atomically, in one
            debit, before the engine runs.
            An empty balance is <code className={code}>402</code> with no verdict returned; a refused or failed call
            (<code className={code}>401</code>, <code className={code}>402</code>, <code className={code}>422</code>,{" "}
            <code className={code}>429</code>) spends nothing, and an application error after the charge
            (<code className={code}>500</code>) refunds it on the ledger. Every response carries{" "}
            <code className={code}>credits_remaining</code> and <code className={code}>credits_charged</code>; you are
            emailed once when the balance drops below 1,000 and once when it reaches zero. Packs of 10,000 are bought
            from the dashboard by UPI or international wire.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Scan.</span> Body{" "}
            <code className={code}>{"{ content, source?, deep?, sanitize? }"}</code> (content up to 50,000 characters).
            Returns <code className={code}>verdict</code> (allow · flag · block), <code className={code}>score</code>{" "}
            (judged against your policy&apos;s thresholds; block at 0.75 and flag at 0.40 by default),{" "}
            <code className={code}>matches</code> (rule id, family, weight, description), <code className={code}>signals</code>{" "}
            (what normalisation uncovered), <code className={code}>policy</code> (the thresholds and muted rules
            applied), <code className={code}>content_sha256</code>, <code className={code}>latency_ms</code>; with{" "}
            <code className={code}>sanitize</code>, a <code className={code}>sanitized</code> copy with hidden characters,
            hidden HTML and the strongest matches removed, at no extra charge; and on a deep scan{" "}
            <code className={code}>semantic</code> (the model&apos;s answer, confidence and weight;{" "}
            <code className={code}>status: &quot;unavailable&quot;</code> with the extra credits refunded; or{" "}
            <code className={code}>status: &quot;skipped&quot;</code> when the rules already blocked).
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Egress.</span> Body{" "}
            <code className={code}>{"{ payload, destination?, allowlist? }"}</code>. Returns the verdict, the credential
            and personal-data patterns found, <code className={code}>destination_checked</code> (false when neither the
            call nor your policy supplied an allowlist -- then any destination passes), and{" "}
            <code className={code}>redacted</code>, the payload with secrets and personal data replaced, or null when
            there was nothing to redact. The call&apos;s allowlist is merged with the policy&apos;s, never substituted
            for it.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Proxy fetch.</span>{" "}
            <code className={code}>POST /v1/airlock/proxy/fetch</code>, body{" "}
            <code className={code}>{"{ url, allowlist?, deep?, return_content? }"}</code>. Airlock checks the URL as
            an outbound call first (your policy allowlist merged with the call&apos;s; credential material in the
            query string is a block), fetches it from its own address under a server-side request forgery guard
            (every resolved address checked, connection pinned to the checked address with the hostname as TLS
            server name, redirects re-checked, max 3, 1 MB read, text types only), scans the page under your
            policy, and returns <code className={code}>content</code> &mdash; the visible text &mdash; on allow,
            sanitized on flag, <code className={code}>null</code> on block. <code className={code}>stage</code> says
            which check decided. Two credits (four more with <code className={code}>deep</code>, refunded when the
            rules already block). A URL that will never be fetched is <code className={code}>422</code>; a public
            URL that could not be reached is <code className={code}>502</code>; both refund the scan credit, keep
            one for the attempt (so a refused fetch is never a free probe), and carry{" "}
            <code className={code}>&quot;verdict&quot;: &quot;block&quot;</code>. Nothing of yours &mdash; no
            headers, no cookies &mdash; is sent to the page.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Policy.</span> <code className={code}>GET /v1/airlock/policy</code>{" "}
            (key or session) returns the account&apos;s <code className={code}>block_threshold</code>,{" "}
            <code className={code}>flag_threshold</code>, <code className={code}>muted_rules</code> and{" "}
            <code className={code}>egress_allowlist</code>; <code className={code}>PUT</code> replaces it and{" "}
            <code className={code}>DELETE</code> resets it, both from a signed-in session only -- a key cannot
            change the policy it runs under, so a leaked key cannot switch the guard off. The rule vocabulary is
            public at <code className={code}>GET /v1/airlock/rules</code> (id, family, weight, description; not the
            patterns).
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Usage.</span> <code className={code}>GET /v1/airlock/usage?days=30</code>{" "}
            is your calls per day per key; <code className={code}>GET /v1/airlock/usage.csv?days=90</code> is every
            ledger line (purchases, grants, each metered call, refunds) as a CSV download. Both are your own ledger,
            not the audit log -- the audit log has no account column, which is what lets it stay append-only while
            deleting your account remains an erasure. Neither is metered.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Tuning.</span> A wrong verdict is reported with{" "}
            <code className={code}>POST /v1/airlock/feedback</code> (not metered): the scan&apos;s{" "}
            <code className={code}>content_sha256</code>, <code className={code}>verdict_given</code>,{" "}
            <code className={code}>verdict_expected</code> and the <code className={code}>rule_ids</code> that fired.{" "}
            <code className={code}>GET /v1/airlock/tuning</code> returns your reports and what they add up to: a rule
            reported as a false positive on three distinct scans becomes a &ldquo;mute this rule&rdquo; suggestion,
            applied in one call with <code className={code}>POST /v1/airlock/tuning/mute</code> (session only, through
            your policy); two reported misses from one source suggest <code className={code}>&quot;deep&quot;: true</code>{" "}
            for it. Include <code className={code}>content</code> on a report only if you want the text kept: it is then
            shown to Gemini as a worked answer on your own deep scans (the eight most recent;{" "}
            <code className={code}>semantic.examples</code> says how many), exportable as{" "}
            <code className={code}>GET /v1/airlock/tuning/export.jsonl</code> in the Vertex AI supervised-tuning format,
            and withdrawable with <code className={code}>DELETE /v1/airlock/feedback/&#123;id&#125;</code>. Both SDKs
            expose this as <code className={code}>feedback(result, expected)</code>, <code className={code}>tuning()</code>{" "}
            and the export. No customer content trains any model.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Operational.</span> Every response carries{" "}
            <code className={code}>X-Request-ID</code> (yours is echoed if you send one) and{" "}
            <code className={code}>Server-Timing</code>; every <code className={code}>429</code> carries{" "}
            <code className={code}>Retry-After</code>. Treat any non-200 as block; when the request reaches the
            application, a <code className={code}>5xx</code> on the scan or egress path says{" "}
            <code className={code}>&quot;verdict&quot;: &quot;block&quot;</code> in its own body, so a client that reads the
            body first agrees. Policy, usage and the CSV are not metered but are bounded per account (600 reads and
            60 exports an hour, then <code className={code}>429</code>). The audit log keeps a SHA-256 of
            what was scanned, never the content and never your account; the standard scan makes no model call.
            Public aggregate counts are at <code className={code}>GET /v1/airlock/stats</code>, prices at{" "}
            <code className={code}>GET /v1/airlock/pricing</code>.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">SDKs.</span> Official clients live in the repository:{" "}
            <a className="underline underline-offset-2" href="https://github.com/vishmatale-nanoneuron/postmortem-ai/tree/main/sdk/python" target="_blank" rel="noopener noreferrer">
              Python
            </a>{" "}
            (<code className={code}>from airlock import Airlock</code>; sync and async, httpx only) and{" "}
            <a className="underline underline-offset-2" href="https://github.com/vishmatale-nanoneuron/postmortem-ai/tree/main/sdk/typescript" target="_blank" rel="noopener noreferrer">
              TypeScript
            </a>{" "}
            (<code className={code}>new Airlock(&#123; apiKey &#125;)</code>; zero dependencies). Three methods each
            &mdash; <code className={code}>scan</code>, <code className={code}>egress</code>,{" "}
            <code className={code}>fetch</code> &mdash; plus <code className={code}>policy</code>,{" "}
            <code className={code}>usage</code>, <code className={code}>rules</code>. Every non-200 raises a typed
            error carrying the request id, so &ldquo;any exception is a block&rdquo; fails closed; nothing is retried,
            because a retried scan is a second charge. Not yet on PyPI or npm: install from the repository path
            until they are.
          </p>
          <p className={cn(p, "mb-0")}>
            Code samples in curl, Python and TypeScript are on{" "}
            <Link className="underline underline-offset-2" href="/airlock#integrate">
              the Airlock page
            </Link>
            ; the long-form reference an AI assistant can read is{" "}
            <a className="underline underline-offset-2" href="/llms-full.txt">
              /llms-full.txt
            </a>
            .
          </p>
        </>,
        "airlock",
      )}

      {section(
        0.5,
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
          <h2 className={h2}>Drafting style -- tuning, per account</h2>
          <p className={p}>
            <code className={code}>GET/PUT/DELETE /v1/postmortems/preferences</code> (session) holds your team&apos;s
            house style: up to 1,500 characters of instructions on phrasing and structure, and whether your most
            recent published postmortem is shown to the model as an example of how you write (on by default). Both
            go into the system prompt on every draft, never into the numbered evidence, and govern form only: a style
            instruction cannot add a fact, and the example is never citable. Drafts made with a style record{" "}
            <code className={code}>prompt_version: &quot;v4+style&quot;</code>. No customer content trains any model
            -- the example is your own text on your own drafts. The <span className="font-medium text-ink">Drafting
            style</span> card on the dashboard edits it.
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
          <p className={p}>
            Every tool call is recorded, including denials: an agent that isn&apos;t authorized for a given action
            (a client-scoped account calling a founder-only tool, an unpaid account trying to create an incident)
            gets refused, and that refusal is written into the same durable activity log as a successful call --
            not just logged to ops output that ages out, queryable via each account&apos;s own activity log, and,
            for the founder, across every account at once. An agent gets exactly the access a browser session
            would, no more, and every attempt it makes -- allowed or not -- leaves a real record.
          </p>
        </>,
        "mcp",
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
          <p className={p}>
            Slack has its own receiver too: paste the URL from account settings into a Slack app&apos;s Event
            Subscriptions, subscribe to <code className="font-mono">message.channels</code>, and invite it to your
            incident channel. One thread becomes one incident -- the first message opens it, every reply is recorded
            as further evidence on it, so the timeline assembles itself instead of being pasted in afterwards.
          </p>
          <p className={p}>
            Three things it deliberately won&apos;t do. Messages from bots are ignored, because this app also posts
            its own notifications into Slack and ingesting those would let it cite text it wrote itself. Edited and
            deleted messages never rewrite evidence already recorded. And nothing resolves an incident or drafts a
            postmortem off a chat message -- &quot;we&apos;re resolved&quot; typed in a channel is not an
            authenticated state change, unlike a PagerDuty resolve, which is.
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
            Every incident, from the first, requires an active subscription; there is no free tier. To judge the
            output before paying, read{" "}
            <Link className="underline underline-offset-2" href="/blog/github-outage-demo">
              the postmortem this tool drafted from a real public outage
            </Link>
            . For clients anywhere in the world, an international SWIFT wire (USD/GBP/EUR) or UPI (India)
            works today -- submit the
            transaction reference and the founder reviews and approves it personally, usually quickly. UPI and
            wire are the only payment rails: there is no card processor, by decision. Not happy after
            subscribing? Email the founder within 14 days of your first charge and it&apos;s refunded -- the same
            personal review as approving a payment, on any rail.
          </p>
          <p className={p}>
            Both rails can be paid monthly or annually, and annual is charged for ten months -- two are free. If
            you&apos;re paying by SWIFT wire, take the annual option: a wire costs the sender roughly USD 15-40 in
            bank fees, which is more than a single month of this subscription, so monthly-by-wire means paying a
            surcharge larger than the product. Current prices are on the{" "}
            <Link className="underline underline-offset-2" href="/pricing">
              pricing page
            </Link>
            .
          </p>
          <p className={p}>
            Deleting your account is a real erasure, not a disabled login: every incident, evidence entry,
            postmortem, draft and activity-log entry it owns is permanently removed, in one transaction, including
            any postmortem you published publicly. Export your data first if you want to keep a copy -- afterwards
            there is nothing left to recover, by you or by us.
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
