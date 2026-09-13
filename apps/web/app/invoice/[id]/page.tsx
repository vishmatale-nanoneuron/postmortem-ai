import type { Metadata } from "next";
import { InvoiceDocument } from "./invoice-document";

// One printable document per payment claim: a proforma invoice while the
// claim is pending (what a finance team needs to raise a wire), a receipt
// once the founder has verified the payment (what a buyer needs to expense
// it). The data is fetched client-side with the session cookie; nothing
// about a claim is in the HTML, and the page is never indexed.
export const metadata: Metadata = {
  title: "Invoice",
  robots: { index: false, follow: false },
};

export default async function InvoicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <InvoiceDocument claimId={id} />;
}
