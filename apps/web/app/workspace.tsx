"use client";
import { useEffect, useState } from "react";
import { api, type Evidence, type Incident, type Postmortem } from "./api";
import { auth, type AuthUser } from "./auth";
import { evidenceSchema, firstError, incidentSchema, loginSchema, registerSchema } from "./validation";

const box: React.CSSProperties = { border: "1px solid #d8d8d3", borderRadius: 8, padding: 16, marginBottom: 16 };
const label: React.CSSProperties = { display: "block", fontSize: 12, color: "#555", marginBottom: 4 };
const input: React.CSSProperties = { width: "100%", padding: 8, marginBottom: 8, boxSizing: "border-box" };
const button: React.CSSProperties = { padding: "8px 14px", cursor: "pointer" };

// Auth gate: unauthenticated visitors see a login/register form instead of
// the incident workspace; nothing incident-related renders (or fetches)
// until GET /v1/auth/me confirms a real signed-in user.
export default function Workspace() {
  const [user, setUser] = useState<AuthUser | null | "loading">("loading");

  useEffect(() => {
    auth
      .me()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  if (user === "loading") return null;
  if (!user) return <AuthGate onSignedIn={setUser} />;

  return (
    <main style={{ maxWidth: 720, margin: "40px auto", padding: "0 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h1>PostMortem AI</h1>
        <div>
          <span style={{ color: "#555", marginRight: 12 }}>{user.email}</span>
          <button
            style={button}
            type="button"
            onClick={() => void auth.logout().then(() => setUser(null))}
          >
            Log out
          </button>
        </div>
      </div>
      <IncidentWorkspace />
    </main>
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
    <main style={{ maxWidth: 360, margin: "80px auto", padding: "0 16px" }}>
      <h1>PostMortem AI</h1>
      <div style={box}>
        <h2>{mode === "login" ? "Log in" : "Create an account"}</h2>
        <form action={submit}>
          <label style={label}>Email</label>
          <input style={input} name="email" type="email" required />
          <label style={label}>Password</label>
          <input style={input} name="password" type="password" minLength={8} required />
          <button style={button} disabled={busy} type="submit">
            {mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>
        {error && <p role="status" style={{ color: "#a33" }}>{error}</p>}
        <p style={{ marginTop: 12, fontSize: 13 }}>
          {mode === "login" ? "No account yet? " : "Already have an account? "}
          <button
            style={{ ...button, padding: 0, border: "none", background: "none", textDecoration: "underline" }}
            type="button"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
          >
            {mode === "login" ? "Create one" : "Log in"}
          </button>
        </p>
      </div>
    </main>
  );
}

function IncidentWorkspace() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [postmortem, setPostmortem] = useState<Postmortem | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function refreshIncidents() {
    setIncidents(await api.listIncidents());
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
      <p style={{ color: "#555" }}>Evidence-grounded incident postmortem drafting.</p>

      <section style={box}>
        <h2>Incidents</h2>
        {incidents.length === 0 ? (
          <p>No incidents yet.</p>
        ) : (
          <ul>
            {incidents.map((incident) => (
              <li key={incident.id}>
                <button style={button} onClick={() => setSelectedId(incident.id)} type="button">
                  {incident.title} ({incident.severity}) {selectedId === incident.id ? "← selected" : ""}
                </button>
              </li>
            ))}
          </ul>
        )}
        <form action={createIncident}>
          <label style={label}>Title</label>
          <input style={input} name="title" required />
          <label style={label}>Severity</label>
          <select style={input} name="severity" defaultValue="sev2">
            <option value="sev1">sev1</option>
            <option value="sev2">sev2</option>
            <option value="sev3">sev3</option>
            <option value="sev4">sev4</option>
          </select>
          <label style={label}>Impact</label>
          <input style={input} name="impact" />
          <button style={button} disabled={busy} type="submit">
            Create incident
          </button>
        </form>
      </section>

      {selectedId && (
        <>
          <section style={box}>
            <h2>Evidence</h2>
            {evidence.length === 0 ? (
              <p>No evidence recorded yet.</p>
            ) : (
              <ul>
                {evidence.map((entry) => (
                  <li key={entry.id}>
                    [{entry.source}] {entry.summary} {entry.detail ? `-- ${entry.detail}` : ""}
                  </li>
                ))}
              </ul>
            )}
            <form action={addEvidence}>
              <label style={label}>Source</label>
              <select style={input} name="source" defaultValue="alert">
                <option value="alert">alert</option>
                <option value="log">log</option>
                <option value="deploy">deploy</option>
                <option value="metric">metric</option>
                <option value="human_note">human_note</option>
                <option value="customer_report">customer_report</option>
              </select>
              <label style={label}>Summary</label>
              <input style={input} name="summary" required />
              <label style={label}>Detail (optional)</label>
              <input style={input} name="detail" />
              <button style={button} disabled={busy} type="submit">
                Add evidence
              </button>
            </form>
          </section>

          <section style={box}>
            <h2>Draft</h2>
            <button style={button} disabled={busy || evidence.length === 0} onClick={() => void generateDraft()} type="button">
              Generate draft
            </button>
            {postmortem && (
              <div style={{ marginTop: 16 }}>
                <p>
                  <b>Status:</b> {postmortem.status}
                </p>
                <p>
                  <b>Summary:</b> {postmortem.summary}
                </p>
                <p>
                  <b>Root cause:</b> {postmortem.root_cause}
                </p>
                <p>
                  <b>Detection:</b> {postmortem.detection}
                </p>
                <p>
                  <b>Resolution:</b> {postmortem.resolution}
                </p>
                {postmortem.contributing_factors.length > 0 && (
                  <div>
                    <b>Contributing factors:</b>
                    <ul>
                      {postmortem.contributing_factors.map((factor) => (
                        <li key={factor}>{factor}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {postmortem.actions.length > 0 && (
                  <div>
                    <b>Actions:</b>
                    <ul>
                      {postmortem.actions.map((action) => (
                        <li key={action.id}>
                          {action.title} -- {action.owner} ({action.rationale})
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <p style={{ color: "#888", fontSize: 12 }}>
                  Cited evidence: {postmortem.cited_evidence_ids.length} / unsupported claims dropped:{" "}
                  {postmortem.unsupported_claims_dropped}
                </p>
                {postmortem.status !== "published" && (
                  <button style={button} disabled={busy} onClick={() => void publish()} type="button">
                    Publish
                  </button>
                )}
                {postmortem.approved_by && (
                  <p style={{ color: "#888", fontSize: 12 }}>
                    Approved by {postmortem.approved_by} at {new Date(postmortem.approved_at ?? 0).toLocaleString()}
                  </p>
                )}
              </div>
            )}
          </section>
        </>
      )}

      {message && <p role="status">{message}</p>}
    </>
  );
}
