// Thin fetch wrapper around the FastAPI backend. No Next.js API-route proxy
// layer for this MVP slice -- the browser calls FastAPI directly (backend
// has CORS enabled for this origin via Settings.cors_origins).
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

// FastAPI's own validation errors (422s) shape `detail` as an array of
// {type, loc, msg} objects, not a string -- every other error response in
// this app uses a plain string detail. `new Error(anArray)` stringifies via
// Array.prototype.toString(), which calls each object's own toString():
// the user would see the literal text "[object Object]" instead of the
// real validation reason. Confirmed directly (not assumed) before fixing:
// `new Error([{type:"string_too_short", ...}]).message` really is
// "[object Object]" in Node.
export function readableDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : null))
      .filter((msg): msg is string => msg !== null);
    return messages.length > 0 ? messages.join("; ") : null;
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include", // every postmortem route now requires the session cookie
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(readableDetail(body.detail) ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export type Incident = {
  id: string;
  title: string;
  severity: string;
  status: string;
  impact?: string | null;
  resolution_ms?: number | null;
  is_public?: boolean;
  public_slug?: string | null;
};

export type Evidence = {
  id: string;
  occurred_at: number;
  source: string;
  summary: string;
  detail: string | null;
  authorized_by: string;
};

export type ExtractedEvidence = { source: string; summary: string; detail: string | null };
export type SuggestedIncident = { title: string; severity: string };

export type PostmortemAction = {
  id: string;
  title: string;
  rationale: string;
  owner: string;
  evidence_id: string | null;
  status: string;
};

export type Postmortem = {
  id: string;
  status: string;
  summary: string;
  root_cause: string;
  detection: string;
  resolution: string;
  contributing_factors: string[];
  cited_evidence_ids: string[];
  unsupported_claims_dropped: number;
  approved_by: string | null;
  approved_at: number | null;
  actions: PostmortemAction[];
  is_public: boolean;
  slug: string | null;
};

export type DashboardSummary = {
  total_incidents: number;
  open_incidents: number;
  resolved_incidents: number;
  drafted_postmortems: number;
  published_postmortems: number;
  // Follow-ups still owed (open or in progress) across every incident.
  open_actions: number;
  avg_resolution_ms: number | null;
  recent_incidents: Incident[];
};

export type ActionStatus = "open" | "in_progress" | "done" | "dropped";
export const ACTION_STATUSES: ActionStatus[] = ["open", "in_progress", "done", "dropped"];

// One window of the founder's margin view. ai_cost_usd_max is a ceiling,
// not an estimate: every token priced at the model's output rate, because
// the backend doesn't record the prompt/completion split (see founder.py).
export type EconomicsWindow = {
  ai_runs: number;
  ai_runs_without_token_data: number;
  ai_tokens: number;
  ai_cost_usd_max: number;
  revenue_inr: number;
};

export type FounderSummary = {
  total_users: number;
  total_incidents: number;
  open_incidents: number;
  resolved_incidents: number;
  avg_resolution_ms: number | null;
  drafted_postmortems: number;
  published_postmortems: number;
  ai_runs_total: number;
  ai_runs_succeeded: number;
  ai_runs_failed: number;
  ai_runs_avg_latency_ms: number | null;
  ai_runs_24h_total: number;
  ai_runs_24h_succeeded: number;
  ai_runs_24h_failed: number;
  ai_runs_24h_avg_latency_ms: number | null;
  ai_runs_by_feature: {
    prompt_version: string;
    total: number;
    succeeded: number;
    failed: number;
    avg_latency_ms: number | null;
  }[];
  pending_payment_claims: number;
  unit_economics: {
    month_start: number;
    month: EconomicsWindow;
    all_time: EconomicsWindow;
    ai_price_usd_per_million_tokens: number;
    ai_price_basis: string;
  };
  conversion_funnel: {
    signups: number;
    tried_free_incident: number;
    ever_paid: number;
    currently_paying: number;
    approved_manual_claims: number;
  };
  airlock_waitlist: { total: number; last_7d: number };
  // Whether Airlock is earning -- see cqrs/airlock_billing.py's
  // handle_airlock_business_stats_query. revenue_by_currency is approved
  // Airlock pack claims only; credits_granted_total is not revenue.
  airlock: {
    credits_sold_total: number;
    credits_granted_total: number;
    credits_used_total: number;
    credits_used_last_7d: number;
    credits_outstanding: number;
    active_keys: number;
    accounts_with_balance: number;
    revenue_by_currency: { currency: string; amount: number; claims: number }[];
  };
  // Unhandled 500s the API answered (cqrs/request_errors.py). Zero is the
  // number this should show.
  errors: { last_24h: number; last_7d: number };
  recent_users: { id: string; email: string; created_at: number }[];
  recent_ai_runs: {
    id: string;
    incident_id: string;
    provider: string;
    model: string;
    status: string;
    error_type: string | null;
    latency_ms: number;
    created_at: number;
  }[];
};

export type BillingStatus = {
  subscription_status: string;
  current_period_end: number | null;
  has_active_subscription: boolean;
};

// Price only -- never the real account/UPI id, never fetched by a client.
// The real details (UpiInfo/WireInfo below) are founder-only now; a client
// who wants to pay is told to contact the founder to arrange it.
export type UpiPricing = { amount_inr: number; amount_inr_annual: number; configured: boolean };
export type WirePricing = {
  configured: boolean;
  currencies: { currency: string; amount: number; amount_annual: number }[];
};

export type UpiInfo = { upi_id: string; payee_name: string; amount_inr: number; configured: boolean };

export type WireCurrency = {
  currency: string;
  amount: number;
  correspondent_bank: string;
  correspondent_swift: string;
  nostro_account: string;
  routing_reference: string;
};

export type WireInfo = {
  account_name: string;
  account_number: string;
  bank_name: string;
  swift_code: string;
  configured: boolean;
  currencies: WireCurrency[];
};

export type Claim = {
  id: string;
  method: string;
  currency: string;
  amount: number;
  reference: string;
  status: string;
  created_at: number;
  // "monthly" | "annual" -- returned by the backend's single _CLAIM_COLUMNS
  // projection. It matters at approval time: an annual claim grants 365 days,
  // not 30, so the founder UI must say which before the click, not after.
  billing_period: string;
  // "postmortem" (a subscription) or "airlock" (a pack of scans), and for
  // the latter how many scans approval grants. Optional because a row read
  // back from before migration 0032 may lack them.
  product?: string;
  scan_credits?: number | null;
};

export type PaymentClaim = Claim & { user_id: string; email: string; bank_verified: boolean };

export type Invoice = {
  number: string;
  // "proforma" while pending, "receipt" once approved, "void" if rejected.
  kind: "proforma" | "receipt" | "void";
  status: string;
  issued_at: number;
  paid_at: number | null;
  seller: { name: string; address: string | null; tax_id: string | null };
  buyer_email: string;
  line: { description: string; quantity: number; unit_amount: number; amount: number; currency: string };
  method: string;
  reference: string;
  product: string;
  billing_period: string | null;
  scan_credits: number | null;
};

export const billing = {
  status: () => request<BillingStatus>("/v1/billing/status"),
  invoice: (claimId: string) => request<Invoice>(`/v1/billing/claims/${claimId}/invoice`),
  upiPricing: () => request<UpiPricing>("/v1/billing/upi/pricing"),
  submitUpiClaim: (reference: string, billingPeriod: "monthly" | "annual" = "monthly") =>
    request<Claim>("/v1/billing/upi/claim", {
      method: "POST",
      body: JSON.stringify({ reference, billing_period: billingPeriod }),
    }),
  // Self-serve replacement for emailing the founder to ask for the real
  // UPI ID -- see api/v1/billing.py's email_upi_details. Sends to the
  // caller's own registered address; there's no address to pass here.
  emailUpiDetails: (billingPeriod: "monthly" | "annual" = "monthly") =>
    request<{ sent: boolean }>("/v1/billing/upi/email-details", {
      method: "POST",
      body: JSON.stringify({ billing_period: billingPeriod }),
    }),
  myUpiClaims: () => request<Claim[]>("/v1/billing/upi/claims"),
  wirePricing: () => request<WirePricing>("/v1/billing/wire/pricing"),
  submitWireClaim: (currency: string, reference: string, billingPeriod: "monthly" | "annual" = "monthly") =>
    request<Claim>("/v1/billing/wire/claim", {
      method: "POST",
      body: JSON.stringify({ currency, reference, billing_period: billingPeriod }),
    }),
  emailWireDetails: (currency: string, billingPeriod: "monthly" | "annual" = "monthly") =>
    request<{ sent: boolean }>("/v1/billing/wire/email-details", {
      method: "POST",
      body: JSON.stringify({ currency, billing_period: billingPeriod }),
    }),
  myWireClaims: () => request<Claim[]>("/v1/billing/wire/claims"),
  // PATCH -- fix a typo'd reference; DELETE -- withdraw the claim. Both
  // only work while the claim is still 'pending' (enforced server-side).
  updateClaim: (claimId: string, reference: string) =>
    request<Claim>(`/v1/billing/claims/${claimId}`, { method: "PATCH", body: JSON.stringify({ reference }) }),
  cancelClaim: async (claimId: string): Promise<void> => {
    const response = await fetch(`${API_BASE}/v1/billing/claims/${claimId}`, { method: "DELETE", credentials: "include" });
    if (!response.ok && response.status !== 204) {
      const body = await response.json().catch(() => ({}));
      throw new Error(readableDetail(body.detail) ?? `Request failed: ${response.status}`);
    }
  },
};

export type PaymentClaimEvent = { event_type: string; actor: string; detail: string | null; created_at: number };

export type ErrorGroup = {
  fingerprint: string;
  error_type: string;
  method: string;
  path: string;
  count: number;
  first_seen: number;
  last_seen: number;
  last_request_id: string;
  sample_message: string;
  notified: boolean;
};

export const founderBilling = {
  paymentClaims: () => request<PaymentClaim[]>("/v1/founder/payment-claims"),
  errors: (days = 7) => request<ErrorGroup[]>(`/v1/founder/errors?days=${days}`),
  // Founder-only Airlock credit grant for everything that is not a
  // payment: refunds credited as scans, goodwill after an outage, a pilot.
  // Every grant is a ledger line with the note on it (founder.py).
  grantAirlockCredits: (email: string, credits: number, reason: "grant" | "refund" | "adjustment", note: string) =>
    request<{ email: string; credits: number; balance: number }>("/v1/founder/airlock/grant", {
      method: "POST",
      body: JSON.stringify({ email, credits, reason, note }),
    }),
  approveClaim: (claimId: string) =>
    request<PaymentClaim>(`/v1/founder/payment-claims/${claimId}/approve`, { method: "POST" }),
  rejectClaim: (claimId: string) =>
    request<PaymentClaim>(`/v1/founder/payment-claims/${claimId}/reject`, { method: "POST" }),
  annotateClaim: (claimId: string, detail: string) =>
    request<PaymentClaimEvent>(`/v1/founder/payment-claims/${claimId}/annotate`, {
      method: "POST",
      body: JSON.stringify({ detail }),
    }),
  // The backend's append-only claim ledger (migration 0016) has held a
  // full history -- created, bank-verified, approved/rejected, annotated
  // -- since it was built, but nothing in the dashboard ever fetched it;
  // a founder could annotate a claim but never see the claim's own
  // history. GET only, never mutates anything.
  claimEvents: (claimId: string) => request<PaymentClaimEvent[]>(`/v1/founder/payment-claims/${claimId}/events`),
};

export type FounderActivityLogEntry = {
  client_email: string;
  action: string;
  incident_id: string | null;
  detail: string | null;
  // "web" or "mcp_agent" -- see mcp_server.py's _audited().
  source: string;
  created_at: number;
};

export type FounderActivityLogPage = {
  entries: FounderActivityLogEntry[];
  // Pass back as the `cursor` filter to fetch the next page; null means
  // this was the last one. See cqrs/activity.py's keyset pagination.
  next_cursor: string | null;
};

export const founderActivity = {
  // The cross-account counterpart to api.activityLog() -- that one is
  // always scoped to the caller's own account; this one can see every
  // account, the actual point of a founder-only accountability view.
  list: (filter?: {
    clientEmail?: string;
    source?: string;
    sinceMs?: number;
    untilMs?: number;
    limit?: number;
    cursor?: string;
  }) => {
    const query = new URLSearchParams();
    if (filter?.clientEmail) query.set("client_email", filter.clientEmail);
    if (filter?.source) query.set("source", filter.source);
    if (filter?.sinceMs != null) query.set("since_ms", String(filter.sinceMs));
    if (filter?.untilMs != null) query.set("until_ms", String(filter.untilMs));
    if (filter?.limit != null) query.set("limit", String(filter.limit));
    if (filter?.cursor) query.set("cursor", filter.cursor);
    const qs = query.toString();
    return request<FounderActivityLogPage>(`/v1/founder/activity-log${qs ? `?${qs}` : ""}`);
  },
};

export type Integrations = { slack_connected: boolean; linear_connected: boolean; linear_team_id: string | null };

export const integrations = {
  get: () => request<Integrations>("/v1/integrations"),
  update: (payload: { slack_webhook_url?: string; linear_api_key?: string; linear_team_id?: string }) =>
    request<Integrations>("/v1/integrations", { method: "PUT", body: JSON.stringify(payload) }),
};

export type WebhookToken = { token: string };

export const webhooks = {
  token: () => request<WebhookToken>("/v1/webhooks/token"),
  rotate: () => request<WebhookToken>("/v1/webhooks/token/rotate", { method: "POST" }),
};

export const api = {
  listIncidents: () => request<Incident[]>("/v1/postmortems/incidents"),
  summary: () => request<DashboardSummary>("/v1/postmortems/summary"),
  updateIncidentStatus: (incidentId: string, status: "open" | "resolved") =>
    request<Incident>(`/v1/postmortems/incidents/${incidentId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  updatePublicVisibility: (incidentId: string, isPublic: boolean) =>
    request<Postmortem>(`/v1/postmortems/incidents/${incidentId}/public`, {
      method: "PATCH",
      body: JSON.stringify({ is_public: isPublic }),
    }),
  founderSummary: () => request<FounderSummary>("/v1/founder/summary"),
  createIncident: (input: { title: string; severity: string; impact?: string }) =>
    request<Incident>("/v1/postmortems/incidents", { method: "POST", body: JSON.stringify(input) }),
  suggestIncident: (text: string) =>
    request<SuggestedIncident>("/v1/postmortems/incidents/suggest", { method: "POST", body: JSON.stringify({ text }) }),
  listEvidence: (incidentId: string) => request<Evidence[]>(`/v1/postmortems/incidents/${incidentId}/evidence`),
  addEvidence: (
    incidentId: string,
    input: { occurred_at: number; source: string; summary: string; detail?: string },
  ) =>
    request<Evidence>(`/v1/postmortems/incidents/${incidentId}/evidence`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  extractEvidence: (incidentId: string, text: string) =>
    request<ExtractedEvidence[]>(`/v1/postmortems/incidents/${incidentId}/evidence/extract`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  draft: (incidentId: string) =>
    request<Postmortem>(`/v1/postmortems/incidents/${incidentId}/draft`, { method: "POST" }),
  getPostmortem: (incidentId: string) => request<Postmortem>(`/v1/postmortems/incidents/${incidentId}`),
  publish: (incidentId: string) =>
    request<Postmortem>(`/v1/postmortems/incidents/${incidentId}/publish`, { method: "POST" }),
  similarIncidents: (incidentId: string) =>
    request<SimilarIncident[]>(`/v1/postmortems/incidents/${incidentId}/similar`),
  previousDraft: (incidentId: string) =>
    request<PreviousDraft | null>(`/v1/postmortems/incidents/${incidentId}/previous-draft`),
  qualitySummary: () => request<EvidenceQualitySummary>("/v1/postmortems/quality-summary"),
  exportData: () => request<ExportedData>("/v1/postmortems/export"),
  // Raw text, not JSON -- the one route that returns a file. A 404 here
  // most likely means the API deployment behind this frontend predates
  // the route (the API does not auto-deploy with the web app), so the
  // message says that instead of a bare status code.
  postmortemMarkdown: async (incidentId: string): Promise<string> => {
    const response = await fetch(`${API_BASE}/v1/postmortems/incidents/${incidentId}/postmortem.md`, {
      credentials: "include",
    });
    if (response.status === 404) throw new Error("Markdown export isn't available on this API version yet.");
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(readableDetail(body.detail) ?? `Request failed: ${response.status}`);
    }
    return response.text();
  },
  activityLog: () => request<ActivityLogEntry[]>("/v1/postmortems/activity-log"),
  updateActionStatus: (incidentId: string, actionId: string, status: ActionStatus) =>
    request<PostmortemAction>(`/v1/postmortems/incidents/${incidentId}/actions/${actionId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  updateStatusPageVisibility: (incidentId: string, isPublic: boolean) =>
    request<Incident>(`/v1/postmortems/incidents/${incidentId}/status-page`, {
      method: "PATCH",
      body: JSON.stringify({ is_public: isPublic }),
    }),
  postStatusPageUpdate: (incidentId: string, message: string) =>
    request<StatusPageUpdate>(`/v1/postmortems/incidents/${incidentId}/status-page/updates`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  statusPageUpdates: (incidentId: string) =>
    request<StatusPageUpdate[]>(`/v1/postmortems/incidents/${incidentId}/status-page/updates`),
};

export type StatusPageUpdate = { message: string; created_at: number };

export type ExportedData = {
  exported_at: number;
  account_email: string;
  incidents: unknown[];
  evidence: unknown[];
  postmortems: unknown[];
  actions: unknown[];
};

export type ActivityLogEntry = {
  action: string;
  incident_id: string | null;
  detail: string | null;
  // "web" (a browser session or a webhook acting as one) or "mcp_agent"
  // (an AI agent -- Claude Desktop, etc. -- via this account's own MCP
  // tools). See apps/api/app/mcp_server.py's _audited().
  source: string;
  created_at: number;
};

export type SimilarIncident = { incident_title: string; summary: string; root_cause: string };

export type PreviousDraft = {
  summary: string;
  root_cause: string;
  detection: string;
  resolution: string;
  contributing_factors: string[];
  unsupported_claims_dropped: number;
  superseded_at: number;
};

export type EvidenceQualitySummary = {
  total_drafts: number;
  drafts_with_any_unsupported_section: number;
  unsupported_by_section: Record<string, number>;
};

// Airlock's early-access list. The second product has no hosted scanner
// yet, so this is the only Airlock call the site can make -- deliberately
// not a "try a scan" endpoint, which would imply an API that isn't running.
// The backend answers 202 for a new address and for one already on the
// list, identically; callers must not try to tell them apart.
export type AirlockWaitlistInput = {
  email: string;
  company?: string | null;
  use_case?: string | null;
};

export async function joinAirlockWaitlist(input: AirlockWaitlistInput): Promise<{ status: string }> {
  return request<{ status: string }>("/v1/airlock/waitlist", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

// Airlock's scanner. Paid and metered -- see apps/api/app/api/v1/airlock.py.
// From the browser it authenticates with the session cookie and spends one
// credit per call from the same balance an API key would; a signed-out
// visitor gets 401 and an unfunded account gets 402. The playground turns
// both into a sentence that says what to do next rather than a raw status.
export type AirlockMatch = { rule_id: string; family: string; weight: number; description: string };

export type AirlockScan = {
  verdict: "allow" | "flag" | "block";
  score: number;
  matches: AirlockMatch[];
  families: string[];
  signals: Record<string, unknown>;
  content_sha256: string;
  content_bytes: number;
  latency_ms: number;
  // Balance after this call; null when the call was not charged (founder).
  credits_remaining: number | null;
  // 1, 5 for a deep scan, back to 1 if Gemini was unavailable and the
  // extra was refunded, 1 when the rules already blocked and the model
  // was not asked, 0 for the founder.
  credits_charged: number;
  // Only on a deep scan: the model's answer, status "unavailable", or
  // status "skipped" (the rules already blocked; nothing for it to raise).
  semantic: {
    status: "ok" | "unavailable" | "skipped";
    injection?: boolean;
    confidence?: number;
    family?: string | null;
    reason: string;
    model?: string;
    weight: number;
  } | null;
  // The content with hidden characters, hidden HTML and the strongest
  // matches removed. Only when the scan asked for it.
  sanitized: string | null;
  // The account policy this verdict was judged under.
  policy: { block_threshold: number; flag_threshold: number; muted_rules: string[]; default: boolean };
};

export type AirlockProxyFetch = {
  verdict: "allow" | "flag" | "block";
  score: number;
  // "egress" when the URL itself was refused before any fetch, "ingress"
  // when the fetched page was scanned.
  stage: "egress" | "ingress";
  reasons: string[];
  matches: AirlockMatch[];
  families: string[];
  signals: Record<string, unknown>;
  url: string;
  final_url: string | null;
  http_status: number | null;
  content_type: string | null;
  content_bytes: number;
  content_sha256: string | null;
  destination_checked: boolean;
  hops: number;
  truncated: boolean;
  fetch_ms: number;
  latency_ms: number;
  // The page's visible text on allow (sanitized on flag); null on block.
  content: string | null;
  credits_remaining: number | null;
  credits_charged: number;
  semantic: AirlockScan["semantic"];
  policy: AirlockScan["policy"];
};

export async function airlockProxyFetch(url: string, deep = false): Promise<AirlockProxyFetch> {
  const response = await fetch(`${API_BASE}/v1/airlock/proxy/fetch`, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ url, deep }),
  });
  if (!response.ok) {
    // 422/502 from the proxy carry verdict: block and a reason; surface the
    // reason and keep the status so the caller can tell 401/402 apart.
    const body = await response.json().catch(() => ({}));
    throw new AirlockScanError(readableDetail(body.detail) ?? `Request failed: ${response.status}`, response.status);
  }
  return response.json() as Promise<AirlockProxyFetch>;
}

export class AirlockScanError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export async function airlockScan(
  content: string,
  source?: string,
  deep = false,
  sanitize = false,
): Promise<AirlockScan> {
  const response = await fetch(`${API_BASE}/v1/airlock/scan`, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ content, source: source ?? null, deep, sanitize }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new AirlockScanError(readableDetail(body.detail) ?? `Request failed: ${response.status}`, response.status);
  }
  return response.json() as Promise<AirlockScan>;
}

// Public, price-only. What a pack costs in each currency and which manual
// rail (UPI for INR, wire otherwise) takes it. Never the payee details.
export type AirlockPricing = {
  scans_per_pack: number;
  max_packs_per_claim: number;
  credits_per_scan: number;
  credits_per_deep_scan: number;
  credits_per_proxy_fetch: number;
  prices: { currency: string; amount: number; method: string; configured: boolean }[];
};

export async function airlockPricing(): Promise<AirlockPricing> {
  return request<AirlockPricing>("/v1/airlock/pricing");
}

export type AirlockApiKey = {
  id: string;
  label: string;
  prefix: string;
  created_at: number;
  last_used_at: number | null;
  revoked_at: number | null;
};

// `secret` is present on creation only. The backend keeps a hash; there is
// no call that returns it again.
export type AirlockCreatedKey = AirlockApiKey & { secret: string };

export type AirlockLedgerEntry = {
  delta: number;
  reason: string;
  reference: string | null;
  key_prefix: string | null;
  created_at: number;
};

export type AirlockCredits = {
  balance: number;
  purchased_total: number;
  used_total: number;
  used_last_30d: number;
  statement: AirlockLedgerEntry[];
};

export type AirlockCurrency = "INR" | "USD" | "GBP" | "EUR";

export type AirlockPolicy = {
  block_threshold: number;
  flag_threshold: number;
  muted_rules: string[];
  egress_allowlist: string[];
  // True while the account has never saved one (the engine defaults apply).
  default: boolean;
  updated_at: number | null;
};

export type AirlockPolicyIn = Omit<AirlockPolicy, "default" | "updated_at">;

export type AirlockRule = { id: string; family: string; weight: number; description: string };

export type AirlockRules = { count: number; families: string[]; rules: AirlockRule[] };

export type AirlockUsageRow = {
  day: string;
  key_prefix: string | null;
  scans: number;
  deep_scans: number;
  egress: number;
  refunds: number;
  credits: number;
};

export type AirlockUsage = { days: number; total_credits: number; rows: AirlockUsageRow[] };

export const airlock = {
  pricing: airlockPricing,
  rules: () => request<AirlockRules>("/v1/airlock/rules"),
  policy: () => request<AirlockPolicy>("/v1/airlock/policy"),
  setPolicy: (policy: AirlockPolicyIn) =>
    request<AirlockPolicy>("/v1/airlock/policy", { method: "PUT", body: JSON.stringify(policy) }),
  resetPolicy: () => request<AirlockPolicy>("/v1/airlock/policy", { method: "DELETE" }),
  usage: (days = 30) => request<AirlockUsage>(`/v1/airlock/usage?days=${days}`),
  // The CSV is fetched with the session cookie and handed back as text;
  // the caller turns it into a download. A plain <a href> to the API
  // would be a cross-site navigation that some browsers send cookieless.
  usageCsv: async (days = 90): Promise<{ filename: string; text: string }> => {
    const response = await fetch(`${API_BASE}/v1/airlock/usage.csv?days=${days}`, { credentials: "include" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(readableDetail(body.detail) ?? `Request failed: ${response.status}`);
    }
    const disposition = response.headers.get("content-disposition") ?? "";
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "airlock-usage.csv";
    return { filename, text: await response.text() };
  },
  keys: () => request<AirlockApiKey[]>("/v1/airlock/keys"),
  createKey: (label: string) =>
    request<AirlockCreatedKey>("/v1/airlock/keys", { method: "POST", body: JSON.stringify({ label }) }),
  revokeKey: async (keyId: string): Promise<void> => {
    const response = await fetch(`${API_BASE}/v1/airlock/keys/${keyId}`, { method: "DELETE", credentials: "include" });
    if (!response.ok && response.status !== 204) {
      const body = await response.json().catch(() => ({}));
      throw new Error(readableDetail(body.detail) ?? `Request failed: ${response.status}`);
    }
  },
  credits: () => request<AirlockCredits>("/v1/airlock/credits"),
  // The purchase is a payment claim (product='airlock') on the same manual
  // rails as the subscription. Amount and credit count are server-derived
  // from currency x packs; the client never states either.
  submitClaim: (currency: AirlockCurrency, reference: string, packs: number) =>
    request<Claim>("/v1/airlock/credits/claim", {
      method: "POST",
      body: JSON.stringify({ currency, reference, packs }),
    }),
  myClaims: () => request<Claim[]>("/v1/airlock/credits/claims"),
  emailDetails: (currency: AirlockCurrency, packs: number) =>
    request<{ sent: boolean }>("/v1/airlock/credits/email-details", {
      method: "POST",
      body: JSON.stringify({ currency, packs }),
    }),
};

export type AirlockStats = {
  total: number;
  blocked: number;
  flagged: number;
  allowed: number;
  last_7d: number;
  top_rules: { rule: string; count: number }[];
};

export async function airlockStats(): Promise<AirlockStats> {
  return request<AirlockStats>("/v1/airlock/stats");
}
