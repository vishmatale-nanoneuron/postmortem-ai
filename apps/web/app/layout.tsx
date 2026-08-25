import type { Metadata } from "next";
import "./globals.css";

const TITLE = "PostMortem AI";
const DESCRIPTION =
  "Record incident evidence and generate AI-drafted postmortems where every claim is grounded to a cited evidence entry -- unsupported claims are marked, never invented. Publish only after a named human approves.";

export const metadata: Metadata = {
  metadataBase: new URL("https://www.nanoneuron.ai"),
  title: { default: TITLE, template: "%s — PostMortem AI" },
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  alternates: { canonical: "/" },
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
  offers: {
    "@type": "Offer",
    price: "999",
    priceCurrency: "INR",
    url: "https://www.nanoneuron.ai/pricing",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <script
          type="application/ld+json"
          // eslint-disable-next-line react/no-danger -- static, hardcoded JSON, no user input
          dangerouslySetInnerHTML={{ __html: JSON.stringify(STRUCTURED_DATA) }}
        />
      </head>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
