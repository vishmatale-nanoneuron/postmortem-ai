import base64
import hashlib
import secrets

# scrypt cost parameters tuned for an interactive login: expensive enough to
# resist offline brute-force at scale, cheap enough not to make local dev
# painful. n=2**14 (16384), r=8, p=1 is a commonly recommended interactive
# baseline (OWASP's scrypt guidance); revisit if this ever needs to scale to
# a high-throughput auth service.
_N = 2**14
_R = 8
_P = 1
_KEY_LENGTH = 32
_SALT_LENGTH = 16


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_LENGTH)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_LENGTH)
    return f"scrypt${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_b64, hash_b64 = stored_hash.split("$")
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    try:
        salt = _unb64(salt_b64)
        expected = _unb64(hash_b64)
    except Exception:
        return False
    candidate = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=len(expected))
    # Compare bytes, not the base64 text -- exact same shape as the
    # UTF-8-bytes rule tokens.py follows, for the same reason: comparing raw
    # str with secrets.compare_digest breaks on non-ASCII input, and while
    # base64 output is always ASCII so that specific crash can't happen
    # here, comparing decoded bytes is the more defensible invariant to hold
    # consistently across this module.
    return secrets.compare_digest(candidate, expected)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))
