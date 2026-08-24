import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

SESSION_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    email: str
    issued_at: int
    expires_at: int


def issue_token(secret: str, user_id: str, email: str) -> str:
    now = int(time.time())
    payload = {"user_id": user_id, "email": email, "issued_at": now, "expires_at": now + SESSION_TTL_SECONDS}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(secret, body)
    return f"{body}.{signature}"


def verify_token(secret: str, raw: str) -> TokenPayload | None:
    try:
        body, signature = raw.split(".", 1)
    except ValueError:
        return None

    expected_signature = _sign(secret, body)
    # Compare UTF-8-encoded bytes, never raw str -- secrets.compare_digest
    # raises TypeError on any non-ASCII str input. Both operands here are
    # always ASCII (base64/hex output) so that specific crash can't occur,
    # but keeping the byte-compare consistent everywhere signatures are
    # checked in this codebase is the point: this is the exact bug class
    # found in nanoneuron-software-company's founder() dependency this
    # session (comparing raw str crashed to a 500 on non-ASCII input instead
    # of a clean 403) -- built correctly here from the start rather than
    # relying on "the input happens to always be ASCII" as the only guard.
    if not secrets.compare_digest(signature.encode("utf-8"), expected_signature.encode("utf-8")):
        return None

    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    user_id = payload.get("user_id")
    email = payload.get("email")
    expires_at = payload.get("expires_at")
    issued_at = payload.get("issued_at")
    if not all(isinstance(value, str) for value in (user_id, email)):
        return None
    if not all(isinstance(value, int) for value in (expires_at, issued_at)):
        return None
    if expires_at < int(time.time()):
        return None

    return TokenPayload(user_id=user_id, email=email, issued_at=issued_at, expires_at=expires_at)


def _sign(secret: str, body: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return _b64(digest)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))
