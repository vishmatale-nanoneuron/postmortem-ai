-- RAG for postmortem drafting: embeds each PUBLISHED postmortem's
-- summary + root cause, so drafting a new incident can retrieve similar
-- past incidents (same client only) as reference context. This is
-- deliberately scaffolding, not evidence: the grounding contract is
-- unchanged -- ground_draft() still only allows citations into the
-- CURRENT incident's own evidence, never into a retrieved similar past
-- postmortem. Retrieval informs the model's reasoning; it can never
-- become a citable source.
CREATE EXTENSION IF NOT EXISTS vector;

-- text-embedding-004's default output dimensionality.
ALTER TABLE public.incident_postmortems ADD COLUMN IF NOT EXISTS embedding vector(768);

-- ivfflat needs at least a few rows to build meaningful lists; harmless to
-- create early on an empty/small table (falls back to a sequential scan
-- until there's enough data, which is correct for a single-founder MVP's
-- likely data volume for a long while).
CREATE INDEX IF NOT EXISTS incident_postmortems_embedding_idx
    ON public.incident_postmortems USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
