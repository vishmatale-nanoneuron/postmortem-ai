# Security posture

What the code actually does, with file references, so a prospective buyer
(or a future maintainer) can check each claim rather than take it on faith.
Reviewed against the code on 2026-09-13. This is documentation of the
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
| Airlock: unauthenticated or invalid-key calls per IP | 60 per hour, then 429 -- a flood of bad keys never becomes a flood of hash lookups |
| Airlock: authenticated scan/egress calls | metered by prepaid credits, not rate-limited -- the balance is the bound, and the charge is taken before the engine runs |
| Airlock: policy and usage reads per account | 600 per hour (unmetered, so the balance is not their bound) |
| Airlock: CSV exports per account | 60 per hour |
| Airlock: active API keys per account | 10, checked under an advisory lock |
| Airlock: payment-details emails per account | 5 per hour |

Circuit breakers per AI provider and the `ai_runs` audit table record
every model call, success or failure.

## Airlock: the paid guard

Airlock (`apps/api/app/api/v1/airlock.py`, `app/airlock/`,
`app/cqrs/airlock_billing.py`) is a paid API that scores untrusted text for
prompt injection and checks outbound calls for credentials and personal
data. Because customers route content they do not control through it, its
posture is stricter than the rest of the product's:

- **Authentication.** `X-Airlock-Key` or `Authorization: Bearer alk_...`,
  or the dashboard session cookie. Keys are 32 random bytes; only their
  SHA-256 is stored (`airlock_api_keys.key_hash`), the secret is returned
  once at creation, and a revoked key answers exactly like a wrong one.
  Both schemes are declared in the OpenAPI document.
- **Metering cannot double-spend, and the paywall is in front of the
  engine.** One credit per call (five with `"deep": true`; four refunded
  when the rules already block and the model is not asked) is taken by a
  single conditional `UPDATE` on a balance row with `CHECK (balance >= 0)`,
  in the same transaction as the ledger line, *before* the detector runs --
  a drained key cannot make the engine do work (pinned by
  `test_a_drained_key_never_reaches_the_engine`);
  Postgres serialises concurrent debits on the row lock. Proven by
  `tests/test_airlock_billing.py`: fifty concurrent scans against ten
  credits yield exactly ten 200s and forty 402s. A refused call (401, 402,
  422, 429) charges nothing, and an application error after the charge
  refunds it (every metered route's post-charge body is guarded; pinned by
  `test_an_application_error_after_the_charge_refunds_and_still_fails_closed`).
  The one deliberate exception is a proxy fetch that is refused or
  unreachable: the scan credit is refunded and the attempt keeps one, so
  the endpoint is not a free oracle for internal hostnames.
- **Fails closed.** A 5xx raised inside the application on
  `/v1/airlock/scan` or `/v1/airlock/egress` carries `"verdict": "block"`
  in its body (`main.py`'s unhandled-exception handler consults
  `FAIL_CLOSED_PATHS`), so a client that reads the body before the status
  still reads a block. Other routes' 500s are undecorated. A platform
  failure before the function runs is outside this mechanism, which is why
  the documented rule for callers is "any non-200 is a block". Pinned by
  `tests/test_airlock_policy.py`.
- **Policy is written by people, read by keys.** The per-account policy
  (`airlock_policies`, migration 0034: thresholds, muted rules, standing
  egress allowlist) is readable with a key and writable only from a
  signed-in session. A leaked key can therefore see the policy it runs
  under but cannot raise the block threshold to 1.0, mute every rule, or
  allowlist a host -- switching the guard off needs the dashboard
  password. Rule ids are validated against the live rule list, allowlist
  entries must be hostnames, and `flag <= block` is a database `CHECK`.
  The per-call `allowlist` on an egress call is unioned with the policy's,
  never substituted for it.
- **Proxy fetch is not an SSRF gadget.** `POST /v1/airlock/proxy/fetch`
  fetches a caller-supplied URL from Airlock's own address, which is the
  textbook shape of a server-side request forgery primitive. The guard
  (`app/airlock/proxy.py`) resolves the hostname and checks EVERY address
  it resolves to against loopback, private, link-local (cloud metadata),
  CGNAT, reserved, multicast, unspecified, documentation, IPv4-mapped and
  NAT64-embedded ranges; recognises decimal, hex and short-dotted IPv4
  literals before DNS; refuses a name that resolves to any non-public
  address; connects to the checked address with the hostname as Host and
  as the TLS server name (httpcore `sni_hostname`), so a DNS answer that
  changes between check and connect cannot move the request and the
  certificate is still verified against the real name; follows redirects
  by hand, re-checking each hop, at most 3; reads at most 1 MB; scans only
  text types; forwards nothing of the caller's. Tested in
  `tests/test_airlock_proxy.py` with a transport that records the exact
  connection attempted. It is metered (2 credits; a refused attempt still
  costs 1), so a drained key cannot make Airlock fetch anything and a
  funded one pays to probe.
