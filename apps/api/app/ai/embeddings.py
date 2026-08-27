"""Text embeddings for RAG retrieval -- deliberately separate from
ModelProvider (which is about drafting completions): embeddings are a
different capability with a different failure mode (a missing/failed
embedding should degrade retrieval gracefully, never block publishing a
postmortem), so they're not forced through the same Protocol.
"""

from google import genai
from google.genai import types

# text-embedding-004 was retired by Google (confirmed 2026-08-27 via a real
# production 404: "models/text-embedding-004 is not found ... or is not
# supported for embedContent"). gemini-embedding-001 is the replacement and
# defaults to 3072 dimensions, but the `incident_postmortems.embedding`
# column is a fixed vector(768) (migration 0009) -- output_dimensionality
# asks Gemini to return the smaller size directly rather than requiring a
# migration to widen the column.
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768


async def embed_text(client: genai.Client, text: str) -> list[float]:
    response = await client.aio.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
    )
    if not response.embeddings:
        raise ValueError("Gemini returned no embedding")
    values = response.embeddings[0].values
    if not values:
        raise ValueError("Gemini returned an empty embedding vector")
    return list(values)


def embedding_to_sql(embedding: list[float]) -> str:
    """pgvector's text input format -- passed as a plain string parameter
    and cast with ::vector in SQL, rather than pulling in a dedicated
    psycopg adapter package for one column."""
    return "[" + ",".join(repr(float(value)) for value in embedding) + "]"
