"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";

// A published postmortem is the one page most likely to be found cold, by
// someone who's never heard of this product -- if it's genuinely good,
// this is the "quality speaks for itself" growth loop, but only if it's
// actually easy to hand to someone else. Plain outbound links (no JS
// needed for X/LinkedIn's own share intents) plus one small client-side
// affordance for copying the link.
export function ShareLinks({ url, title }: { url: string; title: string }) {
  const [copied, setCopied] = useState(false);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied (permissions, non-HTTPS context) --
      // the URL is still visible/selectable in the address bar either way.
    }
  }

  const encodedUrl = encodeURIComponent(url);
  const encodedTitle = encodeURIComponent(title);

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="text-muted">Share:</span>
      <a
        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-7 border-line px-2.5 text-xs text-ink")}
        href={`https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedTitle}`}
        target="_blank"
        rel="noopener noreferrer"
      >
        X
      </a>
      <a
        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-7 border-line px-2.5 text-xs text-ink")}
        href={`https://www.linkedin.com/sharing/share-offsite/?url=${encodedUrl}`}
        target="_blank"
        rel="noopener noreferrer"
      >
        LinkedIn
      </a>
      <button
        type="button"
        onClick={() => void copyLink()}
        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-7 border-line px-2.5 text-xs text-ink")}
      >
        {copied ? "Copied!" : "Copy link"}
      </button>
    </div>
  );
}
