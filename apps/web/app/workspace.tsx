"use client";
import { useEffect, useState } from "react";
import { api, type DashboardSummary, type Evidence, type FounderSummary, type Incident, type Postmortem } from "./api";
import { auth, type AuthUser } from "./auth";
import { Hero, HowItWorks, WhatThisIsnt } from "./landing";
import { evidenceSchema, firstError, incidentSchema, loginSchema, registerSchema } from "./validation";

const card = "rounded-lg border border-line bg-white p-4 shadow-sm mb-4";
const fieldLabel = "block text-xs font-medium text-muted mb-1";
const fieldInput =
  "w-full rounded-md border border-line px-3 py-2 mb-3 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";
const primaryButton =
  "rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper transition hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-50";
const secondaryButton =
  "rounded-md border border-line px-4 py-2 text-sm font-medium text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50";

// Auth gate: defaults to the logged-out landing/sign-in view, since that's
// what Next.js actually renders server-side for a "use client" component's
// initial state -- a curl request, a crawler, or a social-link preview
// never runs the useEffect below, so if the default were a bare loading
// state (or null) they'd see an empty page instead of the branded landing
// content. Real signed-in users still only see it for one render before
// the GET /v1/auth/me check below swaps them to the real workspace --
// nothing incident-related renders or fetches until that positively
// confirms a signed-in user.
export default function Workspace() {
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    auth
      .me()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  if (!user) return <AuthGate onSignedIn={setUser} />;

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">PostMortem AI</h1>
        <div className="flex items-center gap-3">
          {user.is_founder && (
            <span className="rounded-full bg-ink px-2.5 py-0.5 text-xs font-medium text-paper">Founder</span>
          )}
          <span className="text-sm text-muted">{user.email}</span>
          <button className={secondaryButton} type="button" onClick={() => void auth.logout().then(() => setUser(null))}>
            Log out
          </button>
        </div>
      </div>
      {user.is_founder && <FounderDashboard />}
      <IncidentWorkspace />
    </main>
  );
}

function FounderDashboard() {
  const [summary, setSummary] = useState<FounderSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .founderSummary()
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load founder summary."));
  }, []);

  if (error) return <p className="mb-4 text-sm text-red-600">{error}</p>;
  if (!summary) return null;

  const stats: [string, number | string][] = [
    ["Users", summary.total_users],
    ["Incidents", summary.total_incidents],
    ["Open incidents", summary.open_incidents],
    ["Resolved incidents", summary.resolved_incidents],
    ["Drafted postmortems", summary.drafted_postmortems],
    ["Published postmortems", summary.published_postmortems],
    ["AI runs (ok / failed)", `${summary.ai_runs_succeeded} / ${summary.ai_runs_failed}`],
    ["Avg draft latency", summary.ai_runs_avg_latency_ms != null ? `${summary.ai_runs_avg_latency_ms} ms` : "--"],
  ];

  return (
    <section className={card}>
      <h2 className="mb-3 text-base font-semibold">Founder dashboard</h2>
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-md bg-paper px-3 py-2">
            <div className="text-lg font-semibold text-ink">{value}</div>
            <div className="text-xs text-muted">{label}</div>
          </div>
        ))}
      </div>
      <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">Recent signups</h3>
      <ul className="mb-4 space-y-1 text-sm">
        {summary.recent_users.length === 0 ? (
          <li className="text-muted">None yet.</li>
        ) : (
          summary.recent_users.map((u) => (
            <li key={u.id} className="flex justify-between rounded-md bg-paper px-3 py-1.5">
              <span>{u.email}</span>
              <span className="text-muted">{new Date(u.created_at).toLocaleString()}</span>
            </li>
          ))
        )}
      </ul>
      <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">Recent AI runs</h3>
      <ul className="space-y-1 text-sm">
        {summary.recent_ai_runs.length === 0 ? (
          <li className="text-muted">None yet.</li>
        ) : (
          summary.recent_ai_runs.map((run) => (
            <li key={run.id} className="flex justify-between rounded-md bg-paper px-3 py-1.5">
              <span>
                {run.provider}/{run.model} -- {run.status}
                {run.error_type ? ` (${run.error_type})` : ""}
              </span>
              <span className="text-muted">{run.latency_ms} ms</span>
            </li>
          ))
        )}
      </ul>
    </section>
  );
}

