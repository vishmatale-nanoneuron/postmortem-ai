import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";

const TITLE = "Terms";
const DESCRIPTION = "How PostMortem AI's subscription, cancellation, and content ownership actually work.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  alternates: { canonical: "/terms" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: "https://www.nanoneuron.ai/terms",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: TITLE }],
  },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION, images: ["/opengraph-image"] },
};

const card = "rounded-lg border border-line bg-white p-5 shadow-sm mb-4";
const h2 = "mb-2 text-lg font-semibold text-ink";
const p = "text-sm text-muted leading-relaxed mb-2";

function section(index: number, children: React.ReactNode) {
  return (
    <div
      style={{ animationDelay: `${index * 70}ms` }}
      className="mb-4 animate-in fade-in slide-in-from-bottom-2 fill-mode-backwards duration-700"
    >
      <section className={cn(card, "mb-0")}>{children}</section>
    </div>
  );
}

export default function TermsPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 duration-700">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Terms</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">How this actually works</h1>
        <p className="mt-2 text-sm text-muted">
          A single-developer product, not a company with a legal department -- this describes real behavior, not a
          template. See{" "}
          <Link className="underline underline-offset-2" href="/privacy">
            privacy
          </Link>{" "}
          for what&apos;s stored, and{" "}
          <a className="underline underline-offset-2" href="mailto:vish.matale@gmail.com">
            email directly
          </a>{" "}
          with any question before relying on anything here.
        </p>
      </div>

      {section(
        0,
        <>
          <h2 className={h2}>The service</h2>
          <p className={p}>
            One incident is fully usable for free -- recording evidence, AI drafting, everything but publishing.
            Publishing a postmortem, or creating a second incident, requires an active subscription. Content is
            AI-assisted, never autonomous: a draft is never published without a named human clicking approve, and
            the database itself enforces that, not just this page&apos;s promise.
          </p>
        </>,
      )}

      {section(
        1,
        <>
          <h2 className={h2}>Your content</h2>
          <p className={p}>
            You own the incident evidence and postmortems you create. Making a published postmortem public is your
            own explicit choice, reversible at any time from that incident&apos;s settings. Evidence and drafts you
            keep private are never shown to anyone but you.
          </p>
        </>,
      )}

      {section(
        2,
        <>
          <h2 className={h2}>Billing and cancellation</h2>
          <p className={p}>
            Card subscriptions (via Stripe) can be cancelled anytime from the Stripe customer portal, linked from
            your account settings -- self-serve, no email required. Manual UPI/wire payments are reviewed and
            approved by the founder directly; to cancel a pending manual claim before it&apos;s approved, use the
            withdraw option on that claim, or email directly. There is no automated refund system for manual
            payments -- if something goes wrong with one, email directly and it will be handled personally, not by
            a policy document promising a specific outcome in advance.
          </p>
        </>,
      )}

      {section(
        3,
        <>
          <h2 className={h2}>No warranty of fitness for any particular purpose</h2>
          <p className={p}>
            This is an active, single-developer product under continued development, not a finished commercial
            product with support-level guarantees. The grounding mechanism (every claim cited or marked
            unsupported) is real and verified -- see{" "}
            <Link className="underline underline-offset-2" href="/blog/grounding-mechanism">
              how it works
            </Link>{" "}
            -- but a postmortem it drafts is a starting point for your own review, not a substitute for it.
          </p>
        </>,
      )}

      {section(
        4,
        <>
          <h2 className={h2}>Changes</h2>
          <p className={p}>
            If these terms change in a way that matters, it&apos;ll be reflected here and, for anything affecting an
            active subscription, communicated by email -- not silently updated with no notice.
          </p>
        </>,
      )}

      <p className="mt-6 text-xs text-muted">
        <Link className="underline underline-offset-2" href="/">
          Back to PostMortem AI
        </Link>
      </p>
    </main>
  );
}
