import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { SiteFooter, SiteHeader } from "../landing";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "PostMortem AI pricing: ₹999/month or ₹9,990/year via UPI in India, or a SWIFT wire in USD/GBP/EUR internationally. Pay annually and two months are free.",
  robots: { index: true, follow: true },
  alternates: { canonical: "/pricing" },
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

// amount_*_annual are served by both pricing endpoints and were being
// discarded here: these types omitted the fields entirely, so the annual plan
// -- fully built in the backend (BillingPeriod, annual_price(), migration
// 0029's billing_period column) -- was unbuyable, because nothing ever showed
// it to a customer.
type UpiInfo = { amount_inr: number; amount_inr_annual: number; configured: boolean };
type WireCurrency = { currency: string; amount: number; amount_annual: number };
type WireInfo = { currencies: WireCurrency[]; configured: boolean };

const CURRENCY_SYMBOLS: Record<string, string> = { USD: "$", GBP: "£", EUR: "€" };

// Sourced only from facts already stated elsewhere on this page and in
// llms.txt -- nothing invented for the sake of having an FAQ. Rendered as
// real, visible page content below (Google's FAQPage rich-result
// eligibility requires the marked-up text to actually appear on the
// page, not just exist in the schema) and mirrored verbatim into the
// JSON-LD script tag in the component -- keep the two in sync if either
// changes.
const FAQ: { question: string; answer: string }[] = [
  {
    question: "Is there a free trial?",
    answer:
      "Not for new accounts -- an active subscription is required from your first incident. (A small number of legacy accounts that used a free incident before this policy took effect keep what they already had.)",
  },
  {
    question: "Can I pay annually?",
    answer:
      "Yes -- an annual payment is charged for ten months, so two months are free. If you are paying by international SWIFT wire, annual is strongly recommended: a wire costs the sender roughly USD 15-40 in bank fees, which is more than a single month's subscription, so paying monthly by wire means a surcharge larger than the thing you're buying.",
  },
  {
    question: "How do I get the UPI ID or bank account details to pay?",
    answer:
      "Request them from your account settings once signed in -- they're emailed directly to your own registered address. No need to contact the founder first just to find out how to pay.",
  },
  {
    question: "What happens after I submit a payment reference?",
    answer:
      "The founder reviews and approves it personally, usually within the day. Access activates the moment it's approved, not before.",
  },
  {
    question: "What if I'm not happy after subscribing?",
    answer:
      "Email vish.matale@gmail.com within 14 days of your first charge and it's refunded -- the founder processes it personally, the same review as approving a payment in the first place.",
  },
  {
    question: "Does this support teams or organizations?",
    answer: "Not yet -- each account is a single user's own incidents, not a shared organization.",
  },
];

// Two genuinely different outcomes were both collapsing into the same "—"
// before this: the backend saying "this payment method isn't offered" and
// this fetch simply failing (a transient network blip, a cold start, the
// API briefly unreachable). UPI and wire are this app's actual live,
// working payment rails -- the realistic failure mode on this exact page
// (the one a real prospect is looking at right before deciding to pay) is
// "couldn't reach the backend just now," not "this was never offered."
// Telling those apart means a transient blip reads as "try again," not as
// "this product doesn't take your money," which is what a bare "—" would
// have implied.
type FetchResult<T> = { status: "ok"; data: T } | { status: "unreachable" };

async function fetchJson<T>(path: string): Promise<FetchResult<T>> {
  try {
    // UPI/wire pricing changes rarely (a manual env-var update, not a
    // per-request value) -- `cache: "no-store"` forced a real cross-service
    // network round-trip to the FastAPI backend on every single visit to
    // this exact page, the one a prospect hits right before deciding to
    // pay. 5-minute revalidation (matching the public postmortem pages'
    // own caching window) makes repeat visits near-instant while still
    // picking up a real pricing change within minutes, not next deploy.
    const response = await fetch(`${API_BASE}${path}`, { next: { revalidate: 300 } });
    if (!response.ok) return { status: "unreachable" };
    return { status: "ok", data: (await response.json()) as T };
  } catch {
    return { status: "unreachable" };
  }
}

const card = "rounded-lg border border-line bg-white p-6 shadow-sm";

