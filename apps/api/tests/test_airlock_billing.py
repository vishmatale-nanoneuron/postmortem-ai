"""Airlock's money path: keys, credits, purchase, erasure.

Each test pins a property a paying customer or the founder would be hurt
by losing, and proves it against the real database rather than by reading
the code:

1. A key is never stored. Only its hash is, and the secret is returned
   exactly once.
2. A credit cannot be spent twice. Fifty concurrent scans against a balance
   of ten produce ten 200s and forty 402s -- never eleven 200s.
3. Buying is the existing claim flow. The amount is server-derived, the
   founder's approve grants exactly the credits on the claim, and approving
   twice is refused rather than granting twice.
4. The founder's manual grant is founder-only and leaves a ledger line.
5. Account deletion takes keys, balance and ledger with it -- and the
   append-only audit rows stay, because they never named the account.
"""

import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

FOUNDER_EMAIL = "airlock-billing-founder@example.com"
CUSTOMER_EMAIL = "airlock-billing-customer@example.com"
OTHER_EMAIL = "airlock-billing-other@example.com"
PASSWORD = "test-password-123"
BENIGN = "Invoice 2291. Amount due USD 4,200. Net 30."


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-0123456789abcdef0123")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    monkeypatch.setenv("FOUNDER_UPI_ID", "founder@upi")
    monkeypatch.setenv("AIRLOCK_PACK_SCANS", "1000")
    monkeypatch.setenv("AIRLOCK_PACK_PRICE_INR", "999")
    monkeypatch.setenv("AIRLOCK_MAX_PACKS_PER_CLAIM", "3")

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM airlock_scan_attempts")
    for email in (FOUNDER_EMAIL, CUSTOMER_EMAIL, OTHER_EMAIL):
        await database.execute("DELETE FROM users WHERE email=%s", (email,))

    application = create_app()
    application.state.database = database
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database

    await database.close()
    get_settings.cache_clear()


async def _sign_in_as(client: AsyncClient, email: str) -> str:
    client.cookies.clear()
    credentials = {"email": email, "password": PASSWORD}
    response = await client.post("/v1/auth/register", json=credentials)
    if response.status_code == 409:
        response = await client.post("/v1/auth/login", json=credentials)
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_a_key_is_shown_once_and_only_its_hash_is_stored(context):
    client, database = context
    await _sign_in_as(client, CUSTOMER_EMAIL)

    created = await client.post("/v1/airlock/keys", json={"label": "prod agent"})
    assert created.status_code == 201, created.text
    body = created.json()
    secret = body["secret"]
    assert secret.startswith("alk_") and len(secret) > 40
    assert body["prefix"] == secret[:12]

    # Nothing in the table holds the secret; the hash is not the secret.
    rows = await database.fetch_all("SELECT * FROM airlock_api_keys WHERE id=%s", (body["id"],))
    assert len(rows) == 1
    assert not any(isinstance(v, str) and secret in v for v in rows[0].values())
    assert len(rows[0]["key_hash"]) == 64

    # The list never includes it either.
    listed = (await client.get("/v1/airlock/keys")).json()
    assert listed[0]["id"] == body["id"]
    assert "secret" not in listed[0]
    assert listed[0]["prefix"] == body["prefix"]

    # Bearer works the same as the header, and a revoked key resolves to
    # nothing for both (test_airlock_scan_routes covers the header path).
    from app.cqrs.airlock_billing import resolve_api_key

    assert (await resolve_api_key(database, secret)) is not None
    assert (await resolve_api_key(database, secret + "x")) is None
    assert (await resolve_api_key(database, "not-a-key")) is None


