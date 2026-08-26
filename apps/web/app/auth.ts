const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type AuthUser = {
  id: string;
  email: string;
  is_founder: boolean;
  subscription_status: string;
  has_active_subscription: boolean;
};

async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include", // send/receive the session cookie across the frontend<->backend origin
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

// Mirrors this browser's backend session into a same-origin cookie the
// frontend's own /api/mcp route can read (cookies are origin-scoped;
// the backend's session_token cookie is never sent to this frontend's
// domain on its own). Best-effort and silent on failure -- MCP access is
// an added capability, not something the rest of the app depends on, so
// a failure here must never surface as a login/registration error.
async function mintMcpSession(): Promise<void> {
  try {
    const { token } = await authRequest<{ token: string }>("/v1/auth/session-token");
    await fetch("/api/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }),
    });
  } catch {
    // Non-fatal -- see comment above.
  }
}

async function withMintedMcpSession(user: AuthUser): Promise<AuthUser> {
  await mintMcpSession();
  return user;
}

export const auth = {
  me: () => authRequest<AuthUser>("/v1/auth/me").then(withMintedMcpSession),
  register: (email: string, password: string) =>
    authRequest<AuthUser>("/v1/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }).then(
      withMintedMcpSession,
    ),
  login: (email: string, password: string) =>
    authRequest<AuthUser>("/v1/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }).then(
      withMintedMcpSession,
    ),
  logout: async () => {
    const result = await authRequest<{ ok: boolean }>("/v1/auth/logout", { method: "POST" });
    await fetch("/api/session", { method: "DELETE" }).catch(() => {});
    return result;
  },
  // PUT -- full replace: both email and password are required.
  replaceAccount: (email: string, password: string) =>
    authRequest<AuthUser>("/v1/auth/me", { method: "PUT", body: JSON.stringify({ email, password }) }),
  // PATCH -- partial update: only the fields passed change.
  updateAccount: (fields: { email?: string; password?: string }) =>
    authRequest<AuthUser>("/v1/auth/me", { method: "PATCH", body: JSON.stringify(fields) }),
  deleteAccount: async () => {
    const response = await fetch(`${API_BASE}/v1/auth/me`, { method: "DELETE", credentials: "include" });
    if (!response.ok && response.status !== 204) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail ?? `Request failed: ${response.status}`);
    }
    await fetch("/api/session", { method: "DELETE" }).catch(() => {});
  },
};
