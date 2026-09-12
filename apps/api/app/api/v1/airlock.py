"""Airlock: a paid guard between an agent and untrusted content.

Two directions, two endpoints:

- POST /scan scores inbound text for prompt injection before it reaches a
  model's context window.
- POST /egress checks an outbound call's destination and payload for
  credentials and personal data before it leaves.

Both are metered. A call is authenticated by an API key (`X-Airlock-Key`
or `Authorization: Bearer alk_...`) or, for the dashboard playground, by
the session cookie; it spends one prepaid credit, and a call with no
credit to spend is refused with 402 before any verdict is returned. There
is no free allowance. Credits are bought as packs over the same manual
UPI/wire rails as the PostMortem AI subscription (billing.py), approved
from the founder dashboard, and land as a ledger line the customer can
read back (GET /credits).

The verdict path and the money path are kept apart on purpose: the
detector never sees who is asking, and cqrs/airlock_billing.py never sees
what was scanned. Every decision is still recorded in the append-only
audit table (migration 0031) that holds a hash and a byte count, never the
content and never the account.

The waitlist endpoint is retained for the self-hosted version, which does
not exist yet. It answers 202 whether the address was new or already on
the list, so the response can never be used to learn who signed up.
"""

import hashlib
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field

from ...ai.model_router import create_model_provider
from ...ai.provider import ModelProvider
from ...airlock import Detector, check_egress
from ...airlock.rules import RULES_BY_ID
from ...airlock.semantic import (
    DEEP_SCAN_EXTRA_CREDITS,
    SEMANTIC_MAX_WEIGHT,
    SEMANTIC_RULE_ID,
    combine,
    semantic_opinion,
)
from ...auth import User, _resolve_user_from_cookie, current_founder, current_user
from ...cqrs.airlock_billing import (
    MAX_ACTIVE_KEYS_PER_USER,
    DebitCreditCommand,
    GrantCreditsCommand,
    InsufficientCredits,
    IssueApiKeyCommand,
    RevokeApiKeyCommand,
    TooManyKeys,
    handle_api_keys_query,
    handle_credit_balance_query,
    handle_debit_credit,
    handle_grant_credits,
    handle_issue_api_key,
    handle_ledger_query,
    handle_revoke_api_key,
    resolve_api_key,
)
from ...cqrs.airlock_scan import RecordScanCommand, handle_record_scan, handle_scan_stats_query
from ...cqrs.airlock_waitlist import (
    JoinWaitlistCommand,
    WaitlistQuery,
    handle_join_waitlist,
    handle_waitlist_query,
)
from ...database import Database
from ...dependencies import get_database
from ...security.rate_limit import (
    client_ip,
    try_record_action,
    try_record_airlock_scan_attempt,
    try_record_airlock_waitlist_attempt,
)
from ...services.email import (
    EmailNotConfiguredError,
    build_upi_payment_link,
    send_airlock_payment_details_email,
)
from ...settings import Settings, get_settings
from .billing import (
    MAX_PAYMENT_DETAILS_EMAILS_PER_WINDOW,
    PAYMENT_DETAILS_EMAIL_WINDOW_MS,
    RATE_LIMITED_DETAIL,
    ClaimOut,
    _CLAIM_COLUMNS,
    _insert_claim,
    _wire_currency_details,
)

logger = logging.getLogger("postmortem_ai")

# Built once at import, not per request: compiling 30 regexes on every call
# would dominate the latency the endpoint reports. Stateless, so sharing it
# across concurrent requests is safe.
_DETECTOR = Detector()

router = APIRouter(prefix="/v1/airlock", tags=["airlock"])

KEY_HEADER = "X-Airlock-Key"

NO_CREDITS_DETAIL = "No Airlock credits left. Buy a pack from the Airlock section of your dashboard."
NOT_AUTHENTICATED_DETAIL = (
    f"Airlock is a paid API. Send your key in the {KEY_HEADER} header, or sign in to use the dashboard."
)


# ---------------------------------------------------------------------------
# Who is asking. A key first (the API), then the session cookie (the
# dashboard playground). Anything else is 401 -- after the per-IP limiter
# has counted the attempt, so an unauthenticated flood is bounded.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AirlockPrincipal:
    user_id: str
    api_key_id: str | None
    # The founder scans without spending credits: it is their product, and a
    # demo or a test from the founder's own account should not need a
    # purchase from themselves.
    is_founder: bool


