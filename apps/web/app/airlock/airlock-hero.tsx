import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AirlockMark } from "./airlock-mark";
import { ScanTheatre } from "./scan-theatre";

// Airlock as the front door of the site. This is the homepage hero; the
// fuller version with the playground, the integration snippets and the FAQ
// lives on /airlock, and every call to action here points there.
//
// Same restraint as the rest of the site: the headline states the problem,
// the demonstration is real engine output, and the two facts a visitor
// most needs -- it is free, and it is live -- are said in the badge rather
// than implied. No price, because there is none.
export function AirlockHero() {
  return (
    <div className="relative overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[28rem] bg-[radial-gradient(60%_50%_at_50%_0%,color-mix(in_oklab,var(--color-accent)_14%,transparent),transparent)]"
      />
      <div className="mx-auto max-w-3xl px-4 pt-16 pb-10 sm:pt-24">
        <div className="mx-auto max-w-2xl text-center">
          <div className="flex items-center justify-center gap-2.5 animate-in fade-in zoom-in-95 duration-700">
            <AirlockMark size={34} />
            <span className="text-lg font-semibold tracking-tight text-ink">Airlock</span>
            <span className="rounded-full border border-line px-2 py-0.5 text-[10px] tracking-wide text-muted uppercase">
              Free scanner · live
            </span>
          </div>
          <h1 className="mt-5 animate-in fade-in slide-in-from-bottom-3 text-4xl leading-[1.1] font-semibold tracking-tight text-ink duration-700 delay-100 fill-mode-backwards sm:text-6xl">
            Your agent reads things{" "}
            <span className="hero-gradient-text bg-gradient-to-r from-accent via-accent/70 to-accent/60 bg-clip-text text-transparent">
              you didn&apos;t write.
            </span>
          </h1>
          <p className="mx-auto mt-5 max-w-xl animate-in fade-in slide-in-from-bottom-3 text-lg text-muted duration-700 delay-200 fill-mode-backwards">
            A support ticket, a web page, a PDF, an email. Any of them can carry a sentence aimed at the model rather
            than at you. Airlock sits between your agent and that content &mdash; scoring what comes in for prompt
            injection, and checking what goes out for credentials and personal data.
          </p>
          <div className="mt-8 flex animate-in fade-in slide-in-from-bottom-3 flex-wrap items-center justify-center gap-x-4 gap-y-3 duration-700 delay-300 fill-mode-backwards">
            <Link
              href="/airlock#try-it"
              className={cn(
                buttonVariants({ size: "lg" }),
                "h-auto px-7 py-3 text-sm shadow-lg shadow-accent/10 transition-[transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-accent/35",
              )}
            >
              Scan your own text
            </Link>
            <Link href="/airlock#how" className={cn(buttonVariants({ variant: "link" }), "text-sm text-ink")}>
              How it decides
            </Link>
            <Link href="/airlock#integrate" className={cn(buttonVariants({ variant: "link" }), "text-sm text-ink")}>
              Integrate in one call
            </Link>
          </div>
        </div>

        {/* The demonstration, where a product video would go. Real engine
            output replayed -- see scan-theatre.tsx. */}
        <div className="mt-10 animate-in fade-in slide-in-from-bottom-2 duration-700 delay-500 fill-mode-backwards">
          <ScanTheatre />
          <p className="mt-2 text-center text-xs text-muted">
            Recorded output from the detector, replayed.{" "}
            <Link className="underline underline-offset-2" href="/airlock#try-it">
              The live scanner
            </Link>{" "}
            runs on whatever you paste into it &mdash; free, no signup, nothing stored.
          </p>
        </div>
      </div>
    </div>
  );
}
