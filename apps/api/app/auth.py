from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from .database import Database
from .dependencies import get_database
from .security.tokens import verify_token
from .settings import Settings, get_settings

SESSION_COOKIE_NAME = "session_token"


@dataclass(frozen=True)
class User:
    id: str
    email: str


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

    return User(id=row["id"], email=row["email"])
