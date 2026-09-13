import { Skeleton } from "@/components/ui/skeleton";

// Shown while the server render of /airlock waits on the backend for the
// live price and the decision counters. A skeleton in the page's own
// shape rather than a spinner, so the layout does not jump when the real
// content arrives.
export default function Loading() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-10" aria-busy aria-label="Loading Airlock">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="mt-3 h-9 w-3/4" />
      <Skeleton className="mt-3 h-4 w-full" />
      <Skeleton className="mt-2 h-4 w-5/6" />
      <div className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
      </div>
      <Skeleton className="mt-8 h-48 w-full" />
    </main>
  );
}
