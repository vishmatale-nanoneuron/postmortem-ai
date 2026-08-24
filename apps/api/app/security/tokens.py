import time
from dataclasses import dataclass

import jwt

SESSION_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days
ALGORITHM = "HS256"


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    email: str
    issued_at: int
    expires_at: int


def issue_token(secret: str, user_id: str, email: str) -> str:
    now = int(time.time())
    # Standard JWT claims (RFC 7519): sub = subject (the user), iat/exp are
    # read natively by PyJWT.decode()'s own expiry check below. `email` is
    # a private (non-registered) claim, which the RFC explicitly allows.
    claims = {"sub": user_id, "email": email, "iat": now, "exp": now + SESSION_TTL_SECONDS}
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def verify_token(secret: str, raw: str) -> TokenPayload | None:
    try:
        # jwt.decode verifies the signature (constant-time internally) and
        # the exp claim itself -- an expired or tampered token raises
        # rather than returning something to check by hand.
        claims = jwt.decode(raw, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None

    user_id = claims.get("sub")
    email = claims.get("email")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if not all(isinstance(value, str) for value in (user_id, email)):
        return None
    if not all(isinstance(value, int) for value in (issued_at, expires_at)):
        return None

    return TokenPayload(user_id=user_id, email=email, issued_at=issued_at, expires_at=expires_at)
