import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { SiteFooter, SiteHeader } from "../landing";
import { CopyTemplateButton } from "./copy-template";
import { DRAFTED_SECTIONS, TEMPLATE_MARKDOWN } from "./template-markdown";

const TITLE = "Blameless postmortem template";
const DESCRIPTION =
  "A free incident postmortem template in Markdown: summary, impact, timeline, detection, root cause, contributing factors, resolution, action items. Every section explains what belongs in it and what to write when the evidence doesn't say. No signup.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  alternates: { canonical: "/postmortem-template" },
  // Defined explicitly for the same reason as /postmortems: Next.js doesn't
  // deep-merge openGraph across segments, so without this the page would
  // share a link preview with the homepage.
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "article",
    url: "https://www.nanoneuron.ai/postmortem-template",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: TITLE }],
  },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION, images: ["/opengraph-image"] },
};

const card = "rounded-lg border border-line bg-white p-5 shadow-sm mb-4";
const h2 = "mb-2 text-lg font-semibold text-ink";
const p = "text-sm text-muted leading-relaxed mb-2";

// This file's own first-commit date, same convention as the blog posts.
const PUBLISHED_DATE = "2026-09-11";

const ARTICLE_STRUCTURED_DATA = {
  "@context": "https://schema.org",
  "@type": "TechArticle",
  headline: TITLE,
  description: DESCRIPTION,
  datePublished: PUBLISHED_DATE,
  author: { "@type": "Organization", name: "PostMortem AI", url: "https://www.nanoneuron.ai" },
  publisher: { "@type": "Organization", name: "PostMortem AI", url: "https://www.nanoneuron.ai" },
  mainEntityOfPage: "https://www.nanoneuron.ai/postmortem-template",
  isAccessibleForFree: true,
};

function section(index: number, children: React.ReactNode) {
  return (
    <div
      style={{ animationDelay: `${index * 90}ms` }}
      className="tilt-card-wrap mb-4 animate-in fade-in slide-in-from-bottom-2 fill-mode-backwards duration-700"
    >
      <section tabIndex={0} className={cn(card, "tilt-card mb-0")}>
        {children}
      </section>
    </div>
  );
}

// What each section is for, in the order they appear in the template. The
// "drafted" flag is derived from DRAFTED_SECTIONS so this list can't claim
// the tool fills a section the backend doesn't actually return.
const GUIDE: { name: string; what: string; avoid: string }[] = [
  {
    name: "Summary",
    what: "What broke, who noticed, how long it lasted, how it ended -- in two to four sentences. Written last.",
    avoid: "Anything not already established further down. The summary condenses the postmortem; it doesn't add to it.",
  },
  {
    name: "Impact",
    what: "What users and internal teams experienced, with numbers where they were actually measured.",
    avoid: "Estimates dressed as measurements. \"Roughly 28% of requests\" is fine if a dashboard said so; \"probably thousands of users\" is not.",
  },
  {
    name: "Timeline",
    what: "One row per event, in UTC, each pointing at a recorded artifact: the alert, the deploy, the log line, the message in the incident channel.",
    avoid: "Reconstructing from memory a week later. If nobody wrote it down at the time, the row says so.",
  },
  {
    name: "Detection",
    what: "How it was noticed, and the gap between first impact and first notice. That gap is often the most useful number in the whole document.",
    avoid: "Skipping it because detection was \"obvious\". It rarely is, and a customer report reaching you before your alerts did is worth recording.",
  },
  {
    name: "Root cause",
    what: "The condition that, had it been absent, would have meant no incident. Cited to the rows that establish it.",
    avoid: "A plausible story the evidence doesn't support. Write \"Not established by the recorded evidence.\" and leave it -- reviewers can act on an honest gap; they can't act on a guess they don't know is a guess.",
  },
  {
    name: "Contributing factors",
    what: "What made it worse, longer, or harder to see. A missing alert, a retry storm, a limit nobody knew existed.",
    avoid: "Naming people. \"The deploy skipped the canary step\" is a factor; \"Priya skipped the canary\" is blame, and the next person will hide the same mistake instead of reporting it.",
  },
  {
    name: "Resolution",
    what: "What actually stopped the impact, and when. A rollback, a revert, a failover.",
    avoid: "Conflating it with the permanent fix. The fix goes under action items, with an owner.",
  },
  {
    name: "Action items",
    what: "Concrete changes, each with one owner and a date. The tool drafts the item, its rationale and a suggested owner, each cited; the date is yours.",
    avoid: "\"Team to consider improving monitoring.\" No owner, no date, no verb anyone can be asked about in a month.",
  },
];

