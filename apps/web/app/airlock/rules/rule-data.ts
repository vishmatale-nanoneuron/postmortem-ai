import benchmark from "../benchmark.json";
import rules from "../rules.json";

// The rule catalogue the per-rule pages are built from. rules.json is
// exported from apps/api/app/airlock/rules.py by scripts/export_rules.py
// and pinned to it by a test, so a page can never describe a rule the
// engine does not run. Benchmark hits come from the committed results.

export type Rule = { id: string; family: string; weight: number; description: string };

export const RULES: Rule[] = (rules as { rules: Rule[] }).rules;
export const RULE_COUNT: number = (rules as { count: number }).count;

export const FAMILY: Record<string, { name: string; what: string }> = {
  instruction_override: { name: "Instruction override", what: "“Ignore all previous instructions” and its many rewordings." },
  role_hijack: { name: "Role hijack", what: "Content that tries to reassign the agent's role or persona mid-context." },
  delimiter_break: { name: "Delimiter break", what: "Fake system/user turn markers, forged tags, anything that pretends to end your prompt." },
  exfiltration: { name: "Exfiltration", what: "Instructions to send data somewhere — a URL, an image, a markdown link that fires on render." },
  tool_abuse: { name: "Tool abuse", what: "Content that asks the agent to call a tool it was not asked to call." },
  authority_spoof: { name: "Authority spoof", what: "“This is your developer / the system administrator” framing." },
  memory_poison: { name: "Memory poison", what: "Instructions aimed at what the agent stores and recalls later, not just this turn." },
  encoding: { name: "Encoding", what: "Base64, rot13 and chained decode-then-obey instructions." },
};

const HITS: Record<string, number> = Object.fromEntries(
  (benchmark as { top_rules_on_injections: { rule: string; hits: number }[] }).top_rules_on_injections.map((r) => [r.rule, r.hits]),
);

export function benchmarkHits(id: string): number | null {
  return id in HITS ? HITS[id]! : null;
}

/** URL slug: the id, lower-cased ("IO-001" -> "io-001"). */
export function slugFor(id: string): string {
  return id.toLowerCase();
}

export function ruleForSlug(slug: string): Rule | undefined {
  const wanted = slug.toUpperCase();
  return RULES.find((rule) => rule.id === wanted);
}

/** The 1xx series is German; everything else is English. */
export function languageOf(id: string): "German" | "English" {
  return /-1\d\d$/.test(id) ? "German" : "English";
}

export function roleOfWeight(weight: number): string {
  if (weight >= 0.75) return "blocks on its own: a single match crosses the default 0.75 block threshold";
  if (weight >= 0.4) return "flags on its own and blocks in combination with any other match";
  return "never decides alone; it raises the score only alongside other signals";
}
