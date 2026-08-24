# CLAUDE.md

Guidance for Claude Code working in this repository. Everything below describes
what is actually built, verified, and running as of this commit — not a plan,
not a target, not aspirational.

## What this is

PostMortem AI MVP: record incident evidence, generate an AI-drafted postmortem
that cites only that evidence, publish it once a human approves. The core bet
is that a trustworthy AI-generated postmortem needs code-level grounding, not
just a well-worded prompt — see "The grounding algorithm" below.

**Current scope (deliberate):** no auth, no multi-tenant, no billing, not
deployed anywhere. Every route is scoped to one fixed demo identity
(`DEMO_CLIENT_EMAIL` in `apps/api/app/api/v1/postmortems.py`). This exists to
validate the grounding/citation mechanics end-to-end before building anything
else on top of it.

## Stack

- **Backend:** `apps/api/` — FastAPI (Python 3.13), `psycopg[binary,pool]`
  (async connection pool), `pydantic-settings` for config, the real
  `anthropic` SDK for drafting (no mock in production code).
- **Frontend:** `apps/web/` — Next.js 15.5 (App Router), TypeScript, one page
  (`app/workspace.tsx`) calling the FastAPI backend directly via `fetch`
  (`app/api.ts`), no proxy layer.
- **Database:** Postgres, migrations in `supabase/migrations/*.sql`, applied
  forward-only by `scripts/migrate.mjs` (no checksum/baseline machinery —
  single-developer MVP against one dev database; add that back if this grows
  multiple contributors/environments).

## Commands

```bash
# Backend
python3.13 -m venv .venv && .venv/bin/pip install -r apps/api/requirements.txt
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/postmortem_ai \
  ANTHROPIC_API_KEY=<real key> \
  .venv/bin/uvicorn app.main:create_app --factory --app-dir apps/api --reload

# Backend tests (grounding tests need no DB; route tests need TEST_DATABASE_URL)
.venv/bin/python -m pytest apps/api/tests -q
.venv/bin/ruff check apps/api

# Database
npm install  # postgres client for scripts/migrate.mjs
DATABASE_URL=... DATABASE_SSL_MODE=disable node scripts/migrate.mjs

# Frontend
npm install --prefix apps/web
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 npm run dev --prefix apps/web
npm run build --prefix apps/web  # NEXT_PUBLIC_API_BASE is baked in at build time, not read at runtime
```

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
  `anthropic.AnthropicError` as a clean 502 — these are NOT the same
  exception hierarchy (`anthropic.AnthropicError` is the Anthropic SDK's own
  base for auth/rate-limit/connection failures). This was found by a live
  smoke test against a real Anthropic endpoint with an invalid key, which
  surfaced as an uncaught 500 before the second catch was added — don't
  remove it assuming `httpx.HTTPError` alone is sufficient.
- Re-drafting an already-published postmortem resets it to `status='draft'`
  (`approved_by`/`approved_at` cleared) via the `ON CONFLICT (incident_id) DO
  UPDATE` clause — a redraft is never silently published.
- Only *generated* actions (`evidence_id IS NOT NULL`) are replaced on
  redraft; any human-added action (`evidence_id NULL`) is preserved.

## Known gaps (not fixed, in scope for a later phase — don't assume otherwise)

- No auth/multi-tenant — `DEMO_CLIENT_EMAIL` is hardcoded everywhere a real
  caller identity should be.
- No deployment configuration (Vercel, Docker, CI) — verified locally only.
- `npm audit` on `apps/web` shows two remaining high-severity transitive
  vulnerabilities (`postcss`, `sharp`, pulled in by Next.js's build
  tooling) whose fix requires Next.js 16 (a breaking major-version jump).
  The critical RCE-class CVE that existed on the original `next@15.1.4` pin
  is already fixed (bumped to `15.5.23`); the remaining two are build-time
  only and lower priority, but worth resolving before any real deployment.
