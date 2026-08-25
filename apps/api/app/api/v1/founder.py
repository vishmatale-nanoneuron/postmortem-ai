from fastapi import APIRouter, Depends

from ...auth import User, current_founder
from ...database import Database
from ...dependencies import get_database

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
        "recent_users": recent_users,
        "recent_ai_runs": recent_ai_runs,
    }
