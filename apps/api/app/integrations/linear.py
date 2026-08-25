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

    if body.get("errors"):
        logger.warning("linear_issue_create_failed", extra={"errors": body["errors"]})
        return None

    result = body.get("data", {}).get("issueCreate", {})
    if not result.get("success"):
        return None
    return result.get("issue")
