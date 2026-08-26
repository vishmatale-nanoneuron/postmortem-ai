"use client";
// Reached via the link in the password-reset email (token in the query
// string) -- deliberately not indexed/crawled (see robots below): every
// URL here embeds a real, if short-lived and single-use, reset token.

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { auth } from "../auth";
import { firstError, passwordResetConfirmSchema } from "../validation";

const card = "rounded-lg border border-line bg-white p-4 shadow-sm mb-4";
const fieldLabel = "block text-xs font-medium text-muted mb-1";
const fieldInput =
  "w-full rounded-md border border-line px-3 py-2 mb-3 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";
const primaryButton =
  "rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper transition hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-50";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(form: FormData) {
    setError("");
    const newPassword = String(form.get("new_password"));
    const validationError = firstError(passwordResetConfirmSchema, { new_password: newPassword });
    if (validationError) return setError(validationError);
    if (!token) return setError("This reset link is missing its token -- use the link from the email directly.");

    setBusy(true);
    try {
      await auth.confirmPasswordReset(token, newPassword);
      setDone(true);
    } catch (err) {
      // The backend returns the same generic "Invalid or expired reset
      // link" for a garbage token, an expired one, and an already-used
      // one -- deliberately not distinguishing those (same enumeration
      // reasoning as the request endpoint).
      setError(err instanceof Error ? err.message : "Could not reset the password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-sm px-4 py-16">
      <div className={card}>
        <h1 className="mb-3 text-lg font-semibold">Choose a new password</h1>
        {done ? (
          <>
            <p className="text-sm text-accent">Your password has been reset. You can now log in with it.</p>
            <button className={`${primaryButton} mt-3 w-full`} type="button" onClick={() => router.push("/")}>
              Go to log in
            </button>
          </>
        ) : (
          <form action={submit}>
            <label className={fieldLabel}>New password</label>
            <input className={fieldInput} name="new_password" type="password" minLength={8} required autoFocus />
            <button className={`${primaryButton} w-full`} disabled={busy} type="submit">
              Reset password
            </button>
            {error && (
              <p role="status" className="mt-3 text-sm text-red-600">
                {error}
              </p>
            )}
          </form>
        )}
      </div>
    </main>
  );
}

export default function ResetPasswordPage() {
  // useSearchParams requires a Suspense boundary in the App Router (reads
  // from the URL at render time, which Next.js can't statically produce).
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}
