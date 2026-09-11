// The template itself, as plain Markdown, kept apart from the page so a test
// can import it without React and so the copy button and the rendered page
// are guaranteed to hand out the same text.
//
// Not named template.ts: inside an app route folder that is a reserved
// Next.js file (a route template component, like layout.tsx), and Next
// tried to render this module as one -- "Element type is invalid: got
// object" on every request to the page.
//
// The six sections marked "drafted" are exactly the six things the
// production drafter returns (apps/api/app/services/postmortem.py: summary,
// root_cause, detection, resolution, contributing_factors, and actions --
// each action a cited title, rationale and owner; the due date is not
// drafted). The rest -- impact, timeline, what went well, lessons -- are
// the author's own. That split is asserted by
// tests/postmortem-template.test.ts so the page's claim about which
// sections the tool fills can't drift from the backend. (The first version
// of this page left action items off the list; the code said otherwise.)

export const DRAFTED_SECTIONS = [
  "Summary",
  "Detection",
  "Root cause",
  "Contributing factors",
  "Resolution",
  "Action items",
] as const;

export const TEMPLATE_MARKDOWN = `# Incident postmortem: <one-line title>

| Field | Value |
|---|---|
| Severity | sev1 / sev2 / sev3 / sev4 |
| Impact started | YYYY-MM-DD HH:MM UTC |
| Impact ended | YYYY-MM-DD HH:MM UTC |
| Author | |
| Reviewers | |
| Status | draft / reviewed / published |

## Summary

Two to four sentences: what broke, who noticed, how long it lasted, how it
ended. Write this last, once the sections below are settled.

## Impact

What users and internal teams actually experienced. Use numbers only where
they were measured (error rate, share of requests, duration). Write
"not measured" rather than estimating.

## Timeline (UTC)

| Time | Source | What happened |
|---|---|---|
| | deploy / alert / log / metric / human note | |
| | | |

One row per event, and every row traceable to a recorded artifact: an alert,
a log line, a deploy, a message in the incident channel. Do not reconstruct
from memory afterwards.

## Detection

How the incident was noticed and how long after impact began. An alert, a
customer report, someone looking at a graph -- say which, and cite the
timeline row.

## Root cause

The condition that, had it been absent, would have meant no incident. Cite
the timeline rows or artifacts that establish it. If the evidence does not
establish it yet, write exactly:

> Not established by the recorded evidence.

and leave it. An honest gap is more useful than a plausible guess.

## Contributing factors

What made it worse, longer, or harder to see: a missing alert, a retry
storm, a stale runbook, a limit nobody knew about. One bullet each, each
cited.

-

## Resolution

What actually stopped the impact (rollback, config revert, failover) and at
what time. Keep this separate from the permanent fix, which belongs under
action items.

## Action items

| Action | Owner | Due | Ticket |
|---|---|---|---|
| | | | |

Every item has exactly one owner and a date. An action nobody owns will not
happen.

## What went well

-

## Lessons

-
`;