export default async function PricingPage() {
  const [upi, wire] = await Promise.all([
    fetchJson<UpiInfo>("/v1/billing/upi/pricing"),
    fetchJson<WireInfo>("/v1/billing/wire/pricing"),
  ]);

  const upiUnreachable = upi.status === "unreachable";
  const wireUnreachable = wire.status === "unreachable";

  // Mirrors FAQ above exactly -- same reasoning as layout.tsx's own
  // STRUCTURED_DATA: static, hardcoded JSON with no user input, safe
  // despite dangerouslySetInnerHTML.
  const faqStructuredData = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: FAQ.map((item) => ({
      "@type": "Question",
      name: item.question,
      acceptedAnswer: { "@type": "Answer", text: item.answer },
    })),
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqStructuredData) }}
      />
      <SiteHeader />
      <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 text-center duration-700">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Pricing</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">One plan, monthly or annual</h1>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted">
          Full access: unlimited incidents, evidence-grounded AI drafting, and publishing. No trial gimmicks, no
          hidden tiers. Pay annually and two months are free.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="tilt-card-wrap animate-in fade-in slide-in-from-bottom-3 delay-100 fill-mode-backwards duration-700">
          <div tabIndex={0} className={cn(card, "tilt-card")}>
            <div className="text-xs font-medium tracking-wide text-muted uppercase">India</div>
            <div className="mt-1 text-3xl font-semibold text-ink">
              {upi.status === "ok" && upi.data.configured ? `₹${upi.data.amount_inr}` : "—"}
              <span className="text-base font-normal text-muted">/mo</span>
            </div>
            {upi.status === "ok" && upi.data.configured && upi.data.amount_inr_annual > 0 ? (
              <div className="mt-1 text-sm text-muted">
                or <span className="font-semibold text-ink">₹{upi.data.amount_inr_annual}</span>/year
                <span className="text-verified"> -- two months free</span>
              </div>
            ) : null}
            {upiUnreachable ? (
              <p className="mt-2 text-sm text-muted">Couldn&apos;t load pricing just now -- try refreshing.</p>
            ) : (
              <p className="mt-2 text-sm text-muted">Pay via UPI. Submit your transaction reference and get approved within the day.</p>
            )}
          </div>
        </div>

        <div className="tilt-card-wrap animate-in fade-in slide-in-from-bottom-3 delay-200 fill-mode-backwards duration-700">
          <div tabIndex={0} className={cn(card, "tilt-card")}>
            <div className="text-xs font-medium tracking-wide text-muted uppercase">International</div>
            <div className="mt-1 space-y-1">
              {wire.status === "ok" && wire.data.configured && wire.data.currencies.length > 0 ? (
                wire.data.currencies.map((c) => (
                  <div key={c.currency} className="text-lg font-semibold text-ink">
                    {CURRENCY_SYMBOLS[c.currency] ?? `${c.currency} `}
                    {c.amount_annual > 0 ? c.amount_annual : c.amount}
                    <span className="text-sm font-normal text-muted">
                      {c.amount_annual > 0 ? ` /year (${c.currency})` : ` /mo (${c.currency})`}
                    </span>
                    {c.amount_annual > 0 ? (
                      <span className="ml-1 text-sm font-normal text-muted">
                        or {CURRENCY_SYMBOLS[c.currency] ?? `${c.currency} `}
                        {c.amount}/mo
                      </span>
                    ) : null}
                  </div>
                ))
              ) : (
                <div className="text-3xl font-semibold text-ink">—</div>
              )}
            </div>
            {wireUnreachable ? (
              <p className="mt-2 text-sm text-muted">Couldn&apos;t load pricing just now -- try refreshing.</p>
            ) : (
              // Annual is shown first here on purpose, and it is not a
              // discount play: a SWIFT wire costs the sender roughly USD 15-40
              // in fees, so paying a ~USD 15 monthly subscription by wire means
              // a >100% surcharge every month. Annual is the only version of
              // this rail that is economically sane for an international
              // customer, which is exactly why migration 0029 added it.
              <p className="mt-2 text-sm text-muted">
                Pay via international SWIFT wire. Annual is recommended -- wire fees make a monthly transfer cost more
                than the subscription. Same manual, human-approved process.
              </p>
            )}
          </div>
        </div>
      </div>

      <p className="mt-6 text-center text-sm text-muted">
        No card required, no auto-renewal surprise -- payment is a manual, human-reviewed step every time. Paying
        annually makes that once a year instead of twelve. See{" "}
        <Link className="underline underline-offset-2" href="/docs">
          how it works
        </Link>
        .
      </p>

      {/* Anchor target for the footer's "Sales and Refunds" link -- it points
          here rather than at a separate page, so there is exactly one copy of
          the refund terms and no chance of two versions disagreeing.
          scroll-mt clears the sticky header when jumped to. */}
      <div id="refunds" className={cn(card, "mt-8 scroll-mt-24")}>
        <div className="text-xs font-medium tracking-wide text-muted uppercase">14-day refund</div>
        <p className="mt-2 text-sm text-muted">
          Not happy? Email{" "}
          <a className="underline underline-offset-2" href="mailto:vish.matale@gmail.com">
            vish.matale@gmail.com
          </a>{" "}
          within 14 days of your first charge and you get it back -- the founder reviews and processes it
          personally, same as approving a payment.
        </p>
      </div>

      <div className="mt-8">
        <h2 className="mb-3 text-center text-xs font-medium tracking-widest text-muted uppercase">
          Frequently asked
        </h2>
        <div className="space-y-3">
          {FAQ.map((item) => (
            <div key={item.question} className={card}>
              <div className="text-sm font-medium text-ink">{item.question}</div>
              <p className="mt-1.5 text-sm text-muted">{item.answer}</p>
            </div>
          ))}
        </div>
      </div>

      <p className="mt-8 text-center">
        <Link
          href="/#get-started"
          className="inline-block rounded-md bg-ink px-6 py-2.5 text-sm font-medium text-paper transition-[transform,background-color] duration-200 hover:-translate-y-0.5 hover:bg-ink/90"
        >
          Get started
        </Link>
      </p>
      </main>
      <SiteFooter />
    </>
  );
}