def _key_from_request(request: Request) -> str | None:
    header = request.headers.get(KEY_HEADER)
    if header:
        return header.strip()
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def airlock_principal(
    request: Request,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> AirlockPrincipal:
    secret = _key_from_request(request)
    if secret:
        resolved = await resolve_api_key(database, secret)
        if resolved is not None:
            return AirlockPrincipal(user_id=resolved.user_id, api_key_id=resolved.id, is_founder=False)
        # An invalid key is counted against the IP before it is refused, so
        # guessing keys costs the guesser their request budget.
        await try_record_airlock_scan_attempt(database, client_ip(request))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked Airlock key")

    user = await _resolve_user_from_cookie(request, database, settings)
    if user is not None:
        return AirlockPrincipal(user_id=user.id, api_key_id=None, is_founder=user.is_founder)

    if not await try_record_airlock_scan_attempt(database, client_ip(request)):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=NOT_AUTHENTICATED_DETAIL)


async def _charge(database: Database, principal: AirlockPrincipal, reason: str, credits: int = 1) -> int | None:
    """Spends `credits` in one debit, or raises the 402. Returns the balance
    after, or None when nothing was charged (the founder)."""
    if principal.is_founder:
        return None
    try:
        return await handle_debit_credit(
            database,
            DebitCreditCommand(
                user_id=principal.user_id, reason=reason, api_key_id=principal.api_key_id, credits=credits
            ),
        )
    except InsufficientCredits:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=NO_CREDITS_DETAIL) from None


def get_model_provider(settings: Settings = Depends(get_settings)) -> Callable[[], ModelProvider]:
    """The same Gemini provider (with the same circuit breaker and optional
    fallback) that drafts postmortems -- returned as a zero-argument factory,
    not an instance, so a plain scan never constructs the model client at
    all. Found the hard way: constructing it eagerly made every ordinary
    scan 500 in an environment with no Gemini key, when the ordinary scan
    does not need Gemini. A dependency so tests can swap it."""
    return lambda: create_model_provider(settings)


# ---------------------------------------------------------------------------
# Waitlist (self-hosted interest). Unchanged.
# ---------------------------------------------------------------------------


class WaitlistIn(BaseModel):
    email: EmailStr
    # Both optional: a bare address is a real signal and demanding a company
    # name to express interest costs more signups than the field is worth.
    company: str | None = Field(default=None, max_length=200)
    use_case: str | None = Field(default=None, max_length=2000)


class WaitlistOut(BaseModel):
    status: str


class WaitlistEntryOut(BaseModel):
    id: str
    email: str
    company: str | None
    use_case: str | None
    created_at: int


@router.post("/waitlist", response_model=WaitlistOut, status_code=status.HTTP_202_ACCEPTED)
async def join_waitlist(
    payload: WaitlistIn,
    request: Request,
    database: Database = Depends(get_database),
) -> WaitlistOut:
    ip = client_ip(request)
    if not await try_record_airlock_waitlist_attempt(database, ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests from this address. Try again later.",
        )
    # Normalisation, the INSERT and the ON CONFLICT all live in the command
    # handler, not here -- this route validates and rate-limits, which is
    # what a route is for.
    await handle_join_waitlist(
        database,
        JoinWaitlistCommand(email=payload.email, company=payload.company, use_case=payload.use_case),
    )
    return WaitlistOut(status="accepted")


@router.get("/waitlist", response_model=list[WaitlistEntryOut])
async def list_waitlist(
    database: Database = Depends(get_database),
    _founder: User = Depends(current_founder),
) -> list[WaitlistEntryOut]:
    """Founder-only. The list is the whole point of the page, and it is not
    readable anywhere else."""
    entries = await handle_waitlist_query(database, WaitlistQuery())
    return [WaitlistEntryOut(**vars(entry)) for entry in entries]


# ---------------------------------------------------------------------------
# The scanner.
# ---------------------------------------------------------------------------

# Bounds the CPU one request can spend in 30 regexes. Far above any real
# document an agent reads in one step.
MAX_SCAN_CHARS = 50_000
MAX_EGRESS_PAYLOAD_CHARS = 20_000


