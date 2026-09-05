# CLAUDE.md

Guidance for Claude Code working in this repository. Everything below describes
what is actually built, verified, and running as of this commit — not a plan,
not a target, not aspirational.

## What this is

PostMortem AI MVP: record incident evidence, generate an AI-drafted postmortem
that cites only that evidence, publish it once a human approves. The core bet
is that a trustworthy AI-generated postmortem needs code-level grounding, not
just a well-worded prompt — see "The grounding algorithm" below.

**Current scope (deliberate):** real email/password auth (see below), a
founder role and a paywall on the actual product work (see "Founder access"
and "Billing / payments" below), but still single-user-per-account, no
organizations/multi-tenant. **Deployed and live** (see "Deployment" below)
— this is not a local-only MVP anymore.

**Production migrations 0006-0008 status**: written, tested locally
against a real Postgres, and the code paths that depend on them
(`subscription_status`, `payment_claims`, founder dashboard, billing) are
already deployed live — but as of this writing those migrations have not
yet been confirmed applied against the real production database, because
`DATABASE_URL` is a Vercel "Sensitive" env var and is permanently
write-only (unreadable via CLI/dashboard/API by anyone, including the
person who set it, once saved that way) — see "Deployment" below for why
that matters and how to unblock it. Until they're applied, `/v1/auth/register`,
`/v1/auth/login`, and everything downstream of them 500 in production. Check
this by hand (`curl -X POST https://postmortem-ai-api.vercel.app/v1/auth/register
-d '{"email":"x@example.com","password":"testtesttest"}'` — 500 means still
pending, 201/409 means it's done) rather than assuming either state.

## Deployment

Live at `https://www.nanoneuron.ai/` (frontend) and
`https://postmortem-ai-api.vercel.app` (backend). Two separate Vercel
projects under the `nanoneuronais-projects` team:

- `postmortem-ai-web` — Next.js frontend. Deployed via `vercel deploy --prod
  --cwd apps/web` (not GitHub auto-deploy -- the GitHub App wasn't
  connectable from this account at setup time, see the "GitHub auto-deploy"
  note below). `NEXT_PUBLIC_API_BASE` is baked in at **build** time, not
  read at runtime -- changing it requires a redeploy, not just an env var
  update taking effect on the next request.
- `postmortem-ai-api` — FastAPI backend, Framework Preset `FastAPI`
  (Vercel's Python/uv-based builder). Requires a top-level `app = create_app()`
  instance in `app/main.py` -- the `--factory` uvicorn flag used for local
  dev isn't how Vercel loads it.
- **`apps/api/package.json` exists solely as a workaround**: this Vercel
  team has an enforced Install Command of `bun install --frozen-lockfile`
  applied to every project regardless of framework (confirmed via a real
  failed deploy: `Bun could not find a package.json file to install
  from`), and project-level Install Command overrides via the Vercel API
  did not take effect. An empty `package.json` with zero dependencies lets
  that enforced step succeed as a no-op (`bun install --frozen-lockfile`
  exits 0 against it even with no `bun.lock` present) so the real Python
  dependency install (`requirements.txt`, via the FastAPI preset) can run
  afterward. Don't delete this file assuming it's dead weight.
- Production Postgres: a dedicated Supabase project (`postmortem-ai`, ref
  `zrfhwvwofaxywjcfccnk`), **separate from `nanoneuron-software-company`'s
  database** — deliberate, keeps the two products' data cleanly apart
  regardless of what domain points where.
- Domain history: `www.nanoneuron.ai` previously pointed to
  `nanoneuron-software-company`'s frontend (`gst-notice-agent` Vercel
  project); confirmed with the user that nothing real (no real clients, no
  real payments) existed there before repointing it to postmortem-ai. The
  apex `nanoneuron.ai` (no `www`) **intentionally still points to the old
  project** — only `www.nanoneuron.ai` was authorized to move, so the
  apex's redirect-to-www was removed rather than silently also moved. If
  the apex should also move to postmortem-ai later, that's a deliberate
  follow-up, not an oversight.
- **AI agent deployment blocking**: this Vercel team appears to flag
  CLI-initiated deployments from a detected AI-agent actor and hold them
  as `readyState: BLOCKED` pending some team-level condition (found via a
  real blocked deployment, `errorLink` pointing at Vercel's
  project-collaboration docs). Cleared once during this session after the
  user checked the team dashboard; the exact setting that unblocked it
  wasn't confirmed. If a future deploy gets stuck in `BLOCKED`, check the
  team's deployment-protection/security settings before assuming it's a
  code problem.
- **Vercel "Sensitive" env vars are permanently write-only — confirmed the
  hard way**: every env var set via `vercel env add` on this project
  (`DATABASE_URL`, `STRIPE_SECRET_KEY`, the UPI/wire settings, etc.)
  defaults to Sensitive visibility. Once saved that way, its value can
  never be read back again by anyone or anything — not `vercel env ls`,
  not `vercel env pull` (prints `[SENSITIVE]` as a literal string, which
  `scripts/migrate.mjs` then fails to parse as a URL), not the dashboard,
  regardless of who's running the command or whether it's an agent session
  or the account owner's own terminal (verified both ways). This is a real
  Vercel platform guarantee, not an agent-specific restriction — don't
  assume switching to a "regular" terminal session fixes it. **The only
  way to recover a value set this way is from its original source** (here,
  Supabase's own dashboard → Project Settings → Database → Connection
  string, for `DATABASE_URL`) — there is no Vercel-side recovery path.
  If you need to read back an env var's value later, set it as
  "Non-sensitive" instead (accepting the tradeoff that it's then visible
  in the dashboard/CLI/logs).
- **Vercel's own MCP server connects fine; Supabase's does not (as of this
  session)** — `claude mcp add-json`/`claude mcp add --scope project`
  against `https://mcp.supabase.com/mcp?project_ref=...` repeatedly
  returned `{"message":"resource: Resource must be a valid MCP endpoint"}`
  even with a correctly project-scoped config (see `.mcp.json` at repo
  root). Also, this session runs inside a VS Code extension, and
  Supabase's own setup docs state authentication must happen in "a
  regular terminal, not an IDE extension" — and even a successful
  terminal-side authentication would authorize a *different* running
  session, not necessarily the one doing the work. Don't assume Supabase
  MCP is a faster path than the dashboard without re-verifying this is
  fixed.

## Stack

- **Backend:** `apps/api/` — FastAPI (Python 3.13), `psycopg[binary,pool]`
  (async connection pool), `pydantic-settings` for config, the real
  `google-genai` SDK (Gemini) for drafting (no mock in production code).
- **Frontend:** `apps/web/` — Next.js 15.5 (App Router), TypeScript, one page
  (`app/workspace.tsx`) calling the FastAPI backend directly via `fetch`
  (`app/api.ts`), no proxy layer. Client-side validation via `zod`
  (`app/validation.ts`) mirrors the real backend Pydantic constraints
  (field lengths, enum values) so a bad form submission fails fast in the
  browser — but this is a UX layer only; the backend's own validation is
  still the actual source of truth and is never bypassed or trusted less.
- **Database:** Postgres, migrations in `supabase/migrations/*.sql`, applied
  forward-only by `scripts/migrate.mjs` (no checksum/baseline machinery —
  single-developer MVP against one dev database; add that back if this grows
  multiple contributors/environments).
- **Package manager: Bun**, not npm — `bun.lock` at repo root and in
  `apps/web`, no `package-lock.json` anywhere. Matches this team's
  convention (and Vercel's own enforced Install Command for this account —
  see "Deployment" below).

## Commands

```bash
# Backend
python3.13 -m venv .venv && .venv/bin/pip install -r apps/api/requirements.txt
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/postmortem_ai \
  GEMINI_API_KEY=<real key> \
  SESSION_SECRET=<real random secret, e.g. python3 -c "import secrets;print(secrets.token_hex(32))"> \
  COOKIE_SECURE=false \
  .venv/bin/uvicorn app.main:create_app --factory --app-dir apps/api --reload

# Backend tests (grounding tests need no DB; route tests need TEST_DATABASE_URL)
.venv/bin/python -m pytest apps/api/tests -q
.venv/bin/ruff check apps/api

# Database (bun, not npm -- this repo uses bun.lock, no package-lock.json)
bun install  # postgres client for scripts/migrate.mjs
DATABASE_URL=... DATABASE_SSL_MODE=disable bun run scripts/migrate.mjs

# Frontend
bun install --cwd apps/web
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 bun run --cwd apps/web dev
bun run --cwd apps/web build  # NEXT_PUBLIC_API_BASE is baked in at build time, not read at runtime

# Deploy (no GitHub auto-deploy configured -- see Deployment above)
npx vercel deploy --prod --yes --cwd apps/api   # backend
npx vercel deploy --prod --yes --cwd apps/web   # frontend, only after backend if NEXT_PUBLIC_API_BASE changed

# SEO: push real URLs to Bing/Yandex immediately (no account needed --
# Google doesn't participate in IndexNow; Search Console is still the
# real fix for Google specifically). Run after a real content change
# (new blog post, a newly published postmortem), not on every deploy.
node scripts/submit-indexnow.mjs
```

## Authentication

Email + password, session cookie (not a bearer token — this is a browser-only
frontend). Design reused (not code copied) from `nanoneuron-software-company`'s
auth system, reviewed and found sound earlier in the session that built this:

- `apps/api/app/security/passwords.py` — scrypt password hashing (stdlib
  `hashlib.scrypt`, no new dependency), random per-password salt, stored as
  `scrypt$<salt_b64>$<hash_b64>`.
- `apps/api/app/security/tokens.py` — a real RFC 7519 JWT (via `PyJWT`,
  `HS256`), not a hand-rolled format. `sub`/`email`/`iat`/`exp` claims;
  `jwt.decode` is always called with an explicit `algorithms=[ALGORITHM]`
  allowlist, which is what actually blocks the classic `alg=none` forged-
  token vulnerability (`test_the_none_algorithm_is_never_accepted` proves
  it against a real forged token, not just by inspection). The original
  version of this file was a hand-rolled HMAC-signed format — replaced with
  a real JWT library on request; **this rotation invalidates every
  previously-issued session cookie** (old tokens don't parse as JWTs) — a
  one-time forced logout for anyone signed in, not a data loss.
- `apps/api/app/auth.py` — `current_user` FastAPI dependency: reads the
  `session_token` cookie, verifies it, loads the user row, 401 on any
  failure. Every route in `apps/api/app/api/v1/postmortems.py` depends on
  this and scopes its query by `user.email` — there is no more hardcoded
  identity anywhere in that file.
- `apps/api/app/api/v1/auth.py` — register/login/logout/me. Login failure
  (wrong password OR unregistered email) returns the exact same generic 401
  message either way, so a failed attempt can't be used to enumerate
  registered emails.
- `Settings.session_secret` has no default — a real secret is required, same
  "no fabricated/guessed credentials" stance as `gemini_api_key`.
  `Settings.cookie_secure` defaults to `true`; set `COOKIE_SECURE=false` for
  local dev over plain `http://`.
- **Verified cross-user isolation manually, not just asserted**: registered
  three real users against a live server, had user 2 create an incident,
  confirmed user 3 gets a 404 (not a leak) on it — see
  `test_a_different_user_cannot_see_or_act_on_this_incident` in
  `test_postmortem_routes.py` for the same check as an automated test.
- `apps/api/app/security/rate_limit.py` — DB-backed login rate limiting
  (`login_attempts` table, `0005_login_attempts.sql`), not in-memory: this
  backend runs as Vercel serverless functions with no shared process memory
  across instances/cold starts, so an in-process counter would silently do
  nothing in production. Per-email lockout (5 failures / 15 min) is the
  primary defense; a looser per-IP lockout (20 failures / 15 min) catches
  credential stuffing across many emails from one source. Login also closes
  a real timing side-channel: an unregistered email now still runs a full
  `scrypt` verify against a fixed decoy hash instead of returning early, so
  "no such account" and "wrong password" take the same time. **Verified
  live**: 5 real wrong-password attempts against the production API
  returned 401, the 6th (with the *correct* password) returned 429.

**Deferred, not built:** password reset, email verification, OAuth/SSO,
multi-tenant organizations.

## Founder access

Not a separate account type or password — `User.is_founder` (`apps/api/app/auth.py`)
is a constant-time comparison of the authenticated account's email against
`Settings.founder_email` (defaults to `vish.matale@gmail.com`; override via
`FOUNDER_EMAIL`). Registering or logging in with that exact email *is* the
founder login. `current_founder` (also `auth.py`) 403s anyone else; it's
independent of subscription state (a founder never needs to pay — see
"Billing / payments" below).

- `apps/web/app/founder/` — a separate, unlinked, `noindex`'d login/register
  page (not the public landing page's `AuthGate`). Denies access generically
  (no account-existence leak) and signs a session back out immediately if
  it isn't the founder account, rather than leaving a non-founder session
  sitting on that page.
- `apps/api/app/api/v1/founder.py` — `GET /v1/founder/summary` (platform-
  wide aggregates: users, incidents, postmortems, `ai_runs` success/
  failure/latency, recent signups) and the payment-claims review routes
  (see "Billing / payments").
- **The actual security-sensitive moment**: the founder email is a fixed,
  known value, and `register()` is first-come-first-served on a unique
  email — whoever registers it first owns the founder account. Every
  registration attempt against that email (successful or a 409 conflict)
  is logged (`founder_email_registration_succeeded`/`_conflict` in
  `api/v1/auth.py`) so this would be visible if it ever happened. Claim it
  immediately once the account doesn't already exist — don't leave that
  window open.

## Dashboards

- **Client** (`workspace.tsx`'s `IncidentWorkspace`): `GET
  /v1/postmortems/summary` — per-account counts (open/resolved incidents,
  drafted/published postmortems) plus a "mark resolved/reopen" action via
  `PATCH /v1/postmortems/incidents/{id}/status`. Closed a real gap found
  while building this: `incidents.status` previously never transitioned
  away from `'open'` anywhere in the codebase.
- **Founder** (`workspace.tsx`'s `FounderDashboard`, shown automatically
  when `user.is_founder`): the platform-wide summary above, plus a
  payment-claims review list (approve/reject buttons, see below).

## Billing / payments

The product's actual work — creating incidents, recording evidence,
drafting, publishing, changing status — requires `User.has_active_subscription`
(`require_active_subscription` dependency, `apps/api/app/auth.py`); read-only
routes (list/summary/get) stay reachable so a lapsed account can still see
its own history. Founders are exempt (see "Founder access" above). Two
independent payment paths feed the same `users.subscription_status` field:

- **Stripe** (`apps/api/app/api/v1/billing.py`, `/v1/billing/checkout`,
  `/portal`, `/webhook`) — built and tested against a real Stripe sandbox
  via the Vercel Marketplace integration, but **not live**: going live
  needs Indian business KYC (a PAN) that hasn't been completed. All three
  `STRIPE_*` settings are `Optional` for exactly this reason — unset in
  production, and those three routes 503 with a pointer to UPI rather than
  the app failing to boot. Webhook handles `checkout.session.completed`,
  `customer.subscription.updated`/`.deleted`, `invoice.payment_failed`;
  signature-verified via `STRIPE_WEBHOOK_SECRET`; no hardcoded
  `payment_method_types` (Stripe determines eligible methods dynamically
  from Dashboard settings — this is also why enabling UPI as a Stripe
  payment method later needs no code change, only Dashboard config, once
  KYC is done).
- **Manual, human-verified** (`payment_claims` table, `0007`/`0008`
  migrations) — the actual live path today. A client pays directly and
  submits a transaction reference; the founder reviews and
  approves/rejects from the founder dashboard
  (`POST /v1/founder/payment-claims/{id}/approve`, which is what actually
  sets `subscription_status='active'` plus a 30-day manual renewal
  window — there is no gateway enforcing a real billing cycle here).
  Submitting a claim does **not** itself grant access.
  - **UPI** (`FOUNDER_UPI_ID`, `SUBSCRIPTION_PRICE_INR`, default ₹999/mo)
    — India-only; UPI requires an Indian bank account on the payer's side,
    there is no workaround for international clients.
  - **International SWIFT wire** (`FOUNDER_BANK_*`, `WIRE_{USD,GBP,EUR}_*`
    settings) — the second manual method, for clients UPI can't reach.
    Beneficiary details are shared across currencies; correspondent
    bank/SWIFT/nostro/ABA-or-IBAN differ per currency. `payment_claims.method`
    (`'upi'`/`'wire'`) and `.currency` distinguish the two; `.amount_inr`
    predates the wire method and is kept as the generic amount column
    (name is a historical artifact, not a currency guarantee) since
    migrations here are additive-only.

## The grounding algorithm (the actual point of this project)

Two-layer defense, not one:

1. **Prompt-side** (`SYSTEM_PROMPT` in `apps/api/app/services/postmortem.py`):
   the model is told to cite every claim by evidence number, and that an
   empty/uncited section is the *correct* answer when evidence doesn't
   support one — not a failure to route around.
2. **Code-side enforcement** (`ground_draft()`, same file): after the model
   responds, code decides what survives, not the prompt. A claim with no
   valid citation (missing, out of range, non-integer, boolean) is replaced
   with a fixed `"Not established by the recorded evidence."` marker for the
   four required sections (summary/root_cause/detection/resolution), or
   simply dropped for contributing factors and actions. **This function can
   only ever remove or replace the model's own text — it can never add new
   text.** That property is checked with a Hypothesis property test
   (`test_grounding_only_ever_removes_never_adds_property` in
   `apps/api/tests/test_postmortem_grounding.py`, 300 adversarial examples),
   not just fixed cases.

A model that ignores every word of the system prompt still cannot produce an
invented, uncited claim that survives `ground_draft`.

## Schema (`supabase/migrations/`)

- `incidents` — `id`, `client_email` (always the demo identity for now),
  `title`, `severity`, `status`, `impact`.
- `incident_evidence` — one row per recorded observation, `source` CHECK'd to
  a fixed enum, `summary`/`authorized_by` non-blank CHECKs.
- `incident_postmortems` — the four grounded sections, `contributing_factors`
  and `cited_evidence_ids` as `jsonb` arrays, `unsupported_claims_dropped`.
  **Key constraint:** `CHECK (status <> 'published' OR (approved_by IS NOT
  NULL AND approved_at IS NOT NULL))` — publishing requires a named human
  approver, enforced by the database itself, not just the API layer.
- `postmortem_actions` — generated (has `evidence_id`) or human-added
  (`evidence_id NULL`) remediation actions.

## Route behavior worth knowing before changing `apps/api/app/api/v1/postmortems.py`

- `load_evidence()` bounds the query to the `MAX_DRAFT_EVIDENCE_ENTRIES`
  (500) most recent entries by `occurred_at`, re-sorted chronologically
  before rendering — an incident with more evidence than that would
  otherwise blow the model's context on a single `/draft` call.
- `POST .../draft` catches both `httpx.HTTPError` **and**
  `google.genai.errors.APIError` as a clean 502 — these are NOT the same
  exception hierarchy (`APIError` is the Gemini SDK's own base for
  auth/rate-limit/server failures). The equivalent gap was originally found
  against Anthropic (a live smoke test with an invalid key surfaced an
  uncaught 500 before that catch was added); carried forward proactively
  when the provider was swapped to Gemini rather than waiting to
  rediscover it — don't remove it assuming `httpx.HTTPError` alone is
  sufficient.
- Re-drafting an already-published postmortem resets it to `status='draft'`
  (`approved_by`/`approved_at` cleared) via the `ON CONFLICT (incident_id) DO
  UPDATE` clause — a redraft is never silently published.
- Only *generated* actions (`evidence_id IS NOT NULL`) are replaced on
  redraft; any human-added action (`evidence_id NULL`) is preserved.

## Known gaps (not fixed, in scope for a later phase — don't assume otherwise)

- Real auth exists now (see "Authentication" above), but no multi-tenant
  organizations, password reset, email verification, or OAuth/SSO.
- Production migrations 0006-0008 (subscription/payment-claims tables) not
  yet confirmed applied — see "Production migrations 0006-0008 status" at
  the top of this file for why and how to check.
- Stripe billing is built and tested (sandbox) but not live — needs Indian
  business KYC (PAN). Manual UPI/wire payment is the real live path; see
  "Billing / payments" above.
- `npm audit` on `apps/web` shows two remaining high-severity transitive
  vulnerabilities (`postcss`, `sharp`, pulled in by Next.js's build
  tooling) whose fix requires Next.js 16 (a breaking major-version jump).
  The critical RCE-class CVE that existed on the original `next@15.1.4` pin
  is already fixed (bumped to `15.5.23`); the remaining two are build-time
  only and lower priority, but worth resolving before any real deployment.
