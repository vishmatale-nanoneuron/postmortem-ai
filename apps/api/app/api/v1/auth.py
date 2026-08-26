import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from ...auth import SESSION_COOKIE_NAME, User, _is_founder, current_user
from ...database import Database
from ...dependencies import get_database
from ...security.captcha import verify_turnstile
from ...security.passwords import hash_password, verify_password
from ...security.rate_limit import (
    client_ip,
    is_login_rate_limited,
    record_login_attempt,
    try_record_registration_attempt,
)
from ...security.tokens import issue_token
from ...settings import Settings, get_settings

logger = logging.getLogger("postmortem_ai")

router = APIRouter(prefix="/v1/auth", tags=["auth"])

# Generic message on any login failure -- wrong email and wrong password get
# the exact same status/detail, so a failed attempt can't be used to
# enumerate which emails are registered.
LOGIN_FAILURE_DETAIL = "Incorrect email or password"
RATE_LIMITED_DETAIL = "Too many attempts. Try again later."
CAPTCHA_FAILURE_DETAIL = "CAPTCHA verification failed"

# Computed once at import time, never stored anywhere, never matched by a
# real password. When the email doesn't exist, login still runs a scrypt
# verify against this instead of skipping straight to failure -- otherwise
# "no such account" would consistently return faster than "wrong password
# for a real account," letting an attacker enumerate registered emails by
# timing alone even though the response body/status are identical.
_DECOY_HASH = hash_password("this-decoy-password-never-matches-a-real-account")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    captcha_token: str | None = None

    # Real bug this closes: without normalizing case, "User@Example.com"
    # and "user@example.com" registered as two separate accounts sharing
    # the same real inbox -- found via a self-directed audit, not a bug
    # report. Only the local part's case is normalized (lowercased);
    # per RFC 5321 the local part is technically case-sensitive, but every
    # mail provider that matters in practice treats it case-insensitively,
    # and consistent lowercasing is what actually prevents the duplicate-
    # account problem here.
    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    captcha_token: str | None = None

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserOut(BaseModel):
    id: str
    email: str
    is_founder: bool = False
    subscription_status: str = "none"
    has_active_subscription: bool = False


def _user_out(row: dict, settings: Settings) -> UserOut:
    # Builds the real User (not a separately re-derived bool) so this and
    # GET /me can never disagree about what counts as active -- this used
    # to recompute is_founder/status in ("active","trialing") locally,
    # which meant it never saw current_period_end and could report a
    # lapsed manual (UPI/wire) subscription as active for a moment.
    user = User(
        id=row["id"],
        email=row["email"],
        is_founder=_is_founder(row["email"], settings.founder_email),
        subscription_status=row.get("subscription_status", "none"),
        current_period_end=row.get("current_period_end"),
    )
    return UserOut(
        id=user.id,
        email=user.email,
        is_founder=user.is_founder,
        subscription_status=user.effective_status,
        has_active_subscription=user.has_active_subscription,
    )


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    # samesite="none" is required, not just permissive: the frontend
    # (www.nanoneuron.ai) calls this API directly cross-origin (see
    # apps/web/app/api.ts) rather than through a same-origin proxy, so
    # samesite="strict"/"lax" would silently never send this cookie back on
    # any subsequent request -- auth.me() would always look logged-out even
    # right after a successful login. "none" requires secure=True, which is
    # exactly the case this cross-origin setup always needs (never send an
    # unencrypted session cookie same-site-unrestricted).
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="none",
        max_age=60 * 60 * 24 * 7,
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    if not await verify_turnstile(settings.turnstile_secret_key, payload.captcha_token, client_ip(request)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=CAPTCHA_FAILURE_DETAIL)
    if not await try_record_registration_attempt(database, client_ip(request)):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    is_founder_email = _is_founder(payload.email, settings.founder_email)
    existing = await database.fetch_one("SELECT id FROM users WHERE email=%s", (payload.email,))
    if existing:
        if is_founder_email:
            # The founder email is a fixed, known value -- any repeat
            # registration attempt against it (yours or otherwise) is worth
            # a visible log line, not just a silent 409.
            logger.warning("founder_email_registration_conflict")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    if is_founder_email:
        # First-ever registration of the founder email is the actual
        # security-sensitive moment: whoever completes it first owns the
        # founder account, since the email is unique. Always log it.
        logger.warning("founder_email_registration_succeeded")

    now = int(time.time() * 1000)
    row = await database.fetch_one(
        """INSERT INTO users (email, password_hash, created_at)
           VALUES (%s, %s, %s) RETURNING id::text, email, subscription_status, current_period_end""",
        (payload.email, hash_password(payload.password), now),
    )
    assert row is not None
    token = issue_token(settings.session_secret, row["id"], row["email"])
    _set_session_cookie(response, settings, token)
    return _user_out(row, settings)


