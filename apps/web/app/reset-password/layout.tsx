import type { Metadata } from "next";

// Every URL under this route embeds a real (short-lived, single-use)
// reset token in the query string -- never meant to be indexed or
// crawled, unlike the marketing/docs pages this app otherwise wants found.
export const metadata: Metadata = {
  title: "Reset password",
  robots: { index: false, follow: false },
};

export default function ResetPasswordLayout({ children }: { children: React.ReactNode }) {
  return children;
}
