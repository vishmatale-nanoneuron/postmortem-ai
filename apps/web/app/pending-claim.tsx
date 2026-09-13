"use client";

import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { billing, type Claim } from "./api";
import { firstError, paymentReferenceSchema } from "./validation";

// Shared by the subscription's UPI/wire forms (workspace.tsx) and the
// Airlock pack form (airlock/airlock-panel.tsx). Its own module because
// the two importers would otherwise form a cycle -- workspace imports the
// panel, the panel imported workspace -- which a bundler tolerates until
// the day it doesn't.
const fieldLabel = "block text-xs font-medium text-muted mb-1";
const fieldInput =
  "w-full rounded-md border border-line px-3 py-2 mb-3 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";

export function PendingClaim({ claim, onChanged }: { claim: Claim; onChanged: () => void | Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function saveReference(form: FormData) {
    const reference = String(form.get("reference") || "").trim();
    const validationError = firstError(paymentReferenceSchema, { reference });
    if (validationError) return setError(validationError);
    setBusy(true);
    setError("");
    try {
      await billing.updateClaim(claim.id, reference);
      setEditing(false);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update reference.");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!window.confirm(`Withdraw reference "${claim.reference}"? You can submit a new one afterward.`)) return;
    setBusy(true);
    setError("");
    try {
      await billing.cancelClaim(claim.id);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel claim.");
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <form action={saveReference} className="rounded-md bg-paper px-3 py-2">
        <label className={fieldLabel} htmlFor={`claim-reference-${claim.id}`}>
          Transaction reference
        </label>
        <input
          id={`claim-reference-${claim.id}`}
          className={fieldInput}
          name="reference"
          defaultValue={claim.reference}
          required
        />
        <div className="flex gap-2">
          <Button variant="ink" size="app" disabled={busy} type="submit">
            Save
          </Button>
          <Button variant="line" size="app" disabled={busy} type="button" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </form>
    );
  }

  return (
    <div className="rounded-md bg-paper px-3 py-2 text-sm text-muted">
      <p>
        Reference <span className="font-medium text-ink">{claim.reference}</span> submitted, awaiting review.
      </p>
      <div className="mt-1.5 flex flex-wrap gap-3">
        <Link className="text-xs underline underline-offset-2" href={`/invoice/${claim.id}`} target="_blank" rel="noopener">
          Proforma invoice
        </Link>
        <button className="text-xs underline underline-offset-2" disabled={busy} type="button" onClick={() => setEditing(true)}>
          Edit
        </button>
        <button className="text-xs text-red-600 underline underline-offset-2" disabled={busy} type="button" onClick={() => void cancel()}>
          Withdraw
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
