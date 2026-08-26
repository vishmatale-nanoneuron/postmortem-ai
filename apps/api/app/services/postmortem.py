import json
import re
from dataclasses import dataclass

from ..ai.provider import ModelMessage, ModelRequest

UNSUPPORTED = "Not established by the recorded evidence."

# Bumped whenever SYSTEM_PROMPT changes meaningfully. Persisted on every
# incident_postmortems row (see 0004_ai_runs.sql's prompt_version column) so
# a future prompt change is traceable against which postmortems were
# drafted under which prompt -- not versioned for its own sake.
# v2 (this one) added the similar-past-incidents RAG section to the
# prompt; bumped because it changes what the model actually sees, even
# though the grounding contract (ground_draft) itself is untouched.
PROMPT_VERSION = "v2"

# Conservative character budget for the rendered evidence body sent to the
# model, independent of MAX_DRAFT_EVIDENCE_ENTRIES's row-count bound in
# apps/api/app/api/v1/postmortems.py. A single evidence entry can carry up
# to a 500-char summary + 4000-char detail (see EvidenceCreate), so even
# well under the 500-row count bound, total rendered size could still be
# large enough to be an expensive or unreliable request. ~40K characters is
# comfortably inside Gemini 2.5 Flash's context window while keeping a
# single drafting call cheap and fast.
MAX_EVIDENCE_CHARS = 40_000

# Two-layer defense, not one. This prompt asks the model to cite every claim
# and to treat an empty/uncited section as correct -- but the prompt is not
# what makes this trustworthy. ground_draft() below is the enforcement layer:
# it is code, not a request, and it can only ever remove or replace the
# model's own text, never add new text. A model that ignores every word of
# this prompt still cannot produce an invented, uncited claim that survives
# ground_draft.
SYSTEM_PROMPT = (
    "You draft incident postmortems for review by the engineering team that ran the "
    "incident. You are given numbered evidence entries. Follow these principles:\n"
    "1. Every statement you make must come from the numbered evidence. Cite the entries "
    "you used by number.\n"
    "2. If the evidence does not establish something, say so and cite nothing rather than "
    "inferring it. An empty, uncited section is the correct answer when the evidence "
    "doesn't support one -- it will be shown to the reviewer as unsupported, not treated "
    "as a failure on your part.\n"
    "3. Do not estimate cost, revenue or customer counts. Do not invent dates, deadlines or "
    "names that are not in the evidence.\n"
    "4. Do not recommend an action the evidence does not support.\n"
    "5. You may also be shown similar past incidents, clearly labeled as reference "
    "context. They are NOT evidence and are not numbered -- never cite them, never treat "
    "them as proof of anything about THIS incident. Use them only to inform how you phrase "
    "or investigate, never as a source for a claim.\n"
    "6. Reply with JSON only, matching this shape:\n"
    '{"summary": {"text": str, "citations": [int]},\n'
    ' "root_cause": {"text": str, "citations": [int]},\n'
    ' "detection": {"text": str, "citations": [int]},\n'
    ' "resolution": {"text": str, "citations": [int]},\n'
    ' "contributing_factors": [{"text": str, "citations": [int]}],\n'
    ' "actions": [{"title": str, "rationale": str, "owner": str, "citations": [int]}]}'
)

SECTIONS = ("summary", "root_cause", "detection", "resolution")


@dataclass(frozen=True)
class EvidenceEntry:
    id: str
    occurred_at: int
    source: str
    summary: str
    detail: str | None
    authorized_by: str


@dataclass(frozen=True)
class SimilarPostmortem:
    """A retrieved past incident for RAG context -- reference only, never
    citable (see SYSTEM_PROMPT rule 5 and ground_draft's docstring: citation
    validity is checked purely by index into `evidence`, so nothing here
    can become a citation no matter what the model outputs)."""

    incident_title: str
    summary: str
    root_cause: str


@dataclass(frozen=True)
class GroundedAction:
    title: str
    rationale: str
    owner: str
    evidence_id: str


@dataclass(frozen=True)
class GroundedDraft:
    summary: str
    root_cause: str
    detection: str
    resolution: str
    contributing_factors: list[str]
    actions: list[GroundedAction]
    cited_evidence_ids: list[str]
    unsupported_claims_dropped: int


