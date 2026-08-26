// Marketing/branding content for logged-out visitors. Deliberately a pure,
// stateless component -- all the sign-in state lives in workspace.tsx's
// AuthGate, which renders alongside this. Every claim made here matches
// public/llms.txt word for word in substance: the grounding guarantee, the
// honest "what this doesn't do" list. Never let this page and llms.txt
// drift -- an AI crawler and a human visitor should learn the same facts.
//
// Uses shadcn's Card + buttonVariants (not the <Button> component itself,
// which wraps Base UI's polymorphic render prop) -- these are plain <a>
// links styled as buttons, not interactive <button> elements, so applying
// buttonVariants()'s className directly to the anchor is simpler and avoids
// any Base UI render-prop friction for what's fundamentally navigation.

import { Card, CardContent } from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Hero() {
  return (
    <div className="mx-auto max-w-2xl px-4 pt-16 pb-10 text-center sm:pt-24">
      <div className="text-xs font-medium tracking-widest text-muted uppercase">PostMortem AI</div>
      <h1 className="mt-3 text-4xl leading-tight font-semibold tracking-tight text-ink sm:text-5xl">
        Postmortems that cite their evidence.
      </h1>
      <p className="mx-auto mt-4 max-w-xl text-lg text-muted">
        Record what actually happened during an incident. Get an AI-drafted postmortem where every claim points back
        to a real, recorded entry — anything the evidence doesn&apos;t support is marked unsupported, never
        invented.
      </p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-x-4 gap-y-3">
        <a href="#get-started" className={cn(buttonVariants({ size: "lg" }), "h-auto px-6 py-2.5 text-sm")}>
          Get started
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
    <div className="mx-auto max-w-2xl px-4 pb-6">
      <Card>
        <CardContent>
          <div className="text-xs font-medium tracking-widest text-muted uppercase">What "grounded" actually means</div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <p className="text-xs font-medium text-accent">Kept -- cites real evidence</p>
              <p className="mt-1 rounded-md bg-paper px-3 py-2 text-sm text-ink">
                "Latency rose from 180ms to 4200ms starting 14:04 UTC, correlated with deploy #482.
                <span className="text-muted"> [2]</span>"
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-red-600">Dropped -- no citation exists</p>
              <p className="mt-1 rounded-md bg-paper px-3 py-2 text-sm text-muted italic">
                "Not established by the recorded evidence."
                <span className="mt-1 block text-xs text-muted not-italic">
                  (what a claim like "this cost the company $40,000" becomes, if no evidence entry says so)
                </span>
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

const steps = [
  {
    title: "1. Record evidence",
    body: "Alerts, deploys, metrics, human notes, customer reports — timestamped entries, not a blank text box.",
  },
  {
    title: "2. Generate a grounded draft",
    body: "The model cites which evidence entry backs every claim. Code checks every citation independently before anything is stored — a claim with no valid citation is replaced with a fixed unsupported marker, never kept.",
  },
  {
    title: "3. A human approves, then it publishes",
    body: "Publishing always records a real, named approver. The database itself refuses to mark a postmortem published without one.",
  },
];

export function HowItWorks() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-6">
      <div className="grid gap-4 sm:grid-cols-3">
        {steps.map((step) => (
          <Card key={step.title}>
            <CardContent>
              <h3 className="text-sm font-semibold text-ink">{step.title}</h3>
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
    <div className="mx-auto max-w-2xl px-4 pt-2 pb-16">
      <div className="text-xs font-medium tracking-widest text-muted uppercase">What this isn&apos;t</div>
      <ul className="mt-2 space-y-1.5 pl-5 text-sm text-muted marker:text-line">
        {notes.map((item) => (
          <li key={item} className="list-disc">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
