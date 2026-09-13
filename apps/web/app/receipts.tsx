import Link from "next/link";
import type { Claim } from "./api";

// Every approved claim has a receipt (a proforma invoice that became one
// when the founder verified the payment). Listed under the buy card so a
// buyer can find the document to expense without asking.
export function Receipts({ claims }: { claims: Claim[] }) {
  const approved = claims.filter((claim) => claim.status === "approved");
  if (approved.length === 0) return null;
  return (
    <p className="mt-3 text-xs text-muted">
      Receipts:{" "}
      {approved.map((claim, index) => (
        <span key={claim.id}>
          {index > 0 && " · "}
          <Link className="underline underline-offset-2" href={`/invoice/${claim.id}`} target="_blank" rel="noopener">
            {new Date(claim.created_at).toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" })}
            {" "}
            {claim.currency} {claim.amount.toLocaleString("en-US")}
          </Link>
        </span>
      ))}
    </p>
  );
}
