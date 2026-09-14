"""Drafting style: PostMortem AI's per-account, in-context tuning.

Pinned: preferences round-trip (defaults until saved, bounded, cleared);
an account with nothing saved sends the published prompt byte for byte;
saved instructions and the account's own approved, published postmortem
reach the drafting model's system prompt -- never the user turn the
citations index into -- and the draft records "v4+style"; the example is
never the incident being drafted and never another account's; the
published example can be switched off; and a style instruction cannot add
a fact: an uncited claim the style asked for is still dropped.
"""

import json
import time

import pytest

# The drafting fixture (fake model, seeded incident, active subscription)
# is the routes file's; importing it registers it here under its own
# name, which is why the test signatures below "redefine" it (F811).
# ruff: noqa: F811
from .test_postmortem_routes import CLIENT_EMAIL, GOOD_RESPONSE, INCIDENT, context, pytestmark, seed_two_entries  # noqa: F401

STYLE = "British spelling. Root cause in one paragraph. Action titles start with a verb."


@pytest.mark.asyncio
async def test_preferences_round_trip_and_bounds(context) -> None:
    from app.cqrs.postmortem_preferences import MAX_INSTRUCTIONS_CHARS

    client, _, database, _ = context
    initial = await client.get("/v1/postmortems/preferences")
    assert initial.status_code == 200, initial.text
    assert initial.json() == {
        "instructions": "",
        "use_published_example": True,
        "updated_at": None,
        "default": True,
        "has_published_example": False,
    }

    saved = await client.put(
        "/v1/postmortems/preferences", json={"instructions": f"  {STYLE}\x00 ", "use_published_example": False}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["instructions"] == STYLE and saved.json()["use_published_example"] is False
    assert saved.json()["default"] is False and saved.json()["updated_at"] is not None
    assert (await client.get("/v1/postmortems/preferences")).json()["instructions"] == STYLE

    too_long = await client.put("/v1/postmortems/preferences", json={"instructions": "x" * (MAX_INSTRUCTIONS_CHARS + 1)})
    assert too_long.status_code == 422

    cleared = await client.delete("/v1/postmortems/preferences")
    assert cleared.status_code == 200 and cleared.json()["default"] is True

    client.cookies.clear()
    assert (await client.get("/v1/postmortems/preferences")).status_code == 401


@pytest.mark.asyncio
async def test_house_style_reaches_the_system_prompt_and_is_recorded_on_the_draft(context) -> None:
    from app.services.postmortem import PROMPT_VERSION, SYSTEM_PROMPT

    client, provider, database, _ = context
    await seed_two_entries(client)

    # Nothing saved, nothing published: the published prompt, byte for byte.
    first = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert first.status_code == 201, first.text
    assert provider.last_request.system == SYSTEM_PROMPT
    assert first.json()["prompt_version"] == PROMPT_VERSION

    # Instructions saved: they ride in the system prompt, never the user turn.
    assert (await client.put("/v1/postmortems/preferences", json={"instructions": STYLE})).status_code == 200
    second = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert second.status_code == 201, second.text
    system = provider.last_request.system
    assert system.startswith(SYSTEM_PROMPT) and "<house_style>" in system and STYLE in system
    assert STYLE not in provider.last_request.messages[0].content
    assert "<example_postmortem" not in system, "nothing published yet, so no example"
    assert second.json()["prompt_version"] == f"{PROMPT_VERSION}+style"
    run = await database.fetch_one(
        "SELECT prompt_version FROM ai_runs WHERE incident_id=%s ORDER BY created_at DESC LIMIT 1", (INCIDENT,)
    )
    assert run["prompt_version"] == f"{PROMPT_VERSION}+style"
    row = await database.fetch_one("SELECT prompt_version FROM incident_postmortems WHERE incident_id=%s", (INCIDENT,))
    assert row["prompt_version"] == f"{PROMPT_VERSION}+style"


@pytest.mark.asyncio
async def test_the_example_is_this_accounts_published_postmortem_never_the_incident_itself(context) -> None:
    from app.services.postmortem import PROMPT_VERSION, SYSTEM_PROMPT

    client, provider, database, _ = context
    await seed_two_entries(client)
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert (await client.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")).status_code == 200
    assert (await client.get("/v1/postmortems/preferences")).json()["has_published_example"] is True

    other = "pm-incident-style-2"
    await database.execute("DELETE FROM incidents WHERE id=%s", (other,))
    now = int(time.time() * 1000)
    await database.execute(
        """INSERT INTO incidents (id, client_email, title, severity, status, impact, created_at, updated_at)
           VALUES (%s, %s, 'A different outage', 'sev2', 'open', 'Some users', %s, %s)""",
        (other, CLIENT_EMAIL, now, now),
    )
    assert (
        await client.post(
            f"/v1/postmortems/incidents/{other}/evidence",
            json={"occurred_at": 2_000, "source": "alert", "summary": "A different alert fired", "detail": None},
        )
    ).status_code == 201

    # A later incident: the published postmortem is the example, in the
    # system prompt, marked never-cite; the evidence turn is untouched.
    draft = await client.post(f"/v1/postmortems/incidents/{other}/draft")
    assert draft.status_code == 201, draft.text
    system = provider.last_request.system
    assert system.startswith(SYSTEM_PROMPT) and "<example_postmortem" in system and "never cite" in system
    assert GOOD_RESPONSE["root_cause"]["text"] in system
    assert GOOD_RESPONSE["root_cause"]["text"] not in provider.last_request.messages[0].content.split("Similar past incidents")[0]
    assert draft.json()["prompt_version"] == f"{PROMPT_VERSION}+style"

    # Re-drafting the published incident itself: it is not its own example
    # (and re-drafting returns it to a draft, so nothing is published after).
    redraft = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert redraft.status_code == 201, redraft.text
    assert "<example_postmortem" not in provider.last_request.system
    assert redraft.json()["prompt_version"] == PROMPT_VERSION
    assert (await client.get("/v1/postmortems/preferences")).json()["has_published_example"] is False

    # Switched off: the bare prompt again even once something is published.
    assert (await client.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")).status_code == 200
    assert (await client.put("/v1/postmortems/preferences", json={"use_published_example": False})).status_code == 200
    again = await client.post(f"/v1/postmortems/incidents/{other}/draft")
    assert again.status_code == 201 and provider.last_request.system == SYSTEM_PROMPT
    assert again.json()["prompt_version"] == PROMPT_VERSION

    # Another account never sees it.
    from app.cqrs.postmortem_preferences import handle_style_example_query

    assert await handle_style_example_query(database, "someone-else@example.com", "") is None
    await database.execute("DELETE FROM incidents WHERE id=%s", (other,))


@pytest.mark.asyncio
async def test_a_style_instruction_cannot_add_a_fact(context) -> None:
    """The guarantee is code after the model: an instruction like "always
    state the revenue impact" can make the model write it, and ground_draft
    still drops it when it is uncited -- the style tunes form, not facts."""
    from app.services.postmortem import UNSUPPORTED

    client, provider, _, _ = context
    await seed_two_entries(client)
    assert (
        await client.put("/v1/postmortems/preferences", json={"instructions": "Always state the revenue impact in the summary."})
    ).status_code == 200
    provider.response = {
        **GOOD_RESPONSE,
        "summary": {"text": "Revenue impact was $40,000.", "citations": []},
        "actions": [{"title": "Refund customers", "rationale": "Revenue was lost.", "owner": "cfo", "citations": []}],
    }
    draft = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert draft.status_code == 201, draft.text
    body = draft.json()
    assert body["summary"] == UNSUPPORTED and body["unsupported_claims_dropped"] >= 1
    assert all("Refund" not in json.dumps(a) for a in body.get("actions", []))
