"""Shared, autouse test setup.

registration_attempts (security/rate_limit.py's try_record_registration_attempt)
is a real Postgres table, and every test file's own ASGI test client reports the
same client_ip() -- httpx's ASGITransport doesn't set request.client, so
client_ip() falls back to "unknown" for literally every test request in the
whole suite. Without this, the first ~5 register() calls across the entire
test run (across every file) would trip MAX_REGISTRATIONS_PER_IP and start
failing unrelated tests with 429s that have nothing to do with what they're
actually testing. Cleared before every test, independent of whatever each
file's own fixture already cleans up (users, login_attempts, etc.) -- this
runs even for test files that don't otherwise touch the database.
"""

import os

import psycopg
import pytest

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def _clear_registration_attempts():
    if DATABASE_URL:
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute("DELETE FROM registration_attempts")
    yield
