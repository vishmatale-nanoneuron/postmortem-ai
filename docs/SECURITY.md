# Security posture

What the code actually does, with file references, so a prospective buyer
(or a future maintainer) can check each claim rather than take it on faith.
Reviewed against the code on 2026-09-11. This is documentation of the
existing posture, not a change to it. To report a vulnerability, see
`/.well-known/security.txt`.

## Server-side validation is the boundary

Every request body is a Pydantic model with field constraints
(`apps/api/app/api/v1/*.py`): email addresses are `EmailStr`, passwords
8-200 characters, evidence and extraction text length-capped, enumerated
values (severity, evidence source, action status) validated against the
same sets the database's CHECK constraints enforce, so a bad value is a
422 with a readable message and never a 500 from Postgres. The frontend's
own validation (`apps/web/app/validation.ts`) is a convenience; nothing
depends on it.

## Authorization: three independent layers

- **Session** -- an HMAC-signed token in an `httponly`, `secure`,
  `samesite=none` cookie (`_set_session_cookie`, `apps/api/app/api/v1/auth.py`).
  Cleared with the same attributes on logout, or it lingers.
- **Ownership** -- every incident route resolves the incident through
  `require_incident(database, incident_id, user.email)`
  (`apps/api/app/api/v1/postmortems.py`), which answers **404, not 403**,
  for another account's incident: a 403 would confirm the id exists. The
  tenant-scoping test registers a second account and asserts 404 on every
  route that touches an incident, including evidence, draft, publish,
  Markdown export and action-item status.
- **Founder** -- `current_founder` (`apps/api/app/auth.py`) is a
  constant-time comparison (`hmac.compare_digest`) of the session's email
  against the configured founder address. It is independent of
  subscription state and cannot be granted by anything a client does. The
  founder dashboard URL is additionally gated by a secret path key in the
  Next.js middleware.
- **Subscription** -- `require_active_subscription` gates only the actions
  that spend money (drafting, extraction, publishing). Reading, exporting
  and changing the state of your own data never requires payment.

## Passwords are never stored in plain text

`apps/api/app/security/passwords.py`: scrypt with a per-user random salt at
OWASP's interactive-login cost parameters, stored as
`scrypt$<salt>$<hash>`. Verification is constant-time and rejects any
other algorithm tag. Both hashing and verification run in a thread pool
so the CPU-bound KDF cannot stall the event loop. Password-reset tokens
are signed, expire in 30 minutes, and embed a fingerprint of the current
hash so a token is single-use: once the password changes, the same token
no longer verifies (`apps/api/app/security/tokens.py`).

## Errors do not leak

- Unhandled exceptions return `{"detail": "Internal server error"}` and
  are logged server-side (`unhandled_exception_handler`,
  `apps/api/app/main.py`). Stack traces never reach a client.
- Login failure is one fixed message whether the email is unknown, the
  password is wrong, or the account is locked out.
- Password-reset requests return 202 whether or not the address exists.
- Foreign resources are 404, as above.
- The MCP read-only SQL tool runs inside a real Postgres read-only
  transaction, wrapped in a subquery with a LIMIT, with credential-shaped
  columns redacted (`apps/api/tests/test_mcp_tools.py` proves this
  against a live database).

**Known, priced trade-off: registration confirms an existing email.**
`POST /v1/auth/register` returns 409 "An account with this email already
exists". That is account enumeration -- the one place the API says whether
an address is registered. Making it enumeration-safe means registration
can no longer log the new user straight in, which breaks the instant
first-incident path that production data says is what converts. It is
bounded by 5 registrations per IP per hour. (A Cloudflare Turnstile
captcha is wired in -- `apps/api/app/security/captcha.py` -- but is
**inactive until `TURNSTILE_SECRET_KEY` is set**; as of this review it is
not set in production, so the per-IP cap is the only bound today.) This is
a deliberate choice, recorded here so it is not mistaken for an oversight;
revisit if the product ever serves a population where the existence of an
account is itself sensitive.

## Rate limits and abuse controls

(`apps/api/app/security/rate_limit.py`, all backed by database rows, not
in-process counters, so they hold across serverless instances.)

| Control | Limit |
|---|---|
| Failed logins per email | 5 per 15 minutes (lockout) |
| Failed logins per IP | 20 per 15 minutes |
| Registrations per IP | 5 per hour (captcha available, not enabled in production) |
| Password-reset requests per IP | 5 per window |
| AI drafts / extractions per account | hourly cap and 500 per month, taken under an advisory lock so concurrent requests cannot exceed it |

Circuit breakers per AI provider and the `ai_runs` audit table record
every model call, success or failure.

## Data handling

- Account deletion is an erasure: incidents, evidence, postmortems and
  the account's own activity history go in one transaction
  (`delete_account`, `apps/api/app/api/v1/auth.py`). The privacy policy
  says so and the code matches it.
- Clients can export everything they own as JSON (`GET /v1/postmortems/export`)
  and each postmortem as Markdown.
- Webhook, PagerDuty and Slack ingestion authenticate by a per-account
  rotatable token in the URL; Slack bot messages are dropped so the
  product cannot cite its own notifications.
- Secrets live in the deployment platform's environment, never in the
  repository; `pip-audit` and `bun audit` run on every CI push and fail
  the build on known vulnerabilities.

## Not implemented, on purpose

- **OAuth / social login.** Not built. It needs a Google (or GitHub)
  OAuth client that only the account owner can create, and it adds new
  authentication surface -- state, PKCE, verified-email handling, accounts
  with no password -- to the one part of the system where a mistake is
  unrecoverable. At current signup volume the bottleneck is discovery, not
  the signup form. If a provider credential is created, wiring it up is a
  contained piece of work; until then, email and password with the
  controls above.
- **Email verification at signup.** Same reasoning as the enumeration
  trade-off: it would break instant onboarding.
