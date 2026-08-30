import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";

const TITLE = "Privacy";
const DESCRIPTION = "What PostMortem AI actually stores, who it's shared with, and how to delete it.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  alternates: { canonical: "/privacy" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: "https://www.nanoneuron.ai/privacy",
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

export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 duration-700">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Privacy</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">What&apos;s actually stored</h1>
        <p className="mt-2 text-sm text-muted">
          Written to match the real running code, the same standard as{" "}
          <Link className="underline underline-offset-2" href="/docs">
            /docs
          </Link>{" "}
          -- not template legal boilerplate. This is a single-developer product; if something here is unclear,{" "}
          <a className="underline underline-offset-2" href="mailto:vish.matale@gmail.com">
            email directly
          </a>
          .
        </p>
      </div>

      {section(
        0,
        <>
          <h2 className={h2}>What you give us</h2>
          <p className={p}>
            An email address and password (hashed, never stored or logged in plain text) to create an account.
            Whatever incident evidence you record -- alerts, logs, deploy notes, human notes, customer reports --
            and the postmortems drafted from it. If you submit a manual UPI or wire payment, a transaction
            reference. Nothing else is asked for.
          </p>
        </>,
      )}

      {section(
        1,
        <>
          <h2 className={h2}>What third parties see</h2>
          <p className={p}>
            Your incident evidence is sent to Google (Gemini) to draft a postmortem, and to Anthropic (Claude) only
            if Gemini&apos;s own call fails and a fallback is configured. Card payments go through Stripe directly
            -- your card details never reach our own servers. Password-reset emails are sent via Resend, which
            sees only the email address and the reset link, nothing about your incidents. The database itself is
            hosted by Supabase, the application by Vercel. None of these are chosen or paid to promote your data
            further -- they process it only to do the specific job listed here.
          </p>
        </>,
      )}

      {section(
        2,
        <>
          <h2 className={h2}>What we never do</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
            <li>Never sell or share your data with advertisers or data brokers -- there is no such relationship to begin with.</li>
            <li>Never expose your email address on a published, publicly-shared postmortem page -- confirmed directly in the API response shape, not just a policy statement.</li>
            <li>Never make an incident public without you explicitly turning that on -- publishing and public visibility are separate, deliberate actions.</li>
          </ul>
        </>,
      )}

      {section(
        3,
        <>
          <h2 className={h2}>Deleting your account</h2>
          <p className={p}>
            Deleting your account (from account settings) really deletes your user row, and any pending payment
            claims with it. What it does <em>not</em> delete: incidents and postmortems you already created stay on
            record, the same append-only-history stance this product applies to its own payment audit trail --
            useful if you ever need to prove what a postmortem said after the account that wrote it is gone. If you
            want those removed too, email directly and it&apos;ll be handled manually.
          </p>
        </>,
      )}

      {section(
        4,
        <>
          <h2 className={h2}>Session</h2>
          <p className={p}>
            Signing in sets one HTTP-only cookie (a signed session token) -- not read by any script on the page,
            not shared with any third-party analytics or ad script. See{" "}
            <Link className="underline underline-offset-2" href="/status">
              system status
            </Link>{" "}
            for the backend&apos;s live health.
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
