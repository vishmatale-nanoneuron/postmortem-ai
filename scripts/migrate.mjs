#!/usr/bin/env node
// Minimal forward-only migration runner: applies supabase/migrations/*.sql
// in filename order against DATABASE_URL, tracking what's applied in a
// schema_migrations table. No checksum verification or baseline machinery
// (unlike the more mature reference project's scripts/migrate-supabase.mjs)
// -- this is a single-developer MVP against one dev database; add that
// machinery back if this project grows multiple contributors/environments.
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import postgres from "postgres";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const migrationsDir = path.join(__dirname, "..", "supabase", "migrations");

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  console.error("DATABASE_URL is required");
  process.exit(1);
}

const sql = postgres(databaseUrl, {
  ssl: process.env.DATABASE_SSL_MODE === "disable" ? false : "require",
});

async function main() {
  await sql`CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
  )`;

  const files = readdirSync(migrationsDir)
    .filter((name) => name.endsWith(".sql"))
    .sort();

  for (const file of files) {
    const [{ exists }] = await sql`
      SELECT EXISTS(SELECT 1 FROM public.schema_migrations WHERE version = ${file}) AS exists
    `;
    if (exists) {
      console.log(`Already applied ${file}`);
      continue;
    }
    const contents = readFileSync(path.join(migrationsDir, file), "utf8");
    await sql.begin(async (tx) => {
      await tx.unsafe(contents);
      await tx`INSERT INTO public.schema_migrations (version) VALUES (${file})`;
    });
    console.log(`Applied ${file}`);
  }

  await sql.end();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
