import type { Metadata } from "next";
import "./globals.css";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";

const geist = Geist({subsets:['latin'],variable:'--font-sans'});

const TITLE = "PostMortem AI";
const DESCRIPTION =
  "Record incident evidence and generate AI-drafted postmortems where every claim is grounded to a cited evidence entry -- unsupported claims are marked, never invented. Publish only after a named human approves.";

export const metadata: Metadata = {
  metadataBase: new URL("https://www.nanoneuron.ai"),
  title: { default: TITLE, template: "%s — PostMortem AI" },
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  // No blanket canonical here -- every real indexable page below sets its
  // own. A root-level default of "/" was silently applied to every page
  // that didn't override it (confirmed live: /docs, /pricing, and the new
  // /blog page were all emitting <link rel="canonical" href=".../"> --
  // telling search engines every one of them was a duplicate of the
  // homepage, not indexable content, likely suppressing them from ranking
  // independently since whenever this was first deployed). Leaving this
  // unset means a future page that forgets its own canonical gets none
  // (neutral) rather than a silently wrong one (actively harmful).
  openGraph: {
    title: TITLE,
    description:
      "Evidence-grounded incident postmortem drafting. Every claim cites real recorded evidence; unsupported claims are marked, never fabricated.",
    url: "https://www.nanoneuron.ai",
    siteName: TITLE,
    type: "website",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: TITLE }],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: ["/opengraph-image"],
  },
};

// SoftwareApplication structured data -- read by search rich results and
// AI answer engines alike. Kept in sync with llms.txt's own facts (pricing,
// what it does) rather than restating a separate marketing claim.
const STRUCTURED_DATA = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: TITLE,
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  description: DESCRIPTION,
  url: "https://www.nanoneuron.ai",
  // One offer per real payment path (verified live against
  // /v1/billing/upi/pricing and /v1/billing/wire/pricing) -- previously
  // only listed the INR/UPI price, silently omitting the USD/GBP/EUR wire
  // pricing international visitors on /pricing actually see.
  offers: [
    { "@type": "Offer", price: "999", priceCurrency: "INR", url: "https://www.nanoneuron.ai/pricing" },
    { "@type": "Offer", price: "15", priceCurrency: "USD", url: "https://www.nanoneuron.ai/pricing" },
    { "@type": "Offer", price: "12", priceCurrency: "GBP", url: "https://www.nanoneuron.ai/pricing" },
    { "@type": "Offer", price: "14", priceCurrency: "EUR", url: "https://www.nanoneuron.ai/pricing" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={cn("font-sans", geist.variable)}>
      <head>
        <script
          type="application/ld+json"
          // Static, hardcoded JSON, no user input -- safe despite dangerouslySetInnerHTML.
          dangerouslySetInnerHTML={{ __html: JSON.stringify(STRUCTURED_DATA) }}
        />
      </head>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
