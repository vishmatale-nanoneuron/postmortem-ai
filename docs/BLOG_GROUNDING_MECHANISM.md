# How postmortem drafting is grounded, mechanically

Most "AI-generated" postmortem tools ask a model to write a plausible-sounding report and hope
it stays honest. We don't rely on hoping. Here's the actual two-layer mechanism, in enough detail
that you could verify it yourself against the code.

## The problem with a single unsupervised generation call

Ask a language model to write a postmortem from a vague description of an incident and it will
happily invent specifics: a plausible root cause, a plausible timeline, a plausible impact number.
None of it is checked against anything real. It reads well. It just isn't necessarily true.

## Layer one: cited generation

When you draft a postmortem, the model is given your incident's recorded evidence — every entry
you logged or that arrived via webhook — each one numbered. The system prompt instructs it to
cite the entry number behind every claim it makes, and explicitly to leave a section unsupported
rather than infer beyond what the evidence says.

This alone isn't the guarantee. A model can still cite incorrectly, or claim a citation supports
something it doesn't.

## Layer two: independent verification

After the model responds, code — not another model call, not a second opinion, plain
deterministic code — checks every citation against the real evidence list before anything is
stored:

- Is the cited entry number real? (Not missing, not out of range.)
- Is it the right type of entry for what's being claimed?

If a claim's citation fails either check, that claim is replaced with a fixed marker —
`"Not established by the recorded evidence."` — for the four required sections (summary, root
cause, detection, resolution), or dropped outright for optional lists like contributing factors.

The critical property: this verification step can only remove or replace text the model produced.
It never adds anything. There's no path by which the check itself introduces a new claim.

## The publish gate is a database constraint, not a UI convention

Even a perfectly grounded draft doesn't become a permanent record on its own. Publishing requires
a named human's approval — and this isn't enforced by a "please don't skip this" button in the
frontend. It's a `CHECK` constraint on the table itself: a postmortem cannot be marked `published`
in the database unless `approved_by` and `approved_at` are both set. If every layer of application
code were bypassed entirely — a bug, a compromised session, a direct SQL client — the database
itself still refuses.

## What this doesn't claim

We don't claim the drafts are always excellent, or that grounding makes them un-improvable. A
draft grounded in incomplete evidence will be an incomplete postmortem — the system tells you that
honestly (via the unsupported-claims marker) rather than filling the gap with something invented.
The mechanism's job is narrower and more checkable than "good writing": every claim that survives
either traces to evidence you actually recorded, or is visibly flagged that it doesn't.

---

*Written 2026-08-27. Reflects the implementation as of this date — verify against
`apps/api/app/services/postmortem.py` and the `incident_postmortems` table's constraints in
`supabase/migrations/` if anything here looks stale by the time you're reading it.*