function AuthGate({ onSignedIn }: { onSignedIn: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(form: FormData) {
    setError("");
    const email = String(form.get("email"));
    const password = String(form.get("password"));
    const schema = mode === "login" ? loginSchema : registerSchema;
    const validationError = firstError(schema, { email, password });
    if (validationError) return setError(validationError);

    setBusy(true);
    try {
      const user = mode === "login" ? await auth.login(email, password) : await auth.register(email, password);
      onSignedIn(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <Hero />
      <HowItWorks />
      <div id="get-started" className="mx-auto mb-16 max-w-sm px-4">
        <div className={card}>
          <h2 className="mb-3 text-lg font-semibold">{mode === "login" ? "Log in" : "Create an account"}</h2>
          <form action={submit}>
            <label className={fieldLabel}>Email</label>
            <input className={fieldInput} name="email" type="email" required />
            <label className={fieldLabel}>Password</label>
            <input className={fieldInput} name="password" type="password" minLength={8} required />
            <button className={`${primaryButton} w-full`} disabled={busy} type="submit">
              {mode === "login" ? "Log in" : "Create account"}
            </button>
          </form>
          {error && (
            <p role="status" className="mt-3 text-sm text-red-600">
              {error}
            </p>
          )}
          <p className="mt-3 text-sm text-muted">
            {mode === "login" ? "No account yet? " : "Already have an account? "}
            <button
              className="font-medium text-ink underline underline-offset-2"
              type="button"
              onClick={() => setMode(mode === "login" ? "register" : "login")}
            >
              {mode === "login" ? "Create one" : "Log in"}
            </button>
          </p>
        </div>
      </div>
      <WhatThisIsnt />
    </main>
  );
}

function IncidentWorkspace() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [postmortem, setPostmortem] = useState<Postmortem | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function refreshIncidents() {
    setIncidents(await api.listIncidents());
    setSummary(await api.summary());
  }

  async function toggleResolved(incident: Incident) {
    const nextStatus = incident.status === "resolved" ? "open" : "resolved";
    setBusy(true);
    try {
      await api.updateIncidentStatus(incident.id, nextStatus);
      await refreshIncidents();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update status.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshSelected(id: string) {
    setEvidence(await api.listEvidence(id));
    try {
      setPostmortem(await api.getPostmortem(id));
    } catch {
      setPostmortem(null);
    }
  }

  useEffect(() => {
    void refreshIncidents();
  }, []);

  useEffect(() => {
    if (selectedId) void refreshSelected(selectedId);
  }, [selectedId]);

  async function createIncident(form: FormData) {
    const payload = {
      title: String(form.get("title")),
      severity: String(form.get("severity")),
      impact: String(form.get("impact") || "") || undefined,
    };
    const validationError = firstError(incidentSchema, payload);
    if (validationError) return setMessage(validationError);

    setBusy(true);
    try {
      const created = await api.createIncident(payload);
      await refreshIncidents();
      setSelectedId(created.id);
      setMessage("Incident created.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create incident.");
    } finally {
      setBusy(false);
    }
  }

  async function addEvidence(form: FormData) {
    if (!selectedId) return;
    const payload = {
      occurred_at: Date.now(),
      source: String(form.get("source")),
      summary: String(form.get("summary")),
      detail: String(form.get("detail") || "") || undefined,
    };
    const validationError = firstError(evidenceSchema, payload);
    if (validationError) return setMessage(validationError);

    setBusy(true);
    try {
      await api.addEvidence(selectedId, payload);
      await refreshSelected(selectedId);
      setMessage("Evidence recorded.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not record evidence.");
    } finally {
      setBusy(false);
    }
  }

  async function generateDraft() {
    if (!selectedId) return;
    setBusy(true);
    setMessage("Drafting...");
    try {
      const draft = await api.draft(selectedId);
      setPostmortem(draft);
      setMessage("Draft generated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not draft postmortem.");
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!selectedId) return;
    setBusy(true);
    try {
      const published = await api.publish(selectedId);
      setPostmortem(published);
      setMessage("Postmortem published.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not publish.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="mb-6 text-sm text-muted">Evidence-grounded incident postmortem drafting.</p>

      {summary && (
        <section className={card}>
          <h2 className="mb-3 text-base font-semibold">Dashboard</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(
              [
                ["Open", summary.open_incidents],
                ["Resolved", summary.resolved_incidents],
                ["Drafted", summary.drafted_postmortems],
                ["Published", summary.published_postmortems],
              ] as [string, number][]
            ).map(([label, value]) => (
              <div key={label} className="rounded-md bg-paper px-3 py-2">
                <div className="text-lg font-semibold text-ink">{value}</div>
                <div className="text-xs text-muted">{label}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className={card}>
        <h2 className="mb-3 text-base font-semibold">Incidents</h2>
        {incidents.length === 0 ? (
          <p className="mb-3 text-sm text-muted">No incidents yet.</p>
        ) : (
          <ul className="mb-3 space-y-1.5">
            {incidents.map((incident) => (
              <li key={incident.id} className="flex items-center gap-1.5">
                <button
                  className={`w-full rounded-md px-3 py-2 text-left text-sm transition ${
                    selectedId === incident.id ? "bg-accent/10 font-medium text-accent" : "hover:bg-paper"
                  }`}
                  onClick={() => setSelectedId(incident.id)}
                  type="button"
                >
                  {incident.title} <span className="text-muted">({incident.severity}, {incident.status})</span>
                </button>
                <button
                  className="shrink-0 rounded-md border border-line px-2 py-1 text-xs text-muted transition hover:bg-paper disabled:opacity-50"
                  disabled={busy}
                  onClick={() => void toggleResolved(incident)}
                  type="button"
                >
                  {incident.status === "resolved" ? "Reopen" : "Mark resolved"}
                </button>
              </li>
            ))}
          </ul>
        )}
        <form action={createIncident}>
          <label className={fieldLabel}>Title</label>
          <input className={fieldInput} name="title" required />
          <label className={fieldLabel}>Severity</label>
          <select className={fieldInput} name="severity" defaultValue="sev2">
            <option value="sev1">sev1</option>
            <option value="sev2">sev2</option>
            <option value="sev3">sev3</option>
            <option value="sev4">sev4</option>
          </select>
          <label className={fieldLabel}>Impact</label>
          <input className={fieldInput} name="impact" />
          <button className={primaryButton} disabled={busy} type="submit">
            Create incident
          </button>
        </form>
      </section>

      {selectedId && (
        <>
          <section className={card}>
            <h2 className="mb-3 text-base font-semibold">Evidence</h2>
            {evidence.length === 0 ? (
              <p className="mb-3 text-sm text-muted">No evidence recorded yet.</p>
            ) : (
              <ul className="mb-3 space-y-1.5 text-sm">
                {evidence.map((entry) => (
                  <li key={entry.id} className="rounded-md bg-paper px-3 py-2">
                    <span className="font-medium">[{entry.source}]</span> {entry.summary}{" "}
                    {entry.detail && <span className="text-muted">-- {entry.detail}</span>}
                  </li>
                ))}
              </ul>
            )}
            <form action={addEvidence}>
              <label className={fieldLabel}>Source</label>
              <select className={fieldInput} name="source" defaultValue="alert">
                <option value="alert">alert</option>
                <option value="log">log</option>
                <option value="deploy">deploy</option>
                <option value="metric">metric</option>
                <option value="human_note">human_note</option>
                <option value="customer_report">customer_report</option>
              </select>
              <label className={fieldLabel}>Summary</label>
              <input className={fieldInput} name="summary" required />
              <label className={fieldLabel}>Detail (optional)</label>
              <input className={fieldInput} name="detail" />
              <button className={primaryButton} disabled={busy} type="submit">
                Add evidence
              </button>
            </form>
          </section>

          <section className={card}>
            <h2 className="mb-3 text-base font-semibold">Draft</h2>
            <button
              className={primaryButton}
              disabled={busy || evidence.length === 0}
              onClick={() => void generateDraft()}
              type="button"
            >
              Generate draft
            </button>
            {postmortem && (
              <div className="mt-4 space-y-2 text-sm">
                <p>
                  <span className="font-medium">Status:</span> {postmortem.status}
                </p>
                <p>
                  <span className="font-medium">Summary:</span> {postmortem.summary}
                </p>
                <p>
                  <span className="font-medium">Root cause:</span> {postmortem.root_cause}
                </p>
                <p>
                  <span className="font-medium">Detection:</span> {postmortem.detection}
                </p>
                <p>
                  <span className="font-medium">Resolution:</span> {postmortem.resolution}
                </p>
                {postmortem.contributing_factors.length > 0 && (
                  <div>
                    <span className="font-medium">Contributing factors:</span>
                    <ul className="mt-1 list-disc space-y-1 pl-5">
                      {postmortem.contributing_factors.map((factor) => (
                        <li key={factor}>{factor}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {postmortem.actions.length > 0 && (
                  <div>
                    <span className="font-medium">Actions:</span>
                    <ul className="mt-1 list-disc space-y-1 pl-5">
                      {postmortem.actions.map((action) => (
                        <li key={action.id}>
                          {action.title} -- {action.owner} ({action.rationale})
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <p className="text-xs text-muted">
                  Cited evidence: {postmortem.cited_evidence_ids.length} / unsupported claims dropped:{" "}
                  {postmortem.unsupported_claims_dropped}
                </p>
                {postmortem.status !== "published" && (
                  <button className={`${primaryButton} mt-1`} disabled={busy} onClick={() => void publish()} type="button">
                    Publish
                  </button>
                )}
                {postmortem.approved_by && (
                  <p className="text-xs text-muted">
                    Approved by {postmortem.approved_by} at {new Date(postmortem.approved_at ?? 0).toLocaleString()}
                  </p>
                )}
              </div>
            )}
          </section>
        </>
      )}

      {message && (
        <p role="status" className="text-sm text-muted">
          {message}
        </p>
      )}
    </>
  );
}
