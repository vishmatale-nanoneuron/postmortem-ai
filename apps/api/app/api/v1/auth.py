import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from ...auth import SESSION_COOKIE_NAME, User, _is_founder, current_user
from ...database import Database
from ...dependencies import get_database
from ...security.passwords import hash_password, verify_password
from ...security.rate_limit import (
    client_ip,
    is_login_rate_limited,
    record_login_attempt,
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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    is_founder: bool = False
    subscription_status: str = "none"
    has_active_subscription: bool = False


def _user_out(row: dict, settings: Settings) -> UserOut:
    is_founder = _is_founder(row["email"], settings.founder_email)
    subscription_status = row.get("subscription_status", "none")
    return UserOut(
        id=row["id"],
        email=row["email"],
        is_founder=is_founder,
        subscription_status=subscription_status,
        has_active_subscription=is_founder or subscription_status in ("active", "trialing"),
    )


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=60 * 60 * 24 * 7,
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def register(
    payload: RegisterRequest,
    response: Response,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> UserOut:
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
           VALUES (%s, %s, %s) RETURNING id::text, email, subscription_status""",
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
    if await is_login_rate_limited(database, payload.email, ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    row = await database.fetch_one(
        "SELECT id::text, email, password_hash, subscription_status FROM users WHERE email=%s", (payload.email,)
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
        subscription_status=user.subscription_status,
        has_active_subscription=user.has_active_subscription,
    )
