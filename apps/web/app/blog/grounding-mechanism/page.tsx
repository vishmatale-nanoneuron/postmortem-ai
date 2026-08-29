import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "How postmortem drafting is grounded, mechanically",
  description:
    "The two-layer mechanism behind every AI-drafted postmortem: cited generation, then independent code-level verification of every citation before anything is stored.",
  robots: { index: true, follow: true },
  alternates: { canonical: "/blog/grounding-mechanism" },
};

const card = "rounded-lg border border-line bg-white p-5 shadow-sm mb-4";
const h2 = "mb-2 text-lg font-semibold text-ink";
const p = "text-sm text-muted leading-relaxed mb-2";
const code = "rounded bg-paper px-1.5 py-0.5 font-mono text-xs";

export default function GroundingMechanismPost() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8">
        <div className="text-xs font-medium tracking-widest text-muted uppercase">Engineering</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">
          How postmortem drafting is grounded, mechanically
        </h1>
        <p className="mt-2 text-sm text-muted">
          Written to be checkable against the running code, not just asserted. Short version:{" "}
          <Link className="underline underline-offset-2" href="/docs">
            /docs
          </Link>
          .
        </p>
      </div>

      <section className={card}>
        <h2 className={h2}>The problem with a single unsupervised generation call</h2>
        <p className={p}>
          Ask a language model to write a postmortem from a vague description of an incident and it will happily
          invent specifics: a plausible root cause, a plausible timeline, a plausible impact number. None of it is
          checked against anything real. It reads well. It just isn&apos;t necessarily true.
        </p>
      </section>

      <section className={card}>
        <h2 className={h2}>Layer one: cited generation</h2>
        <p className={p}>
          When you draft a postmortem, the model is given your incident&apos;s recorded evidence — every entry you
          logged or that arrived via webhook — each one numbered. The system prompt instructs it to cite the entry
          number behind every claim it makes, and explicitly to leave a section unsupported rather than infer
          beyond what the evidence says.
        </p>
        <p className={p}>
          This alone isn&apos;t the guarantee. A model can still cite incorrectly, or claim a citation supports
          something it doesn&apos;t.
        </p>
      </section>

      <section className={card}>
        <h2 className={h2}>Layer two: independent verification</h2>
        <p className={p}>
          After the model responds, code — not another model call, plain deterministic code — checks every citation
          against the real evidence list before anything is stored: is the cited entry number real (not missing,
          not out of range)? Is it the right kind of entry for what&apos;s being claimed?
        </p>
        <p className={p}>
          If a claim&apos;s citation fails either check, it&apos;s replaced with a fixed marker —{" "}
          <span className={code}>&quot;Not established by the recorded evidence.&quot;</span> — for the four
          required sections, or dropped outright for optional lists like contributing factors. This step can only
          remove or replace the model&apos;s text. It never adds anything.
        </p>
      </section>

      <section className={card}>
        <h2 className={h2}>The publish gate is a database constraint, not a UI convention</h2>
        <p className={p}>
          Even a perfectly grounded draft doesn&apos;t become a permanent record on its own. Publishing requires a
          named human&apos;s approval, enforced by a <span className={code}>CHECK</span> constraint on the table
          itself — a postmortem cannot be marked published in the database unless an approver and a timestamp are
          both set. If every layer of application code were bypassed entirely, the database still refuses.
        </p>
      </section>

      <section className={card}>
        <h2 className={h2}>What this doesn&apos;t claim</h2>
        <p className={p}>
          We don&apos;t claim the drafts are always excellent, or that grounding makes them un-improvable. A draft
          grounded in incomplete evidence will be an incomplete postmortem — the system says so honestly, rather
          than filling the gap with something invented. The mechanism&apos;s job is narrower than &quot;good
          writing&quot;: every claim that survives either traces to evidence you actually recorded, or is visibly
          flagged that it doesn&apos;t.
        </p>
      </section>

      <p className="mt-6 text-xs text-muted">
        <Link className="underline underline-offset-2" href="/">
          Back to PostMortem AI
        </Link>
      </p>
    </main>
  );
}
