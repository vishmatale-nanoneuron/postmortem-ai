import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Pricing — PostMortem AI",
  description: "PostMortem AI pricing: ₹999/month via UPI in India, or a SWIFT wire in USD/GBP/EUR internationally.",
  robots: { index: true, follow: true },
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type UpiInfo = { amount_inr: number; configured: boolean };
type WireCurrency = { currency: string; amount: number };
type WireInfo = { currencies: WireCurrency[]; configured: boolean };

const CURRENCY_SYMBOLS: Record<string, string> = { USD: "$", GBP: "£", EUR: "€" };

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

const card = "rounded-lg border border-line bg-white p-6 shadow-sm";

export default async function PricingPage() {
  const [upi, wire] = await Promise.all([
    fetchJson<UpiInfo>("/v1/billing/upi/pricing"),
    fetchJson<WireInfo>("/v1/billing/wire/pricing"),
  ]);

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8 text-center">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Pricing</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">One plan, billed monthly</h1>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted">
          Full access: unlimited incidents, evidence-grounded AI drafting, and publishing. No trial gimmicks, no
          hidden tiers.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className={card}>
          <div className="text-xs font-medium tracking-wide text-muted uppercase">India</div>
          <div className="mt-1 text-3xl font-semibold text-ink">
            {upi?.configured ? `₹${upi.amount_inr}` : "—"}
            <span className="text-base font-normal text-muted">/mo</span>
          </div>
          <p className="mt-2 text-sm text-muted">Pay via UPI. Submit your transaction reference and get approved within the day.</p>
        </div>

        <div className={card}>
          <div className="text-xs font-medium tracking-wide text-muted uppercase">International</div>
          <div className="mt-1 space-y-1">
            {wire?.configured && wire.currencies.length > 0 ? (
              wire.currencies.map((c) => (
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
          <p className="mt-2 text-sm text-muted">Pay via international SWIFT wire. Same manual, human-approved process.</p>
        </div>
      </div>

      <p className="mt-6 text-center text-sm text-muted">
        No card required, no auto-renewal surprise -- payment is a manual, human-reviewed step every time. See{" "}
        <Link className="underline underline-offset-2" href="/docs">
          how it works
        </Link>
        .
      </p>

      <p className="mt-8 text-center">
        <a
          href="/#get-started"
          className="inline-block rounded-md bg-ink px-6 py-2.5 text-sm font-medium text-paper transition hover:bg-ink/90"
        >
          Get started
        </a>
      </p>
    </main>
  );
}
