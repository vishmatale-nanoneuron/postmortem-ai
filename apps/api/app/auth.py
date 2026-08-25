import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from .database import Database
from .dependencies import get_database
from .security.tokens import verify_token
from .settings import Settings, get_settings

SESSION_COOKIE_NAME = "session_token"


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

    row = await database.fetch_one("SELECT id::text, email FROM users WHERE id=%s", (payload.user_id,))
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists")

    return User(id=row["id"], email=row["email"], is_founder=_is_founder(row["email"], settings.founder_email))


async def current_founder(user: User = Depends(current_user)) -> User:
    # Independent of any client/subscription state and not grantable by
    # workspace membership -- matches the same invariant already documented
    # for nanoneuron-software-company's founder dependency.
    if not user.is_founder:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Founder access required")
    return user
