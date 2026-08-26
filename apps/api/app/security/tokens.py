import hashlib
import time
from dataclasses import dataclass

import jwt

SESSION_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days
PASSWORD_RESET_TTL_SECONDS = 30 * 60  # 30 minutes -- short-lived, this token grants a password change
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


def _password_hash_fingerprint(password_hash: str) -> str:
    # Not for verifying the password itself -- just a short, stable
    # fingerprint of the CURRENT password_hash, embedded in the reset
    # token so a token becomes unusable the instant the password it was
    # issued against actually changes. This is what makes the token
    # single-use without a separate "used tokens" table: reset once, the
    # fingerprint on record no longer matches, and reusing the same email
    # link (or a captured/leaked one) a second time fails verification.
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class PasswordResetPayload:
    user_id: str
    email: str


def issue_password_reset_token(secret: str, user_id: str, email: str, current_password_hash: str) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "email": email,
        "purpose": "password_reset",
        "pwh": _password_hash_fingerprint(current_password_hash),
        "iat": now,
        "exp": now + PASSWORD_RESET_TTL_SECONDS,
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def verify_password_reset_token(secret: str, raw: str, current_password_hash: str) -> PasswordResetPayload | None:
    """Distinct from verify_token above -- a session token must never be
    accepted here (checked via the `purpose` claim) and vice versa, so a
    leaked session cookie can't be replayed as a password-reset grant or
    the other way around. current_password_hash must be freshly read from
    the database by the caller, not cached -- that's what makes reuse
    after a successful reset fail (see _password_hash_fingerprint)."""
    try:
        claims = jwt.decode(raw, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None

    if claims.get("purpose") != "password_reset":
        return None
    user_id = claims.get("sub")
    email = claims.get("email")
    fingerprint = claims.get("pwh")
    if not all(isinstance(value, str) for value in (user_id, email, fingerprint)):
        return None
    if fingerprint != _password_hash_fingerprint(current_password_hash):
        return None

    return PasswordResetPayload(user_id=user_id, email=email)
