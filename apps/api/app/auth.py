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
    # The one incident this account may create/work on without paying --
    # None until first used. Only ever set for non-founder, non-subscribed
    # accounts (see create_incident); a founder or a real subscriber never
    # needs it and it stays irrelevant for them.
    free_incident_id: str | None = None

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

    @property
    def has_free_incident_available(self) -> bool:
        """Whether this account can still create its one free incident --
        false once it's used (free_incident_id set), and false for any
        account that has ever actually paid, even if that subscription has
        since lapsed. subscription_status == 'none' is the real test for
        that, not just "not currently active": a Stripe subscription that
        lapsed reports a real terminal status (past_due/canceled/unpaid/...),
        and a manually approved UPI/wire subscription whose period ended
        stays stored as 'active' forever (see effective_status) -- neither
        should read as "never subscribed" just because access happens to be
        inactive right now. Without this check, a real customer whose
        payment lapsed would get a second, unpaid free incident instead of
        being asked to renew."""
        return (
            not self.is_founder
            and not self.has_active_subscription
            and self.subscription_status == "none"
            and self.free_incident_id is None
        )


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
        "SELECT id::text, email, subscription_status, current_period_end, free_incident_id FROM users WHERE id=%s",
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
        free_incident_id=row["free_incident_id"],
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
        "SELECT id::text, email, subscription_status, current_period_end, free_incident_id"
        " FROM users WHERE webhook_token=%s",
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
        # Previously omitted -- harmless today (webhooks.py's paywall only
        # ever checks has_active_subscription, which doesn't depend on this
        # field), but the constructed User silently didn't match the real
        # DB row, a latent inconsistency worth closing rather than leaving
        # for whatever reads this object next to trip over.
        free_incident_id=row["free_incident_id"],
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
    # start checkout. Used as-is (no free-tier exception) for actions that
    # should never be free: publishing and changing public visibility --
    # see require_active_subscription_or_free_slot /
    # require_active_subscription_or_free_incident below for the actions
    # that do have a free-tier exception.
    if not user.has_active_subscription:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="An active subscription is required")
    return user


async def require_active_subscription_or_free_slot(user: User = Depends(current_user)) -> User:
    """Gates incident *creation* specifically: allows a non-subscribed
    account through exactly once (while has_free_incident_available is
    true), so a prospect can try the real core loop -- evidence, a grounded
    draft -- before paying anything. create_incident itself is what
    actually records free_incident_id once this lets a free create
    through; this dependency only decides whether to let the request
    proceed, not which incident it becomes."""
    if user.has_active_subscription or user.has_free_incident_available:
        return user
    raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="An active subscription is required")


async def require_active_subscription_or_free_incident(incident_id: str, user: User = Depends(current_user)) -> User:
    """Gates actions on an *existing* incident (recording evidence,
    drafting, changing open/resolved status): allowed for a real
    subscriber, or for a free-tier account acting on specifically the one
    incident its free slot was spent on -- never any other incident_id,
    including one it used to own before the free slot was reassigned some
    other way. Publishing and public-visibility changes deliberately don't
    use this -- they stay behind require_active_subscription unconditionally
    (see its own docstring)."""
    if user.has_active_subscription:
        return user
    if user.free_incident_id is not None and user.free_incident_id == incident_id:
        return user
    raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="An active subscription is required")
