import Link from "next/link";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";

// A published postmortem is often the first thing a cold visitor ever
// sees of this product -- previously the only path back to the product
// from here was a small underlined "PostMortem AI" link buried in a
// footnote at the bottom of the page. Since the whole strategy here is
// "let the product's own quality bring people in" rather than outbound
// marketing, the page that's actually most likely to be found on its own
// merit needs a real, visible way to act on that interest.
export function CtaBanner() {
  return (
    <div className="mb-8 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-accent/20 bg-accent/5 px-4 py-3">
      <p className="text-sm text-ink">
        Had an incident like this? Get an evidence-grounded postmortem for your own -- first one&apos;s free.
      </p>
      <Link href="/#get-started" className={cn(buttonVariants({ size: "sm" }), "shrink-0")}>
        Try it free
      </Link>
    </div>
  );
}