class ScanIn(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_SCAN_CHARS)
    # Free-form label for where the content came from ("support_ticket",
    # "web"). Recorded on the audit row; never interpreted.
    source: str | None = Field(default=None, max_length=64)
    # Ask Gemini for a second opinion after the rules have run. Costs
    # DEEP_SCAN_EXTRA_CREDITS more, sends the content to Google's API, and
    # can only make the verdict stricter -- see airlock/semantic.py.
    deep: bool = False


class MatchOut(BaseModel):
    rule_id: str
    family: str
    weight: float
    description: str


class ScanOut(BaseModel):
    verdict: str
    score: float
    matches: list[MatchOut]
    families: list[str]
    # What normalisation uncovered before any rule ran -- hidden HTML
    # comments, decoded Unicode tag payloads, spaced-out text. The most
    # useful half of the answer when the verdict is a surprise.
    signals: dict
    content_sha256: str
    content_bytes: int
    latency_ms: int
    # Balance after this call. None when the call was not charged (founder).
    credits_remaining: int | None
    # What this call cost. 1, or 1 + DEEP_SCAN_EXTRA_CREDITS for a deep scan
    # that got its second opinion; back to 1 if Gemini was unavailable and
    # the extra was refunded. 0 for the founder.
    credits_charged: int
    # Present only on a deep scan: the model's answer, its confidence, the
    # weight it contributed, or status "unavailable" with weight 0.
    semantic: dict | None = None


class EgressIn(BaseModel):
    payload: str = Field(min_length=1, max_length=MAX_EGRESS_PAYLOAD_CHARS)
    destination: str | None = Field(default=None, max_length=2000)
    allowlist: list[str] = Field(default_factory=list, max_length=100)


class EgressOut(BaseModel):
    verdict: str
    score: float
    reasons: list[str]
    secrets_found: list[str]
    pii_found: dict
    destination: str | None
    # False when no allowlist was supplied, in which case ANY destination
    # passes and only the payload was examined. Returned explicitly because
    # the alternative is a caller believing they have a destination control
    # they never configured -- the failure mode of a security default that
    # is silently permissive.
    destination_checked: bool
    # The payload with credential material and personal data replaced, so a
    # caller can see exactly what would have been safe to send.
    #
    # None when there was nothing to redact. It must be Optional: the engine
    # returns None for a clean payload, and typing it `str` made every
    # CLEAN egress call fail response validation with a 500 -- the one path
    # most likely to be the common case in production, and the one every
    # test missed because they all carried a secret. Found by auditing, not
    # by a user hitting it.
    redacted: str | None
    credits_remaining: int | None
    credits_charged: int


