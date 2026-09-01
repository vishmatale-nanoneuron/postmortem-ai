import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type PublicStatusPage = {
  incident_title: string;
  severity: string;
  status: string;
  updates: { message: string; created_at: number }[];
};

async function fetchStatusPage(slug: string): Promise<PublicStatusPage | null> {
  try {
    // Deliberately no-store, not a revalidate window -- this is the one
    // page on the whole site where staleness of even a few minutes is the
    // actual failure mode (someone checking "is it down right now" during
    // a real incident), the same reasoning /status uses for its own
    // backend health check.
    const response = await fetch(`${API_BASE}/v1/postmortems/status-page/${encodeURIComponent(slug)}`, {
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as PublicStatusPage;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const page = await fetchStatusPage(slug);
  if (!page) return { title: "Status page not found", robots: { index: false, follow: false } };
  const title = `${page.incident_title} — Status`;
  return {
    title,
    // Deliberately not indexed -- a live incident status page is
    // transient by nature and shouldn't outlive the incident in search
    // results, unlike a published postmortem, which is meant to be a
    // permanent, citable record.
    robots: { index: false, follow: false },
  };
}

export default async function StatusPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const page = await fetchStatusPage(slug);
  if (!page) notFound();

  const isResolved = page.status === "resolved";

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 animate-in fade-in slide-in-from-bottom-2 duration-700">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Status -- {page.severity}</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">{page.incident_title}</h1>
      </div>

      <div
        className={cn(
          "mb-4 flex items-center gap-3 rounded-lg border p-5 shadow-sm",
          isResolved ? "border-accent/30 bg-accent/5" : "border-red-200 bg-red-50",
        )}
      >
        <span aria-hidden className={cn("size-3 shrink-0 rounded-full", isResolved ? "bg-accent" : "bg-red-600")} />
        <div className={cn("text-base font-semibold", isResolved ? "text-accent" : "text-red-700")}>
          {isResolved ? "Resolved" : "Investigating"}
        </div>
      </div>

      {page.updates.length === 0 ? (
        <p className="text-sm text-muted">No updates posted yet.</p>
      ) : (
        <ul className="space-y-3">
          {page.updates.map((update) => (
            <li key={update.created_at} className="rounded-lg border border-line bg-white p-4 shadow-sm">
              <p className="text-sm text-ink">{update.message}</p>
              <p className="mt-1 text-xs text-muted">{new Date(update.created_at).toLocaleString()}</p>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-6 text-xs text-muted">
        <Link className="underline underline-offset-2" href="/">
          Powered by PostMortem AI
        </Link>
      </p>
    </main>
  );
}
