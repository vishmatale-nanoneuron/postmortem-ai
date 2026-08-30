import type { Metadata } from "next";
import Link from "next/link";
import { CtaBanner } from "./cta-banner";

const TITLE = "Published postmortems";
const DESCRIPTION = "Publicly shared, evidence-grounded incident postmortems.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  alternates: { canonical: "/postmortems" },
  // Defining `openGraph` here replaces the root layout's entirely (Next.js
  // doesn't deep-merge it across segments) -- previously this page defined
  // no openGraph object at all, so it inherited none of the parent's,
  // which for `og:title`/`og:description` meant a link to this page shared
  // anywhere showed the homepage's own generic title, not this page's.
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: "https://www.nanoneuron.ai/postmortems",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: TITLE }],
  },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION, images: ["/opengraph-image"] },
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type PublicPostmortem = { slug: string; incident_title: string; severity: string; summary: string; approved_at: number | null };

async function fetchPublicPostmortems(): Promise<PublicPostmortem[]> {
  try {
    const response = await fetch(`${API_BASE}/v1/postmortems/public`, { next: { revalidate: 300 } });
    if (!response.ok) return [];
    return (await response.json()) as PublicPostmortem[];
  } catch {
    return [];
  }
}

export default async function PublicPostmortemsIndex() {
  const postmortems = await fetchPublicPostmortems();

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 duration-700">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Published postmortems</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">Incidents, transparently.</h1>
        <p className="mt-2 text-sm text-muted">
          Every one of these is grounded to its own recorded evidence -- see{" "}
          <Link className="underline underline-offset-2" href="/docs">
            how it works
          </Link>
          .
        </p>
      </div>

      <CtaBanner />

      {postmortems.length === 0 ? (
        <p className="text-sm text-muted">No public postmortems yet.</p>
      ) : (
        <ul className="space-y-3">
          {postmortems.map((item, i) => (
            <li
              key={item.slug}
              // Delay capped at 10 items' worth -- a long list shouldn't
              // make the 40th entry wait 2+ seconds to appear.
              style={{ animationDelay: `${Math.min(i, 10) * 60}ms` }}
              className="tilt-card-wrap animate-in fade-in slide-in-from-bottom-2 fill-mode-backwards duration-500"
            >
              <div className="tilt-card rounded-lg border border-line bg-white p-4 shadow-sm">
                <Link href={`/postmortems/${item.slug}`} className="text-base font-medium text-ink underline-offset-2 hover:underline">
                  {item.incident_title}
                </Link>
                <span className="ml-2 text-xs text-muted">{item.severity}</span>
                <p className="mt-1 text-sm text-muted">{item.summary}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
