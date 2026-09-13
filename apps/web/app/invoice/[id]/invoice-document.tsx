"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { billing, type Invoice } from "../../api";

const SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", GBP: "£", EUR: "€" };

function money(currency: string, amount: number): string {
  return `${SYMBOLS[currency] ?? currency + " "}${amount.toLocaleString("en-US")}`;
}

function date(ms: number): string {
  return new Date(ms).toLocaleDateString("en-GB", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
}

const TITLES = { proforma: "Proforma invoice", receipt: "Receipt", void: "Void -- claim rejected" } as const;

export function InvoiceDocument({ claimId }: { claimId: string }) {
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [error, setError] = useState<{ status: number; text: string } | null>(null);

  useEffect(() => {
    billing
      .invoice(claimId)
      .then(setInvoice)
      .catch((cause: unknown) => {
        const message = cause instanceof Error ? cause.message : "Could not load this document.";
        const status = /401|sign in|unauthori/i.test(message) ? 401 : /404|not found/i.test(message) ? 404 : 0;
        setError({ status, text: message });
      });
  }, [claimId]);

  if (error) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16 text-sm text-muted">
        {error.status === 401 ? (
          <p>
            This document belongs to a signed-in account.{" "}
            <Link className="underline underline-offset-2" href="/">
              Sign in
            </Link>{" "}
            and open it again from your dashboard.
          </p>
        ) : (
          <p>No such document on this account. {error.text}</p>
        )}
      </main>
    );
  }
  if (!invoice) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16 text-sm text-muted" aria-busy>
        Loading…
      </main>
    );
  }

  const title = TITLES[invoice.kind];
  const paid = invoice.kind === "receipt";

  return (
    <main className="mx-auto max-w-2xl px-6 py-10 text-ink print:max-w-none print:px-0 print:py-0">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Link href="/" className="text-xs text-muted underline-offset-2 hover:underline">
          ← Dashboard
        </Link>
        <Button type="button" size="sm" onClick={() => window.print()}>
          Print / save as PDF
        </Button>
      </div>

      <article className="rounded-lg border border-line bg-white p-8 shadow-sm print:border-0 print:p-0 print:shadow-none">
        <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-medium tracking-widest text-muted uppercase">{title}</div>
            <h1 className="mt-1 font-mono text-lg font-semibold">{invoice.number}</h1>
          </div>
          <div className="text-right text-sm">
            <div className="font-semibold">{invoice.seller.name}</div>
            {invoice.seller.address && <div className="whitespace-pre-line text-muted">{invoice.seller.address}</div>}
            {invoice.seller.tax_id && <div className="font-mono text-xs text-muted">Tax ID {invoice.seller.tax_id}</div>}
          </div>
        </header>

        <dl className="mb-8 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
          <dt className="text-muted">Issued</dt>
          <dd>{date(invoice.issued_at)}</dd>
          <dt className="text-muted">{paid ? "Payment verified" : "Status"}</dt>
          <dd className={paid ? "font-medium text-emerald-700" : ""}>
            {paid && invoice.paid_at ? date(invoice.paid_at) : invoice.status}
          </dd>
          <dt className="text-muted">Billed to</dt>
          <dd className="col-span-1 break-all sm:col-span-3">{invoice.buyer_email}</dd>
          <dt className="text-muted">Method</dt>
          <dd>{invoice.method === "upi" ? "UPI" : "International bank wire (SWIFT)"}</dd>
          <dt className="text-muted">Reference</dt>
          <dd className="font-mono break-all">{invoice.reference}</dd>
        </dl>

        <table className="mb-6 w-full text-left text-sm">
          <thead className="border-b border-line text-xs text-muted">
            <tr>
              <th className="py-2 font-medium">Description</th>
              <th className="py-2 text-right font-medium">Qty</th>
              <th className="py-2 text-right font-medium">Unit</th>
              <th className="py-2 text-right font-medium">Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-line">
              <td className="py-3">{invoice.line.description}</td>
              <td className="py-3 text-right font-mono tabular-nums">{invoice.line.quantity}</td>
              <td className="py-3 text-right font-mono tabular-nums">{money(invoice.line.currency, invoice.line.unit_amount)}</td>
              <td className="py-3 text-right font-mono tabular-nums">{money(invoice.line.currency, invoice.line.amount)}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={3} className="py-3 text-right font-medium">
                {paid ? "Total paid" : "Total due"}
              </td>
              <td className="py-3 text-right font-mono text-base font-semibold tabular-nums">
                {money(invoice.line.currency, invoice.line.amount)} {invoice.line.currency}
              </td>
            </tr>
          </tfoot>
        </table>

        <div className="space-y-2 text-xs leading-relaxed text-muted">
          {invoice.kind === "proforma" && (
            <p>
              Pay by {invoice.method === "upi" ? "UPI" : "bank wire"} using the payee details emailed to{" "}
              {invoice.buyer_email} from the dashboard, and quote reference{" "}
              <span className="font-mono text-ink">{invoice.reference}</span> on the transfer.
              {invoice.method === "wire" && " Send with the OUR charge code so the full amount arrives."} This
              document becomes the receipt once the payment is verified.
            </p>
          )}
          {paid && <p>Payment received and verified by hand on the date shown. Thank you.</p>}
          {invoice.kind === "void" && <p>This claim was rejected; no payment was matched to it and nothing is owed.</p>}
          <p>
            Issued by {invoice.seller.name} · www.nanoneuron.ai · questions to the founder by replying to any email
            from us.
          </p>
        </div>
      </article>
    </main>
  );
}
