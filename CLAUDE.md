# CLAUDE.md

Guidance for Claude Code working in this repository. Everything below describes
what is actually built, verified, and running as of this commit — not a plan,
not a target, not aspirational.

## What this is

PostMortem AI MVP: record incident evidence, generate an AI-drafted postmortem
that cites only that evidence, publish it once a human approves. The core bet
is that a trustworthy AI-generated postmortem needs code-level grounding, not
just a well-worded prompt — see "The grounding algorithm" below.

**Current scope (deliberate):** real email/password auth (see below), but
still single-user-per-account, no organizations/multi-tenant, no billing.
**Deployed and live** (see "Deployment" below) — this is not a local-only
MVP anymore.

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

## Stack

- **Backend:** `apps/api/` — FastAPI (Python 3.13), `psycopg[binary,pool]`
  (async connection pool), `pydantic-settings` for config, the real
  `google-genai` SDK (Gemini) for drafting (no mock in production code).
- **Frontend:** `apps/web/` — Next.js 15.5 (App Router), TypeScript, one page
  (`app/workspace.tsx`) calling the FastAPI backend directly via `fetch`
  (`app/api.ts`), no proxy layer.
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
- No deployment configuration (Vercel, Docker, CI) — verified locally only.
- `npm audit` on `apps/web` shows two remaining high-severity transitive
  vulnerabilities (`postcss`, `sharp`, pulled in by Next.js's build
  tooling) whose fix requires Next.js 16 (a breaking major-version jump).
  The critical RCE-class CVE that existed on the original `next@15.1.4` pin
  is already fixed (bumped to `15.5.23`); the remaining two are build-time
  only and lower priority, but worth resolving before any real deployment.
