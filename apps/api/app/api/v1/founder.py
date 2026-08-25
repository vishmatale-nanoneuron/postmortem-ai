import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...auth import User, current_founder
from ...database import Database
from ...dependencies import get_database
from ...services.billing import activate_manual_subscription

router = APIRouter(prefix="/v1/founder", tags=["founder"])


@router.get("/summary")
async def founder_summary(
    database: Database = Depends(get_database),
    _founder: User = Depends(current_founder),
) -> dict[str, object]:
    """Platform-wide aggregates -- unlike /v1/postmortems/summary (scoped to
    one client's own email), this is founder-only precisely because it
    spans every account. Founder authorization is independent of any
    client/subscription state, per the same invariant as
    nanoneuron-software-company."""
    user_counts = await database.fetch_one("SELECT count(*) AS total FROM users")
    incident_counts = await database.fetch_one(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE status = 'open') AS open,
                  count(*) FILTER (WHERE status = 'resolved') AS resolved
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
    avg_latency = (ai_run_counts or {}).get("avg_latency_ms")
    return {
        "total_users": (user_counts or {}).get("total", 0),
        "total_incidents": (incident_counts or {}).get("total", 0),
        "open_incidents": (incident_counts or {}).get("open", 0),
        "resolved_incidents": (incident_counts or {}).get("resolved", 0),
        "drafted_postmortems": (postmortem_counts or {}).get("drafted", 0),
        "published_postmortems": (postmortem_counts or {}).get("published", 0),
        "ai_runs_total": (ai_run_counts or {}).get("total", 0),
        "ai_runs_succeeded": (ai_run_counts or {}).get("succeeded", 0),
        "ai_runs_failed": (ai_run_counts or {}).get("failed", 0),
        "ai_runs_avg_latency_ms": round(float(avg_latency), 1) if avg_latency is not None else None,
        "pending_payment_claims": (pending_claims or {}).get("total", 0),
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

    now = int(time.time() * 1000)
    async with database.transaction() as tx:
        await tx.execute(
            "UPDATE payment_claims SET status='approved', reviewed_by=%s, reviewed_at=%s WHERE id=%s",
            (founder.email, now, claim_id),
        )
        # 'active' is one of the statuses require_active_subscription treats
        # as paid (see auth.ACTIVE_SUBSCRIPTION_STATUSES) -- a manually
        # approved claim grants access exactly the same way a Stripe
        # webhook would, through the same field. Shared with bank_alerts.py's
        # auto-approval so both grant access exactly the same way.
        await activate_manual_subscription(tx, claim["user_id"])
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

    now = int(time.time() * 1000)
    await database.execute(
        "UPDATE payment_claims SET status='rejected', reviewed_by=%s, reviewed_at=%s WHERE id=%s",
        (founder.email, now, claim_id),
    )
    return PaymentClaimOut(**{**claim, "status": "rejected"})
