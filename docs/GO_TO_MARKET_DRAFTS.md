# Go-to-market drafts (2026-08-27)

Everything below is written to be true today, verified live against production this session.
Don't add numbers we haven't actually measured (quality scores, uptime %, "N companies use this") —
if a real number becomes available later (a real testimonial, a real usage stat), add it then.

---

## Show HN post

**Title:**
Show HN: Postmortem AI – drafts incident postmortems, cites the evidence you gave it or leaves it blank

**Body:**

I built this because every postmortem I've ever written started the same way: open a blank doc,
try to remember the timeline, guess at the impact, and hope I didn't misremember the root cause.

How it works:

1. You record evidence as the incident happens — an alert, a log line, a deploy note, a manual
   observation. Or it arrives automatically: every account gets a webhook URL, so your monitoring
   tool can POST evidence directly as things happen.
2. When you're ready, it drafts a postmortem — summary, root cause, detection, resolution,
   contributing factors — grounded only in that evidence.
3. Every claim in the draft is checked against the evidence list before it's ever shown to you.
   If a sentence doesn't trace back to a real, numbered piece of evidence you gave it, it's
   replaced with a fixed "Not established by the recorded evidence" marker instead of being left
   in. This is checked in code, not just asked of the model — the verification step can only
   remove or replace text, never add anything.
4. Nothing publishes without a real, named human clicking approve. The database itself won't let
   a postmortem move to "published" without an approver on record — it's a hard constraint, not a
   UI convention.

Every account gets one full incident free — record evidence, run extraction, draft, no card
required. Publishing (making it a permanent citable record) and a second incident need a paid
plan.

It's a real, live, single-developer product — not a funded startup, not a big team. I'd genuinely
like feedback, especially from anyone who's had to write one of these under pressure and can tell
me where the grounding falls short.

[link]

---

## Cold outreach email template

**Subject:** Ran your [date] outage through a postmortem tool — sending you the output

Hi [name],

I read the writeup your team posted about the [service] outage on [date] — [one specific detail
that shows you actually read it, e.g. "the rollback at 14:51 UTC after the currency-field bug"].

I've been building a tool that drafts postmortems from recorded evidence rather than free
generation — every sentence in the output is checked against the evidence you gave it before
being shown, and anything that isn't traceable gets replaced with a flagged placeholder instead
of a plausible-sounding guess. I ran the public details from your writeup through it and I'm
attaching what it produced, in case it's useful as a comparison point — not because I'm assuming
it's better than what you already wrote, genuinely curious what you think given you know the
incident firsthand.

If it's useful, the free tier covers one full incident with no card needed:
[link]. If not, I'd take five minutes of "here's what's wrong with it" over silence any day.

[name]

---

## Landing page one-liner (if not already this direct)

Current framing should lead with, above the fold, in this order:
1. What it does in one sentence (drafts a postmortem from evidence you actually recorded)
2. The grounding guarantee in one sentence (every claim is checked against your evidence, or
   marked unsupported — never invented)
3. "Your first incident is free" — no card, no signup friction beyond email+password

Don't lead with pricing tiers, feature lists, or comparison tables — none of that is what gets a
first click to convert. Verify this is actually the current above-the-fold copy before assuming
it needs rewriting.
