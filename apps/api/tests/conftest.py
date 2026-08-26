"""Shared, autouse test setup.

registration_attempts, login_attempts, and password_reset_attempts (security/rate_limit.py) are real
Postgres tables, and every test file's own ASGI test client reports the same
client_ip() -- httpx's ASGITransport doesn't set request.client, so
client_ip() falls back to "unknown" for literally every test request in the
whole suite. Without clearing both globally, attempts accumulate across the
ENTIRE test run (every file, every invocation of the suite against the same
database) and eventually trip the real rate limiter, failing unrelated tests
with 429s that have nothing to do with what they're actually testing --
reproduced directly: running the full suite repeatedly against one
long-lived local Postgres container (the normal way to iterate locally) is
enough to accumulate past MAX_LOGIN_ATTEMPTS, at which point
test_put_me_requires_both_fields_and_replaces_password and its neighbors
started failing with 429 instead of their real assertions, with no code
change involved at all. login_attempts is additionally keyed by email, but
that doesn't help here -- multiple test files reuse literal email strings
like "auth-test-put-1@example.com" from run to run.
"""

import os

import psycopg
import pytest

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def _clear_rate_limit_tables():
    if DATABASE_URL:
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute("DELETE FROM registration_attempts")
            connection.execute("DELETE FROM login_attempts")
            connection.execute("DELETE FROM password_reset_attempts")
    yield
