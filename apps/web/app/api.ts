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
  avg_resolution_ms: number | null;
  recent_incidents: Incident[];
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
  conversion_funnel: {
    signups: number;
    tried_free_incident: number;
    ever_paid: number;
    ever_paid_via_stripe: number;
    currently_paying: number;
    approved_manual_claims: number;
  };
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
export type UpiPricing = { amount_inr: number; configured: boolean };
export type WirePricing = { configured: boolean; currencies: { currency: string; amount: number }[] };

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
};

export type PaymentClaim = Claim & { user_id: string; email: string; bank_verified: boolean };

export type CardPricing = { configured: boolean };

export const billing = {
  status: () => request<BillingStatus>("/v1/billing/status"),
  cardPricing: () => request<CardPricing>("/v1/billing/card/pricing"),
  checkout: () => request<{ url: string }>("/v1/billing/checkout", { method: "POST" }),
  portal: () => request<{ url: string }>("/v1/billing/portal", { method: "POST" }),
  upiPricing: () => request<UpiPricing>("/v1/billing/upi/pricing"),
  submitUpiClaim: (reference: string) =>
    request<Claim>("/v1/billing/upi/claim", { method: "POST", body: JSON.stringify({ reference }) }),
  // Self-serve replacement for emailing the founder to ask for the real
  // UPI ID -- see api/v1/billing.py's email_upi_details. Sends to the
  // caller's own registered address; there's no address to pass here.
  emailUpiDetails: () => request<{ sent: boolean }>("/v1/billing/upi/email-details", { method: "POST" }),
  myUpiClaims: () => request<Claim[]>("/v1/billing/upi/claims"),
  wirePricing: () => request<WirePricing>("/v1/billing/wire/pricing"),
  submitWireClaim: (currency: string, reference: string) =>
    request<Claim>("/v1/billing/wire/claim", { method: "POST", body: JSON.stringify({ currency, reference }) }),
  emailWireDetails: (currency: string) =>
    request<{ sent: boolean }>("/v1/billing/wire/email-details", {
      method: "POST",
      body: JSON.stringify({ currency }),
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

export const founderBilling = {
  paymentClaims: () => request<PaymentClaim[]>("/v1/founder/payment-claims"),
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
  activityLog: () => request<ActivityLogEntry[]>("/v1/postmortems/activity-log"),
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
