/**
 * The founder gate's 404 response used to be a module-level constant:
 *
 *   const NOT_FOUND = new NextResponse("Not Found", { status: 404 });
 *
 * A Response's body is a single-use stream, so one shared instance served its
 * body to the first request on a warm serverless instance and an EMPTY body to
 * every request after it. Confirmed against production before the fix: six
 * consecutive GETs to /founder returned 404 with 9, 0, 0, 0, 0, 0 bytes.
 *
 * The status code was never affected, so the gate never leaked -- which is
 * exactly why it survived unnoticed. These tests assert on the body, not just
 * the status, because only the body ever showed the bug.
 */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it } from "vitest";

import { middleware } from "../middleware";

const SECRET = "test-founder-key";

function get(path: string): NextRequest {
  return new NextRequest(new URL(path, "https://example.test"));
}

describe("founder gate middleware", () => {
  beforeEach(() => {
    process.env.FOUNDER_ACCESS_KEY = SECRET;
  });

  it("returns a readable body on every call, not just the first", async () => {
    // The actual regression. Two calls in the same module instance is exactly
    // what a warm serverless instance does.
    const first = middleware(get("/founder"));
    const second = middleware(get("/founder"));
    const third = middleware(get("/founder"));

    expect(first.status).toBe(404);
    expect(second.status).toBe(404);
    expect(third.status).toBe(404);

    expect(await first.text()).toBe("Not Found");
    expect(await second.text()).toBe("Not Found");
    expect(await third.text()).toBe("Not Found");
  });

  it("404s a wrong key without consuming the next caller's body", async () => {
    const wrong = middleware(get("/founder?key=nope"));
    const alsoWrong = middleware(get("/founder?key=also-nope"));

    expect(wrong.status).toBe(404);
    expect(alsoWrong.status).toBe(404);
    expect(await wrong.text()).toBe("Not Found");
    expect(await alsoWrong.text()).toBe("Not Found");
  });

  it("fails closed with no key configured, repeatably", async () => {
    delete process.env.FOUNDER_ACCESS_KEY;

    const first = middleware(get("/founder"));
    const second = middleware(get("/founder"));

    expect(first.status).toBe(404);
    expect(second.status).toBe(404);
    expect(await first.text()).toBe("Not Found");
    expect(await second.text()).toBe("Not Found");
  });

  it("still unlocks on the correct key and strips it from the URL", async () => {
    const response = middleware(get(`/founder?key=${SECRET}`));

    // A redirect, so the key doesn't linger in browser history.
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("https://example.test/founder");
    expect(response.cookies.get("founder_gate")?.value).toBe(SECRET);
  });

  it("leaves non-founder paths alone", () => {
    expect(middleware(get("/pricing")).status).toBe(200);
  });
});
