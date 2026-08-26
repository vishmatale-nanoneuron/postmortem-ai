import hmac
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from .database import Database
from .dependencies import get_database
from .security.tokens import verify_token
from .settings import Settings, get_settings

SESSION_COOKIE_NAME = "session_token"

# Stripe subscription.status values that mean "the account may use the
# product." Everything else (past_due, canceled, unpaid, incomplete,
# incomplete_expired, or the pre-checkout 'none') is treated as inactive --
# an explicit allowlist rather than a denylist, so a Stripe status this
# code hasn't seen before fails closed instead of silently granting access.
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


def _is_founder(email: str, founder_email: str) -> bool:
    # Constant-time comparison -- same defense as nanoneuron-software-
    # company's founder gate, for the same reason: an early-exit `==`
    # leaks how many leading characters matched via response timing.
    return hmac.compare_digest(email.strip().lower(), founder_email.strip().lower())


@dataclass(frozen=True)
class User:
    id: str
    email: str
    is_founder: bool
    subscription_status: str
    current_period_end: int | None = None

    @property
    def has_active_subscription(self) -> bool:
        # Founder access is independent of any client/subscription state --
        # same invariant as nanoneuron-software-company's founder gate.
        if self.is_founder:
            return True
        if self.subscription_status not in ACTIVE_SUBSCRIPTION_STATUSES:
            return False
        # A status of 'active'/'trialing' alone isn't enough: a manually
        # approved UPI/wire claim (founder.py's approve_payment_claim) sets
        # status='active' once and nothing ever flips it back -- there's no
        # recurring billing system behind a manual payment, unlike Stripe,
        # which corrects status itself via webhook when a period lapses.
        # Without this check, a single ₹999 payment bought permanent access
        # instead of the one month it was actually billed for.
        if self.current_period_end is None:
            return True
        return self.current_period_end > int(time.time())

    @property
    def effective_status(self) -> str:
        """What should actually be shown to the account -- not just what's
        stored. subscription_status stays 'active' in the database forever
        after a manual (UPI/wire) period lapses (see has_active_subscription
        above): there's no recurring billing system to flip it back on its
        own. Without this, a client whose 30 days ran out a month ago would
        still see "Subscription: active" in their own dashboard, which is
        actively misleading -- a real subscription product (this is the
        actual "like Claude AI" expectation) tells you plainly when your
        plan has expired so you know to renew, rather than showing a stale
        status next to a past date."""
        if not self.is_founder and self.subscription_status == "active" and not self.has_active_subscription:
            return "expired"
        return self.subscription_status


async def current_user(
    request: Request,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> User:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")

    payload = verify_token(settings.session_secret, raw)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")

    row = await database.fetch_one(
        "SELECT id::text, email, subscription_status, current_period_end FROM users WHERE id=%s",
        (payload.user_id,),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists")

    return User(
        id=row["id"],
        email=row["email"],
        is_founder=_is_founder(row["email"], settings.founder_email),
        subscription_status=row["subscription_status"],
        current_period_end=row["current_period_end"],
    )


async def user_by_webhook_token(database: Database, settings: Settings, token: str) -> User | None:
    """Resolves a User the same way current_user does, but from a
    per-account webhook token instead of a session cookie -- for
    unauthenticated-by-browser callers (monitoring tools, scripts) that
    can't hold a session. Returns None rather than raising so callers
    control the exact error shape/status for their own endpoint (a
    webhook consumer shouldn't see this app's normal 401 JSON body)."""
    if not token:
        return None
    row = await database.fetch_one(
        "SELECT id::text, email, subscription_status, current_period_end FROM users WHERE webhook_token=%s",
        (token,),
    )
    if not row:
        return None
    return User(
        id=row["id"],
        email=row["email"],
        is_founder=_is_founder(row["email"], settings.founder_email),
        subscription_status=row["subscription_status"],
        current_period_end=row["current_period_end"],
    )


async def current_founder(user: User = Depends(current_user)) -> User:
    # Independent of any client/subscription state and not grantable by
    # workspace membership -- matches the same invariant already documented
    # for nanoneuron-software-company's founder dependency.
    if not user.is_founder:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Founder access required")
    return user


async def require_active_subscription(user: User = Depends(current_user)) -> User:
    # Gates the product's actual work (creating incidents, drafting,
    # publishing) -- not signup/login/read routes, which stay reachable so
    # a lapsed or not-yet-paying account can still see its own history and
    # start checkout.
    if not user.has_active_subscription:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="An active subscription is required")
    return user
