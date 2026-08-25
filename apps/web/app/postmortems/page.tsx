import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Published postmortems — PostMortem AI",
  description: "Publicly shared, evidence-grounded incident postmortems.",
  robots: { index: true, follow: true },
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
      <div className="mb-8">
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

      {postmortems.length === 0 ? (
        <p className="text-sm text-muted">No public postmortems yet.</p>
      ) : (
        <ul className="space-y-3">
          {postmortems.map((item) => (
            <li key={item.slug} className="rounded-lg border border-line bg-white p-4 shadow-sm">
              <Link href={`/postmortems/${item.slug}`} className="text-base font-medium text-ink underline-offset-2 hover:underline">
                {item.incident_title}
              </Link>
              <span className="ml-2 text-xs text-muted">{item.severity}</span>
              <p className="mt-1 text-sm text-muted">{item.summary}</p>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
