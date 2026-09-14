-- PostMortem AI drafting style: the in-context form of tuning, per account.
--
-- A team's house style -- how they phrase and structure a postmortem --
-- and whether one of their own published postmortems is shown to the
-- drafting model as an example of that style. Both govern form only. The
-- guarantee that every claim cites recorded evidence is enforced by code
-- after the model answers (services/postmortem.py: ground_draft) and is
-- untouched by anything here: a style instruction cannot add a fact, and
-- an example postmortem is never citable (citations are checked by index
-- into this incident's evidence alone).
--
-- Nothing here trains a model. The example is the account's own approved,
-- published postmortem, shown only on that account's drafts.
--
-- Cascades from users: erasure takes the preferences.

CREATE TABLE IF NOT EXISTS public.postmortem_drafting_preferences (
    user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    -- Free text, bounded by the API (1,500 characters).
    instructions text NOT NULL DEFAULT '',
    -- Show the most recent approved, published postmortem of this account
    -- as an example of its style. On by default once a row exists; an
    -- account with no row gets the same default.
    use_published_example boolean NOT NULL DEFAULT true,
    updated_at bigint NOT NULL
);