- **A shipped migration is never edited.** `scripts/check-migrations.mjs`
  pins a SHA-256 of every file in `supabase/migrations/` in
  `CHECKSUMS.json` and fails CI when a recorded file changes or a new one
  is unrecorded (`node scripts/check-migrations.mjs --update` records
  it). Also refuses `DROP TABLE` / `DROP SCHEMA` / `TRUNCATE` at statement
  start and `CREATE INDEX CONCURRENTLY`.
- **Errors are recorded, not sent to a vendor.** The API's unhandled-
  exception handler writes one row per 500 to `request_errors` (migration
  0035): method, path, exception type, a truncated message, the request id
  the customer was shown, and a fingerprint -- never a request body, a
  header, a stack trace, or the user. The founder dashboard lists faults
  grouped by fingerprint; the first sighting of a fault in 24 hours emails
  the founder, capped at ten emails an hour. The write is best-effort and
  can never change the 500 the customer receives (pinned by
  `tests/test_request_errors.py`). Rows are pruned at 90 days.
- **Invoices never carry payee account details.** `GET
  /v1/billing/claims/{id}/invoice` (owner-only; a neighbour is 404) renders
  the proforma/receipt from the claim row and the seller settings; the
  bank account number and UPI ID stay email-on-request, as before. The page
  at `/invoice/{id}` is `noindex` and fetches with the session cookie, so
  nothing about a claim is in the HTML.
- **Usage exports come from the ledger, not the audit log.** `GET
  /v1/airlock/usage` and `/usage.csv` read `airlock_credit_ledger`, which
  is attributed and cascades with the account. The audit log has no
  account column and cannot be exported per customer by construction.
- **Content is never stored.** The audit table (`airlock_scan_events`,
  migration 0031) has a SHA-256, byte count, verdict and rule ids -- no
  content column, no account column, no IP. It is append-only by two
  Postgres triggers (row-level `BEFORE UPDATE OR DELETE`, statement-level
  `BEFORE TRUNCATE`), tested from a separate connection. Attribution lives
  in the deletable ledger, so account erasure still holds.
- **Content is stored only when the customer sends it as feedback.** A
  wrong-verdict report (`POST /v1/airlock/feedback`, migration 0036) holds
  the hash, verdicts and rule ids; `content` is a nullable column filled
  only when the report includes it. Kept text is that account's: shown to
  the classifier on that account's deep scans as a worked example (the
  most recent eight, capped in length), exportable and deletable by the
  account, cascaded on erasure, invisible to the founder view (which
  returns per-rule counts only) and to every other account -- pinned by
  `tests/test_airlock_feedback.py`. Nothing trains a model on it.
  A key can file reports (that is what the SDK's `feedback()` does), so a
  leaked key can add examples to the account's deep-scan prompt; the
  bound is that examples cannot lower a verdict below the rules -- the
  model's term is zero unless it answers "injection" and the combination
  only raises (`airlock/semantic.py`) -- and a key still cannot mute a
  rule or change a threshold. Reports are listed on the dashboard and
  withdrawable there.
- **No model call by default.** The standard scan is forty regular
  expressions over normalised text. A deep scan is opt-in per call, sends
  that content to Google's Gemini API, can only raise a verdict (its weight
  is zero unless it says "injection", capped below the strongest single
  rule), and on any provider failure reports `status: "unavailable"` and
  refunds the extra credits -- it never silently changes the answer.
- **Credits are granted in one place.** The founder's `approve_payment_claim`
  (for a paid pack) or the founder-only manual grant endpoint; both write
  a ledger line. No client-reachable route can add credits.
- **Public reads are the only cached responses.** `/v1/airlock/pricing`
  and `/v1/airlock/stats` (aggregate counts, no content) opt in to a short
  `Cache-Control`; every other response on the API stays
  `private, no-store`, pinned by a test.

## Data handling

- Account deletion is an erasure: incidents, evidence, postmortems, the
  account's own activity history, and its Airlock keys, balance and ledger
  go in one transaction (`delete_account`, `apps/api/app/api/v1/auth.py`,
  with the Airlock tables cascading from `users`). The privacy policy says
  so and the code matches it. The append-only Airlock audit rows are not
  touched, because they never named the account.
- Payments are UPI or international wire only. There is no card
  processor; no payment instrument is ever sent to or stored by this
  service, only the transaction reference the customer submits.
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
