import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { SiteFooter, SiteHeader } from "../landing";

export const metadata: Metadata = {
  title: "Pricing",
  description: "PostMortem AI pricing: ₹999/month via UPI in India, or a SWIFT wire in USD/GBP/EUR internationally.",
  robots: { index: true, follow: true },
  alternates: { canonical: "/pricing" },
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type UpiInfo = { amount_inr: number; configured: boolean };
type WireCurrency = { currency: string; amount: number };
type WireInfo = { currencies: WireCurrency[]; configured: boolean };

const CURRENCY_SYMBOLS: Record<string, string> = { USD: "$", GBP: "£", EUR: "€" };

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

  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 text-center duration-700">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Pricing</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">One plan, billed monthly</h1>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted">
          Full access: unlimited incidents, evidence-grounded AI drafting, and publishing. No trial gimmicks, no
          hidden tiers.
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
                    {c.amount}
                    <span className="text-sm font-normal text-muted"> /mo ({c.currency})</span>
                  </div>
                ))
              ) : (
                <div className="text-3xl font-semibold text-ink">—</div>
              )}
            </div>
            {wireUnreachable ? (
              <p className="mt-2 text-sm text-muted">Couldn&apos;t load pricing just now -- try refreshing.</p>
            ) : (
              <p className="mt-2 text-sm text-muted">Pay via international SWIFT wire. Same manual, human-approved process.</p>
            )}
          </div>
        </div>
      </div>

      <p className="mt-6 text-center text-sm text-muted">
        No card required, no auto-renewal surprise -- payment is a manual, human-reviewed step every time. See{" "}
        <Link className="underline underline-offset-2" href="/docs">
          how it works
        </Link>
        .
      </p>

      <div className={cn(card, "mt-8")}>
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
