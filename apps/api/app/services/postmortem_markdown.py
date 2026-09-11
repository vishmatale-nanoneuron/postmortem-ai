"""Renders one postmortem as a Markdown document.

The postmortem's real destination is the team's wiki, not this product's
dashboard -- every incident-management tool this competes with exports for
that reason. This is the shape the public /postmortem-template page hands
out, filled in, so a team that already uses the template gets a document in
the same structure.

Pure function over already-loaded rows; no database access here so it can
be tested without one. Two properties the route's tests pin:

- Citations resolve. `cited_evidence_ids` and each action's `evidence_id`
  are database ids, not the [n] numbers the model cited. The evidence
  section numbers every entry, and every reference elsewhere in the file
  maps an id to that number -- a marker that points at nothing never gets
  emitted; an unresolvable id renders as a dash instead.
- The count of unsupported claims the model dropped is in the document.
  It is the one line that says what kind of document this is, and it
  should leave the product with the text rather than stay behind in a
  dashboard nobody at the wiki will ever see.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

_SEVERITY_LABELS = {"sev1": "Sev 1", "sev2": "Sev 2", "sev3": "Sev 3", "sev4": "Sev 4"}


def _cell(value: object) -> str:
    """One table cell: no pipes (they would split the cell), no newlines
    (they would end the row), and never the literal 'None'."""
    if value is None:
        return ""
    return " ".join(str(value).split()).replace("|", "\\|")


def _utc(epoch_ms: object) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(epoch_ms) / 1000))
    except (TypeError, ValueError, OverflowError):
        return ""


def _paragraph(text: object) -> str:
    stripped = str(text or "").strip()
    return stripped if stripped else "_Not established by the recorded evidence._"


def render_postmortem_markdown(
    *,
    incident: dict,
    postmortem: dict,
    evidence: Iterable[dict],
    exported_at_ms: int | None = None,
) -> str:
    evidence_rows = list(evidence)
    number_by_id = {str(row["id"]): index for index, row in enumerate(evidence_rows, start=1)}
    cited = {str(value) for value in (postmortem.get("cited_evidence_ids") or [])}

    def ref(evidence_id: object) -> str:
        number = number_by_id.get(str(evidence_id)) if evidence_id is not None else None
        return f"[{number}]" if number else "--"

    lines: list[str] = []
    lines.append(f"# Postmortem: {_cell(incident.get('title')) or incident.get('id')}")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    severity = str(incident.get("severity") or "")
    lines.append(f"| Severity | {_cell(_SEVERITY_LABELS.get(severity, severity))} |")
    lines.append(f"| Incident status | {_cell(incident.get('status'))} |")
    lines.append(f"| Postmortem status | {_cell(postmortem.get('status'))} |")
    if postmortem.get("approved_by"):
        lines.append(f"| Approved by | {_cell(postmortem.get('approved_by'))}, {_utc(postmortem.get('approved_at'))} |")
    if incident.get("impact"):
        lines.append(f"| Impact | {_cell(incident.get('impact'))} |")
    lines.append("")

    for heading, key in (("Summary", "summary"), ("Detection", "detection"), ("Root cause", "root_cause")):
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(_paragraph(postmortem.get(key)))
        lines.append("")

    lines.append("## Contributing factors")
    lines.append("")
    factors = [str(f).strip() for f in (postmortem.get("contributing_factors") or []) if str(f).strip()]
    if factors:
        lines.extend(f"- {factor}" for factor in factors)
    else:
        lines.append("_None established by the recorded evidence._")
    lines.append("")

    lines.append("## Resolution")
    lines.append("")
    lines.append(_paragraph(postmortem.get("resolution")))
    lines.append("")

    lines.append("## Action items")
    lines.append("")
    actions = list(postmortem.get("actions") or [])
    if actions:
        lines.append("| Action | Owner | Status | Evidence | Rationale |")
        lines.append("|---|---|---|---|---|")
        for action in actions:
            lines.append(
                f"| {_cell(action.get('title'))} | {_cell(action.get('owner'))} | {_cell(action.get('status'))}"
                f" | {ref(action.get('evidence_id'))} | {_cell(action.get('rationale'))} |"
            )
    else:
        lines.append("_None drafted._")
    lines.append("")

    lines.append(f"## Evidence ({len(evidence_rows)} entries)")
    lines.append("")
    if evidence_rows:
        lines.append("| # | Time | Source | Summary | Detail | Cited |")
        lines.append("|---|---|---|---|---|---|")
        for index, row in enumerate(evidence_rows, start=1):
            mark = "yes" if str(row["id"]) in cited else ""
            lines.append(
                f"| {index} | {_utc(row.get('occurred_at'))} | {_cell(row.get('source'))} | {_cell(row.get('summary'))}"
                f" | {_cell(row.get('detail'))} | {mark} |"
            )
    else:
        lines.append("_No evidence recorded._")
    lines.append("")

    dropped = int(postmortem.get("unsupported_claims_dropped") or 0)
    lines.append("---")
    lines.append("")
    lines.append(
        f"Every statement above was drafted from the numbered evidence and cites it; "
        f"entries marked *Cited* were used by the draft. "
        f"Claims the model attempted that the evidence did not support were removed rather than kept: "
        f"**{dropped}** dropped."
    )
    stamp = _utc(exported_at_ms if exported_at_ms is not None else int(time.time() * 1000))
    lines.append("")
    lines.append(f"Exported from PostMortem AI (https://www.nanoneuron.ai) on {stamp}.")
    lines.append("")
    return "\n".join(lines)
