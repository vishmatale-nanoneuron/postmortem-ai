"""Linear ticket creation via a client-provided personal API key -- no
OAuth app registration needed (a full public OAuth app, with a hosted
redirect URI and Linear's app review, is a much bigger lift and
deliberately deferred). Each account connects by pasting its own personal
API key (Linear -> Settings -> API -> Personal API keys) and team ID.
"""

import logging

import httpx

logger = logging.getLogger("postmortem_ai")

GRAPHQL_URL = "https://api.linear.app/graphql"

ISSUE_CREATE_MUTATION = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { id identifier url }
  }
}
"""


async def create_linear_issue(
    api_key: str | None, team_id: str | None, title: str, description: str
) -> dict | None:
    """Best-effort -- returns the created issue's {id, identifier, url} on
    success, or None on any failure/misconfiguration. Never raises: a
    failed ticket creation must never block or fail the postmortem publish
    that triggered it."""
    if not api_key or not team_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                GRAPHQL_URL,
                # Linear's personal API keys go directly in Authorization,
                # with no "Bearer " prefix -- verified against Linear's own
                # API docs, not assumed from a generic OAuth pattern.
                headers={"Authorization": api_key, "Content-Type": "application/json"},
                json={
                    "query": ISSUE_CREATE_MUTATION,
                    "variables": {"input": {"teamId": team_id, "title": title, "description": description}},
                },
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError:
        logger.warning("linear_issue_create_failed", exc_info=True)
        return None

    if not isinstance(body, dict):
        logger.warning("linear_issue_create_failed", extra={"reason": "non-dict response body"})
        return None
    if body.get("errors"):
        logger.warning("linear_issue_create_failed", extra={"errors": body["errors"]})
        return None

    # `.get("data", {})` looks like it defaults to {} on a missing key, but
    # a key present with an explicit `null` value (a real, adversarially-
    # tested case: `{"data": null}`) makes `.get` return None regardless
    # of the default, and .get() on None/a list crashes -- found via a
    # direct adversarial test against this function, not by inspection.
    # `or {}` catches both None and a missing key; the isinstance guard
    # catches Linear (or a hostile response) returning the wrong shape
    # entirely (e.g. issueCreate as a list).
    data = body.get("data") or {}
    result = data.get("issueCreate") if isinstance(data, dict) else None
    if not isinstance(result, dict) or not result.get("success"):
        return None
    return result.get("issue")
