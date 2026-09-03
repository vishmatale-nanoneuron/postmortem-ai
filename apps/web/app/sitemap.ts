import type { MetadataRoute } from "next";

const SITE_URL = "https://www.nanoneuron.ai";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type PublicPostmortem = { slug: string; published_at: number | null };

async function fetchPublicSlugs(): Promise<PublicPostmortem[]> {
  try {
    const response = await fetch(`${API_BASE}/v1/postmortems/public`, { next: { revalidate: 300 } });
    if (!response.ok) return [];
    return (await response.json()) as PublicPostmortem[];
  } catch {
    return [];
  }
}

// Google's own sitemap guidance: lastmod is a real signal it uses for
// recrawl priority when accurate; changeFrequency/priority are largely
// ignored and kept here only because they cost nothing and don't hurt.
// A serverless function's deployed bundle doesn't include .git, so this
// can't be computed at request time the way it'd be nice to (git log -1
// each page's source file) -- these are that same real command's output,
// captured by hand. Update a date here when that page's actual visible
// content changes; a rebuild alone (styling, refactors) doesn't need a
// bump, and a wrong-but-static date is still more honest to a crawler
// than one that silently reads "today" on every request regardless of
// whether anything changed.
const LAST_MODIFIED = {
  home: new Date("2026-08-29T13:58:11+05:30"),
  docs: new Date("2026-09-04T01:19:04+05:30"),
  pricing: new Date("2026-09-01T22:45:05+05:30"),
  groundingMechanism: new Date("2026-09-02T20:56:15+05:30"),
  githubOutageDemo: new Date("2026-09-02T20:56:15+05:30"),
  postmortems: new Date("2026-09-01T22:56:32+05:30"),
  status: new Date("2026-09-01T20:53:02+05:30"),
  privacy: new Date("2026-09-01T20:53:02+05:30"),
  terms: new Date("2026-09-04T01:19:04+05:30"),
} as const;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, lastModified: LAST_MODIFIED.home, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/docs`, lastModified: LAST_MODIFIED.docs, changeFrequency: "monthly", priority: 0.8 },
    { url: `${SITE_URL}/pricing`, lastModified: LAST_MODIFIED.pricing, changeFrequency: "monthly", priority: 0.8 },
    {
      url: `${SITE_URL}/blog/grounding-mechanism`,
      lastModified: LAST_MODIFIED.groundingMechanism,
      changeFrequency: "yearly",
      priority: 0.6,
    },
    {
      url: `${SITE_URL}/blog/github-outage-demo`,
      lastModified: LAST_MODIFIED.githubOutageDemo,
      changeFrequency: "yearly",
      priority: 0.6,
    },
    { url: `${SITE_URL}/postmortems`, lastModified: LAST_MODIFIED.postmortems, changeFrequency: "daily", priority: 0.6 },
    { url: `${SITE_URL}/status`, lastModified: LAST_MODIFIED.status, changeFrequency: "daily", priority: 0.3 },
    { url: `${SITE_URL}/privacy`, lastModified: LAST_MODIFIED.privacy, changeFrequency: "monthly", priority: 0.3 },
    { url: `${SITE_URL}/terms`, lastModified: LAST_MODIFIED.terms, changeFrequency: "monthly", priority: 0.3 },
  ];

  const postmortems = await fetchPublicSlugs();
  const postmortemRoutes: MetadataRoute.Sitemap = postmortems.map((item) => ({
    url: `${SITE_URL}/postmortems/${item.slug}`,
    lastModified: item.published_at ? new Date(item.published_at) : undefined,
    changeFrequency: "monthly",
    priority: 0.5,
  }));

  return [...staticRoutes, ...postmortemRoutes];
}
