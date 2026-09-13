"use client";

// The last line: an error in the root layout itself, where error.tsx
// cannot render because the layout is what failed. Must supply its own
// <html> and <body>, and uses no app styles because they may be what
// broke. Deliberately plain.
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0, padding: "6rem 1.5rem", color: "#171a1c" }}>
        <main style={{ maxWidth: 560, margin: "0 auto" }}>
          <p style={{ fontSize: 12, letterSpacing: "0.1em", textTransform: "uppercase", color: "#666" }}>Something broke</p>
          <h1 style={{ fontSize: 24, margin: "0.5rem 0 0" }}>The site failed to load.</h1>
          <p style={{ fontSize: 14, lineHeight: 1.6, color: "#555" }}>
            The fault is on our side and has been logged{error.digest ? ` (reference ${error.digest})` : ""}. The
            API and your data are unaffected; see the status page at /status.
          </p>
          <button
            type="button"
            onClick={() => reset()}
            style={{ marginTop: "1.5rem", padding: "0.5rem 0.9rem", fontSize: 13, cursor: "pointer" }}
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