# Bumped independently of PROMPT_VERSION (the drafting prompt) -- this is a
# separate model call with its own contract, not a variant of drafting.
EXTRACTION_PROMPT_VERSION = "extract-v1"

EVIDENCE_SOURCES = ("alert", "log", "deploy", "metric", "human_note", "customer_report")

# Same two-layer philosophy as SYSTEM_PROMPT/ground_draft above: this prompt
# asks the model to extract only what's actually stated, but the real
# guarantee is downstream -- extract_evidence_from_text() below never saves
# anything to the database itself. Every suggestion is returned to the
# client for a human to review, edit, or discard before it becomes a real
# evidence entry via the existing POST .../evidence endpoint, which is
# unchanged by this feature. This is assistive extraction, not autonomous
# recording.
EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured incident-evidence entries from raw, informal text (a Slack "
    "thread, a log excerpt, a string of notes). You are not drafting a postmortem and you "
    "must not summarize, interpret, or infer beyond what the text actually says.\n"
    "1. Extract only entries that are actually stated in the text. Do not invent entries, "
    "dates, names, or numbers that are not present.\n"
    "2. Each entry needs a `source` (one of: alert, log, deploy, metric, human_note, "
    "customer_report -- pick the closest match), a `summary` (a single factual sentence, "
    "under 200 characters), and an optional `detail` (additional specifics, if present in "
    "the text).\n"
    "3. If the text contains no extractable factual entries, return an empty list -- do not "
    "pad the output with invented content.\n"
    "4. Reply with JSON only, matching this shape:\n"
    '{"entries": [{"source": str, "summary": str, "detail": str | null}]}'
)


@dataclass(frozen=True)
class ExtractedEvidence:
    source: str
    summary: str
    detail: str | None


def build_extraction_request(raw_text: str, model: str | None = None) -> ModelRequest:
    return ModelRequest(
        messages=[ModelMessage(role="user", content=raw_text)],
        system=EXTRACTION_SYSTEM_PROMPT,
        model=model,
        max_tokens=2_048,
        temperature=0.1,
    )


def parse_extracted_evidence(response: dict) -> list[ExtractedEvidence]:
    """Same defense-in-depth shape as ground_draft: code, not the prompt, is
    what enforces the actual contract. Anything malformed is dropped rather
    than raised -- a partially-unreadable response should still surface
    whatever entries WERE well-formed, since this only ever produces
    editable suggestions, never a final record."""
    raw_entries = response.get("entries")
    if not isinstance(raw_entries, list):
        return []
    extracted: list[ExtractedEvidence] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        source = raw.get("source")
        summary = raw.get("summary")
        detail = raw.get("detail")
        if source not in EVIDENCE_SOURCES:
            continue
        if not isinstance(summary, str) or not summary.strip():
            continue
        if not (detail is None or isinstance(detail, str)):
            detail = None
        extracted.append(
            ExtractedEvidence(
                source=source,
                summary=summary.strip()[:500],
                detail=(detail.strip()[:4000] if isinstance(detail, str) and detail.strip() else None),
            )
        )
    return extracted


def render_evidence(evidence: list[EvidenceEntry]) -> str:
    lines = []
    for index, entry in enumerate(evidence, start=1):
        detail = f" -- {entry.detail}" if entry.detail else ""
        lines.append(
            f"[{index}] ({entry.source}, recorded by {entry.authorized_by}, "
            f"at {entry.occurred_at}) {entry.summary}{detail}"
        )
    return "\n".join(lines)


def bound_evidence_by_chars(evidence: list[EvidenceEntry], max_chars: int = MAX_EVIDENCE_CHARS) -> list[EvidenceEntry]:
    """Trim to the most recent entries whose rendered form fits max_chars.

    Same rationale as postmortems.py's row-count bound: keep the entries
    closest to resolution (most recent), not the oldest. Always keeps at
    least one entry, even if it alone exceeds the budget, so a single
    oversized entry can't block drafting entirely -- the caller still sees
    a real (possibly very large) request rather than a silent empty one.
    Callers must use the SAME returned list for both build_draft_request
    and ground_draft, since citation numbers are positional.
    """
    if not evidence:
        return evidence
    selected: list[EvidenceEntry] = []
    total = 0
    for entry in reversed(evidence):
        detail = f" -- {entry.detail}" if entry.detail else ""
        line = f"[i] ({entry.source}, recorded by {entry.authorized_by}, at {entry.occurred_at}) {entry.summary}{detail}"
        length = len(line) + 1
        if selected and total + length > max_chars:
            break
        selected.append(entry)
        total += length
    selected.reverse()
    return selected


