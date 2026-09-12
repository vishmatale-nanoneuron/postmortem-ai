import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { SiteFooter, SiteHeader } from "../landing";
import { AirlockMark } from "./airlock-mark";
import { Playground } from "./playground";
import { ScanTheatre } from "./scan-theatre";
import { WaitlistForm } from "./waitlist-form";

// The second product. Rules for this page, which matter more here than on
// any other page on the site:
//
// 1. Nothing is sold, and the line between what runs and what doesn't is
//    drawn explicitly. The scanner IS live: POST /v1/airlock/scan and
//    /v1/airlock/egress run the engine in this repo's FastAPI backend, free
//    and unauthenticated, and the playground on this page really calls them.
//    What does not exist is the commercial product around it -- API keys,
//    per-tenant policy, metering, billing, an SLA. So there is still no
//    price and no buy button, and the waitlist is for that hosted version,
//    not for the scanner (which needs no waiting).
// 2. Every number below was produced by running the code, not taken from a
//    description of it: 30 rules across 8 families (backend/app/engine/
//    rules.py), block at 0.75 / flag at 0.40 (engine/detector.py), 11
//    credential and 7 PII patterns (engine/egress.py), and the 18-case
//    result from backend/tests/test_detector.py.
// 3. The 18 cases are OUR OWN and the page says so in the same sentence as
//    the result. It is a smoke test, not a benchmark; publishing it as a
//    precision/recall figure would be the exact dressing-an-estimate-as-a-
//    measurement move /postmortem-template tells readers not to make.
const TITLE = "Airlock — prompt injection and exfiltration guard for AI agents";
const DESCRIPTION =
  "A guard that sits between an AI agent and untrusted content: scores inbound text for prompt injection before it reaches the context window, and checks outbound calls for credentials and PII before they leave. Free scanner, no signup. Append-only audit log.";

export const metadata: Metadata = {
  title: "Airlock — prompt injection guard for AI agents",
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  alternates: { canonical: "/airlock" },
  // Defined explicitly for the same reason as /postmortem-template: Next.js
  // doesn't deep-merge openGraph across segments, so without this a shared
  // link to the second product would preview as the first one.
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: "https://www.nanoneuron.ai/airlock",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: TITLE }],
  },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION, images: ["/opengraph-image"] },
};

const card = "rounded-lg border border-line bg-white p-5 shadow-sm";
const h2 = "mb-2 text-lg font-semibold text-ink";
const p = "text-sm text-muted leading-relaxed mb-2";

const STRUCTURED_DATA = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Airlock",
  applicationCategory: "SecurityApplication",
  description: DESCRIPTION,
  url: "https://www.nanoneuron.ai/airlock",
  // No `offers` block: there is no price and nothing to buy yet, and
  // claiming one in structured data would put a price in search results
  // that the page itself doesn't make.
  author: { "@type": "Organization", name: "NanoNeuron", url: "https://www.nanoneuron.ai" },
};

// Straight from backend/app/engine/rules.py's family field -- eight
// families, with the rule counts this page quotes.
const FAMILIES: { name: string; what: string }[] = [
  { name: "Instruction override", what: "“Ignore all previous instructions” and its many rewordings." },
  { name: "Role hijack", what: "Content that tries to reassign the agent's role or persona mid-context." },
  { name: "Delimiter break", what: "Fake system/user turn markers, forged tags, anything that pretends to end your prompt." },
  { name: "Exfiltration", what: "Instructions to send data somewhere — a URL, an image, a markdown link that fires on render." },
  { name: "Tool abuse", what: "Content that asks the agent to call a tool it was not asked to call." },
  { name: "Authority spoof", what: "“This is your developer / the system administrator” framing." },
  { name: "Memory poison", what: "Instructions aimed at what the agent stores and recalls later, not just this turn." },
  { name: "Encoding", what: "Base64, rot13 and chained decode-then-obey instructions." },
];

function Section({
  children,
  className,
  id,
}: {
  children: React.ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={cn(card, "mb-4", className)}>
      {children}
    </section>
  );
}

