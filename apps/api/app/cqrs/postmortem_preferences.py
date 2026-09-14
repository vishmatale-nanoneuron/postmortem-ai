"""Drafting style: PostMortem AI's per-account tuning, in context.

A team writes postmortems a particular way -- British spelling, a
one-paragraph root cause, action titles that start with a verb, "customer
facing" rather than "external". Two things carry that into the drafting
model for this account and no other:

- instructions: the team's own house-style text, bounded;
- an example: the account's most recent approved, published postmortem,
  shown as an example of how they write (on by default, switchable).

Both govern form only. The product's guarantee -- every claim cites
recorded evidence, anything unsupported is marked -- is enforced by
ground_draft after the model answers and is untouched here: an instruction
cannot add a fact, and the example is never citable (citations are checked
by index into this incident's evidence alone). Nothing trains a model.
"""

import re
import time
from dataclasses import dataclass

from ..database import Database

MAX_INSTRUCTIONS_CHARS = 1_500
# Each section of the example postmortem is cut here so the example stays a
# bounded cost on every draft, separate from the evidence budget.
MAX_EXAMPLE_SECTION_CHARS = 1_200

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class InvalidPreferences(ValueError):
    pass


@dataclass(frozen=True)
class DraftingPreferences:
    instructions: str
    use_published_example: bool
    updated_at: int | None
    # True while the account has never saved any (the defaults apply).
    default: bool


DEFAULTS = DraftingPreferences(instructions="", use_published_example=True, updated_at=None, default=True)


async def handle_preferences_query(database: Database, user_id: str) -> DraftingPreferences:
    row = await database.fetch_one(
        "SELECT instructions, use_published_example, updated_at FROM postmortem_drafting_preferences WHERE user_id=%s",
        (user_id,),
    )
    if row is None:
        return DEFAULTS
    return DraftingPreferences(
        instructions=row["instructions"],
        use_published_example=bool(row["use_published_example"]),
        updated_at=int(row["updated_at"]),
        default=False,
    )


@dataclass(frozen=True)
class SetPreferencesCommand:
    user_id: str
    instructions: str
    use_published_example: bool


def _clean(instructions: str) -> str:
    text = _CONTROL.sub("", instructions or "").strip()
    if len(text) > MAX_INSTRUCTIONS_CHARS:
        raise InvalidPreferences(f"instructions are limited to {MAX_INSTRUCTIONS_CHARS} characters")
    return text


async def handle_set_preferences(database: Database, command: SetPreferencesCommand) -> DraftingPreferences:
    instructions = _clean(command.instructions)
    now = int(time.time() * 1000)
    await database.execute(
        """INSERT INTO postmortem_drafting_preferences (user_id, instructions, use_published_example, updated_at)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (user_id) DO UPDATE SET
             instructions=excluded.instructions,
             use_published_example=excluded.use_published_example,
             updated_at=excluded.updated_at""",
        (command.user_id, instructions, command.use_published_example, now),
    )
    return DraftingPreferences(
        instructions=instructions, use_published_example=command.use_published_example, updated_at=now, default=False
    )


async def handle_clear_preferences(database: Database, user_id: str) -> DraftingPreferences:
    await database.execute("DELETE FROM postmortem_drafting_preferences WHERE user_id=%s", (user_id,))
    return DEFAULTS


async def handle_has_style_example_query(database: Database, client_email: str) -> bool:
    """Whether the account has an approved, published postmortem the example
    can be drawn from -- a boolean for the dashboard, not the row."""
    row = await database.fetch_one(
        """SELECT EXISTS(
             SELECT 1 FROM incident_postmortems p JOIN incidents i ON i.id = p.incident_id
             WHERE i.client_email = %s AND p.status = 'published' AND p.approved_by IS NOT NULL
           ) AS present""",
        (client_email,),
    )
    return bool(row and row["present"])


@dataclass(frozen=True)
class StyleExample:
    incident_title: str
    summary: str
    root_cause: str
    detection: str
    resolution: str
    contributing_factors: list[str]


async def handle_style_example_query(database: Database, client_email: str, exclude_incident_id: str) -> StyleExample | None:
    """The account's most recent approved, published postmortem -- text a
    human signed off on -- as the example of how this team writes. This
    account only; never the incident being drafted."""
    row = await database.fetch_one(
        """SELECT i.title, p.summary, p.root_cause, p.detection, p.resolution, p.contributing_factors
           FROM incident_postmortems p JOIN incidents i ON i.id = p.incident_id
           WHERE i.client_email = %s AND p.status = 'published' AND p.approved_by IS NOT NULL
             AND p.incident_id <> %s
           ORDER BY p.approved_at DESC NULLS LAST, p.updated_at DESC LIMIT 1""",
        (client_email, exclude_incident_id),
    )
    if row is None:
        return None
    cut = lambda text: (text or "")[:MAX_EXAMPLE_SECTION_CHARS]  # noqa: E731
    return StyleExample(
        incident_title=cut(row["title"]),
        summary=cut(row["summary"]),
        root_cause=cut(row["root_cause"]),
        detection=cut(row["detection"]),
        resolution=cut(row["resolution"]),
        contributing_factors=[cut(f) for f in (row["contributing_factors"] or [])][:5],
    )
