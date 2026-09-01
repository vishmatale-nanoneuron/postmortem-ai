import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { SiteFooter, SiteHeader } from "../../landing";

export const metadata: Metadata = {
  title: "What our tool drafted from a real public outage",
  description:
    "We fed the public facts of GitHub's August 17, 2026 outage into PostMortem AI and published the real, unedited output -- a concrete demonstration of the grounding mechanism, not a claim of being better than anyone's official writeup.",
  robots: { index: true, follow: true },
  alternates: { canonical: "/blog/github-outage-demo" },
};

const card = "rounded-lg border border-line bg-white p-5 shadow-sm mb-4";
const h2 = "mb-2 text-lg font-semibold text-ink";
const p = "text-sm text-muted leading-relaxed mb-2";
const mono = "font-mono text-[13px] leading-relaxed text-ink";

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

const evidence = [
  {
    source: "alert",
    summary: "GitHub confirmed a global outage at 13:40 UTC",
    detail:
      "Peak error rate ~20% across web/API traffic, ~50% on archive downloads and raw repository content. Capacity failure in Central US region cascaded through authentication, Actions, APIs, pull requests, issues, and Copilot.",
  },
  {
    source: "log",
    summary: "Copilot Token Service traffic spiked roughly 10x normal",
    detail:
      "Normally handles 7,000-9,000 requests/sec; during the incident this rose to 70,000-100,000 requests/sec. When auth token refreshes timed out, the VS Code extension's client-side retry logic did not back off, entering a tight unthrottled retry loop that amplified load during recovery.",
  },
  {
    source: "human_note",
    summary: "Core services mitigated by 16:59 UTC",
    detail:
      "Copilot authentication continued failing intermittently into the evening after core services were mitigated. Total core outage duration approximately 3.5 hours from confirmation to mitigation.",
  },
];

export default function GithubOutageDemoPost() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 duration-700">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Demo</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">
          What our tool drafted from a real public outage
        </h1>
        <p className="mt-2 text-sm text-muted">
          Not a claim that this beats anyone&apos;s official postmortem. A concrete demonstration of{" "}
          <Link className="underline underline-offset-2" href="/blog/grounding-mechanism">
            the grounding mechanism
          </Link>{" "}
          on an incident you can independently check, instead of a fabricated example.
        </p>
      </div>

      {section(
        0,
        <>
          <h2 className={h2}>The source</h2>
          <p className={p}>
            GitHub had a real, widely reported outage on August 17, 2026. We don&apos;t have GitHub&apos;s own
            official postmortem to cite here, so the facts below come from third-party reporting, not GitHub
            directly — treat them as illustrative, not authoritative, and check the original reporting yourself if
            you want the full picture:
          </p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
            <li>
              <a
                className="underline underline-offset-2"
                href="https://www.digitalapplied.com/blog/github-august-17-outage-postmortem-retry-amplification"
                target="_blank"
                rel="noopener noreferrer"
              >
                digitalapplied.com — &ldquo;GitHub&apos;s Outage Postmortem: Client Retries Made It Worse&rdquo;
              </a>
            </li>
            <li>
              <a
                className="underline underline-offset-2"
                href="https://www.explainx.ai/blog/github-august-17-outage-root-cause-reliability-2026"
                target="_blank"
                rel="noopener noreferrer"
              >
                explainx.ai — &ldquo;GitHub Outage Aug 17: 7h47m, 2.9B Commits, RCA&rdquo;
              </a>
            </li>
          </ul>
        </>,
      )}

      {section(
        1,
        <>
          <h2 className={h2}>What we gave it</h2>
          <p className={p}>
            Three evidence entries, transcribed from the reporting above — the same generic shape (source type,
            summary, detail, timestamp) any real account uses, nothing GitHub-specific about the schema:
          </p>
          {evidence.map((e, i) => (
            <div key={e.summary} className="mt-2.5 rounded-md bg-paper px-3.5 py-3">
              <p className="mb-1 text-xs font-medium text-accent">
                [{i + 1}] {e.source}
              </p>
              <p className={mono}>
                {e.summary}
                {e.detail ? ` — ${e.detail}` : ""}
              </p>
            </div>
          ))}
        </>,
      )}

      {section(
        2,
        <>
          <h2 className={h2}>What it drafted — real, unedited output</h2>
          <p className={p}>
            This is the actual JSON our production API returned for this exact evidence, copied verbatim — not
            cleaned up, not cherry-picked. Every field below traces to one of the three entries above;{" "}
            <span className="font-mono text-xs">unsupported_claims_dropped</span> came back{" "}
            <span className="font-mono text-xs">0</span> because the model didn&apos;t attempt anything the
            evidence didn&apos;t support.
          </p>
          <div className="mt-2.5 space-y-3">
            <div>
              <p className="text-xs font-medium text-muted uppercase">Summary</p>
              <p className={cn(mono, "mt-1")}>
                A global outage was confirmed at 13:40 UTC, impacting authentication, Actions, APIs, pull requests,
                issues, and Copilot. Peak error rates reached approximately 20% across web/API traffic and 50% on
                archive downloads and raw repository content. Core services were mitigated by 16:59 UTC, with the
                total core outage duration being approximately 3.5 hours from confirmation to mitigation. Copilot
                authentication continued to experience intermittent failures into the evening after core services
                were mitigated.
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-muted uppercase">Root cause</p>
              <p className={cn(mono, "mt-1")}>The incident was caused by a capacity failure in the Central US region.</p>
            </div>
            <div>
              <p className="text-xs font-medium text-muted uppercase">Detection</p>
              <p className={cn(mono, "mt-1")}>GitHub confirmed a global outage at 13:40 UTC.</p>
            </div>
            <div>
              <p className="text-xs font-medium text-muted uppercase">Resolution</p>
              <p className={cn(mono, "mt-1")}>
                Core services were mitigated by 16:59 UTC, approximately 3.5 hours after confirmation of the
                outage.
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-muted uppercase">Contributing factors</p>
              <p className={cn(mono, "mt-1")}>
                The VS Code extension&apos;s client-side retry logic did not back off when authentication token
                refreshes timed out. This led to a tight unthrottled retry loop, causing Copilot Token Service
                traffic to spike roughly 10x, from a normal 7,000-9,000 requests/sec to 70,000-100,000
                requests/sec, which amplified load during recovery.
              </p>
            </div>
          </div>
        </>,
      )}

      {section(
        3,
        <>
          <h2 className={h2}>What this does and doesn&apos;t show</h2>
          <p className={p}>
            It shows the mechanism working on a real, checkable incident: every sentence above ties back to
            something in the three evidence entries, and nothing was invented — no cost estimate, no customer
            count, no fabricated timeline detail beyond what was given.
          </p>
          <p className={p}>
            It doesn&apos;t show that this output is better than GitHub&apos;s own internal postmortem, which we
            don&apos;t have and which almost certainly contains far more detail than three secondhand paragraphs
            could. A real incident inside your own team, with your own recorded evidence, is what this is actually
            built for.
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
