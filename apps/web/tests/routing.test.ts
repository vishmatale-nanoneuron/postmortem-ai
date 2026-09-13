// The routes a visitor plausibly types or lands on. Pinned: /blog lists
// every post in the registry and every registry entry has a real page;
// the feed is valid RSS carrying the same posts; /airlock/benchmark
// exists and /airlock no longer inlines the misses; the guessed URLs
// redirect; the sitemap carries the new routes.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { POSTS, POSTS_BY_DATE } from "../app/blog/posts";

const root = join(__dirname, "..");

describe("routing", () => {
  it("every registered post has a page, and every post page is registered", () => {
    const { readdirSync } = require("node:fs") as typeof import("node:fs");
    const dirs = readdirSync(join(root, "app", "blog"), { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name)
      .sort();
    expect(dirs).toEqual(POSTS.map((p) => p.slug).sort());
    for (const post of POSTS) {
      expect(existsSync(join(root, "app", "blog", post.slug, "page.tsx"))).toBe(true);
      expect(post.title.length).toBeGreaterThan(10);
      expect(post.published).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(post.updated >= post.published).toBe(true);
    }
    expect(POSTS_BY_DATE[0]!.published >= POSTS_BY_DATE[POSTS_BY_DATE.length - 1]!.published).toBe(true);
  });

  it("serves a valid RSS feed of the same posts", async () => {
    const { GET } = await import("../app/feed.xml/route");
    const response = GET();
    expect(response.headers.get("content-type")).toContain("application/rss+xml");
    const xml = await response.text();
    expect(xml.startsWith('<?xml version="1.0"')).toBe(true);
    expect(xml).toContain("<rss version=\"2.0\"");
    expect((xml.match(/<item>/g) ?? []).length).toBe(POSTS.length);
    for (const post of POSTS) expect(xml).toContain(`https://www.nanoneuron.ai/blog/${post.slug}`);
    expect(xml).not.toContain("<script");
  });

  it("gives the benchmark its own page and keeps the misses off /airlock", () => {
    expect(existsSync(join(root, "app", "airlock", "benchmark", "page.tsx"))).toBe(true);
    const section = readFileSync(join(root, "app", "airlock", "benchmark-section.tsx"), "utf8");
    expect(section).toContain('href="/airlock/benchmark"');
    expect(section).toContain("full ?");
    const page = readFileSync(join(root, "app", "airlock", "page.tsx"), "utf8");
    expect(page).toContain("<BenchmarkSection h2={h2} />");
    expect(page).not.toContain("<BenchmarkSection h2={h2} full");
  });

  it("redirects the URLs people guess and advertises the feed", () => {
    const config = readFileSync(join(root, "next.config.mjs"), "utf8");
    for (const [from, to] of [
      ["/airlock/pricing", "/airlock#pricing"],
      ["/airlock/docs", "/docs#airlock"],
      ["/docs/airlock", "/docs#airlock"],
      ["/rss.xml", "/feed.xml"],
    ]) {
      expect(config).toContain(`source: "${from}", destination: "${to}"`);
    }
    const layout = readFileSync(join(root, "app", "layout.tsx"), "utf8");
    expect(layout).toContain('"application/rss+xml"');
    const sitemap = readFileSync(join(root, "app", "sitemap.ts"), "utf8");
    expect(sitemap).toContain("`${SITE_URL}/blog`");
    expect(sitemap).toContain("`${SITE_URL}/airlock/benchmark`");
    const rulePage = readFileSync(join(root, "app", "airlock", "rules", "[id]", "page.tsx"), "utf8");
    expect(rulePage).toContain("permanentRedirect(`/airlock/rules/${id.toLowerCase()}`)");
  });
});
