# Architecture

What is actually built and running, verified against the code at the time of
writing — not a target state. Where something is incomplete it says so. If this
document and the running system ever disagree, the system is right and this is
stale.

## The bet

A postmortem is only worth reading if you can trust every claim in it. So the
central engineering problem is not "generate text" — it is **making it
structurally impossible to publish a claim the evidence doesn't support**.
Nearly every unusual decision below follows from that.

## Shape

```
Browser  ──►  Next.js 15 (App Router)  ──┐
              apps/web · Vercel          │  direct fetch (CORS)
                                         ▼
AI agent ──►  MCP /mcp (JWT bearer) ──►  FastAPI · Python 3.13
                                         apps/api · Vercel serverless
                                                 │
                                                 ▼
                                    Supabase PostgreSQL + pgvector
                                    29 forward-only migrations
```

Two deployables, one database. The frontend calls FastAPI directly — no
Next.js API-proxy layer, because a second hop adds latency and a second place
for authorization to drift.

## Backend — FastAPI

Nine routers under `apps/api/app/api/v1/`: `auth`, `postmortems`, `billing`,
`founder`, `webhooks`, `bank_alerts`, `integrations`, `internal`.

Layering is deliberate but not dogmatic:

- **Routers** — HTTP concerns plus their domain's logic.
- **`services/`** (`postmortem`, `billing`, `email`) — logic more than one
  caller needs, or that must run outside a request.
- **`ai/`** — model providers behind a `ModelProvider` protocol, with an
  independent circuit breaker per provider. Gemini primary, Claude a configured
  fallback; the abstraction has already survived one real provider swap.
- **`cqrs/`** — see below.
- **`security/`** — scrypt hashing, JWT issue/verify, rate limiting.

### CQRS — where it is used, and where it deliberately is not

Applied where one piece of data has **more than one genuinely different read
shape**, because that is exactly where hand-written queries drift apart:

- **`cqrs/activity.py`** — the account activity log. One command
  (`RecordActivityCommand`) for every write; one query handler
  (`ActivityLogFilter`) serving three readers: a client's own history, the
  founder's cross-account view, and the `list_agent_activity` MCP tool. Keyset
  pagination on `(created_at, id)` rather than `OFFSET`, so pages don't drift
  under concurrent inserts.
- **`billing.py`'s `_CLAIM_COLUMNS`** — the same principle, applied after a code
  review found three of four claim read paths had already drifted and were
  reporting annual claims as monthly.

Deliberately **not** adopted as a global pattern. There is one Postgres instance
and one writer; event sourcing, a message bus, or separate read models would be
ceremony this scale cannot justify. CQRS here means *the read side is defined
once and reused* — nothing more.

## The grounding algorithm — the core invariant

Two independent layers, and the second does not trust the first:

1. The model receives numbered evidence entries and must cite an entry number
   for every claim.
2. **Code — not a second model call — re-verifies every citation** against the
   real evidence list before anything is stored. An invalid citation is replaced
   with a fixed `"Not established by the recorded evidence."` marker for
   required sections, or dropped for optional lists.

This step can only ever *remove or replace* model output. It has no path to add
text. RAG context (similar past postmortems) is retrieved but never numbered and
never citable, so a retrieved incident structurally cannot become a source.

Publishing requires a named human approver, enforced by a database `CHECK`
constraint — not application code, not UI convention. The database itself
refuses to mark a postmortem published without one.

## Agent accountability

Every MCP tool call writes a durable `account_activity_log` row tagged
`source='mcp_agent'`, **including authorization denials** — a `PermissionError`
from a subscription or founder gate is caught, recorded, and re-raised. Without
that, only an agent's successes were ever visible anywhere.

`source` is deliberately **not** a parameter on any HTTP-facing route. It was
once, and a code review found FastAPI treats such a parameter as a *query
parameter* — letting any authenticated caller forge `?source=mcp_agent` and
misattribute their own action to an AI agent. The fix was removing it from the
signature entirely rather than validating its value; a structural test now fails
if it ever returns.

## Data model

15 tables. The ones carrying the product's guarantees:

| Table | Role |
|---|---|
| `incidents`, `incident_evidence` | the recorded facts a draft may cite |
| `incident_postmortems` | drafts/published; `CHECK` enforces a named approver |
| `postmortem_draft_history` | append-only; a re-draft never destroys its predecessor |
| `account_activity_log` | who did what — `web` vs `mcp_agent` |
| `payment_claims`, `payment_claim_events` | claims plus an append-only decision ledger |
| `ai_runs` | every model call: provider, latency, outcome |

Append-only ledgers (`*_events`, `*_history`) exist so financial and editorial
history survives the current-state row moving on.

## Payments — no processor dependency

Stripe is invite-only for Indian businesses, so the working rails are direct
bank transfer: **UPI** (India) and **SWIFT wire** (international). Money moves
bank-to-bank — no aggregator, no percentage fee.

- Prices are always derived **server-side** from the billing period. A
  client-supplied amount is ignored; otherwise anyone could buy a year at the
  monthly price.
- A forwarded bank alert can only mark a claim `bank_verified`. **It can never
  grant access.** Only an explicit founder approval calls
  `activate_manual_subscription`, which has exactly one call site.
- Annual billing exists for wire economics: an `OUR`-charge wire costs the
  sender USD 15–40, which is a >100% surcharge monthly but a one-off annually.

## Frontend — Next.js 15

App Router, overwhelmingly Server Components — only 5 client components in the
whole app. shadcn/ui on Base UI, with app-specific `ink`/`line` button variants
so the design system has a single home. Zod validation mirrors the backend's
Pydantic constraints for fast feedback, but the backend remains the only source
of truth.

A tight CSP is set in `next.config.mjs`: `default-src 'self'`, and no
`unsafe-eval` in production (development relaxes only that one directive,
because Next's dev React Refresh requires it).

## Testing

31 backend test files, 329 tests, run against a **real ephemeral Postgres**
rather than mocks — because most guarantees above are enforced *by the
database*, and a mock cannot enforce a `CHECK` constraint. Tests needing no
database deliberately avoid the `TEST_DATABASE_URL` skip so they run everywhere,
including bare CI.

## Known gaps — stated honestly

- **`postmortem-ai-web` cannot deploy.** Vercel fails every deployment with
  "Resource provisioning failed", including redeploys of previously-successful
  builds. Proven server-side: byte-identical output deploys READY to a different
  project. Frontend work is queued, not shipped.
- **No card payments.** Not an omission — Stripe is invite-only in India, and
  accepting cards independently requires an RBI Payment Aggregator licence
  (₹15 crore net worth).
- **Single-user accounts.** No organisations, teams, or roles.
- **Annual billing has no UI.** The API supports it; the dashboard cannot yet
  select it.
- **Effectively no search traffic.** One indexed URL, and it 404s.
