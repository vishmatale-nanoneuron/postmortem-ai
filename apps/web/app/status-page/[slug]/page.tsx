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

// This is the one page on the site most likely to be hit *during* a real
// backend problem -- its own reason for existing is "someone checking is
// it down right now during a real incident," and a real incident is
// exactly when backend/database load is most likely to cause a transient
// failure here. Collapsing "genuinely no such status page" and "backend
// briefly unreachable" into the same notFound() meant the worst possible
// moment for a worried customer -- a live incident -- was also the moment
// this page was most likely to falsely tell them it doesn't exist.
type FetchResult = { status: "found"; data: PublicStatusPage } | { status: "not_found" } | { status: "unreachable" };

async function fetchStatusPage(slug: string): Promise<FetchResult> {
  try {
    // Deliberately no-store, not a revalidate window -- this is the one
    // page on the whole site where staleness of even a few minutes is the
    // actual failure mode (someone checking "is it down right now" during
    // a real incident), the same reasoning /status uses for its own
    // backend health check.
    const response = await fetch(`${API_BASE}/v1/postmortems/status-page/${encodeURIComponent(slug)}`, {
      cache: "no-store",
    });
    if (response.status === 404) return { status: "not_found" };
    if (!response.ok) return { status: "unreachable" };
    return { status: "found", data: (await response.json()) as PublicStatusPage };
  } catch {
    return { status: "unreachable" };
  }
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const result = await fetchStatusPage(slug);
  if (result.status === "not_found") return { title: "Status page not found", robots: { index: false, follow: false } };
  if (result.status === "unreachable") return { title: "Status", robots: { index: false, follow: false } };
  const title = `${result.data.incident_title} — Status`;
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
  const result = await fetchStatusPage(slug);
  if (result.status === "not_found") notFound();
  if (result.status === "unreachable") {
    return (
      <main className="mx-auto max-w-2xl px-4 py-10">
        <div className="rounded-lg border border-line bg-white p-6 text-center shadow-sm">
          <p className="text-sm text-ink">Couldn&apos;t load this status page just now -- try refreshing.</p>
        </div>
      </main>
    );
  }
  const page = result.data;

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