@pytest.mark.asyncio
async def test_a_credit_cannot_be_spent_twice_under_concurrency(context):
    """The double-spend test. Fifty scans race for ten credits through the
    real route; the conditional UPDATE in handle_debit_credit is the only
    thing standing between this and eleven successes."""
    client, database = context
    from app.cqrs.airlock_billing import GrantCreditsCommand, handle_grant_credits

    user_id = await _sign_in_as(client, CUSTOMER_EMAIL)
    await handle_grant_credits(database, GrantCreditsCommand(user_id=user_id, credits=10, reason="grant", reference="t"))
    key = (await client.post("/v1/airlock/keys", json={})).json()["secret"]
    client.cookies.clear()

    async def one() -> int:
        response = await client.post("/v1/airlock/scan", json={"content": BENIGN}, headers={"X-Airlock-Key": key})
        return response.status_code

    statuses = await asyncio.gather(*(one() for _ in range(50)))
    assert statuses.count(200) == 10, statuses
    assert statuses.count(402) == 40, statuses

    balance = await database.fetch_one("SELECT balance FROM airlock_credit_balances WHERE user_id=%s", (user_id,))
    assert balance["balance"] == 0
    # Ten debit lines, no more: the ledger and the balance agree.
    ledger = await database.fetch_one(
        "SELECT coalesce(sum(delta), 0) AS net, count(*) FILTER (WHERE delta < 0) AS debits"
        " FROM airlock_credit_ledger WHERE user_id=%s",
        (user_id,),
    )
    assert ledger["net"] == 0
    assert ledger["debits"] == 10


@pytest.mark.asyncio
async def test_buying_a_pack_is_a_claim_the_founder_approves_once(context):
    """The purchase path end to end, on the rails that already exist. The
    client never states an amount; approval grants exactly the credits the
    claim recorded; a second approve is 409, not a second grant."""
    client, database = context
    await _sign_in_as(client, CUSTOMER_EMAIL)

    pricing = (await client.get("/v1/airlock/pricing")).json()
    assert pricing["scans_per_pack"] == 1000
    inr = next(p for p in pricing["prices"] if p["currency"] == "INR")
    assert inr == {"currency": "INR", "amount": 999, "method": "upi", "configured": True}

    # Two packs. The claim records the server's price and credits.
    claim = await client.post(
        "/v1/airlock/credits/claim", json={"currency": "INR", "reference": "UTR-AIRLOCK-0001", "packs": 2}
    )
    assert claim.status_code == 201, claim.text
    body = claim.json()
    assert body["product"] == "airlock"
    assert body["amount"] == 1998
    assert body["currency"] == "INR"
    assert body["method"] == "upi"
    assert body["scan_credits"] == 2000
    assert body["status"] == "pending"

    # Over the per-claim cap is refused, and a currency whose rail is not
    # configured is 503 rather than a claim nobody can pay.
    too_many = await client.post(
        "/v1/airlock/credits/claim", json={"currency": "INR", "reference": "UTR-AIRLOCK-0002", "packs": 4}
    )
    assert too_many.status_code == 422
    unpaid_rail = await client.post(
        "/v1/airlock/credits/claim", json={"currency": "USD", "reference": "WIRE-0001", "packs": 1}
    )
    assert unpaid_rail.status_code == 503

    # Nothing is granted by submitting. The subscription claim lists do not
    # show it, the Airlock one does.
    credits = (await client.get("/v1/airlock/credits")).json()
    assert credits["balance"] == 0
    assert (await client.get("/v1/billing/upi/claims")).json() == []
    assert [c["id"] for c in (await client.get("/v1/airlock/credits/claims")).json()] == [body["id"]]

    # The founder approves from the shared queue, which shows the product.
    await _sign_in_as(client, FOUNDER_EMAIL)
    queue = (await client.get("/v1/founder/payment-claims")).json()
    mine = next(c for c in queue if c["id"] == body["id"])
    assert mine["product"] == "airlock"
    assert mine["scan_credits"] == 2000
    approved = await client.post(f"/v1/founder/payment-claims/{body['id']}/approve")
    assert approved.status_code == 200, approved.text
    again = await client.post(f"/v1/founder/payment-claims/{body['id']}/approve")
    assert again.status_code == 409

    # The customer has exactly the credits on the claim, with a statement
    # line pointing at it, and no subscription was granted as a side effect.
    await _sign_in_as(client, CUSTOMER_EMAIL)
    credits = (await client.get("/v1/airlock/credits")).json()
    assert credits["balance"] == 2000
    assert credits["purchased_total"] == 2000
    assert credits["statement"][0]["reason"] == "purchase"
    assert credits["statement"][0]["reference"] == f"claim:{body['id']}"
    me = (await client.get("/v1/auth/me")).json()
    assert me["has_active_subscription"] is False


