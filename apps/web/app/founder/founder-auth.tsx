"use client";
// Dedicated founder auth surface, separate from the public client
// login/register page. It reuses the same backend accounts and endpoints
// (auth.ts) -- there is no second password system, since a second auth
// system to keep in sync would be a bigger security liability than the
// separation it's meant to buy. What this page actually adds: it refuses
// to proceed for any account that isn't the founder email (generic denial,
// no leak of whether an email exists), it's not linked from the public
// site or indexed by search engines, and every attempt against the
// founder email is logged server-side (see api/v1/auth.py).
import { useState } from "react";
import { auth } from "../auth";
import { emailOnlySchema, firstError, loginSchema, registerSchema } from "../validation";

const card = "rounded-lg border border-line bg-white p-4 shadow-sm";
const fieldLabel = "block text-xs font-medium text-muted mb-1";
const fieldInput =
  "w-full rounded-md border border-line px-3 py-2 mb-3 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";
const primaryButton =
  "rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper transition hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-50";

export default function FounderAuth() {
  const [mode, setMode] = useState<"login" | "register" | "forgot">("login");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(form: FormData) {
    setError("");
    setMessage("");
    const email = String(form.get("email"));

    if (mode === "forgot") {
      // Same backend endpoint the client login uses -- founder auth is
      // the same account system, not a second one, so the same reset
      // flow applies. Identical message regardless of whether the email
      // is real or is the founder account, same reasoning as the
      // backend's own "never reveal whether an account exists" stance.
      const validationError = firstError(emailOnlySchema, { email });
      if (validationError) return setError(validationError);
      setBusy(true);
      try {
        await auth.requestPasswordReset(email);
        setMessage("If an account exists for that email, a reset link is on its way.");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not send the reset email.");
      } finally {
        setBusy(false);
      }
      return;
    }

    const password = String(form.get("password"));
    const schema = mode === "login" ? loginSchema : registerSchema;
    const validationError = firstError(schema, { email, password });
    if (validationError) return setError(validationError);

    setBusy(true);
    try {
      const user = mode === "login" ? await auth.login(email, password) : await auth.register(email, password);
      if (!user.is_founder) {
        // Never say "wrong account" vs "not founder" differently from a
        // plain auth failure -- a generic denial here, then sign the
        // session back out immediately rather than leaving a valid
        // non-founder session sitting on this page.
        await auth.logout();
        setError("Access denied.");
        return;
      }
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-4 py-10">
      <div className={card}>
        <h1 className="mb-1 text-lg font-semibold">Founder access</h1>
        <p className="mb-4 text-xs text-muted">
          {mode === "forgot"
            ? "Enter the founder account's email and we'll send a link to choose a new password."
            : "Not a client login. Access is restricted to one account."}
        </p>
        <form action={submit}>
          <label className={fieldLabel} htmlFor="founder-email">
            Email
          </label>
          <input
            className={fieldInput}
            id="founder-email"
            name="email"
            type="email"
            autoComplete="email"
            required
          />
          {mode !== "forgot" && (
            <>
              <label className={fieldLabel} htmlFor="founder-password">
                Password
              </label>
              <input
                className={fieldInput}
                id="founder-password"
                name="password"
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                minLength={8}
                required
              />
            </>
          )}
          <button className={`${primaryButton} w-full`} disabled={busy} type="submit">
            {busy
              ? "..."
              : mode === "login"
                ? "Log in"
                : mode === "register"
                  ? "Register founder account"
                  : "Send reset link"}
          </button>
        </form>
        {message && (
          <p role="status" className="mt-3 text-sm text-accent">
            {message}
          </p>
        )}
        {error && (
          <p role="status" className="mt-3 text-sm text-red-600">
            {error}
          </p>
        )}
        {mode === "login" && (
          <button
            className="mt-3 block text-xs text-muted underline underline-offset-2"
            onClick={() => {
              setMode("forgot");
              setError("");
              setMessage("");
            }}
            type="button"
          >
            Forgot password?
          </button>
        )}
        <button
          className="mt-2 text-xs text-muted underline underline-offset-2"
          onClick={() => {
            setMode(mode === "register" ? "login" : mode === "forgot" ? "login" : "register");
            setError("");
            setMessage("");
          }}
          type="button"
        >
          {mode === "login"
            ? "First time -- register the founder account"
            : mode === "register"
              ? "Already registered -- log in"
              : "Back to log in"}
        </button>
      </div>
    </main>
  );
}
