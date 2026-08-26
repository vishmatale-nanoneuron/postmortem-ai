import time

from fastapi import Request

from ..database import Database

# Per-email lockout: the primary defense, since it directly limits how many
# passwords can be tried against one account regardless of how many source
# IPs an attacker uses.
MAX_FAILED_ATTEMPTS_PER_EMAIL = 5
EMAIL_WINDOW_MS = 15 * 60 * 1000

# Per-IP bound: a secondary defense against one source trying many
# different emails (credential stuffing) rather than brute-forcing one
# account. Deliberately looser than the per-email limit.
MAX_FAILED_ATTEMPTS_PER_IP = 20
IP_WINDOW_MS = 15 * 60 * 1000


def client_ip(request: Request) -> str:
    # Vercel (and most reverse proxies) put the real client IP first in
    # X-Forwarded-For; request.client.host would otherwise be the proxy's
    # own address, making every request look like it came from one IP.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def is_login_rate_limited(database: Database, email: str, ip: str) -> bool:
    now = int(time.time() * 1000)
    email_failures = await database.fetch_one(
        """SELECT count(*) AS n FROM login_attempts
           WHERE email=%s AND succeeded=false AND created_at > %s""",
        (email, now - EMAIL_WINDOW_MS),
    )
    if email_failures and email_failures["n"] >= MAX_FAILED_ATTEMPTS_PER_EMAIL:
        return True

    ip_failures = await database.fetch_one(
        """SELECT count(*) AS n FROM login_attempts
           WHERE ip=%s AND succeeded=false AND created_at > %s""",
        (ip, now - IP_WINDOW_MS),
    )
    return bool(ip_failures and ip_failures["n"] >= MAX_FAILED_ATTEMPTS_PER_IP)


async def record_login_attempt(database: Database, email: str, ip: str, succeeded: bool) -> None:
    await database.execute(
        "INSERT INTO login_attempts (email, ip, succeeded, created_at) VALUES (%s, %s, %s, %s)",
        (email, ip, succeeded, int(time.time() * 1000)),
    )


# Registration had no rate limiting at all before this -- creating an
# account is free and instant (no email verification, no KYC), which meant
# billing/upi/info and billing/wire/info (see postmortems.py's paywall,
# gated behind "any signed-in user" because a genuine unpaid client needs
# to see the real payment details to become a paying one) were only ever
# one trivial free registration away from anyone, not a real barrier.
# CAPTCHA (security/captcha.py) is the stronger defense and is already
# wired into register() -- but it's optional/unconfigured until a real
# Cloudflare Turnstile key is set. This is the defense that's active
# regardless: same atomic check-and-record pattern as try_record_action,
# to avoid the same TOCTOU race a naive check-then-insert would have.
MAX_REGISTRATIONS_PER_IP = 5
REGISTRATION_WINDOW_MS = 60 * 60 * 1000


async def try_record_registration_attempt(database: Database, ip: str) -> bool:
    """Atomically check-and-record. Returns True if this IP is still under
    the per-hour registration limit (and the attempt is now recorded),
    False if it should be rejected."""
    now = int(time.time() * 1000)
    async with database.transaction() as tx:
        await tx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"register:{ip}",))
        row = await tx.fetch_one(
            "SELECT count(*) AS n FROM registration_attempts WHERE ip=%s AND created_at > %s",
            (ip, now - REGISTRATION_WINDOW_MS),
        )
        if row and row["n"] >= MAX_REGISTRATIONS_PER_IP:
            return False
        await tx.execute("INSERT INTO registration_attempts (ip, created_at) VALUES (%s, %s)", (ip, now))
        return True


# Password-reset requests send a real email per call -- bounding this
# matters for a different reason than registration's own limit: an
# unbounded endpoint here is a way to spam an arbitrary inbox (the
# endpoint is deliberately unauthenticated, since the whole point is
# recovering an account you're locked out of) as much as it's an abuse
# vector against this app itself. Same atomic pattern as the two limiters
# above, own table so this can never cross-contaminate registration's or
# login's own counts.
MAX_PASSWORD_RESET_REQUESTS_PER_IP = 5
PASSWORD_RESET_WINDOW_MS = 60 * 60 * 1000


async def try_record_password_reset_attempt(database: Database, ip: str) -> bool:
    """Atomically check-and-record, same shape as
    try_record_registration_attempt above."""
    now = int(time.time() * 1000)
    async with database.transaction() as tx:
        await tx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"password_reset:{ip}",))
        row = await tx.fetch_one(
            "SELECT count(*) AS n FROM password_reset_attempts WHERE ip=%s AND created_at > %s",
            (ip, now - PASSWORD_RESET_WINDOW_MS),
        )
        if row and row["n"] >= MAX_PASSWORD_RESET_REQUESTS_PER_IP:
            return False
        await tx.execute("INSERT INTO password_reset_attempts (ip, created_at) VALUES (%s, %s)", (ip, now))
        return True


# Generic per-account action rate limiting -- separate from login's own
# email/IP-based limiter (a different threat model: this bounds how often
# an already-authenticated account can call a specific action, regardless
# of who's calling it or from where).
async def try_record_action(
    database: Database, user_id: str, action: str, max_per_window: int, window_ms: int
) -> bool:
    """Atomically check-and-record. Returns True if allowed (and recorded),
    False if the caller is currently rate-limited.

    This used to be two separate calls -- a SELECT count() to check, then a
    separate INSERT to record -- with real daylight between them (a route
    handler does other work, like creating the incident row, before the
    INSERT). A burst of concurrent requests each running the SELECT before
    any of their INSERTs committed could all see "under the limit" and all
    proceed: a classic TOCTOU race that let a burst blow past
    max_per_window by up to the burst size. This matters here specifically
    because create_incident/draft_postmortem's limits exist to bound real
    Gemini API cost, not just as a formality.

    Fixed with a Postgres advisory lock scoped to (user_id, action):
    concurrent attempts for the *same* user+action serialize against each
    other (so only one can be mid-check-and-insert at a time), while
    unrelated users/actions are never blocked by it. pg_advisory_xact_lock
    auto-releases at transaction end -- no separate unlock/cleanup needed.
    """
    now = int(time.time() * 1000)
    async with database.transaction() as tx:
        await tx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{user_id}:{action}",))
        row = await tx.fetch_one(
            "SELECT count(*) AS n FROM api_action_events WHERE user_id=%s AND action=%s AND created_at > %s",
            (user_id, action, now - window_ms),
        )
        if row and row["n"] >= max_per_window:
            return False
        await tx.execute(
            "INSERT INTO api_action_events (user_id, action, created_at) VALUES (%s, %s, %s)",
            (user_id, action, now),
        )
        return True