@pytest.mark.asyncio
async def test_the_founder_can_grant_credits_and_nobody_else_can(context):
    client, database = context
    await _sign_in_as(client, CUSTOMER_EMAIL)
    forbidden = await client.post(
        "/v1/founder/airlock/grant", json={"email": CUSTOMER_EMAIL, "credits": 500, "note": "self-serve?"}
    )
    assert forbidden.status_code == 403

    await _sign_in_as(client, FOUNDER_EMAIL)
    granted = await client.post(
        "/v1/founder/airlock/grant",
        json={"email": CUSTOMER_EMAIL.upper(), "credits": 500, "reason": "refund", "note": "outage on 12 Sep"},
    )
    assert granted.status_code == 200, granted.text
    assert granted.json() == {"email": CUSTOMER_EMAIL, "credits": 500, "balance": 500}
    unknown = await client.post(
        "/v1/founder/airlock/grant", json={"email": "nobody@example.com", "credits": 1, "note": "x"}
    )
    assert unknown.status_code == 404

    line = await database.fetch_one(
        "SELECT l.delta, l.reason, l.reference FROM airlock_credit_ledger l JOIN users u ON u.id=l.user_id"
        " WHERE u.email=%s ORDER BY l.created_at DESC LIMIT 1",
        (CUSTOMER_EMAIL,),
    )
    assert line["delta"] == 500
    assert line["reason"] == "refund"
    assert "outage on 12 Sep" in line["reference"]

    # The founder's own scans are not metered -- it is their product.
    founder_scan = await client.post("/v1/airlock/scan", json={"content": BENIGN})
    assert founder_scan.status_code == 200
    assert founder_scan.json()["credits_remaining"] is None


@pytest.mark.asyncio
async def test_the_signed_in_playground_spends_the_same_credits(context):
    """The dashboard's own scanner is not a free side door: a cookie
    session is charged exactly like a key, and an unfunded one gets the
    same 402."""
    client, database = context
    from app.cqrs.airlock_billing import GrantCreditsCommand, handle_grant_credits

    user_id = await _sign_in_as(client, CUSTOMER_EMAIL)
    assert (await client.post("/v1/airlock/scan", json={"content": BENIGN})).status_code == 402
    await handle_grant_credits(database, GrantCreditsCommand(user_id=user_id, credits=2, reason="grant", reference="t"))
    first = await client.post("/v1/airlock/scan", json={"content": BENIGN})
    assert first.status_code == 200
    assert first.json()["credits_remaining"] == 1
    # The statement attributes a cookie scan to no key.
    credits = (await client.get("/v1/airlock/credits")).json()
    assert credits["used_total"] == 1
    usage = next(e for e in credits["statement"] if e["reason"] == "usage")
    assert usage["key_prefix"] is None
    assert usage["delta"] == -1


@pytest.mark.asyncio
async def test_another_account_cannot_see_or_revoke_my_keys(context):
    client, _database = context
    await _sign_in_as(client, CUSTOMER_EMAIL)
    mine = (await client.post("/v1/airlock/keys", json={"label": "mine"})).json()

    await _sign_in_as(client, OTHER_EMAIL)
    assert (await client.get("/v1/airlock/keys")).json() == []
    # 404, not 403: a foreign id must not confirm the key exists.
    assert (await client.delete(f"/v1/airlock/keys/{mine['id']}")).status_code == 404

    await _sign_in_as(client, CUSTOMER_EMAIL)
    assert (await client.get("/v1/airlock/keys")).json()[0]["revoked_at"] is None


@pytest.mark.asyncio
async def test_the_key_cap_holds_under_concurrent_creation(context):
    client, _database = context
    from app.cqrs.airlock_billing import MAX_ACTIVE_KEYS_PER_USER

    await _sign_in_as(client, CUSTOMER_EMAIL)

    async def one() -> int:
        return (await client.post("/v1/airlock/keys", json={})).status_code

    statuses = await asyncio.gather(*(one() for _ in range(MAX_ACTIVE_KEYS_PER_USER + 5)))
    assert statuses.count(201) == MAX_ACTIVE_KEYS_PER_USER, statuses
    assert statuses.count(409) == 5


