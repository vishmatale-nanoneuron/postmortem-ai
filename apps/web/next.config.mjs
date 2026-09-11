import { existsSync } from "node:fs";
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

// This app gets built two different ways, and the file-tracing root has to
// differ between them or one of the two breaks:
//
//   1. Scoped CLI deploy (`cd apps/web && vercel deploy --prod`) uploads ONLY
//      this directory, so this directory IS the build root. node_modules lives
//      here. Tracing root must be __dirname.
//   2. Git-triggered build with the Vercel project's Root Directory set to
//      apps/web clones the whole repo and installs the Bun workspace, which
//      HOISTS node_modules to the repo root -- outside __dirname. Tracing from
//      __dirname then silently omits server dependencies.
//
// (2) is not hypothetical: with a hardcoded `outputFileTracingRoot: __dirname`,
// setting Root Directory to apps/web produced a build that reported success and
// then served a persistent 500 on /status in production, while every other
// route stayed 200 -- because only that route's server-side dependencies fell
// outside the traced set. Detecting the layout instead of hardcoding either
// value keeps both paths working.
//
// The original reason for pinning this at all still holds: two lockfiles exist
// by design (the repo root's, for scripts/migrate.mjs's `postgres` dependency,
// and this app's own), so leaving it unset makes Next.js guess and warn.
const repoRoot = path.join(__dirname, "..", "..");
const isWorkspaceBuild = existsSync(path.join(repoRoot, "bun.lock"));

// The bare domain redirects to www. Until 2026-09-11, nanoneuron.ai (no
// www) was aliased to an unrelated 74-day-old deployment of a different
// product, while www.nanoneuron.ai served this one -- so the domain's own
// front door showed something other than what was being sold, and search
// engines (which fold apex and www into one site) indexed the domain as
// that other product. Kept in the app config rather than in the Vercel
// dashboard so it is in git, reviewable, and survives a project re-link.
// Host-matched so it only fires for the apex: preview URLs and localhost
// are untouched. `permanent` is a 308, which preserves method and body.
const APEX_HOST = "nanoneuron.ai";
const CANONICAL_ORIGIN = "https://www.nanoneuron.ai";

/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingRoot: isWorkspaceBuild ? repoRoot : __dirname,
  async redirects() {
    return [
      {
        source: "/:path*",
        has: [{ type: "host", value: APEX_HOST }],
        destination: `${CANONICAL_ORIGIN}/:path*`,
        permanent: true,
      },
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
