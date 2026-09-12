"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { joinAirlockWaitlist } from "../api";

// The only interactive element on the page, so /airlock itself stays a
// server component. Posts straight to FastAPI like every other form in this
// app (api.ts, credentials: "include") rather than through a Next route.
//
// The backend answers 202 whether the address is new or already on the
// list, deliberately -- so this component must not claim "you're on the
// list" in one case and "already registered" in the other, which would
// reintroduce exactly the enumeration the endpoint avoids.
export function WaitlistForm() {
  const [state, setState] = useState<"idle" | "sending" | "done">("idle");
  const [error, setError] = useState<string | null>(null);

  async function submit(form: FormData) {
    setError(null);
    setState("sending");
    try {
      await joinAirlockWaitlist({
        email: String(form.get("email") ?? ""),
        company: String(form.get("company") ?? "") || null,
        use_case: String(form.get("use_case") ?? "") || null,
      });
      setState("done");
    } catch (cause) {
      setState("idle");
      setError(cause instanceof Error ? cause.message : "Something went wrong. Try again.");
    }
  }

  if (state === "done") {
    return (
      <p className="rounded-md border border-line bg-paper px-3.5 py-3 text-sm text-ink" role="status">
        Recorded. You&apos;ll get one email when Airlock is hosted and the scanner is callable — nothing else, and
        no other use of the address.
      </p>
    );
  }

  return (
    <form action={submit} className="space-y-3">
      <div>
        <label className="mb-1 block text-sm font-medium text-ink" htmlFor="airlock-email">
          Work email
        </label>
        <input
          id="airlock-email"
          name="email"
          type="email"
          required
          autoComplete="email"
          placeholder="you@company.com"
          className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        />
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium text-ink" htmlFor="airlock-company">
          Company <span className="font-normal text-muted">(optional)</span>
        </label>
        <input
          id="airlock-company"
          name="company"
          type="text"
          maxLength={200}
          className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        />
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium text-ink" htmlFor="airlock-use-case">
          What would you point it at? <span className="font-normal text-muted">(optional)</span>
        </label>
        <textarea
          id="airlock-use-case"
          name="use_case"
          rows={3}
          maxLength={2000}
          placeholder="e.g. a support agent that reads customer tickets and can call refund tools"
          className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        />
        <p className="mt-1 text-xs text-muted">
          This is the useful part. The rules that exist today came from public payloads; the ones worth writing next
          come from what people are actually running.
        </p>
      </div>
      {error && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}
      <Button type="submit" size="app" disabled={state === "sending"}>
        {state === "sending" ? "Sending…" : "Get early access"}
      </Button>
    </form>
  );
}
