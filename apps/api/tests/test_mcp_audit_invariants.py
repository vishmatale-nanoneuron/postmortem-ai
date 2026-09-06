"""Structural guards on the agent-accountability audit trail.

Pure introspection -- deliberately no database and no `TEST_DATABASE_URL`
skip, unlike the rest of this suite, so these run everywhere including a
bare CI job. They protect an invariant that is otherwise only a naming
convention, which a code-review pass flagged as the one part of the
feature nothing would catch if a future change got it wrong.
"""

import inspect


def _rest_functions_taking_source() -> set[str]:
    """The REST-layer functions that write their own account_activity_log
    row with an explicit source. `source` is the reliable marker: a
    function only needs that parameter *because* mcp_server.py calls it
    directly and has to say the call came from an agent."""
    from app.api.v1 import postmortems as postmortem_routes

    found = set()
    for name, fn in vars(postmortem_routes).items():
        if not inspect.isfunction(fn):
            continue
        # log_activity is the writer itself, not a self-logging route.
        if name == "log_activity":
            continue
        if "source" in inspect.signature(fn).parameters:
            found.add(name)
    return found


def test_self_logged_tools_matches_the_routes_that_actually_self_log() -> None:
    """_audited() skips its own success logging for a hardcoded set of tool
    names, because those tools' underlying REST routes already log the
    action themselves -- logging again would double-count it. Nothing
    enforced that the set stayed in sync: add a third self-logging route,
    forget to list it here, and every call through it silently writes two
    rows, with no test failing. This makes that mismatch fail loudly.

    The mapping is deliberate rather than clever: an MCP tool named `x`
    calls the REST function `_x`, so stripping one leading underscore is
    the whole correspondence."""
    from app.mcp_server import _SELF_LOGGED_TOOLS

    expected = {name.lstrip("_") for name in _rest_functions_taking_source()}
    assert expected == _SELF_LOGGED_TOOLS, (
        "A REST route that self-logs is missing from _SELF_LOGGED_TOOLS (or vice versa). "
        f"routes-with-source={sorted(expected)} _SELF_LOGGED_TOOLS={sorted(_SELF_LOGGED_TOOLS)}"
    )


def test_source_is_never_reachable_from_an_http_request() -> None:
    """The security fix behind this: `source` must not be a parameter on
    any function FastAPI routes to. A plain-typed parameter with no
    Body(...) wrapper becomes a query parameter, which let any REST caller
    spoof ?source=mcp_agent and forge the audit trail. The public route
    functions must stay clean; only the private _-prefixed
    implementations, which are called directly in Python by
    mcp_server.py, may take it."""
    public_offenders = {name for name in _rest_functions_taking_source() if not name.startswith("_")}
    assert not public_offenders, (
        "These route-level functions accept `source`, making it settable via an HTTP query string: "
        f"{sorted(public_offenders)}. Move the parameter to a private _-prefixed implementation."
    )
