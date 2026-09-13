"use client";

import Link from "next/link";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";

// The route-level error boundary: a render or data failure inside a page
// shows this instead of a blank screen, with a retry that re-renders the
// segment. The digest is Next's own id for the server-side error log; it
// is shown so a report can be matched to a log line, the same way the
// API's request id works. Nothing about the error's contents is shown --
// a stack trace is for the log, not the visitor.
export default function ErrorBoundary({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // Also reaches the browser console for anyone debugging locally.
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto max-w-xl px-6 py-24 text-ink">
      <div className="text-xs font-medium tracking-widest text-muted uppercase">Something broke</div>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">This page failed to render.</h1>
      <p className="mt-3 text-sm leading-relaxed text-muted">
        The fault is on our side, not yours, and it has been logged.
        {error.digest && (
          <>
            {" "}
            If you report it, quote <code className="rounded bg-paper px-1 font-mono text-xs">{error.digest}</code>.
          </>
        )}
      </p>
      <div className="mt-6 flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={() => reset()}>
          Try again
        </Button>
        <Link href="/" className="rounded-md border border-line px-3 py-1.5 text-xs text-ink">
          Home
        </Link>
        <Link href="/status" className="rounded-md border border-line px-3 py-1.5 text-xs text-ink">
          Status page
        </Link>
      </div>
    </main>
  );
}
