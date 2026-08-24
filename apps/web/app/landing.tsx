// Marketing/branding content for logged-out visitors. Deliberately a pure,
// stateless component -- all the sign-in state lives in workspace.tsx's
// AuthGate, which renders alongside this. Every claim made here matches
// public/llms.txt word for word in substance: the grounding guarantee, the
// honest "what this doesn't do" list. Never let this page and llms.txt
// drift -- an AI crawler and a human visitor should learn the same facts.

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
      <a
        href="#get-started"
        className="mt-8 inline-block rounded-md bg-ink px-6 py-2.5 text-sm font-medium text-paper transition hover:bg-ink/90"
      >
        Get started
      </a>
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
          <div key={step.title} className="rounded-lg border border-line bg-white p-4 shadow-sm">
            <h3 className="text-sm font-semibold text-ink">{step.title}</h3>
            <p className="mt-1.5 text-sm text-muted">{step.body}</p>
          </div>
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
