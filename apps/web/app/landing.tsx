// Marketing/branding content for logged-out visitors. Deliberately a pure,
// stateless component -- all the sign-in state lives in workspace.tsx's
// AuthGate, which renders alongside this. Every claim made here matches
// public/llms.txt word for word in substance: the grounding guarantee, the
// honest "what this doesn't do" list. Never let this page and llms.txt
// drift -- an AI crawler and a human visitor should learn the same facts.
//
// Uses shadcn's Card + Badge + buttonVariants (not the <Button> component
// itself, which wraps Base UI's polymorphic render prop) -- these are plain
// <a> links styled as buttons, not interactive <button> elements, so
// applying buttonVariants()'s className directly to the anchor is simpler
// and avoids any Base UI render-prop friction for what's fundamentally
// navigation.

import { CheckCircle2, ClipboardList, ShieldCheck, Sparkles, UserCheck, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Hero() {
  return (
    <div className="relative overflow-hidden">
      {/* Soft radial wash behind the hero only -- an accent-tinted glow,
          not a full-page gradient, so every other section stays on the
          plain paper background this app's design is built around. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[32rem] bg-[radial-gradient(60%_50%_at_50%_0%,color-mix(in_oklab,var(--color-accent)_14%,transparent),transparent)]"
      />
      <div className="mx-auto max-w-3xl px-4 pt-20 pb-12 text-center sm:pt-28">
        <Badge variant="outline" className="h-auto gap-1.5 rounded-full border-line px-3 py-1 text-[11px] text-muted">
          <Sparkles className="size-3 text-accent" />
          AI-drafted, evidence-cited postmortems
        </Badge>
        <h1 className="mt-5 text-4xl leading-[1.1] font-semibold tracking-tight text-ink sm:text-6xl">
          Postmortems that{" "}
          <span className="bg-gradient-to-r from-accent to-accent/60 bg-clip-text text-transparent">
            cite their evidence.
          </span>
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-lg text-muted">
          Record what actually happened during an incident. Get an AI-drafted postmortem where every claim points
          back to a real, recorded entry — anything the evidence doesn&apos;t support is marked unsupported, never
          invented.
        </p>
        <div className="mt-9 flex flex-wrap items-center justify-center gap-x-4 gap-y-3">
          <a href="#get-started" className={cn(buttonVariants({ size: "lg" }), "h-auto px-7 py-3 text-sm shadow-lg shadow-accent/10")}>
            Get started — first postmortem free
          </a>
          <a href="/postmortems" className={cn(buttonVariants({ variant: "link" }), "text-sm text-ink")}>
            See real examples
          </a>
          <a href="/docs" className={cn(buttonVariants({ variant: "link" }), "text-sm text-ink")}>
            How it works
          </a>
          <a href="/pricing" className={cn(buttonVariants({ variant: "link" }), "text-sm text-ink")}>
            Pricing
          </a>
        </div>
      </div>
    </div>
  );
}

// A concrete before/after, not just the abstract claim above -- the
// citation/unsupported-marker guarantee is easy to assert and hard to
// believe from prose alone. Numbers and text are illustrative, not a real
// incident -- deliberately labeled as an example, not dressed up as a real
// customer's postmortem (that's what the published examples at
// /postmortems are for).
export function GroundingExample() {
  return (
    <div className="mx-auto max-w-3xl px-4 pb-8">
      <Card className="overflow-hidden border-line py-0 shadow-sm">
        <div className="border-b border-line bg-paper/60 px-6 py-3.5">
          <div className="text-xs font-medium tracking-widest text-muted uppercase">
            What &ldquo;grounded&rdquo; actually means
          </div>
        </div>
        <CardContent className="grid gap-px overflow-hidden sm:grid-cols-2 sm:gap-0 sm:divide-x sm:divide-line">
          <div className="px-6 py-5">
            <p className="flex items-center gap-1.5 text-xs font-medium text-accent">
              <CheckCircle2 className="size-3.5" />
              Kept — cites real evidence
            </p>
            <p className="mt-2.5 rounded-md bg-paper px-3.5 py-3 font-mono text-[13px] leading-relaxed text-ink">
              &ldquo;Latency rose from 180ms to 4200ms starting 14:04 UTC, correlated with deploy #482.
              <span className="ml-1 rounded bg-accent/10 px-1 py-0.5 text-accent">[2]</span>&rdquo;
            </p>
          </div>
          <div className="px-6 py-5">
            <p className="flex items-center gap-1.5 text-xs font-medium text-red-600">
              <XCircle className="size-3.5" />
              Dropped — no citation exists
            </p>
            <p className="mt-2.5 rounded-md bg-paper px-3.5 py-3 font-mono text-[13px] leading-relaxed text-muted italic">
              &ldquo;Not established by the recorded evidence.&rdquo;
            </p>
            <p className="mt-2 text-xs text-muted">
              (what a claim like &ldquo;this cost the company $40,000&rdquo; becomes, if no evidence entry says so)
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

const steps = [
  {
    icon: ClipboardList,
    title: "Record evidence",
    body: "Alerts, deploys, metrics, human notes, customer reports — timestamped entries, not a blank text box.",
  },
  {
    icon: ShieldCheck,
    title: "Generate a grounded draft",
    body: "The model cites which evidence entry backs every claim. Code checks every citation independently before anything is stored — a claim with no valid citation is replaced with a fixed unsupported marker, never kept.",
  },
  {
    icon: UserCheck,
    title: "A human approves, then it publishes",
    body: "Publishing always records a real, named approver. The database itself refuses to mark a postmortem published without one.",
  },
];

export function HowItWorks() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <div className="grid gap-4 sm:grid-cols-3">
        {steps.map((step, i) => (
          <Card key={step.title} className="border-line shadow-sm transition-shadow hover:shadow-md">
            <CardContent>
              <div className="flex items-center gap-2.5">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent">
                  {i + 1}
                </span>
                <step.icon className="size-4 text-muted" />
              </div>
              <h3 className="mt-3 text-sm font-semibold text-ink">{step.title}</h3>
              <p className="mt-1.5 text-sm text-muted">{step.body}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

const notes = [
  "Doesn't auto-publish anything — publishing is always a deliberate, named human action.",
  "Doesn't estimate cost, revenue, or customer-impact figures the evidence didn't state.",
  "Doesn't integrate with PagerDuty, Datadog, or other monitoring tools yet — evidence is entered directly.",
  "Doesn't support teams or organizations yet — each account is a single user's own incidents.",
];

export function WhatThisIsnt() {
  return (
    <div className="mx-auto max-w-3xl px-4 pt-4 pb-20">
      <div className="text-xs font-medium tracking-widest text-muted uppercase">What this isn&apos;t</div>
      <ul className="mt-3 space-y-2.5">
        {notes.map((item) => (
          <li key={item} className="flex items-start gap-2.5 text-sm text-muted">
            <XCircle className="mt-0.5 size-3.5 shrink-0 text-line" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
