import json
import time

import anthropic
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...ai.model_router import create_model_provider
from ...ai.provider import ModelProvider
from ...auth import User, current_user
from ...database import Database
from ...dependencies import get_database
from ...services.postmortem import (
    EvidenceEntry,
    build_draft_request,
    ground_draft,
    parse_model_json,
)
from ...settings import Settings, get_settings

router = APIRouter(prefix="/v1/postmortems", tags=["postmortems"])

# Evidence has no upper bound at the schema level, and every entry is
# rendered into a single prompt with no truncation of its own -- bounding
# here (not in render_evidence) keeps the most recent evidence, closest to
# resolution and most likely to describe root cause/recovery, rather than
# silently keeping only the oldest.
MAX_DRAFT_EVIDENCE_ENTRIES = 500


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
    user: User = Depends(current_user),
) -> dict[str, object]:
    incident_id = f"inc-{int(time.time() * 1000)}"
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


@router.post("/incidents/{incident_id}/evidence", status_code=status.HTTP_201_CREATED)
async def record_evidence(
    incident_id: str,
    payload: EvidenceCreate,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> dict[str, object]:
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
    user: User = Depends(current_user),
) -> dict[str, object]:
    """Build a review-ready draft from the recorded evidence.

    The model's answer is grounded before it is stored: any claim not supported
    by a cited evidence entry is replaced or removed, never kept. The result is
    always a draft -- publishing is a separate, human act.
    """
    incident = await require_incident(database, incident_id, user.email)
    evidence = await load_evidence(database, incident_id)
    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Record at least one piece of evidence before drafting a postmortem",
        )

    try:
        raw = await provider.complete(build_draft_request(dict(incident), evidence))
        response = parse_model_json(raw)
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The drafting model returned an unreadable response",
        ) from error
    except (httpx.HTTPError, anthropic.AnthropicError) as error:
        # httpx.HTTPError covers a generic ModelProvider's own request
        # failures; anthropic.AnthropicError is the Anthropic SDK's own
        # common base (auth errors, rate limits, connection failures) and
        # is NOT a subclass of httpx.HTTPError, so it needs its own catch --
        # confirmed by a live smoke test against a real (invalid) API key,
        # which surfaced as an uncaught 500 before this was added.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The drafting model is temporarily unavailable",
        ) from error

    draft = ground_draft(response, evidence)
    now = int(time.time() * 1000)

    async with database.transaction() as tx:
        postmortem = await tx.fetch_one(
            """INSERT INTO incident_postmortems
                 (id,incident_id,status,summary,root_cause,detection,resolution,
                  contributing_factors,cited_evidence_ids,unsupported_claims_dropped,
                  generated_by,created_at,updated_at)
               VALUES (gen_random_uuid(),%s,'draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (incident_id) DO UPDATE SET
                 status='draft', approved_by=NULL, approved_at=NULL,
                 summary=excluded.summary, root_cause=excluded.root_cause,
                 detection=excluded.detection, resolution=excluded.resolution,
                 contributing_factors=excluded.contributing_factors,
                 cited_evidence_ids=excluded.cited_evidence_ids,
                 unsupported_claims_dropped=excluded.unsupported_claims_dropped,
                 generated_by=excluded.generated_by, updated_at=excluded.updated_at
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
    user: User = Depends(current_user),
) -> dict[str, object]:
    await require_incident(database, incident_id, user.email)
    now = int(time.time() * 1000)
    updated = await database.execute(
        """UPDATE incident_postmortems
           SET status='published', approved_by=%s, approved_at=%s, updated_at=%s
           WHERE incident_id=%s""",
        (user.email, now, now, incident_id),
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No draft postmortem to publish")
    return await _load_postmortem(database, incident_id)


async def _load_postmortem(database: Database, incident_id: str) -> dict[str, object]:
    postmortem = await database.fetch_one(
        """SELECT id::text, status, summary, root_cause, detection, resolution,
                  contributing_factors, cited_evidence_ids, unsupported_claims_dropped,
                  approved_by, approved_at
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
