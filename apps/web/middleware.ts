import { NextRequest, NextResponse } from "next/server";

// Makes /founder genuinely invisible to the world, not just unindexed.
// Before this, the route was reachable by anyone who guessed/shared the
// URL -- they'd see a real login form and could attempt logins against it
// (even though non-founder accounts were denied server-side after auth).
// Now: no valid key -> a plain 404, indistinguishable from a route that
// doesn't exist at all. No exception for a misconfigured secret -- if
// FOUNDER_ACCESS_KEY isn't set, the page can never be unlocked by anyone,
// which fails toward hidden rather than toward exposed.
const FOUNDER_PATH_PREFIX = "/founder";
const GATE_COOKIE = "founder_gate";
const NOT_FOUND = new NextResponse("Not Found", { status: 404 });

export function middleware(request: NextRequest): NextResponse {
  const { pathname, searchParams } = request.nextUrl;
  if (!pathname.startsWith(FOUNDER_PATH_PREFIX)) {
    return NextResponse.next();
  }

  const secret = process.env.FOUNDER_ACCESS_KEY;
  if (!secret) {
    return NOT_FOUND;
  }

  if (request.cookies.get(GATE_COOKIE)?.value === secret) {
    return NextResponse.next();
  }

  const keyParam = searchParams.get("key");
  if (keyParam === secret) {
    // Strip ?key=... from the visible URL (it'd otherwise sit in browser
    // history / could get shared by accident) and remember the unlock via
    // an HttpOnly cookie scoped to this path instead.
    const response = NextResponse.redirect(new URL(pathname, request.url));
    response.cookies.set(GATE_COOKIE, secret, {
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: FOUNDER_PATH_PREFIX,
      maxAge: 60 * 60 * 24 * 365,
    });
    return response;
  }

  return NOT_FOUND;
}

export const config = {
  matcher: ["/founder/:path*"],
};
