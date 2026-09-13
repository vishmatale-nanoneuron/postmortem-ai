// The blog's table of contents: one entry per post, the source of truth
// for /blog, the sitemap and /feed.xml. A post's own page.tsx keeps its
// full metadata; this registry carries what a list, a crawler and a feed
// reader need. Dates are the last time the visible content changed (the
// same values the sitemap has always carried by hand).

export type Post = {
  slug: string;
  title: string;
  description: string;
  published: string; // ISO date
  updated: string; // ISO date
  product: "postmortem" | "airlock";
};

export const POSTS: Post[] = [
  {
    slug: "cloudflare-outages-2025",
    title: "Two Cloudflare outages, in postmortem form",
    description:
      "Cloudflare's own 18 November and 5 December 2025 incident reports laid out in a blameless postmortem template -- every line quoted verbatim and linked to the source, so you can see what a filled-in template looks like on a real, public, checkable incident.",
    published: "2026-09-11",
    updated: "2026-09-11",
    product: "postmortem",
  },
  {
    slug: "github-outage-demo",
    title: "What our tool drafted from a real public outage",
    description:
      "We fed the public facts of GitHub's August 17, 2026 outage into PostMortem AI and published the real, unedited output -- a concrete demonstration of the grounding mechanism itself, not a claim of being better than anyone's official writeup.",
    published: "2026-09-04",
    updated: "2026-09-04",
    product: "postmortem",
  },
  {
    slug: "grounding-mechanism",
    title: "How postmortem drafting is grounded, mechanically",
    description:
      "The two-layer mechanism behind every AI-drafted postmortem: cited generation, then independent code-level verification of every citation before anything is stored.",
    published: "2026-09-04",
    updated: "2026-09-04",
    product: "postmortem",
  },
];

export const POSTS_BY_DATE: Post[] = [...POSTS].sort((a, b) => (a.published < b.published ? 1 : -1));
