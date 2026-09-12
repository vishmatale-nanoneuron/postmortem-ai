"""Airlock: the scanner, and the early-access list.

Airlock is a guard that sits between an agent and untrusted content. Two
directions, two endpoints:

- POST /scan scores inbound text for prompt injection before it reaches a
  model's context window.
- POST /egress checks an outbound call's destination and payload for
  credentials and personal data before it leaves.

Both are free and unauthenticated, bounded per IP. That is a deliberate
go-to-market choice as much as a technical one: this product's compounding
asset is its attack corpus, and the fastest way to grow one is to let
people scan their own content. Every decision is recorded in an append-only
table (migration 0031) that holds a hash and a byte count, never the
content.

The waitlist endpoint below is for the hosted, metered version that does
not exist yet. It is shaped like the password-reset endpoint in `auth.py`
for the same reason: it answers 202 whether the address was new or already
on the list, so the response can never be used to learn who signed up.
"""

import hashlib
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from ...airlock import Detector, check_egress
from ...airlock.rules import RULES_BY_ID
from ...auth import User, current_founder
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
    try_record_airlock_scan_attempt,
    try_record_airlock_waitlist_attempt,
)

# Built once at import, not per request: compiling 30 regexes on every call
# would dominate the latency the endpoint reports. Stateless, so sharing it
# across concurrent requests is safe.
_DETECTOR = Detector()

router = APIRouter(prefix="/v1/airlock", tags=["airlock"])


class WaitlistIn(BaseModel):
    email: EmailStr
    # Both optional: a bare address is a real signal and demanding a company
    # name to express interest costs more signups than the field is worth.
    company: str | None = Field(default=None, max_length=200)
    use_case: str | None = Field(default=None, max_length=2000)


class WaitlistOut(BaseModel):
    status: str


class ScanStatsOut(BaseModel):
    total: int
    blocked: int
    flagged: int
    allowed: int
    last_7d: int
    top_rules: list[dict]


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
    readable anywhere else -- there is no Airlock dashboard yet."""
    entries = await handle_waitlist_query(database, WaitlistQuery())
    return [WaitlistEntryOut(**vars(entry)) for entry in entries]


# ---------------------------------------------------------------------------
# The scanner itself. Free and unauthenticated on purpose: the product's
# compounding asset is the attack corpus, and nothing seeds a corpus like
# letting people point it at their own content. The bound is per-IP and
# about protecting the function, not about metering.
# ---------------------------------------------------------------------------

# Bounds the CPU one request can spend in 30 regexes. Far above any real
# document someone pastes to evaluate the product.
MAX_SCAN_CHARS = 50_000
MAX_EGRESS_PAYLOAD_CHARS = 20_000


class ScanIn(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_SCAN_CHARS)
    # Free-form label for where the content came from ("support_ticket",
    # "web"). Recorded on the audit row; never interpreted.
    source: str | None = Field(default=None, max_length=64)


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
    # The payload with credential material replaced. Returned so a caller
    # can see exactly what would have been safe to send.
    redacted: str


@router.post("/scan", response_model=ScanOut)
async def scan(payload: ScanIn, request: Request, database: Database = Depends(get_database)) -> ScanOut:
    """Score untrusted content for prompt injection, before it reaches an
    agent's context window."""
    if not await try_record_airlock_scan_attempt(database, client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many scans from this address. Try again later.",
        )
    started = time.perf_counter()
    detection = _DETECTOR.scan(payload.content)
    latency_ms = int((time.perf_counter() - started) * 1000)

    await handle_record_scan(
        database,
        RecordScanCommand(
            kind="ingress",
            verdict=detection.verdict,
            score=detection.score,
            content_sha256=detection.content_sha256,
            content_bytes=detection.content_bytes,
            matched_rules=[match.rule_id for match in detection.matches],
            source=payload.source,
            latency_ms=latency_ms,
            # No excerpt: see RecordScanCommand.excerpt and 0031's header.
        ),
    )
    return ScanOut(
        verdict=detection.verdict,
        score=round(detection.score, 4),
        matches=[
            MatchOut(
                rule_id=match.rule_id,
                family=match.family,
                weight=match.weight,
                description=RULES_BY_ID[match.rule_id].description if match.rule_id in RULES_BY_ID else "",
            )
            for match in detection.matches
        ],
        families=list(detection.families),
        # Signal *names* and what was found, which is the explanatory half.
        signals={key: value for key, value in (detection.signals or {}).items()},
        content_sha256=detection.content_sha256,
        content_bytes=detection.content_bytes,
        latency_ms=latency_ms,
    )


@router.post("/egress", response_model=EgressOut)
async def egress(payload: EgressIn, request: Request, database: Database = Depends(get_database)) -> EgressOut:
    """Check an outbound call for credentials and personal data, and its
    destination against an allowlist, before the agent sends it."""
    if not await try_record_airlock_scan_attempt(database, client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many scans from this address. Try again later.",
        )
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
        redacted=verdict.redacted,
    )


@router.get("/stats", response_model=ScanStatsOut)
async def stats(database: Database = Depends(get_database)) -> ScanStatsOut:
    """Public, and aggregate-only by construction (see cqrs/airlock_scan.py).
    Published rather than kept private: a scanner that tells you how often
    it fires, and which rules do the work, is easier to trust than one that
    asks you to take its accuracy on faith."""
    counts = await handle_scan_stats_query(database)
    return ScanStatsOut(**vars(counts))