@router.post("/scan", response_model=ScanOut)
async def scan(
    payload: ScanIn,
    database: Database = Depends(get_database),
    principal: AirlockPrincipal = Depends(airlock_principal),
    model_provider: Callable[[], ModelProvider] = Depends(get_model_provider),
) -> ScanOut:
    """Score untrusted content for prompt injection, before it reaches an
    agent's context window. One credit per call (five with `deep`); 402
    with nothing scanned when the balance is short."""
    # Charge before scanning, not after: a caller with no credits gets the
    # 402 without the engine running for them, and a caller with credits is
    # charged for exactly the calls that return a verdict. The detector is
    # pure and does not fail, so there is no "charged but no answer" path.
    # A deep scan is taken as one debit for the whole price, so a caller
    # either affords the second opinion or is told so up front.
    cost = 1 + DEEP_SCAN_EXTRA_CREDITS if payload.deep else 1
    remaining = await _charge(database, principal, "deep_scan" if payload.deep else "scan", cost)
    charged = 0 if principal.is_founder else cost

    started = time.perf_counter()
    detection = _DETECTOR.scan(payload.content)
    verdict, score = detection.verdict, detection.score
    matched_rules = [match.rule_id for match in detection.matches]
    matches = [
        MatchOut(
            rule_id=match.rule_id,
            family=match.family,
            weight=match.weight,
            description=RULES_BY_ID[match.rule_id].description if match.rule_id in RULES_BY_ID else "",
        )
        for match in detection.matches
    ]
    families = list(detection.families)
    semantic: dict | None = None

    if payload.deep:
        opinion = await semantic_opinion(model_provider, payload.content)
        semantic = opinion.as_dict()
        if opinion.status == "ok":
            score, verdict = combine(detection.score, opinion)
            if opinion.weight > 0:
                # The model's contribution appears alongside the rules, under
                # its own id, so the audit row and the response both say the
                # classifier had a hand in this verdict.
                matched_rules.append(SEMANTIC_RULE_ID)
                matches.append(
                    MatchOut(
                        rule_id=SEMANTIC_RULE_ID,
                        family=opinion.family or "AI",
                        weight=opinion.weight,
                        description=opinion.reason
                        or f"Gemini classified this as an injection attempt (max weight {SEMANTIC_MAX_WEIGHT}).",
                    )
                )
                if opinion.family and opinion.family not in families:
                    families.append(opinion.family)
        elif not principal.is_founder:
            # The customer paid for a second opinion that did not arrive.
            # Refund exactly the extra, leave the ordinary scan charged, and
            # say so in the response.
            remaining = await handle_grant_credits(
                database,
                GrantCreditsCommand(
                    user_id=principal.user_id,
                    credits=DEEP_SCAN_EXTRA_CREDITS,
                    reason="refund",
                    reference="deep scan: second opinion unavailable",
                ),
            )
            charged = 1
    latency_ms = int((time.perf_counter() - started) * 1000)

    await handle_record_scan(
        database,
        RecordScanCommand(
            kind="ingress",
            verdict=verdict,
            score=score,
            content_sha256=detection.content_sha256,
            content_bytes=detection.content_bytes,
            matched_rules=matched_rules,
            source=payload.source,
            latency_ms=latency_ms,
            # No excerpt: see RecordScanCommand.excerpt and 0031's header.
        ),
    )
    return ScanOut(
        verdict=verdict,
        score=round(score, 4),
        matches=matches,
        families=families,
        # Signal *names* and what was found, which is the explanatory half.
        signals={key: value for key, value in (detection.signals or {}).items()},
        content_sha256=detection.content_sha256,
        content_bytes=detection.content_bytes,
        latency_ms=latency_ms,
        credits_remaining=remaining,
        credits_charged=charged,
        semantic=semantic,
    )


