import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type PublicPostmortem = {
  slug: string;
  incident_title: string;
  severity: string;
  summary: string;
  root_cause: string;
  detection: string;
  resolution: string;
  contributing_factors: string[];
  approved_at: number | null;
  published_at: number | null;
};

async function fetchPostmortem(slug: string): Promise<PublicPostmortem | null> {
  try {
    const response = await fetch(`${API_BASE}/v1/postmortems/public/${encodeURIComponent(slug)}`, {
      next: { revalidate: 300 },
    });
    if (!response.ok) return null;
    return (await response.json()) as PublicPostmortem;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const postmortem = await fetchPostmortem(slug);
  if (!postmortem) return { title: "Postmortem not found", robots: { index: false, follow: false } };

  const title = `${postmortem.incident_title} — Postmortem`;
  return {
    title,
    description: postmortem.summary,
    robots: { index: true, follow: true },
    alternates: { canonical: `/postmortems/${slug}` },
    openGraph: { title, description: postmortem.summary, type: "article", url: `https://www.nanoneuron.ai/postmortems/${slug}` },
  };
}

const card = "rounded-lg border border-line bg-white p-5 shadow-sm mb-4";
const h2 = "mb-1.5 text-sm font-semibold tracking-wide text-muted uppercase";
const p = "text-sm text-ink leading-relaxed";

function section(index: number, children: React.ReactNode) {
  return (
    <div
      style={{ animationDelay: `${index * 90}ms` }}
      className="tilt-card-wrap mb-4 animate-in fade-in slide-in-from-bottom-2 fill-mode-backwards duration-700"
    >
      <section tabIndex={0} className={cn(card, "tilt-card mb-0")}>
        {children}
      </section>
    </div>
  );
}

export default async function PublicPostmortemPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const postmortem = await fetchPostmortem(slug);
  if (!postmortem) notFound();

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 duration-700">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Postmortem -- {postmortem.severity}</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">{postmortem.incident_title}</h1>
        {postmortem.approved_at && (
          <p className="mt-1 text-xs text-muted">Published {new Date(postmortem.approved_at).toLocaleDateString()}</p>
        )}
      </div>

      {section(
        0,
        <>
          <h2 className={h2}>Summary</h2>
          <p className={p}>{postmortem.summary}</p>
        </>,
      )}
      {section(
        1,
        <>
          <h2 className={h2}>Root cause</h2>
          <p className={p}>{postmortem.root_cause}</p>
        </>,
      )}
      {section(
        2,
        <>
          <h2 className={h2}>Detection</h2>
          <p className={p}>{postmortem.detection}</p>
        </>,
      )}
      {section(
        3,
        <>
          <h2 className={h2}>Resolution</h2>
          <p className={p}>{postmortem.resolution}</p>
        </>,
      )}
      {postmortem.contributing_factors.length > 0 &&
        section(
          4,
          <>
            <h2 className={h2}>Contributing factors</h2>
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink">
              {postmortem.contributing_factors.map((factor) => (
                <li key={factor}>{factor}</li>
              ))}
            </ul>
          </>,
        )}

      <p className="mt-6 text-xs text-muted">
        Every claim above is grounded to the recorded evidence for this incident --{" "}
        <Link className="underline underline-offset-2" href="/docs">
          how this works
        </Link>
        . Published with{" "}
        <Link className="underline underline-offset-2" href="/">
          PostMortem AI
        </Link>
        .
      </p>
    </main>
  );
}
