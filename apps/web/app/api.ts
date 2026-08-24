// Thin fetch wrapper around the FastAPI backend. No Next.js API-route proxy
// layer for this MVP slice -- the browser calls FastAPI directly (backend
// has CORS enabled for this origin via Settings.cors_origins).
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
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
};

export const api = {
  listIncidents: () => request<Incident[]>("/v1/postmortems/incidents"),
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