@router.post("/egress", response_model=EgressOut)
async def egress(
    payload: EgressIn,
    database: Database = Depends(get_database),
    principal: AirlockPrincipal = Depends(airlock_principal),
) -> EgressOut:
    """Check an outbound call for credentials and personal data, and its
    destination against an allowlist, before the agent sends it. One
    credit per call."""
    remaining = await _charge(database, principal, "egress")
    started = time.perf_counter()
    verdict = check_egress(
        payload=payload.payload,
        destination=payload.destination,
        allowlist=list(payload.allowlist),
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    await handle_record_scan(
        database,
        RecordScanCommand(
            kind="egress",
            verdict=verdict.verdict,
            score=verdict.score,
            content_sha256=hashlib.sha256(payload.payload.encode()).hexdigest(),
            content_bytes=len(payload.payload.encode()),
            matched_rules=list(verdict.secrets_found),
            source=verdict.destination,
            latency_ms=latency_ms,
        ),
    )
    return EgressOut(
        verdict=verdict.verdict,
        score=round(verdict.score, 4),
        reasons=list(verdict.reasons),
        secrets_found=list(verdict.secrets_found),
        pii_found=dict(verdict.pii_found or {}),
        destination=verdict.destination,
        destination_checked=bool(payload.allowlist),
        redacted=verdict.redacted,
        credits_remaining=remaining,
        credits_charged=0 if principal.is_founder else 1,
    )


class ScanStatsOut(BaseModel):
    total: int
    blocked: int
    flagged: int
    allowed: int
    last_7d: int
    top_rules: list[dict]


@router.get("/stats", response_model=ScanStatsOut)
async def stats(database: Database = Depends(get_database)) -> ScanStatsOut:
    """Public, and aggregate-only by construction (see cqrs/airlock_scan.py).
    Published rather than kept private: a scanner that tells you how often
    it fires, and which rules do the work, is easier to trust than one that
    asks you to take its accuracy on faith."""
    counts = await handle_scan_stats_query(database)
    return ScanStatsOut(**vars(counts))


# ---------------------------------------------------------------------------
# Pricing. Public and price-only, like /v1/billing/upi/pricing: the page
# that quotes a price must never need an account to render it, and the
# real payee details are never in this response.
# ---------------------------------------------------------------------------


class PackPriceOut(BaseModel):
    currency: str
    amount: int
    # Which manual rail takes this currency. INR is UPI; the rest are wire.
    method: str
    configured: bool


class PricingOut(BaseModel):
    scans_per_pack: int
    max_packs_per_claim: int
    # Credits per call. A deep scan adds a Gemini second opinion.
    credits_per_scan: int = 1
    credits_per_deep_scan: int = 1 + DEEP_SCAN_EXTRA_CREDITS
    prices: list[PackPriceOut]


def _pack_prices(settings: Settings) -> list[PackPriceOut]:
    wire_ok = bool(settings.founder_bank_account_number)
    return [
        PackPriceOut(currency="INR", amount=settings.airlock_pack_price_inr, method="upi", configured=bool(settings.founder_upi_id)),
        PackPriceOut(currency="USD", amount=settings.airlock_pack_price_usd, method="wire", configured=wire_ok),
        PackPriceOut(currency="GBP", amount=settings.airlock_pack_price_gbp, method="wire", configured=wire_ok),
        PackPriceOut(currency="EUR", amount=settings.airlock_pack_price_eur, method="wire", configured=wire_ok),
    ]


@router.get("/pricing", response_model=PricingOut)
async def pricing(settings: Settings = Depends(get_settings)) -> PricingOut:
    return PricingOut(
        scans_per_pack=settings.airlock_pack_scans,
        max_packs_per_claim=settings.airlock_max_packs_per_claim,
        prices=_pack_prices(settings),
    )


# ---------------------------------------------------------------------------
# Keys. Cookie-authenticated: a key is minted from the dashboard, never
# from another key.
# ---------------------------------------------------------------------------


class CreateKeyIn(BaseModel):
    label: str = Field(default="", max_length=80)


class ApiKeyOut(BaseModel):
    id: str
    label: str
    prefix: str
    created_at: int
    last_used_at: int | None
    revoked_at: int | None


class CreatedKeyOut(ApiKeyOut):
    # The one and only time the full key leaves the server.
    secret: str


@router.post("/keys", response_model=CreatedKeyOut, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: CreateKeyIn,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> CreatedKeyOut:
    try:
        issued = await handle_issue_api_key(database, IssueApiKeyCommand(user_id=user.id, label=payload.label))
    except TooManyKeys:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have {MAX_ACTIVE_KEYS_PER_USER} active keys. Revoke one first.",
        ) from None
    return CreatedKeyOut(
        id=issued.id,
        label=issued.label,
        prefix=issued.prefix,
        created_at=issued.created_at,
        last_used_at=None,
        revoked_at=None,
        secret=issued.secret,
    )


@router.get("/keys", response_model=list[ApiKeyOut])
async def list_keys(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> list[ApiKeyOut]:
    return [ApiKeyOut(**vars(key)) for key in await handle_api_keys_query(database, user.id)]


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: str,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> None:
    if not await handle_revoke_api_key(database, RevokeApiKeyCommand(user_id=user.id, key_id=key_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")


# ---------------------------------------------------------------------------
# Credits: the balance, the statement, and buying more.
# ---------------------------------------------------------------------------


class LedgerEntryOut(BaseModel):
    delta: int
    reason: str
    reference: str | None
    key_prefix: str | None
    created_at: int


class CreditsOut(BaseModel):
    balance: int
    purchased_total: int
    used_total: int
    used_last_30d: int
    statement: list[LedgerEntryOut]


@router.get("/credits", response_model=CreditsOut)
async def credits(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> CreditsOut:
    balance = await handle_credit_balance_query(database, user.id)
    statement = await handle_ledger_query(database, user.id)
    return CreditsOut(**vars(balance), statement=[LedgerEntryOut(**vars(entry)) for entry in statement])


Currency = Literal["INR", "USD", "GBP", "EUR"]


class PackClaimIn(BaseModel):
    currency: Currency
    reference: str = Field(min_length=4, max_length=200)
    packs: int = Field(default=1, ge=1)


def _quote(settings: Settings, currency: str, packs: int) -> tuple[PackPriceOut, int, int]:
    """(price row, amount, credits) for a purchase -- all server-derived
    from settings, never from the client, for the same reason billing.py
    derives every subscription amount: a client-supplied amount lets anyone
    claim ten packs for the price of one."""
    if packs > settings.airlock_max_packs_per_claim:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"At most {settings.airlock_max_packs_per_claim} packs per payment. For more, email the founder.",
        )
    price = next(p for p in _pack_prices(settings) if p.currency == currency)
    if not price.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"{price.method.upper()} payment is not configured"
        )
    return price, price.amount * packs, settings.airlock_pack_scans * packs


@router.post("/credits/claim", status_code=status.HTTP_201_CREATED, response_model=ClaimOut)
async def submit_pack_claim(
    payload: PackClaimIn,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> ClaimOut:
    """"I have paid for N packs; here is the reference." Lands as a pending
    payment_claims row with product='airlock' that the founder approves
    from the same review queue as subscription claims; approval is what
    grants the credits (founder.py), never this call."""
    price, amount, scan_credits = _quote(settings, payload.currency, payload.packs)
    return await _insert_claim(
        database,
        settings,
        user,
        price.method,
        payload.currency,
        amount,
        payload.reference,
        product="airlock",
        scan_credits=scan_credits,
    )


@router.get("/credits/claims", response_model=list[ClaimOut])
async def my_pack_claims(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> list[ClaimOut]:
    rows = await database.fetch_all(
        f"""SELECT {_CLAIM_COLUMNS}
           FROM payment_claims WHERE user_id=%s AND product='airlock' ORDER BY created_at DESC""",
        (user.id,),
    )
    return [ClaimOut(**row) for row in rows]


class PackEmailDetailsIn(BaseModel):
    currency: Currency
    packs: int = Field(default=1, ge=1)


class EmailDetailsOut(BaseModel):
    sent: bool


@router.post("/credits/email-details", response_model=EmailDetailsOut)
async def email_pack_details(
    payload: PackEmailDetailsIn,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> EmailDetailsOut:
    """Sends the real payee details for a pack to the caller's own
    registered address -- the same self-serve shape, and the same
    per-account limit, as billing.py's email_upi_details. The account
    details themselves stay founder-only everywhere in the API."""
    price, amount, scan_credits = _quote(settings, payload.currency, payload.packs)
    allowed = await try_record_action(
        database, user.id, "airlock_details_email", MAX_PAYMENT_DETAILS_EMAILS_PER_WINDOW, PAYMENT_DETAILS_EMAIL_WINDOW_MS
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    if price.method == "upi":
        lines = [("UPI ID", settings.founder_upi_id), ("Payee name", settings.founder_upi_payee_name)]
        upi_link: str | None = build_upi_payment_link(settings.founder_upi_id, settings.founder_upi_payee_name, amount)
    else:
        wire = next(d for d in _wire_currency_details(settings) if d.currency == payload.currency)
        lines = [
            ("Beneficiary", settings.founder_bank_account_name),
            ("Account number", settings.founder_bank_account_number),
            ("Bank", settings.founder_bank_name),
            ("SWIFT", settings.founder_bank_swift_code),
            ("Correspondent bank", wire.correspondent_bank),
            ("Correspondent SWIFT", wire.correspondent_swift),
            ("Nostro account", wire.nostro_account),
            ("ABA" if payload.currency == "USD" else "IBAN", wire.routing_reference),
        ]
        upi_link = None
    try:
        await run_in_threadpool(
            send_airlock_payment_details_email,
            settings,
            user.email,
            secrets.token_hex(8),
            method=price.method,
            currency=payload.currency,
            amount=amount,
            scan_credits=scan_credits,
            lines=lines,
            upi_link=upi_link,
        )
    except EmailNotConfiguredError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email is not configured") from error
    except Exception as error:
        logger.warning("airlock_payment_details_email_failed", extra={"user_id": user.id}, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send the email right now. Try again, or email the founder directly.",
        ) from error
    return EmailDetailsOut(sent=True)
