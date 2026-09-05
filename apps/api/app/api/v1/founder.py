import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...auth import User, current_founder
from ...cqrs.activity import ActivityLogFilter, handle_activity_log_query
from ...database import Database
from ...dependencies import get_database
from ...services.billing import activate_manual_subscription, record_claim_event
from ...settings import Settings, get_settings

router = APIRouter(prefix="/v1/founder", tags=["founder"])


@router.get("/summary")
async def founder_summary(
    database: Database = Depends(get_database),
    _founder: User = Depends(current_founder),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Platform-wide aggregates -- unlike /v1/postmortems/summary (scoped to
    one client's own email), this is founder-only precisely because it
    spans every account. Founder authorization is independent of any
    client/subscription state, per the same invariant as
    nanoneuron-software-company."""
    user_counts = await database.fetch_one("SELECT count(*) AS total FROM users")
    # A real revenue/conversion funnel, not just activity counts -- the
    # existing stats above answer "is the AI pipeline healthy" but not
    # "why isn't this making money," which needs to see where accounts
    # actually drop off. Excludes the founder's own account (is_founder
    # isn't a DB column -- it's an email comparison against
    # settings.founder_email, same as auth.py's _is_founder) since it's
    # not a real conversion data point. subscription_status <> 'none' is
    # "ever paid" per auth.py's own has_free_incident_available reasoning
    # (a lapsed manual subscription stays 'active' forever in storage, so
    # this can't just check the current status); has_active_subscription's
    # exact expiry logic (current_period_end is stored in *seconds*, not
    # the milliseconds every other timestamp column here uses) is
    # replicated in SQL rather than refetched per-row in Python.
    funnel = await database.fetch_one(
        """SELECT
               count(*) AS signups,
               count(*) FILTER (WHERE free_incident_id IS NOT NULL) AS tried_free_incident,
               count(*) FILTER (WHERE subscription_status <> 'none') AS ever_paid,
               count(*) FILTER (WHERE stripe_subscription_id IS NOT NULL) AS ever_paid_via_stripe,
               count(*) FILTER (
                   WHERE subscription_status IN ('active', 'trialing')
                     AND (current_period_end IS NULL OR current_period_end > extract(epoch FROM now()))
               ) AS currently_paying
           FROM users
           WHERE lower(email) <> lower(%s)""",
        (settings.founder_email,),
    )
    approved_claims = await database.fetch_one(
        "SELECT count(*) AS total FROM payment_claims WHERE status = 'approved'"
    )
    incident_counts = await database.fetch_one(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE status = 'open') AS open,
                  count(*) FILTER (WHERE status = 'resolved') AS resolved,
                  avg(updated_at - created_at) FILTER (WHERE status = 'resolved') AS avg_resolution_ms
           FROM incidents"""
    )
    postmortem_counts = await database.fetch_one(
        """SELECT count(*) FILTER (WHERE status = 'draft') AS drafted,
                  count(*) FILTER (WHERE status = 'published') AS published
           FROM incident_postmortems"""
    )
    ai_run_counts = await database.fetch_one(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
                  count(*) FILTER (WHERE status = 'failed') AS failed,
                  avg(latency_ms) FILTER (WHERE status = 'succeeded') AS avg_latency_ms
           FROM ai_runs"""
    )
    # Last 24h, separately from the all-time totals above -- an all-time
    # success rate stays reassuringly high for months even while something
    # is actively broken right now; this is the "is it broken today" view.
    day_ago = int(time.time() * 1000) - 24 * 60 * 60 * 1000
    ai_run_counts_24h = await database.fetch_one(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
                  count(*) FILTER (WHERE status = 'failed') AS failed,
                  avg(latency_ms) FILTER (WHERE status = 'succeeded') AS avg_latency_ms
           FROM ai_runs WHERE created_at >= %s""",
        (day_ago,),
    )
    # Broken out by prompt_version -- drafting (PROMPT_VERSION, currently
    # "v2") and evidence extraction (EXTRACTION_PROMPT_VERSION, "extract-v1")
    # are two different model calls with independent failure modes; a
    # single blended success rate can hide one of them being broken while
    # the other masks it in the average.
    ai_runs_by_feature = await database.fetch_all(
        """SELECT prompt_version,
                  count(*) AS total,
                  count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
                  count(*) FILTER (WHERE status = 'failed') AS failed,
                  avg(latency_ms) FILTER (WHERE status = 'succeeded') AS avg_latency_ms
           FROM ai_runs GROUP BY prompt_version ORDER BY count(*) DESC"""
    )
    pending_claims = await database.fetch_one(
        "SELECT count(*) AS total FROM payment_claims WHERE status='pending'"
    )
    recent_users = await database.fetch_all(
        "SELECT id::text, email, created_at FROM users ORDER BY created_at DESC LIMIT 10"
    )
    recent_ai_runs = await database.fetch_all(
        """SELECT id::text, incident_id, provider, model, status, error_type, latency_ms, created_at
           FROM ai_runs ORDER BY created_at DESC LIMIT 10"""
    )
    def _latency(row: dict | None) -> float | None:
        value = (row or {}).get("avg_latency_ms")
        return round(float(value), 1) if value is not None else None

    avg_latency = (ai_run_counts or {}).get("avg_latency_ms")
    avg_resolution_ms = (incident_counts or {}).get("avg_resolution_ms")
    return {
        "total_users": (user_counts or {}).get("total", 0),
        "total_incidents": (incident_counts or {}).get("total", 0),
        "open_incidents": (incident_counts or {}).get("open", 0),
        "resolved_incidents": (incident_counts or {}).get("resolved", 0),
        "avg_resolution_ms": round(float(avg_resolution_ms)) if avg_resolution_ms is not None else None,
        "drafted_postmortems": (postmortem_counts or {}).get("drafted", 0),
        "published_postmortems": (postmortem_counts or {}).get("published", 0),
        "ai_runs_total": (ai_run_counts or {}).get("total", 0),
        "ai_runs_succeeded": (ai_run_counts or {}).get("succeeded", 0),
        "ai_runs_failed": (ai_run_counts or {}).get("failed", 0),
        "ai_runs_avg_latency_ms": round(float(avg_latency), 1) if avg_latency is not None else None,
        "ai_runs_24h_total": (ai_run_counts_24h or {}).get("total", 0),
        "ai_runs_24h_succeeded": (ai_run_counts_24h or {}).get("succeeded", 0),
        "ai_runs_24h_failed": (ai_run_counts_24h or {}).get("failed", 0),
        "ai_runs_24h_avg_latency_ms": _latency(ai_run_counts_24h),
        "ai_runs_by_feature": [
            {
                "prompt_version": row["prompt_version"],
                "total": row["total"],
                "succeeded": row["succeeded"],
                "failed": row["failed"],
                "avg_latency_ms": _latency(row),
            }
            for row in ai_runs_by_feature
        ],
        "pending_payment_claims": (pending_claims or {}).get("total", 0),
        "conversion_funnel": {
            "signups": (funnel or {}).get("signups", 0),
            "tried_free_incident": (funnel or {}).get("tried_free_incident", 0),
            "ever_paid": (funnel or {}).get("ever_paid", 0),
            "ever_paid_via_stripe": (funnel or {}).get("ever_paid_via_stripe", 0),
            "currently_paying": (funnel or {}).get("currently_paying", 0),
            "approved_manual_claims": (approved_claims or {}).get("total", 0),
        },
        "recent_users": recent_users,
        "recent_ai_runs": recent_ai_runs,
    }


class PaymentClaimOut(BaseModel):
    id: str
    user_id: str
    email: str
    method: str
    currency: str
    amount: int
    reference: str
    status: str
    created_at: int
    # True when a real forwarded bank alert already matched this claim's
    # reference/amount (see bank_alerts.py) -- strong evidence the money
    # really arrived, shown to the founder as a signal, never a substitute
    # for the founder's own approve click.
    bank_verified: bool


_CLAIM_SELECT = """SELECT c.id::text, c.user_id::text, u.email, c.method, c.currency,
                           c.amount_inr AS amount, c.reference, c.status, c.created_at, c.bank_verified
                    FROM payment_claims c JOIN users u ON u.id = c.user_id"""


@router.get("/payment-claims", response_model=list[PaymentClaimOut])
async def list_payment_claims(
    database: Database = Depends(get_database),
    _founder: User = Depends(current_founder),
) -> list[PaymentClaimOut]:
    rows = await database.fetch_all(
        f"{_CLAIM_SELECT} ORDER BY (c.status = 'pending') DESC, c.created_at DESC LIMIT 50"
    )
    return [PaymentClaimOut(**row) for row in rows]


@router.post("/payment-claims/{claim_id}/approve", response_model=PaymentClaimOut)
async def approve_payment_claim(
    claim_id: str,
    database: Database = Depends(get_database),
    founder: User = Depends(current_founder),
) -> PaymentClaimOut:
    claim = await database.fetch_one(f"{_CLAIM_SELECT} WHERE c.id=%s", (claim_id,))
    if not claim:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    # Same invariant billing.py already enforces client-side (update_my_claim/
    # cancel_my_claim: "only a pending claim can be edited/cancelled") --
    # this side never had the equivalent guard. Without it, approving an
    # already-approved or already-rejected claim silently re-runs
    # activate_manual_subscription (resetting current_period_end to a fresh
    # 30 days from now) and appends a duplicate "approved" event, with no
    # error to signal anything was off -- a double-click or two open founder
    # dashboard tabs could grant an unintended free extension.
    if claim["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a pending claim can be approved")

    now = int(time.time() * 1000)
    async with database.transaction() as tx:
        await tx.execute(
            "UPDATE payment_claims SET status='approved', reviewed_by=%s, reviewed_at=%s WHERE id=%s",
            (founder.email, now, claim_id),
        )
        # 'active' is one of the statuses require_active_subscription treats
        # as paid (see auth.ACTIVE_SUBSCRIPTION_STATUSES). This is the ONLY
        # call site in the whole codebase that reaches
        # activate_manual_subscription with a real, unconditional grant --
        # gated behind current_founder above and the frontend's own
        # explicit confirmation dialog. bank_alerts.py never calls this.
        await activate_manual_subscription(tx, claim["user_id"])
        await record_claim_event(tx, claim_id, "approved", founder.email)
    return PaymentClaimOut(**{**claim, "status": "approved"})


@router.post("/payment-claims/{claim_id}/reject", response_model=PaymentClaimOut)
async def reject_payment_claim(
    claim_id: str,
    database: Database = Depends(get_database),
    founder: User = Depends(current_founder),
) -> PaymentClaimOut:
    claim = await database.fetch_one(f"{_CLAIM_SELECT} WHERE c.id=%s", (claim_id,))
    if not claim:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    # Same reasoning as approve_payment_claim above -- and more important
    # here: there is no code path anywhere in this codebase that revokes a
    # manually-granted subscription (confirmed by grep for every
    # subscription_status='...' write site). Rejecting an already-approved
    # claim would mark it 'rejected' in the ledger while the access it
    # already granted keeps running untouched until natural expiry --
    # a real, misleading gap between what the claim's status says and what
    # access the account actually has. Refusing the transition here at
    # least makes that gap visible instead of silent.
    if claim["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a pending claim can be rejected")

    now = int(time.time() * 1000)
    await database.execute(
        "UPDATE payment_claims SET status='rejected', reviewed_by=%s, reviewed_at=%s WHERE id=%s",
        (founder.email, now, claim_id),
    )
    await record_claim_event(database, claim_id, "rejected", founder.email)
    return PaymentClaimOut(**{**claim, "status": "rejected"})


class PaymentClaimEventOut(BaseModel):
    event_type: str
    actor: str
    detail: str | None
    created_at: int


class AnnotateClaimRequest(BaseModel):
    detail: str = Field(min_length=1, max_length=2000)


@router.post("/payment-claims/{claim_id}/annotate", response_model=PaymentClaimEventOut)
async def annotate_payment_claim(
    claim_id: str,
    payload: AnnotateClaimRequest,
    database: Database = Depends(get_database),
    founder: User = Depends(current_founder),
) -> PaymentClaimEventOut:
    """Appends a founder-authored note to a claim's ledger without touching
    payment_claims.status -- for recording something that happened outside
    the normal approve/reject flow (e.g. a correction to a past decision)
    so the audit trail stays complete instead of getting a gap. Never
    mutates status or grants/revokes access itself; use approve/reject for
    that."""
    exists = await database.fetch_one("SELECT id FROM payment_claims WHERE id=%s", (claim_id,))
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    now = int(time.time() * 1000)
    await record_claim_event(database, claim_id, "annotated", founder.email, payload.detail)
    return PaymentClaimEventOut(event_type="annotated", actor=founder.email, detail=payload.detail, created_at=now)


@router.get("/payment-claims/{claim_id}/events", response_model=list[PaymentClaimEventOut])
async def payment_claim_events(
    claim_id: str,
    database: Database = Depends(get_database),
    _founder: User = Depends(current_founder),
) -> list[PaymentClaimEventOut]:
    """The actual payoff of the append-only ledger (migration 0016): a
    full, unmodifiable history of what happened to a claim -- when it was
    created, whether/when a real bank alert verified it, and who approved
    or rejected it and when. Never reconstructed from payment_claims'
    current-state fields, which only ever show the latest state."""
    exists = await database.fetch_one("SELECT id FROM payment_claims WHERE id=%s", (claim_id,))
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    rows = await database.fetch_all(
        "SELECT event_type, actor, detail, created_at FROM payment_claim_events WHERE claim_id=%s ORDER BY created_at",
        (claim_id,),
    )
    return [PaymentClaimEventOut(**row) for row in rows]


class ActivityLogEntryOut(BaseModel):
    client_email: str
    action: str
    incident_id: str | None
    detail: str | None
    # "web" or "mcp_agent" -- see mcp_server.py's _audited().
    source: str
    created_at: int


class ActivityLogPageOut(BaseModel):
    entries: list[ActivityLogEntryOut]
    # Pass back as ?cursor=... to fetch the next page; null means this was
    # the last one.
    next_cursor: str | None


@router.get("/activity-log", response_model=ActivityLogPageOut)
async def founder_activity_log(
    client_email: str | None = None,
    source: str | None = None,
    since_ms: int | None = None,
    until_ms: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
    database: Database = Depends(get_database),
    _founder: User = Depends(current_founder),
) -> ActivityLogPageOut:
    """The cross-account counterpart to /v1/postmortems/activity-log --
    that endpoint only ever shows the caller's own history; this is the
    actual accountability surface for an autonomous agent acting across
    every account, not just one. Same query handler
    (cqrs.activity.handle_activity_log_query) as the client-scoped route
    and as mcp_server.py's list_agent_activity tool, called here with
    client_email left unset rather than a second, separately-written SQL
    query -- filters (source, a specific client_email, a time window) are
    real WHERE clauses, not client-side filtering of an unbounded dump,
    and pagination is keyset-based (see cqrs/activity.py) so a busy log
    doesn't drift or duplicate rows across pages the way OFFSET would."""
    page = await handle_activity_log_query(
        database,
        ActivityLogFilter(
            client_email=client_email, source=source, since_ms=since_ms, until_ms=until_ms, limit=limit, cursor=cursor
        ),
    )
    return ActivityLogPageOut(
        entries=[
            ActivityLogEntryOut(
                client_email=entry.client_email,
                action=entry.action,
                incident_id=entry.incident_id,
                detail=entry.detail,
                source=entry.source,
                created_at=entry.created_at,
            )
            for entry in page.entries
        ],
        next_cursor=page.next_cursor,
    )
