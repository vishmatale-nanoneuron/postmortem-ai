const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type AuthUser = { id: string; email: string; is_founder: boolean };

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

export const auth = {
  me: () => authRequest<AuthUser>("/v1/auth/me"),
  register: (email: string, password: string) =>
    authRequest<AuthUser>("/v1/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    authRequest<AuthUser>("/v1/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => authRequest<{ ok: boolean }>("/v1/auth/logout", { method: "POST" }),
};
