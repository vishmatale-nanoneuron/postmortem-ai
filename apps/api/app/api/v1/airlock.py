"""Airlock's early-access list.

Airlock is the second product: a guard that sits between an agent and
untrusted content, scoring text for prompt injection before it enters the
context window and scanning outbound calls for credentials and PII before
they leave. Its code exists and its detector runs; it is not hosted, has no
metering and no checkout. Nothing here scans anything -- that would be
advertising an endpoint that does not exist. This router does the one thing
the product can honestly do today: record who wants it.

The endpoint is deliberately shaped like the password-reset one
(`auth.py`), for the same reason: it answers 202 whether the address was
new, already on the list, or invalid-but-well-formed, so the response can
never be used to learn who has signed up.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from ...auth import User, current_founder
from ...cqrs.airlock_waitlist import (
    JoinWaitlistCommand,
    WaitlistQuery,
    handle_join_waitlist,
    handle_waitlist_query,
)
from ...database import Database
from ...dependencies import get_database
from ...security.rate_limit import client_ip, try_record_airlock_waitlist_attempt

router = APIRouter(prefix="/v1/airlock", tags=["airlock"])


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
    readable anywhere else -- there is no Airlock dashboard yet."""
    entries = await handle_waitlist_query(database, WaitlistQuery())
    return [WaitlistEntryOut(**vars(entry)) for entry in entries]
