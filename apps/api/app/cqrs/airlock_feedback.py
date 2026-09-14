"""Tuning feedback: the customer's corrections, and what they tune.

A report says "this verdict was wrong, it should have been X". Reports
are the account's own tuning data, in three forms:

- suggestions: rules that keep producing reported false positives on this
  account become "mute this rule" suggestions (applied through the policy
  in one call); reported misses become "use the deep scan for this source"
  suggestions. Each carries the count behind it, so the dashboard shows
  evidence, not advice.
- an export: the reports the customer chose to include content for, in
  the same supervised-tuning format scripts/airlock_finetune_dataset.py
  writes, so a customer tuning their own classifier gets their own labelled
  examples out.
- the engine's signal: across accounts, the founder sees how often each
  rule is reported as a false positive -- counts only, never content --
  which is where a rule's weight or pattern gets changed, benchmarked
  before it ships.

Content is stored only when the report includes it; the privacy policy's
"scans are not kept" holds for everything else.
"""

import json
import time
from dataclasses import dataclass, field

from ..airlock.rules import RULES_BY_ID
from ..database import Database

MAX_NOTE_CHARS = 500
MAX_CONTENT_CHARS = 50_000
MAX_REPORTS_LISTED = 200
# A rule is suggested for muting once this many distinct reports on the
# account name it as a false positive. One report is a disagreement; three
# is a pattern.
MUTE_SUGGESTION_THRESHOLD = 3
DEEP_SCAN_SUGGESTION_THRESHOLD = 2
# The source the website's own try-it box sends. It is not a customer's
# pipeline, so a "use the deep scan for this source" suggestion about it
# would be advice about a page, not their integration.
DASHBOARD_SOURCES = frozenset({"playground"})


class InvalidFeedback(ValueError):
    pass


@dataclass(frozen=True)
class RecordFeedbackCommand:
    user_id: str
    content_sha256: str
    kind: str
    verdict_given: str
    verdict_expected: str
    rule_ids: list[str] = field(default_factory=list)
    source: str | None = None
    note: str | None = None
    content: str | None = None


VERDICTS = ("allow", "flag", "block")


def _validate(command: RecordFeedbackCommand) -> list[str]:
    if command.kind not in ("ingress", "egress"):
        raise InvalidFeedback("kind must be ingress or egress")
    if command.verdict_given not in VERDICTS or command.verdict_expected not in VERDICTS:
        raise InvalidFeedback("verdicts must be allow, flag or block")
    if command.verdict_given == command.verdict_expected:
        raise InvalidFeedback("verdict_expected must differ from verdict_given -- a report says the guard was wrong")
    if not (len(command.content_sha256) == 64 and all(c in "0123456789abcdef" for c in command.content_sha256.lower())):
        raise InvalidFeedback("content_sha256 must be the 64-hex hash the scan response carried")
    if command.note and len(command.note) > MAX_NOTE_CHARS:
        raise InvalidFeedback(f"note is limited to {MAX_NOTE_CHARS} characters")
    if command.content is not None and len(command.content) > MAX_CONTENT_CHARS:
        raise InvalidFeedback(f"content is limited to {MAX_CONTENT_CHARS} characters")
    rules = sorted({r.strip().upper() for r in command.rule_ids if r and r.strip()})
    unknown = [r for r in rules if r not in RULES_BY_ID and r != "AI-001"]
    if unknown:
        raise InvalidFeedback(f"Unknown rule id(s): {', '.join(unknown[:5])}")
    return rules


async def handle_record_feedback(database: Database, command: RecordFeedbackCommand) -> str:
    rules = _validate(command)
    row = await database.fetch_one(
        """INSERT INTO airlock_feedback
             (user_id, content_sha256, kind, verdict_given, verdict_expected, rule_ids, source, note, content, created_at)
           VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s) RETURNING id::text""",
        (
            command.user_id,
            command.content_sha256.lower(),
            command.kind,
            command.verdict_given,
            command.verdict_expected,
            json.dumps(rules),
            (command.source or None) and command.source[:64],
            (command.note or None) and command.note.strip()[:MAX_NOTE_CHARS],
            command.content,
            int(time.time() * 1000),
        ),
    )
    return row["id"]


@dataclass(frozen=True)
class FeedbackReport:
    id: str
    content_sha256: str
    kind: str
    verdict_given: str
    verdict_expected: str
    rule_ids: list[str]
    source: str | None
    note: str | None
    has_content: bool
    created_at: int


async def handle_feedback_query(database: Database, user_id: str) -> list[FeedbackReport]:
    rows = await database.fetch_all(
        """SELECT id::text, content_sha256, kind, verdict_given, verdict_expected, rule_ids, source, note,
                  (content IS NOT NULL) AS has_content, created_at
           FROM airlock_feedback WHERE user_id=%s ORDER BY created_at DESC LIMIT %s""",
        (user_id, MAX_REPORTS_LISTED),
    )
    return [FeedbackReport(**{**row, "rule_ids": list(row["rule_ids"] or [])}) for row in rows]


async def handle_delete_feedback(database: Database, user_id: str, feedback_id: str) -> bool:
    return (await database.execute("DELETE FROM airlock_feedback WHERE id=%s AND user_id=%s", (feedback_id, user_id))) > 0


