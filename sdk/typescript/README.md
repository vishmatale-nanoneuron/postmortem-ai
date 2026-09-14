# Airlock — TypeScript SDK

The prompt-injection and exfiltration guard for AI agents, as three calls.
Zero dependencies (global `fetch`). Paid per call from your key's prepaid
credits; every non-200 throws, so "any throw = block" fails closed.

```bash
npm install nanoneuron-airlock     # once published; until then: copy src/index.ts
```

```ts
import { Airlock } from "nanoneuron-airlock";

const guard = new Airlock({ apiKey: process.env.AIRLOCK_KEY! });

// Inbound: score untrusted text before it reaches the model. 1 credit.
const result = await guard.scan(documentText, { source: "web" });
if (result.verdict === "block") throw new Error(`injection: ${result.matches.map((m) => m.rule_id)}`);

// Outbound: check a payload and its destination before sending. 1 credit.
const check = await guard.egress(payload, { destination: "https://hooks.slack.com/...", allowlist: ["hooks.slack.com"] });
const safePayload = check.verdict === "allow" ? payload : (check.redacted ?? "");

// Proxy: let Airlock fetch the page and hand back text only if it passes. 2 credits.
const page = await guard.fetch("https://example.com/vendor-terms.html", { allowlist: ["example.com"] });
if (page.verdict === "allow") modelInput = page.content;
```

Errors: `AuthenticationError` (401), `InsufficientCredits` (402, nothing was
scanned), `RateLimited` (429, `.retryAfter` seconds), `FetchRefused` (proxy
422/502, verdict block), `AirlockError` (anything else). Every error carries
`.requestId`, which is what to quote if you ask about it.

Wrong verdict? Report it — not metered — and it tunes your account:

```ts
await guard.feedback(result, "allow", { note: "our own terms mention 'test mode enabled'" });
// Include the text only to keep it as a tuning example you can export later:
await guard.feedback(result, "block", { content: documentText });

const tuning = await guard.tuning(); // reports, suggestions (mute a rule, deep-scan a source), examples_with_content
const jsonl = await guard.tuningExamples(); // the reports that kept their text, for supervised tuning
```

Three reports naming the same rule on distinct scans become a one-click mute
in the dashboard; two reported misses from one source suggest `deep: true`
for it. Only the scan's hash, verdicts and rule ids are stored unless you
pass `content`.

Reference: https://www.nanoneuron.ai/docs#airlock
