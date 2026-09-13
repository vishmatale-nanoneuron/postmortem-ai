// The per-rule slug pages (/airlock/rules/[id]). Pinned: every rule in
// rules.json gets a static page and a sitemap entry; slugs round-trip
// case-insensitively; an unknown slug is a 404 (dynamicParams = false);
// the data file matches what the API serves (the API side pins it to
// rules.py); and the /airlock prose never hard-codes a rule count again.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { FAMILY, RULES, RULE_COUNT, benchmarkHits, languageOf, roleOfWeight, ruleForSlug, slugFor } from "../app/airlock/rules/rule-data";

describe("rule pages", () => {
  it("has a page and a slug for every rule, and only for real rules", async () => {
    expect(RULES.length).toBe(RULE_COUNT);
    expect(RULE_COUNT).toBeGreaterThanOrEqual(30);
    const { generateStaticParams, dynamicParams } = await import("../app/airlock/rules/[id]/page");
    const params = generateStaticParams();
    expect(params.map((p) => p.id)).toEqual(RULES.map((r) => slugFor(r.id)));
    expect(new Set(params.map((p) => p.id)).size).toBe(RULES.length);
    expect(dynamicParams).toBe(false);
    for (const rule of RULES) {
      expect(slugFor(rule.id)).toMatch(/^[a-z]{2}-\d{3}$/);
      expect(ruleForSlug(slugFor(rule.id))?.id).toBe(rule.id);
      expect(ruleForSlug(rule.id)?.id).toBe(rule.id);
      expect(FAMILY[rule.family]).toBeDefined();
      expect(rule.description.length).toBeGreaterThan(10);
      expect("pattern" in rule).toBe(false);
    }
    expect(ruleForSlug("zz-999")).toBeUndefined();
    expect(Object.keys(FAMILY).length).toBe(8);
  });

  it("classifies weights, languages and benchmark hits from the committed data", () => {
    expect(languageOf("IO-101")).toBe("German");
    expect(languageOf("IO-001")).toBe("English");
    expect(roleOfWeight(0.8)).toMatch(/blocks on its own/);
    expect(roleOfWeight(0.5)).toMatch(/flags on its own/);
    expect(roleOfWeight(0.3)).toMatch(/never decides alone/);
    expect(benchmarkHits("IO-003")).toBeGreaterThan(0);
    expect(benchmarkHits("ZZ-999")).toBeNull();
  });

  it("is in the sitemap and linked from /airlock, which no longer hard-codes a count", async () => {
    const sitemap = readFileSync(join(__dirname, "..", "app", "sitemap.ts"), "utf8");
    expect(sitemap).toContain("/airlock/rules/${slugFor(rule.id)}");
    const page = readFileSync(join(__dirname, "..", "app", "airlock", "page.tsx"), "utf8");
    expect(page).toContain('href="/airlock/rules"');
    expect(page).not.toMatch(/\b30 weighted rules\b/);
    expect(page).toContain("{RULE_COUNT} weighted rules");
  });
});