@dataclass(frozen=True)
class Suggestion:
    # "mute_rule" | "deep_scan_source"
    kind: str
    rule_id: str | None
    source: str | None
    reports: int
    detail: str


async def handle_suggestions_query(database: Database, user_id: str, muted: tuple[str, ...] = ()) -> list[Suggestion]:
    """What this account's reports say to change. Only rules not already
    muted are suggested; a rule reported as a false positive across enough
    distinct scans is a pattern, one report is not."""
    rows = await database.fetch_all(
        """SELECT verdict_given, verdict_expected, rule_ids, source, content_sha256
           FROM airlock_feedback WHERE user_id=%s""",
        (user_id,),
    )
    false_positive_rules: dict[str, set[str]] = {}
    missed_sources: dict[str, set[str]] = {}
    for row in rows:
        stricter_given = VERDICTS.index(row["verdict_given"]) > VERDICTS.index(row["verdict_expected"])
        if stricter_given:
            for rule_id in row["rule_ids"] or []:
                if rule_id in RULES_BY_ID and rule_id not in muted:
                    false_positive_rules.setdefault(rule_id, set()).add(row["content_sha256"])
        elif row["source"] not in DASHBOARD_SOURCES:
            # A deep-scan suggestion is about a source in the customer's own
            # pipeline; the dashboard's try-it box is not one.
            missed_sources.setdefault(row["source"] or "(unlabelled)", set()).add(row["content_sha256"])

    suggestions: list[Suggestion] = []
    for rule_id, hashes in sorted(false_positive_rules.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(hashes) >= MUTE_SUGGESTION_THRESHOLD:
            suggestions.append(
                Suggestion(
                    kind="mute_rule",
                    rule_id=rule_id,
                    source=None,
                    reports=len(hashes),
                    detail=f"{rule_id} ({RULES_BY_ID[rule_id].family}) was reported as a false positive on {len(hashes)} distinct scans: "
                    f"{RULES_BY_ID[rule_id].description} Muting it applies to every key on this account.",
                )
            )
    for source, hashes in sorted(missed_sources.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(hashes) >= DEEP_SCAN_SUGGESTION_THRESHOLD:
            suggestions.append(
                Suggestion(
                    kind="deep_scan_source",
                    rule_id=None,
                    source=source,
                    reports=len(hashes),
                    detail=f"{len(hashes)} distinct scans from source '{source}' were reported as missed injections. "
                    "The rules match fixed phrasings; for this source, send \"deep\": true so the model reads the paraphrases.",
                )
            )
    return suggestions


async def handle_feedback_examples_query(database: Database, user_id: str, *, newest: int | None = None) -> list[dict]:
    """The consented examples (reports that include content) as tuning
    rows: the same shape scripts/airlock_finetune_dataset.py writes, so the
    customer's export drops straight into the same tuning job. Oldest first
    for the export; `newest=n` returns the n most recent, newest first, for
    the deep scan's in-context tuning (airlock/semantic.py)."""
    if newest is None:
        rows = await database.fetch_all(
            """SELECT content, verdict_expected, rule_ids, source, created_at
               FROM airlock_feedback WHERE user_id=%s AND content IS NOT NULL AND kind='ingress'
               ORDER BY created_at""",
            (user_id,),
        )
    else:
        rows = await database.fetch_all(
            """SELECT content, verdict_expected, rule_ids, source, created_at
               FROM airlock_feedback WHERE user_id=%s AND content IS NOT NULL AND kind='ingress'
               ORDER BY created_at DESC LIMIT %s""",
            (user_id, newest),
        )
    examples = []
    for row in rows:
        injection = row["verdict_expected"] != "allow"
        families = [RULES_BY_ID[r].family for r in (row["rule_ids"] or []) if r in RULES_BY_ID]
        examples.append(
            {
                "text": row["content"],
                "label": 1 if injection else 0,
                "family": families[0] if (injection and families) else None,
                "source": row["source"],
                "created_at": int(row["created_at"]),
            }
        )
    return examples


@dataclass(frozen=True)
class RuleFeedbackStat:
    rule_id: str
    family: str
    false_positive_reports: int
    accounts: int


async def handle_rule_feedback_stats_query(database: Database, *, days: int = 90) -> list[RuleFeedbackStat]:
    """Founder view: which rules customers keep reporting as false
    positives, across accounts. Counts only -- no content, no account --
    the signal for reweighting a rule in rules.py."""
    since = int(time.time() * 1000) - days * 24 * 60 * 60 * 1000
    rows = await database.fetch_all(
        """SELECT rule AS rule_id, count(*)::int AS false_positive_reports, count(DISTINCT user_id)::int AS accounts
           FROM airlock_feedback, jsonb_array_elements_text(rule_ids) AS rule
           WHERE created_at > %s
             AND array_position(ARRAY['allow','flag','block'], verdict_given) > array_position(ARRAY['allow','flag','block'], verdict_expected)
           GROUP BY rule ORDER BY false_positive_reports DESC, rule LIMIT 50""",
        (since,),
    )
    return [
        RuleFeedbackStat(
            rule_id=row["rule_id"],
            family=RULES_BY_ID[row["rule_id"]].family if row["rule_id"] in RULES_BY_ID else "",
            false_positive_reports=row["false_positive_reports"],
            accounts=row["accounts"],
        )
        for row in rows
    ]