@router.post("/login", response_model=UserOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    ip = client_ip(request)
    if not await verify_turnstile(settings.turnstile_secret_key, payload.captcha_token, ip):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=CAPTCHA_FAILURE_DETAIL)
    if await is_login_rate_limited(database, payload.email, ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    row = await database.fetch_one(
        "SELECT id::text, email, password_hash, subscription_status, current_period_end FROM users WHERE email=%s",
        (payload.email,),
    )
    stored_hash = row["password_hash"] if row else _DECOY_HASH
    password_matches = verify_password(payload.password, stored_hash)
    succeeded = bool(row) and password_matches
    await record_login_attempt(database, payload.email, ip, succeeded)
    if not succeeded:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_FAILURE_DETAIL)

    if _is_founder(row["email"], settings.founder_email):  # type: ignore[index]
        logger.info("founder_login_succeeded")

    token = issue_token(settings.session_secret, row["id"], row["email"])  # type: ignore[index]
    _set_session_cookie(response, settings, token)
    return _user_out(row, settings)  # type: ignore[arg-type]


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        is_founder=user.is_founder,
        subscription_status=user.effective_status,
        has_active_subscription=user.has_active_subscription,
    )


class UpdateAccountRequest(BaseModel):
    """PUT semantics: a full replace of the mutable account fields -- both
    are required, unlike PATCH below. password is re-entered (not the old
    one) since this is intended for "set my account to exactly this", not
    a change-password flow that needs the current password confirmed."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PatchAccountRequest(BaseModel):
    """PATCH semantics: every field optional, only what's supplied changes."""

    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str | None) -> str | None:
        return value.strip().lower() if value is not None else None


async def _apply_account_update(
    database: Database,
    settings: Settings,
    user: User,
    email: str | None,
    password: str | None,
) -> UserOut:
    if email is None and password is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update")

    # The founder email is a fixed, known value (settings.founder_email) --
    # letting it be reassigned away via account update would silently strip
    # founder access from the account that's supposed to hold it, and
    # letting some other account rename itself into it would hand that
    # account founder access without ever going through register()'s
    # explicit first-registration check. Simplest correct rule: the
    # founder account can't change its own email here, and no account can
    # rename itself into the founder email.
    if email is not None and email != user.email:
        if user.is_founder or _is_founder(email, settings.founder_email):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot reassign the founder email")
        existing = await database.fetch_one("SELECT id FROM users WHERE email=%s AND id<>%s", (email, user.id))
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    fields: list[str] = []
    values: list[object] = []
    if email is not None:
        fields.append("email=%s")
        values.append(email)
    if password is not None:
        fields.append("password_hash=%s")
        values.append(hash_password(password))
    values.append(user.id)

    row = await database.fetch_one(
        f"UPDATE users SET {', '.join(fields)} WHERE id=%s "
        "RETURNING id::text, email, subscription_status, current_period_end",
        tuple(values),
    )
    assert row is not None
    return _user_out(row, settings)


@router.put("/me", response_model=UserOut)
async def replace_account(
    payload: UpdateAccountRequest,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> UserOut:
    return await _apply_account_update(database, settings, user, payload.email, payload.password)


@router.patch("/me", response_model=UserOut)
async def update_account(
    payload: PatchAccountRequest,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> UserOut:
    return await _apply_account_update(database, settings, user, payload.email, payload.password)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    response: Response,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> None:
    # The founder account is the one account this product cannot function
    # without (it's the sole authorizer of every manual payment claim) --
    # refuse self-deletion rather than leave the product with no founder.
    if user.is_founder:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The founder account cannot be deleted")
    # payment_claims and action_rate_limits both cascade (ON DELETE CASCADE
    # on user_id) -- see supabase/migrations/0007 and 0010. Incidents and
    # postmortems are owned by client_email, not a user_id FK, so they are
    # deliberately NOT deleted here: they stay as historical record even
    # after the account that created them is gone, consistent with this
    # app's append-only-history stance elsewhere (payment_claim_events).
    await database.execute("DELETE FROM users WHERE id=%s", (user.id,))
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


@router.get("/captcha-config")
async def captcha_config(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """Public config the frontend needs to render (or skip) the Turnstile
    widget -- site_key is meant to be public (it's shipped to every
    browser as part of the widget itself); secret_key never leaves this
    backend."""
    return {"enabled": bool(settings.turnstile_secret_key), "site_key": settings.turnstile_site_key}


@router.get("/session-token")
async def session_token(request: Request, _user: User = Depends(current_user)) -> dict[str, str]:
    """Returns the caller's own already-issued session JWT verbatim (not a
    new one) -- exists solely so apps/web/app/api/mcp/route.ts (a
    same-origin Next.js route on the FRONTEND's own domain) can mirror it
    into a cookie on ITS OWN origin. This is necessary, not incidental:
    session_token is set by THIS backend's domain
    (postmortem-ai-api.vercel.app); browsers never send an
    origin-scoped cookie cross-origin to www.nanoneuron.ai, so the
    frontend's server genuinely has no other way to learn it. Requires
    current_user (i.e. the caller must already hold a valid cookie) --
    this route mirrors an existing session, it never grants a new one."""
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    assert raw is not None  # current_user already required this cookie to resolve a user
    return {"token": raw}
