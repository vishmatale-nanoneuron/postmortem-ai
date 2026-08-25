import { z } from "zod";

// Mirrors the real backend constraints (apps/api/app/api/v1/postmortems.py's
// IncidentCreate/EvidenceCreate, apps/api/app/api/v1/auth.py's
// RegisterRequest/LoginRequest) so a client gets a clear, immediate error
// instead of round-tripping to the server first -- but the backend's own
// Pydantic validation stays the actual source of truth and is never
// bypassed; this is a UX layer on top of it, not a replacement for it.

export const registerSchema = z.object({
  email: z.email(),
  password: z.string().min(8).max(200),
});

export const loginSchema = z.object({
  email: z.email(),
  password: z.string().min(1).max(200),
});

export const incidentSchema = z.object({
  title: z.string().min(1).max(200),
  severity: z.enum(["sev1", "sev2", "sev3", "sev4"]),
  impact: z.string().max(500).optional(),
});

export const evidenceSchema = z.object({
  occurred_at: z.number().int().positive(),
  source: z.enum(["alert", "log", "deploy", "metric", "human_note", "customer_report"]),
  summary: z.string().min(1).max(500),
  detail: z.string().max(4000).optional(),
});

// Mirrors UpiClaimIn/WireClaimIn in apps/api/app/api/v1/billing.py -- both
// use the identical reference constraint, so one shared schema rather
// than two copies of the same rule.
export const paymentReferenceSchema = z.object({
  reference: z.string().min(4).max(200),
});

// Returns the first validation error message, or null if valid -- the
// shape every form on this page actually needs (one message to show the
// user), rather than making each call site deal with Zod's full issue
// array.
export function firstError<T>(schema: z.ZodType<T>, value: unknown): string | null {
  const result = schema.safeParse(value);
  if (result.success) return null;
  return result.error.issues[0]?.message ?? "Invalid input.";
}
