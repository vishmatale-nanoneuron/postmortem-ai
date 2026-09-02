"use client";

import * as React from "react";

// Anthropic-style scroll reveal for below-the-fold marketing content.
//
// Before this file existed, every entrance animation on the landing page
// (landing.tsx's animate-in utilities) fired at page-mount time -- the
// instant the page loaded, not when a visitor actually scrolled a section
// into view. For anything below the hero (the grounding example, the
// how-it-works steps, the integrations marquee, the "what this isn't"
// list) that meant the fade/slide/stamp animation had already finished
// running, invisibly, before the visitor ever scrolled far enough to see
// it -- so in practice nobody below the fold saw any animation at all.
// This makes those sections animate when they actually enter the
// viewport instead, which is the specific thing "meaningful, like
// Anthropic's site" is asking for: motion tied to what the visitor is
// doing, not motion that already happened off-screen.
//
// Starts revealed=true has one exception worth calling out: this is
// intentionally *not* how it starts. It starts hidden (opacity-0,
// translated down slightly) and flips to visible via IntersectionObserver.
// That's safe here -- unlike a data-dependent state -- because the
// fallback path is covered by CSS, not JS: prefers-reduced-motion (see
// globals.css) collapses the transition duration to ~0, and if
// IntersectionObserver itself is unavailable (very old browser, not a
// real risk for this app's audience but cheap to cover) the effect below
// reveals immediately rather than leaving content permanently invisible.
export function ScrollReveal({
  children,
  className,
}: {
  children: (revealed: boolean) => React.ReactNode;
  className?: string;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [revealed, setRevealed] = React.useState(false);

  React.useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") {
      setRevealed(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setRevealed(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15, rootMargin: "0px 0px -10% 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className={className}>
      {children(revealed)}
    </div>
  );
}
