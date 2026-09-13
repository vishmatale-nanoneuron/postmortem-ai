// Migrations are forward-only and append-only: a file that has shipped is
// never edited, because production already ran it and the edit would run
// nowhere. Nothing enforced that. This pins a SHA-256 of every migration
// in supabase/migrations/CHECKSUMS.json and fails CI when a shipped file
// changes without its checksum being updated in the same commit -- the
// diff then shows a reviewer exactly what happened. Adding a new file is
// allowed with `--update`, which writes the new entry.
//
//   node scripts/check-migrations.mjs            # verify (CI)
//   node scripts/check-migrations.mjs --update   # record new files
//
// Also refuses the statements that need a reviewed process rather than a
// routine migration (DROP TABLE / DROP SCHEMA / TRUNCATE) and the one that
// cannot run inside the migration runner's transaction (CREATE INDEX
// CONCURRENTLY).

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

const directory = path.resolve("supabase/migrations");
const pinsFile = path.join(directory, "CHECKSUMS.json");
const update = process.argv.includes("--update");

const files = (await fs.readdir(directory))
  .filter((file) => /^\d{4}_.*\.sql$/.test(file))
  .sort((left, right) => left.localeCompare(right));

if (files.length === 0) throw new Error("No migration files found");
const versions = files.map((file) => file.slice(0, 4));
if (new Set(versions).size !== versions.length) {
  throw new Error(`Duplicate migration numbers: ${versions.filter((v, i) => versions.indexOf(v) !== i).join(", ")}`);
}

let pins = {};
try {
  pins = JSON.parse(await fs.readFile(pinsFile, "utf8"));
} catch {
  if (!update) throw new Error(`${path.relative(process.cwd(), pinsFile)} is missing; run with --update to create it`);
}

const problems = [];
const next = {};
for (const file of files) {
  const sql = await fs.readFile(path.join(directory, file), "utf8");
  // Statement starts only, with comments and string literals removed: the
  // append-only trigger in 0031 mentions TRUNCATE in order to refuse it,
  // and a comment explaining why a table is not dropped is not a DROP.
  const code = sql.replace(/--[^\n]*/g, "").replace(/'(?:[^']|'')*'/g, "''");
  if (/(?:^|;)\s*(?:DROP\s+(?:TABLE|SCHEMA)|TRUNCATE)\b/im.test(code)) {
    problems.push(`${file}: destructive statement (DROP TABLE / DROP SCHEMA / TRUNCATE) needs a reviewed process, not a routine migration`);
  }
  if (/CREATE\s+INDEX\s+CONCURRENTLY/i.test(sql)) {
    problems.push(`${file}: CREATE INDEX CONCURRENTLY cannot run inside the migration runner's transaction`);
  }
  const checksum = crypto.createHash("sha256").update(sql).digest("hex");
  next[file] = checksum;
  if (!(file in pins)) {
    if (!update) problems.push(`${file}: new migration is not recorded in CHECKSUMS.json (run: node scripts/check-migrations.mjs --update)`);
  } else if (pins[file] !== checksum) {
    problems.push(`${file}: content changed after it was recorded. A shipped migration is never edited; add a new numbered migration instead (or, if this file has NOT shipped anywhere, run --update and say so in the commit).`);
  }
}
for (const recorded of Object.keys(pins)) {
  if (!files.includes(recorded)) problems.push(`${recorded}: recorded in CHECKSUMS.json but the file is gone`);
}

if (problems.length > 0 && !update) {
  for (const problem of problems) console.error(`✗ ${problem}`);
  process.exit(1);
}
if (update) {
  await fs.writeFile(pinsFile, JSON.stringify(next, null, 2) + "\n");
  console.log(`Recorded ${files.length} migrations in ${path.relative(process.cwd(), pinsFile)}`);
} else {
  console.log(`${files.length} migrations verified against CHECKSUMS.json`);
}
