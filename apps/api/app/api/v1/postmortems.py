import json
import logging
import re
import secrets
import time

import anthropic
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field

from ...ai.circuit_breaker import CircuitOpenError
from ...ai.embeddings import embed_text
from ...ai.model_router import create_model_provider
from ...ai.provider import ModelProvider
from ...ai.rag import (
    embed_and_store_postmortem,
    find_similar_postmortems,
    get_embedding_client,
)
from ...alerting import send_alert
from ...auth import (
    User,
    current_user,
    require_active_subscription,
    require_active_subscription_or_free_incident,
    require_active_subscription_or_free_slot,
)
from ...database import Database
from ...dependencies import get_database
from ...integrations.linear import create_linear_issue
from ...integrations.slack import notify_slack
from ...security.rate_limit import try_record_action
from ...services.postmortem import (
    EXTRACTION_PROMPT_VERSION,
    PROMPT_VERSION,
    UNSUPPORTED,
    EvidenceEntry,
    bound_evidence_by_chars,
    build_draft_request,
    build_extraction_request,
    ground_draft,
    parse_extracted_evidence,
    parse_model_json,
    render_evidence,
)
from ...settings import Settings, get_settings

logger = logging.getLogger("postmortem_ai")

router = APIRouter(prefix="/v1/postmortems", tags=["postmortems"])

# Evidence has no upper bound at the schema level, and every entry is
# rendered into a single prompt with no truncation of its own -- bounding
# here (not in render_evidence) keeps the most recent evidence, closest to
# resolution and most likely to describe root cause/recovery, rather than
# silently keeping only the oldest.
MAX_DRAFT_EVIDENCE_ENTRIES = 500

# Per-account rate limits on every write action -- creating incidents,
# recording evidence, and changing status are cheap individually but still
# a real spam/abuse surface with zero cost to an attacker otherwise;
# drafting is the AI-cost-incurring call and the one that matters most to
# bound. Generous enough not to interfere with real usage.
MAX_INCIDENTS_PER_HOUR = 30
MAX_EVIDENCE_PER_HOUR = 100
MAX_STATUS_CHANGES_PER_HOUR = 60
MAX_DRAFTS_PER_HOUR = 20
MAX_EXTRACTIONS_PER_HOUR = 20
# A full account export is a real, if infrequent, thing a real client does
# (backing up their own data, or before cancelling) -- generous enough to
# never interfere with that, still bounded against a scripted hammering of
# the one read query in this file that scans every incident/evidence/
# postmortem row for an account at once rather than one row/page at a time.
MAX_EXPORTS_PER_HOUR = 10
# Same real cost as drafting's own RAG lookup (one embedding call), just
# reachable on its own now instead of only ever running invisibly inside
# draft_postmortem -- rate-limited the same way for the same reason.
MAX_SIMILAR_SEARCHES_PER_HOUR = 20
RATE_LIMITED_DETAIL = "Too many requests. Try again later."


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    severity: str = Field(pattern="^(sev1|sev2|sev3|sev4)$")
    impact: str | None = Field(default=None, max_length=500)


class EvidenceCreate(BaseModel):
    occurred_at: int = Field(gt=0)
    source: str = Field(pattern="^(alert|log|deploy|metric|human_note|customer_report)$")
    summary: str = Field(min_length=1, max_length=500)
    detail: str | None = Field(default=None, max_length=4000)


def get_model_provider(settings: Settings = Depends(get_settings)) -> ModelProvider:
    return create_model_provider(settings)


