import type { Metadata } from "next";
import Link from "next/link";
import benchmark from "../benchmark.json";
import { BenchmarkSection } from "../benchmark-section";

// The benchmark's own URL. /airlock keeps the summary table and the plain
// reading of it; this page carries every miss verbatim (195 list items
// that were making /airlock's DOM the largest on the site), the rules
// that fired most, and the reproduce command. Built from the same
// committed results file, pinned to the engine by tests.

const data = benchmark as { dataset: string; overall: { recall: number | null; false_positive_rate: number | null; rows: number } };

export const metadata: Metadata = {
  title: "Airlock benchmark — recall, false positives and every miss",
  description: `The Airlock rule engine on ${data.dataset} (${data.overall.rows} labelled texts): recall ${((data.overall.recall ?? 0) * 100).toFixed(1)}%, false-positive rate ${((data.overall.false_positive_rate ?? 0) * 100).toFixed(1)}%, every miss listed verbatim, reproducible from the public repository.`,
  alternates: { canonical: "/airlock/benchmark" },
};

export default function BenchmarkPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-10 text-ink">
      <nav className="mb-4 text-xs text-muted" aria-label="Breadcrumb">
        <Link className="underline underline-offset-2" href="/airlock">
          Airlock
        </Link>{" "}
        / Benchmark
      </nav>
      <BenchmarkSection h2="text-3xl font-semibold tracking-tight mb-3" full />
      <p className="mt-6 text-sm text-muted">
        <Link className="underline underline-offset-2" href="/airlock/rules">
          Every rule, in the open
        </Link>{" "}
        ·{" "}
        <Link className="underline underline-offset-2" href="/airlock#try-it">
          Try it on your own text
        </Link>
      </p>
    </main>
  );
}
