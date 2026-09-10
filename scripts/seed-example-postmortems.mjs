#!/usr/bin/env bun
/**
 * Seeds public example postmortems by driving the real product API -- login,
 * create incident, record evidence, draft, approve/publish, make public.
 *
 * Why this exists: /postmortems is empty, so a prospect evaluating the product
 * cannot see what its output actually looks like, and there is nothing
 * substantive for search engines or AI assistants to index. Hand-writing
 * marketing pages would not fix that, because the point is to show what the
 * *pipeline* produces.
 *
 * Every evidence entry below is a verbatim line from a published, public
 * incident writeup, with the source URL carried in `detail`. Nothing is
 * summarised from memory. That is not fussiness -- this product's core promise
 * is that claims are cited or dropped, so a demo built on paraphrase would be
 * a demo of the opposite.
 *
 * These are ANALYSES OF PUBLIC INCIDENTS by other companies, grounded in and
 * linked to those companies' own published postmortems. The titles say so
 * explicitly. Nothing here implies those companies are customers of this
 * product, and nothing is presented as their own writeup.
 *
 * Usage:
 *   SEED_EMAIL=you@example.com SEED_PASSWORD=... bun run scripts/seed-example-postmortems.mjs
 *   # ^ dry run: prints exactly what it would create, writes nothing
 *
 *   SEED_EMAIL=... SEED_PASSWORD=... bun run scripts/seed-example-postmortems.mjs --apply
 *   # ^ the irreversible one: creates real incidents and PUBLIC pages
 *
 * Requires an account with an ACTIVE SUBSCRIPTION -- publish_postmortem is
 * gated behind require_active_subscription, and drafting spends real AI credit.
 */

const API_BASE = process.env.API_BASE ?? "https://postmortem-ai-api.vercel.app";
const EMAIL = process.env.SEED_EMAIL;
const PASSWORD = process.env.SEED_PASSWORD;
const APPLY = process.argv.includes("--apply");

/**
 * Sources, both fetched 2026-09-10:
 *   https://blog.cloudflare.com/18-november-2025-outage/
 *   https://blog.cloudflare.com/5-december-2025-outage/
 *
 * `summary` values are the timeline rows as published. `detail` carries the
 * citation so the grounding survives into the drafted postmortem, because
 * incident_evidence has no source-URL column of its own -- worth knowing
 * before adding more sources here.
 */
const INCIDENTS = [
  {
    title: "Public incident analysis: Cloudflare global outage, 18 November 2025",
    severity: "sev1",
    impact:
      "Core network traffic delivery failed globally for 5h38m (11:28-17:06 UTC), affecting HTTP traffic, Workers KV and Cloudflare Access.",
    source: "https://blog.cloudflare.com/18-november-2025-outage/",
    evidence: [
      ["2025-11-18T11:05:00Z", "deploy", "Database access control change deployed"],
      ["2025-11-18T11:28:00Z", "alert", "Deployment reaches customer environments, first errors observed on customer HTTP traffic"],
      ["2025-11-18T11:32:00Z", "human_note", "Team investigated elevated traffic levels and errors to Workers KV service; mitigations attempted"],
      ["2025-11-18T13:05:00Z", "human_note", "Workers KV and Cloudflare Access bypass implemented -- impact reduced"],
      ["2025-11-18T13:37:00Z", "human_note", "Work focused on rollback of Bot Management configuration file to last-known-good version"],
      ["2025-11-18T14:24:00Z", "human_note", "Stopped creation and propagation of new Bot Management configuration files; observed successful recovery using old version of configuration file"],
      ["2025-11-18T14:30:00Z", "deploy", "Correct Bot Management configuration file deployed globally; most services operating correctly"],
      ["2025-11-18T17:06:00Z", "human_note", "All services resolved; impact ends"],
      ["2025-11-18T17:10:00Z", "log", 'Root cause, as published: "A change in our underlying ClickHouse query behaviour caused it to have a large number of duplicate \'feature\' rows."'],
      ["2025-11-18T17:11:00Z", "log", 'Failure mode, as published: "When the bad file with more than 200 features was propagated to our servers, this limit was hit -- resulting in the system panicking."'],
      ["2025-11-18T17:12:00Z", "log", 'Resolution, as published: "We solved the problem by stopping the generation and propagation of the larger-than-expected feature file and replacing it with an earlier version."'],
    ],
  },
  {
    title: "Public incident analysis: Cloudflare HTTP traffic errors, 5 December 2025",
    severity: "sev2",
    impact:
      "Approximately 28% of all HTTP traffic served by Cloudflare failed for 25 minutes (08:47-09:12 UTC).",
    source: "https://blog.cloudflare.com/5-december-2025-outage/",
    evidence: [
      ["2025-12-05T08:47:00Z", "deploy", "Configuration change deployed and propagated to network"],
      ["2025-12-05T08:48:00Z", "deploy", "Change fully propagated"],
      ["2025-12-05T08:50:00Z", "alert", "Incident declared via automated alerts"],
      ["2025-12-05T09:11:00Z", "deploy", "Configuration change reverted and propagation began"],
      ["2025-12-05T09:12:00Z", "metric", "Revert fully propagated; all traffic restored"],
      ["2025-12-05T09:20:00Z", "log", 'Trigger, as published: "The issue was triggered by changes being made to our body parsing logic while attempting to detect and mitigate an industry-wide vulnerability in React Server Components."'],
      ["2025-12-05T09:21:00Z", "log", 'Failure mode, as published: "When the killswitch was applied, the code correctly skipped the evaluation of the execute action, and didn\'t evaluate the sub-ruleset pointed to by it. However, an error was then encountered while processing the overall results."'],
      ["2025-12-05T09:22:00Z", "log", 'Resolution, as published: "The issue was identified shortly after the change was applied, and was reverted at 09:12, after which all traffic was served correctly."'],
    ],
  },
];

