// The one place the frontend knows a price. These mirror the backend's
// settings defaults (apps/api/app/settings.py: AIRLOCK_PACK_*) and are
// used only when the live /v1/airlock/pricing fetch fails at render time,
// so the page never shows an empty pricing section -- and never a number
// the backend would not itself quote. tests/airlock-page.test.ts reads
// settings.py and fails if these drift.
export const AIRLOCK_PRICING_DEFAULTS = {
  scans_per_pack: 10_000,
  max_packs_per_claim: 10,
  credits_per_scan: 1,
  credits_per_deep_scan: 5,
  // Proxy fetch: the fetch plus the scan (apps/api/app/airlock/proxy.py).
  credits_per_proxy_fetch: 2,
  prices: [
    { currency: "INR", amount: 999, method: "upi", configured: true },
    { currency: "USD", amount: 15, method: "wire", configured: true },
    { currency: "GBP", amount: 12, method: "wire", configured: true },
    { currency: "EUR", amount: 14, method: "wire", configured: true },
  ],
} as const;

export const CURRENCY_SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", GBP: "£", EUR: "€" };

export function formatMoney(currency: string, amount: number): string {
  return `${CURRENCY_SYMBOLS[currency] ?? currency + " "}${amount.toLocaleString("en-US")}`;
}
