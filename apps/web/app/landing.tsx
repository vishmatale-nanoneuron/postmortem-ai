// Marketing/branding content for logged-out visitors. Deliberately a pure,
// stateless component -- all the sign-in state lives in workspace.tsx's
// AuthGate, which renders alongside this. Every claim made here matches
// public/llms.txt word for word in substance: the grounding guarantee, the
// honest "what this doesn't do" list. Never let this page and llms.txt
// drift -- an AI crawler and a human visitor should learn the same facts.

const section: React.CSSProperties = { maxWidth: 720, margin: "0 auto", padding: "0 16px" };
const eyebrow: React.CSSProperties = { fontSize: 12, letterSpacing: 1, textTransform: "uppercase", color: "#8a8a85" };

export function Hero() {
  return (
    <div style={{ ...section, textAlign: "center", padding: "64px 16px 40px" }}>
      <div style={eyebrow}>PostMortem AI</div>
      <h1 style={{ fontSize: 40, lineHeight: 1.15, margin: "12px 0" }}>Postmortems that cite their evidence.</h1>
      <p style={{ fontSize: 17, color: "#444", maxWidth: 520, margin: "0 auto" }}>
        Record what actually happened during an incident. Get an AI-drafted postmortem where every claim points back
        to a real, recorded entry — anything the evidence doesn&apos;t support is marked unsupported, never
        invented.
      </p>
      <a
        href="#get-started"
        style={{
          display: "inline-block",
          marginTop: 20,
          padding: "10px 20px",
          background: "#1a1a1a",
          color: "#fff",
          borderRadius: 6,
          textDecoration: "none",
          fontSize: 14,
        }}
      >
        Get started
      </a>
    </div>
  );
}

export function HowItWorks() {
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
  return (
    <div style={{ ...section, padding: "24px 16px" }}>
      <div style={{ display: "grid", gap: 16 }}>
        {steps.map((step) => (
          <div key={step.title} style={{ border: "1px solid #d8d8d3", borderRadius: 8, padding: 16 }}>
            <h3 style={{ margin: "0 0 6px", fontSize: 15 }}>{step.title}</h3>
            <p style={{ margin: 0, color: "#444", fontSize: 14 }}>{step.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function WhatThisIsnt() {
  const items = [
    "Doesn't auto-publish anything — publishing is always a deliberate, named human action.",
    "Doesn't estimate cost, revenue, or customer-impact figures the evidence didn't state.",
    "Doesn't integrate with PagerDuty, Datadog, or other monitoring tools yet — evidence is entered directly.",
    "Doesn't support teams or organizations yet — each account is a single user's own incidents.",
  ];
  return (
    <div style={{ ...section, padding: "8px 16px 40px" }}>
      <div style={eyebrow}>What this isn&apos;t</div>
      <ul style={{ color: "#444", fontSize: 14, paddingLeft: 20, margin: "8px 0 0" }}>
        {items.map((item) => (
          <li key={item} style={{ marginBottom: 6 }}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