let cookie = "";

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "content-type": "application/json", ...(cookie ? { cookie } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const setCookie = res.headers.get("set-cookie");
  if (setCookie) cookie = setCookie.split(";")[0];
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}: ${text.slice(0, 400)}`);
  return text ? JSON.parse(text) : null;
}

function preview() {
  console.log(`\nDRY RUN -- nothing will be written. Re-run with --apply to create these.\n`);
  for (const inc of INCIDENTS) {
    console.log(`  ${inc.title}`);
    console.log(`    severity : ${inc.severity}`);
    console.log(`    impact   : ${inc.impact}`);
    console.log(`    source   : ${inc.source}`);
    console.log(`    evidence : ${inc.evidence.length} entries, all verbatim from the source above`);
    for (const [at, source, summary] of inc.evidence) {
      console.log(`        ${at}  [${source}]  ${summary.slice(0, 88)}${summary.length > 88 ? "..." : ""}`);
    }
    console.log("");
  }
  console.log(`  Would create ${INCIDENTS.length} incidents, draft each with the real AI provider,`);
  console.log(`  publish them, and make each one a PUBLIC page at /postmortems/{slug}.`);
  console.log(`\n  This spends real AI credit and creates permanent public content.\n`);
}

async function seed() {
  console.log(`\nAPPLYING against ${API_BASE} as ${EMAIL}\n`);
  await api("/v1/auth/login", { method: "POST", body: { email: EMAIL, password: PASSWORD } });
  console.log("  logged in");

  for (const inc of INCIDENTS) {
    console.log(`\n  ${inc.title}`);
    const incident = await api("/v1/postmortems/incidents", {
      method: "POST",
      body: { title: inc.title, severity: inc.severity, impact: inc.impact },
    });
    const id = incident.id ?? incident.incident_id;
    console.log(`    incident ${id}`);

    for (const [at, source, summary] of inc.evidence) {
      await api(`/v1/postmortems/incidents/${id}/evidence`, {
        method: "POST",
        body: {
          occurred_at: Date.parse(at),
          source,
          summary: summary.slice(0, 500),
          // The citation. incident_evidence has no URL column, so it rides in
          // detail -- which is what the drafting model reads, so the grounding
          // survives into the postmortem itself.
          detail: `Verbatim from the published incident report: ${inc.source}`,
        },
      });
    }
    console.log(`    ${inc.evidence.length} evidence entries recorded`);

    await api(`/v1/postmortems/incidents/${id}/draft`, { method: "POST" });
    console.log("    drafted");

    await api(`/v1/postmortems/incidents/${id}/publish`, { method: "POST" });
    console.log("    published");

    const pub = await api(`/v1/postmortems/incidents/${id}/public`, {
      method: "PATCH",
      body: { is_public: true },
    });
    console.log(`    public at /postmortems/${pub.slug ?? "(slug not returned)"}`);
  }

  console.log(`\n  Done. Check https://www.nanoneuron.ai/postmortems\n`);
}

if (!EMAIL || !PASSWORD) {
  console.error("\nSet SEED_EMAIL and SEED_PASSWORD (an account with an ACTIVE subscription).\n");
  process.exit(1);
}

if (APPLY) {
  seed().catch((err) => {
    console.error(`\n  FAILED: ${err.message}\n`);
    console.error("  Nothing is rolled back automatically -- check /postmortems and the client");
    console.error("  dashboard for a partially-created incident before re-running.\n");
    process.exit(1);
  });
} else {
  preview();
}
