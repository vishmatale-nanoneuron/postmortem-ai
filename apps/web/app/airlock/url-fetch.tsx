"use client";

import * as React from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { airlockProxyFetch, type AirlockProxyFetch } from "../api";
import { auth, type AuthUser } from "../auth";
import { describeFailure } from "./playground";

// The proxy mode, live: paste a URL, Airlock fetches it (under the
// server-side request forgery rules in app/airlock/proxy.py), scans what
// came back under your policy, and shows the page text only if the
// verdict allows it. Two credits from the signed-in account, like the API.

const VERDICT_STYLES = {
  block: "bg-red-600 text-white",
  flag: "bg-amber-500 text-white",
  allow: "bg-emerald-600 text-white",
} as const;

const SAMPLE_URLS = [
  { label: "A public page", url: "https://www.nanoneuron.ai/airlock" },
  { label: "Cloud metadata (refused)", url: "http://169.254.169.254/latest/meta-data/" },
  { label: "Localhost (refused)", url: "http://localhost:8080/admin" },
];

export function UrlFetch({ credits }: { credits: number }) {
  const [url, setUrl] = React.useState(SAMPLE_URLS[0]!.url);
  const [deep, setDeep] = React.useState(false);
  const [result, setResult] = React.useState<AirlockProxyFetch | null>(null);
  const [error, setError] = React.useState<ReturnType<typeof describeFailure> | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [user, setUser] = React.useState<AuthUser | null | false>(null);

  React.useEffect(() => {
    auth
      .checkSession()
      .then((u) => setUser(u ?? false))
      .catch(() => setUser(false));
  }, []);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await airlockProxyFetch(url.trim(), deep));
    } catch (cause) {
      setResult(null);
      setError(describeFailure(cause));
    } finally {
      setBusy(false);
    }
  }

  if (user === false) {
    return (
      <p className="rounded-md border border-line bg-paper px-4 py-3 text-sm text-muted">
        Proxy fetch uses the same paid balance as the scanner above.{" "}
        <Link href="/" className="underline underline-offset-2">
          Sign in
        </Link>{" "}
        to try it on a URL.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {SAMPLE_URLS.map((sample) => (
          <button
            key={sample.url}
            type="button"
            onClick={() => {
              setUrl(sample.url);
              setResult(null);
              setError(null);
            }}
            className={cn(
              "rounded-full border border-line px-2.5 py-1 text-xs text-muted transition-colors",
              "hover:border-ink/30 hover:text-ink",
              url === sample.url && "border-ink/40 bg-paper text-ink",
            )}
          >
            {sample.label}
          </button>
        ))}
      </div>

      <label className="sr-only" htmlFor="airlock-url-input">
        URL to fetch and scan
      </label>
      <input
        id="airlock-url-input"
        type="url"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        maxLength={2048}
        spellCheck={false}
        placeholder="https://"
        className="w-full rounded-md border border-line bg-white px-3 py-2 font-mono text-[12.5px] text-ink outline-none focus:border-accent"
      />

      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" size="app" onClick={() => void run()} disabled={busy || url.trim().length < 8}>
          {busy ? "Fetching…" : `Fetch & scan it (${credits + (deep ? 4 : 0)} credits)`}
        </Button>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} />
          Deep scan
        </label>
        <span className="text-xs text-muted">
          Airlock makes the request from its own address, sends nothing of yours, and refuses anything that is not
          the public internet.
        </span>
      </div>

      {error && (
        <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
          <span className="mr-1.5 rounded bg-red-600 px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-wide text-white uppercase">
            block
          </span>
          {error.text}{" "}
          {error.next === "sign-in" && (
            <Link className="underline underline-offset-2" href="/">
              Sign in
            </Link>
          )}
          {error.next === "buy" && (
            <Link className="underline underline-offset-2" href="/#client-airlock">
              Buy a pack from your dashboard
            </Link>
          )}
        </p>
      )}

      {result && (
        <div className="rounded-md border border-line bg-paper p-3.5" role="status">
          <div className="flex flex-wrap items-center gap-2.5">
            <span
              className={cn(
                "rounded px-2 py-0.5 font-mono text-[11px] font-semibold tracking-wide uppercase",
                VERDICT_STYLES[result.verdict],
              )}
            >
              {result.verdict}
            </span>
            <span className="font-mono text-sm text-ink">{result.score.toFixed(2)}</span>
            <span className="text-xs text-muted">
              {result.stage === "egress" ? "refused before fetching" : "page scanned"}
              {result.http_status !== null && ` · HTTP ${result.http_status}`}
              {result.content_type && ` · ${result.content_type}`}
              {result.hops > 0 && ` · ${result.hops} redirect${result.hops > 1 ? "s" : ""}`}
              {" · "}
              {result.content_bytes.toLocaleString("en-US")} bytes · fetch {result.fetch_ms} ms · total{" "}
              {result.latency_ms} ms
              {result.credits_remaining !== null && ` · ${result.credits_remaining.toLocaleString("en-US")} credits left`}
            </span>
          </div>
          {result.final_url && result.final_url !== result.url && (
            <p className="mt-1.5 font-mono text-[11.5px] break-all text-muted">→ {result.final_url}</p>
          )}

          {result.reasons.length > 0 && (
            <ul className="mt-2.5 space-y-1">
              {result.reasons.map((reason) => (
                <li key={reason} className="text-xs text-ink">
                  {reason}
                </li>
              ))}
            </ul>
          )}

          {result.matches.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {result.matches.map((match) => (
                <li key={match.rule_id} className="flex flex-wrap items-baseline gap-2">
                  <span className="rounded bg-red-50 px-1.5 py-0.5 font-mono text-[11px] font-medium text-red-700">
                    {match.rule_id}
                  </span>
                  <span className="text-xs text-muted">{match.family.replace(/_/g, " ")}</span>
                  <span className="text-xs text-ink">{match.description}</span>
                  <span className="ml-auto font-mono text-[11px] text-muted">w {match.weight.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          )}

          {result.semantic && (
            <p className="mt-2.5 text-xs text-muted">
              <span className="font-medium text-ink">Gemini:</span>{" "}
              {result.semantic.status === "ok"
                ? `${result.semantic.injection ? "injection" : "not an injection"} · confidence ${Number(result.semantic.confidence).toFixed(2)} · weight ${Number(result.semantic.weight).toFixed(2)}`
                : result.semantic.status === "skipped"
                  ? "not asked — the rules already block; the extra credits were refunded"
                  : "second opinion unavailable — the extra credits were refunded"}
            </p>
          )}

          {result.content !== null ? (
            <div className="mt-3 border-t border-line pt-2.5">
              <p className="mb-1 text-xs font-medium text-ink">
                What your agent would receive
                {result.verdict === "flag" && " (sanitized)"}
                {result.truncated && " · truncated"}
              </p>
              <pre className="max-h-48 overflow-auto rounded-md border border-line bg-white p-2 font-mono text-[11.5px] leading-relaxed break-words whitespace-pre-wrap text-ink">
                {result.content}
              </pre>
            </div>
          ) : (
            <p className="mt-3 border-t border-line pt-2.5 text-xs text-muted">
              Nothing is handed over on a block. The agent never saw this page.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
