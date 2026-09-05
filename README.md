# PostMortem AI

**[www.nanoneuron.ai](https://www.nanoneuron.ai)** — evidence-grounded incident postmortem drafting for DevOps and SRE teams, and freelance SRE/DevOps consultants.

Record what actually happened during an incident. Get an AI-drafted postmortem where every claim
points back to a real, recorded evidence entry — anything the evidence doesn't support is marked
unsupported, never invented.

## The actual guarantee

The drafting model is given numbered evidence entries and told to cite the entry number behind
every claim. Independently of what the model says about its own citations, code re-verifies every
citation against the real evidence list before anything is stored. A claim with no valid citation
is replaced with a fixed `"Not established by the recorded evidence."` marker, or dropped. This
verification step can only remove or replace the model's text — it never adds anything.

Publishing always records a named human approver; the database itself refuses to mark a postmortem
published without one (a `CHECK` constraint, not just application logic).

See it applied to a real, public incident: [what the tool drafted from GitHub's August 2026
outage](https://www.nanoneuron.ai/blog/github-outage-demo) — real, unedited output, not a cherry-picked
demo. The mechanism itself: [how postmortem drafting is grounded, mechanically](https://www.nanoneuron.ai/blog/grounding-mechanism).

## How it works

1. **Record evidence** — alerts, deploys, metrics, human notes, customer reports. Timestamped
   entries, not a blank text box. Arrives by hand, via a generic webhook, or via real PagerDuty/Datadog
   webhook integrations.
2. **Generate a grounded draft** — the model cites which evidence entry backs every claim; code
   checks every citation independently before anything is stored.
3. **A human approves, then it publishes** — publishing always records a real, named approver.

Full detail: [docs](https://www.nanoneuron.ai/docs) · [llms.txt](https://www.nanoneuron.ai/llms.txt) (short) ·
[llms-full.txt](https://www.nanoneuron.ai/llms-full.txt) (complete reference, checked against the running code)

## What this isn't

- Doesn't auto-publish anything — publishing is always a deliberate, named human action.
- Doesn't estimate cost, revenue, or customer-impact figures the evidence didn't state.
- Has real, documented setup for PagerDuty and Datadog webhooks — not for other monitoring vendors
  yet, though any tool that can POST JSON can still use the generic webhook.
- Doesn't support teams or organizations yet — each account is a single user's own incidents.

## Stack

- **Backend**: FastAPI (Python 3.13), deployed as a Vercel serverless function.
- **Frontend**: Next.js 15 (App Router, React 19), deployed to Vercel.
- **Database**: PostgreSQL (Supabase), pgvector for RAG over past incidents.
- **AI**: Google Gemini, with a provider abstraction that made an earlier Anthropic→Gemini swap a
  clean one-file change.
- **Payments**: Stripe (card, self-serve), UPI and international SWIFT wire (manual, founder-reviewed)
  for clients anywhere card payment isn't live yet.

This is a real, running product, not a demo or a starter kit — the source here is public for
transparency into how the grounding mechanism actually works.

## Real examples

Published postmortems, when any exist, are public and citable: [nanoneuron.ai/postmortems](https://www.nanoneuron.ai/postmortems)

## Contact

[vish.matale@gmail.com](mailto:vish.matale@gmail.com)