def render_similar_postmortems(similar: list[SimilarPostmortem]) -> str:
    if not similar:
        return ""
    blocks = [
        f"- \"{item.incident_title}\": {item.summary} (root cause: {item.root_cause})" for item in similar
    ]
    return (
        "\n\nSimilar past incidents (reference only -- NOT evidence, not numbered, "
        "never cite these):\n" + "\n".join(blocks)
    )


def build_draft_request(
    incident: dict[str, object],
    evidence: list[EvidenceEntry],
    model: str | None = None,
    similar_past_incidents: list[SimilarPostmortem] | None = None,
) -> ModelRequest:
    body = (
        f"Incident: {incident.get('title')}\n"
        f"Severity: {incident.get('severity')}\n"
        f"Stated impact: {incident.get('impact')}\n\n"
        f"Evidence entries:\n{render_evidence(evidence)}"
        f"{render_similar_postmortems(similar_past_incidents or [])}"
    )
    return ModelRequest(
        messages=[ModelMessage(role="user", content=body)],
        system=SYSTEM_PROMPT,
        model=model,
        max_tokens=2_048,
        temperature=0.1,
    )


def parse_model_json(raw: str) -> dict:
    """Read the model's JSON, tolerating a ```json fence around it.

    A response that is not JSON at all raises, because silently continuing with
    an empty draft would look like "the evidence supported nothing" rather than
    "the model failed".
    """
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Model response was not a JSON object")
    return parsed


def _valid_citations(raw: object, count: int) -> list[int]:
    if not isinstance(raw, list):
        return []
    seen: set[int] = set()
    for item in raw:
        # bool is a subclass of int in Python -- exclude it explicitly, a
        # citation of `true`/`false` is not a real evidence index.
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        if 1 <= item <= count:
            seen.add(item)
    return sorted(seen)


def _claim(raw: object, count: int) -> tuple[str, list[int]]:
    if not isinstance(raw, dict):
        return "", []
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        return "", []
    return text.strip(), _valid_citations(raw.get("citations"), count)


def ground_draft(response: dict, evidence: list[EvidenceEntry]) -> GroundedDraft:
    """Keep only what the evidence supports.

    Anything whose citations are absent, out of range or non-numeric is dropped.
    The four required sections are replaced with UNSUPPORTED rather than removed,
    so a reviewer sees that the section was considered and found unsupported
    instead of silently missing.
    """
    count = len(evidence)
    dropped = 0
    cited: set[int] = set()
    sections: dict[str, str] = {}

    for name in SECTIONS:
        text, citations = _claim(response.get(name), count)
        if text and citations:
            sections[name] = text
            cited.update(citations)
        else:
            sections[name] = UNSUPPORTED
            if text:
                dropped += 1

    contributing_factors: list[str] = []
    for raw_factor in response.get("contributing_factors") or []:
        text, citations = _claim(raw_factor, count)
        if text and citations:
            contributing_factors.append(text)
            cited.update(citations)
        elif text:
            dropped += 1

    actions: list[GroundedAction] = []
    for raw_action in response.get("actions") or []:
        if not isinstance(raw_action, dict):
            continue
        title = raw_action.get("title")
        rationale = raw_action.get("rationale")
        owner = raw_action.get("owner")
        citations = _valid_citations(raw_action.get("citations"), count)
        has_text = all(isinstance(value, str) and value.strip() for value in (title, rationale, owner))
        if has_text and citations:
            cited.update(citations)
            actions.append(
                GroundedAction(
                    title=title.strip(),  # type: ignore[union-attr]
                    rationale=rationale.strip(),  # type: ignore[union-attr]
                    owner=owner.strip(),  # type: ignore[union-attr]
                    evidence_id=evidence[citations[0] - 1].id,
                )
            )
        elif has_text:
            dropped += 1

    return GroundedDraft(
        summary=sections["summary"],
        root_cause=sections["root_cause"],
        detection=sections["detection"],
        resolution=sections["resolution"],
        contributing_factors=contributing_factors,
        actions=actions,
        cited_evidence_ids=[evidence[i - 1].id for i in sorted(cited)],
        unsupported_claims_dropped=dropped,
    )
