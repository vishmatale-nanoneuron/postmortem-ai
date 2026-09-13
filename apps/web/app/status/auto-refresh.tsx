"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { usePolling } from "../use-polling";

// Keeps the status page a live view rather than a snapshot: re-runs the
// server-side checks every `seconds` while the tab is visible (and on
// returning to it), by asking Next.js to re-render the route. The page
// itself stays a server component with `cache: "no-store"` fetches, so
// what a refresh shows is what is true at that moment.
export function AutoRefresh({ seconds }: { seconds: number }) {
  const router = useRouter();
  const [remaining, setRemaining] = useState(seconds);

  usePolling(() => {
    router.refresh();
    setRemaining(seconds);
  }, seconds * 1000);

  useEffect(() => {
    const id = window.setInterval(() => setRemaining((r) => (r > 1 ? r - 1 : r)), 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <span className="font-mono text-xs text-muted" aria-live="off">
      re-checking in {remaining}s
    </span>
  );
}
