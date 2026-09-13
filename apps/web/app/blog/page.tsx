import type { Metadata } from "next";
import Link from "next/link";
import { POSTS_BY_DATE } from "./posts";

// /blog was a 404 with three posts underneath it: anyone trimming a post
// URL, or a crawler following the breadcrumb, hit the not-found page.
// This is the index those posts always implied.
export const metadata: Metadata = {
  title: "Writing — worked examples and how the mechanism works",
  description:
    "Real outages laid out in postmortem form, the unedited output of PostMortem AI on a public incident, and how the grounding mechanism works. No marketing posts.",
  alternates: { canonical: "/blog", types: { "application/rss+xml": "/feed.xml" } },
};

function date(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
}

export default function BlogIndex() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-10 text-ink">
      <div className="text-xs font-medium tracking-widest text-muted uppercase">Writing</div>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Worked examples, and how it works</h1>
      <p className="mt-3 text-sm leading-relaxed text-muted">
        Every post here is either a real, public incident laid out in postmortem form with sources, or the mechanism
        explained. Subscribe:{" "}
        <a className="underline underline-offset-2" href="/feed.xml">
          RSS
        </a>
        .
      </p>
      <ul className="mt-8 divide-y divide-line">
        {POSTS_BY_DATE.map((post) => (
          <li key={post.slug} className="py-5">
            <div className="text-xs text-muted">
              <time dateTime={post.published}>{date(post.published)}</time>
              {post.updated !== post.published && <> · updated {date(post.updated)}</>}
            </div>
            <h2 className="mt-1 text-lg font-semibold">
              <Link className="underline-offset-2 hover:underline" href={`/blog/${post.slug}`}>
                {post.title}
              </Link>
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-muted">{post.description}</p>
          </li>
        ))}
      </ul>
      <p className="mt-8 text-sm text-muted">
        Also:{" "}
        <Link className="underline underline-offset-2" href="/postmortem-template">
          the postmortem template
        </Link>
        ,{" "}
        <Link className="underline underline-offset-2" href="/postmortems">
          published postmortems
        </Link>
        , and{" "}
        <Link className="underline underline-offset-2" href="/airlock/benchmark">
          Airlock&apos;s public benchmark
        </Link>
        .
      </p>
    </main>
  );
}
