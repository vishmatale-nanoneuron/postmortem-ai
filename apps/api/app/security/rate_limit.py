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