@pytest.mark.asyncio
async def test_deleting_the_account_erases_keys_and_credits_but_not_the_audit_log(context):
    """The two guarantees this design exists to keep at the same time. The
    audit rows survive because they never said whose they were."""
    client, database = context
    from app.cqrs.airlock_billing import GrantCreditsCommand, handle_grant_credits

    user_id = await _sign_in_as(client, CUSTOMER_EMAIL)
    await handle_grant_credits(database, GrantCreditsCommand(user_id=user_id, credits=3, reason="grant", reference="t"))
    await client.post("/v1/airlock/keys", json={})
    scan = await client.post("/v1/airlock/scan", json={"content": BENIGN})
    assert scan.status_code == 200
    digest = scan.json()["content_sha256"]
    audit_before = await database.fetch_one(
        "SELECT count(*) AS n FROM airlock_scan_events WHERE content_sha256=%s", (digest,)
    )

    deleted = await client.request("DELETE", "/v1/auth/me", json={"password": PASSWORD})
    assert deleted.status_code in (200, 204), deleted.text

    for table in ("airlock_api_keys", "airlock_credit_balances", "airlock_credit_ledger"):
        row = await database.fetch_one(f"SELECT count(*) AS n FROM {table} WHERE user_id=%s", (user_id,))
        assert row["n"] == 0, table
    audit_after = await database.fetch_one(
        "SELECT count(*) AS n FROM airlock_scan_events WHERE content_sha256=%s", (digest,)
    )
    assert audit_after["n"] == audit_before["n"]


@pytest.mark.asyncio
async def test_the_openapi_contract_documents_the_paid_api(context):
    """A generated client, or a buyer reading /docs, must see how to
    authenticate and what 401/402/429 mean without reading the source."""
    client, _database = context
    schema = (await client.get("/openapi.json")).json()
    scan = schema["paths"]["/v1/airlock/scan"]["post"]
    assert {"401", "402", "422", "429"} <= set(scan["responses"])
    assert "402" in scan["responses"] and "credits" in scan["responses"]["402"]["description"].lower()
    schemes = schema["components"]["securitySchemes"]
    by_kind = {(s.get("type"), s.get("in"), s.get("scheme")): s for s in schemes.values()}
    assert by_kind[("apiKey", "header", None)]["name"] == "X-Airlock-Key"
    assert ("http", None, "bearer") in by_kind
    # The session cookie is declared too, so session routes say how they
    # authenticate instead of leaving it implicit.
    assert by_kind[("apiKey", "cookie", None)]["name"] == "session_token"
    # The scan route declares the two key schemes, so "Authorize" in /docs
    # applies to it; the session routes declare the cookie.
    declared = {name for entry in scan["security"] for name in entry}
    assert len(declared) == 2 and all(schemes[n]["type"] in ("apiKey", "http") for n in declared)
    keys_route = schema["paths"]["/v1/airlock/keys"]["post"]
    assert {name for entry in keys_route["security"] for name in entry} == {"APIKeyCookie"}
    assert any(t["name"] == "airlock" for t in schema["tags"])
    # Clean operationIds for generated clients, and the document metadata a
    # reviewer or SDK generator needs.
    assert scan["operationId"] == "scan"
    assert keys_route["operationId"] == "create_key"
    assert schema["info"]["contact"]["url"].rstrip("/") == "https://www.nanoneuron.ai"
    assert schema["info"]["termsOfService"] == "https://www.nanoneuron.ai/terms"
    assert schema["servers"][0]["url"] == "https://postmortem-ai-api.vercel.app"

    # Public reads are cacheable; metered writes are not.
    assert "max-age" in (await client.get("/v1/airlock/pricing")).headers["cache-control"]
    assert "max-age" in (await client.get("/v1/airlock/stats")).headers["cache-control"]


@pytest.mark.asyncio
async def test_authenticated_responses_are_still_never_cached(context):
    """The public-read opt-out must not have loosened anything that carries
    account data: the session, the balance and the keys stay no-store."""
    client, _database = context
    await _sign_in_as(client, CUSTOMER_EMAIL)
    for path in ("/v1/auth/me", "/v1/airlock/credits", "/v1/airlock/keys", "/v1/billing/status"):
        response = await client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "private, no-store, must-revalidate", path
        assert response.headers["vary"] == "Cookie", path


