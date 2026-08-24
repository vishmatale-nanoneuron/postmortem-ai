import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://www.nanoneuron.ai"),
  title: "PostMortem AI",
  description:
    "Record incident evidence and generate AI-drafted postmortems where every claim is grounded to a cited evidence entry -- unsupported claims are marked, never invented. Publish only after a named human approves.",
  robots: { index: true, follow: true },
  openGraph: {
    title: "PostMortem AI",
    description:
      "Evidence-grounded incident postmortem drafting. Every claim cites real recorded evidence; unsupported claims are marked, never fabricated.",
    url: "https://www.nanoneuron.ai",
    siteName: "PostMortem AI",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
