# PagerDuty and Datadog webhook ingestion

Real setup paths for two monitoring vendors, added on top of the always-
available generic webhook (`POST /v1/webhooks/incidents/{token}`, see
`apps/api/app/api/v1/webhooks.py`). Written up here because the two vendors
needed genuinely different treatment, and because the field names below
were sourced from public documentation rather than a live test account —
worth being explicit about exactly what that basis is.

## PagerDuty (`POST /v1/webhooks/pagerduty/{token}`)

PagerDuty's v3 webhook subscriptions send one fixed JSON envelope that
can't be customized — only which event types you subscribe to is
configurable, not the payload shape. That makes a real adapter possible:
`apps/api/app/api/v1/webhooks.py`'s `receive_pagerduty_webhook` parses it
directly.

Field names used (`event.event_type`, `event.occurred_at`,
`event.data.id`/`title`/`urgency`/`html_url`) are corroborated across two
independent sources, not a single guess:

- PagerDuty's own v3 webhook documentation:
  https://developer.pagerduty.com/docs/db0fa8c8984fc-overview (the actual
  page content wasn't fetchable at write time — it appears to render via
  client-side JS — so this is cited as the canonical source, not as a page
  this was verified against directly)
- Sumo Logic's PagerDuty V3 integration guide, which independently
  documents the same field names when describing how it consumes
  PagerDuty v3 webhooks:
  https://www.sumologic.com/help/docs/integrations/saas-cloud/pagerduty-v3/

This was **not** tested against a live PagerDuty account or a captured
real payload — the parsing in `receive_pagerduty_webhook` is deliberately
defensive (every field read with `.get()`, never indexed, missing/renamed
fields degrade to "ignore this event" rather than an error) specifically
because of that. If a real PagerDuty payload is ever captured and a field
name turns out to be wrong, fix the parsing and add the real payload as a
test fixture — don't just patch the field name from memory again.

Handled event types: `incident.triggered` (creates an incident),
`incident.acknowledged` and `incident.resolved` (find the existing
incident by PagerDuty's own incident id, stored in `incidents.external_id`
— migration `0025_incident_external_id.sql`; `incident.resolved` also
closes it). Any other event type gets a `200` with
`{"status": "ignored"}` rather than an error, because PagerDuty disables a
webhook subscription after enough non-2xx responses and there's no
per-event-type filter in its subscription config — filtering has to
happen on this side.

Urgency (`high`/`low` — PagerDuty's only two levels) maps to this app's
`sev2`/`sev4`; there's no finer split to map onto a middle severity
honestly, so this is a conservative two-point mapping, not a guess at a
four-point one.

## Datadog (no adapter — a payload template)

Datadog's webhook integration has **no fixed payload schema of its own**:
the JSON body is written by the person configuring the integration, using
Datadog's own template variables (`$EVENT_TITLE`, `$EVENT_MSG`,
`$LAST_UPDATED`, etc.) — confirmed from Datadog's own webhook docs
(https://docs.datadoghq.com/integrations/webhooks/), which state the user
"must specify your own payload in the Payload field."

That means there's nothing to write a parser against — the real
integration is a template that already matches this app's generic
webhook shape, pointed at `/v1/webhooks/incidents/{token}` directly
(shown in the app's own webhook settings, `WebhookSettings` in
`apps/web/app/workspace.tsx`):

```json
{
  "source": "alert",
  "summary": "$EVENT_TITLE",
  "detail": "$EVENT_MSG",
  "occurred_at": $LAST_UPDATED,
  "title": "$EVENT_TITLE"
}
```

`$LAST_UPDATED` is already documented by Datadog as epoch milliseconds,
which is exactly this app's own `occurred_at` unit — no conversion
needed.

**Known limitation, stated rather than glossed over**: there's no way to
carry this app's dynamically assigned incident id back into a static
Datadog payload template, so each Datadog alert creates its own new
incident rather than grouping into one the way a caller who remembers
`incident_id` can (the generic endpoint) or the way PagerDuty's adapter
does (via its own stable incident id). Auto-resolve isn't supported for
Datadog for the same reason. Fixing this for real would need either a
small proxy that holds per-Datadog-monitor state, or Datadog gaining a
way to template a value back into a *stored* variable across calls to the
same monitor — neither exists today, so it isn't claimed anywhere in this
app's docs or landing copy.
