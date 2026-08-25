import type { Metadata } from "next";
import FounderAuth from "./founder-auth";

// Not linked from the public site and excluded from search indexing. Real
// access control lives in middleware.ts now (a 404 for anyone without the
// FOUNDER_ACCESS_KEY) -- this metadata is defense-in-depth against search
// engines, not the actual gate.
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function FounderPage() {
  return <FounderAuth />;
}
