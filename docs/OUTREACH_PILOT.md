# Outreach pilot: 20 prospects in 14 days

Written 2026-09-11. The product is complete enough; the funnel data says
volume is the only problem (≈4 visitors/day, ≈3 signups/day since the free
trial came back, 2 customers ever). This is the founder's checklist for two
weeks of talking to real prospects. Everything here is executable from a
laptop with no new software. The cold email itself is in
`GO_TO_MARKET_DRAFTS.md`; this file is the process around it.

**The single measurement this pilot exists to get:** *how long does a
postmortem take your team today, and what is the worst part of it?* Every
conversation must end with an answer to that. Twenty answers turn "faster
postmortems" from an abstract claim into a number the homepage can state
honestly.

---

## 1. Who to contact (and where to find them without buying a list)

Target the people who have **already written a public postmortem**. They
have felt the pain, they can judge the output, and the first email can be
about *their* incident instead of about us.

Where public postmortems come from, in order of yield:

0. **https://postmortem.io** -- a public library of real postmortems,
   browsable by company and date. Filter to the last year, skip the
   hyperscalers, keep the ones with a named author. Ten minutes gets ten
   rows.
1. **Company engineering blogs** -- search `site:<company>.com postmortem`
   or `incident report` for any SaaS company you have heard of. The author
   byline is the prospect.
2. **Status pages** -- `status.<company>.com` incident history; the
   "postmortem" links there usually name a team, not a person. Find the
   platform/SRE lead on LinkedIn.
3. **GitHub** -- search `postmortem` in repos named `*-incidents`,
   `*-postmortems`, `sre-*`. The committer is the prospect.
4. **The two posts already on our site** show the shape: Cloudflare and
   GitHub publish these; so do Slack, Reddit, Discord, Notion, Vercel,
   Supabase, Linear, PostHog, Sentry and hundreds of smaller companies.

Qualification, one line each -- stop if any is "no":

- They published a postmortem in the last 12 months (they care).
- 20 to 500 engineers (big enough to have incidents, small enough that one
  person can say yes).
- The prospect wrote or reviewed the postmortem (they own the pain).

Fill the tracker (`outreach-pilot-tracker.csv`) as you go. That file is the
CRM. Do not build or buy one for 20 rows.

## 2. The sequence

Two touches, seven days apart. Personal address, plain text, no images, no
tracking links. Send from your own name.

**Touch 1 -- the question (day 0).** Ask, don't pitch.

> Subject: your [month] postmortem -- one question
>
> Hi [first name],
>
> I read your team's writeup on the [date] [service] incident -- [one
> specific detail from it, e.g. "the 90 minutes on Workers KV before the
> config file turned out to be the trigger"]. It's one of the clearer ones
> I've read this year.
>
> One question, because I'm trying to understand this properly: roughly
> how long did that document take from incident end to published, and
> which part of it was the worst to produce?
>
> I build a tool in this space, but I'm not asking you to look at it -- I'm
> asking because twenty honest answers to that question are worth more to
> me right now than twenty demos.
>
> [your name]
> [one line: who you are, where you are]

**Touch 2 -- the output (day 7, only if no reply).** This is the email
already in `GO_TO_MARKET_DRAFTS.md` ("Ran your [date] outage through a
postmortem tool -- sending you the output"). Before sending it, run their
published timeline through the product yourself -- you are the founder,
your account is not paywalled -- and attach the Markdown export
(**Download as Markdown** in the Draft card). Every line in that export
cites their own evidence; the "unsupported claims dropped" count at the
bottom is the thing to point at.

If they reply to touch 1, skip touch 2 and ask for 15 minutes.

## 3. The 15-minute call

Five questions. Write the answers in the tracker the same hour.

1. Walk me through the last postmortem you wrote -- from "incident over" to
   "document published". How many hours, across how many people?
2. Which part took longest: gathering the timeline, writing, review, or
   getting people to agree?
3. What happens to the action items afterwards? Who checks?
4. What would make you distrust an AI-drafted version of that document?
5. If a draft showed up an hour after the incident with every sentence
   linked to a log line, alert or message -- and honest gaps where the
   evidence was missing -- what would you still have to do by hand?

Do not demo unless asked. If asked, share the screen and do section 4
below live; it takes three minutes.

What to write down: hours per postmortem (the number), people involved,
tooling (Slack? PagerDuty? Notion?), the answer to question 4 verbatim,
and whether they would pay ₹999 / $15 a month or would prefer to pay per
incident. That last answer decides pricing (section 5) -- not a guess.

## 4. The 2-minute demo, recorded once

Record with QuickTime (File → New Screen Recording) or Loom. One take is
fine; nobody expects polish from a founder. Use the Cloudflare 18 Nov 2025
timeline from `/blog/cloudflare-outages-2025` as the evidence -- it is
public, real, and already verified verbatim.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Homepage, signed in, empty incident list | "This is PostMortem AI. I'm going to draft a postmortem for a real outage -- Cloudflare's, from November -- using only what Cloudflare published." |
| 0:15 | New incident: title, sev1, impact line | "Title, severity, the one-line impact. That's the only thing I write." |
| 0:30 | Paste the timeline rows into the evidence box and click **Extract evidence with AI**, or add 5-6 evidence rows by hand | "The timeline goes in as evidence. Each row is something that was actually recorded -- a deploy, an alert, a message." |
| 1:00 | Click **Generate draft**; wait | "Now it drafts. The rule: every sentence must cite one of those rows, and a sentence it can't cite is dropped, not kept." |
| 1:15 | Scroll the draft: summary, root cause, contributing factors, action items | "Summary, root cause, contributing factors, action items with an owner -- and here, the count of claims it tried to make and threw away because the evidence didn't support them." |
| 1:40 | Point at a "Not established by the recorded evidence." line if one appears | "Where the evidence doesn't say, it says so. It doesn't guess." |
| 1:50 | **Download as Markdown**, open the file | "And it leaves as a Markdown file for your wiki, evidence numbered, every citation resolved." |
| 2:00 | Pricing page | "First incident is free. Then ₹999 or $15 a month. That's it." |

Put the video on the homepage only after two prospects have said the
demo answered their question 4. Until then it is a link you send.

## 5. Pricing: decided by the answers, not now

Today: one flat plan, ₹999/month in India, $15/month elsewhere, annual
with two months free, first incident free. It is public on `/pricing`, on
the homepage, and self-serve (UPI and wire with human approval; card via
Stripe inside the dashboard). It is not behind "contact us".

The suggestion to price per incident is plausible and untested. Rule for
this pilot: **if at least 3 of the first 10 calls say the monthly fee is
the blocker and per-incident would not be, add a per-incident option.**
If they say the blocker is trust in the output, or that nobody owns the
postmortem process, pricing is not the problem and changing it is
procrastination.

Do not tier by company size before there is a company in each tier.

## 6. What "done" looks like on day 14

- 20 rows in the tracker with a sent date.
- At least 5 answers to the time question, as numbers.
- At least 2 calls.
- One sentence for the homepage that is true because prospects said it,
  e.g. "Teams told us a postmortem takes 3 to 6 hours. This drafts it in
  under a minute, cited." -- only with the real numbers in it.
- A pricing decision made by rule 5, or explicitly deferred.

## 7. What not to do

- No mass mailing, no purchased lists, no automation. Twenty personal
  emails from a founder is normal; two hundred templated ones is spam and
  gets the domain blocked.
- No fabricated stats ("saves 4 hours", "used by N teams") anywhere until
  measured.
- No new features during the pilot unless a prospect's answer to question
  5 names one.
