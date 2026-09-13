import type { Metadata } from "next";
import Link from "next/link";

// The branded 404. Until this existed a mistyped URL showed Next's bare
// "404: This page could not be found." with no way onward -- on a site
// whose whole pitch is that every claim points somewhere. Links go to the
// places a lost visitor actually wants; nothing is invented about why the
// page is missing.
export const metadata: Metadata = {
  title: "Page not found",
  robots: { index: false, follow: true },
};

export default function NotFound() {
  return (
    <main className="mx-auto max-w-xl px-6 py-24 text-ink">
      <div className="text-xs font-medium tracking-widest text-muted uppercase">404</div>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">There is nothing at this address.</h1>
      <p className="mt-3 text-sm leading-relaxed text-muted">
        The link may be old, or mistyped. Nothing was recorded about your visit beyond the request log every page
        writes.
      </p>
      <ul className="mt-6 space-y-2 text-sm">
        <li>
          <Link className="underline underline-offset-2" href="/">
            Home &mdash; PostMortem AI and your dashboard
          </Link>
        </li>
        <li>
          <Link className="underline underline-offset-2" href="/airlock">
            Airlock &mdash; the prompt-injection guard, live scanner and benchmark
          </Link>
        </li>
        <li>
          <Link className="underline underline-offset-2" href="/docs">
            Docs &mdash; the API reference and how it works
          </Link>
        </li>
        <li>
          <Link className="underline underline-offset-2" href="/pricing">
            Pricing
          </Link>
        </li>
        <li>
          <Link className="underline underline-offset-2" href="/status">
            Status
          </Link>
        </li>
      </ul>
    </main>
  );
}
