"use client";

import { useEffect, useState } from "react";
import { auth, type AuthUser } from "./auth";
import { GroundingExample, Hero, HowItWorks, IntegrationLogos, SiteFooter, SiteHeader, WhatThisIsnt } from "./landing";
import { AirlockHero } from "./airlock/airlock-hero";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { emailOnlySchema, firstError, loginSchema, registerSchema } from "./validation";
import { fieldLabel } from "./dashboard-shared";
import dynamic from "next/dynamic";

// Loaded only once a session is confirmed: a signed-out visitor -- most
// first-time visitors -- never downloads the workspace, the founder
// dashboard or the Airlock panels. What they get is the landing below.
const SignedInWorkspace = dynamic(() => import("./signed-in-workspace"), { ssr: false });


// Auth gate: defaults to the logged-out landing/sign-in view, since that's
// what Next.js actually renders server-side for a "use client" component's
// initial state -- a curl request, a crawler, or a social-link preview
// never runs the useEffect below, so if the default were a bare loading
// state (or null) they'd see an empty page instead of the branded landing
// content. Real signed-in users still only see it for one render before
// the GET /v1/auth/me check below swaps them to the real workspace --
// nothing incident-related renders or fetches until that positively
// confirms a signed-in user.

export default function Workspace() {
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    // checkSession(), not me() -- me() 401s for every signed-out visitor,
    // which is most first-time visitors on this exact mount-time check.
    // See auth.ts's checkSession for why (a real Lighthouse Best
    // Practices finding, not a style preference).
    auth
      .checkSession()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  if (!user) return <AuthGate onSignedIn={setUser} />;

  return <SignedInWorkspace user={user} setUser={setUser} />;
}

function AuthGate({ onSignedIn }: { onSignedIn: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<"login" | "register" | "forgot">("login");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(form: FormData) {
    setError("");
    setMessage("");
    const email = String(form.get("email"));

    if (mode === "forgot") {
      const validationError = firstError(emailOnlySchema, { email });
      if (validationError) return setError(validationError);
      setBusy(true);
      try {
        await auth.requestPasswordReset(email);
        // Always the same message whether or not the email is registered
        // -- the backend never reveals that distinction either.
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
      onSignedIn(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  }

  const heading = mode === "login" ? "Welcome back" : mode === "register" ? "Get started" : "Reset your password";
  const subheading =
    mode === "login"
      ? "Log in to your account."
      : mode === "register"
        ? "Create your account to get started."
        : "Enter your email and we'll send you a link to choose a new password.";

  return (
    <>
      <SiteHeader />
      <main>
      {/* Airlock first: it is the main product. PostMortem AI follows as
          its own labelled section, with the sign-in card that is still the
          site's only paid conversion. */}
      <AirlockHero />
      <Hero />
      <GroundingExample />
      <HowItWorks />
      <IntegrationLogos />
      <div id="get-started" className="mx-auto mb-16 max-w-sm px-4">
        <Card className="animate-in fade-in slide-in-from-bottom-1 rounded-xl border border-line bg-white p-6 text-ink shadow-lg shadow-ink/5 duration-500">
          <h2 className="mb-1 text-lg font-semibold text-ink">{heading}</h2>
          <p className="mb-4 text-sm text-muted">{subheading}</p>
          <form action={submit}>
            <Label className={fieldLabel} htmlFor="auth-email">
              Email
            </Label>
            <Input
              id="auth-email"
              className="mb-3 rounded-md border-line text-ink focus-visible:ring-accent/30"
              name="email"
              type="email"
              autoComplete="email"
              required
            />
            {mode !== "forgot" && (
              <>
                <Label className={fieldLabel} htmlFor="auth-password">
                  Password
                </Label>
                <Input
                  id="auth-password"
                  className="mb-3 rounded-md border-line text-ink focus-visible:ring-accent/30"
                  name="password"
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  minLength={8}
                  required
                />
              </>
            )}
            <Button variant="ink" size="app" className="w-full" disabled={busy} type="submit">
              {mode === "login" ? "Log in" : mode === "register" ? "Create account" : "Send reset link"}
            </Button>
          </form>
          {message && (
            <Alert role="status" className="mt-3 animate-in fade-in border-accent/30 bg-accent/10 text-accent">
              <AlertDescription className="text-accent">{message}</AlertDescription>
            </Alert>
          )}
          {error && (
            <Alert role="status" variant="destructive" className="mt-3 animate-in fade-in border-red-200 bg-red-50">
              <AlertDescription className="text-red-700">{error}</AlertDescription>
            </Alert>
          )}
          {mode === "login" && (
            <p className="mt-2 text-sm text-muted">
              <button
                className="font-medium text-ink underline underline-offset-2"
                type="button"
                onClick={() => {
                  setMode("forgot");
                  setError("");
                  setMessage("");
                }}
              >
                Forgot password?
              </button>
            </p>
          )}
          <p className="mt-3 text-sm text-muted">
            {mode === "login" && (
              <>
                No account yet?{" "}
                <button
                  className="font-medium text-ink underline underline-offset-2"
                  type="button"
                  onClick={() => {
                    setMode("register");
                    setError("");
                    setMessage("");
                  }}
                >
                  Create one
                </button>
              </>
            )}
            {mode === "register" && (
              <>
                Already have an account?{" "}
                <button
                  className="font-medium text-ink underline underline-offset-2"
                  type="button"
                  onClick={() => {
                    setMode("login");
                    setError("");
                    setMessage("");
                  }}
                >
                  Log in
                </button>
              </>
            )}
            {mode === "forgot" && (
              <button
                className="font-medium text-ink underline underline-offset-2"
                type="button"
                onClick={() => {
                  setMode("login");
                  setError("");
                  setMessage("");
                }}
              >
                Back to log in
              </button>
            )}
          </p>
        </Card>
      </div>
      <WhatThisIsnt />
      </main>
      <SiteFooter />
    </>
  );
}

