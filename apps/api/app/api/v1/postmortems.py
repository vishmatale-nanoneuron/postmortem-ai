import json
import logging
import re
import secrets
import time

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
from ...auth import User, current_user, require_active_subscription
from ...database import Database
from ...dependencies import get_database
from ...integrations.linear import create_linear_issue
from ...integrations.slack import notify_slack
from ...security.rate_limit import try_record_action
from ...services.postmortem import (
    PROMPT_VERSION,
    EvidenceEntry,
    bound_evidence_by_chars,
    build_draft_request,
    ground_draft,
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
    user: User = Depends(require_active_subscription),
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
    return dict(row or {})


@router.get("/incidents")
async def list_incidents(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> list[dict]:
    return await database.fetch_all(
        "SELECT id, title, severity, status FROM incidents WHERE client_email=%s ORDER BY created_at DESC",
        (user.email,),
    )


class IncidentStatusUpdate(BaseModel):
    status: str = Field(pattern="^(open|resolved)$")


@router.patch("/incidents/{incident_id}/status")
async def update_incident_status(
    incident_id: str,
    payload: IncidentStatusUpdate,
    database: Database = Depends(get_database),
    user: User = Depends(require_active_subscription),
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
                  count(*) FILTER (WHERE status = 'resolved') AS resolved
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
        "SELECT id, title, severity, status FROM incidents WHERE client_email=%s ORDER BY created_at DESC LIMIT 5",
        (user.email,),
    )
    return {
        "total_incidents": (incident_counts or {}).get("total", 0),
        "open_incidents": (incident_counts or {}).get("open", 0),
        "resolved_incidents": (incident_counts or {}).get("resolved", 0),
        "drafted_postmortems": (postmortem_counts or {}).get("drafted", 0),
        "published_postmortems": (postmortem_counts or {}).get("published", 0),
        "recent_incidents": recent_incidents,
    }


@router.post("/incidents/{incident_id}/evidence", status_code=status.HTTP_201_CREATED)
async def record_evidence(
    incident_id: str,
    payload: EvidenceCreate,
    database: Database = Depends(get_database),
    user: User = Depends(require_active_subscription),
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


@router.post("/incidents/{incident_id}/draft", status_code=status.HTTP_201_CREATED)
async def draft_postmortem(
    incident_id: str,
    database: Database = Depends(get_database),
    provider: ModelProvider = Depends(get_model_provider),
    user: User = Depends(require_active_subscription),
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
    except (httpx.HTTPError, genai_errors.APIError) as error:
        # httpx.HTTPError covers a generic ModelProvider's own request
        # failures; google.genai.errors.APIError is the Gemini SDK's own
        # common base (auth errors, rate limits, server errors) and is NOT a
        # subclass of httpx.HTTPError, so it needs its own catch -- this
        # codebase previously ran the same swap against Anthropic, where a
        # live smoke test against a real (invalid) API key surfaced an
        # uncaught 500 before the equivalent catch was added; added
        # proactively here rather than waiting to rediscover the same gap.
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
        for action in draft.actions:
            await tx.execute(
                """INSERT INTO postmortem_actions
                     (id,postmortem_id,title,rationale,owner,evidence_id,created_at,updated_at)
                   VALUES (gen_random_uuid(),%s,%s,%s,%s,%s,%s,%s)""",
                (postmortem_id, action.title, action.rationale, action.owner, action.evidence_id, now, now),
            )

    return await _load_postmortem(database, incident_id)


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
