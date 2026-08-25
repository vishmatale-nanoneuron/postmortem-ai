import time

import jwt
from app.security.tokens import ALGORITHM, issue_token, verify_token

SECRET = "test-secret-do-not-use-in-production"


def test_a_valid_token_round_trips() -> None:
    token = issue_token(SECRET, user_id="u1", email="user@example.com")
    payload = verify_token(SECRET, token)
    assert payload is not None
    assert payload.user_id == "u1"
    assert payload.email == "user@example.com"


def test_it_is_a_real_rfc_7519_jwt() -> None:
    # Decodable by a plain jwt.decode() call, not just our own verify_token
    # -- proves this is a real, standard-format JWT (three dot-separated
    # base64url segments, "sub"/"email"/"iat"/"exp" claims), not a
    # custom-shaped token that merely looks similar.
    token = issue_token(SECRET, user_id="u1", email="user@example.com")
    assert token.count(".") == 2
    claims = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    assert claims["sub"] == "u1"
    assert claims["email"] == "user@example.com"
    assert "iat" in claims and "exp" in claims


def test_a_non_ascii_email_round_trips_without_crashing() -> None:
    token = issue_token(SECRET, user_id="u1", email="müller@example.com")
    payload = verify_token(SECRET, token)
    assert payload is not None
    assert payload.email == "müller@example.com"


def test_a_tampered_signature_is_rejected() -> None:
    token = issue_token(SECRET, user_id="u1", email="user@example.com")
    header, payload_segment, signature = token.split(".")
    # Flip the FIRST character of the signature, not the last. The last
    # base64url character of a 32-byte HMAC-SHA256 signature only encodes
    # 2 significant bits (256 bits doesn't divide evenly into 6-bit
    # groups), so corrupting it had a real chance of decoding to the exact
    # same byte string -- a flaky false pass, reproduced multiple times.
    # The first character always encodes a full 6 bits, so any
    # substitution reliably changes the decoded signature.
    replacement = "a" if signature[0] != "a" else "b"
    tampered = f"{header}.{payload_segment}.{replacement}{signature[1:]}"
    assert verify_token(SECRET, tampered) is None


def test_a_token_signed_with_a_different_secret_is_rejected() -> None:
    token = issue_token(SECRET, user_id="u1", email="user@example.com")
    assert verify_token("a-different-secret", token) is None


def test_an_expired_token_is_rejected() -> None:
    now = int(time.time())
    expired_claims = {"sub": "u1", "email": "user@example.com", "iat": now - 1000, "exp": now - 1}
    expired_token = jwt.encode(expired_claims, SECRET, algorithm=ALGORITHM)
    assert verify_token(SECRET, expired_token) is None


def test_malformed_tokens_are_rejected_not_a_crash() -> None:
    for malformed in ("", "no-dot-here", "a.b", "a.b.c", "a.b.c.d"):
        assert verify_token(SECRET, malformed) is None


def test_a_token_with_wrong_field_types_is_rejected() -> None:
    now = int(time.time())
    bad_claims = {"sub": 123, "email": "x", "iat": "now", "exp": now + 100}
    bad_token = jwt.encode(bad_claims, SECRET, algorithm=ALGORITHM)
    assert verify_token(SECRET, bad_token) is None


def test_a_token_missing_required_claims_is_rejected() -> None:
    now = int(time.time())
    incomplete_claims = {"sub": "u1", "iat": now, "exp": now + 100}  # no "email"
    incomplete_token = jwt.encode(incomplete_claims, SECRET, algorithm=ALGORITHM)
    assert verify_token(SECRET, incomplete_token) is None


def test_the_none_algorithm_is_never_accepted() -> None:
    # The classic JWT vulnerability: a token whose header claims alg=none
    # and carries no signature at all must never be treated as valid, even
    # though verify_token always passes an explicit algorithms=[ALGORITHM]
    # allowlist to jwt.decode (which is what actually prevents this).
    now = int(time.time())
    none_alg_claims = {"sub": "u1", "email": "user@example.com", "iat": now, "exp": now + 100}
    forged = jwt.encode(none_alg_claims, key=None, algorithm="none")
    assert verify_token(SECRET, forged) is None