@pytest.mark.asyncio
async def test_every_response_carries_a_request_id_and_timing(context):
    """Correlation and app-side latency on every response: a customer can
    quote X-Request-ID from a failed scan and it matches the log line; a
    supplied id is echoed so their own trace id survives the hop."""
    client, _database = context
    fresh = await client.get("/v1/airlock/pricing")
    assert len(fresh.headers["x-request-id"]) == 32
    assert fresh.headers["server-timing"].startswith("app;dur=")
    echoed = await client.get("/v1/airlock/pricing", headers={"X-Request-ID": "trace-abc-123"})
    assert echoed.headers["x-request-id"] == "trace-abc-123"
    # Unprintable or oversized ids are replaced, never echoed into logs.
    junk = await client.get("/v1/airlock/pricing", headers={"X-Request-ID": "x" * 500})
    assert junk.headers["x-request-id"] != "x" * 500
    # Large bodies are compressed when the caller accepts it.
    gz = await client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert gz.headers.get("content-encoding") == "gzip"
    assert gz.status_code == 200 and "paths" in gz.json()


@pytest.mark.asyncio
async def test_a_rate_limited_response_says_when_to_retry(context):
    client, _database = context
    from app.security.rate_limit import MAX_AIRLOCK_SCANS_PER_IP

    client.cookies.clear()
    for _ in range(MAX_AIRLOCK_SCANS_PER_IP):
        await client.post("/v1/airlock/scan", json={"content": BENIGN})
    limited = await client.post("/v1/airlock/scan", json={"content": BENIGN})
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "3600"


@pytest.mark.asyncio
async def test_the_customer_is_emailed_when_the_balance_runs_low_and_when_it_empties(context, monkeypatch):
    """Exactly one email per crossing, on the call that crosses: the low
    mark once (not on every call under it) and empty once. Proved by
    counting sends through a fake, with the balance driven across both
    lines by real charges."""
    client, database = context
    import app.api.v1.airlock as airlock_module
    from app.airlock.semantic import DEEP_SCAN_EXTRA_CREDITS
    from app.cqrs.airlock_billing import GrantCreditsCommand, handle_grant_credits

    sent: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        airlock_module,
        "send_airlock_balance_email",
        lambda settings, to, remaining, *, empty: sent.append((to, remaining, empty)),
    )
    user_id = await _sign_in_as(client, CUSTOMER_EMAIL)
    # 1,003 credits: three plain scans reach 1,000 (not yet below), the
    # fourth crosses to 999 -> one "low" email. Then drain to zero.
    await handle_grant_credits(
        database, GrantCreditsCommand(user_id=user_id, credits=1_003, reason="grant", reference="t")
    )
    for _ in range(3):
        assert (await client.post("/v1/airlock/scan", json={"content": BENIGN})).status_code == 200
    assert sent == []
    assert (await client.post("/v1/airlock/scan", json={"content": BENIGN})).status_code == 200
    assert sent == [(CUSTOMER_EMAIL, 999, False)]
    # Further calls under the line do not repeat the low email.
    assert (await client.post("/v1/airlock/scan", json={"content": BENIGN})).status_code == 200
    assert len(sent) == 1

    # Drain: a fresh account with exactly 1 + extra credits, one deep scan
    # (charged 1 + extra with the model answering) empties it -> one
    # "empty" email; the next call is 402 and sends nothing.
    sent.clear()
    await _sign_in_as(client, OTHER_EMAIL)
    other = (await client.get("/v1/auth/me")).json()["id"]
    await handle_grant_credits(
        database, GrantCreditsCommand(user_id=other, credits=1 + DEEP_SCAN_EXTRA_CREDITS, reason="grant", reference="t")
    )
    from app.api.v1.airlock import get_model_provider

    class Fake:
        model_name = "fake"

        async def complete(self, request):
            from app.ai.provider import ModelResponse

            return ModelResponse(text='{"injection": false, "confidence": 0.1, "family": null, "reason": "x"}')

    client._transport.app.dependency_overrides[get_model_provider] = lambda: (lambda: Fake())  # type: ignore[attr-defined]
    deep = await client.post("/v1/airlock/scan", json={"content": BENIGN, "deep": True})
    assert deep.status_code == 200 and deep.json()["credits_remaining"] == 0
    assert sent == [(OTHER_EMAIL, 0, True)]
    assert (await client.post("/v1/airlock/scan", json={"content": BENIGN})).status_code == 402
    assert len(sent) == 1
