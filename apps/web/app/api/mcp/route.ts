// Frontend MCP federation: proxies MCP streamable-HTTP requests to the
// real backend /mcp server under the CALLER'S OWN session. Reads
// mcp_session_token, a same-value MIRROR of the backend's session_token
// cookie -- session_token itself is set on the backend's own origin
// (postmortem-ai-api.vercel.app) and a browser never sends an
// origin-scoped cookie cross-origin to this frontend's domain, so this
// server genuinely cannot read it directly. See /api/session/route.ts
// (which creates the mirror) and auth.ts's mintMcpSession() (which calls
// it, client-side, after every login/register/me resolution) for how it
// gets here. This is a deliberate single-authorization-decision design
// (the backend's MCPBearerAuthMiddleware is the one place access is
// actually decided, same as apps/web never re-implementing incident/
// postmortem business logic of its own) rather than a second, parallel
// auth check here that could drift from the backend's -- this route
// forwards the token as Authorization: Bearer and lets the backend
// re-verify it exactly as it would for a direct MCP client.
//
// No tool logic lives in this file -- it is a pure reverse proxy over the
// MCP wire protocol (JSON-RPC over POST, SSE over GET, session teardown
// over DELETE). A browser-based MCP client (or a script using this app's
// own session) talks to /api/mcp exactly as it would talk to the backend
// directly, just same-origin.

import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

// Headers stripped when forwarding in either direction -- hop-by-hop or
// meaningless across the proxy boundary (Host/Content-Length get
// recomputed by fetch/Next.js itself; Connection is HTTP/1.1-only).
const STRIPPED_REQUEST_HEADERS = new Set(["host", "content-length", "connection", "cookie", "authorization"]);
const STRIPPED_RESPONSE_HEADERS = new Set(["content-length", "connection", "transfer-encoding"]);

async function proxy(request: Request): Promise<Response> {
  const sessionToken = (await cookies()).get("mcp_session_token")?.value;
  if (!sessionToken) {
    return Response.json({ error: "Not signed in -- call POST /api/session first" }, { status: 401 });
  }

  const forwardHeaders = new Headers();
  for (const [key, value] of request.headers) {
    if (!STRIPPED_REQUEST_HEADERS.has(key.toLowerCase())) forwardHeaders.set(key, value);
  }
  forwardHeaders.set("authorization", `Bearer ${sessionToken}`);

  const hasBody = request.method !== "GET" && request.method !== "HEAD" && request.method !== "DELETE";
  const upstream = await fetch(`${API_BASE}/mcp/`, {
    method: request.method,
    headers: forwardHeaders,
    body: hasBody ? request.body : undefined,
    // Node's fetch requires this for a streamed request body.
    ...(hasBody ? { duplex: "half" } : {}),
    cache: "no-store",
  } as RequestInit);

  const responseHeaders = new Headers();
  for (const [key, value] of upstream.headers) {
    if (!STRIPPED_RESPONSE_HEADERS.has(key.toLowerCase())) responseHeaders.set(key, value);
  }

  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export async function GET(request: Request): Promise<Response> {
  return proxy(request);
}

export async function POST(request: Request): Promise<Response> {
  return proxy(request);
}

export async function DELETE(request: Request): Promise<Response> {
  return proxy(request);
}
