import type { Metadata } from "next";
import Workspace from "./workspace";

const TITLE = "Airlock and PostMortem AI — NanoNeuron";
const DESCRIPTION =
  "Airlock: a free, live prompt-injection and exfiltration guard for AI agents -- scores untrusted content before it reaches the model, checks outbound calls for credentials and PII, keeps an append-only audit log. PostMortem AI: incident postmortems where every claim cites recorded evidence.";

// Homepage-level only. app/layout.tsx keeps the site-wide title template and
// siteName as they were: those are what search engines have indexed for the
// product that has paying customers, and changing site identity is a
// separate decision from what leads on the front door. This block puts
// Airlock first in the tab, the search snippet and the link preview for
// "/" alone.
export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: "/" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: "https://www.nanoneuron.ai",
    type: "website",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: TITLE }],
  },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION, images: ["/opengraph-image"] },
};

export default function Home() {
  return <Workspace />;
}