async def require_incident(database: Database, incident_id: str, email: str) -> dict:
    incident = await database.fetch_one(
        "SELECT id, title, severity, status FROM incidents WHERE id=%s AND client_email=%s",
        (incident_id, email),
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return incident


async def load_evidence(database: Database, incident_id: str) -> list[EvidenceEntry]:
    rows = await database.fetch_all(
        """SELECT id::text, occurred_at, source, summary, detail, authorized_by
           FROM incident_evidence WHERE incident_id=%s
           ORDER BY occurred_at DESC, id DESC LIMIT %s""",
        (incident_id, MAX_DRAFT_EVIDENCE_ENTRIES),
    )
    rows = list(reversed(rows))
    return [
        EvidenceEntry(
            id=row["id"],
            occurred_at=row["occurred_at"],
            source=row["source"],
            summary=row["summary"],
            detail=row["detail"],
            authorized_by=row["authorized_by"],
        )
        for row in rows
    ]


@router.post("/incidents", status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: IncidentCreate,
    database: Database = Depends(get_database),
    user: User = Depends(require_active_subscription_or_free_slot),
) -> dict[str, object]:
    if not await try_record_action(database, user.id, "create_incident", MAX_INCIDENTS_PER_HOUR, 60 * 60 * 1000):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    # A bare millisecond timestamp collides under real concurrency -- two
    # create_incident calls landing in the same millisecond (plausible on
    # serverless, and more so now that try_record_action lets a legitimate
    # burst through as fast as the DB allows) hit incidents.id's PRIMARY
    # KEY and the second caller gets an unhandled UniqueViolation -> 500.
    # Reproduced directly against Postgres before this fix. The random
    # suffix makes a collision astronomically unlikely without changing
    # incidents.id's column type (still `text`, still human-legible).
    incident_id = f"inc-{int(time.time() * 1000)}-{secrets.token_hex(4)}"
    now = int(time.time() * 1000)
    row = await database.fetch_one(
        """INSERT INTO incidents (id, client_email, title, severity, status, impact, created_at, updated_at)
           VALUES (%s, %s, %s, %s, 'open', %s, %s, %s)
           RETURNING id, title, severity, status, impact""",
        (incident_id, user.email, payload.title, payload.severity, payload.impact, now, now),
    )
    # require_active_subscription_or_free_slot already confirmed this
    # account is either a real subscriber or has its free slot still
    # available -- only spend the slot in the latter case, and only once
    # the insert above actually succeeded (never record a slot as used for
    # an incident that doesn't exist).
    if not user.has_active_subscription:
        await database.execute("UPDATE users SET free_incident_id=%s WHERE id=%s", (incident_id, user.id))
    return dict(row or {})


@router.get("/incidents")
async def list_incidents(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> list[dict]:
    # resolution_ms is a real, computed metric (updated_at - created_at,
    # only meaningful when status='resolved') -- standard incident-response
    # practice (mean time to resolve), not copied from any vendor's
    # product. Honest limitation, not hidden: updated_at reflects the most
    # recent status change, so an incident resolved, reopened, then
    # resolved again shows only its latest resolution span, not the total
    # time across both. update_incident_status is the only write path that
    # ever changes status, and always stamps updated_at at the same time,
    # so this is accurate for the common case (resolved exactly once).
    return await database.fetch_all(
        """SELECT id, title, severity, status, is_public, public_slug,
                  CASE WHEN status = 'resolved' THEN updated_at - created_at END AS resolution_ms
           FROM incidents WHERE client_email=%s ORDER BY created_at DESC""",
        (user.email,),
    )


@router.get("/export")
async def export_my_data(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> dict[str, object]:
    """Everything this account owns, as one downloadable JSON document --
    the real, concrete form 'you can always get your own data out' takes
    here, not a policy statement on a privacy page with nothing backing
    it. Every incident, every piece of evidence, and every postmortem
    (draft or published) this account's client_email owns, in three flat
    lists rather than nested per-incident (a client restoring into another
    tool, or just archiving, wants raw rows, not this app's own internal
    incident-centric shape). Scoped by client_email exactly like every
    other read in this file -- no cross-account leak is possible here any
    more than anywhere else.
    """
    if not await try_record_action(database, user.id, "export_data", MAX_EXPORTS_PER_HOUR, 60 * 60 * 1000):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    incidents = await database.fetch_all(
        """SELECT id, title, severity, status, impact, created_at, updated_at
           FROM incidents WHERE client_email=%s ORDER BY created_at""",
        (user.email,),
    )
    evidence = await database.fetch_all(
        """SELECT e.incident_id, e.id::text AS id, e.occurred_at, e.source, e.summary, e.detail,
                  e.authorized_by, e.recorded_at
           FROM incident_evidence e
           JOIN incidents i ON i.id = e.incident_id
           WHERE i.client_email=%s ORDER BY e.recorded_at""",
        (user.email,),
    )
    postmortems = await database.fetch_all(
        """SELECT p.incident_id, p.status, p.summary, p.root_cause, p.detection, p.resolution,
                  p.contributing_factors, p.cited_evidence_ids, p.unsupported_claims_dropped,
                  p.prompt_version, p.approved_by, p.approved_at, p.is_public, p.slug, p.updated_at
           FROM incident_postmortems p
           JOIN incidents i ON i.id = p.incident_id
           WHERE i.client_email=%s ORDER BY p.updated_at""",
        (user.email,),
    )
    actions = await database.fetch_all(
        """SELECT p.incident_id, a.title, a.rationale, a.owner, a.status, a.evidence_id::text AS evidence_id,
                  a.created_at, a.updated_at
           FROM postmortem_actions a
           JOIN incident_postmortems p ON p.id = a.postmortem_id
           JOIN incidents i ON i.id = p.incident_id
           WHERE i.client_email=%s ORDER BY a.created_at""",
        (user.email,),
    )
    return {
        "exported_at": int(time.time() * 1000),
        "account_email": user.email,
        "incidents": incidents,
        "evidence": evidence,
        "postmortems": postmortems,
        "actions": actions,
    }


class IncidentStatusUpdate(BaseModel):
    status: str = Field(pattern="^(open|resolved)$")


@router.patch("/incidents/{incident_id}/status")
async def update_incident_status(
    incident_id: str,
    payload: IncidentStatusUpdate,
    database: Database = Depends(get_database),
    user: User = Depends(require_active_subscription_or_free_incident),
) -> dict[str, object]:
    if not await try_record_action(
        database, user.id, "update_incident_status", MAX_STATUS_CHANGES_PER_HOUR, 60 * 60 * 1000
    ):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    await require_incident(database, incident_id, user.email)
    now = int(time.time() * 1000)
    row = await database.fetch_one(
        "UPDATE incidents SET status=%s, updated_at=%s WHERE id=%s RETURNING id, title, severity, status",
        (payload.status, now, incident_id),
    )
    return dict(row or {})


@router.get("/summary")
async def dashboard_summary(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> dict[str, object]:
    """Real aggregate counts for a client dashboard -- one query, not the
    frontend fetching every incident's own postmortem to count client-side
    (which would be an N+1 call pattern for something this cheap to do in
    SQL once)."""
    incident_counts = await database.fetch_one(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE status = 'open') AS open,
                  count(*) FILTER (WHERE status = 'resolved') AS resolved,
                  avg(updated_at - created_at) FILTER (WHERE status = 'resolved') AS avg_resolution_ms
           FROM incidents WHERE client_email=%s""",
        (user.email,),
    )
    postmortem_counts = await database.fetch_one(
        """SELECT count(*) FILTER (WHERE p.status = 'draft') AS drafted,
                  count(*) FILTER (WHERE p.status = 'published') AS published
           FROM incident_postmortems p
           JOIN incidents i ON i.id = p.incident_id
           WHERE i.client_email=%s""",
        (user.email,),
    )
    recent_incidents = await database.fetch_all(
        """SELECT id, title, severity, status,
                  CASE WHEN status = 'resolved' THEN updated_at - created_at END AS resolution_ms
           FROM incidents WHERE client_email=%s ORDER BY created_at DESC LIMIT 5""",
        (user.email,),
    )
    avg_resolution_ms = (incident_counts or {}).get("avg_resolution_ms")
    return {
        "total_incidents": (incident_counts or {}).get("total", 0),
        "open_incidents": (incident_counts or {}).get("open", 0),
        "resolved_incidents": (incident_counts or {}).get("resolved", 0),
        "drafted_postmortems": (postmortem_counts or {}).get("drafted", 0),
        "published_postmortems": (postmortem_counts or {}).get("published", 0),
        "avg_resolution_ms": round(float(avg_resolution_ms)) if avg_resolution_ms is not None else None,
        "recent_incidents": recent_incidents,
    }


class EvidenceQualitySummaryOut(BaseModel):
    total_drafts: int
    drafts_with_any_unsupported_section: int
    unsupported_by_section: dict[str, int]


@router.get("/quality-summary", response_model=EvidenceQualitySummaryOut)
async def evidence_quality_summary(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> EvidenceQualitySummaryOut:
    """Turns 'Not established by the recorded evidence.' from a per-draft
    error marker into an account-wide signal. The fixed UNSUPPORTED text is
    already stored verbatim in whichever of the four required sections
    couldn't be grounded (see ground_draft) -- this just counts how often
    that's true across the account's own drafts, broken down by which
    section it happens to most, rather than inventing a new tracking
    mechanism for something the data already records. Nothing here is a
    quality judgment on any one incident (an incomplete-evidence incident
    isn't a mistake) -- it's meant to help someone notice a pattern, e.g.
    'resolution is unsupported on 8 of my last 10 incidents' suggesting
    evidence habits worth adjusting, not any single draft worth doubting.
    """
    row = await database.fetch_one(
        """SELECT count(*) AS total,
                  count(*) FILTER (
                      WHERE p.summary = %s OR p.root_cause = %s OR p.detection = %s OR p.resolution = %s
                  ) AS any_unsupported,
                  count(*) FILTER (WHERE p.summary = %s) AS summary_unsupported,
                  count(*) FILTER (WHERE p.root_cause = %s) AS root_cause_unsupported,
                  count(*) FILTER (WHERE p.detection = %s) AS detection_unsupported,
                  count(*) FILTER (WHERE p.resolution = %s) AS resolution_unsupported
           FROM incident_postmortems p
           JOIN incidents i ON i.id = p.incident_id
           WHERE i.client_email = %s""",
        (UNSUPPORTED, UNSUPPORTED, UNSUPPORTED, UNSUPPORTED, UNSUPPORTED, UNSUPPORTED, UNSUPPORTED, UNSUPPORTED, user.email),
    )
    row = row or {}
    return EvidenceQualitySummaryOut(
        total_drafts=row.get("total", 0) or 0,
        drafts_with_any_unsupported_section=row.get("any_unsupported", 0) or 0,
        unsupported_by_section={
            "summary": row.get("summary_unsupported", 0) or 0,
            "root_cause": row.get("root_cause_unsupported", 0) or 0,
            "detection": row.get("detection_unsupported", 0) or 0,
            "resolution": row.get("resolution_unsupported", 0) or 0,
        },
    )


@router.post("/incidents/{incident_id}/evidence", status_code=status.HTTP_201_CREATED)
async def record_evidence(
    incident_id: str,
    payload: EvidenceCreate,
    database: Database = Depends(get_database),
    user: User = Depends(require_active_subscription_or_free_incident),
) -> dict[str, object]:
    if not await try_record_action(database, user.id, "record_evidence", MAX_EVIDENCE_PER_HOUR, 60 * 60 * 1000):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    await require_incident(database, incident_id, user.email)
    now = int(time.time() * 1000)
    row = await database.fetch_one(
        """INSERT INTO incident_evidence
             (incident_id,client_email,occurred_at,source,summary,detail,
              authorized_by,recorded_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id::text, occurred_at, source, summary, detail, authorized_by""",
        (
            incident_id,
            user.email,
            payload.occurred_at,
            payload.source,
            payload.summary,
            payload.detail,
            user.email,
            now,
        ),
    )
    return dict(row or {})


@router.get("/incidents/{incident_id}/evidence")
async def list_evidence(
    incident_id: str,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> list[dict]:
    await require_incident(database, incident_id, user.email)
    return await database.fetch_all(
        """SELECT id::text, occurred_at, source, summary, detail, authorized_by, recorded_at
           FROM incident_evidence WHERE incident_id=%s ORDER BY occurred_at, id""",
        (incident_id,),
    )


class ExtractEvidenceIn(BaseModel):
    text: str = Field(min_length=1, max_length=40_000)


class ExtractedEvidenceOut(BaseModel):
    source: str
    summary: str
    detail: str | None


@router.post("/incidents/{incident_id}/evidence/extract", response_model=list[ExtractedEvidenceOut])
async def extract_evidence(
    incident_id: str,
    payload: ExtractEvidenceIn,
    database: Database = Depends(get_database),
    provider: ModelProvider = Depends(get_model_provider),
    user: User = Depends(require_active_subscription_or_free_incident),
) -> list[ExtractedEvidenceOut]:
    """Assistive, not autonomous: proposes evidence entries from a pasted
    thread/log, but never writes to incident_evidence itself. The client
    reviews, edits, or discards each suggestion and adds it through the
    existing POST .../evidence endpoint, unchanged by this feature -- same
    reason ground_draft only ever filters the drafting model's output
    rather than trusting it directly."""
    if not await try_record_action(database, user.id, "extract_evidence", MAX_EXTRACTIONS_PER_HOUR, 60 * 60 * 1000):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    await require_incident(database, incident_id, user.email)
    started_at = time.monotonic()

    async def record_ai_run(status_value: str, output_tokens: int | None, error_type: str | None) -> None:
        latency_ms = int((time.monotonic() - started_at) * 1000)
        await database.execute(
            """INSERT INTO ai_runs
                 (id,incident_id,provider,model,prompt_version,input_chars,
                  output_tokens,latency_ms,status,error_type,created_at)
               VALUES (gen_random_uuid(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                incident_id,
                provider.name,
                provider.model_name,
                EXTRACTION_PROMPT_VERSION,
                len(payload.text),
                output_tokens,
                latency_ms,
                status_value,
                error_type,
                int(time.time() * 1000),
            ),
        )

    try:
        result = await provider.complete(build_extraction_request(payload.text))
        response = parse_model_json(result.text)
    except CircuitOpenError as error:
        logger.warning("evidence_extraction_failed", extra={"incident_id": incident_id, "error_type": "circuit_open"})
        await record_ai_run("failed", None, "circuit_open")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The extraction model has failed repeatedly and is being avoided for a short cooldown -- try again shortly",
        ) from error
    except (ValueError, TypeError) as error:
        logger.warning(
            "evidence_extraction_failed", extra={"incident_id": incident_id, "error_type": "unreadable_response"}
        )
        await record_ai_run("failed", None, "unreadable_response")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The extraction model returned an unreadable response",
        ) from error
    except (httpx.HTTPError, genai_errors.APIError, anthropic.APIError, anthropic.APIConnectionError) as error:
        logger.warning(
            "evidence_extraction_failed", extra={"incident_id": incident_id, "error_type": type(error).__name__}
        )
        await record_ai_run("failed", None, type(error).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The extraction model is temporarily unavailable",
        ) from error

    extracted = parse_extracted_evidence(response)
    await record_ai_run("succeeded", result.output_tokens, None)
    logger.info(
        "evidence_extraction_succeeded",
        extra={"incident_id": incident_id, "entries_extracted": len(extracted)},
    )
    return [ExtractedEvidenceOut(source=e.source, summary=e.summary, detail=e.detail) for e in extracted]


class SimilarIncidentOut(BaseModel):
    incident_title: str
    summary: str
    root_cause: str


@router.get("/incidents/{incident_id}/similar", response_model=list[SimilarIncidentOut])
async def similar_incidents(
    incident_id: str,
    database: Database = Depends(get_database),
    user: User = Depends(require_active_subscription_or_free_incident),
    settings: Settings = Depends(get_settings),
) -> list[SimilarIncidentOut]:
    """Surfaces the same similar-past-incident retrieval draft_postmortem
    already runs internally as hidden RAG context for the model -- reachable
    directly now so a human can see "you've had 3 incidents like this
    before" *before* committing to a draft, not just have it silently
    shape the model's output. Same retrieval, same account-scoped,
    published-only pool (see ai/rag.py's find_similar_postmortems) --
    intentionally not a second implementation.
    """
    if not await try_record_action(
        database, user.id, "similar_incidents", MAX_SIMILAR_SEARCHES_PER_HOUR, 60 * 60 * 1000
    ):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    incident = await require_incident(database, incident_id, user.email)
    evidence = await load_evidence(database, incident_id)
    if not evidence:
        return []

    evidence = bound_evidence_by_chars(evidence)
    try:
        query_text = f"{incident.get('title')}\n{render_evidence(evidence)}"
        embedding_client = get_embedding_client(settings.gemini_api_key)
        query_embedding = await embed_text(embedding_client, query_text)
        similar = await find_similar_postmortems(database, user.email, query_embedding, incident_id)
    except Exception:
        logger.warning("similar_incidents_lookup_failed", extra={"incident_id": incident_id}, exc_info=True)
        return []

    return [
        SimilarIncidentOut(incident_title=s.incident_title, summary=s.summary, root_cause=s.root_cause)
        for s in similar
    ]


@router.post("/incidents/{incident_id}/draft", status_code=status.HTTP_201_CREATED)
async def draft_postmortem(
    incident_id: str,
    database: Database = Depends(get_database),
    provider: ModelProvider = Depends(get_model_provider),
    user: User = Depends(require_active_subscription_or_free_incident),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Build a review-ready draft from the recorded evidence.

    The model's answer is grounded before it is stored: any claim not supported
    by a cited evidence entry is replaced or removed, never kept. The result is
    always a draft -- publishing is a separate, human act.
    """
    if not await try_record_action(database, user.id, "draft_postmortem", MAX_DRAFTS_PER_HOUR, 60 * 60 * 1000):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    incident = await require_incident(database, incident_id, user.email)
    evidence = await load_evidence(database, incident_id)
    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Record at least one piece of evidence before drafting a postmortem",
        )
    # Two independent bounds: load_evidence already caps row count; this
    # caps the rendered character size of whatever survived that cap, since
    # a small number of large entries (summary + detail near their max
    # lengths) can still be an oversized request on their own. Both bounds
    # must use the exact same evidence list for build_draft_request and
    # ground_draft, or citation numbers won't line up.
    evidence = bound_evidence_by_chars(evidence)
    input_chars = len(render_evidence(evidence))

    logger.info(
        "postmortem_draft_requested",
        extra={"incident_id": incident_id, "provider": provider.name, "evidence_count": len(evidence)},
    )
    started_at = time.monotonic()

    async def record_ai_run(status_value: str, output_tokens: int | None, error_type: str | None) -> None:
        latency_ms = int((time.monotonic() - started_at) * 1000)
        await database.execute(
            """INSERT INTO ai_runs
                 (id,incident_id,provider,model,prompt_version,input_chars,
                  output_tokens,latency_ms,status,error_type,created_at)
               VALUES (gen_random_uuid(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                incident_id,
                provider.name,
                provider.model_name,
                PROMPT_VERSION,
                input_chars,
                output_tokens,
                latency_ms,
                status_value,
                error_type,
                int(time.time() * 1000),
            ),
        )

    # RAG: retrieve similar past PUBLISHED postmortems (this client only)
    # as reference context -- never evidence, never citable (see
    # services/postmortem.py's SYSTEM_PROMPT rule 5). Best-effort: any
    # failure here (embedding call, retrieval query) must never block
    # drafting itself, which is why it's wrapped separately from the
    # actual drafting try/except below and simply degrades to no context.
    similar_past_incidents = []
    try:
        query_text = f"{incident.get('title')}\n{render_evidence(evidence)}"
        embedding_client = get_embedding_client(settings.gemini_api_key)
        query_embedding = await embed_text(embedding_client, query_text)
        similar_past_incidents = await find_similar_postmortems(
            database, user.email, query_embedding, incident_id
        )
    except Exception:
        logger.warning("postmortem_rag_retrieval_failed", extra={"incident_id": incident_id}, exc_info=True)

    try:
        result = await provider.complete(
            build_draft_request(dict(incident), evidence, similar_past_incidents=similar_past_incidents)
        )
        response = parse_model_json(result.text)
    except CircuitOpenError as error:
        # Distinct from a single failed call (502 below): the breaker is
        # deliberately avoiding a provider that has failed repeatedly,
        # rather than adding one more failing request on top -- 503 says
        # "we know, don't retry immediately" rather than "this one call
        # happened to fail." Also the one failure mode worth a real alert
        # (not just a log line): the drafting model is broken right now,
        # not just this one request. May fire more than once per outage
        # (every blocked call during the cooldown re-raises this), which
        # is an accepted tradeoff over the added complexity of tracking
        # "already alerted for this open period" state.
        logger.warning("postmortem_draft_failed", extra={"incident_id": incident_id, "error_type": "circuit_open"})
        await record_ai_run("failed", None, "circuit_open")
        await send_alert(
            settings.alert_webhook_url,
            f"PostMortem AI: drafting circuit breaker is OPEN for {provider.name}/{provider.model_name} "
            f"-- the model has failed repeatedly and is being avoided for a cooldown.",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The drafting model has failed repeatedly and is being avoided for a short cooldown -- try again shortly",
        ) from error
    except (ValueError, TypeError) as error:
        logger.warning("postmortem_draft_failed", extra={"incident_id": incident_id, "error_type": "unreadable_response"})
        await record_ai_run("failed", None, "unreadable_response")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The drafting model returned an unreadable response",
        ) from error
    except (httpx.HTTPError, genai_errors.APIError, anthropic.APIError, anthropic.APIConnectionError) as error:
        # httpx.HTTPError covers a generic ModelProvider's own request
        # failures; google.genai.errors.APIError is the Gemini SDK's own
        # common base (auth errors, rate limits, server errors) and is NOT a
        # subclass of httpx.HTTPError, so it needs its own catch -- found the
        # hard way via a live smoke test against a real (invalid) API key
        # surfacing an uncaught 500 before this catch existed at all.
        # anthropic.APIError/APIConnectionError are the same story for
        # Claude, added proactively this time (not after another live
        # surprise): Claude is now a real fallback provider FallbackProvider
        # can actually reach (see ai/model_router.py), not just a historical
        # note, and in Python APIConnectionError is a SIBLING of APIError,
        # not a subclass of it -- catching only APIError would still miss a
        # real Claude network failure.
        logger.warning(
            "postmortem_draft_failed",
            extra={"incident_id": incident_id, "error_type": type(error).__name__},
        )
        await record_ai_run("failed", None, type(error).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The drafting model is temporarily unavailable",
        ) from error

    draft = ground_draft(response, evidence)
    await record_ai_run("succeeded", result.output_tokens, None)
    logger.info(
        "postmortem_draft_succeeded",
        extra={
            "incident_id": incident_id,
            "provider": provider.name,
            "unsupported_claims_dropped": draft.unsupported_claims_dropped,
        },
    )
    now = int(time.time() * 1000)

    async with database.transaction() as tx:
        # Snapshot whatever draft already exists (if any -- the first-ever
        # draft has nothing to snapshot) before the UPSERT below overwrites
        # it, so a re-draft is comparable to what it replaced instead of
        # just silently vanishing. Same transaction as the overwrite: this
        # snapshot and the new draft either both land or neither does.
        existing = await tx.fetch_one(
            """SELECT summary, root_cause, detection, resolution, contributing_factors, unsupported_claims_dropped
               FROM incident_postmortems WHERE incident_id=%s""",
            (incident_id,),
        )
        if existing is not None:
            await tx.execute(
                """INSERT INTO postmortem_draft_history
                     (incident_id, summary, root_cause, detection, resolution,
                      contributing_factors, unsupported_claims_dropped, superseded_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    incident_id,
                    existing["summary"],
                    existing["root_cause"],
                    existing["detection"],
                    existing["resolution"],
                    # existing["contributing_factors"] comes back from SELECT
                    # already deserialized into a native Python list (psycopg3's
                    # jsonb adapter does this automatically on read) -- writing
                    # it into another jsonb column needs the same explicit
                    # json.dumps() every other write in this file uses (see
                    # json_list below), not the raw list passed straight through.
                    json_list(existing["contributing_factors"]),
                    existing["unsupported_claims_dropped"],
                    now,
                ),
            )

        postmortem = await tx.fetch_one(
            """INSERT INTO incident_postmortems
                 (id,incident_id,status,summary,root_cause,detection,resolution,
                  contributing_factors,cited_evidence_ids,unsupported_claims_dropped,
                  generated_by,prompt_version,created_at,updated_at)
               VALUES (gen_random_uuid(),%s,'draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (incident_id) DO UPDATE SET
                 status='draft', approved_by=NULL, approved_at=NULL,
                 summary=excluded.summary, root_cause=excluded.root_cause,
                 detection=excluded.detection, resolution=excluded.resolution,
                 contributing_factors=excluded.contributing_factors,
                 cited_evidence_ids=excluded.cited_evidence_ids,
                 unsupported_claims_dropped=excluded.unsupported_claims_dropped,
                 generated_by=excluded.generated_by, prompt_version=excluded.prompt_version,
                 updated_at=excluded.updated_at
               RETURNING id::text""",
            (
                incident_id,
                draft.summary,
                draft.root_cause,
                draft.detection,
                draft.resolution,
                json_list(draft.contributing_factors),
                json_list(draft.cited_evidence_ids),
                draft.unsupported_claims_dropped,
                provider.name,
                PROMPT_VERSION,
                now,
                now,
            ),
        )
        postmortem_id = postmortem["id"]  # type: ignore[index]

        await tx.execute(
            "DELETE FROM postmortem_actions WHERE postmortem_id=%s AND evidence_id IS NOT NULL",
            (postmortem_id,),
        )
        if draft.actions:
            # Single batched INSERT instead of one round-trip per action --
            # draft.actions is always small (bounded by the AI response),
            # so this isn't a big win in absolute terms, but N sequential
            # round-trips inside one transaction for what's naturally one
            # statement is still the wrong default to reach for.
            values_clause = ", ".join("(gen_random_uuid(),%s,%s,%s,%s,%s,%s,%s)" for _ in draft.actions)
            params: list[object] = []
            for action in draft.actions:
                params.extend([postmortem_id, action.title, action.rationale, action.owner, action.evidence_id, now, now])
            await tx.execute(
                f"""INSERT INTO postmortem_actions
                      (id,postmortem_id,title,rationale,owner,evidence_id,created_at,updated_at)
                    VALUES {values_clause}""",
                params,
            )

    return await _load_postmortem(database, incident_id)


class PreviousDraftOut(BaseModel):
    summary: str
    root_cause: str
    detection: str
    resolution: str
    contributing_factors: list[str]
    unsupported_claims_dropped: int
    superseded_at: int


@router.get("/incidents/{incident_id}/previous-draft", response_model=PreviousDraftOut | None)
async def previous_draft(
    incident_id: str,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> PreviousDraftOut | None:
    """The one snapshot draft_postmortem takes immediately before each
    overwrite (see postmortem_draft_history, migration 0021) -- lets a
    client diff the current draft against what it replaced instead of a
    re-draft looking like an unexplained full rewrite. Read-only; nothing
    here can grant the paywalled actions drafting/publishing require --
    the same current_user dependency /incidents/{id} itself uses, since
    viewing your own history is meant to stay reachable even for a lapsed
    account (see require_active_subscription's own docstring)."""
    await require_incident(database, incident_id, user.email)
    row = await database.fetch_one(
        """SELECT summary, root_cause, detection, resolution, contributing_factors,
                  unsupported_claims_dropped, superseded_at
           FROM postmortem_draft_history WHERE incident_id=%s
           ORDER BY superseded_at DESC LIMIT 1""",
        (incident_id,),
    )
    if row is None:
        return None
    return PreviousDraftOut(
        summary=row["summary"],
        root_cause=row["root_cause"],
        detection=row["detection"],
        resolution=row["resolution"],
        contributing_factors=list(row["contributing_factors"] or []),
        unsupported_claims_dropped=row["unsupported_claims_dropped"],
        superseded_at=row["superseded_at"],
    )


@router.get("/incidents/{incident_id}")
async def get_postmortem(
    incident_id: str,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> dict[str, object]:
    await require_incident(database, incident_id, user.email)
    return await _load_postmortem(database, incident_id)


@router.post("/incidents/{incident_id}/publish")
async def publish_postmortem(
    incident_id: str,
    database: Database = Depends(get_database),
    user: User = Depends(require_active_subscription),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    incident = await require_incident(database, incident_id, user.email)
    now = int(time.time() * 1000)
    updated = await database.execute(
        """UPDATE incident_postmortems
           SET status='published', approved_by=%s, approved_at=%s, updated_at=%s
           WHERE incident_id=%s""",
        (user.email, now, now, incident_id),
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No draft postmortem to publish")

    published = await _load_postmortem(database, incident_id)
    # Best-effort, never blocks the publish response -- a failure here
    # only means this postmortem won't surface as RAG context for future
    # drafts, not that publishing itself failed.
    try:
        text = f"{published.get('summary')}\n{published.get('root_cause')}"
        await embed_and_store_postmortem(database, settings.gemini_api_key, str(published["id"]), text)
    except Exception:
        logger.warning("postmortem_embedding_failed", extra={"incident_id": incident_id}, exc_info=True)

    # Client integrations (Slack notify, Linear ticket-per-action) -- also
    # best-effort, also never blocks the publish response. Each account
    # connects its own workspace; a client with neither configured pays no
    # extra cost here (both calls are no-ops when unconfigured).
    try:
        integration_row = await database.fetch_one(
            "SELECT slack_webhook_url, linear_api_key, linear_team_id FROM users WHERE id=%s", (user.id,)
        )
        integration_row = integration_row or {}
        await notify_slack(
            integration_row.get("slack_webhook_url"),
            f"Postmortem published: *{incident['title']}* -- {published.get('summary')}",
        )
        for action in published.get("actions", []):
            await create_linear_issue(
                integration_row.get("linear_api_key"),
                integration_row.get("linear_team_id"),
                title=action["title"],
                description=f"{action['rationale']}\n\nFrom postmortem: {incident['title']}",
            )
    except Exception:
        logger.warning("postmortem_publish_integrations_failed", extra={"incident_id": incident_id}, exc_info=True)

    return published


async def _load_postmortem(database: Database, incident_id: str) -> dict[str, object]:
    postmortem = await database.fetch_one(
        """SELECT id::text, status, summary, root_cause, detection, resolution,
                  contributing_factors, cited_evidence_ids, unsupported_claims_dropped,
                  prompt_version, approved_by, approved_at, is_public, slug
           FROM incident_postmortems WHERE incident_id=%s""",
        (incident_id,),
    )
    if not postmortem:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No postmortem drafted yet")
    actions = await database.fetch_all(
        """SELECT id::text, title, rationale, owner, evidence_id::text, status
           FROM postmortem_actions WHERE postmortem_id=%s ORDER BY created_at""",
        (postmortem["id"],),
    )
    return {**postmortem, "actions": actions}


def json_list(values: list[str]) -> str:
    return json.dumps(values)


def slugify(title: str, incident_id: str) -> str:
    """A public URL's slug -- kebab-cased title plus a short suffix
    derived from the incident id, so two incidents titled the same way
    still get distinct URLs without a retry-on-collision loop."""
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "postmortem"
    suffix = incident_id.split("-")[-1][-8:] if "-" in incident_id else incident_id[-8:]
    return f"{base}-{suffix}"


class PublicVisibilityUpdate(BaseModel):
    is_public: bool


@router.patch("/incidents/{incident_id}/public")
async def update_public_visibility(
    incident_id: str,
    payload: PublicVisibilityUpdate,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> dict[str, object]:
    """Opt a PUBLISHED postmortem in or out of having a public, SEO-indexed
    page at /postmortems/{slug}. Owner-only, but deliberately not gated
    behind require_active_subscription -- managing the privacy of already-
    published content shouldn't be blocked by a lapsed subscription."""
    incident = await require_incident(database, incident_id, user.email)
    existing = await database.fetch_one(
        "SELECT id::text, status, slug FROM incident_postmortems WHERE incident_id=%s", (incident_id,)
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No postmortem drafted yet")
    if existing["status"] != "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a published postmortem can be made public")

    # Generate the slug once, the first time this postmortem ever goes
    # public, and never again -- a stable URL matters for real SEO/
    # sharing; regenerating on every re-publish or re-toggle would break
    # every link and search index entry pointing at the old one.
    slug = existing["slug"]
    if payload.is_public and not slug:
        slug = slugify(str(incident["title"]), incident_id)

    await database.execute(
        "UPDATE incident_postmortems SET is_public=%s, slug=%s WHERE incident_id=%s",
        (payload.is_public, slug, incident_id),
    )
    return await _load_postmortem(database, incident_id)


MAX_STATUS_PAGE_UPDATES_PER_HOUR = 20


@router.patch("/incidents/{incident_id}/status-page")
async def update_status_page_visibility(
    incident_id: str,
    payload: PublicVisibilityUpdate,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> dict[str, object]:
    """Turn an incident's own live public status page on or off --
    independent of update_public_visibility above, which only ever applies
    to a PUBLISHED postmortem after the incident is over. This is for
    while the incident is still happening: 'is it down right now,' often
    before any postmortem exists at all. Same not-gated-behind-
    subscription reasoning as the postmortem one -- toggling visibility of
    your own already-created content isn't the paywalled action."""
    incident = await require_incident(database, incident_id, user.email)
    # require_incident's own SELECT doesn't carry public_slug (used by many
    # other call sites that don't need it) -- same reasoning
    # update_public_visibility above already applies to incident_postmortems'
    # own slug: a small, targeted extra fetch rather than widening a
    # shared helper's column list for one caller.
    existing = await database.fetch_one("SELECT public_slug FROM incidents WHERE id=%s", (incident_id,))
    public_slug = (existing or {}).get("public_slug")
    if payload.is_public and not public_slug:
        public_slug = slugify(str(incident["title"]), incident_id)

    row = await database.fetch_one(
        """UPDATE incidents SET is_public=%s, public_slug=%s WHERE id=%s
           RETURNING id, title, severity, status, is_public, public_slug""",
        (payload.is_public, public_slug, incident_id),
    )
    return dict(row or {})


class StatusPageUpdateIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class StatusPageUpdateOut(BaseModel):
    message: str
    created_at: int


@router.post(
    "/incidents/{incident_id}/status-page/updates",
    status_code=status.HTTP_201_CREATED,
    response_model=StatusPageUpdateOut,
)
async def post_status_page_update(
    incident_id: str,
    payload: StatusPageUpdateIn,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> StatusPageUpdateOut:
    """A curated message for the public page -- deliberately separate from
    incident_evidence (which can carry internal debugging detail, customer
    PII, or raw log content never meant for a public audience). Posting an
    update doesn't require the page to be public yet -- lets a client
    write the first update, then flip is_public on, without a forced
    ordering."""
    await require_incident(database, incident_id, user.email)
    if not await try_record_action(
        database, user.id, "status_page_update", MAX_STATUS_PAGE_UPDATES_PER_HOUR, 60 * 60 * 1000
    ):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    now = int(time.time() * 1000)
    await database.execute(
        "INSERT INTO incident_public_updates (incident_id, message, posted_by, created_at) VALUES (%s, %s, %s, %s)",
        (incident_id, payload.message, user.email, now),
    )
    return StatusPageUpdateOut(message=payload.message, created_at=now)


@router.get("/incidents/{incident_id}/status-page/updates", response_model=list[StatusPageUpdateOut])
async def list_status_page_updates(
    incident_id: str,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> list[StatusPageUpdateOut]:
    """The owner's own view of updates they've posted -- for managing the
    page, not the public-facing read (see get_public_status_page below,
    which is unauthenticated and scoped by public_slug instead)."""
    await require_incident(database, incident_id, user.email)
    rows = await database.fetch_all(
        "SELECT message, created_at FROM incident_public_updates WHERE incident_id=%s ORDER BY created_at DESC",
        (incident_id,),
    )
    return [StatusPageUpdateOut(**row) for row in rows]


class PublicStatusPageOut(BaseModel):
    incident_title: str
    severity: str
    status: str
    updates: list[StatusPageUpdateOut]


@router.get("/status-page/{public_slug}", response_model=PublicStatusPageOut)
async def get_public_status_page(public_slug: str, database: Database = Depends(get_database)) -> PublicStatusPageOut:
    """Unauthenticated -- a live incident status page. 404s (not 403) for
    a private or nonexistent slug, same reasoning as get_public_postmortem:
    doesn't let this be used to distinguish 'exists but private' from
    'never existed'. Deliberately returns no client_email, no internal
    evidence, no incident id -- only the fields a public visitor should
    ever see."""
    incident = await database.fetch_one(
        "SELECT title, severity, status FROM incidents WHERE public_slug=%s AND is_public=true",
        (public_slug,),
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    updates = await database.fetch_all(
        """SELECT u.message, u.created_at FROM incident_public_updates u
           JOIN incidents i ON i.id = u.incident_id
           WHERE i.public_slug=%s ORDER BY u.created_at DESC""",
        (public_slug,),
    )
    return PublicStatusPageOut(
        incident_title=incident["title"],
        severity=incident["severity"],
        status=incident["status"],
        updates=[StatusPageUpdateOut(**row) for row in updates],
    )


class PublicPostmortemOut(BaseModel):
    slug: str
    incident_title: str
    severity: str
    summary: str
    root_cause: str
    detection: str
    resolution: str
    contributing_factors: list[str]
    approved_at: int | None
    published_at: int | None


@router.get("/public", response_model=list[PublicPostmortemOut])
async def list_public_postmortems(database: Database = Depends(get_database)) -> list[PublicPostmortemOut]:
    """Unauthenticated -- every currently-public postmortem, most recently
    approved first. Backs both the public index page and the sitemap; only
    the fields safe to publish (no client_email, no internal ids)."""
    rows = await database.fetch_all(
        """SELECT p.slug, i.title AS incident_title, i.severity, p.summary, p.root_cause,
                  p.detection, p.resolution, p.contributing_factors, p.approved_at, p.updated_at AS published_at
           FROM incident_postmortems p JOIN incidents i ON i.id = p.incident_id
           WHERE p.is_public = true AND p.status = 'published'
           ORDER BY p.approved_at DESC NULLS LAST
           LIMIT 200"""
    )
    return [PublicPostmortemOut(**row) for row in rows]


@router.get("/public/{slug}", response_model=PublicPostmortemOut)
async def get_public_postmortem(slug: str, database: Database = Depends(get_database)) -> PublicPostmortemOut:
    """Unauthenticated -- a single public postmortem by its slug. 404s
    (not 403) for a private or nonexistent slug, so this can't be used to
    distinguish "exists but private" from "never existed"."""
    row = await database.fetch_one(
        """SELECT p.slug, i.title AS incident_title, i.severity, p.summary, p.root_cause,
                  p.detection, p.resolution, p.contributing_factors, p.approved_at, p.updated_at AS published_at
           FROM incident_postmortems p JOIN incidents i ON i.id = p.incident_id
           WHERE p.slug=%s AND p.is_public = true AND p.status = 'published'""",
        (slug,),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return PublicPostmortemOut(**row)
