import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Two lockfiles exist by design: the repo root's (for scripts/migrate.mjs's
  // `postgres` dependency) and this app's own. Without this, Next.js guesses
  // the workspace root and warns on every build.
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
