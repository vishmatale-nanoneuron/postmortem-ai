import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const API_ORIGIN = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

// No CDN scripts, no external fonts, no third-party embeds anywhere in this
// app (checked: no next/font/google, no CDN references) -- the CSP below is
// deliberately tight rather than a generic template. script-src/style-src
// keep 'unsafe-inline' because Next.js injects inline hydration data/styles
// itself; a nonce-based CSP would remove that but is a larger, separate
// change. connect-src needs the API's own origin since the frontend calls
// FastAPI directly, cross-origin (see apps/web/app/api.ts).
// Dev only: Next.js's React Refresh runtime (hot reload) evaluates strings
// as JavaScript, which this CSP otherwise blocks outright -- and the
// failure is not graceful. It throws an uncaught EvalError in the main
// bundle, which means *no client component hydrates at all* in local dev:
// every form, the whole workspace, any useEffect. Found by loading the
// real dev server in a browser and reading the console, not by reasoning
// about the config. Production keeps the tight policy unchanged -- Next
// doesn't use eval in a production build, so this costs nothing there.
const isDev = process.env.NODE_ENV === "development";

const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  `connect-src 'self' ${API_ORIGIN}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  // Belt-and-suspenders alongside frame-ancestors above -- older browsers
  // that don't support CSP frame-ancestors still get clickjacking protection.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Two lockfiles exist by design: the repo root's (for scripts/migrate.mjs's
  // `postgres` dependency) and this app's own. Without this, Next.js guesses
  // the workspace root and warns on every build.
  outputFileTracingRoot: __dirname,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
