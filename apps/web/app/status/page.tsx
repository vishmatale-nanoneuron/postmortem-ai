import type { Metadata } from "next";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { SiteFooter, SiteHeader } from "../landing";

const TITLE = "System status";
const DESCRIPTION = "Live status of PostMortem AI's backend and database, checked in real time.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  alternates: { canonical: "/status" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: "https://www.nanoneuron.ai/status",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: TITLE }],
  },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION, images: ["/opengraph-image"] },
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type HealthCheck = { status: string; database: string } | null;

async function fetchHealth(): Promise<{ health: HealthCheck; ok: boolean; checkedAt: number }> {
  const checkedAt = Date.now();
  try {
    // cache: "no-store" is deliberate here, the one real exception to this
    // app's usual "cache what changes rarely" stance (see pricing's own
    // revalidate fix) -- a status page showing a 5-minute-stale "healthy"
    // during a real outage would be actively misleading, the opposite of
    // what this page exists for.
    const response = await fetch(`${API_BASE}/health`, { cache: "no-store" });
    const body = (await response.json().catch(() => null)) as HealthCheck;
    return { health: body, ok: response.ok, checkedAt };
  } catch {
    return { health: null, ok: false, checkedAt };
  }
}

export default async function StatusPage() {
  const { health, ok, checkedAt } = await fetchHealth();

  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 duration-700">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Status</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">{TITLE}</h1>
        <p className="mt-2 text-sm text-muted">
          A real check against the live backend and database, run the moment this page was loaded -- not a
          historical uptime chart, since no reliable one exists yet to show honestly.
        </p>
      </div>

      <div
        className={cn(
          "mb-4 flex items-center gap-3 rounded-lg border p-5 shadow-sm",
          ok ? "border-accent/30 bg-accent/5" : "border-red-200 bg-red-50",
        )}
      >
        <span
          aria-hidden
          className={cn("size-3 shrink-0 rounded-full", ok ? "bg-accent" : "bg-red-600")}
        />
        <div>
          <div className={cn("text-base font-semibold", ok ? "text-accent" : "text-red-700")}>
            {ok ? "All systems operational" : "Degraded -- something is wrong right now"}
          </div>
          <div className="text-sm text-muted">
            Backend: {ok ? "reachable" : "unreachable"}
            {health?.database && <> -- Database: {health.database}</>}
          </div>
        </div>
      </div>

      <p className="text-xs text-muted">
        Checked at {new Date(checkedAt).toISOString()}. Reload this page for a fresh check -- it is never cached.
      </p>

      <p className="mt-6 text-xs text-muted">
        <Link className="underline underline-offset-2" href="/docs">
          How this works
        </Link>{" "}
        --{" "}
        <Link className="underline underline-offset-2" href="/">
          Back to PostMortem AI
        </Link>
      </p>
      </main>
      <SiteFooter />
    </>
  );
}