export default function PostmortemTemplatePage() {
  const drafted = new Set<string>(DRAFTED_SECTIONS);
  return (
    <>
      <script
        type="application/ld+json"
        // Static, hardcoded JSON, no user input -- safe despite dangerouslySetInnerHTML.
        dangerouslySetInnerHTML={{ __html: JSON.stringify(ARTICLE_STRUCTURED_DATA) }}
      />
      <SiteHeader />
      <main className="mx-auto max-w-2xl px-4 py-10">
        <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 duration-700">
          <div className="text-xs font-medium tracking-widest text-muted uppercase">
            Template · <time dateTime={PUBLISHED_DATE}>{PUBLISHED_DATE}</time>
          </div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">{TITLE}</h1>
          <p className="mt-2 text-sm text-muted">
            Plain Markdown, no signup, paste it into whatever your team already writes in. Each section says what
            belongs in it and -- more useful -- what to write when the evidence doesn&apos;t say.
          </p>
        </div>

        {section(
          0,
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className={cn(h2, "mb-0")}>The template</h2>
              <CopyTemplateButton />
            </div>
            <pre className="overflow-x-auto rounded-md bg-paper px-3.5 py-3 font-mono text-[12.5px] leading-relaxed whitespace-pre text-ink">
              {TEMPLATE_MARKDOWN}
            </pre>
          </>,
        )}

        {section(
          1,
          <>
            <h2 className={h2}>Why &ldquo;blameless&rdquo; is a structural choice, not a tone</h2>
            <p className={p}>
              A postmortem exists so the next incident is shorter. That only works if the people closest to the
              failure tell you exactly what happened, and they won&apos;t if the document is where names get
              attached to mistakes. So the template has no field for &ldquo;who&rdquo; -- only for what the systems
              and the recorded evidence show. This isn&apos;t our invention; it&apos;s the position of{" "}
              <a
                className="underline underline-offset-2"
                href="https://sre.google/sre-book/postmortem-culture/"
                target="_blank"
                rel="noopener noreferrer"
              >
                Google&apos;s SRE book, &ldquo;Postmortem Culture: Learning from Failure&rdquo;
              </a>
              , which is the clearest published argument for it.
            </p>
            <p className={p}>
              The second structural choice: every claim points at a timeline row. A root cause with no citation
              isn&apos;t a root cause yet, it&apos;s a hypothesis -- and the template says to write that down as
              such rather than promote it.
            </p>
          </>,
        )}

        {section(
          2,
          <>
            <h2 className={h2}>Section by section</h2>
            <div className="space-y-3">
              {GUIDE.map((g) => (
                <div key={g.name} className="rounded-md bg-paper px-3.5 py-3">
                  <p className="mb-1 text-sm font-medium text-ink">
                    {g.name}
                    {drafted.has(g.name) && (
                      <span className="ml-2 rounded-full border border-line px-2 py-0.5 text-[11px] font-normal text-muted">
                        drafted by the tool
                      </span>
                    )}
                  </p>
                  <p className="text-sm text-muted leading-relaxed">{g.what}</p>
                  <p className="mt-1 text-sm text-muted leading-relaxed">
                    <span className="font-medium text-ink">Avoid:</span> {g.avoid}
                  </p>
                </div>
              ))}
            </div>
          </>,
        )}

        {section(
          3,
          <>
            <h2 className={h2}>A real one, filled in</h2>
            <p className={p}>
              The template is easier to judge with an incident in it. We filled it from Cloudflare&apos;s own
              published reports on two of its 2025 outages -- every line quoted verbatim and linked, nothing
              paraphrased --{" "}
              <Link className="underline underline-offset-2" href="/blog/cloudflare-outages-2025">
                here
              </Link>
              . For what the tool itself drafts, unedited, from three evidence entries, see{" "}
              <Link className="underline underline-offset-2" href="/blog/github-outage-demo">
                the GitHub outage demo
              </Link>
              .
            </p>
          </>,
        )}

        {section(
          4,
          <>
            <h2 className={h2}>Where the tool fits</h2>
            <p className={p}>
              The six sections tagged &ldquo;drafted by the tool&rdquo; above are what PostMortem AI writes from
              your recorded evidence, each sentence cited to a timeline row, and any sentence it can&apos;t cite
              is dropped rather than kept. The rest -- impact, what went well, lessons, and the dates on action
              items -- stay yours, because they need judgment the evidence doesn&apos;t contain.
            </p>
            <p className={p}>
              Your first incident is free.{" "}
              <Link className="underline underline-offset-2" href="/">
                Start one
              </Link>{" "}
              or read{" "}
              <Link className="underline underline-offset-2" href="/blog/grounding-mechanism">
                how the grounding works
              </Link>
              .
            </p>
          </>,
        )}

        <p className="mt-6 text-xs text-muted">
          <Link className="underline underline-offset-2" href="/">
            Back to PostMortem AI
          </Link>
          {" · "}
          <Link className="underline underline-offset-2" href="/docs">
            How it works
          </Link>
        </p>
      </main>
      <SiteFooter />
    </>
  );
}
