"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { TEMPLATE_MARKDOWN } from "./template-markdown";

// The one interactive element on an otherwise static page, so the page
// itself can stay a server component. Same clipboard handling as
// workspace.tsx's CopyField: a denied clipboard is not an error, the text
// is still on the page to select by hand.
export function CopyTemplateButton() {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(TEMPLATE_MARKDOWN);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied (permissions, non-HTTPS context).
    }
  }
  return (
    <Button variant="line" size="app" type="button" onClick={() => void copy()} aria-live="polite">
      {copied ? "Copied" : "Copy as Markdown"}
    </Button>
  );
}
