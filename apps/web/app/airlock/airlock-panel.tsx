"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  airlock,
  type AirlockApiKey,
  type AirlockCredits,
  type AirlockCurrency,
  type AirlockPricing,
  type Claim,
} from "../api";
import { firstError, paymentReferenceSchema } from "../validation";
import { AirlockMark } from "./airlock-mark";
import { PendingClaim } from "../pending-claim";

// The Airlock section of the client dashboard: balance, keys, buying more,
// and the statement. Everything that spends or grants money lives behind
// the backend's CQRS handlers; this component only ever asks and shows.

const card =
  "block gap-0 animate-in fade-in slide-in-from-bottom-1 rounded-lg border border-line bg-white p-4 py-4 text-ink shadow-sm ring-0 duration-500 mb-4";
const fieldLabel = "block text-xs font-medium text-muted mb-1";
const fieldInput =
  "w-full rounded-md border border-line px-3 py-2 mb-3 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";

const SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", GBP: "£", EUR: "€" };

function money(currency: string, amount: number): string {
  return `${SYMBOLS[currency] ?? currency + " "}${amount.toLocaleString("en-US")}`;
}

function when(ms: number): string {
  return new Date(ms).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function AirlockPanel({ isFounder }: { isFounder: boolean }) {
  const [credits, setCredits] = useState<AirlockCredits | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setCredits(await airlock.credits());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your Airlock balance.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <section id="client-airlock" aria-labelledby="airlock-panel-heading">
      <Card className={card}>
        <div className="mb-1 flex items-center gap-2">
          <AirlockMark size={18} />
          <h2 id="airlock-panel-heading" className="text-base font-semibold">
            Airlock
          </h2>
        </div>
        <p className="mb-4 text-xs text-muted">
          Prompt-injection and exfiltration guard for your agents. One credit per scan, prepaid.{" "}
          {isFounder && <span className="text-ink">Your founder account scans without spending credits.</span>}
        </p>

        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Credits left" value={credits ? credits.balance : null} emphasis />
          <Stat label="Used, 30 days" value={credits ? credits.used_last_30d : null} />
          <Stat label="Used, all time" value={credits ? credits.used_total : null} />
          <Stat label="Bought, all time" value={credits ? credits.purchased_total : null} />
        </div>
        {credits && credits.balance === 0 && !isFounder && (
          <p className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            No credits. Every scan and egress check will answer <span className="font-mono">402</span> until you buy
            a pack below.
          </p>
        )}
        {error && (
          <p role="status" className="mb-3 text-sm text-red-600">
            {error}
          </p>
        )}

        <Keys />
        {/* The founder is not metered, so there is nothing for them to buy. */}
        {!isFounder && <BuyCredits onChanged={refresh} />}
        {credits && credits.statement.length > 0 && <Statement entries={credits.statement} />}
      </Card>
    </section>
  );
}

