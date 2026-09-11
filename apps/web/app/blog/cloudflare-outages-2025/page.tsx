import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { SiteFooter, SiteHeader } from "../../landing";

const TITLE = "Two Cloudflare outages, in postmortem form";
const DESCRIPTION =
  "Cloudflare's own 18 November and 5 December 2025 incident reports laid out in a blameless postmortem template -- every line quoted verbatim and linked to the source, so you can see what a filled-in template looks like on a real, public, checkable incident.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  alternates: { canonical: "/blog/cloudflare-outages-2025" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "article",
    url: "https://www.nanoneuron.ai/blog/cloudflare-outages-2025",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: TITLE }],
  },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION, images: ["/opengraph-image"] },
};

const card = "rounded-lg border border-line bg-white p-5 shadow-sm mb-4";
const h2 = "mb-2 text-lg font-semibold text-ink";
const h3 = "mt-4 mb-1 text-xs font-medium text-muted uppercase";
const p = "text-sm text-muted leading-relaxed mb-2";
const quote = "font-mono text-[13px] leading-relaxed text-ink";

// This file's own first-commit date, same convention as the other posts.
const PUBLISHED_DATE = "2026-09-11";

const ARTICLE_STRUCTURED_DATA = {
  "@context": "https://schema.org",
  "@type": "TechArticle",
  headline: TITLE,
  description: DESCRIPTION,
  datePublished: PUBLISHED_DATE,
  author: { "@type": "Organization", name: "PostMortem AI", url: "https://www.nanoneuron.ai" },
  publisher: { "@type": "Organization", name: "PostMortem AI", url: "https://www.nanoneuron.ai" },
  mainEntityOfPage: "https://www.nanoneuron.ai/blog/cloudflare-outages-2025",
  citation: ["https://blog.cloudflare.com/18-november-2025-outage/", "https://blog.cloudflare.com/5-december-2025-outage/"],
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

// Every string below was checked against the linked post on 2026-09-11 and
// is reproduced exactly, including Cloudflare's own spelling ("behaviour")
// and its own grammar ("replace it with"). If a line here ever needs
// "tidying", it should be removed instead -- the page's only claim is that
// nothing in it is paraphrased.
type Row = { time: string; status: string; text: string };
type Incident = {
  slug: string;
  heading: string;
  source: { title: string; url: string; author: string };
  severityNote: string;
  impact: string[];
  timeline: Row[];
  detection: string;
  rootCause: string;
  contributing: string[];
  resolution: string;
};

const INCIDENTS: Incident[] = [
  {
    slug: "nov-18",
    heading: "18 November 2025 -- core traffic failed globally",
    source: {
      title: "Cloudflare outage on November 18, 2025",
      url: "https://blog.cloudflare.com/18-november-2025-outage/",
      author: "Matthew Prince",
    },
    severityNote:
      "The report doesn't assign one. On our own scale this is a sev1: a global failure of core traffic delivery lasting hours.",
    impact: [
      "On 18 November 2025 at 11:20 UTC (all times in this blog are UTC), Cloudflare's network began experiencing significant failures to deliver core network traffic. This showed up to Internet users trying to access our customers' sites as an error page indicating a failure within Cloudflare's network.",
    ],
    timeline: [
      { time: "11:05", status: "Normal.", text: "Database access control change deployed." },
      {
        time: "11:28",
        status: "Impact starts.",
        text: "Deployment reaches customer environments, first errors observed on customer HTTP traffic.",
      },
      {
        time: "11:32-13:05",
        status: "The team investigated elevated traffic levels and errors to Workers KV service.",
        text: "The initial symptom appeared to be degraded Workers KV response rate causing downstream impact on other Cloudflare services. Mitigations such as traffic manipulation and account limiting were attempted to bring the Workers KV service back to normal operating levels. The first automated test detected the issue at 11:31 and manual investigation started at 11:32. The incident call was created at 11:35.",
      },
      {
        time: "13:05",
        status: "Workers KV and Cloudflare Access bypass implemented -- impact reduced.",
        text: "During investigation, we used internal system bypasses for Workers KV and Cloudflare Access so they fell back to a prior version of our core proxy. Although the issue was also present in prior versions of our proxy, the impact was smaller as described below.",
      },
      {
        time: "13:37",
        status: "Work focused on rollback of the Bot Management configuration file to a last-known-good version.",
        text: "We were confident that the Bot Management configuration file was the trigger for the incident. Teams worked on ways to repair the service in multiple workstreams, with the fastest workstream a restore of a previous version of the file.",
      },
      {
        time: "14:24",
        status: "Stopped creation and propagation of new Bot Management configuration files.",
        text: "We identified that the Bot Management module was the source of the 500 errors and that this was caused by a bad configuration file. We stopped automatic deployment of new Bot Management configuration files.",
      },
      {
        time: "14:24",
        status: "Test of new file complete.",
        text: "We observed successful recovery using the old version of the configuration file and then focused on accelerating the fix globally.",
      },
      {
        time: "14:30",
        status: "Main impact resolved. Downstream impacted services started observing reduced errors.",
        text: "A correct Bot Management configuration file was deployed globally and most services started operating correctly.",
      },
      {
        time: "17:06",
        status: "All services resolved. Impact ends.",
        text: "All downstream services restarted and all operations fully restored.",
      },
    ],
    detection:
      "The first automated test detected the issue at 11:31 and manual investigation started at 11:32. The incident call was created at 11:35.",
    rootCause:
      "A change in our underlying ClickHouse query behaviour (explained below) that generates this file caused it to have a large number of duplicate 'feature' rows.",
    contributing: [
      "When the bad file with more than 200 features was propagated to our servers, this limit was hit -- resulting in the system panicking.",
    ],
    resolution:
      "We solved the problem by stopping the generation and propagation of the larger-than-expected feature file and replace it with an earlier version of the file.",
  },
  {
    slug: "dec-5",
    heading: "5 December 2025 -- 28% of HTTP traffic, 25 minutes",
    source: {
      title: "Cloudflare outage on December 5, 2025",
      url: "https://blog.cloudflare.com/5-december-2025-outage/",
      author: "Dane Knecht",
    },
    severityNote:
      "Not assigned in the report. On our scale a sev2: a large share of traffic, but contained within half an hour by a revert.",
    impact: [
      "On December 5, 2025, at 08:47 UTC (all times in this blog are UTC), a portion of Cloudflare's network began experiencing significant failures. The incident was resolved at 09:12 (~25 minutes total impact), when all services were fully restored.",
      "A subset of customers were impacted, accounting for approximately 28% of all HTTP traffic served by Cloudflare",
    ],
    timeline: [
      { time: "08:47", status: "INCIDENT start", text: "Configuration change deployed and propagated to the network" },
      { time: "08:48", status: "Full impact", text: "Change fully propagated" },
      { time: "08:50", status: "INCIDENT declared", text: "Automated alerts" },
      { time: "09:11", status: "Change reverted", text: "Configuration change reverted and propagation start" },
      { time: "09:12", status: "INCIDENT end", text: "Revert fully propagated, all traffic restored" },
    ],
    detection: "08:50 -- INCIDENT declared -- Automated alerts",
    rootCause:
      "it was triggered by changes being made to our body parsing logic while attempting to detect and mitigate an industry-wide vulnerability",
    contributing: [
      "When the killswitch was applied, the code correctly skipped the evaluation of the execute action, and didn't evaluate the sub-ruleset pointed to by it.",
    ],
    resolution:
      "The issue was identified shortly after the change was applied, and was reverted at 09:12, after which all traffic was served correctly.",
  },
];

function Quote({ children }: { children: React.ReactNode }) {
  return (
    <blockquote className="mt-1 rounded-md bg-paper px-3.5 py-3">
      <p className={quote}>&ldquo;{children}&rdquo;</p>
    </blockquote>
  );
}

function IncidentSection({ incident, index }: { incident: Incident; index: number }) {
  return section(
    index,
    <>
      <h2 className={h2} id={incident.slug}>
        {incident.heading}
      </h2>
      <p className={p}>
        Source:{" "}
        <a className="underline underline-offset-2" href={incident.source.url} target="_blank" rel="noopener noreferrer">
          {incident.source.title}
        </a>
        , by {incident.source.author}, on the Cloudflare blog. Every quoted line below is from that post.
      </p>

      <h3 className={h3}>Severity</h3>
      <p className={p}>{incident.severityNote}</p>

      <h3 className={h3}>Impact</h3>
      {incident.impact.map((line) => (
        <Quote key={line.slice(0, 40)}>{line}</Quote>
      ))}

      <h3 className={h3}>Timeline (UTC), as published</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-muted uppercase">
              <th className="py-1.5 pr-3 font-medium">Time</th>
              <th className="py-1.5 pr-3 font-medium">Status</th>
              <th className="py-1.5 font-medium">Description</th>
            </tr>
          </thead>
          <tbody>
            {incident.timeline.map((row, i) => (
              <tr key={`${row.time}-${i}`} className="border-b border-line align-top last:border-b-0">
                <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap text-ink">{row.time}</td>
                <td className="py-2 pr-3 text-ink">{row.status}</td>
                <td className="py-2 text-muted">{row.text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className={h3}>Detection</h3>
      <Quote>{incident.detection}</Quote>

      <h3 className={h3}>Root cause</h3>
      <Quote>{incident.rootCause}</Quote>

      <h3 className={h3}>Contributing factors</h3>
      {incident.contributing.map((line) => (
        <Quote key={line.slice(0, 40)}>{line}</Quote>
      ))}

      <h3 className={h3}>Resolution</h3>
      <Quote>{incident.resolution}</Quote>

      <h3 className={h3}>Action items</h3>
      <p className={p}>
        Not reproduced here. Cloudflare&apos;s report lists its own follow-up work; it belongs to them and is
        best read at the source.
      </p>
    </>,
  );
}

export default function CloudflareOutagesPost() {
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
            Worked example · <time dateTime={PUBLISHED_DATE}>{PUBLISHED_DATE}</time>
          </div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">{TITLE}</h1>
          <p className="mt-2 text-sm text-muted">
            <Link className="underline underline-offset-2" href="/postmortem-template">
              The template
            </Link>{" "}
            is easier to judge with a real incident in it. These two are public, unusually well documented by the
            company that ran them, and checkable by anyone with the links.
          </p>
        </div>

        {section(
          0,
          <>
            <h2 className={h2}>What this is, and isn&apos;t</h2>
            <p className={p}>
              This page was assembled by hand from Cloudflare&apos;s two published incident reports. Nothing here
              is drafted by our tool, and nothing is paraphrased: each field of the template is filled only with
              a sentence quoted verbatim from the report and linked back to it. Where the report doesn&apos;t
              state something the template asks for, the field says so instead of filling the gap.
            </p>
            <p className={p}>
              It is not an independent analysis of Cloudflare, and it doesn&apos;t imply Cloudflare uses this
              product. It is their account, in this shape. For what the tool itself produces, unedited, see{" "}
              <Link className="underline underline-offset-2" href="/blog/github-outage-demo">
                the GitHub outage demo
              </Link>
              .
            </p>
          </>,
        )}

        {INCIDENTS.map((incident, i) => (
          <IncidentSection key={incident.slug} incident={incident} index={i + 1} />
        ))}

        {section(
          INCIDENTS.length + 1,
          <>
            <h2 className={h2}>What the filled-in shape makes obvious</h2>
            <p className={p}>
              Both reports put the detection gap in plain numbers: 11:28 impact, 11:31 first automated detection
              in November; 08:47 deploy, 08:50 declared in December. Both name the thing that stopped the impact
              (a restored file; a revert) separately from the thing that caused it. And in November, the first
              ninety minutes of investigation went to Workers KV, which the report itself describes as the
              initial symptom rather than the trigger -- the timeline records that plainly, which is exactly what
              a timeline is for.
            </p>
            <p className={p}>
              That&apos;s the discipline the template asks of your own incidents: every claim points at a row, and a
              row nobody recorded at the time is a gap you write down rather than a story you reconstruct. If
              you&apos;d rather the citing were done for you, your{" "}
              <Link className="underline underline-offset-2" href="/">
                first incident is free
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
          <Link className="underline underline-offset-2" href="/postmortem-template">
            The template
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
