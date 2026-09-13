"use client";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// Shared between the signed-out front door (workspace.tsx), the signed-in
// workspace and the founder dashboard, which are split into separately
// loaded modules so a visitor downloads only the part they can see.


// Used as an override on shadcn's <Card>, not a standalone className --
// Card's own defaults (flex flex-col + gap-(--card-spacing), ring-1
// ring-foreground/10, text-card-foreground, py-(--card-spacing)) are all
// shadcn's own theme tokens/layout, tuned for shadcn's default palette,
// not this app's own ink/paper/line/muted design system. Every one of
// those is explicitly neutralized here so wrapping the existing plain
// block sections in a real <Card> doesn't change their layout or colors
// at all -- block+gap-0 cancels the flex/gap, ring-0 removes the added
// ring border, text-ink matches this app's own body text color.
export const card =
  "block gap-0 animate-in fade-in slide-in-from-bottom-1 rounded-lg border border-line bg-white p-4 py-4 text-ink shadow-sm ring-0 duration-500 mb-4";
export const fieldLabel = "block text-xs font-medium text-muted mb-1";
export const fieldInput =
  "w-full rounded-md border border-line px-3 py-2 mb-3 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";

const CURRENCY_SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", GBP: "£", EUR: "€" };
export function currencySymbol(currency: string): string {
  return CURRENCY_SYMBOLS[currency] ?? `${currency} `;
}

export const POLL_INTERVAL_MS = 20_000;

// The polling above was already keeping data live every 20s, but with no
// visible sign of it -- a user watching the screen had no way to tell
// whether it was current or stale. Recomputed at render time (no separate
// ticking timer needed): the poll cycle and any user action already
// re-render this component often enough to keep the text reasonably fresh.

export function timeAgo(timestampMs: number): string {
  const seconds = Math.max(0, Math.round((Date.now() - timestampMs) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  return `${minutes}m ago`;
}

// Mean-time-to-resolve, formatted for a human -- a real duration computed
// from real created_at/updated_at timestamps (see postmortems.py's own
// comment on resolution_ms for the one honest limitation: a reopened-then-
// re-resolved incident shows only its latest resolution span). Coarsest
// unit only (days OR hours OR minutes), matching timeAgo's own style
// above rather than a full "1d 4h 12m" breakdown nobody needs at a glance.
export function formatDuration(ms: number): string {
  const minutes = Math.round(ms / 60_000);
  if (minutes < 60) return `${Math.max(minutes, 1)}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  return `${days}d`;
}


const ACTION_LABELS: Record<string, string> = {
  incident_created: "Incident created",
  status_changed: "Status changed",
  postmortem_published: "Postmortem published",
  data_exported: "Data exported",
};


// agent_<tool_name>[_denied|_failed] is the shape every MCP tool call logs
// under (see mcp_server.py's _audited) -- humanized here rather than
// hand-listing one label per tool (14 tools today, and growing), which
// would silently go stale the moment a new tool is added. Falls through
// to the raw action string for anything that matches neither this nor
// ACTION_LABELS, same as before this feature existed.

export function formatActivityAction(action: string): string {
  if (action in ACTION_LABELS) return ACTION_LABELS[action];
  const match = /^agent_(.+?)(_denied|_failed)?$/.exec(action);
  if (!match) return action;
  const [, toolName, outcome] = match;
  const readable = toolName.replaceAll("_", " ");
  const capitalized = readable.charAt(0).toUpperCase() + readable.slice(1);
  if (outcome === "_denied") return `${capitalized} — denied`;
  if (outcome === "_failed") return `${capitalized} — failed`;
  return capitalized;
}

export function AgentSourceBadge() {
  return (
    <span
      className="mr-1.5 rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent"
      title="Taken by an AI agent via MCP, not a browser session"
    >
      AI agent
    </span>
  );
}

export function ActivityLogRow({
  action,
  detail,
  source,
  createdAt,
  clientEmail,
}: {
  action: string;
  detail: string | null;
  source: string;
  createdAt: number;
  // Only passed by AgentActivityPanel -- ActivityLogPanel's rows are
  // always the viewer's own account, so naming it again would be noise.
  clientEmail?: string;
}) {
  return (
    <li className="flex flex-wrap justify-between gap-x-3 rounded-md bg-paper px-3 py-1.5 text-xs">
      <span>
        {source === "mcp_agent" && <AgentSourceBadge />}
        {clientEmail && <span className="font-medium">{clientEmail} -- </span>}
        {formatActivityAction(action)}
        {detail && <span className="text-muted"> -- {detail}</span>}
      </span>
      <span className="text-muted">{new Date(createdAt).toLocaleString()}</span>
    </li>
  );
}


export function DashboardSkeleton({ tiles = 4 }: { tiles?: number }) {
  return (
    <Card className={card}>
      <Skeleton className="mb-3 h-5 w-40 bg-paper" />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: tiles }).map((_, i) => (
          <Skeleton key={i} className="h-14 rounded-md bg-paper" />
        ))}
      </div>
    </Card>
  );
}