function Stat({ label, value, emphasis = false }: { label: string; value: number | null; emphasis?: boolean }) {
  return (
    <div className="rounded-md bg-paper px-3 py-2">
      <div className="text-[11px] font-medium tracking-wide text-muted uppercase">{label}</div>
      <div className={cn("font-mono text-lg tabular-nums", emphasis ? "text-ink" : "text-muted")}>
        {value === null ? "–" : value.toLocaleString("en-US")}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Keys. The secret appears exactly once, in the response to creation; the
// list endpoint never carries it, so the UI holds it in state until the
// user dismisses it and then it is gone for good.
// ---------------------------------------------------------------------------

function Keys() {
  const [keys, setKeys] = useState<AirlockApiKey[]>([]);
  const [fresh, setFresh] = useState<{ id: string; secret: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setKeys(await airlock.keys());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load keys.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function create(form: FormData) {
    const label = String(form.get("label") ?? "").trim();
    setBusy(true);
    setError("");
    try {
      const created = await airlock.createKey(label);
      setFresh({ id: created.id, secret: created.secret });
      setCopied(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create a key.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(key: AirlockApiKey) {
    if (!window.confirm(`Revoke ${key.prefix}…? Any agent using it will get 401 immediately.`)) return;
    setBusy(true);
    setError("");
    try {
      await airlock.revokeKey(key.id);
      if (fresh?.id === key.id) setFresh(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not revoke the key.");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!fresh) return;
    try {
      await navigator.clipboard.writeText(fresh.secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be denied; the key is still visible to select by hand.
    }
  }

  const active = keys.filter((k) => k.revoked_at === null);

  return (
    <div className="mb-4">
      <h3 className="mb-1 text-sm font-semibold">API keys</h3>
      <p className="mb-2 text-xs text-muted">
        Send a key as <span className="font-mono">X-Airlock-Key</span> on every call. A key is shown once, when you
        create it; we keep only a hash.
      </p>

      {fresh && (
        <div className="mb-3 rounded-md border border-line bg-paper px-3 py-2">
          <p className="mb-1 text-xs font-medium text-ink">Copy this key now. It will not be shown again.</p>
          <div className="flex gap-2">
            <input
              className={`${fieldInput} mb-0 font-mono text-xs`}
              value={fresh.secret}
              readOnly
              aria-label="Your new Airlock API key"
              onFocus={(e) => e.currentTarget.select()}
            />
            <Button variant="line" size="app" type="button" onClick={() => void copy()}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          <button
            className="mt-2 text-xs text-muted underline underline-offset-2"
            type="button"
            onClick={() => setFresh(null)}
          >
            I have saved it
          </button>
        </div>
      )}

      {active.length > 0 && (
        <ul className="mb-3 divide-y divide-line rounded-md border border-line">
          {active.map((key) => (
            <li key={key.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
              <div className="min-w-0">
                <span className="font-mono text-xs">{key.prefix}…</span>
                {key.label && <span className="ml-2 text-ink">{key.label}</span>}
                <div className="text-xs text-muted">
                  Created {when(key.created_at)}
                  {key.last_used_at ? ` · last used ${when(key.last_used_at)}` : " · never used"}
                </div>
              </div>
              <button
                className="text-xs text-red-600 underline underline-offset-2"
                disabled={busy}
                type="button"
                onClick={() => void revoke(key)}
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}

      <form action={create} className="flex flex-wrap items-end gap-2">
        <div className="min-w-[12rem] flex-1">
          <label className={fieldLabel} htmlFor="airlock-key-label">
            Label (optional)
          </label>
          <input id="airlock-key-label" className={`${fieldInput} mb-0`} name="label" placeholder="prod agent" maxLength={80} />
        </div>
        <Button variant="ink" size="app" disabled={busy} type="submit">
          {busy ? "Working…" : active.length === 0 ? "Create your first key" : "Create key"}
        </Button>
      </form>
      {error && (
        <p role="status" className="mt-2 text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Buying. Same shape as the subscription's UpiPayment/WirePayment: pick
// currency and packs, have the payee details emailed to your own address,
// pay, submit the reference, wait for the founder's approval. Nothing here
// grants a credit -- approval does (founder.py).
// ---------------------------------------------------------------------------

function BuyCredits({ onChanged }: { onChanged: () => void | Promise<void> }) {
  const [pricing, setPricing] = useState<AirlockPricing | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [currency, setCurrency] = useState<AirlockCurrency>("INR");
  const [packs, setPacks] = useState(1);
  const [busy, setBusy] = useState(false);
  const [emailing, setEmailing] = useState(false);
  const [detailsSent, setDetailsSent] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [p, c] = await Promise.all([airlock.pricing(), airlock.myClaims()]);
      setPricing(p);
      setClaims(c);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load pricing.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const price = pricing?.prices.find((p) => p.currency === currency) ?? null;
  const amount = price ? price.amount * packs : 0;
  const scans = pricing ? pricing.scans_per_pack * packs : 0;
  const pending = claims.find((c) => c.status === "pending");

  async function emailDetails() {
    setEmailing(true);
    setError("");
    try {
      await airlock.emailDetails(currency, packs);
      setDetailsSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not email the payment details.");
    } finally {
      setEmailing(false);
    }
  }

  async function submit(form: FormData) {
    const reference = String(form.get("reference") ?? "").trim();
    const validationError = firstError(paymentReferenceSchema, { reference });
    if (validationError) return setError(validationError);
    setBusy(true);
    setError("");
    try {
      await airlock.submitClaim(currency, reference, packs);
      await refresh();
      await onChanged();
      setMessage(
        `Submitted. Once the payment is verified -- usually within the day -- ${scans.toLocaleString("en-US")} credits land on this account and you get an email.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit the reference.");
    } finally {
      setBusy(false);
    }
  }

  if (!pricing) return null;

  return (
    <div className="mb-4">
      <h3 className="mb-1 text-sm font-semibold">Buy credits</h3>
      <p className="mb-2 text-xs text-muted">
        {pricing.scans_per_pack.toLocaleString("en-US")} scans per pack. Credits do not expire. UPI for INR;
        international SWIFT wire for USD, GBP and EUR (wire fees make larger orders the sensible choice there).
      </p>

      <fieldset
        className="mb-3"
        onChange={() => {
          setDetailsSent(false);
          setMessage("");
        }}
      >
        <legend className="sr-only">Currency</legend>
        <div className="flex flex-wrap gap-3">
          {pricing.prices.map((p) => (
            <label key={p.currency} className={cn("flex items-center gap-2 text-sm", !p.configured && "opacity-50")}>
              <input
                type="radio"
                name="airlock-currency"
                value={p.currency}
                checked={currency === p.currency}
                disabled={!p.configured}
                onChange={() => setCurrency(p.currency as AirlockCurrency)}
              />
              <span>
                {money(p.currency, p.amount)} <span className="text-muted">/ pack · {p.method.toUpperCase()}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div>
          <label className={fieldLabel} htmlFor="airlock-packs">
            Packs
          </label>
          <input
            id="airlock-packs"
            className={`${fieldInput} mb-0 w-24`}
            type="number"
            min={1}
            max={pricing.max_packs_per_claim}
            value={packs}
            onChange={(e) => {
              const next = Math.max(1, Math.min(pricing.max_packs_per_claim, Number(e.target.value) || 1));
              setPacks(next);
              setDetailsSent(false);
            }}
          />
        </div>
        <p className="pb-2 text-sm">
          <span className="font-medium text-ink">{price ? money(currency, amount) : "–"}</span>{" "}
          <span className="text-muted">for {scans.toLocaleString("en-US")} scans</span>
        </p>
      </div>

      {price && !price.configured ? (
        <p className="mb-3 text-sm text-muted">{price.method.toUpperCase()} payment is not configured yet.</p>
      ) : detailsSent ? (
        <p className="mb-3 text-sm text-accent">
          Sent to your email -- check your inbox (and spam) for where to pay.{" "}
          <button className="underline underline-offset-2" onClick={() => void emailDetails()} type="button">
            Send again
          </button>
        </p>
      ) : (
        <p className="mb-3 text-sm text-muted">
          <button
            className="underline underline-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={emailing}
            onClick={() => void emailDetails()}
            type="button"
          >
            {emailing ? "Sending…" : "Email me the payment details"}
          </button>
          , pay, then submit the transaction reference below.
        </p>
      )}

      {pending ? (
        <PendingClaim claim={pending} onChanged={refresh} />
      ) : (
        <form action={submit}>
          <label className={fieldLabel} htmlFor="airlock-reference">
            Transaction reference (UTR for UPI, your bank&apos;s reference for a wire)
          </label>
          <input id="airlock-reference" className={fieldInput} name="reference" placeholder="e.g. 123456789012" required />
          <Button variant="ink" size="app" disabled={busy || !price?.configured} type="submit">
            {busy ? "Submitting…" : "I've paid -- submit reference"}
          </Button>
        </form>
      )}
      {message && <p className="mt-3 text-sm text-accent">{message}</p>}
      {claims.some((c) => c.status === "rejected") && !pending && (
        <p className="mt-3 text-sm text-red-600">
          A previous reference could not be matched -- check the amount and the reference, then resubmit.
        </p>
      )}
      {error && (
        <p role="status" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The statement. Purchases and grants as their own lines; scans rolled up
// per key per day by the backend so a month of usage is readable.
// ---------------------------------------------------------------------------

function Statement({ entries }: { entries: AirlockCredits["statement"] }) {
  return (
    <div>
      <h3 className="mb-1 text-sm font-semibold">Statement</h3>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-paper text-muted">
            <tr>
              <th className="px-3 py-1.5 font-medium">Date</th>
              <th className="px-3 py-1.5 font-medium">What</th>
              <th className="px-3 py-1.5 font-medium">Key</th>
              <th className="px-3 py-1.5 text-right font-medium">Credits</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {entries.map((entry, index) => (
              <tr key={`${entry.created_at}-${index}`}>
                <td className="px-3 py-1.5 whitespace-nowrap text-muted">{when(entry.created_at)}</td>
                <td className="px-3 py-1.5">
                  {entry.reason === "usage"
                    ? "Scans"
                    : entry.reason === "purchase"
                      ? "Pack purchased"
                      : entry.reason.charAt(0).toUpperCase() + entry.reason.slice(1)}
                  {entry.reference && entry.reason !== "purchase" && (
                    <span className="ml-1 text-muted">· {entry.reference}</span>
                  )}
                </td>
                <td className="px-3 py-1.5 font-mono text-muted">{entry.key_prefix ? `${entry.key_prefix}…` : "dashboard"}</td>
                <td
                  className={cn(
                    "px-3 py-1.5 text-right font-mono tabular-nums",
                    entry.delta > 0 ? "text-emerald-700" : "text-ink",
                  )}
                >
                  {entry.delta > 0 ? `+${entry.delta.toLocaleString("en-US")}` : entry.delta.toLocaleString("en-US")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
