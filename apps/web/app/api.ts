// Thin fetch wrapper around the FastAPI backend. No Next.js API-route proxy
// layer for this MVP slice -- the browser calls FastAPI directly (backend
// has CORS enabled for this origin via Settings.cors_origins).
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include", // every postmortem route now requires the session cookie
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export type Incident = { id: string; title: string; severity: string; status: string; impact?: string | null };

export type Evidence = {
  id: string;
  occurred_at: number;
  source: string;
  summary: string;
  detail: string | null;
  authorized_by: string;
};

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
  recent_incidents: Incident[];
};

export type FounderSummary = {
  total_users: number;
  total_incidents: number;
  open_incidents: number;
  resolved_incidents: number;
  drafted_postmortems: number;
  published_postmortems: number;
  ai_runs_total: number;
  ai_runs_succeeded: number;
  ai_runs_failed: number;
  ai_runs_avg_latency_ms: number | null;
  pending_payment_claims: number;
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

export const billing = {
  status: () => request<BillingStatus>("/v1/billing/status"),
  checkout: () => request<{ url: string }>("/v1/billing/checkout", { method: "POST" }),
  portal: () => request<{ url: string }>("/v1/billing/portal", { method: "POST" }),
  upiPricing: () => request<UpiPricing>("/v1/billing/upi/pricing"),
  submitUpiClaim: (reference: string) =>
    request<Claim>("/v1/billing/upi/claim", { method: "POST", body: JSON.stringify({ reference }) }),
  myUpiClaims: () => request<Claim[]>("/v1/billing/upi/claims"),
  wirePricing: () => request<WirePricing>("/v1/billing/wire/pricing"),
  submitWireClaim: (currency: string, reference: string) =>
    request<Claim>("/v1/billing/wire/claim", { method: "POST", body: JSON.stringify({ currency, reference }) }),
  myWireClaims: () => request<Claim[]>("/v1/billing/wire/claims"),
};

export const founderBilling = {
  paymentClaims: () => request<PaymentClaim[]>("/v1/founder/payment-claims"),
  approveClaim: (claimId: string) =>
    request<PaymentClaim>(`/v1/founder/payment-claims/${claimId}/approve`, { method: "POST" }),
  rejectClaim: (claimId: string) =>
    request<PaymentClaim>(`/v1/founder/payment-claims/${claimId}/reject`, { method: "POST" }),
};

export type Integrations = { slack_connected: boolean; linear_connected: boolean; linear_team_id: string | null };

export const integrations = {
  get: () => request<Integrations>("/v1/integrations"),
  update: (payload: { slack_webhook_url?: string; linear_api_key?: string; linear_team_id?: string }) =>
    request<Integrations>("/v1/integrations", { method: "PUT", body: JSON.stringify(payload) }),
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
  listEvidence: (incidentId: string) => request<Evidence[]>(`/v1/postmortems/incidents/${incidentId}/evidence`),
  addEvidence: (
    incidentId: string,
    input: { occurred_at: number; source: string; summary: string; detail?: string },
  ) =>
    request<Evidence>(`/v1/postmortems/incidents/${incidentId}/evidence`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  draft: (incidentId: string) =>
    request<Postmortem>(`/v1/postmortems/incidents/${incidentId}/draft`, { method: "POST" }),
  getPostmortem: (incidentId: string) => request<Postmortem>(`/v1/postmortems/incidents/${incidentId}`),
  publish: (incidentId: string) =>
    request<Postmortem>(`/v1/postmortems/incidents/${incidentId}/publish`, { method: "POST" }),
};
