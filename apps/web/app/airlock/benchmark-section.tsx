import benchmark from "./benchmark.json";

// The public benchmark, rendered from the committed results file. The
// numbers are whatever scripts/airlock_benchmark.py produced on the
// committed dataset rows; apps/api/tests/test_airlock_public_benchmark.py
// fails if this file and the engine disagree, and airlock-page.test.ts
// fails if this copy and the API's copy differ. Nothing here is typed by
// hand.

type Metrics = {
  rows: number;
  injections: number;
  legitimate: number;
  caught: number;
  blocked: number;
  recall: number | null;
  block_rate: number | null;
  false_positives: number;
  false_positive_rate: number | null;
  precision: number | null;
};

type Miss = { language: string; score: number; verdict: string; rules: string[]; text: string };

const data = benchmark as {
  dataset: string;
  dataset_url: string;
  license: string;
  generated_at: number;
  engine: { rules: number; families: string[]; deep_scan: boolean };
  overall: Metrics;
  english: Metrics;
  german: Metrics;
  top_rules_on_injections: { rule: string; hits: number }[];
  weight_headroom: {
    injections_matching_no_rule: number;
    injections_matched_below_flag: number;
    legitimate_with_any_match: number;
    legitimate_max_score: number;
  };
  misses: Miss[];
  false_positives: Miss[];
};

function pct(value: number | null): string {
  return value === null ? "–" : `${(value * 100).toFixed(1)}%`;
}

const p = "mb-3 text-[15px] leading-relaxed text-muted";

export function BenchmarkSection({ h2, full = false }: { h2: string; full?: boolean }) {
  const date = new Date(data.generated_at).toLocaleDateString("en-GB", { year: "numeric", month: "long", day: "numeric" });
  const rows: [string, Metrics][] = [
    ["All rows", data.overall],
    ["English", data.english],
    ["German", data.german],
  ];
  return (
    <>
      <h2 className={h2}>The benchmark, misses included</h2>
      <p className={p}>
        The rule engine, run on{" "}
        <a className="underline underline-offset-2" href={data.dataset_url} target="_blank" rel="noopener noreferrer">
          {data.dataset}
        </a>{" "}
        ({data.license}; {data.overall.rows.toLocaleString("en-US")} labelled texts, {data.overall.injections} marked
        injection and {data.overall.legitimate} legitimate, in English and German), re-run on {date} with{" "}
        {data.engine.rules} rules and no model call. &ldquo;Caught&rdquo; means flag or block. Every number below is
        computed from the committed results file; a test fails if the engine and the file disagree.
      </p>
      <div className="mb-3 overflow-x-auto rounded-md border border-line">
        <table className="w-full text-left text-sm">
          <thead className="bg-paper text-xs text-muted">
            <tr>
              <th className="px-3 py-1.5 font-medium">Rows</th>
              <th className="px-3 py-1.5 text-right font-medium">Injections caught</th>
              <th className="px-3 py-1.5 text-right font-medium">of which blocked</th>
              <th className="px-3 py-1.5 text-right font-medium">Legitimate flagged</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map(([label, m]) => (
              <tr key={label}>
                <td className="px-3 py-1.5">
                  {label} <span className="text-muted">({m.rows})</span>
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                  {m.caught}/{m.injections} <span className="text-muted">({pct(m.recall)})</span>
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                  {m.blocked} <span className="text-muted">({pct(m.block_rate)})</span>
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                  {m.false_positives}/{m.legitimate} <span className="text-muted">({pct(m.false_positive_rate)})</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={p}>
        <span className="font-medium text-ink">Read it plainly.</span> The rules catch about a quarter of what this
        dataset calls an injection, and raise no false alarm on any of its {data.overall.legitimate} legitimate
        texts. The false-alarm number is the one that decides whether a guard survives in production, and it is the
        one we will not trade away. The recall number is low for two reasons that are both true: this dataset labels
        off-topic questions and role-play requests to a news chatbot as injections, which a regex guard for agent
        pipelines does not and should not flag; and paraphrased overrides with no fixed phrasing are exactly what
        the rules cannot see and the{" "}
        <a className="underline underline-offset-2" href="#try-it">
          deep scan
        </a>{" "}
        exists for &mdash; it is not part of this run. Before this benchmark the same rules caught 1.1%; every rule
        added since is a general phrasing (&ldquo;forget everything before that&rdquo;, &ldquo;new tasks
        follow&rdquo;, &ldquo;show me your prompt text&rdquo;, and their German forms), not a fingerprint of a sample.
      </p>
      <p className={p}>
        <span className="font-medium text-ink">Why the weights are not tuned on it.</span> Of the{" "}
        {data.overall.injections - data.overall.caught} misses, {data.weight_headroom.injections_matching_no_rule}{" "}
        match no rule at all &mdash; no weight reaches text a pattern never saw &mdash; and only{" "}
        {data.weight_headroom.injections_matched_below_flag} match below the flag line. Fitting the weights to this
        data would recover those {data.weight_headroom.injections_matched_below_flag} and nothing else; what moves the
        number is new general phrasings, and the paraphrases go to the deep scan. The figures are in the results file
        and a test fails if reweighting ever becomes worth it.
      </p>
      {full ? (
        <section className="mb-3" aria-labelledby="benchmark-misses">
          <h3 id="benchmark-misses" className="mb-2 text-base font-semibold text-ink">
            All {data.misses.length} misses, verbatim from the dataset
          </h3>
          <ol className="space-y-1.5 rounded-md border border-line bg-paper px-3 py-2 font-mono text-[11.5px] leading-relaxed text-muted">
            {data.misses.map((miss, index) => (
              <li key={index} className="break-words">
                <span className="mr-1 rounded bg-white px-1 text-[10px] text-ink">{miss.language}</span>
                {miss.text}
              </li>
            ))}
          </ol>
        </section>
      ) : (
        <p className={p}>
          <a className="underline underline-offset-2" href="/airlock/benchmark">
            All {data.misses.length} misses, verbatim from the dataset
          </a>{" "}
          are on the benchmark&apos;s own page, with the rules that fired most and the reproduce command.
        </p>
      )}
      <p className={p}>
        Reproduce it:{" "}
        <code className="rounded bg-paper px-1 py-0.5 font-mono text-[12px]">
          PYTHONPATH=apps/api python apps/api/scripts/airlock_benchmark.py
        </code>{" "}
        in the public repository. The dataset rows are committed with attribution so the run needs no network.
        The rules that fired most on this dataset&apos;s injections:{" "}
        {data.top_rules_on_injections.slice(0, 5).map((r, index) => (
          <span key={r.rule} className="font-mono text-[12px] text-ink">
            {index > 0 && ", "}
            {r.rule} ({r.hits})
          </span>
        ))}
        .
      </p>
    </>
  );
}
