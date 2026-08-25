"""Retrieval for RAG: similar past PUBLISHED postmortems, scoped to the
same client only -- tenant isolation matters here exactly as much as
everywhere else in this codebase; retrieval must never surface another
account's incident history. See services/postmortem.py's SYSTEM_PROMPT
rule 5 and render_similar_postmortems for why what's retrieved here can
never become a citable claim.
"""

from functools import lru_cache

from google import genai

from ..database import Database
from ..services.postmortem import SimilarPostmortem
from .embeddings import embed_text, embedding_to_sql


@lru_cache
def _shared_embedding_client(api_key: str) -> genai.Client:
    # Cached per API key -- avoids constructing a new client (and its
    # underlying HTTP connection pool) on every single draft/publish call.
    return genai.Client(api_key=api_key)


def get_embedding_client(api_key: str) -> genai.Client:
    return _shared_embedding_client(api_key)


async def find_similar_postmortems(
    database: Database,
    client_email: str,
    embedding: list[float],
    exclude_incident_id: str,
    limit: int = 3,
) -> list[SimilarPostmortem]:
    rows = await database.fetch_all(
        """SELECT i.title, p.summary, p.root_cause
           FROM incident_postmortems p
           JOIN incidents i ON i.id = p.incident_id
           WHERE i.client_email = %s AND p.status = 'published' AND p.incident_id != %s
                 AND p.embedding IS NOT NULL
           ORDER BY p.embedding <=> %s::vector
           LIMIT %s""",
        (client_email, exclude_incident_id, embedding_to_sql(embedding), limit),
    )
    return [
        SimilarPostmortem(incident_title=row["title"], summary=row["summary"], root_cause=row["root_cause"])
        for row in rows
    ]


async def embed_and_store_postmortem(database: Database, api_key: str, postmortem_id: str, text: str) -> None:
    """Best-effort -- called after a successful publish. A failure here
    must never surface to the caller or undo the publish; it only means
    this one postmortem won't be retrievable as RAG context later."""
    client = get_embedding_client(api_key)
    embedding = await embed_text(client, text)
    await database.execute(
        "UPDATE incident_postmortems SET embedding = %s::vector WHERE id = %s",
        (embedding_to_sql(embedding), postmortem_id),
    )
