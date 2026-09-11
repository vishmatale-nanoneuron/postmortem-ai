"""Pure-function tests for the Markdown export renderer -- no database."""

from app.services.postmortem_markdown import render_postmortem_markdown

INCIDENT = {"id": "inc-1", "title": "Checkout | latency", "severity": "sev2", "status": "resolved", "impact": "p99 up 4x"}
EVIDENCE = [
    {"id": "ev-a", "occurred_at": 1_757_500_000_000, "source": "alert", "summary": "CHK-LAT fired", "detail": None},
    {"id": "ev-b", "occurred_at": 1_757_500_600_000, "source": "deploy", "summary": "Release 1.2 | rolled out", "detail": "line one\nline two"},
]
POSTMORTEM = {
    "status": "published",
    "summary": "Latency rose after release 1.2.",
    "root_cause": "The new payment client slowed checkout.",
    "detection": "Alert CHK-LAT fired.",
    "resolution": "Rollback restored latency.",
    "contributing_factors": ["The release changed the payment client."],
    "cited_evidence_ids": ["ev-b"],
    "unsupported_claims_dropped": 3,
    "approved_by": "lead@example.com",
    "approved_at": 1_757_600_000_000,
    "actions": [
        {"title": "Load-test the client", "owner": "ops@example.com", "status": "open", "evidence_id": "ev-b", "rationale": "Reached prod undetected."},
        {"title": "Orphaned action", "owner": "", "status": "open", "evidence_id": "ev-gone", "rationale": ""},
    ],
}


def test_citations_resolve_to_evidence_numbers_and_never_dangle() -> None:
    text = render_postmortem_markdown(incident=INCIDENT, postmortem=POSTMORTEM, evidence=EVIDENCE, exported_at_ms=0)
    # Evidence is numbered in occurred_at order and the cited row is marked.
    assert "| 1 | 2025-09-10 10:26 UTC | alert | CHK-LAT fired |  |  |" in text
    assert "| 2 | 2025-09-10 10:36 UTC | deploy | Release 1.2 \\| rolled out | line one line two | yes |" in text
    # The action's evidence_id maps to that number; an id that no longer
    # exists renders as a dash, not as a marker pointing at nothing.
    assert "| Load-test the client | ops@example.com | open | [2] | Reached prod undetected. |" in text
    assert "| Orphaned action |  | open | -- |  |" in text
    assert "[None]" not in text and "[0]" not in text


def test_the_dropped_claim_count_and_approval_leave_with_the_document() -> None:
    text = render_postmortem_markdown(incident=INCIDENT, postmortem=POSTMORTEM, evidence=EVIDENCE, exported_at_ms=0)
    assert "**3** dropped" in text
    assert "| Approved by | lead@example.com, 2025-09-11 14:13 UTC |" in text
    assert "| Impact | p99 up 4x |" in text
    # Pipes in a title would split the table cell; they are escaped.
    assert text.startswith("# Postmortem: Checkout \\| latency\n")
    assert "Exported from PostMortem AI (https://www.nanoneuron.ai) on 1970-01-01 00:00 UTC." in text


def test_empty_sections_say_so_instead_of_disappearing() -> None:
    bare = {**POSTMORTEM, "root_cause": "", "contributing_factors": [], "actions": [], "approved_by": None}
    text = render_postmortem_markdown(incident={**INCIDENT, "impact": None}, postmortem=bare, evidence=[], exported_at_ms=0)
    assert "## Root cause\n\n_Not established by the recorded evidence._" in text
    assert "## Contributing factors\n\n_None established by the recorded evidence._" in text
    assert "## Action items\n\n_None drafted._" in text
    assert "## Evidence (0 entries)\n\n_No evidence recorded._" in text
    assert "| Approved by |" not in text and "| Impact |" not in text
