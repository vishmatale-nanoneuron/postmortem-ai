import base64
import json
import time

from app.security.tokens import _sign, issue_token, verify_token

SECRET = "test-secret-do-not-use-in-production"


def test_a_valid_token_round_trips() -> None:
    token = issue_token(SECRET, user_id="u1", email="user@example.com")
    payload = verify_token(SECRET, token)
    assert payload is not None
    assert payload.user_id == "u1"
    assert payload.email == "user@example.com"


def test_a_non_ascii_email_round_trips_without_crashing() -> None:
    # The exact regression class found and fixed in nanoneuron-software-
    # company's founder() dependency this session: comparing raw str with
    # secrets.compare_digest raises TypeError on non-ASCII input, which
    # surfaced as an unhandled 500 instead of a clean 403. verify_token
    # compares UTF-8-encoded bytes throughout, so this must not crash.
    token = issue_token(SECRET, user_id="u1", email="müller@example.com")
    payload = verify_token(SECRET, token)
    assert payload is not None
    assert payload.email == "müller@example.com"


def test_a_tampered_signature_is_rejected() -> None:
    token = issue_token(SECRET, user_id="u1", email="user@example.com")
    body, signature = token.split(".", 1)
    tampered = f"{body}.{signature[:-1]}x"
    assert verify_token(SECRET, tampered) is None


def test_a_token_signed_with_a_different_secret_is_rejected() -> None:
    token = issue_token(SECRET, user_id="u1", email="user@example.com")
    assert verify_token("a-different-secret", token) is None


def test_an_expired_token_is_rejected() -> None:
    import app.security.tokens as tokens_module

    original_ttl = tokens_module.SESSION_TTL_SECONDS
    tokens_module.SESSION_TTL_SECONDS = -1
    try:
        token = issue_token(SECRET, user_id="u1", email="user@example.com")
    finally:
        tokens_module.SESSION_TTL_SECONDS = original_ttl
    assert verify_token(SECRET, token) is None


def test_malformed_tokens_are_rejected_not_a_crash() -> None:
    for malformed in ("", "no-dot-here", "body-only.", ".signature-only", "a.b.c"):
        assert verify_token(SECRET, malformed) is None


def test_a_token_with_wrong_field_types_is_rejected() -> None:
    bad_payload = json.dumps({"user_id": 123, "email": "x", "issued_at": "now", "expires_at": int(time.time()) + 100})
    body = base64.urlsafe_b64encode(bad_payload.encode("utf-8")).decode("ascii")
    signature = _sign(SECRET, body)
    assert verify_token(SECRET, f"{body}.{signature}") is None
