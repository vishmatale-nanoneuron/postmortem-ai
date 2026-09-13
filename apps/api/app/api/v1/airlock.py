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

import csv
import hashlib
import io
import logging
import secrets
import time
from datetime import UTC, datetime
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, Security, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from ...ai.model_router import create_model_provider
from ...ai.provider import ModelProvider
from ...airlock import Detector, check_egress, sanitize
from ...airlock.proxy import (
    MAX_PROXY_SCAN_CHARS,
    MAX_RETURNED_CHARS,
    PROXY_FETCH_CREDITS,
    Fetched,
    ProxyRefused,
    fetch_url,
    prepare_for_scan,
    visible_text,
)
from ...airlock.rules import RULES, RULES_BY_ID
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
    handle_ledger_lines_query,
    handle_ledger_query,
    handle_revoke_api_key,
    handle_usage_query,
    resolve_api_key,
)
from ...cqrs.airlock_policy import (
    DEFAULT_BLOCK_THRESHOLD,
    DEFAULT_FLAG_THRESHOLD,
    DEFAULT_POLICY,
    MAX_ALLOWLIST_HOSTS,
    MAX_MUTED_RULES,
    InvalidPolicy,
    Policy,
    SetPolicyCommand,
    handle_policy_query,
    handle_reset_policy,
    handle_set_policy,
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
    AIRLOCK_SCAN_WINDOW_MS,
    client_ip,
    try_record_action,
    try_record_airlock_scan_attempt,
    try_record_airlock_waitlist_attempt,
)
from ...services.email import (
    EmailNotConfiguredError,
    build_upi_payment_link,
    send_airlock_balance_email,
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

# Fail closed. The page tells integrators to treat any non-200 as a block;
# the 500 body says so itself, so a client that parses the body before the
# status (they exist) still reads "block". main.py's unhandled-exception
# handler consults this set. Nothing else about the 500 changes.
FAIL_CLOSED_PATHS = frozenset({"/v1/airlock/scan", "/v1/airlock/egress", "/v1/airlock/proxy/fetch"})

# Declared, not just parsed: these put the key in the OpenAPI document as a
# real security scheme, so /docs gets an Authorize button and a generated
# client knows where the key goes. auto_error=False because the route,
# not the scheme, decides between 401 (no key, no session) and 429.
_api_key_header = APIKeyHeader(name=KEY_HEADER, auto_error=False, description="Your Airlock API key (alk_...).")
_bearer = HTTPBearer(auto_error=False, description="The same key as a Bearer token.")

# The responses every metered route can produce, documented once.
METERED_RESPONSES = {
    401: {"description": "No API key or session, or an invalid/revoked key. Nothing was scanned or charged."},
    402: {"description": "The account has no credits left. Nothing was scanned or charged; buy a pack."},
    422: {"description": "The request body failed validation (empty or oversized content). Nothing was charged."},
    429: {"description": "Too many unauthenticated requests from this address. Resets within the hour."},
}

NO_CREDITS_DETAIL = "No Airlock credits left. Buy a pack from the Airlock section of your dashboard."

# The reads that take a key but spend no credit (policy, usage, the CSV)
# are bounded per account instead, so "the balance is the bound" stays
# true for everything a key can do: a drained key can neither run the
# engine nor pull a 50,000-row export in a loop. Generous enough for a
# dashboard tab polling once a minute.
MAX_READS_PER_WINDOW = 600
MAX_EXPORTS_PER_WINDOW = 60
READ_WINDOW_MS = AIRLOCK_SCAN_WINDOW_MS


async def _bound_reads(database: Database, principal: "AirlockPrincipal", action: str, cap: int) -> None:
    if principal.is_founder:
        return
    if not await try_record_action(database, principal.user_id, action, cap, READ_WINDOW_MS):
        raise _rate_limited()


def _rate_limited() -> HTTPException:
    """429 with Retry-After (RFC 9110 §10.2.3): the per-IP window is an hour,
    and a well-behaved client backs off for exactly that rather than
    guessing. The value is the window, not the precise remaining time,
    which would cost a query to compute and reveals nothing useful."""
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=RATE_LIMITED_DETAIL,
        headers={"Retry-After": str(AIRLOCK_SCAN_WINDOW_MS // 1000)},
    )


# Balance emails. Stateless on purpose: an email goes out on exactly the
# call that crosses a threshold (the balance was at or above it before the
# charge and below it after), so each crossing notifies once with no
# "already notified" column to keep in sync. Two thresholds: running low,
# and empty.
LOW_BALANCE_THRESHOLD = 1_000


async def _notify_balance_crossings(
    database: Database, settings: Settings, principal: "AirlockPrincipal", remaining: int | None, charged: int
) -> None:
    if remaining is None or charged <= 0:
        return
    before = remaining + charged
    crossed_low = before >= LOW_BALANCE_THRESHOLD > remaining
    crossed_empty = remaining == 0
    if not (crossed_low or crossed_empty):
        return
    row = await database.fetch_one("SELECT email FROM users WHERE id=%s", (principal.user_id,))
    if not row:
        return
    try:
        await run_in_threadpool(
            send_airlock_balance_email, settings, str(row["email"]), remaining, empty=crossed_empty
        )
    except EmailNotConfiguredError:
        logger.info("airlock_balance_email_skipped", extra={"reason": "email_not_configured"})
    except Exception:
        logger.warning("airlock_balance_email_failed", extra={"user_id": principal.user_id}, exc_info=True)
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
    # The account's thresholds, muted rules and standing allowlist. Comes
    # with the key lookup for the API; one extra read for the playground.
    policy: Policy = DEFAULT_POLICY


async def airlock_principal(
    request: Request,
    header_key: str | None = Security(_api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> AirlockPrincipal:
    secret = (header_key or "").strip() or (bearer.credentials.strip() if bearer else "")
    if secret:
        resolved = await resolve_api_key(database, secret)
        if resolved is not None:
            return AirlockPrincipal(
                user_id=resolved.user_id, api_key_id=resolved.id, is_founder=False, policy=resolved.policy
            )
        # An invalid key is counted against the IP and, past the cap, refused
        # with a 429 before the database is asked again. A 256-bit key cannot
        # be guessed, so this is not about brute force; it is about a
        # misconfigured or malicious client not being able to turn every
        # wrong key into a hash lookup for the whole hour.
        if not await try_record_airlock_scan_attempt(database, client_ip(request)):
            raise _rate_limited()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked Airlock key")

    user = await _resolve_user_from_cookie(request, database, settings)
    if user is not None:
        policy = await handle_policy_query(database, user.id)
        return AirlockPrincipal(user_id=user.id, api_key_id=None, is_founder=user.is_founder, policy=policy)

    if not await try_record_airlock_scan_attempt(database, client_ip(request)):
        raise _rate_limited()
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


Fetcher = Callable[[str], Awaitable[Fetched]]


def get_fetcher() -> Fetcher:
    """The proxy's URL fetcher (airlock/proxy.fetch_url) as a dependency, so
    tests can hand the route one bound to a mock transport and a fake
    resolver and still exercise every rule the real one enforces."""
    return fetch_url


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
    # Also return the content with hidden characters, hidden HTML and the
    # highest-weight matches removed (airlock/detector.sanitize) -- for a
    # pipeline that would rather pass on a defanged document than drop it.
    # No extra charge; off by default so an ordinary verdict is not twice
    # the size of the content it judged.
    sanitize: bool = False


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
    # weight it contributed; status "unavailable" with weight 0 when the
    # model could not be asked; status "skipped" when the rules already
    # blocked and the model could not have changed the verdict.
    semantic: dict | None = None
    # The content after airlock/detector.sanitize, when `sanitize` was
    # requested. None otherwise.
    sanitized: str | None = None
    # The thresholds this verdict was judged against and the rules that were
    # not consulted -- the account's policy (PUT /policy), so a verdict can
    # be explained without a second call.
    policy: dict = Field(default_factory=dict)


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
    # False when no allowlist was supplied on the call OR in the account's
    # policy, in which case ANY destination passes and only the payload was
    # examined. Returned explicitly because the alternative is a caller
    # believing they have a destination control they never configured --
    # the failure mode of a security default that is silently permissive.
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


@router.post("/scan", response_model=ScanOut, responses=METERED_RESPONSES)
async def scan(
    payload: ScanIn,
    database: Database = Depends(get_database),
    principal: AirlockPrincipal = Depends(airlock_principal),
    model_provider: Callable[[], ModelProvider] = Depends(get_model_provider),
    settings: Settings = Depends(get_settings),
) -> ScanOut:
    """Score untrusted content for prompt injection, before it reaches an
    agent's context window. One credit per call (five with `deep`; when the
    rules alone already block, the model is not asked and four are refunded,
    so the net is one); 402 with nothing scanned when the balance is short.
    Any 5xx from the application carries `verdict: "block"`: fail closed."""
    policy = principal.policy
    # Charge before scanning, not after: a caller with no credits gets the
    # 402 without the engine running for them (the balance is the bound on
    # what an authenticated key can make the engine do), and a caller with
    # credits is charged for exactly the calls that return a verdict. A
    # deep scan is taken as one debit for the whole price, so a caller
    # either affords the second opinion or is told so up front.
    cost = 1 + DEEP_SCAN_EXTRA_CREDITS if payload.deep else 1
    remaining = await _charge(database, principal, "deep_scan" if payload.deep else "scan", cost)
    charged = 0 if principal.is_founder else cost

    started = time.perf_counter()
    detection = _DETECTOR.scan(
        payload.content,
        block_threshold=policy.block_threshold,
        flag_threshold=policy.flag_threshold,
        muted=policy.muted_rules,
    )
    verdict, score = detection.verdict, detection.score

    # A deep scan is only worth its price when the model can move the
    # verdict. It can only raise one (semantic.combine), so once the rules
    # already say block there is nothing for it to do: skip the call, hand
    # the extra credits back on the same refund path an unavailable model
    # uses, and say so. The other direction is deliberately NOT bounded --
    # the paraphrased attack that scores 0.00 on rules is the case the
    # second opinion exists for.
    ask_model = payload.deep and verdict != "block"

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

    if payload.deep and not ask_model:
        semantic = {
            "status": "skipped",
            "reason": "The rules already block this content; a second opinion can only raise a verdict.",
            "weight": 0.0,
        }
        if not principal.is_founder:
            remaining = await handle_grant_credits(
                database,
                GrantCreditsCommand(
                    user_id=principal.user_id,
                    credits=DEEP_SCAN_EXTRA_CREDITS,
                    reason="refund",
                    reference="deep scan: rules already block",
                ),
            )
            charged = 1
    elif ask_model:
        opinion = await semantic_opinion(model_provider, payload.content)
        semantic = opinion.as_dict()
        if opinion.status == "ok":
            score, verdict = combine(detection.score, opinion, policy.block_threshold, policy.flag_threshold)
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
    sanitized = sanitize(payload.content, detection) if payload.sanitize else None
    latency_ms = int((time.perf_counter() - started) * 1000)

    await _notify_balance_crossings(database, settings, principal, remaining, charged)
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
        sanitized=sanitized,
        policy=_policy_summary(policy),
    )


def _policy_summary(policy: Policy) -> dict:
    return {
        "block_threshold": policy.block_threshold,
        "flag_threshold": policy.flag_threshold,
        "muted_rules": list(policy.muted_rules),
        "default": policy.is_default,
    }


@router.post("/egress", response_model=EgressOut, responses=METERED_RESPONSES)
async def egress(
    payload: EgressIn,
    database: Database = Depends(get_database),
    principal: AirlockPrincipal = Depends(airlock_principal),
    settings: Settings = Depends(get_settings),
) -> EgressOut:
    """Check an outbound call for credentials and personal data, and its
    destination against an allowlist, before the agent sends it. One
    credit per call."""
    remaining = await _charge(database, principal, "egress")
    await _notify_balance_crossings(database, settings, principal, remaining, 0 if principal.is_founder else 1)
    started = time.perf_counter()
    # The standing allowlist from the account's policy plus whatever the
    # call names. A union, never a replacement: a per-call list can widen
    # what the policy allows for one call, and cannot silently drop the
    # policy's entries.
    allowlist = list(dict.fromkeys([*principal.policy.egress_allowlist, *payload.allowlist]))
    verdict = check_egress(
        payload=payload.payload,
        destination=payload.destination,
        allowlist=allowlist,
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
        destination_checked=bool(allowlist),
        redacted=verdict.redacted,
        credits_remaining=remaining,
        credits_charged=0 if principal.is_founder else 1,
    )


# ---------------------------------------------------------------------------
# Proxy fetch: both directions in one call. Airlock checks the URL as an
# outbound destination (allowlist, credential material in the URL), fetches
# it under the SSRF rules in airlock/proxy.py, scans what came back under
# the account's policy, and returns the page text only when the verdict
# allows it. The agent never fetches the page itself, so the check cannot
# be skipped.
# ---------------------------------------------------------------------------


class ProxyFetchIn(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    # Merged with the policy's standing allowlist, like an egress call. With
    # neither, any public host is fetched and `destination_checked` is false.
    allowlist: list[str] = Field(default_factory=list, max_length=100)
    deep: bool = False
    # False to get the verdict only (cheaper on the wire, same price).
    return_content: bool = True


class ProxyFetchOut(BaseModel):
    verdict: str
    score: float
    # Which check decided: "egress" when the URL itself was refused before
    # any fetch (not on the allowlist, or carrying credential material);
    # "ingress" when the fetched content was scanned.
    stage: str
    reasons: list[str]
    matches: list[MatchOut]
    families: list[str]
    signals: dict
    url: str
    final_url: str | None
    http_status: int | None
    content_type: str | None
    content_bytes: int
    content_sha256: str | None
    destination_checked: bool
    hops: int
    truncated: bool
    fetch_ms: int
    latency_ms: int
    # The page's visible text when the verdict allows it: as fetched on
    # allow, sanitized on flag, absent on block. Capped at MAX_RETURNED_CHARS.
    content: str | None
    credits_remaining: int | None
    credits_charged: int
    semantic: dict | None = None
    policy: dict = Field(default_factory=dict)


PROXY_RESPONSES = {
    **METERED_RESPONSES,
    422: {
        "description": "The URL will never be fetched: not http(s), a private/loopback/link-local/reserved "
        "address (before or after redirects), too many redirects, or a non-text content type. Refunded."
    },
    502: {"description": "A public URL that could not be reached this time (DNS, connect, timeout). Refunded."},
}


async def _refund_all(database: Database, principal: AirlockPrincipal, credits: int, why: str) -> None:
    if principal.is_founder or credits <= 0:
        return
    await handle_grant_credits(
        database,
        GrantCreditsCommand(user_id=principal.user_id, credits=credits, reason="refund", reference=why),
    )


@router.post("/proxy/fetch", response_model=ProxyFetchOut, responses=PROXY_RESPONSES)
async def proxy_fetch(
    payload: ProxyFetchIn,
    database: Database = Depends(get_database),
    principal: AirlockPrincipal = Depends(airlock_principal),
    fetcher: Fetcher = Depends(get_fetcher),
    model_provider: Callable[[], ModelProvider] = Depends(get_model_provider),
    settings: Settings = Depends(get_settings),
) -> ProxyFetchOut | JSONResponse:
    """Fetch a URL on the agent's behalf and scan it before the agent sees
    it. Two credits (the fetch and the scan; plus four with `deep`, refunded
    when the rules already block). The URL is checked as an outbound call
    first; the fetch refuses anything that is not the public internet,
    re-checking every redirect; a fetch that cannot be made is refunded
    and answered with `verdict: block`."""
    policy = principal.policy
    cost = PROXY_FETCH_CREDITS + (DEEP_SCAN_EXTRA_CREDITS if payload.deep else 0)
    remaining = await _charge(database, principal, "deep_scan" if payload.deep else "scan", cost)
    charged = 0 if principal.is_founder else cost
    started = time.perf_counter()

    # Outbound first: is this somewhere the agent may reach, and is the URL
    # itself carrying something out (a key in the query string)?
    allowlist = list(dict.fromkeys([*policy.egress_allowlist, *payload.allowlist]))
    outbound = check_egress(payload=payload.url, destination=payload.url, allowlist=allowlist, redact=False)
    if outbound.verdict == "block":
        if payload.deep:
            remaining = await _refund_or_keep(database, principal, remaining, DEEP_SCAN_EXTRA_CREDITS, "proxy fetch: refused outbound")
            charged = 0 if principal.is_founder else PROXY_FETCH_CREDITS
        latency_ms = int((time.perf_counter() - started) * 1000)
        await _notify_balance_crossings(database, settings, principal, remaining, charged)
        await handle_record_scan(
            database,
            RecordScanCommand(
                kind="egress",
                verdict="block",
                score=outbound.score,
                content_sha256=hashlib.sha256(payload.url.encode()).hexdigest(),
                content_bytes=len(payload.url.encode()),
                matched_rules=list(outbound.secrets_found),
                source=f"proxy:{outbound.destination or ''}"[:64],
                latency_ms=latency_ms,
            ),
        )
        return ProxyFetchOut(
            verdict="block",
            score=round(outbound.score, 4),
            stage="egress",
            reasons=list(outbound.reasons),
            matches=[],
            families=[],
            signals={},
            url=payload.url,
            final_url=None,
            http_status=None,
            content_type=None,
            content_bytes=0,
            content_sha256=None,
            destination_checked=bool(allowlist),
            hops=0,
            truncated=False,
            fetch_ms=0,
            latency_ms=latency_ms,
            content=None,
            credits_remaining=remaining,
            credits_charged=charged,
            policy=_policy_summary(policy),
        )

    try:
        fetched = await fetcher(payload.url)
    except ProxyRefused as refused:
        # Nothing was scanned, so nothing is owed. The body still says
        # block: an agent that cannot get the page through Airlock must not
        # go and get it some other way.
        await _refund_all(database, principal, cost, f"proxy fetch: {refused.detail[:120]}")
        logger.info("airlock_proxy_refused", extra={"status": refused.status_code, "detail": refused.detail})
        return JSONResponse(
            status_code=refused.status_code,
            content={"detail": refused.detail, "verdict": "block", "stage": "fetch", "credits_charged": 0},
        )

    scan_text = prepare_for_scan(fetched.text, fetched.content_type)
    detection = _DETECTOR.scan(
        scan_text,
        block_threshold=policy.block_threshold,
        flag_threshold=policy.flag_threshold,
        muted=policy.muted_rules,
    )
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
    reasons = list(outbound.reasons)

    ask_model = payload.deep and verdict != "block"
    if payload.deep and not ask_model:
        semantic = {
            "status": "skipped",
            "reason": "The rules already block this content; a second opinion can only raise a verdict.",
            "weight": 0.0,
        }
        remaining = await _refund_or_keep(database, principal, remaining, DEEP_SCAN_EXTRA_CREDITS, "deep scan: rules already block")
        charged = 0 if principal.is_founder else PROXY_FETCH_CREDITS
    elif ask_model:
        opinion = await semantic_opinion(model_provider, scan_text)
        semantic = opinion.as_dict()
        if opinion.status == "ok":
            score, verdict = combine(detection.score, opinion, policy.block_threshold, policy.flag_threshold)
            if opinion.weight > 0:
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
        else:
            remaining = await _refund_or_keep(database, principal, remaining, DEEP_SCAN_EXTRA_CREDITS, "deep scan: second opinion unavailable")
            charged = 0 if principal.is_founder else PROXY_FETCH_CREDITS

    if verdict == "block" or not payload.return_content:
        content: str | None = None
    elif verdict == "flag":
        content = visible_text(sanitize(scan_text, detection), fetched.content_type)
    else:
        content = visible_text(scan_text, fetched.content_type)
    latency_ms = int((time.perf_counter() - started) * 1000)

    await _notify_balance_crossings(database, settings, principal, remaining, charged)
    await handle_record_scan(
        database,
        RecordScanCommand(
            kind="ingress",
            verdict=verdict,
            score=score,
            content_sha256=detection.content_sha256,
            content_bytes=fetched.content_bytes,
            matched_rules=matched_rules,
            source=f"proxy:{outbound.destination or ''}"[:64],
            latency_ms=latency_ms,
        ),
    )
    return ProxyFetchOut(
        verdict=verdict,
        score=round(score, 4),
        stage="ingress",
        reasons=reasons,
        matches=matches,
        families=families,
        signals={key: value for key, value in (detection.signals or {}).items()},
        url=fetched.url,
        final_url=fetched.final_url,
        http_status=fetched.http_status,
        content_type=fetched.content_type,
        content_bytes=fetched.content_bytes,
        content_sha256=detection.content_sha256,
        destination_checked=bool(allowlist),
        hops=fetched.hops,
        # True when any cap cut something the agent might have wanted: the
        # body read, what the scanner saw, or what is handed back.
        truncated=fetched.truncated
        or len(fetched.text) > MAX_PROXY_SCAN_CHARS
        or (content is not None and len(content) >= MAX_RETURNED_CHARS),
        fetch_ms=fetched.fetch_ms,
        latency_ms=latency_ms,
        content=content,
        credits_remaining=remaining,
        credits_charged=charged,
        semantic=semantic,
        policy=_policy_summary(policy),
    )


async def _refund_or_keep(
    database: Database, principal: AirlockPrincipal, remaining: int | None, credits: int, why: str
) -> int | None:
    """Refunds `credits` for a metered principal and returns the new
    balance; the founder was never charged, so nothing moves."""
    if principal.is_founder:
        return remaining
    return await handle_grant_credits(
        database,
        GrantCreditsCommand(user_id=principal.user_id, credits=credits, reason="refund", reference=why),
    )


class ScanStatsOut(BaseModel):
    total: int
    blocked: int
    flagged: int
    allowed: int
    last_7d: int
    top_rules: list[dict]


@router.get("/stats", response_model=ScanStatsOut)
async def stats(response: Response, database: Database = Depends(get_database)) -> ScanStatsOut:
    """Public, and aggregate-only by construction (see cqrs/airlock_scan.py).
    Published rather than kept private: a scanner that tells you how often
    it fires, and which rules do the work, is easier to trust than one that
    asks you to take its accuracy on faith."""
    # Two aggregate queries over an append-only table; a minute of shared
    # caching at the edge is invisible to a reader and spares the database
    # a crawler hitting the page every few seconds.
    response.headers["Cache-Control"] = "public, max-age=60, s-maxage=60"
    counts = await handle_scan_stats_query(database)
    return ScanStatsOut(**vars(counts))


# ---------------------------------------------------------------------------
# Rules. Public: the ids, families, weights and descriptions are the
# vocabulary every verdict is written in, and a customer muting a rule
# from the dashboard needs the list to choose from. The patterns
# themselves are not served -- they are the engine, not the contract.
# ---------------------------------------------------------------------------


class RuleOut(BaseModel):
    id: str
    family: str
    weight: float
    description: str


class RulesOut(BaseModel):
    count: int
    families: list[str]
    rules: list[RuleOut]


@router.get("/rules", response_model=RulesOut)
async def list_rules(response: Response) -> RulesOut:
    """Every rule the scanner runs, in the order it runs them. Changes only
    with a deploy, so cached like /pricing."""
    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=300"
    return RulesOut(
        count=len(RULES),
        families=sorted({rule.family for rule in RULES}),
        rules=[RuleOut(id=r.id, family=r.family, weight=r.weight, description=r.description) for r in RULES],
    )


# ---------------------------------------------------------------------------
# Policy. Readable with a key (an SDK can show what it is running under);
# writable only from a signed-in session, like keys: a leaked key must not
# be able to raise the block threshold to 1.0 and switch the guard off.
# ---------------------------------------------------------------------------


class PolicyIn(BaseModel):
    block_threshold: float = Field(default=DEFAULT_BLOCK_THRESHOLD, gt=0, le=1)
    flag_threshold: float = Field(default=DEFAULT_FLAG_THRESHOLD, gt=0, le=1)
    muted_rules: list[str] = Field(default_factory=list, max_length=MAX_MUTED_RULES)
    egress_allowlist: list[str] = Field(default_factory=list, max_length=MAX_ALLOWLIST_HOSTS)


class PolicyOut(PolicyIn):
    # True while the account has never saved a policy (the defaults apply).
    default: bool
    updated_at: int | None


def _policy_out(policy: Policy) -> PolicyOut:
    return PolicyOut(
        block_threshold=policy.block_threshold,
        flag_threshold=policy.flag_threshold,
        muted_rules=list(policy.muted_rules),
        egress_allowlist=list(policy.egress_allowlist),
        default=policy.is_default,
        updated_at=policy.updated_at,
    )


READ_RESPONSES = {
    401: METERED_RESPONSES[401],
    429: {"description": f"More than {MAX_READS_PER_WINDOW} reads from this account in an hour. Not metered otherwise."},
}


@router.get("/policy", response_model=PolicyOut, responses=READ_RESPONSES)
async def get_policy(
    database: Database = Depends(get_database), principal: AirlockPrincipal = Depends(airlock_principal)
) -> PolicyOut:
    """The policy every scan and egress call on this account is judged
    under. Not metered; bounded per account."""
    await _bound_reads(database, principal, "airlock_read", MAX_READS_PER_WINDOW)
    return _policy_out(principal.policy)


@router.put("/policy", response_model=PolicyOut)
async def put_policy(
    payload: PolicyIn,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> PolicyOut:
    """Replaces the whole policy. Rule ids must exist (GET /rules);
    allowlist entries must be hostnames or host suffixes; flag_threshold
    cannot exceed block_threshold. Takes effect on the next call."""
    try:
        policy = await handle_set_policy(
            database,
            SetPolicyCommand(
                user_id=user.id,
                block_threshold=payload.block_threshold,
                flag_threshold=payload.flag_threshold,
                muted_rules=payload.muted_rules,
                egress_allowlist=payload.egress_allowlist,
            ),
        )
    except InvalidPolicy as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from None
    return _policy_out(policy)


@router.delete("/policy", response_model=PolicyOut)
async def reset_policy(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> PolicyOut:
    """Back to the defaults."""
    return _policy_out(await handle_reset_policy(database, user.id))


# ---------------------------------------------------------------------------
# Usage. The customer's own ledger, by day and by key, and as CSV. This is
# attributed data (it is theirs, and erased with the account), which is
# why it comes from the ledger and not from the audit log: the audit log
# holds no account column on purpose, so it can stay append-only while
# deletion stays an erasure.
# ---------------------------------------------------------------------------

MAX_USAGE_DAYS = 366
MAX_EXPORT_ROWS = 50_000


class UsageDayOut(BaseModel):
    day: str  # YYYY-MM-DD, UTC
    key_prefix: str | None
    scans: int
    deep_scans: int
    egress: int
    refunds: int
    # Net credits spent that day on that key (positive number).
    credits: int


class UsageOut(BaseModel):
    days: int
    total_credits: int
    rows: list[UsageDayOut]


@router.get("/usage", response_model=UsageOut, responses=READ_RESPONSES)
async def usage(
    days: int = Query(default=30, ge=1, le=MAX_USAGE_DAYS),
    database: Database = Depends(get_database),
    principal: AirlockPrincipal = Depends(airlock_principal),
) -> UsageOut:
    """Calls per day per key over the last `days` days. Not metered;
    bounded per account."""
    await _bound_reads(database, principal, "airlock_read", MAX_READS_PER_WINDOW)
    rows = await handle_usage_query(database, principal.user_id, days=days)
    out = [UsageDayOut(**vars(row)) for row in rows]
    return UsageOut(days=days, total_credits=sum(row.credits for row in out), rows=out)


@router.get(
    "/usage.csv",
    responses={
        200: {"content": {"text/csv": {}}, "description": "One ledger line per row, newest first."},
        401: METERED_RESPONSES[401],
        429: {"description": f"More than {MAX_EXPORTS_PER_WINDOW} exports from this account in an hour."},
    },
)
async def usage_csv(
    days: int = Query(default=90, ge=1, le=MAX_USAGE_DAYS),
    database: Database = Depends(get_database),
    principal: AirlockPrincipal = Depends(airlock_principal),
) -> StreamingResponse:
    """Every ledger line (purchases, grants, each metered call, refunds)
    for the last `days` days as CSV -- for a spreadsheet, or an auditor.
    Capped at MAX_EXPORT_ROWS lines (narrow the window for more) and at
    MAX_EXPORTS_PER_WINDOW pulls an hour."""
    await _bound_reads(database, principal, "airlock_export", MAX_EXPORTS_PER_WINDOW)
    lines = await handle_ledger_lines_query(database, principal.user_id, days=days, limit=MAX_EXPORT_ROWS)

    def rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["timestamp_utc", "reason", "delta", "key_prefix", "reference"])
        yield buffer.getvalue()
        for line in lines:
            buffer.seek(0)
            buffer.truncate()
            stamp = datetime.fromtimestamp(line.created_at / 1000, tz=UTC).isoformat(timespec="seconds")
            writer.writerow([stamp, line.reason, line.delta, line.key_prefix or "", line.reference or ""])
            yield buffer.getvalue()

    today = datetime.now(tz=UTC).date().isoformat()
    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="airlock-usage-{today}.csv"'},
    )


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
    # A proxy fetch is the fetch plus the scan.
    credits_per_proxy_fetch: int = PROXY_FETCH_CREDITS
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
async def pricing(response: Response, settings: Settings = Depends(get_settings)) -> PricingOut:
    # Changes only with a deploy or an env var; safe to cache briefly.
    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=300"
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
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=RATE_LIMITED_DETAIL,
            headers={"Retry-After": str(PAYMENT_DETAILS_EMAIL_WINDOW_MS // 1000)},
        )

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
