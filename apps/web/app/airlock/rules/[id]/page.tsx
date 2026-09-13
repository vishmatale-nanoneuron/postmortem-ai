import type { Metadata } from "next";
import Link from "next/link";
import { notFound, permanentRedirect } from "next/navigation";
import { FAMILY, RULES, benchmarkHits, languageOf, roleOfWeight, ruleForSlug, slugFor } from "../rule-data";

// One page per detection rule, generated at build time from rules.json.
// A rule is a thing people search for ("ignore previous instructions
// detection", "prompt injection role hijack rule"), and until these pages
// existed nothing on the site could be linked to for one. Each page says
// what the rule catches, how much it weighs, how it did on the public
// benchmark, and how to mute it -- never the pattern itself.

// Unknown slugs are still 404s (see the page body); dynamicParams stays on
// only so an upper-case id -- the casing the API itself uses, "IO-001" --
// can be redirected to its canonical lower-case page instead of 404ing.
export const dynamicParams = true;

export function generateStaticParams() {
  return RULES.map((rule) => ({ id: slugFor(rule.id) }));
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const rule = ruleForSlug(id);
  if (!rule) return { title: "Rule not found" };
  const family = FAMILY[rule.family]?.name ?? rule.family;
  return {
    title: `${rule.id} — ${family} rule`,
    description: `${rule.description} Weight ${rule.weight.toFixed(2)} in the Airlock prompt-injection guard's ${family.toLowerCase()} family.`,
    alternates: { canonical: `/airlock/rules/${slugFor(rule.id)}` },
  };
}

const p = "text-sm leading-relaxed text-muted";

export default async function RulePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (id !== id.toLowerCase() && ruleForSlug(id)) permanentRedirect(`/airlock/rules/${id.toLowerCase()}`);
  const rule = ruleForSlug(id);
  if (!rule) notFound();
  const family = FAMILY[rule.family] ?? { name: rule.family, what: "" };
  const siblings = RULES.filter((r) => r.family === rule.family && r.id !== rule.id);
  const hits = benchmarkHits(rule.id);
  const language = languageOf(rule.id);

  const structuredData = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Airlock", item: "https://www.nanoneuron.ai/airlock" },
      { "@type": "ListItem", position: 2, name: "Rules", item: "https://www.nanoneuron.ai/airlock/rules" },
      { "@type": "ListItem", position: 3, name: rule.id, item: `https://www.nanoneuron.ai/airlock/rules/${slugFor(rule.id)}` },
    ],
  };

  return (
    <main className="mx-auto max-w-3xl px-6 py-10 text-ink">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }} />
      <nav className="mb-4 text-xs text-muted" aria-label="Breadcrumb">
        <Link className="underline underline-offset-2" href="/airlock">
          Airlock
        </Link>{" "}
        /{" "}
        <Link className="underline underline-offset-2" href="/airlock/rules">
          Rules
        </Link>{" "}
        / {rule.id}
      </nav>
      <div className="text-xs font-medium tracking-widest text-muted uppercase">{family.name}</div>
      <h1 className="mt-2 font-mono text-3xl font-semibold tracking-tight">{rule.id}</h1>
      <p className="mt-3 text-lg text-ink">{rule.description}</p>

      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-3 rounded-md border border-line bg-white p-4 text-sm sm:grid-cols-4">
        <dt className="text-muted">Weight</dt>
        <dd className="font-mono">{rule.weight.toFixed(2)}</dd>
        <dt className="text-muted">Family</dt>
        <dd>{family.name}</dd>
        <dt className="text-muted">Language</dt>
        <dd>{language}</dd>
        <dt className="text-muted">Benchmark</dt>
        <dd className="font-mono">{hits === null ? "0 hits" : `${hits} hits`}</dd>
      </dl>

      <h2 className="mt-8 text-lg font-semibold">What it means</h2>
      <p className={`mt-2 ${p}`}>
        On its own this rule {roleOfWeight(rule.weight)}. Scores combine with noisy-OR, not addition, so several weak
        matches raise suspicion without being able to manufacture certainty. The family: {family.what}
      </p>
      <p className={`mt-2 ${p}`}>
        {hits === null
          ? "It did not fire on any injection in the public benchmark dataset -- a rule kept for what it catches, not for its hit count."
          : `It fired on ${hits} of the injections in the public benchmark dataset (deepset/prompt-injections).`}{" "}
        {language === "German"
          ? "It is one of the German override forms added after that benchmark; any other language is the deep scan's job."
          : "The rules match English phrasing; any other language is the deep scan's job."}
      </p>

      <h2 className="mt-8 text-lg font-semibold">If it fires on your own documents</h2>
      <p className={`mt-2 ${p}`}>
        Mute it for your account: open the Policy card in your dashboard, tick <span className="font-mono">{rule.id}</span>{" "}
        under muted rules, and save. It takes effect on the next call under any of your keys, and every scan
        response names the policy it was judged under. Only a signed-in session can change the policy; a key cannot.
      </p>

      {siblings.length > 0 && (
        <>
          <h2 className="mt-8 text-lg font-semibold">Other {family.name.toLowerCase()} rules</h2>
          <ul className="mt-2 divide-y divide-line rounded-md border border-line bg-white">
            {siblings.map((sibling) => (
              <li key={sibling.id} className="flex flex-wrap items-baseline gap-x-3 px-3 py-2 text-sm">
                <Link className="font-mono underline-offset-2 hover:underline" href={`/airlock/rules/${slugFor(sibling.id)}`}>
                  {sibling.id}
                </Link>
                <span className="font-mono text-xs text-muted">w {sibling.weight.toFixed(2)}</span>
                <span className="min-w-0 flex-1 text-muted">{sibling.description}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className={`mt-8 ${p}`}>
        <Link className="underline underline-offset-2" href="/airlock#try-it">
          Try it on your own text
        </Link>{" "}
        ·{" "}
        <Link className="underline underline-offset-2" href="/airlock#benchmark">
          The benchmark, misses included
        </Link>{" "}
        ·{" "}
        <Link className="underline underline-offset-2" href="/airlock#pricing">
          Pricing
        </Link>
      </p>
    </main>
  );
}
