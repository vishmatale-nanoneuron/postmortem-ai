import type { Metadata } from "next";
import FounderAuth from "./founder-auth";

// Not linked from the public site and excluded from search indexing --
// not real security on its own (the URL still works if guessed/shared),
// but there's no reason to make it discoverable either.
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function FounderPage() {
  return <FounderAuth />;
}
