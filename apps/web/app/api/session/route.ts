// Mirrors the backend's session JWT into a cookie on THIS (frontend)
// origin, purely so /api/mcp (a same-origin Next.js route) can read it.
// Called client-side, once, after auth.me()/login/register resolve --
// see auth.ts's mintMcpSession(). The token itself is unchanged; this
// does not create or extend a session, it copies an existing one's value
// into a second, frontend-scoped cookie. Never trust this cookie for
// authorization decisions on its own -- the backend re-verifies it (via
// the same verify_token used everywhere else) on every /mcp request; this
// route is transport, not an authority.
import { cookies } from "next/headers";

const COOKIE_NAME = "mcp_session_token";

export async function POST(request: Request): Promise<Response> {
  let token: unknown;
  try {
    ({ token } = await request.json());
  } catch {
    return Response.json({ error: "Invalid request body" }, { status: 400 });
  }
  if (typeof token !== "string" || token.length === 0 || token.length > 4096) {
    return Response.json({ error: "Invalid token" }, { status: 400 });
  }

  const store = await cookies();
  store.set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/api/mcp",
    maxAge: 60 * 60 * 24 * 7,
  });
  return Response.json({ ok: true });
}

export async function DELETE(): Promise<Response> {
  const store = await cookies();
  store.delete(COOKIE_NAME);
  return Response.json({ ok: true });
}