export default function AirlockPage() {
  return (
    <>
      <script
        type="application/ld+json"
        // Static, hardcoded JSON, no user input -- safe despite dangerouslySetInnerHTML.
        dangerouslySetInnerHTML={{ __html: JSON.stringify(STRUCTURED_DATA) }}
      />
      <SiteHeader />
      <main className="mx-auto max-w-2xl px-4 py-10">
        <div className="mb-8">
          <div className="flex items-center gap-2.5">
            <AirlockMark size={26} />
            <span className="text-sm font-semibold tracking-tight text-ink">Airlock</span>
            <span className="rounded-full border border-line px-2 py-0.5 text-[10px] tracking-wide text-muted uppercase">
              Free scanner · live
            </span>
          </div>
          <h1 className="mt-4 text-3xl leading-[1.15] font-semibold tracking-tight text-ink sm:text-4xl">
            Your agent reads things you didn&apos;t write.
          </h1>
          <p className="mt-3 text-sm text-muted leading-relaxed">
            A support ticket, a web page, a PDF, a GitHub issue, an email. Any of them can contain a sentence aimed
            at the model rather than at you. Airlock is a guard that sits between your agent and that content:
            untrusted text goes through it before it reaches the context window, and outbound calls go through it
            before they leave.
          </p>
        </div>

        {/* The demonstration, where a product video would go. Every verdict,
            score and rule id in it is real output from the engine -- see
            scan-theatre.tsx. */}
        <div className="mb-3">
          <ScanTheatre />
        </div>
        <p className="mb-8 text-xs text-muted">
          Recorded output from Airlock&apos;s detector, replayed &mdash; scores, rule ids and verdicts are what the
          engine actually returned for exactly this content. This panel is a replay;{" "}
          <a className="underline underline-offset-2" href="#try-it">
            the scanner further down is live
          </a>{" "}
          and will run on whatever you paste into it.
        </p>

        <Section>
          <h2 className={h2}>Two checks, in opposite directions</h2>
          <p className={p}>
            <span className="font-medium text-ink">Inbound.</span> Text is normalised first &mdash; Unicode tag
            characters decoded, invisible characters stripped, HTML comments and hidden elements pulled out, letter
            s p a c i n g collapsed &mdash; because an injection that survives only until someone looks at the raw
            bytes is the whole trick. The normalised text is then scored against{" "}
            <span className="font-medium text-ink">30 weighted rules across 8 attack families</span>. Scores combine
            with noisy-OR, not addition: three weak signals raise suspicion without three of them being able to
            manufacture certainty. At 0.75 the verdict is block; at 0.40, flag.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Outbound.</span> Before your agent calls something, the
            destination is checked against your allowlist and the payload against{" "}
            <span className="font-medium text-ink">11 credential patterns</span> (AWS keys, OpenAI and Anthropic
            keys, GitHub and Slack tokens, Stripe keys, private keys, bearer tokens and JWTs) and{" "}
            <span className="font-medium text-ink">7 personal-data patterns</span> (email, phone, card number, SSN,
            Aadhaar, PAN, IBAN), plus an entropy check on query strings &mdash; the shape a key takes when someone
            hides it in a URL.
          </p>
          <p className={p}>
            Personal data is weighted by kind, not just counted. One email address in an outbound call is ordinary
            and passes; one card number, SSN, Aadhaar, PAN or IBAN is flagged even to an allowed destination, and
            three at once is blocked &mdash; that is an export, not an integration. The allowlist answers{" "}
            <em>where</em>, never <em>what</em>, which is the same reason an AWS key is blocked on its way to a
            destination you approved.
          </p>
        </Section>

        <Section>
          <h2 className={h2}>The eight families</h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {FAMILIES.map((family) => (
              <div key={family.name} className="rounded-md bg-paper px-3.5 py-3">
                <p className="text-sm font-medium text-ink">{family.name}</p>
                <p className="mt-0.5 text-sm text-muted leading-relaxed">{family.what}</p>
              </div>
            ))}
          </div>
        </Section>

        <Section>
          <h2 className={h2}>What we can honestly say it detects today</h2>
          <p className={p}>
            Airlock ships with an 18-case suite we wrote ourselves: 11 attacks &mdash; including ones hidden in
            Unicode tag characters, HTML comments and spaced-out text &mdash; and 7 ordinary documents (an invoice,
            a support ticket, a security blog post, source code, docs, an email, a research paper). On the current
            rules it blocks all 11 and scores all 7 ordinary documents at zero.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">That is a smoke test, not a benchmark.</span> Eighteen cases we
            chose ourselves cannot tell you a false-positive rate, and we are not going to quote one until the
            corpus is seeded from public injection datasets and the benchmark is run in the open. When it is, the
            corpus and the numbers get published &mdash; including the misses.
          </p>
        </Section>

        <Section>
          <h2 className={h2}>What it does with your content</h2>
          <p className={p}>
            It is the first question worth asking about a product you route untrusted text through, so:{" "}
            <span className="font-medium text-ink">the raw content is not stored.</span> An audit entry keeps a
            SHA-256 of what was scanned, the byte count, the verdict, the rules that fired and a redacted excerpt
            &mdash; enough to prove later what the guard saw and decided, without keeping the thing itself.
          </p>
          <p className={p}>
            The log is append-only, and that is enforced by database triggers that reject UPDATE, DELETE{" "}
            <em>and TRUNCATE</em> on the table &mdash; not by application code that could be bypassed by anything
            else holding the same connection. The TRUNCATE guard matters more than it sounds: a row-level trigger
            alone leaves it open, because TRUNCATE deletes no rows, and we confirmed it emptied the table silently
            before adding the second trigger.
          </p>
          <p className={p}>
            There is no model call and no network request in the decision path &mdash; 30 regexes over normalised
            text, and nothing else &mdash; so the scanner has no &ldquo;undecided&rdquo; state to fail open into. If
            it breaks it returns a 5xx with no verdict at all, which a caller must treat as block. A security check
            that defaults to &ldquo;allow&rdquo; when it breaks is not a security check.
          </p>
        </Section>

        <Section className="border-accent/40" id="try-it">
          <h2 className={h2}>Try it on your own text</h2>
          <p className={p}>
            This is the real scanner, not a demo of one. It posts to{" "}
            <code className="rounded bg-paper px-1 py-0.5 font-mono text-[12px]">POST /v1/airlock/scan</code> and
            shows exactly what the engine returned — including when it disagrees with what you expected. Free, no
            signup, bounded per address.
          </p>
          <div className="mt-4">
            <Playground />
          </div>
        </Section>

        <Section>
          <h2 className={h2}>What runs, and what doesn&apos;t</h2>
          <p className={p}>
            <span className="font-medium text-ink">Running now:</span> the detection engine, the egress check and
            the append-only audit log, served free and unauthenticated from this site&apos;s own backend at{" "}
            <code className="rounded bg-paper px-1 py-0.5 font-mono text-[12px]">/v1/airlock/scan</code> and{" "}
            <code className="rounded bg-paper px-1 py-0.5 font-mono text-[12px]">/v1/airlock/egress</code>. Point a
            script at them today if you want to.
          </p>
          <p className={p}>
            <span className="font-medium text-ink">Not built yet:</span> API keys, per-tenant thresholds and
            allowlists, usage metering, billing, a customer dashboard, and any kind of support commitment. That is
            the commercial product, and it is what the early-access list below is for — not the scanner, which
            needs no waiting.
          </p>
          <p className={p}>
            The next thing worth building is not features either, it is the corpus: 30 hand-written rules is a
            starting point, not a defence. Public injection payloads go in first, and the benchmark gets published
            with them.
          </p>
        </Section>

        <Section className="border-accent/40">
          <h2 className={h2}>Early access</h2>
          <p className={p}>
            The scanner above is already free and needs no account. This list is for the hosted version — your own
            API key, your own thresholds and egress allowlist, and a log you can export. One email when that
            exists. If you describe what you&apos;d point it at, that shapes which attack families get seeded
            first.
          </p>
          <div className="mt-4">
            <WaitlistForm />
          </div>
        </Section>

        <p className="mt-6 text-xs text-muted">
          Airlock is the second product from NanoNeuron. The first is{" "}
          <Link className="underline underline-offset-2" href="/">
            PostMortem AI
          </Link>
          , which drafts incident postmortems where every claim cites recorded evidence &mdash; live, paid, and
          documented at{" "}
          <Link className="underline underline-offset-2" href="/docs">
            /docs
          </Link>
          . Both are built on the same rule: say what the evidence supports, and say so plainly when it
          doesn&apos;t.
        </p>
      </main>
      <SiteFooter />
    </>
  );
}
