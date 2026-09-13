import type { Metadata } from "next";
import Link from "next/link";
import { FAMILY, RULES, RULE_COUNT, benchmarkHits, languageOf, slugFor } from "./rule-data";

export const metadata: Metadata = {
  title: "Airlock detection rules — every rule, its family and its weight",
  description:
    "The complete rule catalogue of the Airlock prompt-injection guard: every weighted rule across eight attack families, what each one catches, and how often it fired on the public benchmark.",
  alternates: { canonical: "/airlock/rules" },
};

const p = "text-sm leading-relaxed text-muted";

export default function RulesIndex() {
  const families = Object.keys(FAMILY);
  return (
    <main className="mx-auto max-w-3xl px-6 py-10 text-ink">
      <nav className="mb-4 text-xs text-muted" aria-label="Breadcrumb">
        <Link className="underline underline-offset-2" href="/airlock">
          Airlock
        </Link>{" "}
        / Rules
      </nav>
      <div className="text-xs font-medium tracking-widest text-muted uppercase">Detection rules</div>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Every rule Airlock runs, in the open</h1>
      <p className={`mt-3 ${p}`}>
        {RULE_COUNT} weighted rules across {families.length} attack families. A rule&apos;s weight is what it contributes to
        the noisy-OR score; at 0.75 the verdict is block, at 0.40 flag. Weights of 0.75 and above are reserved for
        phrasings with no plausible benign use. The patterns themselves live in the public repository; these pages
        describe what each one catches. Any rule can be muted for your account from the dashboard policy.
      </p>
      {families.map((family) => {
        const members = RULES.filter((rule) => rule.family === family);
        return (
          <section key={family} className="mt-8" aria-labelledby={`family-${family}`}>
            <h2 id={`family-${family}`} className="text-lg font-semibold">
              {FAMILY[family]!.name} <span className="font-normal text-muted">· {members.length}</span>
            </h2>
            <p className={`mt-1 ${p}`}>{FAMILY[family]!.what}</p>
            <ul className="mt-3 divide-y divide-line rounded-md border border-line bg-white">
              {members.map((rule) => {
                const hits = benchmarkHits(rule.id);
                return (
                  <li key={rule.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2 text-sm">
                    <Link className="font-mono text-ink underline-offset-2 hover:underline" href={`/airlock/rules/${slugFor(rule.id)}`}>
                      {rule.id}
                    </Link>
                    <span className="font-mono text-xs text-muted">w {rule.weight.toFixed(2)}</span>
                    {languageOf(rule.id) === "German" && <span className="text-xs text-muted">German</span>}
                    <span className="min-w-0 flex-1 text-muted">{rule.description}</span>
                    {hits !== null && <span className="font-mono text-xs text-muted">benchmark hits {hits}</span>}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      <p className={`mt-8 ${p}`}>
        How they do on public data:{" "}
        <Link className="underline underline-offset-2" href="/airlock#benchmark">
          the benchmark, misses included
        </Link>
        . Try them on your own text:{" "}
        <Link className="underline underline-offset-2" href="/airlock#try-it">
          the live scanner
        </Link>
        .
      </p>
    </main>
  );
}
