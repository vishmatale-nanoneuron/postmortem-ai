"""Text embeddings for RAG retrieval -- deliberately separate from
ModelProvider (which is about drafting completions): embeddings are a
different capability with a different failure mode (a missing/failed
embedding should degrade retrieval gracefully, never block publishing a
postmortem), so they're not forced through the same Protocol.
"""

from google import genai

EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIMENSIONS = 768


async def embed_text(client: genai.Client, text: str) -> list[float]:
    response = await client.aio.models.embed_content(model=EMBEDDING_MODEL, contents=text)
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
