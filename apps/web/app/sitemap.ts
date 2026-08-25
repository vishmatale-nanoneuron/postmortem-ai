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

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/docs`, changeFrequency: "monthly", priority: 0.8 },
    { url: `${SITE_URL}/pricing`, changeFrequency: "monthly", priority: 0.8 },
    { url: `${SITE_URL}/postmortems`, changeFrequency: "daily", priority: 0.6 },
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
