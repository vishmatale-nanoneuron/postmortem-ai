import { POSTS_BY_DATE } from "../blog/posts";

// RSS 2.0 for the blog. Aggregators, readers and a few AI crawlers
// discover new writing through this; without it every post had to be
// found by search alone. Static at build time from the posts registry.

const SITE_URL = "https://www.nanoneuron.ai";

export const dynamic = "force-static";

function escape(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function GET(): Response {
  const items = POSTS_BY_DATE.map(
    (post) => `    <item>
      <title>${escape(post.title)}</title>
      <link>${SITE_URL}/blog/${post.slug}</link>
      <guid isPermaLink="true">${SITE_URL}/blog/${post.slug}</guid>
      <pubDate>${new Date(`${post.published}T00:00:00Z`).toUTCString()}</pubDate>
      <description>${escape(post.description)}</description>
    </item>`,
  );
  const latest = POSTS_BY_DATE[0]?.updated ?? "2026-09-04";
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>NanoNeuron — Airlock and PostMortem AI</title>
    <link>${SITE_URL}/blog</link>
    <description>Real outages in postmortem form, the unedited output of PostMortem AI on public incidents, and how the grounding mechanism works.</description>
    <language>en</language>
    <lastBuildDate>${new Date(`${latest}T00:00:00Z`).toUTCString()}</lastBuildDate>
    <atom:link href="${SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
${items.join("\n")}
  </channel>
</rss>
`;
  return new Response(xml, {
    headers: { "content-type": "application/rss+xml; charset=utf-8", "cache-control": "public, max-age=3600, s-maxage=3600" },
  });
}
